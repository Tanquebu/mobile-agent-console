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


@dataclass(frozen=True)
class AgentStatus:
    provider: AgentProvider
    state: AgentState
    detail: str
    changed_at: float
    permission_state: PermissionState
    permission_detail: str


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

        if self._matches(AUTHORIZATION_PATTERNS[provider], tail):
            return AgentStatus(
                provider,
                "waiting_authorization",
                "Attende autorizzazione",
                changed_at,
                permission_state,
                permission_detail,
            )
        if (
            prompt_index is not None
            and any(
                line.rstrip().endswith("?")
                for line in recent_lines[max(0, prompt_index - 4) : prompt_index]
            )
        ):
            return AgentStatus(
                provider,
                "waiting_input",
                "Attende feedback",
                changed_at,
                permission_state,
                permission_detail,
            )
        if self._matches(ACTIVE_PATTERNS[provider], tail):
            return AgentStatus(
                provider,
                "active",
                "Elaborazione in corso",
                changed_at,
                permission_state,
                permission_detail,
            )
        if previous is not None and observed_now - changed_at <= self.active_window_seconds:
            return AgentStatus(
                provider,
                "active",
                "Output in aggiornamento",
                changed_at,
                permission_state,
                permission_detail,
            )
        if prompt_index is not None:
            return AgentStatus(
                provider,
                "idle",
                "Inattivo o completato",
                changed_at,
                permission_state,
                permission_detail,
            )
        return AgentStatus(
            provider,
            "unknown",
            "Stato non riconosciuto",
            changed_at,
            permission_state,
            permission_detail,
        )

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
