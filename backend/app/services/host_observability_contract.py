from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator
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
HostReasonV1 = Literal[
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
HostReasonV2 = Literal[
    "memory_unavailable",
    "memory_available_critical",
    "memory_available_low",
    "swap_used_high",
    "swap_sample_unavailable",
    "swap_activity_high",
    "swap_pressure_critical",
    "load_unavailable",
    "load_critical",
    "load_high",
    "filesystems_not_configured",
    "filesystem_used_critical",
    "filesystem_used_high",
    "filesystem_unavailable",
    "processes_unavailable",
    "processes_partial",
    "process_policy_count_critical",
    "process_policy_count_high",
    "process_policy_rss_critical",
    "process_policy_rss_high",
    "listeners_unavailable",
    "listeners_partial",
    "wildcard_listener_unexpected",
    "tcp_listener_unexpected",
    "docker_disabled",
    "docker_unavailable",
    "docker_state_stale",
    "docker_output_excessive",
    "docker_output_invalid",
    "containers_problematic",
    "essential_container_down",
    "services_unavailable",
    "services_state_stale",
    "services_output_excessive",
    "services_output_invalid",
    "essential_service_down",
    "supervisor_unavailable",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class TimestampedSnapshot(StrictModel):
    collected_at: datetime
    duration_ms: int = Field(ge=0, le=10000)

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


class ComponentV1(StrictModel):
    status: HostStatus
    reasons: list[HostReasonV1] = Field(max_length=8)


class MemoryComponentV1(ComponentV1):
    total_bytes: int | None = Field(default=None, ge=0)
    available_bytes: int | None = Field(default=None, ge=0)
    available_percent: float | None = Field(default=None, ge=0, le=100)
    swap_total_bytes: int | None = Field(default=None, ge=0)
    swap_used_bytes: int | None = Field(default=None, ge=0)
    swap_used_percent: float | None = Field(default=None, ge=0, le=100)


class LoadComponentV1(ComponentV1):
    one: float | None = Field(default=None, ge=0)
    five: float | None = Field(default=None, ge=0)
    fifteen: float | None = Field(default=None, ge=0)
    cpu_count: int | None = Field(default=None, ge=1, le=65536)
    normalized_one: float | None = Field(default=None, ge=0)


class FilesystemItemV1(ComponentV1):
    label: SafeLabel
    total_bytes: int | None = Field(default=None, ge=0)
    available_bytes: int | None = Field(default=None, ge=0)
    used_percent: float | None = Field(default=None, ge=0, le=100)


class FilesystemsComponentV1(ComponentV1):
    items: list[FilesystemItemV1] = Field(max_length=16)


class ProcessItem(StrictModel):
    pid: int = Field(ge=1, le=2**31 - 1)
    name: SafeProcessName
    label: SafeLabel | None = None
    rss_bytes: int = Field(ge=0)
    age_seconds: int = Field(ge=0)


class ProcessGroupV1(StrictModel):
    name: SafeProcessName
    label: SafeLabel | None = None
    count: int = Field(ge=1, le=4096)
    rss_bytes: int = Field(ge=0)
    oldest_age_seconds: int = Field(ge=0)


class ProcessesComponentV1(ComponentV1):
    top: list[ProcessItem] = Field(max_length=10)
    groups: list[ProcessGroupV1] = Field(max_length=20)
    scanned: int = Field(ge=0, le=4096)
    skipped: int = Field(ge=0, le=4096)
    inaccessible: int = Field(ge=0, le=4096)
    truncated: bool


class ListenerItemV1(StrictModel):
    port: int = Field(ge=1, le=65535)
    address_scope: AddressScope
    process_name: SafeProcessName | None = None
    process_label: SafeLabel | None = None
    expected: bool
    status: Literal["ok", "warning", "critical"]


class ListenersComponentV1(ComponentV1):
    items: list[ListenerItemV1] = Field(max_length=50)
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


class DockerComponentV1(ComponentV1):
    available: bool
    problematic: list[ContainerProblem] = Field(max_length=50)
    unmapped_problematic_count: int = Field(ge=0, le=1000)


class HostObservabilitySnapshotV1(TimestampedSnapshot):
    schema_version: Literal[1]
    status: HostStatus
    reasons: list[HostReasonV1] = Field(max_length=8)
    memory: MemoryComponentV1
    load: LoadComponentV1
    filesystems: FilesystemsComponentV1
    processes: ProcessesComponentV1
    listeners: ListenersComponentV1
    docker: DockerComponentV1


class ComponentV2(StrictModel):
    status: HostStatus
    reasons: list[HostReasonV2] = Field(max_length=8)


class SwapIoSample(StrictModel):
    available: bool
    duration_ms: int | None = Field(default=None, ge=1, le=1000)
    pages_in_delta: int | None = Field(default=None, ge=0)
    pages_out_delta: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_complete_available_sample(self) -> "SwapIoSample":
        results = (self.duration_ms, self.pages_in_delta, self.pages_out_delta)
        has_any_result = any(value is not None for value in results)
        has_all_results = all(value is not None for value in results)
        if (self.available and not has_all_results) or (
            not self.available and has_any_result
        ):
            raise ValueError("swap sample availability and result are inconsistent")
        return self


class MemoryComponentV2(ComponentV2):
    total_bytes: int | None = Field(default=None, ge=0)
    available_bytes: int | None = Field(default=None, ge=0)
    available_percent: float | None = Field(default=None, ge=0, le=100)
    swap_total_bytes: int | None = Field(default=None, ge=0)
    swap_used_bytes: int | None = Field(default=None, ge=0)
    swap_used_percent: float | None = Field(default=None, ge=0, le=100)
    swap_io_sample: SwapIoSample


class LoadComponentV2(ComponentV2):
    one: float | None = Field(default=None, ge=0)
    five: float | None = Field(default=None, ge=0)
    fifteen: float | None = Field(default=None, ge=0)
    cpu_count: int | None = Field(default=None, ge=1, le=65536)
    normalized_one: float | None = Field(default=None, ge=0)


class FilesystemItemV2(ComponentV2):
    label: SafeLabel
    total_bytes: int | None = Field(default=None, ge=0)
    available_bytes: int | None = Field(default=None, ge=0)
    used_percent: float | None = Field(default=None, ge=0, le=100)


class FilesystemsComponentV2(ComponentV2):
    items: list[FilesystemItemV2] = Field(max_length=16)


class ProcessItemV2(ProcessItem):
    # Assente negli snapshot prodotti da collector precedenti alla raccolta di
    # VmSwap: `None` significa "non accertato", mai "nessuna swap".
    swap_bytes: int | None = Field(default=None, ge=0)


class ProcessGroupV2(StrictModel):
    name: SafeProcessName
    label: SafeLabel | None = None
    count: int = Field(ge=1, le=4096)
    rss_bytes: int = Field(ge=0)
    swap_bytes: int | None = Field(default=None, ge=0)
    oldest_age_seconds: int = Field(ge=0)
    policy_status: Literal["not_configured", "within_limits", "violated"]


class ProcessesComponentV2(ComponentV2):
    top: list[ProcessItemV2] = Field(max_length=10)
    top_swap: list[ProcessItemV2] = Field(default_factory=list, max_length=10)
    # Somma della swap attribuita ai processi osservati: confrontabile con
    # `memory.swap_used_bytes` per capire quanta swap resta non attribuita.
    swap_attributed_bytes: int | None = Field(default=None, ge=0)
    groups: list[ProcessGroupV2] = Field(max_length=20)
    scanned: int = Field(ge=0, le=4096)
    skipped: int = Field(ge=0, le=4096)
    inaccessible: int = Field(ge=0, le=4096)
    truncated: bool


class ListenerItemV2(StrictModel):
    port: int = Field(ge=1, le=65535)
    bind_scope: AddressScope
    external_reachability: Literal["not_assessed"]
    process_name: SafeProcessName | None = None
    process_label: SafeLabel | None = None
    policy_status: Literal["not_configured", "allowed", "violated"]
    status: Literal["ok", "warning", "critical"]


class ListenersComponentV2(ComponentV2):
    items: list[ListenerItemV2] = Field(max_length=50)
    truncated: bool


class ContainerUsage(StrictModel):
    label: SafeLabel
    # `None` = container fermo o memoria non campionata; mai zero sintetico.
    memory_bytes: int | None = Field(default=None, ge=0)
    # Stato osservato, separato dal giudizio: la severita' la decide `priority`.
    state: Literal[
        "running", "stopped", "restarting", "unhealthy", "starting", "paused", "unknown"
    ] = "unknown"
    # `essential`: fermo, rende l'host critico. `optional`: resta visibile con il
    # suo stato senza concorrere alla severita'.
    priority: Literal["essential", "optional"] = "optional"


class DockerComponentV2(ComponentV2):
    available: bool
    problematic: list[ContainerProblem] = Field(max_length=50)
    unmapped_problematic_count: int = Field(ge=0, le=1000)
    # Solo container con una label configurata: i nomi reali non attraversano
    # il boundary, quelli senza label restano un conteggio.
    containers: list[ContainerUsage] = Field(default_factory=list, max_length=50)
    unmapped_count: int = Field(default=0, ge=0, le=1000)
    # Eta' dell'evidenza Docker: a differenza del resto della fotografia arriva
    # da un file aggiornato a timer, quindi non e' istantanea (ADR 011).
    state_age_seconds: int | None = Field(default=None, ge=0, le=86400)


class ServiceUsage(StrictModel):
    label: SafeLabel
    supervisor: Literal["systemd_system", "systemd_user", "pm2"]
    # `absent`: il supervisore ha risposto e non conosce piu' questo servizio.
    # `unknown`: il supervisore non ha risposto, quindi non e' accertato nulla.
    state: Literal[
        "running", "starting", "stopped", "failed", "restarting", "absent", "unknown"
    ]
    # `essential`: non in esecuzione, rende l'host critico. `optional`: resta
    # visibile con il suo stato senza concorrere alla severita'.
    priority: Literal["essential", "optional"] = "optional"
    # Riavvii cumulativi dichiarati dal supervisore: mostrati, mai giudicati,
    # perche' senza una linea di base una soglia sarebbe arbitraria (ADR 012).
    restarts: int | None = Field(default=None, ge=0, le=2**31 - 1)
    memory_bytes: int | None = Field(default=None, ge=0)


class ServicesComponentV2(ComponentV2):
    available: bool
    items: list[ServiceUsage] = Field(default_factory=list, max_length=50)
    # Solo app pm2 senza policy: gli unit systemd non dichiarati sono decine per
    # costruzione e contarli non direbbe nulla.
    unmapped_count: int = Field(default=0, ge=0, le=1000)
    # Come per Docker l'evidenza arriva da un file aggiornato a timer, quindi
    # non e' istantanea (ADR 012).
    state_age_seconds: int | None = Field(default=None, ge=0, le=86400)


class HostObservabilitySnapshotV2(TimestampedSnapshot):
    schema_version: Literal[2]
    status: HostStatus
    reasons: list[HostReasonV2] = Field(max_length=8)
    memory: MemoryComponentV2
    load: LoadComponentV2
    filesystems: FilesystemsComponentV2
    processes: ProcessesComponentV2
    listeners: ListenersComponentV2
    docker: DockerComponentV2
    # Assente o `null` quando la raccolta dei servizi supervisionati non e'
    # configurata: non e' "nessun servizio giu'", e' una fonte che non esiste.
    services: ServicesComponentV2 | None = None


HostObservabilitySnapshot = Annotated[
    HostObservabilitySnapshotV1 | HostObservabilitySnapshotV2,
    Field(discriminator="schema_version"),
]
HOST_OBSERVABILITY_SNAPSHOT_ADAPTER = TypeAdapter(HostObservabilitySnapshot)


def validate_host_observability_snapshot(payload: object) -> HostObservabilitySnapshot:
    return HOST_OBSERVABILITY_SNAPSHOT_ADAPTER.validate_python(payload)
