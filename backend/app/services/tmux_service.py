import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

SESSION_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
TARGET_ID = re.compile(r"^\d{1,10}$")
RUNTIME_KEEPALIVE = "__runtime__"


class TmuxError(RuntimeError):
    pass


class SessionNotFound(TmuxError):
    pass


@dataclass(frozen=True)
class TmuxSession:
    id: str
    name: str
    attached: bool
    windows: int
    current_command: str
    activity_at: datetime


class TmuxGateway(Protocol):
    async def create_session(self, session_id: str, directory: str, command: str = "bash") -> None: ...
    async def list_sessions(self) -> list[TmuxSession]: ...
    async def capture_output(self, session_id: str, lines: int = 500) -> str: ...
    async def send_text(self, session_id: str, text: str) -> None: ...
    async def send_key(self, session_id: str, key: str) -> None: ...
    async def check_server(self) -> str | None: ...


class TmuxService:
    def __init__(
        self,
        socket_name: str,
        binary: str = "tmux",
        socket_path: str | None = None,
        socket_file: str | None = None,
        external_server: bool = False,
    ) -> None:
        if not SESSION_NAME.fullmatch(socket_name):
            raise ValueError("Invalid tmux socket name")
        self._prefix = [binary, "-S", socket_file] if socket_file else (
            [binary, "-S", f"{socket_path.rstrip('/')}/{socket_name}.sock"]
            if socket_path
            else [binary, "-L", socket_name]
        )
        self._external_server = external_server

    @staticmethod
    def validate_session_id(session_id: str) -> str:
        if not SESSION_NAME.fullmatch(session_id):
            raise ValueError("Invalid session id")
        return session_id

    @staticmethod
    def validate_target(session_id: str) -> str:
        if not TARGET_ID.fullmatch(session_id):
            raise ValueError("Invalid session id")
        return f"${session_id}"

    async def _run(self, *args: str, stdin: bytes | None = None) -> bytes:
        process = await asyncio.create_subprocess_exec(
            *self._prefix,
            *args,
            stdin=asyncio.subprocess.PIPE if stdin is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate(stdin)
        if process.returncode != 0:
            message = stderr.decode(errors="replace").strip()
            if "can't find session" in message or "no server running" in message:
                raise SessionNotFound(message)
            raise TmuxError(message or f"tmux exited with {process.returncode}")
        return stdout

    async def check_server(self) -> str | None:
        try:
            await self._run("list-sessions", "-F", "#{session_id}")
        except TmuxError as exc:
            return str(exc) or "tmux server unavailable"
        return None

    async def _require_server(self) -> None:
        # In modalità host un new-session senza server attivo avvierebbe il
        # server tmux dentro questo container invece che sull'host.
        try:
            await self._run("list-sessions", "-F", "#{session_id}")
        except SessionNotFound as exc:
            raise TmuxError(
                "Host tmux server is not running; start tmux on the host first"
            ) from exc

    async def list_sessions(self) -> list[TmuxSession]:
        fmt = (
            "#{session_id}\t#{session_attached}\t#{session_windows}"
            "\t#{pane_current_command}\t#{session_activity}\t#{session_name}"
        )
        try:
            raw = await self._run("list-sessions", "-F", fmt)
        except SessionNotFound:
            return []
        sessions = []
        for line in raw.decode(errors="replace").splitlines():
            raw_id, attached, windows, command, activity, name = line.split("\t", 5)
            session_id = raw_id.removeprefix("$")
            if not TARGET_ID.fullmatch(session_id):
                continue
            if not self._external_server and name == RUNTIME_KEEPALIVE:
                continue
            sessions.append(
                TmuxSession(
                    id=session_id,
                    name=name,
                    attached=attached not in {"", "0"},
                    windows=int(windows),
                    current_command=command,
                    activity_at=datetime.fromtimestamp(int(activity), tz=UTC),
                )
            )
        return sessions

    async def capture_output(self, session_id: str, lines: int = 500) -> str:
        target = self.validate_target(session_id)
        raw = await self._run("capture-pane", "-p", "-J", "-S", f"-{lines}", "-t", target)
        return raw.decode(errors="replace")

    async def create_session(self, session_id: str, directory: str, command: str = "bash") -> None:
        self.validate_session_id(session_id)
        if command != "bash":
            raise ValueError("Unsupported profile")
        if self._external_server:
            await self._require_server()
        await self._run("new-session", "-d", "-s", session_id, "-c", directory, "bash", "-l")

    async def send_text(self, session_id: str, text: str) -> None:
        target = self.validate_target(session_id)
        buffer_name = f"mac-{session_id}"
        await self._run("load-buffer", "-b", buffer_name, "-", stdin=text.encode())
        try:
            await self._run("paste-buffer", "-b", buffer_name, "-t", target, "-d")
        except TmuxError:
            await self._run("delete-buffer", "-b", buffer_name)
            raise

    async def send_key(self, session_id: str, key: str) -> None:
        if key != "Enter":
            raise ValueError("Unsupported key")
        target = self.validate_target(session_id)
        await self._run("send-keys", "-t", target, "Enter")
