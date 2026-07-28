import hashlib
import re
import time
from dataclasses import dataclass
from typing import Literal

AgentProvider = Literal["codex", "claude"]
AgentState = Literal[
    "active",
    "idle",
    "waiting_input",
    "waiting_authorization",
    "unknown",
]
PermissionState = Literal[
    "restricted",
    "standard",
    "elevated",
    "bypass",
    "plan",
    "ask",
    "auto",
    "manual",
    "accept_edits",
    "dont_ask",
    "unknown",
]

AUTHORIZATION_PATTERNS = {
    "codex": (
        r"would you like to run",
        r"allow (?:this )?command",
        r"yes,\s*(?:proceed|and don't ask again)",
        r"press enter to confirm",
    ),
    "claude": (
        r"do you want to proceed",
        r"allow (?:this )?(?:command|tool)",
        r"yes,\s*(?:proceed|and don't ask again)",
        r"esc to cancel",
    ),
}
# Non solo "?" letterale: frasi come "fammi sapere se..."/"dimmi quando..."
# sono altrettanto una richiesta di feedback ma non terminano con punto
# interrogativo, e restavano classificate "idle" (docs/backlog.md).
FEEDBACK_REQUEST_PATTERNS = (
    r"\?",
    r"\blet me know\b",
    r"\btell me\b",
    r"\bfammi sapere\b",
    r"\bdimmi (?:se|quando|cosa|come)\b",
    r"\bavvisami\b",
    r"\bconfermami\b",
    r"\bfammi un fischio\b",
)
ACTIVE_PATTERNS = {
    "codex": (
        r"\bworking\b",
        r"\breasoning\b",
        r"\bthinking\b",
        r"esc to interrupt",
    ),
    "claude": (
        r"\bworking\b",
        r"\bthinking\b",
        r"\btool use\b",
        r"esc to interrupt",
    ),
}
PROMPT_PATTERNS = {
    "codex": re.compile(r"^\s*[›>]\s*"),
    "claude": re.compile(r"^\s*[>❯]\s*"),
}
# Righe di "chrome" dell'interfaccia (prompt, marcatori di tool/attività,
# separatori, barre di stato, suggerimenti tastiera) da escludere dal
# riepilogo euristico: non è un parser degli stessi blocchi di chatBlocks()
# (frontend), solo un filtro leggero per non includere queste righe nel
# testo estratto. Verificato su output reali di Claude Code e Codex.
SUMMARY_NOISE_PREFIX = re.compile(
    r"^\s*(?:[›❯>•●◻☐]|✔|✘|✱|✻|✽|✢|✳|✶|⏺|⏵⏵|\d+\.\s|─{3,}|Ran\b|Explored\b|Read\b|Edited\b)"
)
SUMMARY_NOISE_ANYWHERE = re.compile(
    r"─{3,}"
    r"|Enter to (?:select|confirm)"
    r"|Esc to cancel"
    r"|to navigate"
    r"|/clear to"
    r"|/config to"
    r"|ctx:\s*\d"
    r"|\d+k\s*/\s*\d+k"
    r"|\bWorked for\b"
    r"|\buncached\b"
    r"|auto mode on"
    r"|shift\+tab to cycle"
    r"|for agents\b",
    re.IGNORECASE,
)
# Barra di stato tipica ("Sonnet 5 | ~/percorso | main | ..." lato Claude,
# "gpt-5.6-terra medium · ~/percorso · main · ..." lato Codex): due o più
# separatori "|" oppure "·" nella stessa riga.
SUMMARY_STATUS_BAR = re.compile(r"(?:\s\|\s.*){2,}|(?:\s·\s.*){2,}")
SUMMARY_MAX_CHARS = 140


@dataclass(frozen=True)
class AgentStatus:
    provider: AgentProvider
    state: AgentState
    detail: str
    changed_at: float
    permission_state: PermissionState
    permission_detail: str
    summary: str | None = None


class AgentStatusService:
    def __init__(self, active_window_seconds: int = 8) -> None:
        self.active_window_seconds = active_window_seconds
        self._observations: dict[str, tuple[str, float]] = {}

    @staticmethod
    def provider_for(command: str) -> AgentProvider | None:
        lowered = command.lower()
        if "codex" in lowered:
            return "codex"
        if "claude" in lowered:
            return "claude"
        return None

    @staticmethod
    def _matches(patterns: tuple[str, ...], content: str) -> bool:
        return any(re.search(pattern, content, re.IGNORECASE) for pattern in patterns)

    def classify(
        self,
        session_id: str,
        command: str,
        content: str,
        now: float | None = None,
    ) -> AgentStatus | None:
        provider = self.provider_for(command)
        if provider is None:
            self._observations.pop(session_id, None)
            return None
        observed_now = time.monotonic() if now is None else now
        digest = hashlib.sha256(content.encode()).hexdigest()
        previous = self._observations.get(session_id)
        changed_at = (
            observed_now
            if previous is None or previous[0] != digest
            else previous[1]
        )
        self._observations[session_id] = (digest, changed_at)

        normalized = "\n".join(line.rstrip() for line in content.splitlines())
        nonempty = [line for line in normalized.splitlines() if line.strip()]
        tail = "\n".join(nonempty[-20:])
        recent_lines = nonempty[-8:]
        prompt_index = next(
            (
                index
                for index in range(len(recent_lines) - 1, -1, -1)
                if PROMPT_PATTERNS[provider].match(recent_lines[index])
            ),
            None,
        )

        permission_state, permission_detail = self._permission(provider, nonempty[-8:])
        summary = self._summarize(nonempty)

        if self._matches(AUTHORIZATION_PATTERNS[provider], tail):
            return AgentStatus(
                provider,
                "waiting_authorization",
                "Attende autorizzazione",
                changed_at,
                permission_state,
                permission_detail,
                summary,
            )
        if (
            prompt_index is not None
            and self._matches(
                FEEDBACK_REQUEST_PATTERNS,
                "\n".join(recent_lines[max(0, prompt_index - 4) : prompt_index]),
            )
        ):
            return AgentStatus(
                provider,
                "waiting_input",
                "Attende feedback",
                changed_at,
                permission_state,
                permission_detail,
                summary,
            )
        if self._matches(ACTIVE_PATTERNS[provider], tail):
            return AgentStatus(
                provider,
                "active",
                "Elaborazione in corso",
                changed_at,
                permission_state,
                permission_detail,
                summary,
            )
        if previous is not None and observed_now - changed_at <= self.active_window_seconds:
            return AgentStatus(
                provider,
                "active",
                "Output in aggiornamento",
                changed_at,
                permission_state,
                permission_detail,
                summary,
            )
        if prompt_index is not None:
            return AgentStatus(
                provider,
                "idle",
                "Inattivo o completato",
                changed_at,
                permission_state,
                permission_detail,
                summary,
            )
        return AgentStatus(
            provider,
            "unknown",
            "Stato non riconosciuto",
            changed_at,
            permission_state,
            permission_detail,
            summary,
        )

    @staticmethod
    def _is_noise(line: str) -> bool:
        return bool(
            SUMMARY_NOISE_PREFIX.match(line)
            or SUMMARY_NOISE_ANYWHERE.search(line)
            or SUMMARY_STATUS_BAR.search(line)
        )

    @staticmethod
    def _summarize(nonempty_lines: list[str]) -> str | None:
        prose = [
            line.strip()
            for line in nonempty_lines
            if line.strip() and not AgentStatusService._is_noise(line)
        ]
        if not prose:
            return None
        text = re.sub(r"\s+", " ", " ".join(prose[-3:])).strip()
        if not text:
            return None
        if len(text) > SUMMARY_MAX_CHARS:
            text = f"{text[: SUMMARY_MAX_CHARS - 1].rstrip()}…"
        return text

    @staticmethod
    def _permission(
        provider: AgentProvider, lines: list[str]
    ) -> tuple[PermissionState, str]:
        tail = "\n".join(lines).lower()
        if provider == "codex":
            patterns = (
                ("bypass", "Accesso completo", r"(?:›|permissions?:)\s*.*full access"),
                ("restricted", "Sola lettura", r"(?:›|permissions?:)\s*.*read only"),
                ("auto", "Auto", r"(?:›|permissions?:)\s*.*\bauto\b"),
            )
        else:
            patterns = (
                ("bypass", "Bypass autorizzazioni", r"bypass permissions"),
                ("plan", "Plan mode", r"plan mode"),
                ("accept_edits", "Accetta modifiche", r"accept(?:edits| edits)"),
                ("dont_ask", "Non chiedere", r"don'?t ask|dontask"),
                ("manual", "Permessi manuali", r"manual mode"),
                ("auto", "Auto", r"permission mode:\s*auto"),
            )
        for state, detail, pattern in patterns:
            if re.search(pattern, tail, re.IGNORECASE):
                return state, detail  # type: ignore[return-value]
        return "unknown", "Livello permessi non rilevato"

    def forget_missing(self, session_ids: set[str]) -> None:
        for session_id in set(self._observations) - session_ids:
            del self._observations[session_id]
