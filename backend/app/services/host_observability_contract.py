from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError

HostStatus = Literal["ok", "warning", "critical", "unknown"]
AddressScope = Literal["loopback", "tailscale", "wildcard", "other"]
SafeLabel = Annotated[
    str,
    Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9 _.+\-]{0,63}$"),
]
SafeProcessName = Annotated[
    str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.+?\-]+$")
]
HostReason = Literal[
    "memory_unavailable",
    "memory_available_critical",
    "memory_available_low",
    "swap_used_critical",
    "swap_used_high",
    "load_unavailable",
    "load_critical",
    "load_high",
    "filesystems_not_configured",
    "filesystem_used_critical",
    "filesystem_used_high",
    "filesystem_unavailable",
    "processes_unavailable",
    "processes_partial",
    "process_group_count_critical",
    "process_group_count_high",
    "listeners_unavailable",
    "listeners_partial",
    "wildcard_listener_unexpected",
    "tcp_listener_unexpected",
    "docker_disabled",
    "docker_unavailable",
    "docker_output_excessive",
    "docker_output_invalid",
    "containers_problematic",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Component(StrictModel):
    status: HostStatus
    reasons: list[HostReason] = Field(max_length=8)


class MemoryComponent(Component):
    total_bytes: int | None = Field(default=None, ge=0)
    available_bytes: int | None = Field(default=None, ge=0)
    available_percent: float | None = Field(default=None, ge=0, le=100)
    swap_total_bytes: int | None = Field(default=None, ge=0)
    swap_used_bytes: int | None = Field(default=None, ge=0)
    swap_used_percent: float | None = Field(default=None, ge=0, le=100)


class LoadComponent(Component):
    one: float | None = Field(default=None, ge=0)
    five: float | None = Field(default=None, ge=0)
    fifteen: float | None = Field(default=None, ge=0)
    cpu_count: int | None = Field(default=None, ge=1, le=65536)
    normalized_one: float | None = Field(default=None, ge=0)


class FilesystemItem(Component):
    label: SafeLabel
    total_bytes: int | None = Field(default=None, ge=0)
    available_bytes: int | None = Field(default=None, ge=0)
    used_percent: float | None = Field(default=None, ge=0, le=100)


class FilesystemsComponent(Component):
    items: list[FilesystemItem] = Field(max_length=16)


class ProcessItem(StrictModel):
    pid: int = Field(ge=1, le=2**31 - 1)
    name: SafeProcessName
    label: SafeLabel | None = None
    rss_bytes: int = Field(ge=0)
    age_seconds: int = Field(ge=0)


class ProcessGroup(StrictModel):
    name: SafeProcessName
    label: SafeLabel | None = None
    count: int = Field(ge=1, le=4096)
    rss_bytes: int = Field(ge=0)
    oldest_age_seconds: int = Field(ge=0)


class ProcessesComponent(Component):
    top: list[ProcessItem] = Field(max_length=10)
    groups: list[ProcessGroup] = Field(max_length=20)
    scanned: int = Field(ge=0, le=4096)
    skipped: int = Field(ge=0, le=4096)
    inaccessible: int = Field(ge=0, le=4096)
    truncated: bool


class ListenerItem(StrictModel):
    port: int = Field(ge=1, le=65535)
    address_scope: AddressScope
    process_name: SafeProcessName | None = None
    process_label: SafeLabel | None = None
    expected: bool
    status: Literal["ok", "warning", "critical"]


class ListenersComponent(Component):
    items: list[ListenerItem] = Field(max_length=50)
    truncated: bool


class ContainerProblem(StrictModel):
    label: SafeLabel
    status: Literal["warning", "critical"]
    reason: Literal[
        "container_unhealthy",
        "container_starting",
        "container_paused",
        "container_state_unknown",
    ]


class DockerComponent(Component):
    available: bool
    problematic: list[ContainerProblem] = Field(max_length=50)
    unmapped_problematic_count: int = Field(ge=0, le=1000)


class HostObservabilitySnapshot(StrictModel):
    schema_version: Literal[1]
    collected_at: datetime
    duration_ms: int = Field(ge=0, le=10000)
    status: HostStatus
    reasons: list[HostReason] = Field(max_length=8)
    memory: MemoryComponent
    load: LoadComponent
    filesystems: FilesystemsComponent
    processes: ProcessesComponent
    listeners: ListenersComponent
    docker: DockerComponent

    @field_validator("collected_at", mode="before")
    @classmethod
    def require_utc_timestamp(cls, value: object) -> datetime:
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError as exc:
                raise ValueError("collected_at must be an ISO-8601 timestamp") from exc
        elif isinstance(value, datetime):
            parsed = value
        else:
            raise PydanticCustomError(
                "datetime_type", "collected_at must be a datetime or ISO-8601 string"
            )
        if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
            raise ValueError("collected_at must be timezone-aware UTC")
        return parsed.astimezone(UTC)
