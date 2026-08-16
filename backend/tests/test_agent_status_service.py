from pathlib import Path

import pytest

from app.services.agent_status_service import AgentStatusService

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "opencode-tui"


def test_agent_status_classifies_provider_and_terminal_states() -> None:
    service = AgentStatusService(active_window_seconds=8)
    assert service.classify("1", "bash", "$ ", now=0) is None

    authorization = service.classify(
        "1",
        "codex",
        "Would you like to run the following command?\n1. Yes, proceed\n› ",
        now=0,
    )
    assert authorization is not None
    assert authorization.state == "waiting_authorization"

    feedback = service.classify(
        "2",
        "claude",
        "Which implementation should I use?\n> ",
        now=0,
    )
    assert feedback is not None
    assert feedback.state == "waiting_input"

    # docs/backlog.md: richieste di feedback senza "?" letterale restavano
    # "idle" prima di questo fix.
    feedback_no_question_mark = service.classify(
        "10",
        "claude",
        "Fammi sapere se preferisci l'opzione A o l'opzione B.\n> ",
        now=0,
    )
    assert feedback_no_question_mark is not None
    assert feedback_no_question_mark.state == "waiting_input"

    active = service.classify("3", "codex", "• Working (3s • esc to interrupt)", now=0)
    assert active is not None
    assert active.state == "active"

    idle = service.classify("4", "claude", "Task completed.\n> ", now=0)
    assert idle is not None
    assert idle.state == "idle"

    codex_idle_with_footer = service.classify(
        "8",
        "codex",
        "Task completed.\n› Implement {feature}\n"
        "gpt-5.6-terra medium · ~/projects/demo · main · Ask for approval",
        now=0,
    )
    assert codex_idle_with_footer is not None
    assert codex_idle_with_footer.state == "idle"

    claude_idle_with_footer = service.classify(
        "9",
        "claude",
        "Task completed.\n❯ \nClaude Code · auto",
        now=0,
    )
    assert claude_idle_with_footer is not None
    assert claude_idle_with_footer.state == "idle"

    codex_permissions = service.classify(
        "5", "codex", "permissions: Read Only\n› ", now=0
    )
    assert codex_permissions is not None
    assert codex_permissions.permission_state == "restricted"
    claude_permissions = service.classify(
        "6", "claude", "⏵⏵ bypass permissions on\n> ", now=0
    )
    assert claude_permissions is not None
    assert claude_permissions.permission_state == "bypass"

    claude_auto = service.classify(
        "7", "claude", "permission mode: auto\n> ", now=0
    )
    assert claude_auto is not None
    assert claude_auto.permission_state == "auto"


def test_agent_status_narrative_word_before_prompt_does_not_force_active() -> None:
    # docs/backlog.md INC-AS-01: frase reale osservata in produzione. "working"
    # è una parola comune nella prosa italiana/inglese di un riepilogo, non un
    # marker di stato: senza contenuto dopo il prompt il turno è concluso.
    service = AgentStatusService(active_window_seconds=8)
    regression = service.classify(
        "1",
        "claude",
        "Una cosa da sapere: lavora nello stesso working tree.\n❯",
        now=0,
    )
    assert regression is not None
    assert regression.state == "idle"


def test_agent_status_narrative_false_positives_for_all_active_words() -> None:
    # Ognuna delle parole di ACTIVE_PATTERNS può comparire in una frase
    # narrativa ordinaria dopo che il turno è già concluso e il prompt è
    # tornato visibile; nessuna deve produrre "active" da sola.
    service = AgentStatusService(active_window_seconds=8)
    claude_cases = [
        "Ho finito di pensare (thinking) alla soluzione migliore.",
        "Il tool use più adatto qui era il file system, non la rete.",
        "Il comando è stato interrotto con esc to interrupt in un turno precedente.",
    ]
    for index, sentence in enumerate(claude_cases):
        status = service.classify(f"claude-{index}", "claude", f"{sentence}\n> ", now=0)
        assert status is not None, sentence
        assert status.state == "idle", sentence

    codex_cases = [
        "Il file di reasoning è stato archiviato insieme agli altri log.",
        "La working directory è rimasta quella di prima, nessuna modifica.",
        "Ho terminato: esc to interrupt non serve più a questo punto.",
    ]
    for index, sentence in enumerate(codex_cases):
        status = service.classify(f"codex-{index}", "codex", f"{sentence}\n› ", now=0)
        assert status is not None, sentence
        assert status.state == "idle", sentence


def test_agent_status_real_active_marker_without_prompt_stays_active() -> None:
    # Controllo di non regressione simmetrico: un marker attivo reale, senza
    # alcun prompt visibile (il turno è ancora in corso), deve restare "active".
    service = AgentStatusService(active_window_seconds=8)
    claude_active = service.classify(
        "1", "claude", "✻ Thinking… (esc to interrupt · 12s)", now=0
    )
    assert claude_active is not None
    assert claude_active.state == "active"

    codex_active = service.classify(
        "2", "codex", "• Reasoning (8s • esc to interrupt)", now=0
    )
    assert codex_active is not None
    assert codex_active.state == "active"


def test_agent_status_historic_marker_before_prompt_is_idle() -> None:
    # Il marker di attività del turno precedente resta visibile nello scroll
    # sopra il prompt: senza contenuto dopo il prompt il turno è concluso.
    service = AgentStatusService(active_window_seconds=8)
    status = service.classify(
        "1",
        "claude",
        "✻ Thinking… (esc to interrupt · 12s)\n"
        "Fatto, ho aggiornato il file richiesto.\n"
        "> ",
        now=0,
    )
    assert status is not None
    assert status.state == "idle"


def test_agent_status_active_marker_after_prompt_is_still_active() -> None:
    # Se il pane mostra un vecchio prompt seguito da chrome più recente
    # (nuovo comando avviato subito dopo), il marker successivo al prompt
    # è il segnale più recente e deve prevalere: il turno è di nuovo attivo.
    service = AgentStatusService(active_window_seconds=8)
    status = service.classify(
        "1",
        "claude",
        "> altro comando\n✻ Thinking… (esc to interrupt · 3s)",
        now=0,
    )
    assert status is not None
    assert status.state == "active"


def test_agent_status_feedback_question_wins_over_active_word_before_prompt() -> None:
    # Precedenza esplicita: una domanda reale (waiting_input) prevale su una
    # parola "attiva" comparsa nella stessa frase narrativa prima del prompt.
    service = AgentStatusService(active_window_seconds=8)
    status = service.classify(
        "1",
        "claude",
        "Stavo pensando (thinking) a due opzioni. Quale preferisci?\n> ",
        now=0,
    )
    assert status is not None
    assert status.state == "waiting_input"


def test_agent_status_antigravity_prompt_first_guard_ignores_content_change() -> None:
    # Antigravity non ha ACTIVE_PATTERNS testuali (alt-screen, chrome
    # permanente): la presenza del prompt resta la guardia autorevole anche
    # se il contenuto è appena cambiato rispetto all'osservazione precedente.
    service = AgentStatusService(active_window_seconds=8)
    first = service.classify("1", "agy", "Passo 1 di 3 completato.\n> ", now=0)
    assert first is not None
    assert first.state == "idle"
    changed = service.classify("1", "agy", "Passo 2 di 3 completato.\n> ", now=1)
    assert changed is not None
    assert changed.state == "idle"

    # Senza prompt visibile, lo stesso agente torna a dipendere dall'euristica
    # di cambio contenuto già esistente.
    no_prompt_first = service.classify("2", "agy", "Passo 1 di 3", now=0)
    assert no_prompt_first is not None
    assert no_prompt_first.state == "unknown"
    no_prompt_changed = service.classify("2", "agy", "Passo 2 di 3", now=1)
    assert no_prompt_changed is not None
    assert no_prompt_changed.state == "active"


def test_agent_status_summary_filters_ui_chrome_and_truncates() -> None:
    service = AgentStatusService(active_window_seconds=8)
    status = service.classify(
        "1",
        "claude",
        "› Sistema le date del changelog\n"
        "⏺ Read changelog.md\n"
        "──────\n"
        "Ho aggiornato le date nel changelog per riflettere il rilascio corrente.\n"
        "> ",
        now=0,
    )
    assert status is not None
    assert status.summary == (
        "Ho aggiornato le date nel changelog per riflettere il rilascio corrente."
    )

    long_line = "parola " * 40
    truncated = service.classify("2", "claude", long_line, now=0)
    assert truncated is not None
    assert truncated.summary is not None
    assert len(truncated.summary) <= 140
    assert truncated.summary.endswith("…")

    no_prose = service.classify("3", "claude", "› \n⏺ Bash\n> ", now=0)
    assert no_prose is not None
    assert no_prose.summary is None


def test_agent_status_uses_recent_output_changes_and_forgets_sessions() -> None:
    service = AgentStatusService(active_window_seconds=8)
    first = service.classify("1", "codex", "compiling", now=10)
    assert first is not None
    assert first.state == "unknown"
    changed = service.classify("1", "codex", "compiling.", now=20)
    assert changed is not None
    assert changed.state == "active"
    stable = service.classify("1", "codex", "compiling.", now=29)
    assert stable is not None
    assert stable.state == "unknown"
    service.forget_missing(set())
    observed_again = service.classify("1", "codex", "compiling.", now=30)
    assert observed_again is not None
    assert observed_again.state == "unknown"


@pytest.mark.parametrize(
    ("fixture", "expected_state", "expected_permission"),
    [
        ("01-idle.txt", "idle", "ask"),
        ("02-prompt-inserito.txt", "idle", "ask"),
        ("03-attivo.txt", "active", "ask"),
        ("04-completato.txt", "idle", "ask"),
        ("05-conferma-interrupt.txt", "active", "ask"),
        ("06-interrotto.txt", "idle", "ask"),
        ("07-autorizzazione.txt", "waiting_authorization", "ask"),
    ],
)
def test_agent_status_opencode_fixtures(
    fixture: str, expected_state: str, expected_permission: str
) -> None:
    # OC-03: il classificatore OpenCode è costruito sui frame reali della TUI
    # (tests/fixtures/opencode-tui/README.md, spike IMP-OC-00), non sui
    # pattern presi in prestito da Codex o Claude. Ogni frame va letto con il
    # servizio "vergine" (stessa sessione "opencode", now=0), perché le
    # osservazioni precedenti dello stesso service potrebbero pilotare lo
    # stato attraverso l'euristica di cambio contenuto.
    service = AgentStatusService(active_window_seconds=8)
    content = (FIXTURES_DIR / fixture).read_text(encoding="utf-8")
    status = service.classify("opencode", "opencode", content, now=0)
    assert status is not None
    assert status.state == expected_state, fixture
    assert status.permission_state == expected_permission, fixture


def test_agent_status_opencode_typed_prompt_stays_idle() -> None:
    # docs/backlog.md OC-03: un "?" letterale nel testo ancora nell'input
    # (non inviato) non deve diventare waiting_input. OpenCode non ha un
    # prompt ">", quindi il ramo feedback (che richiede prompt_index) è
    # sempre saltato; il testo nell'input bar (bordo "┃") resta idle.
    service = AgentStatusService(active_window_seconds=8)
    content = (FIXTURES_DIR / "02-prompt-inserito.txt").read_text(encoding="utf-8")
    status = service.classify("opencode", "opencode", content, now=0)
    assert status is not None
    assert status.state == "idle"
    assert status.summary is None


def test_agent_status_opencode_summary_filters_tui_chrome() -> None:
    # Il riepilogo del frame completato deve contenere la prosa del turno
    # ("2 righe."), senza il chrome della TUI (logo, bordo "┃", barra di
    # avanzamento, footer, stato del modello "1.18.11", durate).
    service = AgentStatusService(active_window_seconds=8)
    content = (FIXTURES_DIR / "04-completato.txt").read_text(encoding="utf-8")
    status = service.classify("opencode", "opencode", content, now=0)
    assert status is not None
    assert status.summary is not None
    assert "2 righe." in status.summary
    assert "esc interrupt" not in status.summary
    assert "ctrl+p" not in status.summary
    assert "1.18.11" not in status.summary


# Frammenti sintetici del pannello subagent del footer di Claude Code,
# trascritti da quattro screenshot reali (non capture-pane grezzo) di una
# sessione di test dedicata ("Test sessione subagent Claude", 16/08/2026):
# a riposo il footer termina con "for agents" e nient'altro sotto; con
# subagent attivi compare subito dopo, senza interazione, un blocco
# "● <branch>" seguito da una riga "○ <tipo agente>   <descrizione>" per
# ciascun subagent, più una riga di metriche indentata che non inizia con
# "○" (tempo e token, non contata). Verificato anche nella vista "Blocchi"
# (stesso testo, solo reimpaginato lato client) e nel transcript inline
# ("● Agent(<descrizione>)" + "⎿ Backgrounded agent" + "⎿ Allowed by auto
# mode classifier" + verbo di stato casuale "Kneading…"), non usato qui
# come fonte: il verbo non è deterministico (come "Thinking…"/"Working…"
# per il turno principale), il pannello del footer sì.
_CLAUDE_FOOTER_NO_SUBAGENT = (
    "Fatto, ho aggiornato il file richiesto.\n"
    "> \n"
    "Sonnet 5 | /home/max/projects/demo | main |...\n"
    "⏵⏵ auto mode on (shift+tab to cycle) · ← for agents"
)
_CLAUDE_FOOTER_ONE_SUBAGENT = (
    "Fatto, ho aggiornato il file richiesto.\n"
    "> \n"
    "Sonnet 5 | /home/max/projects/demo | main |...\n"
    "⏵⏵ auto mode on (shift+tab to cycle) · ← for agents\n"
    "\n"
    "● main\n"
    "\n"
    "○ general-purpose   Ricognizione overview progetti\n"
    "     9s · ↓ 43.3k tokens"
)
_CLAUDE_FOOTER_TWO_SUBAGENTS = (
    "Fatto, ho aggiornato il file richiesto.\n"
    "> \n"
    "Sonnet 5 | /home/max/projects/demo | main |...\n"
    "⏵⏵ auto mode on (shift+tab to cycle) · ← for agents\n"
    "\n"
    "● main\n"
    "○ general-purpose   Ricognizione overview progetti\n"
    "     16s · ↓ 43.4k tokens\n"
    "○ general-purpose   Ricognizione profilo.md vs sviluppi recenti\n"
    "     4s · ↓ 31.6k tokens"
)


@pytest.mark.parametrize(
    ("content", "expected_count"),
    [
        (_CLAUDE_FOOTER_NO_SUBAGENT, 0),
        (_CLAUDE_FOOTER_ONE_SUBAGENT, 1),
        (_CLAUDE_FOOTER_TWO_SUBAGENTS, 2),
    ],
)
def test_agent_status_claude_subagent_panel_counts_active_subagents(
    content: str, expected_count: int
) -> None:
    service = AgentStatusService(active_window_seconds=8)
    status = service.classify("1", "claude", content, now=0)
    assert status is not None
    assert status.subagent_count == expected_count


def test_agent_status_subagent_panel_ignored_for_other_providers() -> None:
    # Il pannello è verificato solo su Claude Code: per gli altri provider il
    # conteggio resta 0 anche se lo stesso testo comparisse per coincidenza,
    # piuttosto che indovinare un pattern senza prova (stessa disciplina di
    # SUBAGENT_PANEL_ANCHOR).
    service = AgentStatusService(active_window_seconds=8)
    content = _CLAUDE_FOOTER_TWO_SUBAGENTS.replace("> ", "› ")
    status = service.classify("1", "codex", content, now=0)
    assert status is not None
    assert status.subagent_count == 0


def test_agent_status_subagent_count_scoped_after_for_agents_anchor() -> None:
    # Disciplina anti-INC-AS-01: una riga "○ ..." comparsa nella prosa prima
    # dell'ancora "for agents" (es. citata in un riepilogo di un turno
    # precedente) non deve essere contata — solo le righe dopo l'ancora più
    # recente sono il pannello live.
    service = AgentStatusService(active_window_seconds=8)
    content = (
        "○ questa non è una riga del pannello, solo testo citato nel turno.\n"
        + _CLAUDE_FOOTER_ONE_SUBAGENT
    )
    status = service.classify("1", "claude", content, now=0)
    assert status is not None
    assert status.subagent_count == 1


def test_agent_status_subagent_count_defaults_to_zero_without_panel() -> None:
    # Regressione: nessuna delle sessioni Claude "normali" già coperte dai
    # test precedenti mostra il pannello subagent; il campo deve restare 0
    # senza influenzare lo stato calcolato.
    service = AgentStatusService(active_window_seconds=8)
    status = service.classify("1", "claude", "Task completed.\n> ", now=0)
    assert status is not None
    assert status.state == "idle"
    assert status.subagent_count == 0
    assert "· 10.1s" not in status.summary
