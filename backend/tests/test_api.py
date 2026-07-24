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
    )
    client = TestClient(create_app(settings, fake))
    csrf = login(client)
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


def test_attachment_validation_rejects_unsafe_names_types_and_sizes(tmp_path) -> None:
    settings = Settings(
        login_password=PASSWORD,
        session_secret=SECRET,
        cookie_secure=False,
        cors_origins=["http://testserver"],
        attachments_root=str(tmp_path),
        max_attachment_bytes=12,
    )
    client = TestClient(create_app(settings, FakeTmux()))
    csrf = login(client)
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
