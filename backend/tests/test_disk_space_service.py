from datetime import UTC, datetime

from app.services.disk_space_service import DiskSpaceService

PAYLOAD = """{
  "schema_version": 1,
  "collected_at": "2026-10-07T10:00:00+00:00",
  "min_free_bytes": 5368709120,
  "max_used_percent": null,
  "filesystems": [
    {"label": "Sistema", "available": true, "total_bytes": 40000000000,
     "free_bytes": 130000000, "used_percent": 99.7, "alert": true, "reasons": ["min_free"]},
    {"label": "Dati", "available": false, "alert": true, "reasons": ["unavailable"]}
  ]
}"""


def test_disk_space_is_loaded_and_marked_fresh(tmp_path) -> None:
    path = tmp_path / "disk-space.json"
    path.write_text(PAYLOAD, encoding="utf-8")

    state = DiskSpaceService(str(path), 10800).read(now=datetime(2026, 10, 7, 11, tzinfo=UTC))

    assert state is not None
    assert state.stale is False
    assert state.filesystems[0].alert is True
    assert state.filesystems[1].free_bytes is None


def test_disk_space_older_than_max_age_is_stale(tmp_path) -> None:
    path = tmp_path / "disk-space.json"
    path.write_text(PAYLOAD, encoding="utf-8")

    state = DiskSpaceService(str(path), 10800).read(now=datetime(2026, 10, 7, 14, tzinfo=UTC))

    assert state is not None
    assert state.stale is True


def test_disk_space_missing_or_invalid_file_is_none(tmp_path) -> None:
    path = tmp_path / "disk-space.json"
    assert DiskSpaceService(str(path), 10800).read() is None

    path.write_text('{"schema_version": 2, "filesystems": []}', encoding="utf-8")
    assert DiskSpaceService(str(path), 10800).read() is None
