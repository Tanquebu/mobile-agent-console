import json
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _validate_absolute_socket_path(value: str, label: str) -> str:
    if "\x00" in value:
        raise ValueError(f"{label} must be an absolute path")
    path = Path(value)
    if (
        not path.is_absolute()
        or str(path) != value
        or any(part in {".", ".."} for part in value.split("/"))
    ):
        raise ValueError(f"{label} must be an absolute path")
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MAC_", extra="ignore", enable_decoding=False
    )

    host: str = "127.0.0.1"
    port: int = Field(default=8080, ge=1, le=65535)
    login_password: str | None = None
    login_password_file: str | None = None
    session_secret: str | None = None
    session_secret_file: str | None = None
    cookie_secure: bool = True
    session_ttl_seconds: int = Field(default=43200, ge=300, le=604800)
    tmux_socket: str = Field(default="mobile-agent-console", pattern=r"^[A-Za-z0-9_-]{1,64}$")
    tmux_socket_path: str | None = None
    tmux_socket_file: str | None = None
    tmux_mode: str = Field(default="docker", pattern=r"^(docker|host)$")
    host_observability_enabled: bool = False
    host_observability_socket_file: str = (
        "/host-observability/host-observability.sock"
    )
    host_observability_socket_timeout_seconds: float = Field(
        default=3.0, ge=0.1, le=10.0
    )
    host_observability_max_response_bytes: int = Field(
        default=128 * 1024, ge=1024, le=128 * 1024
    )
    host_observability_rate_limit: int = Field(default=6, ge=1, le=1000)
    host_observability_rate_window_seconds: int = Field(default=60, ge=1, le=3600)
    allowed_roots: list[str] = ["/workspace"]
    cors_origins: list[str] = ["http://localhost:5173"]
    workspace_presets: dict[str, str] = {}
    attachments_root: str = "/workspace/.agent-attachments"
    artifacts_root: str = "/workspace/.agent-artifacts"
    snapshots_root: str = "/workspace/.agent-snapshots"
    backups_root: str = "/workspace/.mobile-agent-console/backups"
    backup_retention: int = Field(default=10, ge=1, le=100)
    provider_rate_limits_path: str = (
        "/workspace/.mobile-agent-console/provider-rate-limits.json"
    )
    provider_rate_limits_history_path: str = (
        "/workspace/.mobile-agent-console/provider-rate-limits-history.jsonl"
    )
    rate_limit_history_max_hours: int = Field(default=168, ge=1, le=336)
    session_usage_enabled: bool = False
    session_usage_path: str = (
        "/workspace/.mobile-agent-console/session-usage-history.jsonl"
    )
    session_usage_max_hours: int = Field(default=168, ge=1, le=336)
    session_usage_max_limit: int = Field(default=500, ge=1, le=5000)
    rate_limit_fresh_enabled: bool = False
    rate_limit_fresh_socket_file: str = "/rate-limit-fresh/rate-limit-fresh.sock"
    # Il campione fresh interroga un provider per volta con una curl da 20s
    # ciascuna: il tetto deve restare sopra il caso peggiore dei due script,
    # coerente con RuntimeMaxSec=90 della unit socket-activated.
    rate_limit_fresh_timeout_seconds: float = Field(default=60.0, ge=0.1, le=120.0)
    rate_limit_fresh_max_response_bytes: int = Field(
        default=128 * 1024, ge=1024, le=512 * 1024
    )
    rate_limit_fresh_rate_limit: int = Field(default=4, ge=1, le=1000)
    rate_limit_fresh_rate_window_seconds: int = Field(default=300, ge=1, le=3600)
    provider_session_states_path: str = (
        "/workspace/.mobile-agent-console/provider-session-states.json"
    )
    orchestrator_state_path: str = (
        "/workspace/.mobile-agent-console/orchestrator-state.json"
    )
    claude_history_enabled: bool = False
    claude_history_path: str = (
        "/workspace/.mobile-agent-console/claude-history.json"
    )
    claude_history_max_age_seconds: int = Field(default=30, ge=5, le=3600)
    database_path: str = "/workspace/.mobile-agent-console/app.db"
    database_auth_enabled: bool = False
    bootstrap_username: str = Field(default="admin", pattern=r"^[A-Za-z0-9_-]{1,64}$")
    attachments_prompt_root: str | None = None
    max_attachment_bytes: int = Field(default=10 * 1024 * 1024, ge=1, le=100 * 1024 * 1024)
    max_attachment_bytes_per_session: int = Field(
        default=100 * 1024 * 1024, ge=1, le=1000 * 1024 * 1024
    )
    attachment_ttl_seconds: int = Field(default=86400, ge=300, le=30 * 86400)
    artifacts_prompt_root: str | None = None
    max_artifact_bytes: int = Field(default=25 * 1024 * 1024, ge=1, le=100 * 1024 * 1024)
    login_rate_limit: int = Field(default=5, ge=1, le=1000)
    login_rate_window_seconds: int = Field(default=60, ge=1, le=3600)
    mutation_rate_limit: int = Field(default=120, ge=1, le=10000)
    mutation_rate_window_seconds: int = Field(default=60, ge=1, le=3600)
    agent_active_window_seconds: int = Field(default=8, ge=2, le=120)
    push_vapid_key_path: str = "/workspace/.mobile-agent-console/vapid_private_key.pem"
    push_contact_email: str = "admin@localhost"
    push_poll_interval_seconds: int = Field(default=5, ge=2, le=60)

    @model_validator(mode="after")
    def require_explicit_host_socket(self) -> "Settings":
        # La modalità host è opt-in esplicito: mai un socket di default silenzioso.
        if self.tmux_mode == "host" and not self.tmux_socket_file:
            raise ValueError("host mode requires an explicit MAC_TMUX_SOCKET_FILE")
        return self

    @field_validator("allowed_roots", "cors_origins", mode="before")
    @classmethod
    def split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            if value.lstrip().startswith("["):
                return json.loads(value)
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("workspace_presets", mode="before")
    @classmethod
    def parse_presets(cls, value: object) -> object:
        # Accetta un oggetto JSON oppure una stringa "label=path,label=path".
        if isinstance(value, str):
            if not value.strip():
                return {}
            if value.lstrip().startswith("{"):
                return json.loads(value)
            presets: dict[str, str] = {}
            for pair in (item.strip() for item in value.split(",") if item.strip()):
                label, sep, path = pair.partition("=")
                if not sep or not label.strip() or not path.strip():
                    raise ValueError(f"Invalid workspace preset '{pair}' (expected label=path)")
                presets[label.strip()] = path.strip()
            return presets
        return value

    @field_validator("host_observability_socket_file")
    @classmethod
    def validate_host_observability_socket_file(cls, value: str) -> str:
        return _validate_absolute_socket_path(value, "host observability socket file")

    @field_validator("rate_limit_fresh_socket_file")
    @classmethod
    def validate_rate_limit_fresh_socket_file(cls, value: str) -> str:
        return _validate_absolute_socket_path(value, "rate limit fresh socket file")

    def read_secret(self, direct: str | None, file_path: str | None, label: str) -> str:
        value = Path(file_path).read_text().strip() if file_path else direct
        if not value or len(value) < 16:
            raise ValueError(f"{label} must contain at least 16 characters")
        return value

    @property
    def resolved_login_password(self) -> str:
        return self.read_secret(self.login_password, self.login_password_file, "login password")

    @property
    def resolved_session_secret(self) -> str:
        return self.read_secret(self.session_secret, self.session_secret_file, "session secret")

    @property
    def resolved_attachments_prompt_root(self) -> str:
        return self.attachments_prompt_root or self.attachments_root

    @property
    def resolved_artifacts_prompt_root(self) -> str:
        return self.artifacts_prompt_root or self.artifacts_root

    @property
    def database_url(self) -> str:
        return f"sqlite:///{Path(self.database_path).resolve()}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
