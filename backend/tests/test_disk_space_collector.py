import importlib.util
import os
from pathlib import Path

import pytest

GIB = 1024**3


def _collector_module():
    path = Path(__file__).parents[2] / "deploy" / "disk-space-collector.py"
    spec = importlib.util.spec_from_file_location("disk_space_collector", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _statvfs(free_gib: float, total_gib: float = 40):
    def fake(_path: str) -> os.statvfs_result:
        # (bsize, frsize, blocks, bfree, bavail, files, ffree, favail, flag, namemax)
        return os.statvfs_result(
            (4096, 4096, int(total_gib * GIB / 4096), 0, int(free_gib * GIB / 4096), 0, 0, 0, 0, 255)
        )

    return fake


def test_parse_filesystems_accepts_presets_format() -> None:
    collector = _collector_module()

    assert collector.parse_filesystems("Sistema=/, Dati=/mnt/data") == [
        ("Sistema", Path("/")),
        ("Dati", Path("/mnt/data")),
    ]


@pytest.mark.parametrize("value", ["", "Sistema", "Sistema=relative", "Bad;label=/"])
def test_parse_filesystems_rejects_invalid_entries(value: str) -> None:
    collector = _collector_module()

    with pytest.raises(ValueError):
        collector.parse_filesystems(value)


def test_alert_when_free_space_below_minimum() -> None:
    collector = _collector_module()

    item = collector.measure("Sistema", Path("/"), 5 * GIB, None, _statvfs(free_gib=4))

    assert item["alert"] is True
    assert item["reasons"] == ["min_free"]
    assert item["free_bytes"] == 4 * GIB


def test_no_alert_above_minimum_without_percent_threshold() -> None:
    collector = _collector_module()

    item = collector.measure("Sistema", Path("/"), 5 * GIB, None, _statvfs(free_gib=6))

    assert item["alert"] is False
    assert item["reasons"] == []


def test_alert_on_used_percent_even_with_enough_free_bytes() -> None:
    collector = _collector_module()

    item = collector.measure("Dati", Path("/"), 5 * GIB, 85, _statvfs(free_gib=6, total_gib=40))

    assert item["used_percent"] == 85.0
    assert item["reasons"] == ["used_percent"]


def test_unreadable_path_is_reported_as_alert() -> None:
    collector = _collector_module()

    def broken(_path: str):
        raise FileNotFoundError

    item = collector.measure("Dati", Path("/missing"), 5 * GIB, None, broken)

    assert item == {"label": "Dati", "available": False, "alert": True, "reasons": ["unavailable"]}


def test_written_payload_is_valid_for_backend(tmp_path) -> None:
    from app.services.disk_space_service import DiskSpaceService

    collector = _collector_module()
    output = tmp_path / "state" / "disk-space.json"
    collector.write_atomic(output, collector.collect([("Sistema", Path("/"))], 5 * GIB, None, _statvfs(4)))

    state = DiskSpaceService(str(output), 10800).read()

    assert state is not None and state.stale is False
    assert state.filesystems[0].alert is True
    assert output.stat().st_mode & 0o777 == 0o600
