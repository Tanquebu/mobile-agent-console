import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

SNAPSHOT_ID = re.compile(r"^[a-f0-9]{32}$")
SNAPSHOT_MODES = {"shell", "codex", "claude", "manual"}
SNAPSHOT_LIMIT = 100


class SnapshotError(ValueError):
    pass


@dataclass(frozen=True)
class SnapshotSession:
    name: str
    directory: str
    mode: str
    observed_command: str


@dataclass(frozen=True)
class Snapshot:
    id: str
    name: str
    created_at: datetime
    sessions: list[SnapshotSession]


class SnapshotService:
    def __init__(self, storage_root: str) -> None:
        self.storage_root = Path(storage_root).resolve()

    @staticmethod
    def validate_name(name: str) -> str:
        normalized = name.strip()
        if not normalized or len(normalized) > 80:
            raise SnapshotError("Snapshot name must contain 1 to 80 characters")
        if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
            raise SnapshotError("Snapshot name contains invalid characters")
        return normalized

    @staticmethod
    def validate_sessions(sessions: list[SnapshotSession]) -> list[SnapshotSession]:
        if not sessions or len(sessions) > 100:
            raise SnapshotError("Snapshot must contain 1 to 100 sessions")
        for session in sessions:
            if session.mode not in SNAPSHOT_MODES:
                raise SnapshotError("Invalid snapshot restore mode")
        return sessions

    def _path(self, snapshot_id: str) -> Path:
        if not SNAPSHOT_ID.fullmatch(snapshot_id):
            raise SnapshotError("Invalid snapshot id")
        return self.storage_root / f"{snapshot_id}.json"

    @staticmethod
    def _decode(data: object) -> Snapshot:
        if not isinstance(data, dict):
            raise SnapshotError("Invalid snapshot metadata")
        try:
            sessions = [SnapshotSession(**item) for item in data["sessions"]]
            snapshot = Snapshot(
                id=data["id"],
                name=data["name"],
                created_at=datetime.fromisoformat(data["created_at"]),
                sessions=sessions,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SnapshotError("Invalid snapshot metadata") from exc
        if not SNAPSHOT_ID.fullmatch(snapshot.id):
            raise SnapshotError("Invalid snapshot metadata")
        SnapshotService.validate_name(snapshot.name)
        SnapshotService.validate_sessions(snapshot.sessions)
        return snapshot

    def list(self) -> list[Snapshot]:
        if not self.storage_root.exists():
            return []
        snapshots = []
        for path in self.storage_root.glob("*.json"):
            try:
                snapshots.append(self._decode(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError, SnapshotError):
                continue
        return sorted(snapshots, key=lambda item: item.created_at, reverse=True)

    def create(self, name: str, sessions: list[SnapshotSession]) -> Snapshot:
        name = self.validate_name(name)
        sessions = self.validate_sessions(sessions)
        if len(self.list()) >= SNAPSHOT_LIMIT:
            raise SnapshotError("Snapshot limit reached")
        snapshot = Snapshot(
            id=uuid4().hex,
            name=name,
            created_at=datetime.now(UTC),
            sessions=sessions,
        )
        self.storage_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self._path(snapshot.id)
        temporary_path = self.storage_root / f".{snapshot.id}.part"
        data = {
            "id": snapshot.id,
            "name": snapshot.name,
            "created_at": snapshot.created_at.isoformat(),
            "sessions": [
                {
                    "name": session.name,
                    "directory": session.directory,
                    "mode": session.mode,
                    "observed_command": session.observed_command,
                }
                for session in snapshot.sessions
            ],
        }
        temporary_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.chmod(0o600)
        temporary_path.replace(path)
        return snapshot

    def get(self, snapshot_id: str) -> Snapshot:
        path = self._path(snapshot_id)
        try:
            snapshot = self._decode(json.loads(path.read_text(encoding="utf-8")))
        except FileNotFoundError as exc:
            raise SnapshotError("Snapshot not found") from exc
        except (OSError, json.JSONDecodeError, SnapshotError) as exc:
            raise SnapshotError("Snapshot is invalid") from exc
        if snapshot.id != snapshot_id:
            raise SnapshotError("Snapshot id does not match its metadata")
        return snapshot

    def delete(self, snapshot_id: str) -> None:
        path = self._path(snapshot_id)
        if not path.is_file():
            raise SnapshotError("Snapshot not found")
        path.unlink()
