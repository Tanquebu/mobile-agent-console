import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

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
    def __init__(self, storage_root: str, prompt_root: str, max_bytes: int) -> None:
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
        attachment = Attachment(
            id=attachment_id,
            session_id=session_id,
            name=name,
            media_type=normalized_media_type,
            size=len(content),
            path=str(prompt_path),
        )
        metadata_path = session_dir / f"{attachment_id}.json"
        metadata_path.write_text(json.dumps(asdict(attachment)), encoding="utf-8")
        metadata_path.chmod(0o600)
        return attachment

    def get(self, session_id: str, attachment_id: str) -> Attachment:
        if not ATTACHMENT_ID.fullmatch(attachment_id):
            raise AttachmentError("Invalid attachment id")
        metadata_path = self.storage_root / session_id / f"{attachment_id}.json"
        try:
            data = json.loads(metadata_path.read_text(encoding="utf-8"))
            attachment = Attachment(**data)
        except (FileNotFoundError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AttachmentError("Attachment not found") from exc
        if attachment.session_id != session_id or attachment.id != attachment_id:
            raise AttachmentError("Attachment does not belong to this session")
        stored_path = self.storage_root / session_id / Path(attachment.path).name
        if not stored_path.is_file():
            raise AttachmentError("Attachment not found")
        return attachment

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
        metadata_path = session_dir / f"{attachment_id}.json"
        stored_path.unlink(missing_ok=True)
        metadata_path.unlink(missing_ok=True)
        try:
            session_dir.rmdir()
        except OSError:
            pass

    def cleanup_expired(self, ttl_seconds: int, now: float | None = None) -> int:
        cutoff = (now if now is not None else time.time()) - ttl_seconds
        removed = 0
        if not self.storage_root.exists():
            return removed
        for session_dir in self.storage_root.iterdir():
            if not session_dir.is_dir():
                continue
            for path in session_dir.iterdir():
                try:
                    if path.is_file() and path.stat().st_mtime < cutoff:
                        path.unlink()
                        removed += 1
                except FileNotFoundError:
                    continue
            try:
                session_dir.rmdir()
            except OSError:
                pass
        return removed
