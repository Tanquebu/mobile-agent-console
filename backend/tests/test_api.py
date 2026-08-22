import json
import os
import sqlite3
import time
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pywebpush import WebPushException
from starlette.websockets import WebSocketDisconnect

from app.config import Settings
from app.database import Database
from app.main import create_app
from app.models import PushSubscription
from app.services.attachment_service import AttachmentService
from app.services.push_service import PushService
from app.services.user_service import UserService
from tests.fakes import FakeTmux

PASSWORD = "a-secure-test-password"
SECRET = "a-secure-session-secret-value"
ADMIN_PASSWORD = "a-secure-admin-password-value"


def migrated_database_with_admin(tmp_path) -> str:
    # database_auth_enabled sostituisce interamente il login legacy con gli
    # account persistenti (main.py: `if users: ... else: ...`), quindi un
    # database migrato da solo non basta per autenticarsi nei test.
    database_path = tmp_path / "db" / "meta.db"
    database = Database(str(database_path))
    database.migrate("/app/alembic.ini")
    UserService(database.engine).bootstrap_admin("admin", ADMIN_PASSWORD)
    database.dispose()
    return str(database_path)


def login_admin(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 200
    return response.json()["csrf_token"]


def client_and_fake(
    provider_rate_limits_path: str = "/workspace/.mobile-agent-console/provider-rate-limits.json",
    provider_session_states_path: str = (
        "/workspace/.mobile-agent-console/provider-session-states.json"
    ),
    orchestrator_state_path: str = (
        "/workspace/.mobile-agent-console/orchestrator-state.json"
    ),
    claude_history_enabled: bool = False,
    claude_history_path: str = (
        "/workspace/.mobile-agent-console/claude-history.json"
    ),
    opencode_history_enabled: bool = False,
    opencode_db_path: str = (
        "/workspace/.local/share/opencode/opencode.db"
    ),
) -> tuple[TestClient, FakeTmux]:
    fake = FakeTmux()
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        provider_rate_limits_path=provider_rate_limits_path,
        provider_session_states_path=provider_session_states_path,
        orchestrator_state_path=orchestrator_state_path,
        claude_history_enabled=claude_history_enabled,
        claude_history_path=claude_history_path,
        opencode_history_enabled=opencode_history_enabled,
        opencode_db_path=opencode_db_path,
    )
    return TestClient(create_app(settings, fake)), fake


def login(client: TestClient) -> str:
    response = client.post("/api/v1/auth/login", json={"password": PASSWORD})
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    return response.json()["csrf_token"]


def test_authentication_required_and_bad_login() -> None:
    client, _ = client_and_fake()
    assert client.get("/api/v1/sessions").status_code == 401
    assert client.post("/api/v1/auth/login", json={"password": "wrong"}).status_code == 401


def test_login_and_mutation_rate_limits() -> None:
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        login_rate_limit=2,
        mutation_rate_limit=2,
    )
    login_client = TestClient(create_app(settings, FakeTmux()))
    assert login_client.post("/api/v1/auth/login", json={"password": "wrong"}).status_code == 401
    assert login_client.post("/api/v1/auth/login", json={"password": "wrong"}).status_code == 401
    limited = login_client.post("/api/v1/auth/login", json={"password": PASSWORD})
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) >= 1

    client = TestClient(create_app(settings, FakeTmux()))
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    for _ in range(2):
        assert client.post(
            "/api/v1/sessions/1/keys", headers=headers, json={"key": "Enter"}
        ).status_code == 202
    limited = client.post(
        "/api/v1/sessions/1/keys", headers=headers, json={"key": "Enter"}
    )
    assert limited.status_code == 429
    assert limited.json() == {"detail": "Too many requests"}


def test_list_and_capture() -> None:
    client, _ = client_and_fake()
    csrf = login(client)
    assert client.get("/api/v1/auth/session").json()["csrf_token"] == csrf
    listed = client.get("/api/v1/sessions").json()["sessions"][0]
    assert listed["id"] == "1"
    assert listed["name"] == "demo"
    assert client.get("/api/v1/sessions/1/output").json()["content"] == "$ "


def test_claude_history_is_isolated_and_can_be_rolled_back(tmp_path) -> None:
    path = tmp_path / "history.json"
    now = datetime.now(UTC).isoformat()
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "collected_at": now,
                "sessions": [
                    {
                        "session_id": "1",
                        "provider": "claude",
                        "source_updated_at": now,
                        "truncated": False,
                        "messages": [
                            {
                                "id": "u1",
                                "role": "user",
                                "content": "Domanda",
                                "timestamp": now,
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    disabled, _ = client_and_fake(
        claude_history_enabled=False,
        claude_history_path=str(path),
    )
    assert disabled.get("/api/v1/sessions/1/claude-history").status_code == 401
    login(disabled)
    assert disabled.get("/api/v1/config").json()["claude_history_enabled"] is False
    assert disabled.get("/api/v1/sessions/1/claude-history").status_code == 404
    assert disabled.get("/api/v1/sessions/1/output").json()["content"] == "$ "

    enabled, fake = client_and_fake(
        claude_history_enabled=True,
        claude_history_path=str(path),
    )
    current = fake.sessions["1"]
    fake.sessions["1"] = type(current)(
        current.id,
        current.name,
        current.attached,
        current.windows,
        "claude",
        current.activity_at,
    )
    login(enabled)
    response = enabled.get("/api/v1/sessions/1/claude-history")
    assert response.status_code == 200
    assert response.json()["messages"][0]["content"] == "Domanda"
    assert enabled.get("/api/v1/sessions/not-an-id/claude-history").status_code == 404


def test_claude_history_rejects_non_claude_and_missing_data(tmp_path) -> None:
    client, _ = client_and_fake(
        claude_history_enabled=True,
        claude_history_path=str(tmp_path / "missing.json"),
    )
    login(client)
    assert client.get("/api/v1/sessions/1/claude-history").status_code == 404


def test_opencode_history_api(tmp_path) -> None:
    from tests.test_opencode_service import _create_sample_opencode_db

    db_path = tmp_path / "opencode.db"
    _create_sample_opencode_db(db_path, "/workspace")

    disabled, _ = client_and_fake(
        opencode_history_enabled=False,
        opencode_db_path=str(db_path),
    )
    assert disabled.get("/api/v1/sessions/1/opencode-history").status_code == 401
    login(disabled)
    assert disabled.get("/api/v1/config").json()["opencode_history_enabled"] is False
    assert disabled.get("/api/v1/sessions/1/opencode-history").status_code == 404
    enabled, fake = client_and_fake(
        opencode_history_enabled=True,
        opencode_db_path=str(db_path),
    )
    from datetime import UTC, datetime
    current = fake.sessions["1"]
    fake.sessions["1"] = type(current)(
        current.id,
        current.name,
        current.attached,
        current.windows,
        "opencode",
        datetime.fromtimestamp(1700000000, tz=UTC),
        datetime.fromtimestamp(1700000000, tz=UTC),
    )
    login(enabled)
    response = enabled.get("/api/v1/sessions/1/opencode-history")
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "1"
    assert data["opencode_session_id"] == "ses_test_123"
    assert len(data["blocks"]) == 3
    assert data["blocks"][0]["kind"] == "user"
    assert data["blocks"][0]["content"] == "Ciao, puoi creare un file?"
    assert data["blocks"][1]["kind"] == "activity"
    assert data["blocks"][2]["kind"] == "agent"


def test_opencode_history_api_new_session_empty_until_first_prompt(tmp_path) -> None:
    from datetime import UTC, datetime

    from tests.test_opencode_service import _create_sample_opencode_db

    db_path = tmp_path / "opencode.db"
    _create_sample_opencode_db(db_path, "/workspace")

    enabled, fake = client_and_fake(
        opencode_history_enabled=True,
        opencode_db_path=str(db_path),
    )
    current = fake.sessions["1"]
    # Nuova sessione tmux creata dopo l'unica conversazione in archivio
    # (sample: time_created 1700000000000): la vista non deve ereditare i
    # blocchi della conversazione precedente finche' il primo prompt non
    # materializza la nuova sessione.
    fake.sessions["1"] = type(current)(
        current.id,
        current.name,
        current.attached,
        current.windows,
        "opencode",
        datetime.fromtimestamp(1700000100, tz=UTC),
        datetime.fromtimestamp(1700000100, tz=UTC),
    )
    login(enabled)
    response = enabled.get("/api/v1/sessions/1/opencode-history")
    assert response.status_code == 200
    assert response.json()["blocks"] == []


def test_opencode_history_api_picks_conversation_born_after_pane_start(tmp_path) -> None:
    from datetime import UTC, datetime

    from tests.test_opencode_service import _create_sample_opencode_db

    db_path = tmp_path / "opencode.db"
    _create_sample_opencode_db(db_path, "/workspace")

    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(
        "INSERT INTO session (id, directory, title, time_created, time_updated, model) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            "ses_born_first",
            "/workspace",
            "Nata per prima",
            1700000120000,
            1700000120000,
            "anthropic/claude-opus-4-1",
        ),
    )
    c.execute(
        "INSERT INTO message VALUES (?, ?, ?, ?)",
        ("msg_b1", "ses_born_first", 1700000121000, json.dumps({"role": "user"})),
    )
    c.execute(
        "INSERT INTO part VALUES (?, ?, ?, ?, ?)",
        ("prt_b1", "msg_b1", "ses_born_first", 1700000121100, json.dumps({"type": "text", "text": "Blocco della conversazione corretta"})),
    )
    c.execute(
        "INSERT INTO session (id, directory, title, time_created, time_updated, model) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("ses_born_later", "/workspace", "Altra sessione", 1700000130000, 1700000140000, "openai/gpt-5"),
    )
    c.execute(
        "INSERT INTO message VALUES (?, ?, ?, ?)",
        ("msg_b2", "ses_born_later", 1700000131000, json.dumps({"role": "user"})),
    )
    c.execute(
        "INSERT INTO part VALUES (?, ?, ?, ?, ?)",
        ("prt_b2", "msg_b2", "ses_born_later", 1700000131100, json.dumps({"type": "text", "text": "Blocco di una sessione chiusa"})),
    )
    conn.commit()
    conn.close()

    enabled, fake = client_and_fake(
        opencode_history_enabled=True,
        opencode_db_path=str(db_path),
    )
    current = fake.sessions["1"]
    fake.sessions["1"] = type(current)(
        current.id,
        current.name,
        current.attached,
        current.windows,
        "opencode",
        datetime.fromtimestamp(1700000100, tz=UTC),
        datetime.fromtimestamp(1700000100, tz=UTC),
    )
    login(enabled)
    response = enabled.get("/api/v1/sessions/1/opencode-history")
    assert response.status_code == 200
    data = response.json()
    assert data["opencode_session_id"] == "ses_born_first"
    assert len(data["blocks"]) == 1
    assert data["blocks"][0]["content"] == "Blocco della conversazione corretta"


def test_agent_statuses_include_only_agentic_sessions() -> None:
    client, fake = client_and_fake()
    login(client)
    current = fake.sessions["1"]
    fake.sessions["1"] = type(current)(
        current.id,
        "Codex demo",
        current.attached,
        current.windows,
        "codex",
        current.activity_at,
    )
    fake.content = "Would you like to run this command?\n1. Yes, proceed\npermissions: Auto\n› "
    response = client.get("/api/v1/agent-statuses")
    assert response.status_code == 200
    body = response.json()
    statuses = body["statuses"]
    assert len(statuses) == 1
    content_changed_at = statuses[0].pop("content_changed_at")
    assert content_changed_at is not None
    assert body == {
        "statuses": [
            {
                "session_id": "1",
                "provider": "codex",
                "state": "waiting_authorization",
                "detail": "Attende autorizzazione",
                "permission_state": "auto",
                "permission_detail": "Auto",
                "context_used_percent": None,
                "summary": "Would you like to run this command? permissions: Auto",
                "model": None,
                "subagent_count": 0,
            }
        ]
    }
    # L'euristica lavora su testo semplice: mai richiedere l'ANSI opt-in.
    assert fake.capture_ansi_calls == [False]


def test_agent_statuses_content_changed_at_tracks_pane_content_not_input() -> None:
    # Il bug: session_activity di tmux si aggiorna solo sull'input del
    # client. content_changed_at deve invece riflettere l'ultimo cambio
    # reale del digest del contenuto del pane (AgentStatusService.classify),
    # e restare stabile tra due poll consecutivi se il contenuto non cambia.
    client, fake = client_and_fake()
    login(client)
    current = fake.sessions["1"]
    fake.sessions["1"] = type(current)(
        current.id,
        "Codex demo",
        current.attached,
        current.windows,
        "codex",
        current.activity_at,
    )
    fake.content = "› "

    first = client.get("/api/v1/agent-statuses").json()["statuses"][0]
    assert first["content_changed_at"] is not None
    first_changed_at = datetime.fromisoformat(first["content_changed_at"])

    # Stesso contenuto al secondo poll: content_changed_at non deve avanzare
    # (a parte un rumore di pochi microsecondi dovuto alla conversione
    # float monotonic -> wall clock ad ogni richiesta).
    second = client.get("/api/v1/agent-statuses").json()["statuses"][0]
    second_changed_at = datetime.fromisoformat(second["content_changed_at"])
    assert abs((second_changed_at - first_changed_at).total_seconds()) < 0.01

    # Il contenuto del pane cambia (nessun nuovo input dal client, solo
    # output del processo): content_changed_at deve avanzare.
    fake.content = "› updated output\n"
    third = client.get("/api/v1/agent-statuses").json()["statuses"][0]
    third_changed_at = datetime.fromisoformat(third["content_changed_at"])
    assert third_changed_at >= second_changed_at


def test_agent_statuses_content_changed_at_none_when_output_unavailable() -> None:
    client, fake = client_and_fake()
    login(client)
    current = fake.sessions["1"]
    fake.sessions["1"] = type(current)(
        current.id,
        "Codex demo",
        current.attached,
        current.windows,
        "codex",
        current.activity_at,
    )
    fake.capture_error_sessions.add("1")
    response = client.get("/api/v1/agent-statuses")
    assert response.status_code == 200
    statuses = response.json()["statuses"]
    assert len(statuses) == 1
    assert statuses[0]["state"] == "unknown"
    assert statuses[0]["content_changed_at"] is None


def test_agent_statuses_opencode_from_real_tui_fixture() -> None:
    # OC-03: una sessione opencode reale (frame 07-autorizzazione.txt) deve
    # essere inclusa in /agent-statuses con lo stato waiting_authorization e
    # il default "ask" (profilo conservativo bash/edit → ask).
    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "opencode-tui"
        / "07-autorizzazione.txt"
    ).read_text(encoding="utf-8")
    client, fake = client_and_fake()
    login(client)
    current = fake.sessions["1"]
    fake.sessions["1"] = type(current)(
        current.id,
        "OpenCode demo",
        current.attached,
        current.windows,
        "opencode",
        current.activity_at,
    )
    fake.content = fixture
    response = client.get("/api/v1/agent-statuses")
    assert response.status_code == 200
    status = response.json()["statuses"][0]
    assert status["provider"] == "opencode"
    assert status["state"] == "waiting_authorization"
    assert status["permission_state"] == "ask"
    assert status["permission_detail"] == "Chiede conferma"
    assert "permission" in status["summary"].lower()


def test_agent_statuses_opencode_model_present_when_history_enabled(tmp_path) -> None:
    from tests.test_opencode_service import _create_sample_opencode_db

    db_path = tmp_path / "opencode.db"
    _create_sample_opencode_db(db_path, "/workspace")

    client, fake = client_and_fake(
        opencode_history_enabled=True,
        opencode_db_path=str(db_path),
    )
    login(client)
    current = fake.sessions["1"]
    fake.sessions["1"] = type(current)(
        current.id,
        "OpenCode demo",
        current.attached,
        current.windows,
        "opencode",
        current.activity_at,
        datetime.fromtimestamp(1699999999, tz=UTC),
    )
    response = client.get("/api/v1/agent-statuses")
    assert response.status_code == 200
    statuses = response.json()["statuses"]
    assert len(statuses) == 1
    assert statuses[0]["provider"] == "opencode"
    assert statuses[0]["model"] == "anthropic/claude-sonnet-4-5"


def test_agent_statuses_model_is_none_for_non_opencode_providers(tmp_path) -> None:
    from tests.test_opencode_service import _create_sample_opencode_db

    db_path = tmp_path / "opencode.db"
    _create_sample_opencode_db(db_path, "/workspace")

    # opencode_history_enabled=True dimostra che il gating è per provider,
    # non solo per il flag: anche con la fonte dati disponibile, claude,
    # codex e antigravity non hanno una fonte affidabile per il modello.
    client, fake = client_and_fake(
        opencode_history_enabled=True,
        opencode_db_path=str(db_path),
    )
    login(client)
    for provider_command in ("claude", "codex", "agy"):
        current = fake.sessions["1"]
        fake.sessions["1"] = type(current)(
            current.id,
            current.name,
            current.attached,
            current.windows,
            provider_command,
            current.activity_at,
        )
        status = client.get("/api/v1/agent-statuses").json()["statuses"][0]
        assert status["model"] is None


def test_agent_statuses_opencode_model_none_when_history_disabled(tmp_path) -> None:
    from tests.test_opencode_service import _create_sample_opencode_db

    db_path = tmp_path / "opencode.db"
    _create_sample_opencode_db(db_path, "/workspace")

    client, fake = client_and_fake(
        opencode_history_enabled=False,
        opencode_db_path=str(db_path),
    )
    login(client)
    current = fake.sessions["1"]
    fake.sessions["1"] = type(current)(
        current.id,
        "OpenCode demo",
        current.attached,
        current.windows,
        "opencode",
        current.activity_at,
        datetime.fromtimestamp(1699999999, tz=UTC),
    )
    response = client.get("/api/v1/agent-statuses")
    assert response.status_code == 200
    statuses = response.json()["statuses"]
    assert len(statuses) == 1
    assert statuses[0]["provider"] == "opencode"
    assert statuses[0]["model"] is None


def test_agent_statuses_opencode_model_none_when_correlation_fails(tmp_path) -> None:
    from tests.test_opencode_service import _create_sample_opencode_db

    db_path = tmp_path / "opencode.db"
    # Il DB di esempio ha sessioni per "/workspace/other", non "/workspace"
    # (la directory del pane fake): nessuna riga corrisponde.
    _create_sample_opencode_db(db_path, "/workspace/other")

    client, fake = client_and_fake(
        opencode_history_enabled=True,
        opencode_db_path=str(db_path),
    )
    login(client)
    current = fake.sessions["1"]
    fake.sessions["1"] = type(current)(
        current.id,
        "OpenCode demo",
        current.attached,
        current.windows,
        "opencode",
        current.activity_at,
    )
    response = client.get("/api/v1/agent-statuses")
    assert response.status_code == 200
    statuses = response.json()["statuses"]
    assert len(statuses) == 1
    assert statuses[0]["provider"] == "opencode"
    assert statuses[0]["model"] is None


def test_agent_statuses_prefer_structured_provider_permissions(tmp_path) -> None:
    path = tmp_path / "provider-session-states.json"
    path.write_text(
        '{"sessions":[{"session_id":"1","provider":"codex",'
        '"permission_state":"bypass","permission_detail":"Accesso completo",'
        '"context_used_percent":73.4}]}',
        encoding="utf-8",
    )
    client, fake = client_and_fake(provider_session_states_path=str(path))
    login(client)
    current = fake.sessions["1"]
    fake.sessions["1"] = type(current)(
        current.id,
        current.name,
        current.attached,
        current.windows,
        "codex",
        current.activity_at,
    )
    fake.content = "permissions: Read Only\n› "
    status = client.get("/api/v1/agent-statuses").json()["statuses"][0]
    assert status["permission_state"] == "bypass"
    assert status["permission_detail"] == "Accesso completo"
    assert status["context_used_percent"] == 73.4


def test_provider_rate_limits_are_authenticated_and_sanitized(tmp_path) -> None:
    path = tmp_path / "limits.json"
    path.write_text(
        '{"collected_at":"2026-07-26T15:30:00+00:00","providers":['
        '{"provider":"claude","available":true,"observed_at":"2026-07-26T15:01:34Z",'
        '"windows":[{"label":"5h","used_percent":12,"resets_at":1785679200,'
        '"detail":"reset later"}],'
        '"reached_type":null,"error":null}]}',
        encoding="utf-8",
    )
    client, _ = client_and_fake(str(path))
    assert client.get("/api/v1/provider-rate-limits").status_code == 401
    login(client)
    payload = client.get("/api/v1/provider-rate-limits").json()
    assert payload["providers"][0]["windows"][0]["used_percent"] == 12
    assert payload["providers"][0]["windows"][0]["resets_at"] == 1785679200


def test_orchestrator_state_is_authenticated_and_read_only(tmp_path) -> None:
    path = tmp_path / "orchestrator-state.json"
    path.write_text(
        '{"schema_version":1,"collected_at":"2026-07-28T12:00:00Z",'
        '"providers":[],"tasks":[{"task_id":"recOpaque",'
        '"task_kind":"weekly-refresh","status":"paused_provider",'
        '"provider":"claude","execution_mode":"atomic","phase":null,'
        '"capacity_paused":true,"next_attempt_at":null,'
        '"fallback_providers":["codex"],"checkpoint_present":false}]}',
        encoding="utf-8",
    )
    client, _ = client_and_fake(orchestrator_state_path=str(path))
    assert client.get("/api/v1/orchestrator-state").status_code == 401
    login(client)
    payload = client.get("/api/v1/orchestrator-state").json()
    assert payload["tasks"][0]["fallback_providers"] == ["codex"]


def test_list_target_and_resize_pane() -> None:
    client, fake = client_and_fake()
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    pane = client.get("/api/v1/sessions/1/panes").json()["panes"][0]
    assert pane["id"] == "10"
    assert client.get("/api/v1/sessions/1/output?pane_id=10").status_code == 200
    assert client.get("/api/v1/sessions/1/output?pane_id=99").status_code == 404
    assert client.post(
        "/api/v1/sessions/1/input",
        headers=headers,
        json={"text": "targeted", "pane_id": "10"},
    ).status_code == 202
    assert fake.targets[-1] == "10"
    assert client.post(
        "/api/v1/sessions/1/panes/10/resize",
        headers=headers,
        json={"columns": 100, "rows": 30},
    ).status_code == 200
    assert fake.resizes == [("10", 100, 30)]
    assert client.post(
        "/api/v1/sessions/1/panes/99/resize",
        headers=headers,
        json={"columns": 100, "rows": 30},
    ).status_code == 404
    split = client.post(
        "/api/v1/sessions/1/panes/split?pane_id=10",
        headers=headers,
    )
    assert split.status_code == 201
    assert split.json()["id"] == "11"
    assert fake.splits == ["horizontal"]
    assert client.post(
        "/api/v1/sessions/1/panes/split?pane_id=99",
        headers=headers,
    ).status_code == 404


def test_split_pane_direction() -> None:
    client, fake = client_and_fake()
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    vertical = client.post(
        "/api/v1/sessions/1/panes/split?direction=vertical", headers=headers
    )
    assert vertical.status_code == 201
    assert fake.splits == ["vertical"]
    assert client.post(
        "/api/v1/sessions/1/panes/split?direction=diagonal", headers=headers
    ).status_code == 422


def test_kill_pane_requires_confirmation_and_keeps_last_pane() -> None:
    client, fake = client_and_fake()
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    assert client.request(
        "DELETE", "/api/v1/sessions/1/panes/10", headers=headers, json={"confirmed": False}
    ).status_code == 400
    # non si può chiudere l'unico pane rimasto: va terminata la sessione.
    last_pane = client.request(
        "DELETE", "/api/v1/sessions/1/panes/10", headers=headers, json={"confirmed": True}
    )
    assert last_pane.status_code == 400
    assert len(fake.panes["1"]) == 1

    split = client.post("/api/v1/sessions/1/panes/split?pane_id=10", headers=headers).json()
    missing = client.request(
        "DELETE", "/api/v1/sessions/1/panes/99", headers=headers, json={"confirmed": True}
    )
    assert missing.status_code == 404
    closed = client.request(
        "DELETE",
        f"/api/v1/sessions/1/panes/{split['id']}",
        headers=headers,
        json={"confirmed": True},
    )
    assert closed.status_code == 204
    assert [pane.id for pane in fake.panes["1"]] == ["10"]


def test_text_and_enter_are_separate_and_csrf_protected() -> None:
    client, fake = client_and_fake()
    csrf = login(client)
    text = "first\nsecond; $(not-a-command)"
    assert client.post("/api/v1/sessions/1/input", json={"text": text}).status_code == 403
    headers = {"X-CSRF-Token": csrf}
    assert client.post("/api/v1/sessions/1/input", headers=headers, json={"text": text}).status_code == 202
    assert fake.texts == [text]
    assert fake.keys == []
    assert client.post("/api/v1/sessions/1/keys", headers=headers, json={"key": "Enter"}).status_code == 202
    assert fake.keys == ["Enter"]


def test_special_keys_interrupt_and_termination_require_confirmation() -> None:
    client, fake = client_and_fake()
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}

    for key in ("Up", "Down", "Left", "Right", "Tab", "Escape"):
        response = client.post(
            "/api/v1/sessions/1/keys",
            headers=headers,
            json={"key": key},
        )
        assert response.status_code == 202
    interrupt_denied = client.post(
        "/api/v1/sessions/1/keys",
        headers=headers,
        json={"key": "C-c"},
    )
    assert interrupt_denied.status_code == 400
    interrupt = client.post(
        "/api/v1/sessions/1/keys",
        headers=headers,
        json={"key": "C-c", "confirmed": True},
    )
    assert interrupt.status_code == 202
    shifted = client.post(
        "/api/v1/sessions/1/keys",
        headers=headers,
        json={"key": "Shift-Tab"},
    )
    assert shifted.status_code == 202
    assert fake.keys == ["Up", "Down", "Left", "Right", "Tab", "Escape", "C-c", "Shift-Tab"]

    assert client.request(
        "DELETE",
        "/api/v1/sessions/1",
        headers=headers,
        json={"confirmed": False},
    ).status_code == 400
    terminated = client.request(
        "DELETE",
        "/api/v1/sessions/1",
        headers=headers,
        json={"confirmed": True},
    )
    assert terminated.status_code == 204
    assert fake.terminated == ["1"]


def test_scroll_pane_up_and_down() -> None:
    unauthenticated, _ = client_and_fake()
    assert unauthenticated.post(
        "/api/v1/sessions/1/scroll", json={"direction": "up", "ticks": 3}
    ).status_code == 401

    client, fake = client_and_fake()
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}

    assert client.post(
        "/api/v1/sessions/1/scroll", json={"direction": "up", "ticks": 3}
    ).status_code == 403

    up = client.post(
        "/api/v1/sessions/1/scroll",
        headers=headers,
        json={"direction": "up", "ticks": 3},
    )
    assert up.status_code == 202
    down = client.post(
        "/api/v1/sessions/1/scroll",
        headers=headers,
        json={"direction": "down", "ticks": 1, "pane_id": "10"},
    )
    assert down.status_code == 202
    assert fake.scrolls == [("up", 3), ("down", 1)]
    assert fake.targets[-1] == "10"

    assert client.post(
        "/api/v1/sessions/1/scroll",
        headers=headers,
        json={"direction": "sideways", "ticks": 1},
    ).status_code == 422
    assert client.post(
        "/api/v1/sessions/1/scroll",
        headers=headers,
        json={"direction": "up", "ticks": 0},
    ).status_code == 422
    assert client.post(
        "/api/v1/sessions/1/scroll",
        headers=headers,
        json={"direction": "up", "ticks": 51},
    ).status_code == 422

    missing = client.post(
        "/api/v1/sessions/9/scroll",
        headers=headers,
        json={"direction": "up", "ticks": 1},
    )
    assert missing.status_code == 404


def test_rename_session_supports_spaces_and_requires_csrf() -> None:
    client, fake = client_and_fake()
    csrf = login(client)
    payload = {"name": "Refactoring Codex"}

    assert client.post("/api/v1/sessions/1/rename", json=payload).status_code == 403
    renamed = client.post(
        "/api/v1/sessions/1/rename",
        headers={"X-CSRF-Token": csrf},
        json=payload,
    )
    assert renamed.status_code == 200
    assert fake.renamed == [("1", "Refactoring Codex")]

    invalid = client.post(
        "/api/v1/sessions/1/rename",
        headers={"X-CSRF-Token": csrf},
        json={"name": "bad:name"},
    )
    assert invalid.status_code == 422
    missing = client.post(
        "/api/v1/sessions/9/rename",
        headers={"X-CSRF-Token": csrf},
        json=payload,
    )
    assert missing.status_code == 404


def test_create_and_rename_session_support_accented_names() -> None:
    client, fake = client_and_fake()
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}

    created = client.post(
        "/api/v1/sessions",
        headers=headers,
        json={"name": "osservabilità", "directory": "/workspace"},
    )
    assert created.status_code == 201

    renamed = client.post(
        "/api/v1/sessions/1/rename",
        headers=headers,
        json={"name": "analisi qualità"},
    )
    assert renamed.status_code == 200
    assert fake.renamed == [("1", "analisi qualità")]


def test_config_exposes_allowed_roots_to_authenticated_users() -> None:
    client, _ = client_and_fake()
    assert client.get("/api/v1/config").status_code == 401
    login(client)
    body = client.get("/api/v1/config").json()
    assert body["allowed_roots"] == ["/workspace"]
    assert body["workspace_presets"] == {}


def test_config_parses_workspace_presets_csv() -> None:
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        workspace_presets="pipeline=/workspace/pipeline, tools=/workspace/tools",
    )
    client = TestClient(create_app(settings, FakeTmux()))
    login(client)
    assert client.get("/api/v1/config").json()["workspace_presets"] == {
        "pipeline": "/workspace/pipeline",
        "tools": "/workspace/tools",
    }


def test_missing_session_and_invalid_ids() -> None:
    client, _ = client_and_fake()
    csrf = login(client)
    assert client.get("/api/v1/sessions/9/output").status_code == 404
    assert client.get("/api/v1/sessions/not-numeric/output").status_code == 400
    response = client.post(
        "/api/v1/sessions/1/keys",
        headers={"X-CSRF-Token": csrf},
        json={"key": "C-c"},
    )
    assert response.status_code == 400


def test_create_session_fails_clearly_without_host_server() -> None:
    client, fake = client_and_fake()
    csrf = login(client)
    fake.server_down = True
    response = client.post(
        "/api/v1/sessions",
        headers={"X-CSRF-Token": csrf},
        json={"name": "new-session", "directory": "/workspace"},
    )
    assert response.status_code == 409


def test_create_and_rename_report_duplicate_session_name() -> None:
    client, fake = client_and_fake()
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    fake.duplicate_name = True

    created = client.post(
        "/api/v1/sessions",
        headers=headers,
        json={"name": "demo", "directory": "/workspace"},
    )
    assert created.status_code == 409
    assert created.json()["detail"] == "Session name already exists"

    renamed = client.post(
        "/api/v1/sessions/1/rename",
        headers=headers,
        json={"name": "demo"},
    )
    assert renamed.status_code == 409
    assert renamed.json()["detail"] == "Session name already exists"


def test_snapshot_create_restore_list_and_delete(tmp_path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    fake = FakeTmux()
    fake.directory = str(workspace)
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        allowed_roots=[str(tmp_path)],
        snapshots_root=str(tmp_path / ".snapshots"),
    )
    client = TestClient(create_app(settings, fake))
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}

    assert client.get("/api/v1/snapshots").json() == {"snapshots": []}
    assert client.post(
        "/api/v1/snapshots",
        json={
            "name": "Before reboot",
            "sessions": [{"session_id": "1", "mode": "codex"}],
        },
    ).status_code == 403
    created = client.post(
        "/api/v1/snapshots",
        headers=headers,
        json={
            "name": "Before reboot",
            "sessions": [{"session_id": "1", "mode": "codex"}],
        },
    )
    assert created.status_code == 201
    snapshot = created.json()
    assert snapshot["name"] == "Before reboot"
    assert snapshot["sessions"] == [
        {
            "name": "demo",
            "directory": str(workspace),
            "mode": "codex",
            "observed_command": "bash",
        }
    ]
    assert client.get("/api/v1/snapshots").json()["snapshots"][0]["id"] == snapshot["id"]

    denied = client.post(
        f"/api/v1/snapshots/{snapshot['id']}/restore",
        headers=headers,
        json={"confirmed": False},
    )
    assert denied.status_code == 400

    fake.sessions.clear()
    restored = client.post(
        f"/api/v1/snapshots/{snapshot['id']}/restore",
        headers=headers,
        json={"confirmed": True},
    )
    assert restored.status_code == 200
    assert restored.json()["results"] == [
        {
            "name": "demo",
            "status": "restored",
            "detail": "Shell restored; codex resume picker launched",
        }
    ]
    assert [item.name for item in fake.sessions.values()] == ["demo"]
    assert fake.texts == ["codex resume"]
    assert fake.keys == ["Enter"]

    assert client.request(
        "DELETE",
        f"/api/v1/snapshots/{snapshot['id']}",
        headers=headers,
        json={"confirmed": False},
    ).status_code == 400
    deleted = client.request(
        "DELETE",
        f"/api/v1/snapshots/{snapshot['id']}",
        headers=headers,
        json={"confirmed": True},
    )
    assert deleted.status_code == 204
    assert client.get("/api/v1/snapshots").json() == {"snapshots": []}


def test_snapshot_restore_skips_existing_name(tmp_path) -> None:
    fake = FakeTmux()
    fake.directory = str(tmp_path)
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        allowed_roots=[str(tmp_path)],
        snapshots_root=str(tmp_path / ".snapshots"),
    )
    client = TestClient(create_app(settings, fake))
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    created = client.post(
        "/api/v1/snapshots",
        headers=headers,
        json={
            "name": "Conflict",
            "sessions": [{"session_id": "1", "mode": "shell"}],
        },
    ).json()

    restored = client.post(
        f"/api/v1/snapshots/{created['id']}/restore",
        headers=headers,
        json={"confirmed": True},
    )
    assert restored.json()["results"] == [
        {
            "name": "demo",
            "status": "skipped",
            "detail": "A session with this name already exists",
        }
    ]


def test_snapshot_restore_launches_opencode_without_continue(tmp_path) -> None:
    # Il ramo "opencode" del restore non deve sparire nel default ("shell"
    # generico): senza questo ramo la sessione salvata verrebbe ripristinata
    # come una shell vuota, perdendo il profilo. Nessun testo di ripresa
    # viene iniettato (niente `--continue`/`--session`): coerente con la
    # decisione di ROOT in IMP-OC-01.
    fake = FakeTmux()
    fake.directory = str(tmp_path)
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        allowed_roots=[str(tmp_path)],
        snapshots_root=str(tmp_path / ".snapshots"),
    )
    client = TestClient(create_app(settings, fake))
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    created = client.post(
        "/api/v1/snapshots",
        headers=headers,
        json={
            "name": "Before reboot",
            "sessions": [{"session_id": "1", "mode": "opencode"}],
        },
    ).json()

    fake.sessions.clear()
    restored = client.post(
        f"/api/v1/snapshots/{created['id']}/restore",
        headers=headers,
        json={"confirmed": True},
    )
    assert restored.status_code == 200
    assert restored.json()["results"] == [
        {
            "name": "demo",
            "status": "restored",
            "detail": "OpenCode launched; resume the conversation from its own /sessions picker",
        }
    ]
    assert fake.created == [("demo", str(tmp_path), "opencode", False)]
    assert fake.texts == []
    assert fake.keys == []


def test_websocket_auth_and_snapshot() -> None:
    client, _ = client_and_fake()
    with pytest.raises(WebSocketDisconnect) as rejected, client.websocket_connect(
        "/api/v1/ws/sessions/1", headers={"origin": "http://testserver"}
    ):
        pass
    assert rejected.value.code == 4401
    login(client)
    with client.websocket_connect("/api/v1/ws/sessions/1", headers={"origin": "http://testserver"}) as ws:
        message = ws.receive_json()
        assert message["type"] == "snapshot"
        assert message["content"] == "$ "


def test_websocket_ansi_opt_in_defaults_to_plain_capture() -> None:
    client, fake = client_and_fake()
    login(client)
    with client.websocket_connect("/api/v1/ws/sessions/1", headers={"origin": "http://testserver"}):
        pass
    assert fake.capture_ansi_calls == [False]

    with client.websocket_connect(
        "/api/v1/ws/sessions/1?ansi=true", headers={"origin": "http://testserver"}
    ):
        pass
    assert fake.capture_ansi_calls == [False, True]


def test_websocket_lines_param_controls_capture_depth() -> None:
    client, fake = client_and_fake()
    login(client)
    with client.websocket_connect("/api/v1/ws/sessions/1", headers={"origin": "http://testserver"}):
        pass
    assert fake.capture_lines_calls == [500]

    with client.websocket_connect(
        "/api/v1/ws/sessions/1?lines=1000", headers={"origin": "http://testserver"}
    ):
        pass
    assert fake.capture_lines_calls == [500, 1000]

    with pytest.raises(WebSocketDisconnect), client.websocket_connect(
        "/api/v1/ws/sessions/1?lines=50", headers={"origin": "http://testserver"}
    ):
        pass
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(
        "/api/v1/ws/sessions/1?lines=5000", headers={"origin": "http://testserver"}
    ):
        pass


def test_create_session_requires_allowed_directory() -> None:
    client, fake = client_and_fake()
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    allowed = client.post(
        "/api/v1/sessions", headers=headers, json={"name": "new-session", "directory": "/workspace"}
    )
    assert allowed.status_code == 201
    spaced = client.post(
        "/api/v1/sessions",
        headers=headers,
        json={"name": "Refactoring Codex", "directory": "/workspace"},
    )
    assert spaced.status_code == 201
    codex = client.post(
        "/api/v1/sessions",
        headers=headers,
        json={"name": "Codex Agent", "directory": "/workspace", "profile": "codex"},
    )
    assert codex.status_code == 201
    assert any(session.name == "Codex Agent" and session.current_command == "codex"
               for session in fake.sessions.values())
    antigravity = client.post(
        "/api/v1/sessions",
        headers=headers,
        json={"name": "Antigravity Agent", "directory": "/workspace", "profile": "antigravity"},
    )
    assert antigravity.status_code == 201
    assert any(session.name == "Antigravity Agent" and session.current_command == "agy"
               for session in fake.sessions.values())
    antigravity_yolo = client.post(
        "/api/v1/sessions",
        headers=headers,
        json={
            "name": "Antigravity Yolo Agent",
            "directory": "/workspace",
            "profile": "antigravity_yolo",
        },
    )
    assert antigravity_yolo.status_code == 201
    assert any(session.name == "Antigravity Yolo Agent" and session.current_command == "agy"
               for session in fake.sessions.values())
    opencode = client.post(
        "/api/v1/sessions",
        headers=headers,
        json={"name": "OpenCode Agent", "directory": "/workspace", "profile": "opencode"},
    )
    assert opencode.status_code == 201
    assert any(session.name == "OpenCode Agent" and session.current_command == "opencode"
               for session in fake.sessions.values())
    opencode_yolo = client.post(
        "/api/v1/sessions",
        headers=headers,
        json={
            "name": "OpenCode Yolo Agent",
            "directory": "/workspace",
            "profile": "opencode_yolo",
        },
    )
    assert opencode_yolo.status_code == 201
    assert any(
        session.name == "OpenCode Yolo Agent" and session.current_command == "opencode"
        for session in fake.sessions.values()
    )
    unsupported = client.post(
        "/api/v1/sessions",
        headers=headers,
        json={"name": "unsafe-profile", "directory": "/workspace", "profile": "custom"},
    )
    assert unsupported.status_code == 422
    denied = client.post(
        "/api/v1/sessions", headers=headers, json={"name": "unsafe", "directory": "/etc"}
    )
    assert denied.status_code == 400


def test_session_directory_lists_entries(tmp_path) -> None:
    (tmp_path / "notes.txt").write_text("hello")
    notes_modified_at = datetime(2026, 7, 24, 10, 30, tzinfo=UTC)
    os.utime(tmp_path / "notes.txt", (notes_modified_at.timestamp(), notes_modified_at.timestamp()))
    (tmp_path / "archive.tar.gz").write_bytes(b"0" * 42)
    (tmp_path / "src").mkdir()
    fake = FakeTmux()
    fake.directory = str(tmp_path)
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        allowed_roots=[str(tmp_path)],
    )
    client = TestClient(create_app(settings, fake))
    assert client.get("/api/v1/sessions/1/directory").status_code == 401
    login(client)
    response = client.get("/api/v1/sessions/1/directory")
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "1"
    assert body["path"] == str(tmp_path)
    assert body["root"] == str(tmp_path)
    assert body["parent"] is None
    assert body["truncated"] is False
    names = [entry["name"] for entry in body["entries"]]
    assert names == ["src", "archive.tar.gz", "notes.txt"]
    by_name = {entry["name"]: entry for entry in body["entries"]}
    assert by_name["src"]["type"] == "dir"
    assert by_name["src"]["size"] is None
    assert by_name["archive.tar.gz"]["type"] == "file"
    assert by_name["archive.tar.gz"]["size"] == 42
    assert by_name["notes.txt"]["created_at"] is not None
    assert by_name["notes.txt"]["modified_at"] == "2026-07-24T10:30:00Z"


def test_session_directory_requires_allowed_root(tmp_path) -> None:
    fake = FakeTmux()
    fake.directory = "/etc"
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        allowed_roots=[str(tmp_path)],
    )
    client = TestClient(create_app(settings, fake))
    login(client)
    assert client.get("/api/v1/sessions/1/directory").status_code == 400


def test_session_directory_missing_and_invalid_session() -> None:
    client, _ = client_and_fake()
    login(client)
    assert client.get("/api/v1/sessions/9/directory").status_code == 404
    assert client.get("/api/v1/sessions/not-numeric/directory").status_code == 400


def test_session_directory_navigates_via_path_param(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "nested").mkdir()
    fake = FakeTmux()
    fake.directory = str(tmp_path)
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        allowed_roots=[str(tmp_path)],
    )
    client = TestClient(create_app(settings, fake))
    login(client)

    child = client.get("/api/v1/sessions/1/directory", params={"path": str(tmp_path / "src")})
    assert child.status_code == 200
    child_body = child.json()
    assert child_body["path"] == str(tmp_path / "src")
    assert child_body["root"] == str(tmp_path)
    assert child_body["parent"] == str(tmp_path)
    assert [entry["name"] for entry in child_body["entries"]] == ["nested"]

    # Con un path esplicito non serve interrogare tmux (niente pane_path), quindi
    # anche un session id numerico ma inesistente va bene; il formato va comunque
    # rispettato.
    missing_session = client.get("/api/v1/sessions/9/directory", params={"path": str(tmp_path)})
    assert missing_session.status_code == 200
    invalid_id = client.get("/api/v1/sessions/not-numeric/directory", params={"path": str(tmp_path)})
    assert invalid_id.status_code == 400

    outside = client.get("/api/v1/sessions/1/directory", params={"path": "/etc"})
    assert outside.status_code == 400


def test_upload_directory_file_success(tmp_path) -> None:
    fake = FakeTmux()
    fake.directory = str(tmp_path)
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        allowed_roots=[str(tmp_path)],
    )
    client = TestClient(create_app(settings, fake))
    csrf_token = login(client)
    headers = {"X-CSRF-Token": csrf_token, "Content-Type": "image/png"}
    content = b"\x89PNG\r\n\x1a\nfake-image-bytes"

    res = client.post(
        "/api/v1/sessions/1/directory/upload",
        params={"filename": "photo.png"},
        headers=headers,
        content=content,
    )
    assert res.status_code == 201
    body = res.json()
    assert body["session_id"] == "1"
    assert body["name"] == "photo.png"
    assert body["size"] == len(content)
    assert (tmp_path / "photo.png").read_bytes() == content

    # Test uploading .md in subfolder with path param
    sub = tmp_path / "docs"
    sub.mkdir()
    md_content = b"# Header\nDoc content"
    res_sub = client.post(
        "/api/v1/sessions/1/directory/upload",
        params={"path": str(sub), "filename": "readme.md"},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "text/markdown"},
        content=md_content,
    )
    assert res_sub.status_code == 201
    assert (sub / "readme.md").read_bytes() == md_content


def test_upload_directory_file_rejects_disallowed_extension(tmp_path) -> None:
    fake = FakeTmux()
    fake.directory = str(tmp_path)
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        allowed_roots=[str(tmp_path)],
    )
    client = TestClient(create_app(settings, fake))
    csrf_token = login(client)

    res = client.post(
        "/api/v1/sessions/1/directory/upload",
        params={"filename": "script.py"},
        headers={"X-CSRF-Token": csrf_token},
        content=b"print('hello')",
    )
    assert res.status_code == 400
    assert "File extension '.py' is not allowed" in res.json()["detail"]


def test_upload_directory_file_rejects_exceeding_max_bytes(tmp_path) -> None:
    fake = FakeTmux()
    fake.directory = str(tmp_path)
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        allowed_roots=[str(tmp_path)],
        max_upload_bytes=50,
    )
    client = TestClient(create_app(settings, fake))
    csrf_token = login(client)

    res = client.post(
        "/api/v1/sessions/1/directory/upload",
        params={"filename": "notes.md"},
        headers={"X-CSRF-Token": csrf_token},
        content=b"A" * 100,
    )
    assert res.status_code == 400
    assert "File exceeds maximum upload size" in res.json()["detail"]


def test_upload_directory_file_security_and_traversal(tmp_path) -> None:
    fake = FakeTmux()
    fake.directory = str(tmp_path)
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        allowed_roots=[str(tmp_path)],
    )
    client = TestClient(create_app(settings, fake))
    csrf_token = login(client)

    # Path traversal attempt in filename
    res1 = client.post(
        "/api/v1/sessions/1/directory/upload",
        params={"filename": "../evil.md"},
        headers={"X-CSRF-Token": csrf_token},
        content=b"evil",
    )
    assert res1.status_code == 400

    # Invalid filename pattern (contains hyphen or space)
    res_hyphen = client.post(
        "/api/v1/sessions/1/directory/upload",
        params={"filename": "my-file.md"},
        headers={"X-CSRF-Token": csrf_token},
        content=b"test",
    )
    assert res_hyphen.status_code == 400
    assert "Filename must contain only letters, numbers, and underscores" in res_hyphen.json()["detail"]

    res_space = client.post(
        "/api/v1/sessions/1/directory/upload",
        params={"filename": "my file.md"},
        headers={"X-CSRF-Token": csrf_token},
        content=b"test",
    )
    assert res_space.status_code == 400
    assert "Filename must contain only letters, numbers, and underscores" in res_space.json()["detail"]

    # Path parameter outside allowed roots
    res2 = client.post(
        "/api/v1/sessions/1/directory/upload",
        params={"path": "/etc", "filename": "evil.md"},
        headers={"X-CSRF-Token": csrf_token},
        content=b"evil",
    )
    assert res2.status_code == 400


def test_session_file_reads_text_content(tmp_path) -> None:
    (tmp_path / "notes.md").write_text("# Titolo\n\nCiao à è ⚡\n")
    fake = FakeTmux()
    fake.directory = str(tmp_path)
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        allowed_roots=[str(tmp_path)],
    )
    client = TestClient(create_app(settings, fake))
    assert client.get(
        "/api/v1/sessions/1/file", params={"path": str(tmp_path / "notes.md")}
    ).status_code == 401
    login(client)
    response = client.get("/api/v1/sessions/1/file", params={"path": str(tmp_path / "notes.md")})
    assert response.status_code == 200
    body = response.json()
    assert body["path"] == str(tmp_path / "notes.md")
    assert body["content"] == "# Titolo\n\nCiao à è ⚡\n"
    assert body["truncated"] is False
    assert body["size"] == len("# Titolo\n\nCiao à è ⚡\n".encode())


def test_session_file_preview_roots_map_external_paths_read_only(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    mount_base = tmp_path / "preview"
    mounted_root = mount_base / "external-preview-test"
    mounted_root.mkdir(parents=True)
    report = mounted_root / "report.md"
    report.write_text("# Report esterno\n")
    modified_at = datetime(2026, 8, 22, 11, 45, tzinfo=UTC)
    os.utime(report, (modified_at.timestamp(), modified_at.timestamp()))
    fake = FakeTmux()
    fake.directory = str(workspace)
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        allowed_roots=[str(workspace)],
        preview_roots=["/external-preview-test"],
        preview_mount_root=str(mount_base),
    )
    client = TestClient(create_app(settings, fake))
    login(client)

    metadata = client.get(
        "/api/v1/sessions/1/file/metadata",
        params={"path": "/external-preview-test/report.md"},
    )
    assert metadata.status_code == 200
    assert metadata.json() == {
        "session_id": "1",
        "path": "/external-preview-test/report.md",
        "size": len("# Report esterno\n"),
        "modified_at": "2026-08-22T11:45:00Z",
        "media_type": "text/markdown",
    }
    content = client.get(
        "/api/v1/sessions/1/file",
        params={"path": "/external-preview-test/report.md"},
    )
    assert content.status_code == 200
    assert content.json()["content"] == "# Report esterno\n"
    assert content.json()["path"] == "/external-preview-test/report.md"


def test_session_file_preview_roots_reject_outside_and_symlink_escape(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    mount_base = tmp_path / "preview"
    mounted_root = mount_base / "external-preview-test"
    mounted_root.mkdir(parents=True)
    outside = tmp_path / "secret.md"
    outside.write_text("segreto")
    (mounted_root / "escape.md").symlink_to(outside)
    fake = FakeTmux()
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        allowed_roots=[str(workspace)],
        preview_roots=["/external-preview-test"],
        preview_mount_root=str(mount_base),
    )
    client = TestClient(create_app(settings, fake))
    login(client)
    url = "/api/v1/sessions/1/file/metadata"

    assert client.get(url, params={"path": "/outside/report.md"}).status_code == 400
    assert client.get(
        url, params={"path": "/external-preview-test/escape.md"}
    ).status_code == 400


def test_preview_roots_reject_filesystem_root() -> None:
    with pytest.raises(ValueError, match="must not expose the filesystem root"):
        Settings(preview_roots=["/"])


def test_session_file_rejects_binary_missing_and_directory(tmp_path) -> None:
    (tmp_path / "image.bin").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x01\x02")
    (tmp_path / "src").mkdir()
    fake = FakeTmux()
    fake.directory = str(tmp_path)
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        allowed_roots=[str(tmp_path)],
    )
    client = TestClient(create_app(settings, fake))
    login(client)

    binary = client.get("/api/v1/sessions/1/file", params={"path": str(tmp_path / "image.bin")})
    assert binary.status_code == 400

    missing = client.get("/api/v1/sessions/1/file", params={"path": str(tmp_path / "missing.txt")})
    assert missing.status_code == 404

    is_dir = client.get("/api/v1/sessions/1/file", params={"path": str(tmp_path / "src")})
    assert is_dir.status_code == 400

    outside = client.get("/api/v1/sessions/1/file", params={"path": "/etc/hostname"})
    assert outside.status_code == 400


def test_session_file_truncates_large_files(tmp_path) -> None:
    big_file = tmp_path / "big.txt"
    big_file.write_text("x" * (256 * 1024 + 10))
    fake = FakeTmux()
    fake.directory = str(tmp_path)
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        allowed_roots=[str(tmp_path)],
    )
    client = TestClient(create_app(settings, fake))
    login(client)
    response = client.get("/api/v1/sessions/1/file", params={"path": str(big_file)})
    assert response.status_code == 200
    body = response.json()
    assert body["truncated"] is True
    assert len(body["content"]) == 256 * 1024
    assert body["size"] == 256 * 1024 + 10


def test_session_file_truncation_does_not_split_utf8_character(tmp_path) -> None:
    prefix = b"x" * (256 * 1024 - 1)
    content = prefix + "€continua".encode()
    text_file = tmp_path / "utf8.txt"
    text_file.write_bytes(content)
    fake = FakeTmux()
    fake.directory = str(tmp_path)
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        allowed_roots=[str(tmp_path)],
    )
    client = TestClient(create_app(settings, fake))
    login(client)

    response = client.get("/api/v1/sessions/1/file", params={"path": str(text_file)})
    assert response.status_code == 200
    body = response.json()
    assert body["content"] == prefix.decode()
    assert body["truncated"] is True
    assert body["size"] == len(content)


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("diagram.png", b"\x89PNG\r\n\x1a\nfake"),
        ("report.pdf", b"%PDF-1.7\nfake"),
        ("notes.doc", b"legacy-word"),
        ("notes.docx", b"zip-like-word"),
        ("memo.m4a", b"\x00\x00\x00\x18ftypM4A " + b"\x00" * 32),
        ("recording.mp3", b"ID3\x04\x00\x00\x00\x00\x00\x00fake"),
    ],
)
def test_session_file_downloads_supported_binary_types(
    tmp_path,
    filename: str,
    content: bytes,
) -> None:
    file_path = tmp_path / filename
    file_path.write_bytes(content)
    fake = FakeTmux()
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        allowed_roots=[str(tmp_path)],
    )
    client = TestClient(create_app(settings, fake))
    url = "/api/v1/sessions/1/file/download"
    assert client.get(url, params={"path": str(file_path)}).status_code == 401
    login(client)

    response = client.get(url, params={"path": str(file_path)})
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-disposition"].startswith("attachment;")
    assert filename in response.headers["content-disposition"]


def test_session_file_download_rejects_unsupported_and_outside_paths(tmp_path) -> None:
    text_file = tmp_path / "notes.txt"
    text_file.write_text("preview only")
    fake = FakeTmux()
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        allowed_roots=[str(tmp_path)],
    )
    client = TestClient(create_app(settings, fake))
    login(client)
    url = "/api/v1/sessions/1/file/download"

    unsupported = client.get(url, params={"path": str(text_file)})
    assert unsupported.status_code == 400
    outside = client.get(url, params={"path": "/etc/hostname"})
    assert outside.status_code == 400
    missing = client.get(url, params={"path": str(tmp_path / "missing.pdf")})
    assert missing.status_code == 404


def test_attachment_upload_requires_database() -> None:
    client, _ = client_and_fake()
    csrf = login(client)
    response = client.post(
        "/api/v1/sessions/1/attachments?filename=note.txt",
        content=b"hello",
        headers={"X-CSRF-Token": csrf, "Content-Type": "text/plain"},
    )
    assert response.status_code == 503
    # Un invio senza allegati referenziati non deve richiedere il database.
    plain = client.post(
        "/api/v1/sessions/1/input",
        headers={"X-CSRF-Token": csrf},
        json={"text": "ciao", "attachment_ids": []},
    )
    assert plain.status_code == 202


def test_upload_attachment_and_reference_it_in_prompt(tmp_path) -> None:
    fake = FakeTmux()
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        attachments_root=str(tmp_path),
        attachments_prompt_root="/workspace/.agent-attachments",
        max_attachment_bytes=1024,
        database_path=migrated_database_with_admin(tmp_path),
        database_auth_enabled=True,
        push_vapid_key_path=str(tmp_path / "vapid.pem"),
    )
    client = TestClient(create_app(settings, fake))
    csrf = login_admin(client)
    headers = {"X-CSRF-Token": csrf, "Content-Type": "image/png"}
    content = b"\x89PNG\r\n\x1a\nminimal"

    assert client.post(
        "/api/v1/sessions/1/attachments?filename=screenshot.png",
        content=content,
        headers={"Content-Type": "image/png"},
    ).status_code == 403
    uploaded = client.post(
        "/api/v1/sessions/1/attachments?filename=screenshot.png",
        content=content,
        headers=headers,
    )
    assert uploaded.status_code == 201
    attachment = uploaded.json()
    assert attachment["name"] == "screenshot.png"
    assert attachment["path"].startswith("/workspace/.agent-attachments/1/")

    response = client.post(
        "/api/v1/sessions/1/input",
        headers={"X-CSRF-Token": csrf},
        json={"text": "Analizza questo errore", "attachment_ids": [attachment["id"]]},
    )
    assert response.status_code == 202
    assert fake.texts == [
        (
            f'Analizza questo errore\n\nAllegati disponibili:\n'
            f'- "screenshot.png": {attachment["path"]}'
        )
    ]
    wrong_session = client.post(
        "/api/v1/sessions/2/input",
        headers={"X-CSRF-Token": csrf},
        json={"text": "test", "attachment_ids": [attachment["id"]]},
    )
    assert wrong_session.status_code == 400
    delete_path = f"/api/v1/sessions/1/attachments/{attachment['id']}"
    assert client.delete(delete_path).status_code == 403
    assert client.delete(delete_path, headers={"X-CSRF-Token": csrf}).status_code == 204
    assert list(tmp_path.glob("1/*")) == []
    deleted_reference = client.post(
        "/api/v1/sessions/1/input",
        headers={"X-CSRF-Token": csrf},
        json={"text": "test", "attachment_ids": [attachment["id"]]},
    )
    assert deleted_reference.status_code == 400


def test_upload_mp3_attachment_and_reference_it_in_prompt(tmp_path) -> None:
    fake = FakeTmux()
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        attachments_root=str(tmp_path),
        attachments_prompt_root="/workspace/.agent-attachments",
        max_attachment_bytes=1024,
        database_path=migrated_database_with_admin(tmp_path),
        database_auth_enabled=True,
        push_vapid_key_path=str(tmp_path / "vapid.pem"),
    )
    client = TestClient(create_app(settings, fake))
    csrf = login_admin(client)
    headers = {"X-CSRF-Token": csrf, "Content-Type": "audio/mpeg"}
    content = b"ID3\x04\x00\x00\x00\x00\x00\x00audio"

    uploaded = client.post(
        "/api/v1/sessions/1/attachments?filename=recording.mp3",
        content=content,
        headers=headers,
    )
    assert uploaded.status_code == 201
    attachment = uploaded.json()
    assert attachment["name"] == "recording.mp3"
    assert attachment["media_type"] == "audio/mpeg"
    assert attachment["path"].endswith(".mp3")

    sent = client.post(
        "/api/v1/sessions/1/input",
        headers={"X-CSRF-Token": csrf},
        json={"text": "Trascrivi", "attachment_ids": [attachment["id"]]},
    )
    assert sent.status_code == 202
    assert '"recording.mp3"' in fake.texts[-1]
    assert attachment["path"] in fake.texts[-1]

    invalid = client.post(
        "/api/v1/sessions/1/attachments?filename=fake.mp3",
        content=b"not really audio",
        headers=headers,
    )
    assert invalid.status_code == 400


def test_attachment_preview_only_for_images(tmp_path) -> None:
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        attachments_root=str(tmp_path),
        database_path=migrated_database_with_admin(tmp_path),
        database_auth_enabled=True,
        push_vapid_key_path=str(tmp_path / "vapid.pem"),
    )
    client = TestClient(create_app(settings, FakeTmux()))
    csrf = login_admin(client)
    headers = {"X-CSRF-Token": csrf}

    buffer = BytesIO()
    Image.new("RGB", (300, 300), color="red").save(buffer, format="PNG")
    image = client.post(
        "/api/v1/sessions/1/attachments?filename=photo.png",
        content=buffer.getvalue(),
        headers={**headers, "Content-Type": "image/png"},
    ).json()
    preview = client.get(f"/api/v1/sessions/1/attachments/{image['id']}/preview")
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/jpeg"
    with Image.open(BytesIO(preview.content)) as thumbnail:
        assert thumbnail.size <= (256, 256)

    text = client.post(
        "/api/v1/sessions/1/attachments?filename=notes.txt",
        content=b"hello",
        headers={**headers, "Content-Type": "text/plain"},
    ).json()
    assert client.get(
        f"/api/v1/sessions/1/attachments/{text['id']}/preview"
    ).status_code == 404

    client.delete(f"/api/v1/sessions/1/attachments/{image['id']}", headers=headers)
    assert client.get(
        f"/api/v1/sessions/1/attachments/{image['id']}/preview"
    ).status_code == 404


def test_attachment_deduplicates_identical_content_within_session(tmp_path) -> None:
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        attachments_root=str(tmp_path),
        database_path=migrated_database_with_admin(tmp_path),
        database_auth_enabled=True,
        push_vapid_key_path=str(tmp_path / "vapid.pem"),
    )
    fake = FakeTmux()
    fake.sessions["2"] = type(fake.sessions["1"])(
        "2", "demo-2", False, 1, "bash", datetime.now(UTC)
    )
    client = TestClient(create_app(settings, fake))
    csrf = login_admin(client)
    headers = {"X-CSRF-Token": csrf, "Content-Type": "text/plain"}
    content = b"identical content"

    first = client.post(
        "/api/v1/sessions/1/attachments?filename=a.txt", content=content, headers=headers
    ).json()
    second = client.post(
        "/api/v1/sessions/1/attachments?filename=b.txt", content=content, headers=headers
    ).json()
    assert first["path"] == second["path"]
    stored_files = list((tmp_path / "1").glob("*.txt"))
    assert len(stored_files) == 1

    other_session = client.post(
        "/api/v1/sessions/2/attachments?filename=c.txt", content=content, headers=headers
    ).json()
    assert other_session["path"] != first["path"]

    client.delete(f"/api/v1/sessions/1/attachments/{first['id']}", headers=headers)
    assert list((tmp_path / "1").glob("*.txt")) == [Path(stored_files[0])]
    client.delete(f"/api/v1/sessions/1/attachments/{second['id']}", headers=headers)
    assert list((tmp_path / "1").glob("*.txt")) == []


def test_terminating_session_cleans_up_its_attachments(tmp_path) -> None:
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        attachments_root=str(tmp_path),
        database_path=migrated_database_with_admin(tmp_path),
        database_auth_enabled=True,
        push_vapid_key_path=str(tmp_path / "vapid.pem"),
    )
    client = TestClient(create_app(settings, FakeTmux()))
    csrf = login_admin(client)
    headers = {"X-CSRF-Token": csrf}
    uploaded = client.post(
        "/api/v1/sessions/1/attachments?filename=notes.txt",
        content=b"hello",
        headers={**headers, "Content-Type": "text/plain"},
    ).json()
    assert (tmp_path / "1").exists()

    terminated = client.request(
        "DELETE", "/api/v1/sessions/1", headers=headers, json={"confirmed": True}
    )
    assert terminated.status_code == 204
    # la sessione terminata libera l'id numerico, che tmux può riassegnare a
    # una sessione futura scollegata: gli allegati non devono sopravvivere.
    assert not (tmp_path / "1").exists()
    assert client.get(
        f"/api/v1/sessions/1/attachments/{uploaded['id']}/preview"
    ).status_code == 404


def test_reserved_session_is_hidden_and_termination_refused_even_by_known_id() -> None:
    # INC-HOST-01: nascondere non basta, l'id resta un target tmux valido.
    client, fake = client_and_fake()
    fake.protected_session_id = "1"
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}

    listed = client.get("/api/v1/sessions").json()["sessions"]
    assert all(item["id"] != "1" for item in listed)

    terminated = client.request(
        "DELETE", "/api/v1/sessions/1", headers=headers, json={"confirmed": True}
    )
    assert terminated.status_code == 409
    assert terminated.json()["detail"] == "Refusing to terminate the reserved keepalive session"
    # non toccata: la sessione fake resta viva dopo il rifiuto.
    assert "1" in fake.sessions


def test_artifacts_require_authentication() -> None:
    client, _ = client_and_fake()
    assert client.get("/api/v1/sessions/1/artifact-directory").status_code == 401
    assert client.get("/api/v1/sessions/1/artifacts").status_code == 401
    assert client.get("/api/v1/sessions/1/artifacts/note.txt").status_code == 401
    assert client.get("/api/v1/sessions/1/archive-draft").status_code == 401


def test_list_and_download_artifacts(tmp_path) -> None:
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        artifacts_root=str(tmp_path),
    )
    client = TestClient(create_app(settings, FakeTmux()))
    login(client)
    session_dir = tmp_path / "1"
    session_dir.mkdir(parents=True)
    (session_dir / "report.pdf").write_bytes(b"%PDF-1.4\nhello")
    (session_dir / "recording.mp3").write_bytes(b"ID3\x04\x00\x00\x00\x00\x00\x00hello")
    (session_dir / "memo.m4a").write_bytes(b"\x00\x00\x00\x18ftypM4A " + b"\x00" * 32)
    (session_dir / "unrecognized.bin").write_bytes(b"\x01\x02\x03")
    (session_dir / "archive-summary.md").write_text("Riepilogo riservato", encoding="utf-8")

    listed = client.get("/api/v1/sessions/1/artifacts").json()
    assert [item["name"] for item in listed] == ["memo.m4a", "recording.mp3", "report.pdf"]
    assert listed[0]["media_type"] == "audio/mp4"
    assert listed[1]["media_type"] == "audio/mpeg"
    assert listed[2]["media_type"] == "application/pdf"

    downloaded = client.get("/api/v1/sessions/1/artifacts/report.pdf")
    assert downloaded.status_code == 200
    assert downloaded.content == b"%PDF-1.4\nhello"
    assert downloaded.headers["content-type"] == "application/pdf"

    downloaded_mp3 = client.get("/api/v1/sessions/1/artifacts/recording.mp3")
    assert downloaded_mp3.status_code == 200
    assert downloaded_mp3.headers["content-type"] == "audio/mpeg"

    downloaded_m4a = client.get("/api/v1/sessions/1/artifacts/memo.m4a")
    assert downloaded_m4a.status_code == 200
    assert downloaded_m4a.headers["content-type"] == "audio/mp4"

    assert client.get("/api/v1/sessions/1/artifacts/unrecognized.bin").status_code == 404
    assert client.get("/api/v1/sessions/1/artifacts/missing.pdf").status_code == 404
    assert client.get("/api/v1/sessions/1/artifacts/archive-summary.md").status_code == 404


def test_archive_draft_reads_only_a_small_valid_reserved_summary(tmp_path) -> None:
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        artifacts_root=str(tmp_path),
    )
    client = TestClient(create_app(settings, FakeTmux()))
    login(client)
    session_dir = tmp_path / "1"
    session_dir.mkdir(parents=True)

    assert client.get("/api/v1/sessions/1/archive-draft").json() == {"summary": None}
    (session_dir / "archive-summary.md").write_text("  Stato della sessione.  ", encoding="utf-8")
    assert client.get("/api/v1/sessions/1/archive-draft").json() == {
        "summary": "Stato della sessione."
    }
    (session_dir / "archive-summary.md").write_bytes(b"\xff")
    assert client.get("/api/v1/sessions/1/archive-draft").json() == {"summary": None}
    (session_dir / "archive-summary.md").write_bytes(b"x" * 8193)
    assert client.get("/api/v1/sessions/1/archive-draft").json() == {"summary": None}
    assert client.get("/api/v1/sessions/999/archive-draft").status_code == 404


def test_artifact_directory_uses_the_path_visible_to_the_session(tmp_path) -> None:
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        artifacts_root=str(tmp_path / "storage"),
        artifacts_prompt_root="/workspace/.agent-artifacts",
    )
    client = TestClient(create_app(settings, FakeTmux()))
    login(client)

    response = client.get("/api/v1/sessions/1/artifact-directory")

    assert response.status_code == 200
    assert response.json() == {"path": "/workspace/.agent-artifacts/1"}
    assert client.get("/api/v1/sessions/not-an-id/artifact-directory").status_code == 400


def test_create_session_does_not_interrupt_cli_first_run(tmp_path) -> None:
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        artifacts_root=str(tmp_path),
    )
    fake = FakeTmux()
    client = TestClient(create_app(settings, fake))
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    client.post(
        "/api/v1/sessions",
        headers=headers,
        json={"name": "shell-one", "directory": "/workspace", "profile": "shell"},
    )
    assert fake.texts == []
    assert fake.keys == []
    client.post(
        "/api/v1/sessions",
        headers=headers,
        json={"name": "claude-one", "directory": "/workspace", "profile": "claude"},
    )
    assert fake.texts == []
    assert fake.keys == []
    client.post(
        "/api/v1/sessions",
        headers=headers,
        json={"name": "antigravity-one", "directory": "/workspace", "profile": "antigravity"},
    )
    # Nessun CLI riceve testo automatico: onboarding e richieste di consenso
    # devono restare integralmente sotto il controllo dell'utente.
    assert fake.texts == []
    assert fake.keys == []


def test_artifact_prompt_is_explicit_and_uses_the_current_pane(tmp_path) -> None:
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        artifacts_root=str(tmp_path),
    )
    fake = FakeTmux()
    client = TestClient(create_app(settings, fake))
    csrf = login(client)
    response = client.post(
        "/api/v1/sessions/1/artifact-prompt",
        headers={"X-CSRF-Token": csrf},
        json={"pane_id": "10"},
    )
    assert response.status_code == 202
    assert len(fake.texts) == 1
    assert "salvalo in:" in fake.texts[0]
    assert fake.keys == ["Enter"]
    assert fake.targets == ["10", "10"]
    assert (tmp_path / "1").is_dir()

    invalid = client.post(
        "/api/v1/sessions/not-an-id/artifact-prompt",
        headers={"X-CSRF-Token": csrf},
        json={},
    )
    assert invalid.status_code == 400
    assert not (tmp_path / "not-an-id").exists()


def test_archive_summary_prompt_targets_the_reserved_file(tmp_path) -> None:
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        artifacts_root=str(tmp_path / "storage"),
        artifacts_prompt_root="/workspace/.agent-artifacts",
    )
    fake = FakeTmux()
    client = TestClient(create_app(settings, fake))
    csrf = login(client)
    response = client.post(
        "/api/v1/sessions/1/archive-summary-prompt",
        headers={"X-CSRF-Token": csrf},
        json={"pane_id": "10"},
    )
    assert response.status_code == 202
    assert "/workspace/.agent-artifacts/1/archive-summary.md" in fake.texts[0]
    assert "senza segreti" in fake.texts[0]
    assert fake.keys == ["Enter"]
    assert fake.targets == ["10", "10"]
    assert (tmp_path / "storage" / "1").is_dir()


def test_terminating_session_cleans_up_its_artifacts(tmp_path) -> None:
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        artifacts_root=str(tmp_path),
    )
    client = TestClient(create_app(settings, FakeTmux()))
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    session_dir = tmp_path / "1"
    session_dir.mkdir(parents=True)
    (session_dir / "report.pdf").write_bytes(b"%PDF-1.4\nhello")

    terminated = client.request(
        "DELETE", "/api/v1/sessions/1", headers=headers, json={"confirmed": True}
    )
    assert terminated.status_code == 204
    assert not session_dir.exists()


def test_attachment_session_quota_is_enforced(tmp_path) -> None:
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        attachments_root=str(tmp_path),
        max_attachment_bytes=1024,
        max_attachment_bytes_per_session=20,
        database_path=migrated_database_with_admin(tmp_path),
        database_auth_enabled=True,
        push_vapid_key_path=str(tmp_path / "vapid.pem"),
    )
    fake = FakeTmux()
    fake.sessions["2"] = type(fake.sessions["1"])(
        "2", "demo-2", False, 1, "bash", datetime.now(UTC)
    )
    client = TestClient(create_app(settings, fake))
    csrf = login_admin(client)
    headers = {"X-CSRF-Token": csrf, "Content-Type": "text/plain"}

    first = client.post(
        "/api/v1/sessions/1/attachments?filename=a.txt",
        content=b"0123456789",
        headers=headers,
    )
    assert first.status_code == 201
    second = client.post(
        "/api/v1/sessions/1/attachments?filename=b.txt",
        content=b"0123456789",
        headers=headers,
    )
    assert second.status_code == 201
    over_quota = client.post(
        "/api/v1/sessions/1/attachments?filename=c.txt",
        content=b"0123456789",
        headers=headers,
    )
    assert over_quota.status_code == 400
    # un'altra sessione ha la propria quota indipendente.
    other_session = client.post(
        "/api/v1/sessions/2/attachments?filename=d.txt",
        content=b"0123456789",
        headers=headers,
    )
    assert other_session.status_code == 201


def test_attachment_validation_rejects_unsafe_names_types_and_sizes(tmp_path) -> None:
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        attachments_root=str(tmp_path),
        max_attachment_bytes=12,
        database_path=migrated_database_with_admin(tmp_path),
        database_auth_enabled=True,
        push_vapid_key_path=str(tmp_path / "vapid.pem"),
    )
    client = TestClient(create_app(settings, FakeTmux()))
    csrf = login_admin(client)
    csrf_header = {"X-CSRF-Token": csrf}

    traversal = client.post(
        "/api/v1/sessions/1/attachments?filename=..%2Fsecret.txt",
        content=b"hello",
        headers={**csrf_header, "Content-Type": "text/plain"},
    )
    assert traversal.status_code == 400
    unsupported = client.post(
        "/api/v1/sessions/1/attachments?filename=script.sh",
        content=b"echo unsafe",
        headers={**csrf_header, "Content-Type": "application/x-sh"},
    )
    assert unsupported.status_code == 400
    too_large = client.post(
        "/api/v1/sessions/1/attachments?filename=large.txt",
        content=b"0123456789abc",
        headers={**csrf_header, "Content-Type": "text/plain"},
    )
    assert too_large.status_code == 400
    missing = client.post(
        "/api/v1/sessions/1/input",
        headers=csrf_header,
        json={"text": "test", "attachment_ids": ["0" * 32]},
    )
    assert missing.status_code == 400


def test_expired_attachments_are_cleaned_up(tmp_path) -> None:
    database = Database(str(tmp_path / "db" / "meta.db"))
    database.migrate("/app/alembic.ini")
    service = AttachmentService(
        database.engine, str(tmp_path), str(tmp_path), max_bytes=1024, max_session_bytes=1024
    )
    attachment = service.create("1", "notes.txt", "text/plain", b"temporary")
    session_dir = tmp_path / "1"
    stored_path = session_dir / os.path.basename(attachment.path)
    assert stored_path.exists()

    # created_at è preso al momento della create(): per simulare la scadenza
    # si sposta "now" avanti nel tempo invece di retrodatare un file.
    assert service.cleanup_expired(ttl_seconds=10, now=time.time() + 1000) == 1
    assert not session_dir.exists()
    database.dispose()


def test_push_public_key_requires_database() -> None:
    client, _ = client_and_fake()
    login(client)
    assert client.get("/api/v1/push/public-key").status_code == 503


def test_push_subscribe_and_unsubscribe(tmp_path) -> None:
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        database_path=migrated_database_with_admin(tmp_path),
        database_auth_enabled=True,
        push_vapid_key_path=str(tmp_path / "vapid.pem"),
    )
    client = TestClient(create_app(settings, FakeTmux()))
    csrf = login_admin(client)
    headers = {"X-CSRF-Token": csrf}

    public_key = client.get("/api/v1/push/public-key")
    assert public_key.status_code == 200
    assert len(public_key.json()["public_key"]) > 32

    subscription = {
        "endpoint": "https://fcm.googleapis.com/fcm/send/ep1",
        "keys": {"p256dh": "a-p256dh-key", "auth": "an-auth-key"},
    }
    created = client.post("/api/v1/push/subscriptions", headers=headers, json=subscription)
    assert created.status_code == 204
    # ri-sottoscrivere lo stesso endpoint aggiorna, non duplica.
    again = client.post("/api/v1/push/subscriptions", headers=headers, json=subscription)
    assert again.status_code == 204

    deleted = client.request(
        "DELETE",
        "/api/v1/push/subscriptions",
        headers=headers,
        json={"endpoint": subscription["endpoint"]},
    )
    assert deleted.status_code == 204


def test_push_subscribe_requires_csrf(tmp_path) -> None:
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        database_path=migrated_database_with_admin(tmp_path),
        database_auth_enabled=True,
        push_vapid_key_path=str(tmp_path / "vapid.pem"),
    )
    client = TestClient(create_app(settings, FakeTmux()))
    login_admin(client)
    subscription = {
        "endpoint": "https://fcm.googleapis.com/fcm/send/ep1",
        "keys": {"p256dh": "a-p256dh-key", "auth": "an-auth-key"},
    }
    assert client.post("/api/v1/push/subscriptions", json=subscription).status_code == 403
    assert client.request(
        "DELETE", "/api/v1/push/subscriptions", json={"endpoint": subscription["endpoint"]}
    ).status_code == 403


def test_push_subscribe_rejects_endpoints_outside_known_push_services(tmp_path) -> None:
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        database_path=migrated_database_with_admin(tmp_path),
        database_auth_enabled=True,
        push_vapid_key_path=str(tmp_path / "vapid.pem"),
    )
    client = TestClient(create_app(settings, FakeTmux()))
    csrf = login_admin(client)
    headers = {"X-CSRF-Token": csrf}
    keys = {"p256dh": "a-p256dh-key", "auth": "an-auth-key"}
    # non-https e host arbitrari (potenziale SSRF verso la rete del backend)
    # devono essere rifiutati prima di raggiungere il servizio.
    for endpoint in (
        "http://fcm.googleapis.com/fcm/send/ep1",
        "https://127.0.0.1:9200/_shutdown",
        "https://attacker.example/ep1",
    ):
        response = client.post(
            "/api/v1/push/subscriptions",
            headers=headers,
            json={"endpoint": endpoint, "keys": keys},
        )
        assert response.status_code == 422


def test_push_service_notify_removes_stale_subscriptions(tmp_path, monkeypatch) -> None:
    database = Database(str(tmp_path / "db" / "meta.db"))
    database.migrate("/app/alembic.ini")
    service = PushService(database.engine, str(tmp_path / "vapid.pem"), "admin@localhost")
    service.subscribe("https://push.example/stale", "p256dh", "auth")

    with service._sessions() as session:
        assert session.query(PushSubscription).count() == 1

    class FakeResponse:
        status_code = 410

    def fake_webpush(**kwargs):
        raise WebPushException("gone", response=FakeResponse())

    monkeypatch.setattr("app.services.push_service.webpush", fake_webpush)
    service.notify("Mobile Agent Console", "test", "tag")

    with service._sessions() as session:
        assert session.query(PushSubscription).count() == 0
    database.dispose()


MP4_BYTES = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32
M4A_BYTES = b"\x00\x00\x00\x18ftypM4A " + b"\x00" * 32


def _preview_client(tmp_path):
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        allowed_roots=[str(tmp_path)],
    )
    return TestClient(create_app(settings, FakeTmux()))


def test_session_file_preview_serves_mp4_inline(tmp_path) -> None:
    """Il caso che mandava il browser di directory in 'Binary file, no preview'."""
    video = tmp_path / "clip.mp4"
    video.write_bytes(MP4_BYTES)
    client = _preview_client(tmp_path)
    url = "/api/v1/sessions/1/file/preview"

    assert client.get(url, params={"path": str(video)}).status_code == 401
    login(client)

    response = client.get(url, params={"path": str(video)})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("video/mp4")
    assert response.headers["content-disposition"].startswith("inline")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.content == MP4_BYTES


def test_session_file_preview_serves_m4a_inline(tmp_path) -> None:
    audio = tmp_path / "memo.m4a"
    audio.write_bytes(M4A_BYTES)
    client = _preview_client(tmp_path)
    login(client)

    response = client.get(
        "/api/v1/sessions/1/file/preview", params={"path": str(audio)}
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/mp4")
    assert response.headers["content-disposition"].startswith("inline")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.content == M4A_BYTES


def test_session_file_preview_serves_mp3_inline(tmp_path) -> None:
    audio = tmp_path / "memo.mp3"
    content = b"ID3\x04\x00\x00\x00\x00\x00\x00fake"
    audio.write_bytes(content)
    client = _preview_client(tmp_path)
    login(client)

    response = client.get(
        "/api/v1/sessions/1/file/preview", params={"path": str(audio)}
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/mpeg")
    assert response.headers["content-disposition"].startswith("inline")
    assert response.content == content


def test_session_file_preview_serves_image_inline(tmp_path) -> None:
    image = tmp_path / "photo.png"
    buffer = BytesIO()
    Image.new("RGB", (8, 6), color="green").save(buffer, format="PNG")
    image.write_bytes(buffer.getvalue())
    client = _preview_client(tmp_path)
    login(client)

    response = client.get(
        "/api/v1/sessions/1/file/preview", params={"path": str(image)}
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.headers["content-disposition"].startswith("inline")
    assert response.headers["x-content-type-options"] == "nosniff"
    with Image.open(BytesIO(response.content)) as preview:
        assert preview.size == (8, 6)


def test_session_file_preview_refuses_types_that_could_execute(tmp_path) -> None:
    """Il tipo si deduce dai byte: un .mp4 che contiene HTML non passa comunque.

    Servire html o svg inline dalla stessa origine sarebbe XSS memorizzato, e il
    browser di directory legge da tutta la radice consentita.
    """
    disguised = tmp_path / "payload.mp4"
    disguised.write_bytes(b"<svg onload=alert(1)></svg>")
    notes = tmp_path / "notes.txt"
    notes.write_text("solo testo")
    client = _preview_client(tmp_path)
    login(client)
    url = "/api/v1/sessions/1/file/preview"

    assert client.get(url, params={"path": str(disguised)}).status_code == 400
    assert client.get(url, params={"path": str(notes)}).status_code == 400


def test_session_file_preview_stays_inside_allowed_roots(tmp_path) -> None:
    client = _preview_client(tmp_path)
    login(client)
    url = "/api/v1/sessions/1/file/preview"

    assert client.get(url, params={"path": "/etc/hostname"}).status_code == 400
    assert client.get(url, params={"path": str(tmp_path / "assente.mp4")}).status_code == 404
    assert client.get(url, params={"path": str(tmp_path)}).status_code == 400
