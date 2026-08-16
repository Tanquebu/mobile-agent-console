from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.database import Database
from app.main import create_app
from app.services.session_profile_service import SessionProfileService
from app.services.user_service import UserService
from tests.fakes import FakeTmux

PASSWORD = "a-secure-test-password"
SECRET = "a-secure-session-secret-value"
ADMIN_PASSWORD = "a-secure-admin-password-value"
YOLO_NAME = "OpenCode Yolo Agent"


def _profiles_path(tmp_path: Path) -> str:
    # I test non devono scrivere nel /workspace predefinito: il file profili
    # vive sempre sotto tmp_path.
    return str(tmp_path / "session-profiles.json")


def _client_and_fake(tmp_path: Path) -> tuple[TestClient, FakeTmux]:
    fake = FakeTmux()
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        session_profiles_path=_profiles_path(tmp_path),
    )
    return TestClient(create_app(settings, fake)), fake


def _bootstrapped_client(tmp_path: Path) -> tuple[TestClient, FakeTmux, dict[str, str]]:
    settings = Settings(
        login_password="legacy-password-not-used",
        session_secret="test-session-secret-at-least-16",
        cookie_secure=False,
        cors_origins=["http://testserver"],
        database_path=str(tmp_path / "app.db"),
        database_auth_enabled=True,
        backups_root=str(tmp_path / "backups"),
        snapshots_root=str(tmp_path / "snapshots"),
        artifacts_root=str(tmp_path / "artifacts"),
        push_vapid_key_path=str(tmp_path / "vapid.pem"),
        session_profiles_path=_profiles_path(tmp_path),
    )
    fake = FakeTmux()
    client = TestClient(create_app(settings, fake))
    database = Database(settings.database_path)
    database.migrate("/app/alembic.ini")
    users = UserService(database.engine)
    users.bootstrap_admin("admin", ADMIN_PASSWORD)
    database.dispose()
    logged_in = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": ADMIN_PASSWORD},
    )
    assert logged_in.status_code == 200
    headers = {"X-CSRF-Token": logged_in.json()["csrf_token"]}
    return client, fake, headers


def login(client: TestClient) -> str:
    response = client.post("/api/v1/auth/login", json={"password": PASSWORD})
    assert response.status_code == 200
    return response.json()["csrf_token"]


def _create_yolo_session(client: TestClient, headers: dict[str, str]) -> None:
    created = client.post(
        "/api/v1/sessions",
        headers=headers,
        json={"name": YOLO_NAME, "directory": "/workspace", "profile": "opencode_yolo"},
    )
    assert created.status_code == 201


def _yolo_session_id(client: TestClient) -> str:
    sessions = client.get("/api/v1/sessions").json()["sessions"]
    yolo = next(session for session in sessions if session["profile"] == "opencode_yolo")
    return yolo["id"]


def test_created_sessions_record_profile_and_unknown_is_none(tmp_path) -> None:
    client, fake = _client_and_fake(tmp_path)
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}

    _create_yolo_session(client, headers)
    shell = client.post(
        "/api/v1/sessions",
        headers=headers,
        json={"name": "Shell Agent", "directory": "/workspace", "profile": "shell"},
    )
    assert shell.status_code == 201

    # La sessione preesistente nel fake (id "1", mai creata via API) non ha
    # un profilo registrato: `None`, non un valore dedotto.
    by_name = {
        session["name"]: session
        for session in client.get("/api/v1/sessions").json()["sessions"]
    }
    assert by_name["demo"]["profile"] is None
    assert by_name[YOLO_NAME]["profile"] == "opencode_yolo"
    assert by_name["Shell Agent"]["profile"] == "shell"
    assert fake.created == [
        (YOLO_NAME, "/workspace", "opencode_yolo", False),
        ("Shell Agent", "/workspace", "shell", False),
    ]
    # Il profilo sopravvive al riavvio: ricaricato dal file su disco.
    store = SessionProfileService(_profiles_path(tmp_path)).read()
    yolo_id = _yolo_session_id(client)
    assert store == {yolo_id: "opencode_yolo", "3": "shell"}


def test_agent_statuses_force_bypass_for_yolo_session(tmp_path) -> None:
    client, fake = _client_and_fake(tmp_path)
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}

    _create_yolo_session(client, headers)
    # La sessione fake "1" è bash, non un agente: resta fuori dall'elenco.
    fake.content = "opencode ›"
    statuses = client.get("/api/v1/agent-statuses").json()["statuses"]
    status = next(
        status for status in statuses if status["session_id"] == _yolo_session_id(client)
    )
    assert status["provider"] == "opencode"
    assert status["permission_state"] == "bypass"
    assert status["permission_detail"] == "Accesso completo"


def test_terminating_session_removes_persisted_profile(tmp_path) -> None:
    client, fake = _client_and_fake(tmp_path)
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}

    _create_yolo_session(client, headers)
    yolo_id = _yolo_session_id(client)
    store = SessionProfileService(_profiles_path(tmp_path))
    assert yolo_id in store.read()

    terminated = client.request(
        "DELETE", f"/api/v1/sessions/{yolo_id}", headers=headers, json={"confirmed": True}
    )
    assert terminated.status_code == 204
    assert yolo_id not in fake.sessions
    # L'id non è più tra le sessioni vive né nello store persistito.
    remaining = client.get("/api/v1/sessions").json()["sessions"]
    assert all(session["id"] != yolo_id for session in remaining)
    assert store.read() == {}


def test_archive_yolo_session_persists_profile_and_clears_store(tmp_path) -> None:
    client, fake, headers = _bootstrapped_client(tmp_path)
    _create_yolo_session(client, headers)
    yolo_id = _yolo_session_id(client)

    archived = client.post(
        f"/api/v1/sessions/{yolo_id}/archive", headers=headers, json={"confirmed": True}
    )
    assert archived.status_code == 201
    assert archived.json()["profile"] == "opencode_yolo"
    listed = client.get("/api/v1/archives").json()["archives"]
    assert listed[0]["profile"] == "opencode_yolo"
    # La sessione è terminata e il profilo rimosso dallo store.
    assert yolo_id not in fake.sessions
    assert SessionProfileService(_profiles_path(tmp_path)).read() == {}


def test_restore_archive_yolo_session_records_profile(tmp_path) -> None:
    client, fake, headers = _bootstrapped_client(tmp_path)
    _create_yolo_session(client, headers)
    archive = client.post(
        f"/api/v1/sessions/{_yolo_session_id(client)}/archive",
        headers=headers,
        json={"confirmed": True},
    ).json()

    restored = client.post(
        f"/api/v1/archives/{archive['id']}/restore",
        headers=headers,
        json={"confirmed": True},
    )
    assert restored.status_code == 201
    assert fake.created[-1] == (YOLO_NAME, "/workspace", "opencode_yolo", True)

    restored_session = next(
        session
        for session in client.get("/api/v1/sessions").json()["sessions"]
        if session["name"] == YOLO_NAME
    )
    assert restored_session["profile"] == "opencode_yolo"
    store = SessionProfileService(_profiles_path(tmp_path)).read()
    assert store == {restored_session["id"]: "opencode_yolo"}
