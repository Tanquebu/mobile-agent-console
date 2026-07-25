from datetime import UTC, datetime

from app.services.tmux_service import SessionNotFound, TmuxError, TmuxService, TmuxSession


class FakeTmux:
    def __init__(self) -> None:
        self.content = "$ "
        self.texts: list[str] = []
        self.keys: list[str] = []
        self.terminated: list[str] = []
        self.server_down = False
        self.directory = "/workspace"

    async def check_server(self) -> str | None:
        return "no server running" if self.server_down else None

    async def list_sessions(self) -> list[TmuxSession]:
        return [TmuxSession("1", "demo", False, 1, "bash", datetime.now(UTC))]

    async def create_session(self, session_id: str, directory: str, command: str = "bash") -> None:
        if self.server_down:
            raise TmuxError("Host tmux server is not running; start tmux on the host first")

    async def capture_output(self, session_id: str, lines: int = 500) -> str:
        TmuxService.validate_target(session_id)
        if session_id != "1":
            raise SessionNotFound(session_id)
        return self.content

    async def send_text(self, session_id: str, text: str) -> None:
        TmuxService.validate_target(session_id)
        if session_id != "1":
            raise SessionNotFound(session_id)
        self.texts.append(text)

    async def send_key(self, session_id: str, key: str) -> None:
        if key not in {"Enter", "Up", "Down", "Escape", "C-c"}:
            raise ValueError("Unsupported key")
        TmuxService.validate_target(session_id)
        self.keys.append(key)

    async def terminate_session(self, session_id: str) -> None:
        TmuxService.validate_target(session_id)
        if session_id != "1":
            raise SessionNotFound(session_id)
        self.terminated.append(session_id)

    async def pane_path(self, session_id: str) -> str:
        TmuxService.validate_target(session_id)
        if session_id != "1":
            raise SessionNotFound(session_id)
        return self.directory
