from pathlib import Path

from pydantic import BaseModel, Field


class ProviderWindow(BaseModel):
    label: str = Field(max_length=32)
    used_percent: float | None = Field(default=None, ge=0, le=100)
    resets_at: int | None = Field(default=None, ge=0)
    detail: str | None = Field(default=None, max_length=300)


class ProviderRateLimit(BaseModel):
    provider: str = Field(max_length=32)
    available: bool
    observed_at: str | None = Field(default=None, max_length=64)
    windows: list[ProviderWindow] = Field(max_length=10)
    reached_type: str | None = Field(default=None, max_length=100)
    error: str | None = Field(default=None, max_length=500)


class RateLimitStatus(BaseModel):
    collected_at: str = Field(max_length=64)
    providers: list[ProviderRateLimit] = Field(max_length=10)


class RateLimitStatusService:
    def __init__(self, path: str) -> None:
        self.path = Path(path).resolve()

    def read(self) -> RateLimitStatus | None:
        if not self.path.is_file():
            return None
        try:
            return RateLimitStatus.model_validate_json(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
