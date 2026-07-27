import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
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
    def __init__(self, engine, storage_root: str, prompt_root: str, max_bytes: int) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)
        self.storage_root = Path(storage_root).resolve()
        self.prompt_root = Path(prompt_root)
        self.max_bytes = max_bytes

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
        signature = SIGNATURE_MEDIA_TYPES.get(normalized)
        if not signature:
            raise AttachmentError("Attachment media type is not allowed")
        expected, extension = signature
        if not prefix.startswith(expected):
            raise AttachmentError("Attachment content does not match its media type")
        return extension

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
        normalized_media_type = media_type.split(";", 1)[0].strip().lower()
        extension = self.extension_for(normalized_media_type, content)
        attachment_id = uuid4().hex
        session_dir = self.storage_root / session_id
        session_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        stored_path = session_dir / f"{attachment_id}{extension}"
        temporary_path = session_dir / f".{attachment_id}.part"
        temporary_path.write_bytes(content)
        temporary_path.chmod(0o600)
        temporary_path.replace(stored_path)
        prompt_path = self.prompt_root / session_id / stored_path.name
        row = AttachmentRow(
            id=attachment_id,
            session_id=session_id,
            name=name,
            media_type=normalized_media_type,
            size=len(content),
            path=str(prompt_path),
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

    def delete(self, session_id: str, attachment_id: str) -> None:
        attachment = self.get(session_id, attachment_id)
        session_dir = self.storage_root / session_id
        stored_path = session_dir / Path(attachment.path).name
        stored_path.unlink(missing_ok=True)
        with self._sessions.begin() as session:
            row = session.get(AttachmentRow, attachment_id)
            if row is not None:
                session.delete(row)
        try:
            session_dir.rmdir()
        except OSError:
            pass

    def cleanup_expired(self, ttl_seconds: int, now: float | None = None) -> int:
        cutoff = datetime.fromtimestamp((now if now is not None else time.time()) - ttl_seconds, UTC)
        removed = 0
        with self._sessions.begin() as session:
            expired = list(
                session.scalars(select(AttachmentRow).where(AttachmentRow.created_at < cutoff))
            )
            for row in expired:
                stored_path = self.storage_root / row.session_id / Path(row.path).name
                stored_path.unlink(missing_ok=True)
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
