from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ConfigView(BaseModel):
    allowed_roots: list[str]
    workspace_presets: dict[str, str]


class SessionView(BaseModel):
    id: str
    name: str
    attached: bool
    windows: int
    current_command: str
    activity_at: datetime


class SessionList(BaseModel):
    sessions: list[SessionView]


class OutputView(BaseModel):
    session_id: str
    content: str
    captured_at: datetime


class TextInput(BaseModel):
    text: str = Field(max_length=65536)
    attachment_ids: list[str] = Field(default_factory=list, max_length=5)


class AttachmentView(BaseModel):
    id: str
    name: str
    media_type: str
    size: int
    path: str


class DirectoryEntryView(BaseModel):
    name: str
    type: Literal["file", "dir", "other"]
    size: int | None = None
    created_at: datetime | None = None


class DirectoryView(BaseModel):
    session_id: str
    path: str
    root: str
    parent: str | None = None
    entries: list[DirectoryEntryView]
    truncated: bool = False


class FileView(BaseModel):
    session_id: str
    path: str
    size: int
    content: str
    truncated: bool = False


class KeyInput(BaseModel):
    key: str
    confirmed: bool = False


class ConfirmedAction(BaseModel):
    confirmed: bool = False


class RenameSessionInput(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z0-9_-]+(?: [A-Za-z0-9_-]+)*$", max_length=64)


class Accepted(BaseModel):
    accepted: bool = True


class LoginInput(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


class LoginResult(BaseModel):
    csrf_token: str


class CreateSessionInput(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z0-9_-]+(?: [A-Za-z0-9_-]+)*$", max_length=64)
    directory: str = Field(min_length=1, max_length=4096)
    profile: str = Field(default="shell", pattern=r"^shell$")
