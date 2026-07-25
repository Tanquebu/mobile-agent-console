import asyncio

import pytest

from app.services.tmux_service import TmuxError, TmuxService


class Recorder:
    """Intercetta create_subprocess_exec registrando argv e stdin."""

    def __init__(self, monkeypatch, stdout: bytes = b"", fail_with: dict[str, bytes] | None = None) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.stdins: list[bytes | None] = []
        fail = fail_with or {}
        recorder = self

        class Process:
            def __init__(self, argv: tuple[str, ...]) -> None:
                self.returncode = 0
                self._stderr = b""
                for keyword, message in fail.items():
                    if keyword in argv:
                        self.returncode = 1
                        self._stderr = message

            async def communicate(self, stdin: bytes | None) -> tuple[bytes, bytes]:
                recorder.stdins.append(stdin)
                return stdout, self._stderr

        async def fake_exec(*argv, **kwargs):
            recorder.calls.append(argv)
            return Process(argv)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)


@pytest.mark.parametrize(
    "value",
    [" bad", "bad ", "bad  name", "x;touch_pwned", "../demo", "bad:name", "", "x" * 65],
)
def test_rejects_unsafe_session_names(value: str) -> None:
    with pytest.raises(ValueError):
        TmuxService.validate_session_id(value)


def test_accepts_safe_session_names() -> None:
    assert TmuxService.validate_session_id("codex_project-1") == "codex_project-1"
    assert TmuxService.validate_session_id("Refactoring Codex") == "Refactoring Codex"


def test_target_accepts_numeric_ids() -> None:
    assert TmuxService.validate_target("3") == "$3"
    assert TmuxService.validate_target("0") == "$0"


@pytest.mark.parametrize("value", ["$3", "", "demo", "3;x", "3.0", "1" * 11])
def test_target_rejects_non_numeric_ids(value: str) -> None:
    with pytest.raises(ValueError):
        TmuxService.validate_target(value)


def test_socket_prefix_variants(monkeypatch) -> None:
    recorder = Recorder(monkeypatch)
    asyncio.run(TmuxService("test").send_key("1", "Enter"))
    asyncio.run(TmuxService("name", socket_path="/tmux/").send_key("1", "Enter"))
    asyncio.run(TmuxService("name", socket_file="/tmp/tmux-1000/default").send_key("1", "Enter"))
    assert recorder.calls[0][:3] == ("tmux", "-L", "test")
    assert recorder.calls[1][:3] == ("tmux", "-S", "/tmux/name.sock")
    assert recorder.calls[2][:3] == ("tmux", "-S", "/tmp/tmux-1000/default")


def test_multiline_and_special_text_goes_through_stdin(monkeypatch) -> None:
    recorder = Recorder(monkeypatch)
    service = TmuxService("test")
    text = "line one\n$(touch /tmp/nope); ' \" à"
    asyncio.run(service.send_text("1", text))

    assert recorder.stdins[0] == text.encode()
    assert recorder.calls[0][:3] == ("tmux", "-L", "test")
    assert "paste-buffer" in recorder.calls[1]
    assert recorder.calls[1][recorder.calls[1].index("-t") + 1] == "$1"


def test_capture_targets_active_pane(monkeypatch) -> None:
    recorder = Recorder(monkeypatch)
    asyncio.run(TmuxService("test").capture_output("7"))
    call = recorder.calls[0]
    assert call[call.index("-t") + 1] == "$7"


def test_create_session_uses_login_shell(monkeypatch) -> None:
    recorder = Recorder(monkeypatch)
    asyncio.run(TmuxService("test").create_session("demo", "/workspace"))
    assert recorder.calls[0][-2:] == ("bash", "-l")


def test_rename_session_uses_numeric_target_and_separate_name_argv(monkeypatch) -> None:
    recorder = Recorder(monkeypatch)
    asyncio.run(TmuxService("test").rename_session("7", "Refactoring Codex"))
    assert recorder.calls[0][-4:] == ("rename-session", "-t", "$7", "Refactoring Codex")


def test_external_server_guard_blocks_autostart(monkeypatch) -> None:
    recorder = Recorder(monkeypatch, fail_with={"list-sessions": b"no server running on /tmp/tmux-1000/default"})
    service = TmuxService("test", socket_file="/tmp/tmux-1000/default", external_server=True)
    with pytest.raises(TmuxError):
        asyncio.run(service.create_session("demo", "/workspace"))
    assert all("new-session" not in call for call in recorder.calls)


def test_check_server_reports_errors(monkeypatch) -> None:
    Recorder(monkeypatch, fail_with={"list-sessions": b"protocol version mismatch (client 3.5, server 3.6)"})
    error = asyncio.run(TmuxService("test").check_server())
    assert error is not None and "protocol version mismatch" in error


def test_list_sessions_uses_ids_and_keeps_host_names(monkeypatch) -> None:
    lines = (
        b"$3\t1\t2\tnode\t1700000000\tnome con spazi\te tab\n"
        b"$4\t0\t1\tbash\t1700000000\t__runtime__\n"
        b"bad\t0\t1\tbash\t1700000000\tx\n"
    )
    recorder = Recorder(monkeypatch, stdout=lines)
    hosted = asyncio.run(TmuxService("test", external_server=True).list_sessions())
    assert [(s.id, s.name) for s in hosted] == [("3", "nome con spazi\te tab"), ("4", "__runtime__")]
    assert hosted[0].attached and not hosted[1].attached

    recorder.calls.clear()
    isolated = asyncio.run(TmuxService("test").list_sessions())
    assert [(s.id, s.name) for s in isolated] == [("3", "nome con spazi\te tab")]


def test_only_allowlisted_keys_are_supported(monkeypatch) -> None:
    recorder = Recorder(monkeypatch)
    service = TmuxService("test")
    for key in ("Enter", "Up", "Down", "Escape", "C-c"):
        asyncio.run(service.send_key("1", key))
    assert [call[-1] for call in recorder.calls] == ["Enter", "Up", "Down", "Escape", "C-c"]
    with pytest.raises(ValueError):
        asyncio.run(service.send_key("1", "C-x"))


def test_terminate_targets_session_id(monkeypatch) -> None:
    recorder = Recorder(monkeypatch)
    asyncio.run(TmuxService("test").terminate_session("7"))
    assert recorder.calls[0][-3:] == ("kill-session", "-t", "$7")


def test_pane_path_targets_active_pane(monkeypatch) -> None:
    recorder = Recorder(monkeypatch, stdout=b"/workspace/demo\n")
    path = asyncio.run(TmuxService("test").pane_path("7"))
    assert path == "/workspace/demo"
    call = recorder.calls[0]
    assert call[call.index("-t") + 1] == "$7"
    assert call[-1] == "#{pane_current_path}"
