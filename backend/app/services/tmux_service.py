import asyncio
import re
import shlex
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

SOCKET_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# ``\w`` is Unicode-aware in Python: session names may use letters and
# numbers such as "osservabilità", but never separators or control characters.
SESSION_NAME = re.compile(r"^[\w-]+(?: [\w-]+)*$")
TARGET_ID = re.compile(r"^\d{1,10}$")
RUNTIME_KEEPALIVE = "__runtime__"
ALLOWED_KEYS = {
    "Enter": "Enter",
    "Up": "Up",
    "Down": "Down",
    "Left": "Left",
    "Right": "Right",
    "Escape": "Escape",
    "C-c": "C-c",
    "Tab": "Tab",
    "Shift-Tab": "BTab",
}



def _missing_binary_shell_command(binary: str, message: str) -> str:
    """Costruisce lo script argv (costante server-side, mai da input client)
    per un profilo il cui binario puo' mancare sull'host. Verifica la
    risoluzione nella stessa login shell che tmux userebbe (`command -v`,
    non un test nella shell interattiva del backend) ed esegue `binary` se
    presente; altrimenti stampa `message` e lascia la sessione viva in una
    shell di login invece di farla sparire in silenzio. Senza questo ramo,
    un binario assente termina l'unico processo del pane subito dopo
    l'avvio e tmux distrugge la sessione: dall'API la richiesta di
    creazione risulta comunque riuscita (201), e l'unico segnale e' la
    sessione che scompare dall'elenco pochi istanti dopo — verificato il
    03/08/2026 con un binario fittizio al posto di `opencode`."""
    quoted_binary = shlex.quote(binary)
    return (
        f"command -v {quoted_binary} >/dev/null 2>&1 && exec {quoted_binary} || "
        f"{{ printf '%s\\n' {shlex.quote(message)}; exec bash -l; }}"
    )


# `OPENCODE_CONFIG_CONTENT` non e' documentata da OpenCode (verificata nel
# binario 1.18.11): un upgrade potrebbe rimuoverla senza preavviso e la
# policy smetterebbe di essere applicata in silenzio. Vedi
# test_tmux_service.py::test_opencode_profile_ships_conservative_permission_policy,
# che fallisce se questa costante smette di essere passata alla sessione.
OPENCODE_PERMISSION_POLICY = '{"permission":{"bash":"ask","edit":"ask"}}'
OPENCODE_MISSING_BINARY_MESSAGE = (
    "opencode non trovato nel PATH della login shell di tmux. Installare "
    "opencode sull'host prima di usare questo profilo (vedi "
    "docs/architecture.md, sezione OpenCode)."
)
_OPENCODE_LAUNCH = (
    "bash",
    "-l",
    "-c",
    _missing_binary_shell_command("opencode", OPENCODE_MISSING_BINARY_MESSAGE),
)
PROFILE_ARGV = {
    "shell": ("bash", "-l"),
    "codex": ("bash", "-l", "-c", "exec codex"),
    "claude": ("bash", "-l", "-c", "exec claude"),
    "antigravity": ("bash", "-l", "-c", "exec agy"),
    "opencode": _OPENCODE_LAUNCH,
}
RESUME_PROFILE_ARGV = {
    "shell": PROFILE_ARGV["shell"],
    "codex": ("bash", "-l", "-c", "exec codex resume"),
    "claude": ("bash", "-l", "-c", "exec claude --resume"),
    "antigravity": ("bash", "-l", "-c", "exec agy -c"),
    # Lo store delle conversazioni OpenCode e' globale per utente, non per
    # progetto: `--continue` puo' agganciare la conversazione di un altro
    # progetto (verificato in IMP-OC-00). Il profilo di ripresa avvia quindi
    # OpenCode normalmente, come un avvio nuovo; l'aggancio alla
    # conversazione giusta e' materia di OC-02 (selettore nativo `/sessions`).
    "opencode": _OPENCODE_LAUNCH,
}
# Variabili d'ambiente per profilo, passate a `tmux new-session -e` come
# costante server-side — mai una stringa di shell, mai un file da montare
# sull'host. E' il meccanismo scelto da ROOT per consegnare la policy dei
# permessi di OpenCode (IMP-OC-01): verificato sul campo che un JSON
# attraversa `tmux -e` integro, virgolette comprese.
PROFILE_ENV: dict[str, tuple[tuple[str, str], ...]] = {
    "opencode": (("OPENCODE_CONFIG_CONTENT", OPENCODE_PERMISSION_POLICY),),
}


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


@dataclass(frozen=True)
class TmuxPane:
    id: str
    window_index: int
    pane_index: int
    active: bool
    command: str
    title: str
    width: int
    height: int


class TmuxGateway(Protocol):
    async def create_session(
        self,
        session_id: str,
        directory: str,
        profile: str = "shell",
        resume: bool = False,
    ) -> None: ...
    async def rename_session(self, session_id: str, name: str) -> None: ...
    async def list_sessions(self) -> list[TmuxSession]: ...
    async def list_panes(self, session_id: str) -> list[TmuxPane]: ...
    async def capture_output(
        self, session_id: str, lines: int = 500, pane_id: str | None = None, ansi: bool = False
    ) -> str: ...
    async def send_text(self, session_id: str, text: str, pane_id: str | None = None) -> None: ...
    async def send_key(self, session_id: str, key: str, pane_id: str | None = None) -> None: ...
    async def resize_pane(self, session_id: str, pane_id: str, columns: int, rows: int) -> None: ...
    async def split_pane(
        self, session_id: str, pane_id: str | None = None, direction: str = "horizontal"
    ) -> TmuxPane: ...
    async def kill_pane(self, session_id: str, pane_id: str) -> None: ...
    async def terminate_session(self, session_id: str) -> None: ...
    async def check_server(self) -> str | None: ...
    async def pane_path(self, session_id: str, pane_id: str | None = None) -> str: ...


class TmuxService:
    def __init__(
        self,
        socket_name: str,
        binary: str = "tmux",
        socket_path: str | None = None,
        socket_file: str | None = None,
        external_server: bool = False,
    ) -> None:
        if not SOCKET_NAME.fullmatch(socket_name):
            raise ValueError("Invalid tmux socket name")
        self._prefix = [binary, "-S", socket_file] if socket_file else (
            [binary, "-S", f"{socket_path.rstrip('/')}/{socket_name}.sock"]
            if socket_path
            else [binary, "-L", socket_name]
        )
        self._external_server = external_server

    @staticmethod
    def validate_session_name(name: str) -> str:
        normalized = unicodedata.normalize("NFC", name)
        if len(normalized) > 64 or not SESSION_NAME.fullmatch(normalized):
            raise ValueError("Invalid session name")
        return normalized

    @staticmethod
    def validate_session_id(session_id: str) -> str:
        """Backward-compatible alias; session ids are validated by validate_target."""
        return TmuxService.validate_session_name(session_id)

    @staticmethod
    def validate_target(session_id: str) -> str:
        if not TARGET_ID.fullmatch(session_id):
            raise ValueError("Invalid session id")
        return f"${session_id}"

    @staticmethod
    def validate_pane_id(pane_id: str) -> str:
        if not TARGET_ID.fullmatch(pane_id):
            raise ValueError("Invalid pane id")
        return f"%{pane_id}"

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

    async def list_panes(self, session_id: str) -> list[TmuxPane]:
        session_target = self.validate_target(session_id)
        fmt = (
            "#{pane_id}\t#{window_index}\t#{pane_index}\t#{pane_active}"
            "\t#{pane_current_command}\t#{pane_title}\t#{pane_width}\t#{pane_height}"
        )
        raw = await self._run("list-panes", "-s", "-t", session_target, "-F", fmt)
        panes = []
        for line in raw.decode(errors="replace").splitlines():
            raw_id, window, pane, active, command, title, width, height = line.split("\t", 7)
            pane_id = raw_id.removeprefix("%")
            if TARGET_ID.fullmatch(pane_id):
                panes.append(
                    TmuxPane(
                        id=pane_id,
                        window_index=int(window),
                        pane_index=int(pane),
                        active=active == "1",
                        command=command,
                        title=title,
                        width=int(width),
                        height=int(height),
                    )
                )
        return panes

    async def _pane_target(self, session_id: str, pane_id: str | None) -> str:
        session_target = self.validate_target(session_id)
        if pane_id is None:
            return session_target
        pane_target = self.validate_pane_id(pane_id)
        if not any(pane.id == pane_id for pane in await self.list_panes(session_id)):
            raise SessionNotFound("Pane not found in session")
        return pane_target

    async def capture_output(
        self, session_id: str, lines: int = 500, pane_id: str | None = None, ansi: bool = False
    ) -> str:
        target = await self._pane_target(session_id, pane_id)
        argv = ["capture-pane", "-p", "-J"]
        if ansi:
            argv.append("-e")
        argv += ["-S", f"-{lines}", "-t", target]
        raw = await self._run(*argv)
        return raw.decode(errors="replace")

    async def create_session(
        self,
        session_id: str,
        directory: str,
        profile: str = "shell",
        resume: bool = False,
    ) -> None:
        session_id = self.validate_session_name(session_id)
        command = (RESUME_PROFILE_ARGV if resume else PROFILE_ARGV).get(profile)
        if command is None:
            raise ValueError("Unsupported profile")
        if self._external_server:
            await self._require_server()
        env_args: list[str] = []
        for key, value in PROFILE_ENV.get(profile, ()):
            env_args += ["-e", f"{key}={value}"]
        await self._run(
            "new-session", "-d", "-s", session_id, "-c", directory, *env_args, *command
        )

    async def rename_session(self, session_id: str, name: str) -> None:
        target = self.validate_target(session_id)
        name = self.validate_session_name(name)
        await self._run("rename-session", "-t", target, name)

    async def send_text(self, session_id: str, text: str, pane_id: str | None = None) -> None:
        target = await self._pane_target(session_id, pane_id)
        buffer_name = f"mac-{session_id}"
        await self._run("load-buffer", "-b", buffer_name, "-", stdin=text.encode())
        try:
            # `-r` e' obbligatorio, non un dettaglio: senza, `paste-buffer`
            # sostituisce ogni LF del buffer con un CR, cioe' con un Invio. Il
            # testo multilinea non arriverebbe mai come testo — arriverebbe
            # come righe separate da Invio, e la prima riga partirebbe da sola
            # prima che l'utente possa rileggere. Verificato il 03/08/2026 su
            # tutte le TUI supportate: claude, antigravity e opencode
            # inviavano la prima riga; codex la gestiva gia' correttamente; per
            # una shell il comportamento e' identico nei due casi. L'invio
            # resta un'operazione distinta (`POST /sessions/{id}/keys`), che e'
            # una garanzia di sicurezza, non una comodita'.
            await self._run("paste-buffer", "-b", buffer_name, "-r", "-t", target, "-d")
        except TmuxError:
            await self._run("delete-buffer", "-b", buffer_name)
            raise

    async def send_key(self, session_id: str, key: str, pane_id: str | None = None) -> None:
        tmux_key = ALLOWED_KEYS.get(key)
        if tmux_key is None:
            raise ValueError("Unsupported key")
        target = await self._pane_target(session_id, pane_id)
        await self._run("send-keys", "-t", target, tmux_key)

    async def resize_pane(self, session_id: str, pane_id: str, columns: int, rows: int) -> None:
        target = await self._pane_target(session_id, pane_id)
        await self._run("resize-pane", "-t", target, "-x", str(columns), "-y", str(rows))

    async def kill_pane(self, session_id: str, pane_id: str) -> None:
        target = await self._pane_target(session_id, pane_id)
        await self._run("kill-pane", "-t", target)

    async def split_pane(
        self, session_id: str, pane_id: str | None = None, direction: str = "horizontal"
    ) -> TmuxPane:
        if direction not in {"horizontal", "vertical"}:
            raise ValueError("Unsupported split direction")
        target = await self._pane_target(session_id, pane_id)
        fmt = (
            "#{pane_id}\t#{window_index}\t#{pane_index}\t#{pane_active}"
            "\t#{pane_current_command}\t#{pane_title}\t#{pane_width}\t#{pane_height}"
        )
        direction_flag = "-h" if direction == "horizontal" else "-v"
        raw = await self._run(
            "split-window", direction_flag, "-d", "-P", "-F", fmt, "-t", target, "bash", "-l"
        )
        values = raw.decode(errors="replace").strip().split("\t", 7)
        if len(values) != 8:
            raise TmuxError("Unable to read the new pane")
        raw_id, window, pane, active, command, title, width, height = values
        pane_id = raw_id.removeprefix("%")
        self.validate_pane_id(pane_id)
        return TmuxPane(
            id=pane_id,
            window_index=int(window),
            pane_index=int(pane),
            active=active == "1",
            command=command,
            title=title,
            width=int(width),
            height=int(height),
        )

    async def terminate_session(self, session_id: str) -> None:
        target = self.validate_target(session_id)
        await self._run("kill-session", "-t", target)

    async def pane_path(self, session_id: str, pane_id: str | None = None) -> str:
        target = await self._pane_target(session_id, pane_id)
        raw = await self._run("display-message", "-p", "-t", target, "#{pane_current_path}")
        return raw.decode(errors="replace").strip()
