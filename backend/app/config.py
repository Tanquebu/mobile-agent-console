import json
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    allowed_roots: list[str] = ["/workspace"]
    cors_origins: list[str] = ["http://localhost:5173"]
    workspace_presets: dict[str, str] = {}
    attachments_root: str = "/workspace/.agent-attachments"
    snapshots_root: str = "/workspace/.agent-snapshots"
    backups_root: str = "/workspace/.mobile-agent-console/backups"
    backup_retention: int = Field(default=10, ge=1, le=100)
    provider_rate_limits_path: str = (
        "/workspace/.mobile-agent-console/provider-rate-limits.json"
    )
    provider_session_states_path: str = (
        "/workspace/.mobile-agent-console/provider-session-states.json"
    )
    database_path: str = "/workspace/.mobile-agent-console/app.db"
    database_auth_enabled: bool = False
    bootstrap_username: str = Field(default="admin", pattern=r"^[A-Za-z0-9_-]{1,64}$")
    attachments_prompt_root: str | None = None
    max_attachment_bytes: int = Field(default=10 * 1024 * 1024, ge=1, le=100 * 1024 * 1024)
    attachment_ttl_seconds: int = Field(default=86400, ge=300, le=30 * 86400)
    login_rate_limit: int = Field(default=5, ge=1, le=1000)
    login_rate_window_seconds: int = Field(default=60, ge=1, le=3600)
    mutation_rate_limit: int = Field(default=120, ge=1, le=10000)
    mutation_rate_window_seconds: int = Field(default=60, ge=1, le=3600)
    agent_active_window_seconds: int = Field(default=8, ge=2, le=120)

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
    def database_url(self) -> str:
        return f"sqlite:///{Path(self.database_path).resolve()}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
