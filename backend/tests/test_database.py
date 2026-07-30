from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.config import Settings
from app.database import Database
from app.main import create_app
from app.services.user_service import UserService
from tests.fakes import FakeTmux


def test_database_migrates_to_head_and_is_reentrant(tmp_path: Path) -> None:
    database_path = tmp_path / "private" / "app.db"
    database = Database(str(database_path))
    database.migrate("/app/alembic.ini")
    database.migrate("/app/alembic.ini")
    database.check()

    assert database_path.is_file()
    assert database_path.stat().st_mode & 0o777 == 0o600
    assert database_path.parent.stat().st_mode & 0o777 == 0o700
    tables = set(inspect(database.engine).get_table_names())
    assert tables == {
        "alembic_version",
        "app_metadata",
        "archived_sessions",
        "attachments",
        "audit_events",
        "hidden_sessions",
        "push_subscriptions",
        "users",
    }
    database.dispose()


def test_database_auth_bootstrap_and_login(tmp_path: Path) -> None:
    database_path = tmp_path / "auth" / "app.db"
    database = Database(str(database_path))
    database.migrate("/app/alembic.ini")
    users = UserService(database.engine)
    assert users.bootstrap_admin("admin", "a-secure-bootstrap-password")
    assert not users.bootstrap_admin("other", "another-secure-password")
    assert users.authenticate("admin", "wrong") is None
    assert users.authenticate("missing", "a-secure-bootstrap-password") is None
    assert users.authenticate("admin", "a-secure-bootstrap-password") is not None
    database.dispose()

    settings = Settings(
        login_password="legacy-password-not-used",
        session_secret="test-session-secret-at-least-16",
        cookie_secure=False,
        cors_origins=["http://testserver"],
        database_path=str(database_path),
        database_auth_enabled=True,
        backups_root=str(tmp_path / "backups"),
        snapshots_root=str(tmp_path / "snapshots"),
        push_vapid_key_path=str(tmp_path / "vapid.pem"),
    )
    fake = FakeTmux()
    client = TestClient(create_app(settings, fake))
    logged_in = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "a-secure-bootstrap-password"},
    )
    assert logged_in.status_code == 200
    assert logged_in.json()["role"] == "admin"
    csrf = logged_in.json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf}
    assert client.get("/api/v1/backups").json() == {"backups": []}
    created_backup = client.post("/api/v1/backups", headers=headers)
    assert created_backup.status_code == 201
    backup = created_backup.json()
    assert len(backup["sha256"]) == 64
    assert backup["files"] == 1
    assert client.get("/api/v1/backups").json()["backups"][0]["id"] == backup["id"]
    downloaded = client.get(f"/api/v1/backups/{backup['id']}/download")
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"] == "application/zip"
    for username, role in (("operator", "operator"), ("viewer", "viewer")):
        created = client.post(
            "/api/v1/users",
            headers=headers,
            json={
                "username": username,
                "password": f"a-secure-{username}-password",
                "role": role,
            },
        )
        assert created.status_code == 201
    assert len(client.get("/api/v1/users").json()["users"]) == 3

    viewer = TestClient(create_app(settings, FakeTmux()))
    viewer_login = viewer.post(
        "/api/v1/auth/login",
        json={"username": "viewer", "password": "a-secure-viewer-password"},
    )
    viewer_headers = {"X-CSRF-Token": viewer_login.json()["csrf_token"]}
    assert viewer.get("/api/v1/sessions").status_code == 200
    assert viewer.get("/api/v1/users").status_code == 403
    assert viewer.get("/api/v1/backups").status_code == 403
    assert viewer.post(
        "/api/v1/sessions/1/keys", headers=viewer_headers, json={"key": "Enter"}
    ).status_code == 403

    operator = TestClient(create_app(settings, FakeTmux()))
    operator_login = operator.post(
        "/api/v1/auth/login",
        json={"username": "operator", "password": "a-secure-operator-password"},
    )
    operator_headers = {"X-CSRF-Token": operator_login.json()["csrf_token"]}
    assert operator.post(
        "/api/v1/sessions/1/keys", headers=operator_headers, json={"key": "Enter"}
    ).status_code == 202
    assert operator.get("/api/v1/users").status_code == 403
    assert operator.post("/api/v1/backups", headers=operator_headers).status_code == 403
    assert client.request(
        "DELETE",
        f"/api/v1/backups/{backup['id']}",
        headers=headers,
        json={"confirmed": True},
    ).status_code == 204
    assert client.get("/api/v1/backups").json() == {"backups": []}

    archived = client.post(
        "/api/v1/sessions/1/archive",
        headers=headers,
        json={"confirmed": True},
    )
    assert archived.status_code == 201
    archive = archived.json()
    assert archive["name"] == "demo"
    assert archive["profile"] == "shell"
    assert archive["archived_by"] == "admin"
    assert "1" not in fake.sessions
    assert client.get("/api/v1/archives").json()["archives"][0]["id"] == archive["id"]
    assert viewer.get("/api/v1/archives").status_code == 200
    restored = client.post(
        f"/api/v1/archives/{archive['id']}/restore",
        headers=headers,
        json={"confirmed": True},
    )
    assert restored.status_code == 201
    assert fake.created[-1] == ("demo", "/workspace", "shell", True)
    assert client.get("/api/v1/archives").json() == {"archives": []}

    visible_session_id = next(iter(fake.sessions))
    hidden = client.post(
        f"/api/v1/sessions/{visible_session_id}/visibility", headers=headers, json={"hidden": True}
    )
    assert hidden.status_code == 200
    assert client.get("/api/v1/sessions").json()["sessions"][0]["hidden"] is True
    assert viewer.post(
        f"/api/v1/sessions/{visible_session_id}/visibility", headers=viewer_headers, json={"hidden": False}
    ).status_code == 403
    restored_visibility = client.post(
        f"/api/v1/sessions/{visible_session_id}/visibility", headers=headers, json={"hidden": False}
    )
    assert restored_visibility.status_code == 200
    assert client.get("/api/v1/sessions").json()["sessions"][0]["hidden"] is False
    assert any(item.name == "demo" for item in fake.sessions.values())

    live_id = next(item.id for item in fake.sessions.values() if item.name == "demo")
    archived_again = client.post(
        f"/api/v1/sessions/{live_id}/archive",
        headers=headers,
        json={"confirmed": True},
    ).json()
    assert client.request(
        "DELETE",
        f"/api/v1/archives/{archived_again['id']}",
        headers=headers,
        json={"confirmed": True},
    ).status_code == 204
    assert client.get("/api/v1/archives").json() == {"archives": []}

    assert client.post(
        "/api/v1/users/viewer/status",
        headers=headers,
        json={"active": False},
    ).status_code == 200
    assert viewer.get("/api/v1/sessions").status_code == 401
    assert client.post(
        "/api/v1/users/admin/status",
        headers=headers,
        json={"active": False},
    ).status_code == 409
    assert client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "legacy-password-not-used"},
    ).status_code == 401
    assert viewer.get("/api/v1/audit").status_code in {401, 403}
    audit_response = client.get("/api/v1/audit")
    assert audit_response.status_code == 200
    events = audit_response.json()["events"]
    assert any(
        event["actor"] == "admin"
        and event["action"] == "POST /api/v1/sessions/{session_id}/archive"
        and event["outcome"] == 201
        for event in events
    )
    assert any(
        event["actor"] == "admin"
        and event["action"] == "LOGIN"
        and event["outcome"] == 401
        for event in events
    )
    assert all("password" not in str(event).lower() for event in events)
