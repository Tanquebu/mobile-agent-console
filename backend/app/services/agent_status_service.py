import hashlib
import re
import time
from dataclasses import dataclass
from typing import Literal

AgentProvider = Literal["codex", "claude", "antigravity", "opencode"]
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
    "antigravity": (
        r"do you want to proceed",
        r"allow (?:this )?(?:command|tool|action)",
        r"approve",
        r"(?:yes|no|always)\s*(?:proceed|allow)",
    ),
    "opencode": (
        r"Permission required",
        r"Allow once",
        r"Allow always",
        r"Reject",
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
    "antigravity": (
        # In alt-screen mode il frame catturato contiene chrome permanente
        # (incluso "esc to interrupt") e l'output precedente.  Qualsiasi
        # pattern testuale produce falsi positivi; lo stato attivo è
        # rilevato esclusivamente dall'euristica di cambio contenuto
        # (step 4 di classify), con la guardia prompt-first sotto.
    ),
    "opencode": (
        # Footer della TUI durante un turno: "esc interrupt" (03-attivo) o
        # "esc again to interrupt" dopo il primo Escape (05-conferma-interrupt).
        # Spinner "⠏ Thinking" (05). La barra di avanzamento "⬝" compare solo
        # nei frame attivi. Nota dal README del fixture: resta da verificare su
        # round più lunghi se "esc interrupt" sopravviva alla fine del turno —
        # è il modo in cui il problema si è manifestato altrove (INC-AS-01).
        r"esc (?:again to )?interrupt",
        r"⠏\s*Thinking",
        r"⬝",
    ),
}
# Marker di inattività esplicita della TUI OpenCode, verificati sui frame reali:
# - "Ask anything..." e "● Tip Run /connect": schermata iniziale, nessun turno;
# - "+ Thought:" : pensiero completato (04-completato, 06-interrotto);
# - "· interrupted" : turno interrotto (06);
# - "· 10.1s" : durata di un turno concluso (04).
# Questi marker prevalgono sull'euristica di cambio contenuto (step 4), così un
# turno appena concluso resta "idle" anche se l'output è appena cambiato.
IDLE_PATTERNS = {
    "opencode": (
        r"Ask anything",
        r"● Tip",
        r"\+ Thought:",
        r"· interrupted",
        r"· \d+(?:\.\d+)?[a-z]+",
    ),
}
PROMPT_PATTERNS = {
    "codex": re.compile(r"^\s*[›>]\s*"),
    "claude": re.compile(r"^\s*[>❯]\s*"),
    "antigravity": re.compile(r"^\s*>\s*"),
}
# Righe di "chrome" dell'interfaccia (prompt, marcatori di tool/attività,
# separatori, barre di stato, suggerimenti tastiera) da escludere dal
# riepilogo euristico: non è un parser degli stessi blocchi di chatBlocks()
# (frontend), solo un filtro leggero per non includere queste righe nel
# testo estratto. Verificato su output reali di Claude Code, Codex e sui
# fixture OpenCode (logo, bordo "┃", barra "╹▀▀▀", footer, stato modello).
SUMMARY_NOISE_PREFIX = re.compile(
    r"^\s*(?:[›❯>•●◻☐┃╹▣⬝⠏△]|✔|✘|✱|✻|✽|✢|✳|✶|⏺|⏵⏵|\d+\.\s|─{3,}|[█▀▄]+(?:\s+[█▀▄]+)*\s*$|Ran\b|Explored\b|Read\b|Edited\b)"
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
    r"|for agents\b"
    r"|ctrl\+p commands"
    r"|tab agents"
    r"|Ask anything"
    r"|Run /connect"
    r"|esc (?:again to )?interrupt"
    r"|\+ Thought:"
    r"|\d+\.\d+K\s*\(\d+%\)"
    r"|\d+\.\d+\.\d+$",
    re.IGNORECASE,
)
# Barra di stato tipica ("Sonnet 5 | ~/percorso | main | ..." lato Claude,
# "gpt-5.6-terra medium · ~/percorso · main · ..." lato Codex): due o più
# separatori "|" oppure "·" nella stessa riga.
SUMMARY_STATUS_BAR = re.compile(r"(?:\s\|\s.*){2,}|(?:\s·\s.*){2,}")
SUMMARY_MAX_CHARS = 140
# Bordo del pannello TUI OpenCode ("┃ "): a differenza degli altri marker in
# SUMMARY_NOISE_PREFIX, il bordo da solo non significa "riga di chrome" — è
# usato per QUALSIASI contenuto del pannello attivo, incluso il dialogo di
# autorizzazione ("△ Permission required", nome del comando). _summarize()
# lo tratta comunque come rumore (corretto per lo stato idle: vedi
# test_agent_status_opencode_typed_prompt_stays_idle, il testo nella input
# bar non ancora inviato non deve comparire nel riepilogo). Per il ramo
# waiting_authorization serve invece leggere dentro il bordo: vedi
# _summarize_authorization.
OPENCODE_BORDER = re.compile(r"^\s*┃\s*")
# Icone decorative che possono precedere il testo utile dentro il bordo
# (es. "△ Permission required"): da rimuovere, non da usare per scartare
# l'intera riga.
LEADING_DECORATION = re.compile(r"^[△✔✘✱✻✽✢✳✶⏺⠏]\s*")
# Riga dei pulsanti del dialogo di conferma OpenCode ("Allow once   Allow
# always   Reject  ctrl+f fullscreen  ⇆ select  enter con..."): chrome puro.
OPENCODE_CONFIRM_BUTTONS = re.compile(r"Allow once\s+Allow always\s+Reject")

# Pannello subagent del footer di Claude Code: quando almeno un subagent
# (tool "Agent(...)", fan-out) è in esecuzione, sotto la barra di stato
# compare automaticamente (nessuna interazione richiesta) un blocco
# "● <branch>" seguito da una riga "○ <tipo agente>   <descrizione>" per
# ciascun subagent attivo, più una riga di metriche indentata (tempo e
# token) che non inizia con "○" e quindi non viene contata. Verificato su
# quattro catture reali (screenshot, non capture-pane grezzo, sessione di
# test dedicata — vedi trascrizione in agent_status_service task, non un
# fixture testuale originale): a riposo il footer termina con la riga
# "for agents" e nient'altro sotto; con subagent attivi il pannello compare
# subito dopo, senza dover premere la freccia suggerita dall'hint. Il verbo
# di stato nel transcript ("Kneading…", ecc., marker A, non usato qui) è
# casuale come "Thinking…"/"Working…" per il turno principale — per questo
# il segnale scelto è il pannello strutturato del footer, non il testo del
# transcript. La riga "for agents" è l'ancora: si contano solo le righe "○"
# che compaiono *dopo* di essa nella finestra recente (stessa disciplina
# "scope sul segnale più recente" di INC-AS-01, non un match su tutto il
# buffer), così una menzione testuale di "for agents" o "○" più in alto nello
# scroll non genera un conteggio falso.
SUBAGENT_PANEL_ANCHOR = re.compile(r"for agents\b")
SUBAGENT_ENTRY_PATTERN = re.compile(r"^\s*○\s+\S")


@dataclass(frozen=True)
class AgentStatus:
    provider: AgentProvider
    state: AgentState
    detail: str
    changed_at: float
    permission_state: PermissionState
    permission_detail: str
    summary: str | None = None
    # Numero di subagent (tool "Agent(...)") live nel pannello del footer,
    # non uno storico: 0 quando non rilevato o non applicabile al provider.
    subagent_count: int = 0


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
        if "agy" in lowered or "antigravity" in lowered:
            return "antigravity"
        if "opencode" in lowered:
            return "opencode"
        return None

    @staticmethod
    def _matches(patterns: tuple[str, ...], content: str) -> bool:
        return any(re.search(pattern, content, re.IGNORECASE) for pattern in patterns)

    @staticmethod
    def _count_subagents(provider: AgentProvider, lines: list[str]) -> int:
        # Solo Claude Code espone il pannello subagent del footer (verificato
        # sugli screenshot reali, vedi SUBAGENT_PANEL_ANCHOR sopra); per gli
        # altri provider il segnale non è ancora verificato, quindi resta 0
        # piuttosto che indovinare un pattern senza prova.
        if provider != "claude":
            return 0
        anchor = next(
            (
                index
                for index in range(len(lines) - 1, -1, -1)
                if SUBAGENT_PANEL_ANCHOR.search(lines[index])
            ),
            None,
        )
        if anchor is None:
            return 0
        return sum(
            1 for line in lines[anchor + 1 :] if SUBAGENT_ENTRY_PATTERN.match(line)
        )

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
        # OpenCode non ha un prompt ">" come Codex/Claude: la barra di input
        # (bordo "┃") è sempre visibile, in ogni stato. La guardia prompt-first
        # non si applica: niente PROMPT_PATTERNS["opencode"], quindi prompt_index
        # resta None e il ramo prompt (feedback/idle) viene saltato.
        prompt_index = next(
            (
                index
                for index in range(len(recent_lines) - 1, -1, -1)
                if PROMPT_PATTERNS.get(provider) is not None
                and PROMPT_PATTERNS[provider].match(recent_lines[index])
            ),
            None,
        )

        permission_state, permission_detail = self._permission(provider, nonempty[-8:])
        summary = self._summarize(nonempty)
        # Calcolato una sola volta, indipendentemente dal ramo di stato: un
        # subagent può restare in esecuzione mentre il turno principale è
        # "idle" in attesa del suo risultato, quindi non è legato a nessuno
        # stato specifico.
        subagent_count = self._count_subagents(provider, nonempty[-20:])

        if self._matches(AUTHORIZATION_PATTERNS[provider], tail):
            # Solo OpenCode borda ogni riga del pannello con "┃": per gli altri
            # provider _summarize() già produce un riepilogo corretto del
            # dialogo di autorizzazione, quindi restano invariati.
            authorization_summary = (
                self._summarize_authorization(recent_lines) if provider == "opencode" else None
            )
            return AgentStatus(
                provider,
                "waiting_authorization",
                "Attende autorizzazione",
                changed_at,
                permission_state,
                permission_detail,
                authorization_summary or summary,
                subagent_count,
            )
        if prompt_index is not None:
            before_prompt = "\n".join(
                recent_lines[max(0, prompt_index - 4) : prompt_index]
            )
            if self._matches(FEEDBACK_REQUEST_PATTERNS, before_prompt):
                return AgentStatus(
                    provider,
                    "waiting_input",
                    "Attende feedback",
                    changed_at,
                    permission_state,
                    permission_detail,
                    summary,
                    subagent_count,
                )
            # Il prompt inattivo è il segnale più recente disponibile: un
            # marker attivo (parola generica come "working"/"thinking" o
            # "esc to interrupt") conta solo se compare *dopo* il prompt,
            # cioè più di recente di esso. Se compare solo nella prosa prima
            # del prompt — narrativa reale ("lavora nello stesso working
            # tree") o chrome storico di un turno già concluso — non è più
            # attuale e non deve sovrascrivere l'inattività: è esattamente
            # la causa di INC-AS-01 (docs/backlog.md). Per gli agenti senza
            # `ACTIVE_PATTERNS` (Antigravity) questo ramo non trova mai un
            # match ed è quindi sempre "idle" in presenza di prompt: è la
            # guardia prompt-first già usata per la loro euristica di
            # cambio contenuto, qui estesa a tutti i provider.
            after_prompt = "\n".join(recent_lines[prompt_index + 1 :])
            if after_prompt and self._matches(ACTIVE_PATTERNS[provider], after_prompt):
                return AgentStatus(
                    provider,
                    "active",
                    "Elaborazione in corso",
                    changed_at,
                    permission_state,
                    permission_detail,
                    summary,
                    subagent_count,
                )
            return AgentStatus(
                provider,
                "idle",
                "Inattivo o completato",
                changed_at,
                permission_state,
                permission_detail,
                summary,
                subagent_count,
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
                subagent_count,
            )
        if self._matches(IDLE_PATTERNS.get(provider, ()), tail):
            return AgentStatus(
                provider,
                "idle",
                "Inattivo o completato",
                changed_at,
                permission_state,
                permission_detail,
                summary,
                subagent_count,
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
                subagent_count,
            )
        return AgentStatus(
            provider,
            "unknown",
            "Stato non riconosciuto",
            changed_at,
            permission_state,
            permission_detail,
            summary,
            subagent_count,
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
    def _summarize_authorization(recent_lines: list[str]) -> str | None:
        # Variante di _summarize() usata solo per il ramo waiting_authorization
        # di OpenCode (vedi OPENCODE_BORDER sopra): rimuove il bordo "┃" invece
        # di trattarlo come marker di riga-intera-rumore, per non perdere il
        # testo del dialogo di autorizzazione ("Permission required", nome del
        # comando) che nella TUI OpenCode è bordato come tutto il resto.
        prose = []
        for line in recent_lines:
            without_border = OPENCODE_BORDER.sub("", line).strip()
            if not without_border or OPENCODE_CONFIRM_BUTTONS.search(without_border):
                continue
            without_border = LEADING_DECORATION.sub("", without_border).strip()
            if without_border and not (
                SUMMARY_NOISE_ANYWHERE.search(without_border)
                or SUMMARY_STATUS_BAR.search(without_border)
            ):
                prose.append(without_border)
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
        elif provider == "antigravity":
            # AGY usa Shift-Tab per ciclare le modalità, come Claude.
            # La status bar mostra [accept-edits], [plan], [auto], ecc.
            patterns = (
                ("bypass", "Bypass autorizzazioni", r"bypass permissions"),
                ("plan", "Plan mode", r"\bplan\b.*mode|\[plan\]"),
                ("accept_edits", "Accetta modifiche", r"accept.?edits|\[accept-edits\]"),
                ("dont_ask", "Non chiedere", r"don'?t ask|\[dont-ask\]"),
                ("auto", "Auto", r"\bauto\b.*mode|\[auto\]"),
            )
        elif provider == "opencode":
            # La TUI OpenCode non espone un indicatore di modalità permessi
            # nella status bar come Codex/Claude; il profilo OpenCode è
            # conservativo (bash/edit → ask, tmux_service.py), quindi il
            # default coerente è "ask". La box di autorizzazione (07) resta
            # uno stato `waiting_authorization` a sé, non un cambio di mode.
            return "ask", "Chiede conferma"
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
