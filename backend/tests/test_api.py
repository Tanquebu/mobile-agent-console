import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import Settings
from app.main import create_app
from tests.fakes import FakeTmux

PASSWORD = "a-secure-test-password"
SECRET = "a-secure-session-secret-value"


def client_and_fake() -> tuple[TestClient, FakeTmux]:
    fake = FakeTmux()
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
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


def test_list_and_capture() -> None:
    client, _ = client_and_fake()
    csrf = login(client)
    assert client.get("/api/v1/auth/session").json()["csrf_token"] == csrf
    listed = client.get("/api/v1/sessions").json()["sessions"][0]
    assert listed["id"] == "1"
    assert listed["name"] == "demo"
    assert client.get("/api/v1/sessions/1/output").json()["content"] == "$ "


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


def test_create_session_requires_allowed_directory() -> None:
    client, _ = client_and_fake()
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    allowed = client.post(
        "/api/v1/sessions", headers=headers, json={"name": "new-session", "directory": "/workspace"}
    )
    assert allowed.status_code == 201
    denied = client.post(
        "/api/v1/sessions", headers=headers, json={"name": "unsafe", "directory": "/etc"}
    )
    assert denied.status_code == 400
