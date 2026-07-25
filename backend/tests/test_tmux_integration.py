import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from app.services.tmux_service import SessionNotFound, TmuxService


@pytest.fixture
def real_tmux(tmp_path: Path):
    binary = shutil.which("tmux")
    if binary is None:
        pytest.skip("tmux is not installed")
    socket_file = tmp_path / "tmux.sock"
    service = TmuxService(
        "integration",
        binary=binary,
        socket_file=str(socket_file),
    )
    yield service
    subprocess.run(
        [binary, "-S", str(socket_file), "kill-server"],
        check=False,
        capture_output=True,
        shell=False,
    )


async def _wait_for_output(
    service: TmuxService,
    session_id: str,
    expected: str,
    attempts: int = 40,
) -> str:
    for _ in range(attempts):
        output = await service.capture_output(session_id)
        if expected in output:
            return output
        await asyncio.sleep(0.05)
    raise AssertionError(f"{expected!r} not found in tmux output")


async def _wait_for_file(path: Path, attempts: int = 40) -> bytes:
    for _ in range(attempts):
        if path.exists():
            return path.read_bytes()
        await asyncio.sleep(0.05)
    raise AssertionError(f"{path} was not created")


async def _wait_for_file_content(path: Path, expected: bytes, attempts: int = 40) -> None:
    for _ in range(attempts):
        if path.exists() and path.read_bytes() == expected:
            return
        await asyncio.sleep(0.05)
    actual = path.read_bytes() if path.exists() else None
    raise AssertionError(f"{path} contains {actual!r}, expected {expected!r}")


async def test_real_tmux_session_lifecycle_and_separate_enter(real_tmux, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    await real_tmux.create_session("Gate M1 Test", str(workspace))
    sessions = await real_tmux.list_sessions()
    assert len(sessions) == 1
    session = sessions[0]
    assert session.name == "Gate M1 Test"
    assert session.id.isdigit()
    assert await real_tmux.pane_path(session.id) == str(workspace.resolve())

    marker = workspace / "enter-was-sent"
    await real_tmux.send_text(session.id, f"touch {marker}")
    await asyncio.sleep(0.1)
    assert not marker.exists()
    await real_tmux.send_key(session.id, "Enter")
    await _wait_for_file(marker)

    await real_tmux.rename_session(session.id, "Gate M1 Renamed")
    renamed = await real_tmux.list_sessions()
    assert [(item.id, item.name) for item in renamed] == [(session.id, "Gate M1 Renamed")]

    await real_tmux.terminate_session(session.id)
    assert await real_tmux.list_sessions() == []
    with pytest.raises(SessionNotFound):
        await real_tmux.capture_output(session.id)


async def test_real_tmux_pastes_special_text_without_shell_interpretation(
    real_tmux,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    captured = workspace / "captured.txt"
    injected = workspace / "must-not-exist"

    await real_tmux.create_session("literal-input", str(workspace))
    session_id = (await real_tmux.list_sessions())[0].id
    await real_tmux.send_text(session_id, f"cat > {captured}")
    await real_tmux.send_key(session_id, "Enter")
    await _wait_for_output(real_tmux, session_id, f"cat > {captured}")

    payload = f"line one\n$(touch {injected}); ' \" à\n"
    await real_tmux.send_text(session_id, payload)
    await asyncio.sleep(0.1)
    await real_tmux.send_key(session_id, "C-c")

    await _wait_for_file_content(captured, payload.encode())
    assert not injected.exists()


async def test_real_tmux_reports_disappeared_server(real_tmux, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    await real_tmux.create_session("server-check", str(workspace))
    session_id = (await real_tmux.list_sessions())[0].id
    await real_tmux.terminate_session(session_id)

    error = await real_tmux.check_server()
    assert error is not None
