import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .attachment_service import SIGNATURE_MEDIA_TYPES, TEXT_MEDIA_TYPES, is_mp3, is_mp4

# M4A con un major brand esplicito: non basta l'estensione, perché artefatti e
# browser di directory espongono file prodotti da processi esterni. Tenere il
# riconoscimento separato evita anche di classificare come video un audio MP4.
M4A_MAJOR_BRANDS = frozenset({b"M4A "})

# Metadato di passaggio tra agente e modale di archiviazione. Non e' una
# consegna: resta escluso dall'elenco/download degli artefatti e viene copiato
# nel database soltanto dopo la revisione esplicita dell'utente.
ARCHIVE_SUMMARY_NAME = "archive-summary.md"
ARCHIVE_SUMMARY_MAX_BYTES = 8 * 1024
ARCHIVE_SUMMARY_MAX_CHARS = 2_000


def sniff_media_type(path: Path) -> str | None:
    """Tipo di media dedotto dal contenuto, non dall'estensione.

    Usato sia dagli artefatti di sessione sia dall'anteprima del browser di
    directory: un solo posto in cui si decide che cosa e' un mp4, altrimenti le
    due viste finiscono per non essere d'accordo.
    """
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
    if is_mp4(prefix):
        return "video/mp4"
    if (
        len(prefix) >= 12
        and prefix[4:8] == b"ftyp"
        and prefix[8:12] in M4A_MAJOR_BRANDS
    ):
        return "audio/mp4"
    if path.suffix.lower() == ".mp3" and is_mp3(prefix):
        return "audio/mpeg"
    suffix = path.suffix.lower()
    if suffix == ".htm":
        try:
            content = path.read_bytes()
        except OSError:
            return None
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            return None
        return "text/html"
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
        if not name or len(name) > 1024:
            raise ArtifactError("Invalid artifact name")
        if any(ord(character) < 32 or ord(character) == 127 for character in name):
            raise ArtifactError("Invalid artifact name")
        parts = name.replace("\\", "/").split("/")
        if any(part in ("", ".", "..") for part in parts):
            raise ArtifactError("Invalid artifact name")
        return "/".join(parts)

    def ensure_session_dir(self, session_id: str) -> Path:
        session_dir = self.storage_root / session_id
        session_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        return session_dir

    def prompt_path(self, session_id: str) -> str:
        return str(self.prompt_root / session_id)

    def _sniff(self, path: Path) -> str | None:
        return sniff_media_type(path)

    def _describe(self, entry: Path, relative_name: str) -> Artifact | None:
        try:
            name = self.validate_name(relative_name)
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

    def read_archive_summary(self, session_id: str) -> str | None:
        session_dir = (self.storage_root / session_id).resolve()
        candidate = (session_dir / ARCHIVE_SUMMARY_NAME).resolve()
        try:
            candidate.relative_to(session_dir)
        except ValueError:
            return None
        try:
            content = candidate.read_bytes()
        except OSError:
            return None
        if not content or len(content) > ARCHIVE_SUMMARY_MAX_BYTES:
            return None
        try:
            text = content.decode("utf-8").strip()
        except UnicodeDecodeError:
            return None
        if not text or any(
            (ord(character) < 32 and character not in {"\n", "\t"})
            or ord(character) == 127
            for character in text
        ):
            return None
        return text[:ARCHIVE_SUMMARY_MAX_CHARS]

    def list(self, session_id: str) -> list[Artifact]:
        session_dir = (self.storage_root / session_id).resolve()
        if not session_dir.is_dir():
            return []
        artifacts = []
        for entry in sorted(session_dir.rglob("*")):
            if not entry.is_file():
                continue
            try:
                rel_path = entry.relative_to(session_dir).as_posix()
            except ValueError:
                continue
            if rel_path == ARCHIVE_SUMMARY_NAME:
                continue
            artifact = self._describe(entry, rel_path)
            if artifact is not None:
                artifacts.append(artifact)
        return artifacts

    def get(self, session_id: str, name: str) -> Artifact:
        name = self.validate_name(name)
        if name == ARCHIVE_SUMMARY_NAME:
            raise ArtifactError("Artifact not found")
        session_dir = (self.storage_root / session_id).resolve()
        candidate = (session_dir / name).resolve()
        try:
            candidate.relative_to(session_dir)
        except ValueError:
            raise ArtifactError("Artifact not found")
        if not candidate.is_file():
            raise ArtifactError("Artifact not found")
        artifact = self._describe(candidate, name)
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

    def archive_for_session(self, session_id: str, archive_id: str) -> int:
        """Sposta la cartella artefatti nell'area di archivio."""
        session_dir = self.storage_root / session_id
        if not session_dir.is_dir():
            return 0
        archive_dir = self.storage_root / "_archived" / archive_id
        archive_dir.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        count = sum(1 for entry in session_dir.rglob("*") if entry.is_file())
        session_dir.rename(archive_dir)
        return count

    def restore_from_archive(self, archive_id: str, session_id: str) -> None:
        """Ripristina gli artefatti archiviati nella cartella della nuova sessione."""
        archive_dir = self.storage_root / "_archived" / archive_id
        if not archive_dir.is_dir():
            return
        target = self.storage_root / session_id
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        archive_dir.rename(target)
        # Rimuovi la directory _archived se vuota
        try:
            archive_dir.parent.rmdir()
        except OSError:
            pass

    def delete_archived(self, archive_id: str) -> None:
        """Cancella artefatti archiviati (su eliminazione archivio)."""
        archive_dir = self.storage_root / "_archived" / archive_id
        shutil.rmtree(archive_dir, ignore_errors=True)
        try:
            archive_dir.parent.rmdir()
        except OSError:
            pass
