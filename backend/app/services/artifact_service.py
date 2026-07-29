import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .attachment_service import (
    SIGNATURE_MEDIA_TYPES,
    TEXT_MEDIA_TYPES,
    AttachmentError,
    AttachmentService,
)


class ArtifactError(ValueError):
    pass


@dataclass(frozen=True)
class Artifact:
    name: str
    media_type: str
    size: int
    modified_at: datetime


class ArtifactService:
    def __init__(self, storage_root: str, prompt_root: str, max_bytes: int) -> None:
        self.storage_root = Path(storage_root).resolve()
        self.prompt_root = Path(prompt_root)
        self.max_bytes = max_bytes

    @staticmethod
    def validate_name(name: str) -> str:
        try:
            return AttachmentService.validate_name(name)
        except AttachmentError as exc:
            raise ArtifactError(str(exc)) from exc

    def ensure_session_dir(self, session_id: str) -> Path:
        session_dir = self.storage_root / session_id
        session_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        return session_dir

    def prompt_path(self, session_id: str) -> str:
        return str(self.prompt_root / session_id)

    def _sniff(self, path: Path) -> str | None:
        try:
            with path.open("rb") as handle:
                prefix = handle.read(64)
        except OSError:
            return None
        for media_type, (signature, _extension) in SIGNATURE_MEDIA_TYPES.items():
            if prefix.startswith(signature):
                return media_type
        if len(prefix) >= 12 and prefix[:4] == b"RIFF" and prefix[8:12] == b"WEBP":
            return "image/webp"
        suffix = path.suffix.lower()
        for media_type, extension in TEXT_MEDIA_TYPES.items():
            if extension != suffix:
                continue
            try:
                content = path.read_bytes()
            except OSError:
                return None
            try:
                content.decode("utf-8")
            except UnicodeDecodeError:
                return None
            return media_type
        return None

    def _describe(self, entry: Path) -> Artifact | None:
        try:
            name = self.validate_name(entry.name)
        except ArtifactError:
            return None
        try:
            stat = entry.stat()
        except OSError:
            return None
        if not stat.st_size or stat.st_size > self.max_bytes:
            return None
        media_type = self._sniff(entry)
        if media_type is None:
            return None
        return Artifact(
            name=name,
            media_type=media_type,
            size=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime, UTC),
        )

    def list(self, session_id: str) -> list[Artifact]:
        session_dir = self.storage_root / session_id
        if not session_dir.is_dir():
            return []
        artifacts = []
        for entry in sorted(session_dir.iterdir()):
            if not entry.is_file():
                continue
            artifact = self._describe(entry)
            if artifact is not None:
                artifacts.append(artifact)
        return artifacts

    def get(self, session_id: str, name: str) -> Artifact:
        name = self.validate_name(name)
        session_dir = (self.storage_root / session_id).resolve()
        candidate = (session_dir / name).resolve()
        if candidate.parent != session_dir or not candidate.is_file():
            raise ArtifactError("Artifact not found")
        artifact = self._describe(candidate)
        if artifact is None:
            raise ArtifactError("Artifact not found")
        return artifact

    def delete_all_for_session(self, session_id: str) -> int:
        session_dir = self.storage_root / session_id
        if not session_dir.is_dir():
            return 0
        removed = sum(1 for entry in session_dir.iterdir() if entry.is_file())
        shutil.rmtree(session_dir, ignore_errors=True)
        return removed
