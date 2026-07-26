import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from app.services.backup_service import BackupError, BackupService


def create_database(path: Path, value: str = "original") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE sample (value TEXT NOT NULL)")
    connection.execute("INSERT INTO sample VALUES (?)", (value,))
    connection.commit()
    connection.close()


def test_backup_create_list_download_delete_and_restore(tmp_path: Path) -> None:
    database = tmp_path / "data" / "app.db"
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    (snapshots / "one.json").write_text('{"name":"before reboot"}', encoding="utf-8")
    create_database(database)
    service = BackupService(
        str(tmp_path / "backups"), str(database), str(snapshots), retention=2
    )

    item = service.create()
    assert service.list() == [item]
    archive = service.archive_path(item.id)
    assert item.files == 2
    assert archive.stat().st_size == item.size

    restored_database = tmp_path / "restored" / "app.db"
    restored_snapshots = tmp_path / "restored-snapshots"
    BackupService.restore(str(archive), str(restored_database), str(restored_snapshots))
    connection = sqlite3.connect(restored_database)
    assert connection.execute("SELECT value FROM sample").fetchone() == ("original",)
    connection.close()
    assert json.loads((restored_snapshots / "one.json").read_text())["name"] == "before reboot"

    service.delete(item.id)
    assert service.list() == []
    with pytest.raises(BackupError, match="not found"):
        service.archive_path(item.id)


def test_backup_retention_and_checksum_validation(tmp_path: Path) -> None:
    database = tmp_path / "app.db"
    create_database(database)
    service = BackupService(
        str(tmp_path / "backups"), str(database), str(tmp_path / "snapshots"), retention=1
    )
    first = service.create()
    second = service.create()
    assert [item.id for item in service.list()] == [second.id]
    assert not (tmp_path / "backups" / f"{first.id}.zip").exists()

    archive = service.archive_path(second.id)
    archive.write_bytes(archive.read_bytes() + b"tampered")
    with pytest.raises(BackupError, match="checksum"):
        service.archive_path(second.id)


def test_restore_rejects_unsafe_manifest(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr(
            "manifest.json",
            json.dumps(
                {
                    "format": 1,
                    "files": [
                        {
                            "path": "../secret",
                            "size": 0,
                            "sha256": "0" * 64,
                        }
                    ],
                }
            ),
        )
    with pytest.raises(BackupError):
        BackupService.restore(
            str(archive), str(tmp_path / "app.db"), str(tmp_path / "snapshots")
        )
