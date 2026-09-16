import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.markdown_service import MAX_MARKDOWN_BYTES, markdown_file
from tests.fakes import FakeTmux


@pytest.fixture
def editing(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    settings = Settings(
        login_password="test-password-at-least-16",
        session_secret="test-session-secret-at-least-16",
        cookie_secure=False,
        allowed_roots=[str(root)],
        preview_roots=[str(tmp_path / "external")],
    )
    client = TestClient(create_app(settings, FakeTmux()))
    response = client.post("/api/v1/auth/login", json={"password": settings.login_password})
    headers = {"X-CSRF-Token": response.json()["csrf_token"]}
    return client, root, headers


URL = "/api/v1/sessions/1/file/markdown"


def test_roundtrip_empty_unicode_and_conflict(editing):
    client, root, headers = editing
    path = root / "notes.md"
    path.write_bytes("# Caffè\r\n".encode())
    path.chmod(0o640)
    opened = client.get(URL, params={"path": str(path)}).json()
    assert opened["content"] == "# Caffè\r\n"
    response = client.post(URL, headers=headers, json={**opened, "content": "# Novità 🌱\n"})
    assert response.status_code == 200
    assert path.read_text() == "# Novità 🌱\n"
    assert path.stat().st_mode & 0o777 == 0o640
    assert client.post(URL, headers=headers, json=opened).status_code == 409
    current = response.json()
    path.write_text("agent update")
    assert client.post(URL, headers=headers, json=current).status_code == 409
    assert path.read_text() == "agent update"
    opened = client.get(URL, params={"path": str(path)}).json()
    assert client.post(URL, headers=headers, json={**opened, "content": ""}).status_code == 200
    assert path.read_bytes() == b""
    assert not list(root.glob(".mac-markdown-*"))


def test_auth_csrf_and_path_boundaries(editing):
    client, root, headers = editing
    path = root / "notes.md"
    path.write_text("original")
    opened = client.get(URL, params={"path": str(path)}).json()
    assert client.post(URL, json=opened).status_code == 403
    outside = root.parent / "outside.md"
    outside.write_text("outside")
    (root / "escape.md").symlink_to(outside)
    for target in (outside, root / "escape.md", root / ".." / "outside.md"):
        assert client.get(URL, params={"path": str(target)}).status_code == 400
        assert client.post(URL, headers=headers, json={**opened, "path": str(target)}).status_code == 400
    assert outside.read_text() == "outside"
    assert client.get(URL.replace("/1/", "/bad/"), params={"path": str(path)}).status_code == 400
    client.cookies.clear()
    assert client.get(URL, params={"path": str(path)}).status_code == 401
    assert client.post(URL, headers=headers, json=opened).status_code == 401


@pytest.mark.parametrize("name,raw,status", [
    ("script.py", b"text", 400),
    ("binary.md", b"a\0b", 400),
    ("encoding.md", b"\xff", 400),
    ("large.md", b"x" * (MAX_MARKDOWN_BYTES + 1), 413),
])
def test_invalid_files(editing, name, raw, status):
    client, root, headers = editing
    path = root / name
    path.write_bytes(raw)
    assert client.get(URL, params={"path": str(path)}).status_code == status
    assert client.post(URL, headers=headers, json={
        "path": str(path), "content": "replace", "revision": "0" * 64,
    }).status_code == status
    assert path.read_bytes() == raw


def test_limits_missing_files_and_links(editing):
    client, root, headers = editing
    path = root / "notes.MARKDOWN"
    path.write_text("original")
    opened = client.get(URL, params={"path": str(path)}).json()
    for content in ("🌱" * 70000, "bad\0text"):
        assert client.post(URL, headers=headers, json={**opened, "content": content}).status_code == 400
    path.unlink()
    assert client.post(URL, headers=headers, json=opened).status_code == 404
    path.mkdir()
    assert client.get(URL, params={"path": str(path)}).status_code == 400
    other = root / "hard.md"
    other.write_text("original")
    os.link(other, root / "alias.md")
    assert client.get(URL, params={"path": str(other)}).status_code == 400
    os.mkfifo(root / "fifo.md")
    assert client.get(URL, params={"path": str(root / "fifo.md")}).status_code == 400


def test_two_simultaneous_saves_only_one_wins(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("original")
    revision = markdown_file(path)["revision"]

    def save(content):
        try:
            markdown_file(path, content, revision)
            return 200
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(save, ["one", "two"])) == [200, 409]
    assert path.read_text() in {"one", "two"}


def test_symlink_directory_swap_fails_closed(tmp_path):
    from app.services import markdown_service

    directory = tmp_path / "allowed"
    directory.mkdir()
    (directory / "notes.md").write_text("safe")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "notes.md").write_text("private")
    directory.rename(tmp_path / "old")
    directory.symlink_to(outside)
    with pytest.raises(HTTPException):
        markdown_service.markdown_file(directory / "notes.md")
    assert (outside / "notes.md").read_text() == "private"



@pytest.mark.parametrize("role,expected", [("viewer", 403), ("operator", 200), ("admin", 200)])
def test_roles_and_audit_exclude_content(tmp_path, role, expected):
    from app.database import Database
    from app.services.user_service import UserService

    database_path = tmp_path / "app.db"
    database = Database(str(database_path))
    database.migrate("/app/alembic.ini")
    users = UserService(database.engine)
    users.bootstrap_admin("admin", "test-password-at-least-16")
    if role != "admin":
        users.create(role, "test-password-at-least-16", role)
    database.dispose()
    settings = Settings(
        login_password="test-password-at-least-16",
        session_secret="test-session-secret-at-least-16",
        cookie_secure=False,
        allowed_roots=[str(tmp_path)],
        database_path=str(database_path),
        database_auth_enabled=True,
        push_vapid_key_path=str(tmp_path / "vapid.pem"),
    )
    client = TestClient(create_app(settings, FakeTmux()))
    token = client.post("/api/v1/auth/login", json={
        "username": role, "password": "test-password-at-least-16",
    }).json()["csrf_token"]
    path = tmp_path / "secret-name.md"
    path.write_text("secret content")
    opened = client.get(URL, params={"path": str(path)}).json()
    response = client.post(URL, json={**opened, "content": "changed"}, headers={"X-CSRF-Token": token})
    assert response.status_code == expected
    assert path.read_text() == ("changed" if expected == 200 else "secret content")
    client.post("/api/v1/auth/login", json={
        "username": "admin", "password": "test-password-at-least-16",
    })
    audit = client.get("/api/v1/audit").text
    assert "file/markdown" in audit
    assert "secret-name" not in audit
    assert "secret content" not in audit
