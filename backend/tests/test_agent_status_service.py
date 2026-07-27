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
