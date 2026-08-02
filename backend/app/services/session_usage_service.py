from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, field_validator

from .jsonl_tail import read_tail_records

MAX_TAIL_BYTES = 4 * 1024 * 1024


class SessionUsageRow(BaseModel):
    bucket_start: datetime
    provider: str = Field(max_length=32)
    session_uuid: str = Field(max_length=64)
    tmux_session_id: str | None = Field(default=None, max_length=10)
    origin: str = Field(max_length=16)
    project: str = Field(default="", max_length=128)
    model: str = Field(default="", max_length=64)
    is_subagent: bool = False
    turns: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    cache_creation_input_tokens: int = Field(default=0, ge=0)
    cache_read_input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)

    @field_validator("bucket_start")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=UTC)

    @property
    def ranking_tokens(self) -> int:
        """Chiave di ordinamento della classifica, non una stima di quota.

        Somma i token che il provider produce o scrive ex novo, escludendo le
        riletture di cache. Serve solo a ordinare le sessioni fra loro: la
        percentuale di quota consumata resta non ricostruibile da questi
        contatori (contratto storico budget v1).
        """
        return self.input_tokens + self.cache_creation_input_tokens + self.output_tokens


class SessionUsageTotals(BaseModel):
    turns: int = 0
    input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    output_tokens: int = 0
    ranking_tokens: int = 0

    def add(self, row: SessionUsageRow) -> None:
        self.turns += row.turns
        self.input_tokens += row.input_tokens
        self.cache_creation_input_tokens += row.cache_creation_input_tokens
        self.cache_read_input_tokens += row.cache_read_input_tokens
        self.output_tokens += row.output_tokens
        self.ranking_tokens += row.ranking_tokens


class SessionUsageEntry(BaseModel):
    session_uuid: str
    provider: str
    origin: str
    project: str
    tmux_session_id: str | None = None
    models: list[str] = Field(default_factory=list)
    own: SessionUsageTotals = Field(default_factory=SessionUsageTotals)
    subagents: SessionUsageTotals = Field(default_factory=SessionUsageTotals)
    total: SessionUsageTotals = Field(default_factory=SessionUsageTotals)


class SessionUsageReport(BaseModel):
    since: datetime
    entries: list[SessionUsageEntry]
    buckets: list[SessionUsageRow]


class SessionUsageService:
    def __init__(self, path: str, max_tail_bytes: int = MAX_TAIL_BYTES) -> None:
        self.path = Path(path).resolve()
        self.max_tail_bytes = max_tail_bytes

    def read(self, hours: int, limit: int) -> SessionUsageReport:
        since = datetime.now(UTC) - timedelta(hours=hours)
        rows = self._rows(since)
        entries: dict[str, SessionUsageEntry] = {}
        for row in rows:
            entry = entries.get(row.session_uuid)
            if entry is None:
                entry = SessionUsageEntry(
                    session_uuid=row.session_uuid,
                    provider=row.provider,
                    origin=row.origin,
                    project=row.project,
                    tmux_session_id=row.tmux_session_id,
                )
                entries[row.session_uuid] = entry
            # Una sessione mappata a un pane vivo resta `mac` anche se alcuni
            # bucket sono stati raccolti mentre il pane non esisteva ancora.
            if row.origin == "mac":
                entry.origin = "mac"
                entry.tmux_session_id = row.tmux_session_id or entry.tmux_session_id
            if row.project and not entry.project:
                entry.project = row.project
            if row.model and row.model not in entry.models:
                entry.models.append(row.model)
            (entry.subagents if row.is_subagent else entry.own).add(row)
            entry.total.add(row)
        ranked = sorted(
            entries.values(), key=lambda item: item.total.ranking_tokens, reverse=True
        )
        return SessionUsageReport(since=since, entries=ranked[:limit], buckets=rows)

    def _rows(self, since: datetime) -> list[SessionUsageRow]:
        if not self.path.is_file():
            return []
        rows = []
        for record in read_tail_records(self.path, self.max_tail_bytes):
            try:
                row = SessionUsageRow.model_validate(record)
            except ValidationError:
                continue
            if row.bucket_start >= since:
                rows.append(row)
        return rows
