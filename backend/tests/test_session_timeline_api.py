from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.session_timeline_socket_client import (
    SessionTimelineSocketResponseError,
    SessionTimelineSocketTimeout,
    SessionTimelineSocketUnavailable,
)
from app.services.user_service import UserService
from tests.fakes import FakeTmux

PASSWORD = "a-secure-test-password"
SECRET = "a-secure-session-secret-value"


def valid_window_payload() -> dict:
    return {
        "available": True,
        "unavailable_reason": None,
        "turns": [
            {
                "timestamp": "2026-08-02T09:30:12.500Z",
                "model": "claude-opus-5",
                "input_tokens": 2,
                "cache_creation_input_tokens": 1,
                "cache_read_input_tokens": 3,
                "output_tokens": 4,
            }
        ],
        "tool_counts": {"file_read": 1, "subagent_orchestration": 1},
        "compactions": [
            {"timestamp": "2026-08-02T09:31:00Z", "pre_tokens": 164812, "post_tokens": 9539}
        ],
        "subagent_spawns": [{"timestamp": "2026-08-02T09:30:12.500Z"}],
        "truncated": False,
    }


class StubSessionTimelineClient:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls = 0
        self.last_request: tuple | None = None

    async def fetch_window(self, provider, session_uuid, bucket_start, bucket_end):
        self.calls += 1
        self.last_request = (provider, session_uuid, bucket_start, bucket_end)
        if isinstance(self.result, BaseException):
            raise self.result
        assert isinstance(self.result, dict)
        return deepcopy(self.result)


def legacy_client(stub: StubSessionTimelineClient, **overrides: object) -> TestClient:
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        **overrides,
    )
    return TestClient(
        create_app(settings, FakeTmux(), session_timeline_client=stub)
    )


def login_legacy(client: TestClient) -> None:
    response = client.post("/api/v1/auth/login", json={"password": PASSWORD})
    assert response.status_code == 200


def database_settings(tmp_path: Path) -> Settings:
    from app.database import Database

    database_path = tmp_path / "metadata.db"
    database = Database(str(database_path))
    database.migrate("/app/alembic.ini")
    users = UserService(database.engine)
    users.bootstrap_admin("admin", "a-secure-admin-password")
    users.create("operator", "a-secure-operator-password", "operator")
    users.create("viewer", "a-secure-viewer-password", "viewer")
    database.dispose()
    return Settings(
        login_password="legacy-password-is-not-used",
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        database_auth_enabled=True,
        database_path=str(database_path),
        backups_root=str(tmp_path / "backups"),
        snapshots_root=str(tmp_path / "snapshots"),
        attachments_root=str(tmp_path / "attachments"),
        artifacts_root=str(tmp_path / "artifacts"),
        push_vapid_key_path=str(tmp_path / "vapid.pem"),
        session_timeline_enabled=True,
    )


def login_account(client: TestClient, username: str) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": f"a-secure-{username}-password"},
    )
    assert response.status_code == 200


QUERY = "provider=claude&session_uuid=5b84b3fa-a26f-4642-abf3-851fc35abf3f&bucket_start=2026-08-02T09:30:00Z"


def test_session_timeline_is_default_off_and_hides_no_transcript_read() -> None:
    stub = StubSessionTimelineClient(valid_window_payload())
    disabled = legacy_client(stub)
    login_legacy(disabled)
    assert disabled.get("/api/v1/config").json()["session_timeline_enabled"] is False
    assert disabled.get(f"/api/v1/session-usage/timeline?{QUERY}").status_code == 404
    assert stub.calls == 0


def test_session_timeline_requires_admin_session_when_enabled() -> None:
    stub = StubSessionTimelineClient(valid_window_payload())
    enabled = legacy_client(stub, session_timeline_enabled=True)
    assert enabled.get(f"/api/v1/session-usage/timeline?{QUERY}").status_code == 401


def test_admin_receives_window_and_backend_computes_bucket_end() -> None:
    stub = StubSessionTimelineClient(valid_window_payload())
    client = legacy_client(stub, session_timeline_enabled=True)
    login_legacy(client)

    response = client.get(f"/api/v1/session-usage/timeline?{QUERY}")

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["tool_counts"] == {"file_read": 1, "subagent_orchestration": 1}
    assert stub.calls == 1
    assert stub.last_request[2] == datetime(2026, 8, 2, 9, 30, tzinfo=UTC)
    assert stub.last_request[3] == datetime(2026, 8, 2, 9, 35, tzinfo=UTC)
    # Il percorso del transcript non deve mai comparire nella risposta.
    assert ".jsonl" not in response.text
    assert "/home/" not in response.text


def test_declared_unavailable_transcript_is_200_not_an_error() -> None:
    stub = StubSessionTimelineClient(
        {"available": False, "unavailable_reason": "transcript_not_found"}
    )
    client = legacy_client(stub, session_timeline_enabled=True)
    login_legacy(client)
    response = client.get(f"/api/v1/session-usage/timeline?{QUERY}")
    assert response.status_code == 200
    assert response.json()["available"] is False
    assert response.json()["unavailable_reason"] == "transcript_not_found"


def test_session_timeline_maps_timeout_unavailable_and_invalid_payload() -> None:
    cases = [
        (SessionTimelineSocketTimeout("private timeout detail"), 504, "session_timeline_timeout"),
        (
            SessionTimelineSocketUnavailable("private socket detail"),
            503,
            "session_timeline_unavailable",
        ),
        (
            SessionTimelineSocketResponseError("private response detail"),
            503,
            "session_timeline_invalid_response",
        ),
    ]
    for result, status_code, code in cases:
        stub = StubSessionTimelineClient(result)
        client = legacy_client(stub, session_timeline_enabled=True)
        login_legacy(client)
        response = client.get(f"/api/v1/session-usage/timeline?{QUERY}")
        assert response.status_code == status_code
        assert response.json()["code"] == code
        assert "private" not in response.text.lower()


def test_session_timeline_has_a_dedicated_rate_limit() -> None:
    stub = StubSessionTimelineClient(valid_window_payload())
    client = legacy_client(
        stub,
        session_timeline_enabled=True,
        session_timeline_rate_limit=1,
        session_timeline_rate_window_seconds=60,
    )
    login_legacy(client)
    assert client.get(f"/api/v1/session-usage/timeline?{QUERY}").status_code == 200
    limited = client.get(f"/api/v1/session-usage/timeline?{QUERY}")
    assert limited.status_code == 429
    assert limited.json()["code"] == "session_timeline_rate_limited"
    assert int(limited.headers["Retry-After"]) >= 1
    assert stub.calls == 1


def test_session_timeline_is_admin_only_hidden_and_not_audited(tmp_path: Path) -> None:
    settings = database_settings(tmp_path)
    stub = StubSessionTimelineClient(valid_window_payload())
    clients: dict[str, TestClient] = {}
    for username in ("admin", "operator", "viewer"):
        client = TestClient(create_app(settings, FakeTmux(), session_timeline_client=stub))
        login_account(client, username)
        clients[username] = client

    assert clients["admin"].get("/api/v1/config").json()["session_timeline_enabled"] is True
    for username in ("operator", "viewer"):
        assert (
            clients[username].get("/api/v1/config").json()["session_timeline_enabled"] is False
        )
        assert (
            clients[username].get(f"/api/v1/session-usage/timeline?{QUERY}").status_code == 403
        )

    audit_before = clients["admin"].get("/api/v1/audit").json()["events"]
    assert clients["admin"].get(f"/api/v1/session-usage/timeline?{QUERY}").status_code == 200
    audit_after = clients["admin"].get("/api/v1/audit").json()["events"]
    assert audit_after == audit_before


def test_invalid_session_uuid_and_provider_are_rejected_before_reaching_client() -> None:
    stub = StubSessionTimelineClient(valid_window_payload())
    client = legacy_client(stub, session_timeline_enabled=True)
    login_legacy(client)
    bad_uuid = client.get(
        "/api/v1/session-usage/timeline?provider=claude&session_uuid=..%2F..%2Fetc%2Fpasswd&bucket_start=2026-08-02T09:30:00Z"
    )
    assert bad_uuid.status_code == 422
    bad_provider = client.get(
        "/api/v1/session-usage/timeline?provider=openai&session_uuid=abc&bucket_start=2026-08-02T09:30:00Z"
    )
    assert bad_provider.status_code == 422
    assert stub.calls == 0


def test_missing_query_parameters_are_422_never_a_raw_500() -> None:
    """Un parametro assente e' un errore del client, non del server.

    Regressione: `bucket_start` era dichiarato `Annotated[...] = ...`, quindi
    quando mancava del tutto il sentinella `Ellipsis` finiva nel corpo
    dell'errore di validazione e faceva fallire `jsonable_encoder` dentro
    l'handler, degradando la risposta a un `500` grezzo. Gli altri due
    parametri restavano `422`: era il solo ingresso non tipizzato
    dell'endpoint. Si verificano tutti e tre per non reintrodurre
    l'asimmetria.
    """
    stub = StubSessionTimelineClient(valid_window_payload())
    client = legacy_client(stub, session_timeline_enabled=True)
    login_legacy(client)
    base = {
        "provider": "claude",
        "session_uuid": "abc",
        "bucket_start": "2026-08-02T09:30:00Z",
    }
    for missing in base:
        query = "&".join(f"{k}={v}" for k, v in base.items() if k != missing)
        response = client.get(f"/api/v1/session-usage/timeline?{query}")
        assert response.status_code == 422, (missing, response.status_code)
        assert response.json()["detail"][0]["loc"] == ["query", missing]
    assert stub.calls == 0
