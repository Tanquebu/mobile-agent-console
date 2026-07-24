from datetime import datetime

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


class KeyInput(BaseModel):
    key: str


class Accepted(BaseModel):
    accepted: bool = True


class LoginInput(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


class LoginResult(BaseModel):
    csrf_token: str


class CreateSessionInput(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    directory: str = Field(min_length=1, max_length=4096)
    profile: str = Field(default="shell", pattern=r"^shell$")
