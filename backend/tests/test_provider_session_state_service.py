from app.services.provider_session_state_service import ProviderSessionStateService


def test_provider_session_states_are_sanitized(tmp_path) -> None:
    path = tmp_path / "states.json"
    path.write_text(
        '{"sessions":['
        '{"session_id":"14","permission_state":"restricted","permission_detail":"Sola lettura"},'
        '{"session_id":"bad","permission_state":"bypass","permission_detail":"no"},'
        '{"session_id":"20","permission_state":"invalid","permission_detail":"no"}'
        "]}",
        encoding="utf-8",
    )
    states = ProviderSessionStateService(str(path)).read()
    assert list(states) == ["14"]
    assert states["14"].permission_state == "restricted"
    assert states["14"].permission_detail == "Sola lettura"


def test_provider_session_states_tolerate_missing_or_invalid_files(tmp_path) -> None:
    assert ProviderSessionStateService(str(tmp_path / "missing.json")).read() == {}
    path = tmp_path / "invalid.json"
    path.write_text("not-json", encoding="utf-8")
    assert ProviderSessionStateService(str(path)).read() == {}
