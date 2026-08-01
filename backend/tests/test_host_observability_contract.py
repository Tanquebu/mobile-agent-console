from typing import Any

import pytest
from pydantic import ValidationError

from app.services.host_observability_contract import HostObservabilitySnapshot


def valid_snapshot() -> dict[str, object]:
    return {
        "schema_version": 1,
        "collected_at": "2026-08-01T12:00:00Z",
        "duration_ms": 21,
        "status": "warning",
        "reasons": ["process_group_count_high"],
        "memory": {
            "status": "ok",
            "reasons": [],
            "total_bytes": 4_000_000_000,
            "available_bytes": 2_000_000_000,
            "available_percent": 50,
            "swap_total_bytes": 1_000_000_000,
            "swap_used_bytes": 0,
            "swap_used_percent": 0,
        },
        "load": {
            "status": "ok",
            "reasons": [],
            "one": 0.5,
            "five": 0.4,
            "fifteen": 0.3,
            "cpu_count": 4,
            "normalized_one": 0.12,
        },
        "filesystems": {
            "status": "ok",
            "reasons": [],
            "items": [
                {
                    "label": "System disk",
                    "status": "ok",
                    "reasons": [],
                    "total_bytes": 1000,
                    "available_bytes": 500,
                    "used_percent": 50,
                }
            ],
        },
        "processes": {
            "status": "warning",
            "reasons": ["process_group_count_high"],
            "top": [
                {
                    "pid": 101,
                    "name": "node",
                    "label": "Development server",
                    "rss_bytes": 270_532_608,
                    "age_seconds": 3600,
                }
            ],
            "groups": [
                {
                    "name": "node",
                    "label": "Development server",
                    "count": 9,
                    "rss_bytes": 2_434_793_472,
                    "oldest_age_seconds": 7200,
                }
            ],
            "scanned": 20,
            "skipped": 1,
            "inaccessible": 0,
            "truncated": False,
        },
        "listeners": {
            "status": "ok",
            "reasons": [],
            "items": [
                {
                    "port": 8081,
                    "address_scope": "loopback",
                    "process_name": "python3",
                    "process_label": None,
                    "expected": True,
                    "status": "ok",
                }
            ],
            "truncated": False,
        },
        "docker": {
            "status": "unknown",
            "reasons": ["docker_disabled"],
            "available": False,
            "problematic": [],
            "unmapped_problematic_count": 0,
        },
    }


def test_host_observability_contract_accepts_v1_snapshot() -> None:
    snapshot = HostObservabilitySnapshot.model_validate(valid_snapshot())

    assert snapshot.schema_version == 1
    assert snapshot.processes.groups[0].count == 9
    assert snapshot.listeners.items[0].address_scope == "loopback"


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("schema_version",), 2),
        (("duration_ms",), "21"),
        (("collected_at",), "2026-08-01T12:00:00"),
        (("collected_at",), "2026-08-01T12:00:00+01:00"),
        (("collected_at",), 123),
        (("status",), "healthy"),
        (("listeners", "items", 0, "address_scope"), "127.0.0.1"),
        (("processes", "top", 0, "name"), "/usr/bin/node"),
        (("docker", "problematic"), [{"label": "x", "status": "ok", "reason": "x"}]),
    ],
)
def test_host_observability_contract_rejects_invalid_or_sensitive_shapes(
    path: tuple[str | int, ...], value: object
) -> None:
    payload = valid_snapshot()
    target: Any = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(ValidationError):
        HostObservabilitySnapshot.model_validate(payload)


def test_host_observability_contract_forbids_extra_fields() -> None:
    payload = valid_snapshot()
    payload["hostname"] = "private-host"

    with pytest.raises(ValidationError):
        HostObservabilitySnapshot.model_validate(payload)
