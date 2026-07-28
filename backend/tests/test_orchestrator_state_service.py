from app.services.orchestrator_state_service import OrchestratorStateService


def test_orchestrator_state_is_loaded_only_when_valid(tmp_path) -> None:
    path = tmp_path / "orchestrator-state.json"
    path.write_text(
        """{
          "schema_version": 1,
          "collected_at": "2026-07-28T12:00:00Z",
          "providers": [{"provider": "claude", "available": false, "primary": {"used_percent": 91, "window_minutes": 300, "resets_at": 4102444800}, "secondary": null}],
          "tasks": [{"task_id": "recOpaque", "task_kind": "weekly-refresh", "status": "paused_provider", "provider": "claude", "execution_mode": "phased", "phase": {"index": 0, "total": 2, "name": "analisi", "interruptible": true}, "capacity_paused": true, "next_attempt_at": "2026-07-28T13:00:00Z", "fallback_providers": ["codex"], "checkpoint_present": true}]
        }""",
        encoding="utf-8",
    )

    state = OrchestratorStateService(str(path)).read()

    assert state is not None
    assert state.tasks[0].fallback_providers == ["codex"]
    assert state.providers[0].primary.used_percent == 91


def test_orchestrator_state_rejects_unsafe_or_invalid_payload(tmp_path) -> None:
    path = tmp_path / "orchestrator-state.json"
    path.write_text('{"schema_version": 2, "tasks": []}', encoding="utf-8")

    assert OrchestratorStateService(str(path)).read() is None
