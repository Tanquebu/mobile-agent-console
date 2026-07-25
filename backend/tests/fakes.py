from datetime import UTC, datetime

from app.services.tmux_service import (
    SessionNotFound,
    TmuxError,
    TmuxPane,
    TmuxService,
    TmuxSession,
)


class FakeTmux:
    def __init__(self) -> None:
        self.content = "$ "
        self.texts: list[str] = []
        self.keys: list[str] = []
        self.targets: list[str | None] = []
        self.resizes: list[tuple[str, int, int]] = []
        self.terminated: list[str] = []
        self.renamed: list[tuple[str, str]] = []
        self.server_down = False
        self.duplicate_name = False
        self.directory = "/workspace"
        self.sessions = {
            "1": TmuxSession("1", "demo", False, 1, "bash", datetime.now(UTC))
        }

    async def check_server(self) -> str | None:
        return "no server running" if self.server_down else None

    async def list_sessions(self) -> list[TmuxSession]:
        return list(self.sessions.values())

    async def create_session(self, session_id: str, directory: str, command: str = "bash") -> None:
        if self.server_down:
            raise TmuxError("Host tmux server is not running; start tmux on the host first")
        if self.duplicate_name:
            raise TmuxError(f"duplicate session: {session_id}")
        if any(item.name == session_id for item in self.sessions.values()):
            raise TmuxError(f"duplicate session: {session_id}")
        new_id = str(max((int(item) for item in self.sessions), default=0) + 1)
        self.sessions[new_id] = TmuxSession(
            new_id,
            session_id,
            False,
            1,
            command,
            datetime.now(UTC),
        )

    async def list_panes(self, session_id: str) -> list[TmuxPane]:
        TmuxService.validate_target(session_id)
        if session_id not in self.sessions:
            raise SessionNotFound(session_id)
        return [TmuxPane("10", 0, 0, True, "bash", "demo", 80, 24)]

    async def capture_output(
        self, session_id: str, lines: int = 500, pane_id: str | None = None
    ) -> str:
        TmuxService.validate_target(session_id)
        if session_id not in self.sessions:
            raise SessionNotFound(session_id)
        if pane_id is not None and pane_id != "10":
            raise SessionNotFound(pane_id)
        return self.content

    async def send_text(self, session_id: str, text: str, pane_id: str | None = None) -> None:
        TmuxService.validate_target(session_id)
        if session_id not in self.sessions:
            raise SessionNotFound(session_id)
        self.texts.append(text)
        self.targets.append(pane_id)

    async def send_key(self, session_id: str, key: str, pane_id: str | None = None) -> None:
        if key not in {"Enter", "Up", "Down", "Escape", "C-c"}:
            raise ValueError("Unsupported key")
        TmuxService.validate_target(session_id)
        if session_id not in self.sessions:
            raise SessionNotFound(session_id)
        self.keys.append(key)
        self.targets.append(pane_id)

    async def resize_pane(self, session_id: str, pane_id: str, columns: int, rows: int) -> None:
        if not await self.list_panes(session_id) or pane_id != "10":
            raise SessionNotFound(pane_id)
        self.resizes.append((pane_id, columns, rows))

    async def split_pane(self, session_id: str, pane_id: str | None = None) -> TmuxPane:
        await self.list_panes(session_id)
        if pane_id not in {None, "10"}:
            raise SessionNotFound(pane_id)
        return TmuxPane("11", 0, 1, False, "bash", "demo", 40, 24)

    async def terminate_session(self, session_id: str) -> None:
        TmuxService.validate_target(session_id)
        if session_id not in self.sessions:
            raise SessionNotFound(session_id)
        self.terminated.append(session_id)
        del self.sessions[session_id]

    async def rename_session(self, session_id: str, name: str) -> None:
        TmuxService.validate_target(session_id)
        TmuxService.validate_session_id(name)
        if session_id not in self.sessions:
            raise SessionNotFound(session_id)
        if self.duplicate_name:
            raise TmuxError(f"duplicate session: {name}")
        self.renamed.append((session_id, name))
        current = self.sessions[session_id]
        self.sessions[session_id] = TmuxSession(
            current.id,
            name,
            current.attached,
            current.windows,
            current.current_command,
            current.activity_at,
        )

    async def pane_path(self, session_id: str, pane_id: str | None = None) -> str:
        TmuxService.validate_target(session_id)
        if session_id not in self.sessions:
            raise SessionNotFound(session_id)
        return self.directory
