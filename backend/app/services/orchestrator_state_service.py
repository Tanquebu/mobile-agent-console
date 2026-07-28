from pathlib import Path

from pydantic import BaseModel, Field


class OrchestratorWindow(BaseModel):
    used_percent: float = Field(ge=0, le=100)
    window_minutes: int | None = Field(default=None, ge=0, le=20000)
    resets_at: int | None = Field(default=None, ge=0)


class OrchestratorProvider(BaseModel):
    provider: str = Field(pattern=r"^(claude|codex)$")
    available: bool | None = None
    observed_at: str | None = Field(default=None, max_length=64)
    primary: OrchestratorWindow | None = None
    secondary: OrchestratorWindow | None = None


class OrchestratorPhase(BaseModel):
    index: int = Field(ge=0, le=100)
    total: int = Field(ge=0, le=100)
    name: str = Field(max_length=128)
    interruptible: bool


class OrchestratorTask(BaseModel):
    task_id: str = Field(min_length=1, max_length=64)
    task_kind: str = Field(max_length=128)
    status: str = Field(pattern=r"^(new|draft|in_progress|paused_provider|error|failed)$")
    provider: str = Field(pattern=r"^(claude|codex)$")
    execution_mode: str = Field(pattern=r"^(atomic|phased)$")
    phase: OrchestratorPhase | None = None
    capacity_paused: bool
    next_attempt_at: str | None = Field(default=None, max_length=64)
    fallback_providers: list[str] = Field(default_factory=list, max_length=2)
    checkpoint_present: bool


class OrchestratorState(BaseModel):
    schema_version: int = Field(ge=1, le=1)
    collected_at: str = Field(max_length=64)
    providers: list[OrchestratorProvider] = Field(max_length=2)
    tasks: list[OrchestratorTask] = Field(max_length=100)


class OrchestratorStateService:
    def __init__(self, path: str) -> None:
        self.path = Path(path).resolve()

    def read(self) -> OrchestratorState | None:
        if not self.path.is_file():
            return None
        try:
            return OrchestratorState.model_validate_json(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
