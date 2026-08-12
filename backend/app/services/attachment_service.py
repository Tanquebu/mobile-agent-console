import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from ..models import Attachment as AttachmentRow

ATTACHMENT_ID = re.compile(r"^[a-f0-9]{32}$")
TEXT_MEDIA_TYPES = {
    "application/json": ".json",
    "application/xml": ".xml",
    "text/csv": ".csv",
    "text/markdown": ".md",
    "text/plain": ".txt",
    "text/xml": ".xml",
}
SIGNATURE_MEDIA_TYPES = {
    "application/pdf": (b"%PDF-", ".pdf"),
    "image/jpeg": (b"\xff\xd8\xff", ".jpg"),
    "image/png": (b"\x89PNG\r\n\x1a\n", ".png"),
}
IMAGE_MEDIA_TYPES = {"image/png", "image/jpeg", "image/webp"}
THUMBNAIL_MAX_SIZE = (256, 256)


def is_mp3(prefix: bytes) -> bool:
    if prefix.startswith(b"ID3"):
        return True
    if len(prefix) < 4 or prefix[0] != 0xFF or prefix[1] & 0xE0 != 0xE0:
        return False
    version = (prefix[1] >> 3) & 0x03
    layer = (prefix[1] >> 1) & 0x03
    bitrate = (prefix[2] >> 4) & 0x0F
    sample_rate = (prefix[2] >> 2) & 0x03
    return version != 0x01 and layer != 0 and bitrate not in (0, 0x0F) and sample_rate != 0x03


class AttachmentError(ValueError):
    pass


@dataclass(frozen=True)
class Attachment:
    id: str
    session_id: str
    name: str
    media_type: str
    size: int
    path: str


class AttachmentService:
    def __init__(
        self,
        engine,
        storage_root: str,
        prompt_root: str,
        max_bytes: int,
        max_session_bytes: int,
    ) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)
        self.storage_root = Path(storage_root).resolve()
        self.prompt_root = Path(prompt_root)
        self.max_bytes = max_bytes
        self.max_session_bytes = max_session_bytes

    def session_total_bytes(self, session_id: str) -> int:
        with self._sessions() as session:
            return session.scalar(
                select(func.coalesce(func.sum(AttachmentRow.size), 0)).where(
                    AttachmentRow.session_id == session_id
                )
            )

    @staticmethod
    def validate_name(name: str) -> str:
        if not name or len(name) > 255 or Path(name).name != name:
            raise AttachmentError("Invalid attachment name")
        if any(ord(character) < 32 or ord(character) == 127 for character in name):
            raise AttachmentError("Invalid attachment name")
        return name

    @staticmethod
    def extension_for(media_type: str, prefix: bytes) -> str:
        normalized = media_type.split(";", 1)[0].strip().lower()
        if normalized in TEXT_MEDIA_TYPES:
            try:
                prefix.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise AttachmentError("Text attachments must be UTF-8") from exc
            return TEXT_MEDIA_TYPES[normalized]
        if normalized == "image/webp":
            if len(prefix) < 12 or prefix[:4] != b"RIFF" or prefix[8:12] != b"WEBP":
                raise AttachmentError("Attachment content does not match its media type")
            return ".webp"
        if normalized in {"audio/mpeg", "audio/mp3"}:
            if not is_mp3(prefix):
                raise AttachmentError("Attachment content does not match its media type")
            return ".mp3"
        signature = SIGNATURE_MEDIA_TYPES.get(normalized)
        if not signature:
            raise AttachmentError("Attachment media type is not allowed")
        expected, extension = signature
        if not prefix.startswith(expected):
            raise AttachmentError("Attachment content does not match its media type")
        return extension

    def _thumbnail_path(self, session_id: str, attachment_id: str) -> Path:
        return self.storage_root / session_id / f"{attachment_id}.thumb.jpg"

    def _write_thumbnail(
        self, session_dir: Path, attachment_id: str, media_type: str, content: bytes
    ) -> None:
        if media_type not in IMAGE_MEDIA_TYPES:
            return
        try:
            with Image.open(BytesIO(content)) as image:
                image.thumbnail(THUMBNAIL_MAX_SIZE)
                buffer = BytesIO()
                image.convert("RGB").save(buffer, format="JPEG", quality=80)
        except (OSError, UnidentifiedImageError):
            # anteprima best-effort: un'immagine non decodificabile da Pillow
            # non deve bloccare l'upload, solo lasciare il file senza thumbnail.
            return
        thumb_path = session_dir / f"{attachment_id}.thumb.jpg"
        temporary_path = session_dir / f".{attachment_id}.thumb.part"
        temporary_path.write_bytes(buffer.getvalue())
        temporary_path.chmod(0o600)
        temporary_path.replace(thumb_path)

    def preview_path(self, session_id: str, attachment_id: str) -> Path:
        self.get(session_id, attachment_id)
        thumb_path = self._thumbnail_path(session_id, attachment_id)
        if not thumb_path.is_file():
            raise AttachmentError("Preview not available")
        return thumb_path

    def create(
        self,
        session_id: str,
        name: str,
        media_type: str,
        content: bytes,
    ) -> Attachment:
        name = self.validate_name(name)
        if not content:
            raise AttachmentError("Attachment is empty")
        if len(content) > self.max_bytes:
            raise AttachmentError("Attachment is too large")
        if self.session_total_bytes(session_id) + len(content) > self.max_session_bytes:
            raise AttachmentError("Attachment storage quota exceeded for this session")
        normalized_media_type = media_type.split(";", 1)[0].strip().lower()
        extension = self.extension_for(normalized_media_type, content)
        content_hash = hashlib.sha256(content).hexdigest()
        attachment_id = uuid4().hex
        session_dir = self.storage_root / session_id
        session_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

        with self._sessions() as session:
            duplicate = session.scalar(
                select(AttachmentRow)
                .where(
                    AttachmentRow.session_id == session_id,
                    AttachmentRow.content_hash == content_hash,
                )
                .limit(1)
            )
        if duplicate is not None:
            # Stesso contenuto già presente in questa sessione: riusa il file
            # fisico esistente invece di riscriverlo, una nuova riga di
            # metadati referenzia lo stesso path.
            stored_name = Path(duplicate.path).name
        else:
            stored_path = session_dir / f"{attachment_id}{extension}"
            temporary_path = session_dir / f".{attachment_id}.part"
            temporary_path.write_bytes(content)
            temporary_path.chmod(0o600)
            temporary_path.replace(stored_path)
            stored_name = stored_path.name
        self._write_thumbnail(session_dir, attachment_id, normalized_media_type, content)
        prompt_path = self.prompt_root / session_id / stored_name
        row = AttachmentRow(
            id=attachment_id,
            session_id=session_id,
            name=name,
            media_type=normalized_media_type,
            size=len(content),
            path=str(prompt_path),
            content_hash=content_hash,
            created_at=datetime.now(UTC),
        )
        with self._sessions.begin() as session:
            session.add(row)
        return Attachment(
            id=row.id,
            session_id=row.session_id,
            name=row.name,
            media_type=row.media_type,
            size=row.size,
            path=row.path,
        )

    def get(self, session_id: str, attachment_id: str) -> Attachment:
        if not ATTACHMENT_ID.fullmatch(attachment_id):
            raise AttachmentError("Invalid attachment id")
        with self._sessions() as session:
            row = session.get(AttachmentRow, attachment_id)
        if row is None or row.session_id != session_id:
            raise AttachmentError("Attachment not found")
        stored_path = self.storage_root / session_id / Path(row.path).name
        if not stored_path.is_file():
            raise AttachmentError("Attachment not found")
        return Attachment(
            id=row.id,
            session_id=row.session_id,
            name=row.name,
            media_type=row.media_type,
            size=row.size,
            path=row.path,
        )

    def prompt_suffix(self, session_id: str, attachment_ids: list[str]) -> str:
        if len(set(attachment_ids)) != len(attachment_ids):
            raise AttachmentError("Duplicate attachment ids")
        attachments = [self.get(session_id, item) for item in attachment_ids]
        if not attachments:
            return ""
        lines = ["", "", "Allegati disponibili:"]
        for attachment in attachments:
            display_name = json.dumps(attachment.name, ensure_ascii=False)
            lines.append(f"- {display_name}: {attachment.path}")
        return "\n".join(lines)

    @staticmethod
    def _other_references(session, row: AttachmentRow) -> int:
        if not row.content_hash:
            return 0
        return session.scalar(
            select(func.count())
            .select_from(AttachmentRow)
            .where(
                AttachmentRow.session_id == row.session_id,
                AttachmentRow.content_hash == row.content_hash,
                AttachmentRow.id != row.id,
            )
        )

    def delete(self, session_id: str, attachment_id: str) -> None:
        attachment = self.get(session_id, attachment_id)
        session_dir = self.storage_root / session_id
        with self._sessions.begin() as session:
            row = session.get(AttachmentRow, attachment_id)
            if row is not None:
                other_refs = self._other_references(session, row)
                session.delete(row)
            else:
                other_refs = 0
        if not other_refs:
            stored_path = session_dir / Path(attachment.path).name
            stored_path.unlink(missing_ok=True)
        self._thumbnail_path(session_id, attachment_id).unlink(missing_ok=True)
        try:
            session_dir.rmdir()
        except OSError:
            pass

    def delete_all_for_session(self, session_id: str) -> int:
        # Retention legata al ciclo di vita: terminare/archiviare una sessione
        # libera l'id tmux numerico, che tmux può riassegnare a una sessione
        # futura scollegata — lasciare allegati sotto il vecchio path
        # rischierebbe di associarli implicitamente alla nuova sessione.
        session_dir = self.storage_root / session_id
        with self._sessions.begin() as session:
            rows = list(
                session.scalars(select(AttachmentRow).where(AttachmentRow.session_id == session_id))
            )
            for row in rows:
                session.delete(row)
        seen_files: set[str] = set()
        for row in rows:
            stored_name = Path(row.path).name
            if stored_name not in seen_files:
                (session_dir / stored_name).unlink(missing_ok=True)
                seen_files.add(stored_name)
            self._thumbnail_path(session_id, row.id).unlink(missing_ok=True)
        try:
            session_dir.rmdir()
        except OSError:
            pass
        return len(rows)

    def cleanup_expired(self, ttl_seconds: int, now: float | None = None) -> int:
        cutoff = datetime.fromtimestamp((now if now is not None else time.time()) - ttl_seconds, UTC)
        removed = 0
        with self._sessions.begin() as session:
            expired = list(
                session.scalars(select(AttachmentRow).where(AttachmentRow.created_at < cutoff))
            )
            for row in expired:
                other_refs = self._other_references(session, row)
                if not other_refs:
                    stored_path = self.storage_root / row.session_id / Path(row.path).name
                    stored_path.unlink(missing_ok=True)
                self._thumbnail_path(row.session_id, row.id).unlink(missing_ok=True)
                session.delete(row)
                removed += 1
        if not self.storage_root.exists():
            return removed
        for session_dir in self.storage_root.iterdir():
            try:
                session_dir.rmdir()
            except OSError:
                pass
        return removed
