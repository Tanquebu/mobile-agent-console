import json

import pytest

from app.services.snapshot_service import (
    SnapshotError,
    SnapshotService,
    SnapshotSession,
)


def saved_session(mode: str = "shell") -> SnapshotSession:
    return SnapshotSession(
        name="Refactoring Codex",
        directory="/workspace/project",
        mode=mode,
        observed_command="codex",
    )


def test_snapshot_service_persists_lists_and_deletes(tmp_path) -> None:
    service = SnapshotService(str(tmp_path))
    created = service.create("Before reboot", [saved_session("codex")])

    listed = service.list()
    assert [item.id for item in listed] == [created.id]
    loaded = service.get(created.id)
    assert loaded.name == "Before reboot"
    assert loaded.sessions == [saved_session("codex")]
    assert (tmp_path / f"{created.id}.json").stat().st_mode & 0o777 == 0o600

    service.delete(created.id)
    assert service.list() == []
    with pytest.raises(SnapshotError, match="not found"):
        service.get(created.id)


def test_snapshot_service_rejects_invalid_input_and_ignores_corrupt_files(tmp_path) -> None:
    service = SnapshotService(str(tmp_path))
    with pytest.raises(SnapshotError):
        service.create("", [saved_session()])
    with pytest.raises(SnapshotError):
        service.create("empty", [])
    with pytest.raises(SnapshotError):
        service.create("bad mode", [saved_session("arbitrary")])
    with pytest.raises(SnapshotError):
        service.get("../escape")

    tmp_path.mkdir(exist_ok=True)
    (tmp_path / f"{'a' * 32}.json").write_text(json.dumps({"broken": True}))
    assert service.list() == []
