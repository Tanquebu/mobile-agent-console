from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from .jsonl_tail import read_tail_records

MAX_TAIL_BYTES = 1024 * 1024


class HistoryWindow(BaseModel):
    label: str = Field(max_length=32)
    used_percent: float | None = Field(default=None, ge=0, le=100)
    resets_at: int | None = Field(default=None, ge=0)


class RateLimitSample(BaseModel):
    sampled_at: datetime
    provider: str = Field(max_length=32)
    source: str = Field(default="cache", max_length=16)
    observed_at: str | None = Field(default=None, max_length=64)
    stale: bool = False
    # Assente nelle righe scritte prima di BH-03: `None` significa "non noto",
    # non "testuale". Il collector lo pubblica soltanto quando ha davvero
    # tentato un parsing (vedi deploy/rate-limit-collector.py:collect()).
    parse_mode: Literal["structured", "text"] | None = Field(default=None)
    windows: list[HistoryWindow] = Field(default_factory=list, max_length=10)
    error: str | None = Field(default=None, max_length=500)

    @field_validator("sampled_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        if value.utcoffset() != timedelta(0):
            raise ValueError("sampled_at must be UTC")
        return value


class RateLimitHistory(BaseModel):
    samples: list[RateLimitSample]


class RateLimitHistoryService:
    def __init__(self, path: str, max_tail_bytes: int = MAX_TAIL_BYTES) -> None:
        self.path = Path(path).resolve()
        self.max_tail_bytes = max_tail_bytes

    def read(self, hours: int, limit: int) -> RateLimitHistory:
        if not self.path.is_file():
            return RateLimitHistory(samples=[])
        horizon = datetime.now(UTC) - timedelta(hours=hours)
        samples = []
        for record in read_tail_records(self.path, self.max_tail_bytes):
            try:
                sample = RateLimitSample.model_validate(record)
            except ValidationError:
                continue
            if sample.sampled_at >= horizon:
                samples.append(sample)
        return RateLimitHistory(samples=samples[-limit:])
