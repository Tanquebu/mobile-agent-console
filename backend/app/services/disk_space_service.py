from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field


class DiskSpaceFilesystem(BaseModel):
    label: str = Field(min_length=1, max_length=64)
    available: bool
    total_bytes: int | None = Field(default=None, ge=0)
    free_bytes: int | None = Field(default=None, ge=0)
    used_percent: float | None = Field(default=None, ge=0, le=100)
    alert: bool
    reasons: list[str] = Field(default_factory=list, max_length=3)


class DiskSpaceState(BaseModel):
    schema_version: int = Field(ge=1, le=1)
    collected_at: datetime
    min_free_bytes: int = Field(ge=0)
    max_used_percent: float | None = Field(default=None, gt=0, le=100)
    filesystems: list[DiskSpaceFilesystem] = Field(max_length=16)
    # Calcolato dal backend, non letto dal file: un collector fermo (magari
    # proprio perché il disco è pieno) non deve far sparire l'alert.
    stale: bool = False


class DiskSpaceService:
    def __init__(self, path: str, max_age_seconds: int) -> None:
        self.path = Path(path).resolve()
        self.max_age_seconds = max_age_seconds

    def read(self, now: datetime | None = None) -> DiskSpaceState | None:
        if not self.path.is_file():
            return None
        try:
            state = DiskSpaceState.model_validate_json(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        collected_at = state.collected_at
        if collected_at.tzinfo is None:
            collected_at = collected_at.replace(tzinfo=UTC)
        age = ((now or datetime.now(UTC)) - collected_at).total_seconds()
        state.stale = age > self.max_age_seconds
        return state
