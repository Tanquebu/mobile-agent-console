import logging
from copy import deepcopy
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.database import Database
from app.main import create_app
from app.services.host_observability_socket_client import (
    HostObservabilitySocketResponseError,
    HostObservabilitySocketTimeout,
    HostObservabilitySocketUnavailable,
)
from app.services.user_service import UserService
from tests.fakes import FakeTmux
from tests.test_host_observability_contract import valid_snapshot, valid_snapshot_v2

PASSWORD = "a-secure-test-password"
SECRET = "a-secure-session-secret-value"


class StubHostObservabilityClient:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls = 0

    async def fetch(self) -> dict[str, object]:
        self.calls += 1
        if isinstance(self.result, BaseException):
            raise self.result
        assert isinstance(self.result, dict)
        return deepcopy(self.result)


def legacy_client(
    stub: StubHostObservabilityClient,
    **overrides: object,
) -> TestClient:
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        **overrides,
    )
    return TestClient(create_app(settings, FakeTmux(), stub))


def login_legacy(client: TestClient) -> None:
    response = client.post("/api/v1/auth/login", json={"password": PASSWORD})
    assert response.status_code == 200


def database_settings(tmp_path: Path) -> Settings:
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
        host_observability_enabled=True,
    )


def login_account(client: TestClient, username: str) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": f"a-secure-{username}-password"},
    )
    assert response.status_code == 200


def test_host_observability_is_default_off_and_requires_authentication() -> None:
    stub = StubHostObservabilityClient(valid_snapshot())
    disabled = legacy_client(stub)
    login_legacy(disabled)
    assert disabled.get("/api/v1/config").json()["host_observability_enabled"] is False
    assert disabled.get("/api/v1/host-observability").status_code == 404
    assert stub.calls == 0

    enabled = legacy_client(
        StubHostObservabilityClient(valid_snapshot()),
        host_observability_enabled=True,
    )
    assert enabled.get("/api/v1/host-observability").status_code == 401


def test_admin_receives_strict_partial_snapshot_without_health_metrics() -> None:
    payload = valid_snapshot()
    payload["status"] = "unknown"
    payload["reasons"] = ["memory_unavailable"]
    payload["memory"] = {
        "status": "unknown",
        "reasons": ["memory_unavailable"],
        "total_bytes": None,
        "available_bytes": None,
        "available_percent": None,
        "swap_total_bytes": None,
        "swap_used_bytes": None,
        "swap_used_percent": None,
    }
    stub = StubHostObservabilityClient(payload)
    client = legacy_client(stub, host_observability_enabled=True)
    login_legacy(client)

    response = client.get("/api/v1/host-observability")

    assert response.status_code == 200
    assert response.json()["memory"]["status"] == "unknown"
    assert response.json()["reasons"] == ["memory_unavailable"]
    assert stub.calls == 1
    assert client.get("/health").json() == {"status": "ok"}


def test_admin_receives_v2_snapshot_without_wrapper_or_export_changes() -> None:
    payload = valid_snapshot_v2()
    stub = StubHostObservabilityClient(payload)
    client = legacy_client(stub, host_observability_enabled=True)
    login_legacy(client)

    response = client.get("/api/v1/host-observability")

    assert response.status_code == 200
    assert response.json() == payload
    listener = response.json()["listeners"]["items"][0]
    assert listener["external_reachability"] == "not_assessed"


def test_host_observability_maps_timeout_unavailable_and_invalid_payload(
    caplog,
) -> None:
    cases = [
        (
            HostObservabilitySocketTimeout("private timeout detail"),
            504,
            "host_observability_timeout",
        ),
        (
            HostObservabilitySocketUnavailable("private socket detail"),
            503,
            "host_observability_unavailable",
        ),
        (
            HostObservabilitySocketResponseError("private response detail"),
            503,
            "host_observability_invalid_response",
        ),
    ]
    manipulated = valid_snapshot()
    manipulated["hostname"] = "private-host-must-not-leak"
    cases.append((manipulated, 503, "host_observability_invalid_response"))
    unsupported = valid_snapshot_v2()
    unsupported["schema_version"] = 99
    cases.append((unsupported, 503, "host_observability_invalid_response"))

    caplog.set_level(logging.DEBUG)
    for result, status_code, code in cases:
        stub = StubHostObservabilityClient(result)
        client = legacy_client(stub, host_observability_enabled=True)
        login_legacy(client)
        with caplog.at_level(logging.DEBUG):
            response = client.get("/api/v1/host-observability")
        assert response.status_code == status_code
        assert response.json()["code"] == code
        assert "private" not in response.text.lower()
    assert "private-host-must-not-leak" not in caplog.text
    assert "private socket detail" not in caplog.text


def test_host_observability_has_a_dedicated_rate_limit() -> None:
    stub = StubHostObservabilityClient(valid_snapshot())
    client = legacy_client(
        stub,
        host_observability_enabled=True,
        host_observability_rate_limit=1,
        host_observability_rate_window_seconds=60,
    )
    login_legacy(client)
    assert client.get("/api/v1/host-observability").status_code == 200
    limited = client.get("/api/v1/host-observability")
    assert limited.status_code == 429
    assert limited.json()["code"] == "host_observability_rate_limited"
    assert int(limited.headers["Retry-After"]) >= 1
    assert stub.calls == 1


def test_host_observability_is_admin_only_hidden_and_not_audited(tmp_path: Path) -> None:
    settings = database_settings(tmp_path)
    stub = StubHostObservabilityClient(valid_snapshot())
    clients: dict[str, TestClient] = {}
    for username in ("admin", "operator", "viewer"):
        client = TestClient(create_app(settings, FakeTmux(), stub))
        login_account(client, username)
        clients[username] = client

    assert clients["admin"].get("/api/v1/config").json()[
        "host_observability_enabled"
    ] is True
    for username in ("operator", "viewer"):
        assert clients[username].get("/api/v1/config").json()[
            "host_observability_enabled"
        ] is False
        assert clients[username].get("/api/v1/host-observability").status_code == 403

    audit_before = clients["admin"].get("/api/v1/audit").json()["events"]
    assert clients["admin"].get("/api/v1/host-observability").status_code == 200
    audit_after = clients["admin"].get("/api/v1/audit").json()["events"]
    assert audit_after == audit_before
