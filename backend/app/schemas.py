from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator


class ConfigView(BaseModel):
    allowed_roots: list[str]
    workspace_presets: dict[str, str]
    claude_history_enabled: bool = False


class SessionView(BaseModel):
    id: str
    name: str
    attached: bool
    windows: int
    current_command: str
    activity_at: datetime


class SessionList(BaseModel):
    sessions: list[SessionView]


class AgentStatusView(BaseModel):
    session_id: str
    provider: Literal["codex", "claude"]
    state: Literal[
        "active",
        "idle",
        "waiting_input",
        "waiting_authorization",
        "unknown",
    ]
    detail: str
    permission_state: Literal[
        "restricted",
        "standard",
        "elevated",
        "bypass",
        "plan",
        "ask",
        "auto",
        "manual",
        "accept_edits",
        "dont_ask",
        "unknown",
    ]
    permission_detail: str
    context_used_percent: float | None = Field(default=None, ge=0, le=100)
    summary: str | None = None


class AgentStatusList(BaseModel):
    statuses: list[AgentStatusView]


class ClaudeHistoryMessageView(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    timestamp: datetime
    kind: Literal["message", "activity"] = "message"
    pending: bool = False


class ClaudeHistoryView(BaseModel):
    session_id: str
    collected_at: datetime
    source_updated_at: datetime
    truncated: bool
    messages: list[ClaudeHistoryMessageView]


class PaneView(BaseModel):
    id: str
    window_index: int
    pane_index: int
    active: bool
    command: str
    title: str
    width: int
    height: int


class PaneList(BaseModel):
    panes: list[PaneView]


class OutputView(BaseModel):
    session_id: str
    content: str
    captured_at: datetime


class TextInput(BaseModel):
    text: str = Field(max_length=65536)
    attachment_ids: list[str] = Field(default_factory=list, max_length=5)
    pane_id: str | None = Field(default=None, pattern=r"^\d{1,10}$")


class PaneTargetInput(BaseModel):
    pane_id: str | None = Field(default=None, pattern=r"^\d{1,10}$")


class AttachmentView(BaseModel):
    id: str
    name: str
    media_type: str
    size: int
    path: str


class ArtifactView(BaseModel):
    name: str
    media_type: str
    size: int
    modified_at: datetime


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
    pane_id: str | None = Field(default=None, pattern=r"^\d{1,10}$")


class ResizePaneInput(BaseModel):
    columns: int = Field(ge=20, le=500)
    rows: int = Field(ge=5, le=300)


class ConfirmedAction(BaseModel):
    confirmed: bool = False


class RenameSessionInput(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z0-9_-]+(?: [A-Za-z0-9_-]+)*$", max_length=64)


class SnapshotSelectionInput(BaseModel):
    session_id: str = Field(pattern=r"^\d{1,10}$")
    mode: Literal["shell", "codex", "claude", "antigravity", "manual"]


class CreateSnapshotInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    sessions: list[SnapshotSelectionInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_sessions(self) -> "CreateSnapshotInput":
        ids = [session.session_id for session in self.sessions]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate session ids")
        return self


class SnapshotSessionView(BaseModel):
    name: str
    directory: str
    mode: Literal["shell", "codex", "claude", "antigravity", "manual"]
    observed_command: str


class SnapshotView(BaseModel):
    id: str
    name: str
    created_at: datetime
    sessions: list[SnapshotSessionView]


class SnapshotList(BaseModel):
    snapshots: list[SnapshotView]


class BackupView(BaseModel):
    id: str
    created_at: datetime
    size: int
    sha256: str
    files: int


class BackupList(BaseModel):
    backups: list[BackupView]


class RestoreItemView(BaseModel):
    name: str
    status: Literal["restored", "skipped", "manual", "error"]
    detail: str


class RestoreResult(BaseModel):
    snapshot_id: str
    results: list[RestoreItemView]


class Accepted(BaseModel):
    accepted: bool = True


class ArchivedSessionView(BaseModel):
    id: str
    name: str
    directory: str
    profile: Literal["shell", "codex", "claude", "antigravity"]
    archived_by: str
    archived_at: datetime


class ArchiveList(BaseModel):
    archives: list[ArchivedSessionView]


class AuditEventView(BaseModel):
    id: int
    actor: str
    action: str
    target: str
    outcome: int
    created_at: datetime


class AuditList(BaseModel):
    events: list[AuditEventView]


class LoginInput(BaseModel):
    username: str = Field(default="admin", pattern=r"^[A-Za-z0-9_-]{1,64}$")
    password: str = Field(min_length=1, max_length=1024)


class LoginResult(BaseModel):
    csrf_token: str
    username: str = "legacy"
    role: Literal["admin", "operator", "viewer"] = "admin"


class UserView(BaseModel):
    username: str
    role: Literal["admin", "operator", "viewer"]
    active: bool
    created_at: datetime


class UserList(BaseModel):
    users: list[UserView]


class CreateUserInput(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    password: str = Field(min_length=16, max_length=1024)
    role: Literal["admin", "operator", "viewer"]


class UserStatusInput(BaseModel):
    active: bool


class CreateSessionInput(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z0-9_-]+(?: [A-Za-z0-9_-]+)*$", max_length=64)
    directory: str = Field(min_length=1, max_length=4096)
    profile: Literal["shell", "codex", "claude", "antigravity"] = "shell"


class PushPublicKeyView(BaseModel):
    public_key: str


class PushSubscriptionKeys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=255)
    auth: str = Field(min_length=1, max_length=255)


# Un vero browser PushManager.subscribe() produce endpoint solo su questi
# host: un allowlist chiude l'SSRF (il poller Web Push chiama pywebpush con
# questo valore dalla rete del backend) senza rifiutare alcun uso legittimo.
PUSH_ENDPOINT_ALLOWED_HOSTS = {
    "fcm.googleapis.com",
    "updates.push.services.mozilla.com",
    "web.push.apple.com",
}
PUSH_ENDPOINT_ALLOWED_SUFFIXES = (".notify.windows.com",)


def _validate_push_endpoint_host(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https":
        raise ValueError("endpoint must use https")
    host = parsed.hostname
    if host is None or (
        host not in PUSH_ENDPOINT_ALLOWED_HOSTS
        and not host.endswith(PUSH_ENDPOINT_ALLOWED_SUFFIXES)
    ):
        raise ValueError("endpoint host is not a recognized push service")
    return value


class PushSubscriptionInput(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2048)
    keys: PushSubscriptionKeys

    @field_validator("endpoint")
    @classmethod
    def endpoint_must_be_known_push_service(cls, value: str) -> str:
        return _validate_push_endpoint_host(value)


class PushUnsubscribeInput(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2048)
