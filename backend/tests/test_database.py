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
    assert tables == {"alembic_version", "app_metadata", "users"}
    database.dispose()


def test_database_auth_bootstrap_and_login(tmp_path: Path) -> None:
    database_path = tmp_path / "auth" / "app.db"
    database = Database(str(database_path))
    database.migrate("/app/alembic.ini")
    users = UserService(database.engine)
    assert users.bootstrap_admin("operator", "a-secure-bootstrap-password")
    assert not users.bootstrap_admin("other", "another-secure-password")
    assert users.authenticate("operator", "wrong") is None
    assert users.authenticate("missing", "a-secure-bootstrap-password") is None
    assert users.authenticate("operator", "a-secure-bootstrap-password") is not None
    database.dispose()

    settings = Settings(
        login_password="legacy-password-not-used",
        session_secret="test-session-secret-at-least-16",
        cookie_secure=False,
        cors_origins=["http://testserver"],
        database_path=str(database_path),
        database_auth_enabled=True,
    )
    client = TestClient(create_app(settings, FakeTmux()))
    assert client.post(
        "/api/v1/auth/login",
        json={"username": "operator", "password": "a-secure-bootstrap-password"},
    ).status_code == 200
    assert client.post(
        "/api/v1/auth/login",
        json={"username": "operator", "password": "legacy-password-not-used"},
    ).status_code == 401
