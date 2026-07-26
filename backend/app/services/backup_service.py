import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

BACKUP_ID_LENGTH = 32


class BackupError(ValueError):
    pass


@dataclass(frozen=True)
class Backup:
    id: str
    created_at: datetime
    size: int
    sha256: str
    files: int


class BackupService:
    def __init__(
        self,
        storage_root: str,
        database_path: str,
        snapshots_root: str,
        retention: int = 10,
    ) -> None:
        self.storage_root = Path(storage_root).resolve()
        self.database_path = Path(database_path).resolve()
        self.snapshots_root = Path(snapshots_root).resolve()
        self.retention = retention

    def _paths(self, backup_id: str) -> tuple[Path, Path]:
        if len(backup_id) != BACKUP_ID_LENGTH or any(
            char not in "0123456789abcdef" for char in backup_id
        ):
            raise BackupError("Invalid backup id")
        return (
            self.storage_root / f"{backup_id}.zip",
            self.storage_root / f"{backup_id}.json",
        )

    def _prepare_root(self) -> None:
        self.storage_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.storage_root, 0o700)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _decode(self, path: Path) -> Backup:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            backup = Backup(
                id=data["id"],
                created_at=datetime.fromisoformat(data["created_at"]),
                size=int(data["size"]),
                sha256=data["sha256"],
                files=int(data["files"]),
            )
            archive, metadata = self._paths(backup.id)
            if metadata != path or not archive.is_file():
                raise BackupError("Invalid backup metadata")
            return backup
        except (KeyError, TypeError, ValueError, OSError) as exc:
            raise BackupError("Invalid backup metadata") from exc

    def list(self) -> list[Backup]:
        if not self.storage_root.is_dir():
            return []
        backups = []
        for path in self.storage_root.glob("*.json"):
            try:
                backups.append(self._decode(path))
            except BackupError:
                continue
        return sorted(backups, key=lambda item: item.created_at, reverse=True)

    def create(self) -> Backup:
        if not self.database_path.is_file():
            raise BackupError("Database file not found")
        self._prepare_root()
        backup_id = uuid4().hex
        archive_path, metadata_path = self._paths(backup_id)
        created_at = datetime.now(UTC)
        file_manifest: list[dict[str, str | int]] = []

        with tempfile.TemporaryDirectory(dir=self.storage_root) as temporary:
            temporary_root = Path(temporary)
            database_copy = temporary_root / "app.db"
            source = sqlite3.connect(f"file:{self.database_path}?mode=ro", uri=True)
            destination = sqlite3.connect(database_copy)
            try:
                source.backup(destination)
            finally:
                destination.close()
                source.close()

            sources = [(database_copy, "database/app.db")]
            if self.snapshots_root.is_dir():
                sources.extend(
                    (path, f"snapshots/{path.name}")
                    for path in sorted(self.snapshots_root.glob("*.json"))
                    if path.is_file()
                )
            for source_path, archive_name in sources:
                file_manifest.append(
                    {
                        "path": archive_name,
                        "size": source_path.stat().st_size,
                        "sha256": self._sha256(source_path),
                    }
                )
            manifest = {
                "format": 1,
                "created_at": created_at.isoformat(),
                "files": file_manifest,
            }
            part_path = temporary_root / "backup.zip"
            with zipfile.ZipFile(part_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for source_path, archive_name in sources:
                    archive.write(source_path, archive_name)
                archive.writestr("manifest.json", json.dumps(manifest, indent=2))
            os.chmod(part_path, 0o600)
            shutil.move(part_path, archive_path)

        backup = Backup(
            id=backup_id,
            created_at=created_at,
            size=archive_path.stat().st_size,
            sha256=self._sha256(archive_path),
            files=len(file_manifest),
        )
        part_metadata = self.storage_root / f".{backup_id}.json.part"
        part_metadata.write_text(
            json.dumps(
                {
                    "id": backup.id,
                    "created_at": backup.created_at.isoformat(),
                    "size": backup.size,
                    "sha256": backup.sha256,
                    "files": backup.files,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        os.chmod(part_metadata, 0o600)
        part_metadata.replace(metadata_path)
        for expired in self.list()[self.retention :]:
            self.delete(expired.id)
        return backup

    def archive_path(self, backup_id: str) -> Path:
        archive, metadata = self._paths(backup_id)
        if not archive.is_file() or not metadata.is_file():
            raise BackupError("Backup not found")
        expected = self._decode(metadata)
        if archive.stat().st_size != expected.size or self._sha256(archive) != expected.sha256:
            raise BackupError("Backup checksum mismatch")
        return archive

    def delete(self, backup_id: str) -> None:
        archive, metadata = self._paths(backup_id)
        if not archive.exists() and not metadata.exists():
            raise BackupError("Backup not found")
        archive.unlink(missing_ok=True)
        metadata.unlink(missing_ok=True)

    @staticmethod
    def restore(archive_path: str, database_path: str, snapshots_root: str) -> None:
        archive_file = Path(archive_path).resolve()
        database_target = Path(database_path).resolve()
        snapshots_target = Path(snapshots_root).resolve()
        try:
            with zipfile.ZipFile(archive_file) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                if manifest.get("format") != 1 or not isinstance(manifest.get("files"), list):
                    raise BackupError("Unsupported backup manifest")
                expected_paths = {
                    item["path"]: item
                    for item in manifest["files"]
                    if isinstance(item, dict) and isinstance(item.get("path"), str)
                }
                if "database/app.db" not in expected_paths:
                    raise BackupError("Backup database is missing")
                allowed = {"database/app.db"} | {
                    name
                    for name in expected_paths
                    if name.startswith("snapshots/")
                    and "/" not in name.removeprefix("snapshots/")
                    and name.endswith(".json")
                }
                if set(expected_paths) != allowed:
                    raise BackupError("Backup contains an unsafe path")
                payloads: dict[str, bytes] = {}
                for name, item in expected_paths.items():
                    payload = archive.read(name)
                    if len(payload) != item["size"] or hashlib.sha256(payload).hexdigest() != item["sha256"]:
                        raise BackupError("Backup file checksum mismatch")
                    payloads[name] = payload
        except (KeyError, TypeError, ValueError, OSError, zipfile.BadZipFile) as exc:
            if isinstance(exc, BackupError):
                raise
            raise BackupError("Invalid backup archive") from exc

        database_target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        snapshots_target.mkdir(mode=0o700, parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=database_target.parent) as temporary:
            database_part = Path(temporary) / "app.db"
            database_part.write_bytes(payloads["database/app.db"])
            connection = sqlite3.connect(f"file:{database_part}?mode=ro", uri=True)
            try:
                if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                    raise BackupError("Restored database failed integrity check")
            finally:
                connection.close()
            os.chmod(database_part, 0o600)
            shutil.move(database_part, database_target)
        for current in snapshots_target.glob("*.json"):
            current.unlink()
        for name, payload in payloads.items():
            if not name.startswith("snapshots/"):
                continue
            target = snapshots_target / name.removeprefix("snapshots/")
            target.write_bytes(payload)
            os.chmod(target, 0o600)
        os.chmod(database_target.parent, 0o700)
        os.chmod(snapshots_target, 0o700)
