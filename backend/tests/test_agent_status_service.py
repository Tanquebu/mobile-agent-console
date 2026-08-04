from app.services.agent_status_service import AgentStatusService


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
