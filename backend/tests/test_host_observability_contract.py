import json
from itertools import product
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.services.host_observability_contract import validate_host_observability_snapshot

BROWSER_FIXTURES = Path(__file__).parents[2] / "frontend" / "tests" / "fixtures"


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


def valid_snapshot_v2() -> dict[str, object]:
    payload = valid_snapshot()
    payload["schema_version"] = 2
    payload["reasons"] = ["process_policy_count_high"]
    memory = payload["memory"]
    assert isinstance(memory, dict)
    memory["swap_io_sample"] = {
        "available": True,
        "duration_ms": 100,
        "pages_in_delta": 0,
        "pages_out_delta": 2,
    }
    processes = payload["processes"]
    assert isinstance(processes, dict)
    processes["reasons"] = ["process_policy_count_high"]
    groups = processes["groups"]
    assert isinstance(groups, list)
    groups[0]["policy_status"] = "violated"
    listeners = payload["listeners"]
    assert isinstance(listeners, dict)
    items = listeners["items"]
    assert isinstance(items, list)
    listener = items[0]
    listener["bind_scope"] = listener.pop("address_scope")
    listener["external_reachability"] = "not_assessed"
    listener["policy_status"] = "allowed"
    listener.pop("expected")
    return payload


def test_host_observability_contract_accepts_v1_snapshot() -> None:
    snapshot = validate_host_observability_snapshot(valid_snapshot())

    assert snapshot.schema_version == 1
    assert snapshot.processes.groups[0].count == 9
    assert snapshot.listeners.items[0].address_scope == "loopback"


def test_host_observability_contract_accepts_v2_snapshot() -> None:
    snapshot = validate_host_observability_snapshot(valid_snapshot_v2())

    assert snapshot.schema_version == 2
    assert snapshot.memory.swap_io_sample.pages_out_delta == 2
    assert snapshot.processes.groups[0].policy_status == "violated"
    assert snapshot.listeners.items[0].bind_scope == "loopback"
    assert snapshot.listeners.items[0].external_reachability == "not_assessed"


@pytest.mark.parametrize(
    ("filename", "schema_version"),
    [("host-observability-v1.json", 1), ("host-observability-v2.json", 2)],
)
def test_browser_fixtures_match_authoritative_contract(
    filename: str, schema_version: int
) -> None:
    payload = json.loads((BROWSER_FIXTURES / filename).read_text(encoding="utf-8"))

    assert validate_host_observability_snapshot(payload).schema_version == schema_version


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("schema_version",), 3),
        (("duration_ms",), "21"),
        (("collected_at",), "2026-08-01T12:00:00"),
        (("collected_at",), "2026-08-01T12:00:00+01:00"),
        (("collected_at",), 123),
        (("status",), "healthy"),
        (("reasons", 0), "swap_pressure_critical"),
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
        validate_host_observability_snapshot(payload)


def test_host_observability_contract_forbids_extra_fields() -> None:
    payload = valid_snapshot()
    payload["hostname"] = "private-host"

    with pytest.raises(ValidationError):
        validate_host_observability_snapshot(payload)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("memory", "swap_io_sample", "available"), False),
        (("memory", "swap_io_sample", "duration_ms"), 0),
        (("memory", "swap_io_sample", "pages_in_delta"), -1),
        (("listeners", "items", 0, "external_reachability"), "closed"),
        (("listeners", "items", 0, "bind_scope"), "0.0.0.0"),
        (("processes", "groups", 0, "policy_status"), "ignored"),
        (("reasons", 0), "swap_used_critical"),
    ],
)
def test_host_observability_contract_rejects_invalid_v2_shapes(
    path: tuple[str | int, ...], value: object
) -> None:
    payload = valid_snapshot_v2()
    target: Any = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(ValidationError):
        validate_host_observability_snapshot(payload)


def test_host_observability_contract_accepts_unavailable_swap_sample() -> None:
    payload = valid_snapshot_v2()
    memory = payload["memory"]
    assert isinstance(memory, dict)
    memory["swap_io_sample"] = {
        "available": False,
        "duration_ms": None,
        "pages_in_delta": None,
        "pages_out_delta": None,
    }
    memory["status"] = "unknown"
    memory["reasons"] = ["swap_sample_unavailable"]

    snapshot = validate_host_observability_snapshot(payload)

    assert snapshot.schema_version == 2
    assert snapshot.memory.swap_io_sample.available is False


@pytest.mark.parametrize("available", [False, True])
@pytest.mark.parametrize("present", list(product([False, True], repeat=3)))
def test_host_observability_contract_enforces_complete_swap_sample_matrix(
    available: bool, present: tuple[bool, bool, bool]
) -> None:
    payload = valid_snapshot_v2()
    memory = payload["memory"]
    assert isinstance(memory, dict)
    memory["swap_io_sample"] = {
        "available": available,
        "duration_ms": 100 if present[0] else None,
        "pages_in_delta": 1 if present[1] else None,
        "pages_out_delta": 2 if present[2] else None,
    }
    valid = (available and all(present)) or (not available and not any(present))

    if valid:
        assert validate_host_observability_snapshot(payload).schema_version == 2
    else:
        with pytest.raises(ValidationError):
            validate_host_observability_snapshot(payload)


def test_host_observability_contract_forbids_v2_extra_fields() -> None:
    payload = valid_snapshot_v2()
    listener = payload["listeners"]["items"][0]
    listener["firewall_state"] = "closed"

    with pytest.raises(ValidationError):
        validate_host_observability_snapshot(payload)
