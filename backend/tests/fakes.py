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
        self.capture_ansi_calls: list[bool] = []
        self.capture_lines_calls: list[int] = []
        self.texts: list[str] = []
        self.keys: list[str] = []
        self.targets: list[str | None] = []
        self.resizes: list[tuple[str, int, int]] = []
        self.splits: list[str] = []
        self.terminated: list[str] = []
        self.renamed: list[tuple[str, str]] = []
        self.created: list[tuple[str, str, str, bool]] = []
        self.server_down = False
        self.duplicate_name = False
        # Simula la sessione di servizio riservata (INC-HOST-01): esclusa da
        # list_sessions e la cui terminazione va rifiutata anche per id noto.
        self.protected_session_id: str | None = None
        self.directory = "/workspace"
        self.sessions = {
            "1": TmuxSession("1", "demo", False, 1, "bash", datetime.now(UTC))
        }
        self.panes: dict[str, list[TmuxPane]] = {
            "1": [TmuxPane("10", 0, 0, True, "bash", "demo", 80, 24)]
        }

    async def check_server(self) -> str | None:
        return "no server running" if self.server_down else None

    async def list_sessions(self) -> list[TmuxSession]:
        return [
            item for item in self.sessions.values() if item.id != self.protected_session_id
        ]

    async def create_session(
        self,
        session_id: str,
        directory: str,
        profile: str = "shell",
        resume: bool = False,
    ) -> None:
        if self.server_down:
            raise TmuxError("Host tmux server is not running; start tmux on the host first")
        if self.duplicate_name:
            raise TmuxError(f"duplicate session: {session_id}")
        if any(item.name == session_id for item in self.sessions.values()):
            raise TmuxError(f"duplicate session: {session_id}")
        self.created.append((session_id, directory, profile, resume))
        new_id = str(max((int(item) for item in self.sessions), default=0) + 1)
        self.sessions[new_id] = TmuxSession(
            new_id,
            session_id,
            False,
            1,
            {
                "shell": "bash",
                "codex": "codex",
                "claude": "claude",
                "antigravity": "agy",
                "opencode": "opencode",
            }[profile],
            datetime.now(UTC),
        )
        self.panes[new_id] = [TmuxPane("10", 0, 0, True, "bash", session_id, 80, 24)]

    async def list_panes(self, session_id: str) -> list[TmuxPane]:
        TmuxService.validate_target(session_id)
        if session_id not in self.sessions:
            raise SessionNotFound(session_id)
        return list(self.panes.get(session_id, []))

    async def capture_output(
        self, session_id: str, lines: int = 500, pane_id: str | None = None, ansi: bool = False
    ) -> str:
        TmuxService.validate_target(session_id)
        if session_id not in self.sessions:
            raise SessionNotFound(session_id)
        if pane_id is not None and pane_id != "10":
            raise SessionNotFound(pane_id)
        self.capture_ansi_calls.append(ansi)
        self.capture_lines_calls.append(lines)
        return self.content

    async def send_text(self, session_id: str, text: str, pane_id: str | None = None) -> None:
        TmuxService.validate_target(session_id)
        if session_id not in self.sessions:
            raise SessionNotFound(session_id)
        self.texts.append(text)
        self.targets.append(pane_id)

    async def send_key(self, session_id: str, key: str, pane_id: str | None = None) -> None:
        if key not in {"Enter", "Up", "Down", "Left", "Right", "Escape", "C-c", "Tab", "Shift-Tab"}:
            raise ValueError("Unsupported key")
        TmuxService.validate_target(session_id)
        if session_id not in self.sessions:
            raise SessionNotFound(session_id)
        self.keys.append(key)
        self.targets.append(pane_id)

    async def resize_pane(self, session_id: str, pane_id: str, columns: int, rows: int) -> None:
        panes = await self.list_panes(session_id)
        if not any(pane.id == pane_id for pane in panes):
            raise SessionNotFound(pane_id)
        self.resizes.append((pane_id, columns, rows))

    async def split_pane(
        self, session_id: str, pane_id: str | None = None, direction: str = "horizontal"
    ) -> TmuxPane:
        if direction not in {"horizontal", "vertical"}:
            raise ValueError("Unsupported split direction")
        panes = await self.list_panes(session_id)
        if pane_id is not None and not any(pane.id == pane_id for pane in panes):
            raise SessionNotFound(pane_id)
        self.splits.append(direction)
        new_id = str(max((int(pane.id) for pane in panes), default=0) + 1)
        new_pane = TmuxPane(new_id, 0, len(panes), False, "bash", "demo", 40, 24)
        self.panes[session_id].append(new_pane)
        return new_pane

    async def kill_pane(self, session_id: str, pane_id: str) -> None:
        panes = await self.list_panes(session_id)
        if not any(pane.id == pane_id for pane in panes):
            raise SessionNotFound(pane_id)
        self.panes[session_id] = [pane for pane in panes if pane.id != pane_id]

    async def terminate_session(self, session_id: str) -> None:
        TmuxService.validate_target(session_id)
        if session_id not in self.sessions:
            raise SessionNotFound(session_id)
        if session_id == self.protected_session_id:
            raise TmuxError("Refusing to terminate the reserved keepalive session")
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
