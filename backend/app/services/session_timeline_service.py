from datetime import UTC, datetime, timedelta
from enum import Enum

from pydantic import BaseModel, Field, ValidationError, field_validator

from .session_timeline_socket_client import (
    SessionTimelineSocketClient,
    SessionTimelineSocketResponseError,
    SessionTimelineSocketTimeout,
    SessionTimelineSocketUnavailable,
)

BUCKET_MINUTES = 5


class ToolCategory(str, Enum):
    """Tassonomia fissa e interna dei conteggi di strumenti (GATE-BH-04).

    Mai il nome grezzo dello strumento: solo una di queste categorie
    attraversa il boundary (docs/contracts/session-timeline-v1.md).
    """

    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    EXEC = "exec"
    NETWORK = "network"
    TASK_MANAGEMENT = "task_management"
    SUBAGENT_ORCHESTRATION = "subagent_orchestration"
    OTHER = "other"


class SessionTimelineUnavailable(RuntimeError):
    pass


class SessionTimelineTimeout(RuntimeError):
    pass


class SessionTimelineInvalidResponse(RuntimeError):
    pass


class SessionTimelineTurn(BaseModel):
    timestamp: datetime
    model: str = Field(default="", max_length=64)
    input_tokens: int = Field(default=0, ge=0)
    cache_creation_input_tokens: int = Field(default=0, ge=0)
    cache_read_input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class SessionTimelineCompaction(BaseModel):
    timestamp: datetime
    # `None` per entrambi i campi è lo stato "n/d" dichiarato per Codex
    # (il provider non pubblica pre/post token count per la compattazione,
    # verificato su dati reali): mai un valore ricostruito.
    pre_tokens: int | None = Field(default=None, ge=0)
    post_tokens: int | None = Field(default=None, ge=0)


class SessionTimelineSubagentSpawn(BaseModel):
    timestamp: datetime


class SessionTimelineWindow(BaseModel):
    provider: str = Field(max_length=32)
    session_uuid: str = Field(max_length=64)
    bucket_start: datetime
    bucket_end: datetime
    available: bool
    # Fatto dichiarato, non un errore: transcript ruotato/rimosso/non
    # trovato (GATE-BH-04, principio "riferisce, non giudica").
    unavailable_reason: str | None = Field(default=None, max_length=64)
    turns: list[SessionTimelineTurn] = Field(default_factory=list)
    # Aggregato sull'intera finestra, non per turno: il testo del gate
    # qualifica "per turno" solo il delta dei quattro contatori di token,
    # non i conteggi di strumenti.
    tool_counts: dict[str, int] = Field(default_factory=dict)
    compactions: list[SessionTimelineCompaction] = Field(default_factory=list)
    subagent_spawns: list[SessionTimelineSubagentSpawn] = Field(default_factory=list)
    truncated: bool = False

    @field_validator("tool_counts")
    @classmethod
    def known_categories_only(cls, value: dict[str, int]) -> dict[str, int]:
        known = {item.value for item in ToolCategory}
        filtered: dict[str, int] = {}
        for key, count in value.items():
            if key not in known or not isinstance(count, int) or count < 0:
                continue
            filtered[key] = count
        return filtered


class SessionTimelineService:
    def __init__(self, client: SessionTimelineSocketClient) -> None:
        self._client = client

    async def read(
        self, provider: str, session_uuid: str, bucket_start: datetime
    ) -> SessionTimelineWindow:
        if bucket_start.tzinfo is None:
            bucket_start = bucket_start.replace(tzinfo=UTC)
        else:
            bucket_start = bucket_start.astimezone(UTC)
        bucket_end = bucket_start + timedelta(minutes=BUCKET_MINUTES)
        try:
            payload = await self._client.fetch_window(
                provider, session_uuid, bucket_start, bucket_end
            )
        except SessionTimelineSocketTimeout as exc:
            raise SessionTimelineTimeout from exc
        except SessionTimelineSocketUnavailable as exc:
            raise SessionTimelineUnavailable from exc
        except SessionTimelineSocketResponseError as exc:
            raise SessionTimelineInvalidResponse from exc
        body = {
            **payload,
            "provider": provider,
            "session_uuid": session_uuid,
            "bucket_start": bucket_start,
            "bucket_end": bucket_end,
        }
        try:
            return SessionTimelineWindow.model_validate(body)
        except ValidationError as exc:
            raise SessionTimelineInvalidResponse from exc
