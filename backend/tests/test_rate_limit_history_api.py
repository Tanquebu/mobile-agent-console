import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.database import Database
from app.logging_config import APP_LOGGER_NAME, configure_logging
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
        "parse_mode": "structured",
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
    # BH-03: il campo attraversa il boundary invariato, response_model senza
    # schema di traduzione intermedio.
    assert body["samples"][0]["parse_mode"] == "structured"


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


def test_config_exposes_optional_features_in_legacy_single_password_mode() -> None:
    # In modalita' legacy (password condivisa, nessun account) l'utente
    # autenticato equivale all'admin, come gia' avviene per gli altri due
    # flag admin-gated dello stesso endpoint.
    client = legacy_client(rate_limit_fresh_enabled=True, host_observability_enabled=True)
    login(client)

    body = client.get("/api/v1/config").json()

    assert body["optional_features"] == {
        "host_observability_enabled": True,
        "session_usage_enabled": False,
        "session_timeline_enabled": False,
        "rate_limit_fresh_enabled": True,
        "claude_history_enabled": False,
        "database_auth_enabled": False,
    }


def test_config_hides_optional_features_from_non_admin_roles(tmp_path: Path) -> None:
    settings = database_settings(tmp_path)
    admin_client = TestClient(create_app(settings, FakeTmux()))
    login_account(admin_client, "admin", "a-secure-admin-password")
    operator_client = TestClient(create_app(settings, FakeTmux()))
    login_account(operator_client, "operator", "a-secure-operator-password")

    admin_body = admin_client.get("/api/v1/config").json()
    operator_body = operator_client.get("/api/v1/config").json()

    # `database_settings()` accende `database_auth_enabled` e
    # `rate_limit_fresh_enabled`; il resto resta allo stato di default.
    assert admin_body["optional_features"] == {
        "host_observability_enabled": False,
        "session_usage_enabled": False,
        "session_timeline_enabled": False,
        "rate_limit_fresh_enabled": True,
        "claude_history_enabled": False,
        "database_auth_enabled": True,
    }
    # Nessuna installazione minima deve apparire come un errore: il ruolo
    # operator vede semplicemente l'informazione assente (`None`), non un
    # dizionario con valori falsi inventati.
    assert operator_body["optional_features"] is None


def test_startup_logs_optional_feature_states_without_secrets(caplog) -> None:
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        host_observability_enabled=True,
        rate_limit_fresh_enabled=True,
    )
    app = create_app(settings, FakeTmux())

    with caplog.at_level(logging.INFO, logger="mobile_agent_console"), TestClient(app):
        pass

    feature_records = [
        record for record in caplog.records if record.getMessage().startswith("Funzioni opzionali:")
    ]
    assert len(feature_records) == 1
    message = feature_records[0].getMessage()
    # Solo enunciazione di fatto: nomi di funzione e stato acceso/spento,
    # nessun confronto con un'attesa e nessun livello di allarme per questa
    # riga.
    assert feature_records[0].levelno == logging.INFO
    for fragment in (
        "host_observability_enabled=on",
        "session_usage_enabled=off",
        "rate_limit_fresh_enabled=on",
        "claude_history_enabled=off",
        "database_auth_enabled=off",
    ):
        assert fragment in message
    assert PASSWORD not in message
    assert SECRET not in message
    assert "/" not in message
    assert not any(
        record.levelno >= logging.WARNING and "Funzioni opzionali" in record.getMessage()
        for record in caplog.records
    )


def test_configure_logging_makes_app_logger_effectively_observable() -> None:
    """Verifica la configurazione REALE del logger, non uno stato forzato da caplog.

    `caplog.at_level(logging.INFO, logger="mobile_agent_console")` (test sopra)
    forza il livello effettivo del logger per la durata del test e installa un
    handler proprio, indipendentemente da come il processo reale è configurato:
    per questo il test precedente restava verde anche quando, in produzione,
    `app/start.py` chiamava `uvicorn.run(...)` senza `log_config`, lasciando il
    logger applicativo a `WARNING` e senza handler (TEST-BH-03/IMP-BH-03-R1,
    riprodotto dal vivo con `docker compose logs backend`, nessuna
    corrispondenza per "Funzioni opzionali").

    Questo test invoca invece `configure_logging()`, la stessa funzione usata
    da `app/start.py` prima di `uvicorn.run` (che a sua volta, quando riceve un
    `log_config` come dict, chiama internamente lo stesso
    `logging.config.dictConfig`), e ispeziona lo stato risultante sul logger
    reale: nessun `caplog.at_level` di mezzo.
    """
    app_logger = logging.getLogger(APP_LOGGER_NAME)
    other_logger = logging.getLogger("urllib3")
    root_logger = logging.getLogger()

    # Stato prima della configurazione, per la teardown e per il confronto
    # "non deve essere cambiato" sui logger di librerie terze.
    saved_level = app_logger.level
    saved_handlers = list(app_logger.handlers)
    saved_propagate = app_logger.propagate
    other_level_before = other_logger.getEffectiveLevel()
    root_level_before = root_logger.getEffectiveLevel()

    try:
        configure_logging()

        # Il criterio manuale/il gate chiedono che le righe INFO del logger
        # applicativo arrivino a `docker compose logs`: questo richiede sia un
        # livello effettivo <= INFO sia almeno un handler raggiungibile.
        assert app_logger.getEffectiveLevel() <= logging.INFO
        assert app_logger.hasHandlers()

        # Riproduce "docker compose logs backend | grep ..." senza un
        # processo separato: il messaggio deve davvero raggiungere un
        # handler reale (quello `default` di uvicorn, su stderr), non solo
        # essere accettato dal filtro di livello.
        import io

        stream = io.StringIO()
        for handler in app_logger.handlers:
            if isinstance(handler, logging.StreamHandler):
                handler.stream = stream
        app_logger.info("Funzioni opzionali: probe di verifica IMP-BH-03-R1")
        for handler in app_logger.handlers:
            handler.flush()
        assert "Funzioni opzionali: probe di verifica IMP-BH-03-R1" in stream.getvalue()

        # Vincolo esplicito del rework: niente abbassamento indiscriminato
        # della soglia globale/di librerie terze.
        assert other_logger.getEffectiveLevel() == other_level_before
        assert root_logger.getEffectiveLevel() == root_level_before
    finally:
        app_logger.handlers = saved_handlers
        app_logger.setLevel(saved_level)
        app_logger.propagate = saved_propagate
