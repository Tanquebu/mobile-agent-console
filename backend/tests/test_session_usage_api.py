import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.fakes import FakeTmux

PASSWORD = "a-secure-test-password"
SECRET = "a-secure-session-secret-value"


def usage_row(bucket_start: str, **overrides: object) -> dict:
    row = {
        "bucket_start": bucket_start,
        "provider": "claude",
        "session_uuid": "5b84b3fa-a26f-4642-abf3-851fc35abf3f",
        "origin": "headless",
        "project": "mobile-agent-console",
        "model": "claude-opus-5",
        "is_subagent": False,
        "turns": 1,
        "input_tokens": 10,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "output_tokens": 5,
    }
    row.update(overrides)
    return row


def legacy_client(**overrides: object) -> TestClient:
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        **overrides,
    )
    return TestClient(create_app(settings, FakeTmux()))


def login(client: TestClient) -> str:
    response = client.post("/api/v1/auth/login", json={"password": PASSWORD})
    assert response.status_code == 200
    return response.json()["csrf_token"]


def test_session_usage_returns_404_when_disabled() -> None:
    client = legacy_client(session_usage_enabled=False)
    login(client)

    response = client.get("/api/v1/session-usage")

    assert response.status_code == 404


def test_session_usage_returns_report_when_enabled(tmp_path: Path) -> None:
    path = tmp_path / "session-usage-history.jsonl"
    path.write_text(json.dumps(usage_row("2026-08-02T09:30:00+00:00")) + "\n", encoding="utf-8")
    client = legacy_client(session_usage_enabled=True, session_usage_path=str(path))
    login(client)

    response = client.get("/api/v1/session-usage")

    assert response.status_code == 200
    body = response.json()
    assert len(body["entries"]) == 1
    assert body["entries"][0]["session_uuid"] == "5b84b3fa-a26f-4642-abf3-851fc35abf3f"


def test_session_usage_missing_file_returns_empty_report_not_500(tmp_path: Path) -> None:
    path = tmp_path / "missing-history.jsonl"
    client = legacy_client(session_usage_enabled=True, session_usage_path=str(path))
    login(client)

    response = client.get("/api/v1/session-usage")

    assert response.status_code == 200
    assert response.json()["entries"] == []


def test_session_usage_requires_an_active_session() -> None:
    client = legacy_client(session_usage_enabled=True)

    response = client.get("/api/v1/session-usage")

    assert response.status_code == 401


def test_session_usage_hours_query_filters_the_horizon(tmp_path: Path) -> None:
    from datetime import UTC, datetime, timedelta

    path = tmp_path / "session-usage-history.jsonl"
    now = datetime.now(UTC)
    stale = usage_row((now - timedelta(hours=48)).isoformat(), session_uuid="stale-session")
    fresh = usage_row(now.isoformat(), session_uuid="fresh-session")
    path.write_text(json.dumps(stale) + "\n" + json.dumps(fresh) + "\n", encoding="utf-8")
    client = legacy_client(session_usage_enabled=True, session_usage_path=str(path))
    login(client)

    response = client.get("/api/v1/session-usage", params={"hours": 6})

    assert response.status_code == 200
    entries = response.json()["entries"]
    assert [entry["session_uuid"] for entry in entries] == ["fresh-session"]


def test_session_usage_hours_query_is_capped_by_settings(tmp_path: Path) -> None:
    client = legacy_client(session_usage_enabled=True, session_usage_max_hours=24)
    login(client)

    response = client.get("/api/v1/session-usage", params={"hours": 999})

    assert response.status_code == 422
