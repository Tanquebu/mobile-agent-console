import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.database import Database
from app.main import create_app
from app.services.rate_limit_fresh_client import (
    RateLimitFreshResult,
    RateLimitFreshTimeout,
    RateLimitFreshUnavailable,
)
from app.services.user_service import UserService
from tests.fakes import FakeTmux

PASSWORD = "a-secure-test-password"
SECRET = "a-secure-session-secret-value"


class StubRateLimitFreshClient:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls = 0

    async def fetch_fresh(self) -> RateLimitFreshResult:
        self.calls += 1
        if isinstance(self.result, BaseException):
            raise self.result
        assert isinstance(self.result, RateLimitFreshResult)
        return self.result


def fresh_result() -> RateLimitFreshResult:
    return RateLimitFreshResult.model_validate(
        {
            "collected_at": "2026-08-02T09:34:50+00:00",
            "samples": [
                {
                    "sampled_at": "2026-08-02T09:34:50+00:00",
                    "provider": "claude",
                    "source": "fresh",
                    "observed_at": "2026-08-02T09:34:41+00:00",
                    "stale": False,
                    "windows": [
                        {"label": "5h", "used_percent": 58.0, "resets_at": 1785679200}
                    ],
                }
            ],
        }
    )


def history_row() -> dict:
    # Relativo a ora, mai fisso: l'endpoint filtra sulle ultime `hours` ore, e
    # un timestamp costante fa passare il test finche' resta dentro la finestra
    # per poi farlo fallire da solo quando ne esce.
    return {
        "sampled_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
        "provider": "claude",
        "source": "cache",
        "observed_at": "2026-08-02T09:34:41+00:00",
        "stale": False,
        "windows": [{"label": "5h", "used_percent": 58.0, "resets_at": 1785679200}],
    }


def legacy_client(
    stub: StubRateLimitFreshClient | None = None,
    **overrides: object,
) -> TestClient:
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        **overrides,
    )
    return TestClient(create_app(settings, FakeTmux(), rate_limit_fresh_client=stub))


def login(client: TestClient) -> str:
    response = client.post("/api/v1/auth/login", json={"password": PASSWORD})
    assert response.status_code == 200
    return response.json()["csrf_token"]


def database_settings(tmp_path: Path) -> Settings:
    database_path = tmp_path / "metadata.db"
    database = Database(str(database_path))
    database.migrate("/app/alembic.ini")
    users = UserService(database.engine)
    users.bootstrap_admin("admin", "a-secure-admin-password")
    users.create("operator", "a-secure-operator-password", "operator")
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
        rate_limit_fresh_enabled=True,
    )


def login_account(client: TestClient, username: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200
    return response.json()["csrf_token"]


def test_history_returns_samples_from_populated_file(tmp_path: Path) -> None:
    path = tmp_path / "provider-rate-limits-history.jsonl"
    path.write_text(json.dumps(history_row()) + "\n", encoding="utf-8")
    client = legacy_client(provider_rate_limits_history_path=str(path))
    login(client)

    response = client.get("/api/v1/provider-rate-limits/history")

    assert response.status_code == 200
    body = response.json()
    assert len(body["samples"]) == 1
    assert body["samples"][0]["provider"] == "claude"


def test_history_missing_file_returns_empty_list_not_500(tmp_path: Path) -> None:
    path = tmp_path / "missing-history.jsonl"
    client = legacy_client(provider_rate_limits_history_path=str(path))
    login(client)

    response = client.get("/api/v1/provider-rate-limits/history")

    assert response.status_code == 200
    assert response.json()["samples"] == []


def test_refresh_succeeds_when_enabled() -> None:
    stub = StubRateLimitFreshClient(fresh_result())
    client = legacy_client(stub, rate_limit_fresh_enabled=True)
    csrf = login(client)

    response = client.post(
        "/api/v1/provider-rate-limits/refresh", headers={"X-CSRF-Token": csrf}
    )

    assert response.status_code == 200
    assert response.json()["samples"][0]["provider"] == "claude"
    assert stub.calls == 1


def test_refresh_returns_404_when_disabled() -> None:
    stub = StubRateLimitFreshClient(fresh_result())
    client = legacy_client(stub, rate_limit_fresh_enabled=False)
    csrf = login(client)

    response = client.post(
        "/api/v1/provider-rate-limits/refresh", headers={"X-CSRF-Token": csrf}
    )

    assert response.status_code == 404
    assert stub.calls == 0


def test_refresh_requires_csrf_token() -> None:
    stub = StubRateLimitFreshClient(fresh_result())
    client = legacy_client(stub, rate_limit_fresh_enabled=True)
    login(client)

    response = client.post("/api/v1/provider-rate-limits/refresh")

    assert response.status_code == 403
    assert stub.calls == 0


def test_refresh_requires_admin_role(tmp_path: Path) -> None:
    settings = database_settings(tmp_path)
    stub = StubRateLimitFreshClient(fresh_result())
    client = TestClient(create_app(settings, FakeTmux(), rate_limit_fresh_client=stub))
    csrf = login_account(client, "operator", "a-secure-operator-password")

    response = client.post(
        "/api/v1/provider-rate-limits/refresh", headers={"X-CSRF-Token": csrf}
    )

    assert response.status_code == 403
    assert stub.calls == 0


def test_refresh_has_a_dedicated_rate_limit() -> None:
    stub = StubRateLimitFreshClient(fresh_result())
    client = legacy_client(
        stub,
        rate_limit_fresh_enabled=True,
        rate_limit_fresh_rate_limit=1,
        rate_limit_fresh_rate_window_seconds=60,
    )
    csrf = login(client)

    first = client.post(
        "/api/v1/provider-rate-limits/refresh", headers={"X-CSRF-Token": csrf}
    )
    assert first.status_code == 200

    second = client.post(
        "/api/v1/provider-rate-limits/refresh", headers={"X-CSRF-Token": csrf}
    )
    assert second.status_code == 429
    assert second.json()["code"] == "rate_limit_fresh_rate_limited"
    assert int(second.headers["Retry-After"]) >= 1
    assert stub.calls == 1


def test_refresh_maps_client_timeout_to_504() -> None:
    stub = StubRateLimitFreshClient(RateLimitFreshTimeout("private timeout detail"))
    client = legacy_client(stub, rate_limit_fresh_enabled=True)
    csrf = login(client)

    response = client.post(
        "/api/v1/provider-rate-limits/refresh", headers={"X-CSRF-Token": csrf}
    )

    assert response.status_code == 504
    assert response.json()["code"] == "rate_limit_fresh_timeout"
    assert "private" not in response.text.lower()


def test_refresh_maps_client_unavailable_to_503() -> None:
    stub = StubRateLimitFreshClient(RateLimitFreshUnavailable("private socket detail"))
    client = legacy_client(stub, rate_limit_fresh_enabled=True)
    csrf = login(client)

    response = client.post(
        "/api/v1/provider-rate-limits/refresh", headers={"X-CSRF-Token": csrf}
    )

    assert response.status_code == 503
    assert response.json()["code"] == "rate_limit_fresh_unavailable"
    assert "private" not in response.text.lower()
