import os

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import Settings
from app.main import create_app
from app.services.attachment_service import AttachmentService
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


def test_special_keys_interrupt_and_termination_require_confirmation() -> None:
    client, fake = client_and_fake()
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}

    for key in ("Up", "Down", "Escape"):
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
    assert fake.keys == ["Up", "Down", "Escape", "C-c"]

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
    spaced = client.post(
        "/api/v1/sessions",
        headers=headers,
        json={"name": "Refactoring Codex", "directory": "/workspace"},
    )
    assert spaced.status_code == 201
    denied = client.post(
        "/api/v1/sessions", headers=headers, json={"name": "unsafe", "directory": "/etc"}
    )
    assert denied.status_code == 400


def test_session_directory_lists_entries(tmp_path) -> None:
    (tmp_path / "notes.txt").write_text("hello")
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


def test_expired_attachments_are_cleaned_up(tmp_path) -> None:
    service = AttachmentService(str(tmp_path), str(tmp_path), max_bytes=1024)
    attachment = service.create("1", "notes.txt", "text/plain", b"temporary")
    session_dir = tmp_path / "1"
    stored_path = session_dir / os.path.basename(attachment.path)
    metadata_path = session_dir / f"{attachment.id}.json"
    os.utime(stored_path, (100, 100))
    os.utime(metadata_path, (100, 100))

    assert service.cleanup_expired(ttl_seconds=10, now=111) == 2
    assert not session_dir.exists()
