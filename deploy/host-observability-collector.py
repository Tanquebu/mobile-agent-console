#!/usr/bin/env python3
import ipaddress
import json
import os
import re
import selectors
import stat
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path

SUPPORTED_CONFIG_SCHEMA_VERSIONS = {1, 2}
MAX_CONFIG_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 128 * 1024
MAX_FILESYSTEMS = 16
MAX_EXPECTED_LISTENERS = 128
MAX_PROCESS_LABELS = 128
MAX_CONTAINER_LABELS = 50
MAX_PROCESSES_SCANNED = 4096
MAX_FDS_PER_PROCESS = 1024
MAX_TOP_PROCESSES = 10
MAX_PROCESS_GROUPS = 20
MAX_LISTENERS = 50
MAX_LISTENERS_SCANNED = 1000
MAX_DOCKER_OUTPUT_BYTES = 64 * 1024
DOCKER_TIMEOUT_SECONDS = 2
DOCKER_BINARY = "/usr/bin/docker"
SAFE_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.+-]{0,63}$")
SAFE_NAME_CHAR = re.compile(r"[^A-Za-z0-9_.+-]")
SAFE_PROCESS_KEY = re.compile(r"^[A-Za-z0-9_.+?\-]{1,64}$")
SAFE_CONTAINER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
STATUSES = {"ok", "warning", "critical", "unknown"}
SCOPES = {"loopback", "tailscale", "wildcard", "other"}
TAILSCALE_IPV6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")


class CollectorConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Thresholds:
    memory_available_warning_percent: float = 20
    memory_available_critical_percent: float = 10
    swap_used_warning_percent: float = 50
    swap_used_critical_percent: float = 80
    load_per_cpu_warning: float = 1
    load_per_cpu_critical: float = 2
    process_group_warning_count: int = 5
    process_group_critical_count: int = 10


@dataclass(frozen=True)
class FilesystemConfig:
    label: str
    path: Path
    warning_percent: float = 80
    critical_percent: float = 90


@dataclass(frozen=True)
class ListenerExpectation:
    port: int
    scopes: frozenset[str]


@dataclass(frozen=True)
class SwapIoSampleConfig:
    duration_ms: int = 100
    warning_pages_delta: int = 1
    critical_pages_delta: int = 128


@dataclass(frozen=True)
class ProcessPolicy:
    label: str | None = None
    warning_count: int | None = None
    critical_count: int | None = None
    warning_rss_bytes: int | None = None
    critical_rss_bytes: int | None = None


@dataclass(frozen=True)
class DockerConfig:
    enabled: bool = False
    container_labels: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CollectorConfig:
    schema_version: int = 1
    thresholds: Thresholds = Thresholds()
    swap_io_sample: SwapIoSampleConfig = SwapIoSampleConfig()
    filesystems: tuple[FilesystemConfig, ...] = ()
    expected_listeners: tuple[ListenerExpectation, ...] = ()
    process_labels: dict[str, str] = field(default_factory=dict)
    process_policies: dict[str, ProcessPolicy] = field(default_factory=dict)
    docker: DockerConfig = DockerConfig()


@dataclass(frozen=True)
class ProcessSample:
    pid: int
    name: str
    rss_bytes: int
    age_seconds: int


@dataclass(frozen=True)
class DockerCommandResult:
    returncode: int
    stdout: bytes
    excessive: bool = False


DockerRunner = Callable[[], DockerCommandResult]
Statvfs = Callable[[str], os.statvfs_result]
Clock = Callable[[], float]
Sleeper = Callable[[float], None]


def require_mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise CollectorConfigError(f"{label} must be an object")
    return value


def require_keys(value: dict[str, object], allowed: set[str], label: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise CollectorConfigError(f"{label} contains unsupported fields")


def number(value: object, label: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CollectorConfigError(f"{label} must be numeric")
    result = float(value)
    if not minimum <= result <= maximum:
        raise CollectorConfigError(f"{label} is outside the supported range")
    return result


def integer(value: object, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CollectorConfigError(f"{label} must be an integer")
    if not minimum <= value <= maximum:
        raise CollectorConfigError(f"{label} is outside the supported range")
    return value


def safe_label(value: object, label: str) -> str:
    if not isinstance(value, str) or not SAFE_LABEL.fullmatch(value):
        raise CollectorConfigError(f"{label} is invalid")
    return value


def parse_thresholds(value: object, schema_version: int) -> Thresholds:
    if value is None:
        return Thresholds()
    raw = require_mapping(value, "thresholds")
    fields = set(Thresholds.__dataclass_fields__)
    if schema_version == 2:
        fields -= {
            "swap_used_critical_percent",
            "process_group_warning_count",
            "process_group_critical_count",
        }
    require_keys(raw, fields, "thresholds")
    defaults = Thresholds()
    percentages = {
        name: number(raw.get(name, getattr(defaults, name)), name, 0, 100)
        for name in (
            "memory_available_warning_percent",
            "memory_available_critical_percent",
            "swap_used_warning_percent",
            "swap_used_critical_percent",
        )
    }
    load_warning = number(
        raw.get("load_per_cpu_warning", defaults.load_per_cpu_warning),
        "load_per_cpu_warning",
        0,
        100,
    )
    load_critical = number(
        raw.get("load_per_cpu_critical", defaults.load_per_cpu_critical),
        "load_per_cpu_critical",
        0,
        100,
    )
    group_warning = integer(
        raw.get("process_group_warning_count", defaults.process_group_warning_count),
        "process_group_warning_count",
        2,
        1000,
    )
    group_critical = integer(
        raw.get("process_group_critical_count", defaults.process_group_critical_count),
        "process_group_critical_count",
        2,
        1000,
    )
    if percentages["memory_available_critical_percent"] > percentages[
        "memory_available_warning_percent"
    ]:
        raise CollectorConfigError("memory critical threshold must not exceed warning")
    if schema_version == 1 and percentages["swap_used_warning_percent"] > percentages[
        "swap_used_critical_percent"
    ]:
        raise CollectorConfigError("swap warning threshold must not exceed critical")
    if load_warning > load_critical or (
        schema_version == 1 and group_warning > group_critical
    ):
        raise CollectorConfigError("warning thresholds must not exceed critical thresholds")
    return Thresholds(
        **percentages,
        load_per_cpu_warning=load_warning,
        load_per_cpu_critical=load_critical,
        process_group_warning_count=group_warning,
        process_group_critical_count=group_critical,
    )


def parse_swap_io_sample(value: object) -> SwapIoSampleConfig:
    raw = require_mapping({} if value is None else value, "swap_io_sample")
    require_keys(
        raw,
        {"duration_ms", "warning_pages_delta", "critical_pages_delta"},
        "swap_io_sample",
    )
    defaults = SwapIoSampleConfig()
    duration = integer(raw.get("duration_ms", defaults.duration_ms), "swap sample duration", 10, 500)
    warning = integer(
        raw.get("warning_pages_delta", defaults.warning_pages_delta),
        "swap sample warning delta",
        1,
        1_000_000_000,
    )
    critical = integer(
        raw.get("critical_pages_delta", defaults.critical_pages_delta),
        "swap sample critical delta",
        1,
        1_000_000_000,
    )
    if warning > critical:
        raise CollectorConfigError("swap sample warning threshold must not exceed critical")
    return SwapIoSampleConfig(duration, warning, critical)


def parse_process_policies(value: object) -> dict[str, ProcessPolicy]:
    raw = require_mapping({} if value is None else value, "process_policies")
    if len(raw) > MAX_PROCESS_LABELS:
        raise CollectorConfigError("process policies exceeds limit")
    result: dict[str, ProcessPolicy] = {}
    for name, policy_value in raw.items():
        if not isinstance(name, str) or not SAFE_PROCESS_KEY.fullmatch(name):
            raise CollectorConfigError("process policy key is invalid")
        policy = require_mapping(policy_value, f"process_policies[{name}]")
        fields = {
            "label",
            "warning_count",
            "critical_count",
            "warning_rss_bytes",
            "critical_rss_bytes",
        }
        require_keys(policy, fields, "process policy")
        limits: dict[str, int | None] = {}
        for key in fields - {"label"}:
            maximum = 4096 if key.endswith("count") else 2**63 - 1
            raw_limit = policy.get(key)
            limits[key] = (
                None
                if raw_limit is None
                else integer(raw_limit, f"process policy {key}", 1, maximum)
            )
        if all(value is None for value in limits.values()):
            raise CollectorConfigError("process policy must define a count or RSS limit")
        if (
            limits["warning_count"] is not None
            and limits["critical_count"] is not None
            and limits["warning_count"] > limits["critical_count"]
        ) or (
            limits["warning_rss_bytes"] is not None
            and limits["critical_rss_bytes"] is not None
            and limits["warning_rss_bytes"] > limits["critical_rss_bytes"]
        ):
            raise CollectorConfigError("process policy warning limit must not exceed critical")
        label_value = policy.get("label")
        label = None if label_value is None else safe_label(label_value, "process policy label")
        result[name] = ProcessPolicy(label=label, **limits)
    return result


def parse_config(payload: object) -> CollectorConfig:
    raw = require_mapping(payload, "config")
    schema_version = raw.get("schema_version")
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version not in SUPPORTED_CONFIG_SCHEMA_VERSIONS
    ):
        raise CollectorConfigError("unsupported config schema version")
    version_fields = (
        {"expected_tcp_listeners", "process_labels"}
        if schema_version == 1
        else {"tcp_listener_policies", "process_policies", "swap_io_sample"}
    )
    require_keys(
        raw,
        {
            "schema_version",
            "thresholds",
            "filesystems",
            "docker",
        }
        | version_fields,
        "config",
    )

    raw_filesystems = raw.get("filesystems", [])
    if not isinstance(raw_filesystems, list) or len(raw_filesystems) > MAX_FILESYSTEMS:
        raise CollectorConfigError("filesystems exceeds limit")
    filesystems: list[FilesystemConfig] = []
    seen_labels: set[str] = set()
    for index, item in enumerate(raw_filesystems):
        entry = require_mapping(item, f"filesystems[{index}]")
        require_keys(entry, {"label", "path", "warning_percent", "critical_percent"}, "filesystem")
        label = safe_label(entry.get("label"), "filesystem label")
        path_value = entry.get("path")
        if (
            not isinstance(path_value, str)
            or len(path_value) > 4096
            or not Path(path_value).is_absolute()
            or "\x00" in path_value
        ):
            raise CollectorConfigError("filesystem path must be absolute")
        warning = number(entry.get("warning_percent", 80), "filesystem warning", 0, 100)
        critical = number(entry.get("critical_percent", 90), "filesystem critical", 0, 100)
        if warning > critical or label in seen_labels:
            raise CollectorConfigError("filesystem thresholds or label are invalid")
        seen_labels.add(label)
        filesystems.append(FilesystemConfig(label, Path(path_value), warning, critical))

    listener_field = "expected_tcp_listeners" if schema_version == 1 else "tcp_listener_policies"
    raw_listeners = raw.get(listener_field, [])
    if not isinstance(raw_listeners, list) or len(raw_listeners) > MAX_EXPECTED_LISTENERS:
        raise CollectorConfigError("expected listeners exceeds limit")
    expected: list[ListenerExpectation] = []
    seen_ports: set[int] = set()
    for index, item in enumerate(raw_listeners):
        entry = require_mapping(item, f"{listener_field}[{index}]")
        scopes_field = "scopes" if schema_version == 1 else "allowed_scopes"
        require_keys(entry, {"port", scopes_field}, "listener policy")
        port = integer(entry.get("port"), "listener port", 1, 65535)
        scopes = entry.get(scopes_field)
        if (
            not isinstance(scopes, list)
            or not scopes
            or len(scopes) > len(SCOPES)
            or any(scope not in SCOPES for scope in scopes)
            or len(set(scopes)) != len(scopes)
            or port in seen_ports
        ):
            raise CollectorConfigError("listener scopes or port are invalid")
        seen_ports.add(port)
        expected.append(ListenerExpectation(port, frozenset(scopes)))

    process_policies: dict[str, ProcessPolicy] = {}
    process_labels: dict[str, str] = {}
    if schema_version == 1:
        raw_labels = require_mapping(raw.get("process_labels", {}), "process_labels")
        if len(raw_labels) > MAX_PROCESS_LABELS:
            raise CollectorConfigError("process labels exceeds limit")
        for name, label in raw_labels.items():
            if not isinstance(name, str) or not SAFE_PROCESS_KEY.fullmatch(name):
                raise CollectorConfigError("process label key is invalid")
            process_labels[name] = safe_label(label, "process label")
    else:
        process_policies = parse_process_policies(raw.get("process_policies"))
        process_labels = {
            name: policy.label
            for name, policy in process_policies.items()
            if policy.label is not None
        }

    raw_docker = require_mapping(raw.get("docker", {}), "docker")
    require_keys(raw_docker, {"enabled", "container_labels"}, "docker")
    enabled = raw_docker.get("enabled", False)
    if not isinstance(enabled, bool):
        raise CollectorConfigError("docker enabled must be boolean")
    raw_containers = require_mapping(raw_docker.get("container_labels", {}), "container_labels")
    if len(raw_containers) > MAX_CONTAINER_LABELS:
        raise CollectorConfigError("container labels exceeds limit")
    container_labels: dict[str, str] = {}
    for name, label in raw_containers.items():
        if not isinstance(name, str) or not SAFE_CONTAINER_NAME.fullmatch(name):
            raise CollectorConfigError("container name is invalid")
        container_labels[name] = safe_label(label, "container label")

    return CollectorConfig(
        schema_version=schema_version,
        thresholds=parse_thresholds(raw.get("thresholds"), schema_version),
        swap_io_sample=(
            parse_swap_io_sample(raw.get("swap_io_sample"))
            if schema_version == 2
            else SwapIoSampleConfig()
        ),
        filesystems=tuple(filesystems),
        expected_listeners=tuple(expected),
        process_labels=process_labels,
        process_policies=process_policies,
        docker=DockerConfig(enabled, container_labels),
    )


def load_config(path: Path) -> CollectorConfig:
    if not path.is_absolute() or any(part in {".", ".."} for part in path.parts):
        raise CollectorConfigError("config path must be absolute and normalized")
    components = path.parts[1:]
    if not components:
        raise CollectorConfigError("config path must identify a file")
    directory_fd: int | None = None
    file_fd: int | None = None
    try:
        directory_fd = os.open(
            "/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
        )
        for component in components[:-1]:
            next_fd = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directory_fd,
            )
            os.close(directory_fd)
            directory_fd = next_fd
        file_fd = os.open(
            components[-1],
            os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=directory_fd,
        )
        before = os.fstat(file_fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_uid != os.geteuid()
            or before.st_size > MAX_CONFIG_BYTES
        ):
            raise CollectorConfigError(
                "config must be an owner-only regular file with mode 0600"
            )
        chunks: list[bytes] = []
        remaining = MAX_CONFIG_BYTES + 1
        while remaining:
            chunk = os.read(file_fd, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(file_fd)
        if len(raw) > MAX_CONFIG_BYTES:
            raise CollectorConfigError("config exceeds size limit")
        stable_fields = (
            "st_dev",
            "st_ino",
            "st_uid",
            "st_mode",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if any(getattr(before, name) != getattr(after, name) for name in stable_fields):
            raise CollectorConfigError("config changed while it was being read")
    except OSError as exc:
        raise CollectorConfigError("config path is unavailable or unsafe") from exc
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            os.close(directory_fd)
    try:
        return parse_config(json.loads(raw))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CollectorConfigError("config is not valid JSON") from exc


def fixed_reason(*reasons: str) -> list[str]:
    return list(dict.fromkeys(reasons))[:8]


def combine_status(statuses: list[str]) -> str:
    if "critical" in statuses:
        return "critical"
    if "warning" in statuses:
        return "warning"
    if "unknown" in statuses:
        return "unknown"
    return "ok"


def percent(part: int, total: int) -> float:
    return round(part * 100 / total, 1) if total > 0 else 0.0


def read_swap_counters(proc_root: Path) -> tuple[int, int]:
    values: dict[str, int] = {}
    for line in (proc_root / "vmstat").read_text(encoding="ascii").splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[0] in {"pswpin", "pswpout"}:
            value = int(fields[1])
            if value < 0:
                raise ValueError
            values[fields[0]] = value
    return values["pswpin"], values["pswpout"]


def sample_swap_io(
    proc_root: Path,
    config: SwapIoSampleConfig,
    *,
    sleep: Sleeper,
    monotonic: Clock,
) -> dict[str, object]:
    unavailable = {
        "available": False,
        "duration_ms": None,
        "pages_in_delta": None,
        "pages_out_delta": None,
    }
    if not 10 <= config.duration_ms <= 500:
        return unavailable
    try:
        first_in, first_out = read_swap_counters(proc_root)
        started = monotonic()
        sleep(config.duration_ms / 1000)
        second_in, second_out = read_swap_counters(proc_root)
        elapsed_ms = round((monotonic() - started) * 1000)
        if (
            second_in < first_in
            or second_out < first_out
            or not 1 <= elapsed_ms <= 1000
        ):
            raise ValueError
    except (OSError, UnicodeError, ValueError, KeyError):
        return unavailable
    return {
        "available": True,
        "duration_ms": elapsed_ms,
        "pages_in_delta": second_in - first_in,
        "pages_out_delta": second_out - first_out,
    }


def read_memory(
    proc_root: Path,
    thresholds: Thresholds,
    *,
    swap_io_config: SwapIoSampleConfig | None = None,
    sleep: Sleeper = time.sleep,
    monotonic: Clock = time.monotonic,
) -> dict[str, object]:
    swap_sample = (
        sample_swap_io(proc_root, swap_io_config, sleep=sleep, monotonic=monotonic)
        if swap_io_config is not None
        else None
    )
    try:
        values: dict[str, int] = {}
        for line in (proc_root / "meminfo").read_text(encoding="ascii").splitlines():
            key, separator, rest = line.partition(":")
            if separator and rest.strip().endswith(" kB"):
                values[key] = int(rest.strip().removesuffix(" kB")) * 1024
        total = values["MemTotal"]
        available = values["MemAvailable"]
        swap_total = values["SwapTotal"]
        swap_used = max(0, swap_total - values["SwapFree"])
        if total <= 0 or not 0 <= available <= total or not 0 <= swap_used <= swap_total:
            raise ValueError
    except (OSError, UnicodeError, ValueError, KeyError):
        unavailable: dict[str, object] = {
            "status": "unknown",
            "reasons": ["memory_unavailable"],
            "total_bytes": None,
            "available_bytes": None,
            "available_percent": None,
            "swap_total_bytes": None,
            "swap_used_bytes": None,
            "swap_used_percent": None,
        }
        if swap_sample is not None:
            unavailable["swap_io_sample"] = swap_sample
            if not swap_sample["available"]:
                unavailable["reasons"] = [
                    "memory_unavailable",
                    "swap_sample_unavailable",
                ]
        return unavailable
    available_percent = percent(available, total)
    swap_percent = percent(swap_used, swap_total)
    status = "ok"
    reasons: list[str] = []
    if swap_sample is None:
        if available_percent <= thresholds.memory_available_critical_percent:
            status, reasons = "critical", ["memory_available_critical"]
        elif available_percent <= thresholds.memory_available_warning_percent:
            status, reasons = "warning", ["memory_available_low"]
        if swap_total and swap_percent >= thresholds.swap_used_critical_percent:
            status, reasons = "critical", [*reasons, "swap_used_critical"]
        elif (
            swap_total
            and swap_percent >= thresholds.swap_used_warning_percent
            and status != "critical"
        ):
            status, reasons = "warning", [*reasons, "swap_used_high"]
    else:
        sample_available = bool(swap_sample["available"])
        activity = (
            int(swap_sample["pages_in_delta"])
            + int(swap_sample["pages_out_delta"])
            if sample_available
            else None
        )
        if (
            available_percent <= thresholds.memory_available_critical_percent
            and activity is not None
            and activity >= swap_io_config.critical_pages_delta
        ):
            status = "critical"
            reasons.extend(["memory_available_critical", "swap_pressure_critical"])
        elif available_percent <= thresholds.memory_available_warning_percent:
            status = "warning"
            reasons.append("memory_available_low")
        if swap_total and swap_percent >= thresholds.swap_used_warning_percent:
            if status == "ok":
                status = "warning"
            reasons.append("swap_used_high")
        if (
            activity is not None
            and activity >= swap_io_config.warning_pages_delta
            and status != "critical"
        ):
            if status == "ok":
                status = "warning"
            reasons.append("swap_activity_high")
        if not sample_available:
            reasons.append("swap_sample_unavailable")
            if status == "ok":
                status = "unknown"
    result: dict[str, object] = {
        "status": status,
        "reasons": fixed_reason(*reasons),
        "total_bytes": total,
        "available_bytes": available,
        "available_percent": available_percent,
        "swap_total_bytes": swap_total,
        "swap_used_bytes": swap_used,
        "swap_used_percent": swap_percent,
    }
    if swap_sample is not None:
        result["swap_io_sample"] = swap_sample
    return result


def read_load(proc_root: Path, thresholds: Thresholds, cpu_count: int | None) -> dict[str, object]:
    try:
        fields = (proc_root / "loadavg").read_text(encoding="ascii").split()
        one, five, fifteen = (float(field) for field in fields[:3])
        cpus = cpu_count or 1
        if min(one, five, fifteen) < 0 or not 1 <= cpus <= 65536:
            raise ValueError
    except (OSError, UnicodeError, ValueError):
        return {
            "status": "unknown",
            "reasons": ["load_unavailable"],
            "one": None,
            "five": None,
            "fifteen": None,
            "cpu_count": None,
            "normalized_one": None,
        }
    normalized = round(one / cpus, 2)
    if normalized >= thresholds.load_per_cpu_critical:
        status, reasons = "critical", ["load_critical"]
    elif normalized >= thresholds.load_per_cpu_warning:
        status, reasons = "warning", ["load_high"]
    else:
        status, reasons = "ok", []
    return {
        "status": status,
        "reasons": reasons,
        "one": round(one, 2),
        "five": round(five, 2),
        "fifteen": round(fifteen, 2),
        "cpu_count": cpus,
        "normalized_one": normalized,
    }


def read_filesystems(config: CollectorConfig, statvfs: Statvfs) -> dict[str, object]:
    items: list[dict[str, object]] = []
    for filesystem in config.filesystems:
        try:
            values = statvfs(str(filesystem.path))
            if (
                values.f_frsize <= 0
                or values.f_blocks <= 0
                or values.f_bavail < 0
                or values.f_bfree < 0
                or values.f_bavail > values.f_bfree
                or values.f_bfree > values.f_blocks
            ):
                raise ValueError
            total = values.f_blocks * values.f_frsize
            available = values.f_bavail * values.f_frsize
            used_percent = percent(total - available, total)
            if used_percent >= filesystem.critical_percent:
                status, reasons = "critical", ["filesystem_used_critical"]
            elif used_percent >= filesystem.warning_percent:
                status, reasons = "warning", ["filesystem_used_high"]
            else:
                status, reasons = "ok", []
            items.append(
                {
                    "label": filesystem.label,
                    "status": status,
                    "reasons": reasons,
                    "total_bytes": total,
                    "available_bytes": available,
                    "used_percent": used_percent,
                }
            )
        except (OSError, ValueError):
            items.append(
                {
                    "label": filesystem.label,
                    "status": "unknown",
                    "reasons": ["filesystem_unavailable"],
                    "total_bytes": None,
                    "available_bytes": None,
                    "used_percent": None,
                }
            )
    statuses = [str(item["status"]) for item in items]
    component_reasons = fixed_reason(
        *(reason for item in items for reason in item["reasons"])
    )
    return {
        "status": combine_status(statuses) if statuses else "unknown",
        "reasons": ["filesystems_not_configured"] if not items else component_reasons,
        "items": items,
    }


def clean_process_name(value: str) -> str:
    return SAFE_NAME_CHAR.sub("?", value.strip())[:64] or "unknown"


def evaluate_process_policy(
    values: dict[str, int], policy: ProcessPolicy
) -> tuple[str, list[str]]:
    critical_reasons: list[str] = []
    warning_reasons: list[str] = []
    if policy.critical_count is not None and values["count"] >= policy.critical_count:
        critical_reasons.append("process_policy_count_critical")
    elif policy.warning_count is not None and values["count"] >= policy.warning_count:
        warning_reasons.append("process_policy_count_high")
    if (
        policy.critical_rss_bytes is not None
        and values["rss_bytes"] >= policy.critical_rss_bytes
    ):
        critical_reasons.append("process_policy_rss_critical")
    elif (
        policy.warning_rss_bytes is not None
        and values["rss_bytes"] >= policy.warning_rss_bytes
    ):
        warning_reasons.append("process_policy_rss_high")
    if critical_reasons:
        return "critical", critical_reasons
    if warning_reasons:
        return "warning", warning_reasons
    return "ok", []


def read_processes(
    proc_root: Path,
    config: CollectorConfig,
    *,
    page_size: int,
    clock_ticks: int,
) -> tuple[dict[str, object], list[ProcessSample]]:
    try:
        uptime = float((proc_root / "uptime").read_text(encoding="ascii").split()[0])
        pid_paths = sorted(
            (path for path in proc_root.iterdir() if path.name.isdecimal()),
            key=lambda path: int(path.name),
        )
    except (OSError, UnicodeError, ValueError):
        return {
            "status": "unknown",
            "reasons": ["processes_unavailable"],
            "top": [],
            "groups": [],
            "scanned": 0,
            "skipped": 0,
            "inaccessible": 0,
            "truncated": False,
        }, []
    samples: list[ProcessSample] = []
    skipped = 0
    inaccessible = 0
    truncated = len(pid_paths) > MAX_PROCESSES_SCANNED
    for path in pid_paths[:MAX_PROCESSES_SCANNED]:
        try:
            stat_fields = (path / "stat").read_text(encoding="ascii").rstrip()
            closing = stat_fields.rfind(")")
            fields = stat_fields[closing + 2 :].split()
            start_ticks = int(fields[19])
            rss_pages = int(fields[21])
            name = clean_process_name((path / "comm").read_text(encoding="utf-8"))
            pid = int(path.name)
            if closing < 1 or start_ticks < 0 or rss_pages < 0:
                raise ValueError
            age = max(0, int(uptime - start_ticks / clock_ticks))
            samples.append(ProcessSample(pid, name, rss_pages * page_size, age))
        except PermissionError:
            inaccessible += 1
        except (OSError, UnicodeError, ValueError, IndexError):
            skipped += 1
    samples.sort(key=lambda item: (-item.rss_bytes, item.pid))
    groups: dict[str, dict[str, int]] = {}
    for sample in samples:
        group = groups.setdefault(sample.name, {"count": 0, "rss_bytes": 0, "oldest_age_seconds": 0})
        group["count"] += 1
        group["rss_bytes"] += sample.rss_bytes
        group["oldest_age_seconds"] = max(group["oldest_age_seconds"], sample.age_seconds)
    ordered_groups = sorted(
        groups.items(), key=lambda item: (-item[1]["rss_bytes"], item[0])
    )
    top_groups: list[dict[str, object]] = []
    status = "ok"
    reasons: list[str] = []
    if config.schema_version == 1:
        for name, values in ordered_groups[:MAX_PROCESS_GROUPS]:
            top_groups.append(
                {
                    "name": name,
                    "label": config.process_labels.get(name),
                    **values,
                }
            )
            if values["count"] >= config.thresholds.process_group_critical_count:
                status, reasons = "critical", ["process_group_count_critical"]
            elif (
                values["count"] >= config.thresholds.process_group_warning_count
                and status != "critical"
            ):
                status, reasons = "warning", ["process_group_count_high"]
    else:
        evaluated: list[tuple[int, str, dict[str, object]]] = []
        severity_rank = {"critical": 0, "warning": 1, "ok": 2}
        for name, values in ordered_groups:
            policy = config.process_policies.get(name)
            group_status, group_reasons = (
                evaluate_process_policy(values, policy) if policy is not None else ("ok", [])
            )
            if group_status == "critical":
                status = "critical"
            elif group_status == "warning" and status != "critical":
                status = "warning"
            reasons.extend(group_reasons)
            policy_status = (
                "not_configured"
                if policy is None
                else "violated"
                if group_status != "ok"
                else "within_limits"
            )
            evaluated.append(
                (
                    severity_rank[group_status],
                    name,
                    {
                        "name": name,
                        "label": config.process_labels.get(name),
                        **values,
                        "policy_status": policy_status,
                    },
                )
            )
        evaluated.sort(
            key=lambda item: (item[0], -int(item[2]["rss_bytes"]), item[1])
        )
        top_groups = [item[2] for item in evaluated[:MAX_PROCESS_GROUPS]]
        reasons = fixed_reason(*reasons)
    if inaccessible or (config.schema_version == 2 and truncated):
        reasons = [*reasons, "processes_partial"]
        if status == "ok":
            status = "unknown"
    top = [
        {
            "pid": sample.pid,
            "name": sample.name,
            "label": config.process_labels.get(sample.name),
            "rss_bytes": sample.rss_bytes,
            "age_seconds": sample.age_seconds,
        }
        for sample in samples[:MAX_TOP_PROCESSES]
    ]
    return {
        "status": status if samples else "unknown",
        "reasons": fixed_reason(*reasons) if samples else ["processes_unavailable"],
        "top": top,
        "groups": top_groups,
        "scanned": len(samples),
        "skipped": skipped,
        "inaccessible": inaccessible,
        "truncated": truncated,
    }, samples


def decode_proc_address(encoded: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    if len(encoded) == 8:
        return ipaddress.IPv4Address(bytes.fromhex(encoded)[::-1])
    if len(encoded) == 32:
        chunks = [bytes.fromhex(encoded[index : index + 8])[::-1] for index in range(0, 32, 8)]
        return ipaddress.IPv6Address(b"".join(chunks))
    raise ValueError


def address_scope(encoded: str) -> str:
    address = decode_proc_address(encoded)
    if address.is_unspecified:
        return "wildcard"
    if address.is_loopback:
        return "loopback"
    if isinstance(address, ipaddress.IPv4Address) and address in ipaddress.ip_network("100.64.0.0/10"):
        return "tailscale"
    if isinstance(address, ipaddress.IPv6Address) and address in TAILSCALE_IPV6:
        return "tailscale"
    return "other"


def read_listener_rows(
    proc_root: Path,
) -> tuple[list[tuple[int, str, str]], bool, bool, bool]:
    rows: list[tuple[int, str, str]] = []
    readable = False
    partial = False
    for relative in (Path("net/tcp"), Path("net/tcp6")):
        try:
            all_lines = (proc_root / relative).read_text(encoding="ascii").splitlines()
            readable = True
        except (OSError, UnicodeError):
            partial = True
            continue
        if not all_lines or not {
            "local_address",
            "rem_address",
            "st",
            "inode",
        }.issubset(all_lines[0].split()):
            partial = True
            continue
        lines = all_lines[1:]
        for line in lines:
            if not line.strip():
                continue
            fields = line.split()
            try:
                if fields[3] != "0A":
                    continue
                encoded, port_hex = fields[1].split(":", 1)
                row = (int(port_hex, 16), address_scope(encoded), fields[9])
                if len(rows) < MAX_LISTENERS_SCANNED:
                    rows.append(row)
                else:
                    return rows, True, True, True
            except (IndexError, ValueError):
                partial = True
    return rows, readable, False, partial


def map_socket_processes(
    proc_root: Path, samples: list[ProcessSample], inodes: set[str]
) -> dict[str, str]:
    result: dict[str, str] = {}
    names = {sample.pid: sample.name for sample in samples}
    for pid, name in names.items():
        try:
            descriptors = islice(
                (proc_root / str(pid) / "fd").iterdir(), MAX_FDS_PER_PROCESS
            )
        except OSError:
            continue
        for descriptor in descriptors:
            try:
                target = os.readlink(descriptor)
            except OSError:
                continue
            if target.startswith("socket:[") and target.endswith("]"):
                inode = target[8:-1]
                if inode in inodes:
                    result.setdefault(inode, name)
        if inodes.issubset(result):
            break
    return result


def read_listeners(
    proc_root: Path, config: CollectorConfig, samples: list[ProcessSample]
) -> dict[str, object]:
    rows, readable, scan_truncated, partial = read_listener_rows(proc_root)
    if not readable:
        return {
            "status": "unknown",
            "reasons": ["listeners_unavailable"],
            "items": [],
            "truncated": False,
        }
    inode_names = map_socket_processes(proc_root, samples, {row[2] for row in rows})
    expectations = {item.port: item.scopes for item in config.expected_listeners}
    unique: dict[tuple[int, str, str | None], dict[str, object]] = {}
    status = "ok"
    reasons: list[str] = []
    ownership_partial = False
    for port, scope, inode in rows:
        process_name = inode_names.get(inode)
        ownership_partial = ownership_partial or process_name is None
        configured = port in expectations
        expected = configured and scope in expectations[port]
        if config.schema_version == 1:
            item_status = "ok" if expected else "warning"
            if not expected and scope == "wildcard":
                item_status = "critical"
            item: dict[str, object] = {
                "port": port,
                "address_scope": scope,
                "process_name": process_name,
                "process_label": config.process_labels.get(process_name or ""),
                "expected": expected,
                "status": item_status,
            }
        else:
            policy_status = (
                "allowed" if expected else "violated" if configured else "not_configured"
            )
            item_status = "ok" if expected else "critical" if configured else "warning"
            item = {
                "port": port,
                "bind_scope": scope,
                "external_reachability": "not_assessed",
                "process_name": process_name,
                "process_label": config.process_labels.get(process_name or ""),
                "policy_status": policy_status,
                "status": item_status,
            }
        if item_status == "critical":
            status = "critical"
            reasons.append(
                "wildcard_listener_unexpected"
                if scope == "wildcard"
                else "tcp_listener_unexpected"
            )
        elif item_status == "warning" and status != "critical":
            status = "warning"
            reasons.append(
                "wildcard_listener_unexpected"
                if scope == "wildcard"
                else "tcp_listener_unexpected"
            )
        unique[(port, scope, process_name)] = item
    scope_field = "address_scope" if config.schema_version == 1 else "bind_scope"
    ordered = sorted(
        unique.values(),
        key=lambda item: (int(item["port"]), str(item[scope_field])),
    )
    if partial or (config.schema_version == 2 and ownership_partial):
        reasons.append("listeners_partial")
        if status == "ok":
            status = "unknown"
    return {
        "status": status,
        "reasons": fixed_reason(*reasons),
        "items": ordered[:MAX_LISTENERS],
        "truncated": scan_truncated or len(ordered) > MAX_LISTENERS,
    }


def run_bounded_process(
    argv: list[str], *, timeout_seconds: float, max_output_bytes: int
) -> DockerCommandResult:
    process = subprocess.Popen(
        argv,
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert process.stdout is not None
    deadline = time.monotonic() + timeout_seconds
    output = bytearray()
    selector = selectors.DefaultSelector()
    os.set_blocking(process.stdout.fileno(), False)
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        while True:
            remaining_time = deadline - time.monotonic()
            if remaining_time <= 0:
                raise subprocess.TimeoutExpired(argv, timeout_seconds)
            events = selector.select(remaining_time)
            if not events:
                raise subprocess.TimeoutExpired(argv, timeout_seconds)
            chunk = os.read(
                process.stdout.fileno(),
                min(64 * 1024, max_output_bytes + 1 - len(output)),
            )
            if not chunk:
                remaining_time = deadline - time.monotonic()
                if remaining_time <= 0:
                    raise subprocess.TimeoutExpired(argv, timeout_seconds)
                return DockerCommandResult(
                    process.wait(timeout=remaining_time), bytes(output)
                )
            output.extend(chunk)
            if len(output) > max_output_bytes:
                process.kill()
                process.wait()
                return DockerCommandResult(process.returncode, bytes(output), excessive=True)
    finally:
        selector.close()
        process.stdout.close()
        if process.poll() is None:
            process.kill()
            process.wait()


def default_docker_runner() -> DockerCommandResult:
    return run_bounded_process(
        [DOCKER_BINARY, "ps", "-a", "--format", "{{.Names}}\t{{.Status}}"],
        timeout_seconds=DOCKER_TIMEOUT_SECONDS,
        max_output_bytes=MAX_DOCKER_OUTPUT_BYTES,
    )


def normalize_container_status(raw: str) -> tuple[str, str]:
    lowered = raw.lower()
    if "unhealthy" in lowered or lowered.startswith(("restarting", "dead", "exited")):
        return "critical", "container_unhealthy"
    if "health: starting" in lowered or lowered.startswith("created"):
        return "warning", "container_starting"
    if "paused" in lowered:
        return "warning", "container_paused"
    if lowered.startswith("up"):
        return "ok", ""
    return "warning", "container_state_unknown"


def docker_invalid_result() -> dict[str, object]:
    return {
        "status": "unknown",
        "reasons": ["docker_output_invalid"],
        "available": False,
        "problematic": [],
        "unmapped_problematic_count": 0,
    }


def read_docker(config: DockerConfig, runner: DockerRunner) -> dict[str, object]:
    if not config.enabled:
        return {
            "status": "unknown",
            "reasons": ["docker_disabled"],
            "available": False,
            "problematic": [],
            "unmapped_problematic_count": 0,
        }
    try:
        completed = runner()
    except (OSError, subprocess.TimeoutExpired):
        return {
            "status": "unknown",
            "reasons": ["docker_unavailable"],
            "available": False,
            "problematic": [],
            "unmapped_problematic_count": 0,
        }
    if completed.returncode != 0 or completed.excessive:
        reason = "docker_output_excessive" if completed.excessive else "docker_unavailable"
        return {
            "status": "unknown",
            "reasons": [reason],
            "available": False,
            "problematic": [],
            "unmapped_problematic_count": 0,
        }
    problematic: list[dict[str, str]] = []
    unmapped = 0
    statuses: list[str] = []
    try:
        lines = completed.stdout.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return docker_invalid_result()
    if len(lines) > 1000:
        return docker_invalid_result()
    for line in lines:
        name, separator, raw_status = line.partition("\t")
        if (
            not separator
            or "\t" in raw_status
            or not SAFE_CONTAINER_NAME.fullmatch(name)
            or not raw_status
            or len(raw_status) > 256
        ):
            return docker_invalid_result()
        status, reason = normalize_container_status(raw_status[:256])
        if status == "ok":
            continue
        statuses.append(status)
        label = config.container_labels.get(name)
        if label and len(problematic) < MAX_CONTAINER_LABELS:
            problematic.append({"label": label, "status": status, "reason": reason})
        else:
            unmapped += 1
    result_status = combine_status(statuses) if statuses else "ok"
    return {
        "status": result_status,
        "reasons": [] if result_status == "ok" else ["containers_problematic"],
        "available": True,
        "problematic": problematic,
        "unmapped_problematic_count": unmapped,
    }


def collect_snapshot(
    config: CollectorConfig,
    *,
    proc_root: Path = Path("/proc"),
    statvfs: Statvfs = os.statvfs,
    docker_runner: DockerRunner = default_docker_runner,
    cpu_count: int | None = None,
    page_size: int | None = None,
    clock_ticks: int | None = None,
    sleep: Sleeper = time.sleep,
    monotonic: Clock = time.monotonic,
) -> dict[str, object]:
    started = monotonic()
    memory = read_memory(
        proc_root,
        config.thresholds,
        swap_io_config=config.swap_io_sample if config.schema_version == 2 else None,
        sleep=sleep,
        monotonic=monotonic,
    )
    load = read_load(proc_root, config.thresholds, cpu_count if cpu_count is not None else os.cpu_count())
    filesystems = read_filesystems(config, statvfs)
    processes, samples = read_processes(
        proc_root,
        config,
        page_size=page_size or os.sysconf("SC_PAGE_SIZE"),
        clock_ticks=clock_ticks or os.sysconf("SC_CLK_TCK"),
    )
    listeners = read_listeners(proc_root, config, samples)
    docker = read_docker(config.docker, docker_runner)
    components = [memory, load, filesystems, processes, listeners, docker]
    reasons = fixed_reason(
        *(reason for component in components for reason in component.get("reasons", []))
    )
    return {
        "schema_version": config.schema_version,
        "collected_at": datetime.now(UTC).isoformat(),
        "duration_ms": max(0, int((monotonic() - started) * 1000)),
        "status": combine_status([str(component["status"]) for component in components]),
        "reasons": reasons,
        "memory": memory,
        "load": load,
        "filesystems": filesystems,
        "processes": processes,
        "listeners": listeners,
        "docker": docker,
    }


def write_response(payload: bytes, fd: int = 1) -> None:
    offset = 0
    while offset < len(payload):
        try:
            written = os.write(fd, payload[offset:])
        except BrokenPipeError:
            # Il consumer può chiudere una socket Accept=yes dopo aver annullato
            # il refresh. Non è un errore di raccolta e non deve lasciare la
            # one-shot systemd in stato failed.
            return
        if written <= 0:
            raise OSError("host observability response write made no progress")
        offset += written


def main() -> None:
    config_value = os.environ.get("MAC_HOST_OBSERVABILITY_CONFIG_FILE")
    if not config_value:
        raise SystemExit("host observability config is not configured")
    try:
        snapshot = collect_snapshot(load_config(Path(config_value)))
        payload = json.dumps(snapshot, separators=(",", ":")).encode("utf-8")
    except (CollectorConfigError, OSError, ValueError) as exc:
        raise SystemExit(f"host observability collector failed: {type(exc).__name__}") from exc
    if len(payload) > MAX_RESPONSE_BYTES:
        raise SystemExit("host observability collector response exceeds limit")
    write_response(payload)


if __name__ == "__main__":
    main()
