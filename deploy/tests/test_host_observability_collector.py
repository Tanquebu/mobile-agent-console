import importlib.util
import ipaddress
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / "host-observability-collector.py"
SPEC = importlib.util.spec_from_file_location("host_observability_collector", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)
TCP_HEADER = (
    "sl local_address rem_address st tx_queue rx_queue tr tm->when retrnsmt "
    "uid timeout inode\n"
)


def base_config(**overrides):
    payload = {
        "schema_version": 1,
        "thresholds": {},
        "filesystems": [
            {
                "label": "System disk",
                "path": "/srv/private-real-path",
                "warning_percent": 80,
                "critical_percent": 90,
            }
        ],
        "expected_tcp_listeners": [
            {"port": 8081, "scopes": ["loopback", "tailscale"]}
        ],
        "process_labels": {"node": "Development server"},
        "docker": {
            "enabled": False,
            "container_labels": {"private-backend-name": "Backend"},
        },
    }
    payload.update(overrides)
    return payload


def base_config_v2(**overrides):
    payload = {
        "schema_version": 2,
        "thresholds": {
            "memory_available_warning_percent": 20,
            "memory_available_critical_percent": 10,
            "swap_used_warning_percent": 50,
            "load_per_cpu_warning": 1,
            "load_per_cpu_critical": 2,
        },
        "swap_io_sample": {
            "duration_ms": 100,
            "warning_pages_delta": 1,
            "critical_pages_delta": 128,
        },
        "filesystems": [],
        "tcp_listener_policies": [
            {"port": 4242, "allowed_scopes": ["loopback", "tailscale"]}
        ],
        "process_policies": {
            "example-worker": {
                "label": "Example worker",
                "warning_count": 8,
                "critical_count": 12,
                "warning_rss_bytes": 1_073_741_824,
                "critical_rss_bytes": 2_147_483_648,
            }
        },
        "docker": {"enabled": False, "container_labels": {}},
    }
    payload.update(overrides)
    return payload


def process_stat(pid: int, name: str, start_ticks: int, rss_pages: int) -> str:
    fields = ["0"] * 22
    fields[0] = "S"
    fields[19] = str(start_ticks)
    fields[21] = str(rss_pages)
    return f"{pid} ({name}) {' '.join(fields)}\n"


def add_process(
    proc_root: Path,
    pid: int,
    name: str,
    rss_pages: int,
    *,
    start_ticks: int = 100,
    socket_inode: str | None = None,
) -> None:
    path = proc_root / str(pid)
    (path / "fd").mkdir(parents=True)
    (path / "comm").write_text(f"{name}\n", encoding="utf-8")
    (path / "stat").write_text(
        process_stat(pid, name, start_ticks, rss_pages), encoding="ascii"
    )
    if socket_inode:
        (path / "fd" / "3").symlink_to(f"socket:[{socket_inode}]")


def tcp_row(address: str, port: int, inode: str) -> str:
    return (
        f"0: {address}:{port:04X} 00000000:0000 0A 00000000:00000000 "
        f"00:00000000 00000000 1000 0 {inode} 1\n"
    )


def make_proc_root(root: Path) -> Path:
    proc_root = root / "proc"
    (proc_root / "net").mkdir(parents=True)
    (proc_root / "meminfo").write_text(
        "MemTotal:       4194304 kB\n"
        "MemAvailable:   2097152 kB\n"
        "SwapTotal:      1048576 kB\n"
        "SwapFree:        786432 kB\n",
        encoding="ascii",
    )
    (proc_root / "loadavg").write_text("2.00 1.50 1.00 1/100 42\n", encoding="ascii")
    (proc_root / "uptime").write_text("10000.00 0.00\n", encoding="ascii")
    write_vmstat(proc_root, pages_in=100, pages_out=200)
    (proc_root / "net" / "tcp").write_text(TCP_HEADER, encoding="ascii")
    (proc_root / "net" / "tcp6").write_text(TCP_HEADER, encoding="ascii")
    return proc_root


def write_memory(
    proc_root: Path,
    *,
    total_kb: int = 1_000_000,
    available_kb: int = 500_000,
    swap_total_kb: int = 1_000_000,
    swap_free_kb: int = 900_000,
) -> None:
    (proc_root / "meminfo").write_text(
        f"MemTotal:       {total_kb} kB\n"
        f"MemAvailable:   {available_kb} kB\n"
        f"SwapTotal:      {swap_total_kb} kB\n"
        f"SwapFree:       {swap_free_kb} kB\n",
        encoding="ascii",
    )


def write_vmstat(proc_root: Path, *, pages_in: int, pages_out: int) -> None:
    (proc_root / "vmstat").write_text(
        f"nr_free_pages 100\npswpin {pages_in}\npswpout {pages_out}\n",
        encoding="ascii",
    )


def sequence_clock(*values: float):
    remaining = iter(values)
    return lambda: next(remaining)


def statvfs_with_usage(used_percent: int):
    blocks = 1000
    available = blocks * (100 - used_percent) // 100
    return os.statvfs_result((4096, 4096, blocks, available, available, 1, 1, 1, 0, 255))


class HostObservabilityCollectorTest(unittest.TestCase):
    def test_consumer_disconnect_during_final_write_exits_cleanly(self) -> None:
        snapshot = {"schema_version": 2, "status": "ok"}
        with (
            patch.dict(
                collector.os.environ,
                {"MAC_HOST_OBSERVABILITY_CONFIG_FILE": "/private/config.json"},
            ),
            patch.object(collector, "load_config", return_value=object()),
            patch.object(collector, "collect_snapshot", return_value=snapshot),
            patch.object(collector.os, "write", side_effect=BrokenPipeError),
        ):
            self.assertIsNone(collector.main())

    def test_final_write_keeps_unexpected_io_errors_fail_closed(self) -> None:
        with patch.object(
            collector.os, "write", side_effect=OSError("write failed")
        ), self.assertRaisesRegex(OSError, "write failed"):
            collector.write_response(b"payload")

    def test_v2_high_swap_without_memory_pressure_is_warning_not_critical(self) -> None:
        with TemporaryDirectory() as temporary:
            proc_root = make_proc_root(Path(temporary))
            write_memory(proc_root, available_kb=500_000, swap_free_kb=100_000)
            result = collector.read_memory(
                proc_root,
                collector.parse_config(base_config_v2()).thresholds,
                swap_io_config=collector.SwapIoSampleConfig(),
                sleep=lambda _seconds: None,
                monotonic=sequence_clock(10, 10.1),
            )

        self.assertEqual(result["status"], "warning")
        self.assertIn("swap_used_high", result["reasons"])
        self.assertNotIn("swap_pressure_critical", result["reasons"])
        self.assertEqual(result["swap_io_sample"]["pages_in_delta"], 0)
        self.assertEqual(result["swap_io_sample"]["pages_out_delta"], 0)

    def test_v2_memory_pressure_and_swap_io_at_boundary_are_critical(self) -> None:
        with TemporaryDirectory() as temporary:
            proc_root = make_proc_root(Path(temporary))
            write_memory(proc_root, available_kb=100_000, swap_free_kb=100_000)
            sleeps: list[float] = []

            def advance_swap(seconds: float) -> None:
                sleeps.append(seconds)
                write_vmstat(proc_root, pages_in=100, pages_out=328)

            config = collector.parse_config(
                base_config_v2(
                    swap_io_sample={
                        "duration_ms": 100,
                        "warning_pages_delta": 1,
                        "critical_pages_delta": 128,
                    },
                    docker={"enabled": True, "container_labels": {}},
                )
            )
            add_process(proc_root, 1, "shell", 10)
            snapshot = collector.collect_snapshot(
                config,
                proc_root=proc_root,
                statvfs=os.statvfs,
                docker_runner=lambda: (_ for _ in ()).throw(PermissionError()),
                cpu_count=4,
                page_size=4096,
                clock_ticks=100,
                sleep=advance_swap,
                monotonic=sequence_clock(1, 1.01, 1.11, 1.12),
            )

        self.assertEqual(sleeps, [0.1])
        self.assertEqual(snapshot["schema_version"], 2)
        self.assertEqual(snapshot["duration_ms"], 120)
        self.assertEqual(snapshot["memory"]["status"], "critical")
        self.assertEqual(snapshot["memory"]["swap_io_sample"]["duration_ms"], 100)
        self.assertIn("swap_pressure_critical", snapshot["memory"]["reasons"])
        self.assertEqual(snapshot["docker"]["status"], "unknown")
        self.assertIn("docker_unavailable", snapshot["reasons"])
        self.assertEqual(snapshot["status"], "critical")
        self.assertIn("swap_pressure_critical", snapshot["reasons"])
        serialized = json.dumps(snapshot)
        self.assertLess(len(serialized.encode()), collector.MAX_RESPONSE_BYTES)
        self.assertNotIn("allowed_scopes", serialized)
        self.assertNotIn("critical_pages_delta", serialized)
        self.assertNotIn("/srv/", serialized)

    def test_v2_swap_sample_unavailable_partial_reset_and_timeout_are_unknown(self) -> None:
        with TemporaryDirectory() as temporary:
            proc_root = make_proc_root(Path(temporary))
            write_memory(proc_root, swap_free_kb=900_000)
            config = collector.parse_config(base_config_v2()).swap_io_sample
            cases = []

            (proc_root / "vmstat").unlink()
            cases.append(
                collector.read_memory(
                    proc_root,
                    collector.Thresholds(),
                    swap_io_config=config,
                    sleep=lambda _seconds: self.fail("sleep after unavailable first read"),
                    monotonic=sequence_clock(),
                )
            )

            write_vmstat(proc_root, pages_in=100, pages_out=200)

            def partial_second_read(_seconds: float) -> None:
                (proc_root / "vmstat").write_text("pswpin 101\n", encoding="ascii")

            cases.append(
                collector.read_memory(
                    proc_root,
                    collector.Thresholds(),
                    swap_io_config=config,
                    sleep=partial_second_read,
                    monotonic=sequence_clock(1),
                )
            )

            write_vmstat(proc_root, pages_in=100, pages_out=200)
            cases.append(
                collector.read_memory(
                    proc_root,
                    collector.Thresholds(),
                    swap_io_config=config,
                    sleep=lambda _seconds: (_ for _ in ()).throw(TimeoutError()),
                    monotonic=sequence_clock(1),
                )
            )

            write_vmstat(proc_root, pages_in=100, pages_out=200)

            def reset_counters(_seconds: float) -> None:
                write_vmstat(proc_root, pages_in=99, pages_out=199)

            cases.append(
                collector.read_memory(
                    proc_root,
                    collector.Thresholds(),
                    swap_io_config=config,
                    sleep=reset_counters,
                    monotonic=sequence_clock(1, 1.1),
                )
            )

            write_vmstat(proc_root, pages_in=100, pages_out=200)
            cases.append(
                collector.read_memory(
                    proc_root,
                    collector.Thresholds(),
                    swap_io_config=config,
                    sleep=lambda _seconds: None,
                    monotonic=sequence_clock(1, 2.001),
                )
            )

        for result in cases:
            with self.subTest(result=result):
                self.assertEqual(result["status"], "unknown")
                self.assertEqual(
                    result["swap_io_sample"],
                    {
                        "available": False,
                        "duration_ms": None,
                        "pages_in_delta": None,
                        "pages_out_delta": None,
                    },
                )
                self.assertIn("swap_sample_unavailable", result["reasons"])

    def test_v2_swap_sample_rejects_unbounded_duration_without_sleeping(self) -> None:
        with TemporaryDirectory() as temporary:
            proc_root = make_proc_root(Path(temporary))
            sleeps: list[float] = []
            result = collector.sample_swap_io(
                proc_root,
                collector.SwapIoSampleConfig(duration_ms=501),
                sleep=sleeps.append,
                monotonic=sequence_clock(),
            )

        self.assertFalse(result["available"])
        self.assertEqual(sleeps, [])

    def test_v2_unconfigured_process_groups_are_visible_and_neutral(self) -> None:
        with TemporaryDirectory() as temporary:
            proc_root = make_proc_root(Path(temporary))
            for index in range(12):
                add_process(proc_root, 100 + index, "node", 64)
            result, _samples = collector.read_processes(
                proc_root,
                collector.parse_config(base_config_v2(process_policies={})),
                page_size=4096,
                clock_ticks=100,
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["reasons"], [])
        self.assertEqual(result["groups"][0]["count"], 12)
        self.assertEqual(result["groups"][0]["policy_status"], "not_configured")

    def test_v2_process_policies_apply_count_and_aggregate_rss_boundaries(self) -> None:
        with TemporaryDirectory() as temporary:
            proc_root = make_proc_root(Path(temporary))
            for index in range(3):
                add_process(proc_root, 100 + index, "node", 1)
            count_config = collector.parse_config(
                base_config_v2(
                    process_policies={
                        "node": {"warning_count": 3, "critical_count": 4}
                    }
                )
            )
            count_result, _samples = collector.read_processes(
                proc_root, count_config, page_size=4096, clock_ticks=100
            )
            rss_config = collector.parse_config(
                base_config_v2(
                    process_policies={
                        "node": {
                            "warning_rss_bytes": 8_192,
                            "critical_rss_bytes": 12_288,
                        }
                    }
                )
            )
            rss_result, _samples = collector.read_processes(
                proc_root, rss_config, page_size=4096, clock_ticks=100
            )

        self.assertEqual(count_result["status"], "warning")
        self.assertIn("process_policy_count_high", count_result["reasons"])
        self.assertEqual(count_result["groups"][0]["policy_status"], "violated")
        self.assertEqual(rss_result["status"], "critical")
        self.assertIn("process_policy_rss_critical", rss_result["reasons"])
        self.assertEqual(rss_result["groups"][0]["rss_bytes"], 12_288)

    def test_v2_process_policy_thresholds_are_inclusive_and_below_is_ok(self) -> None:
        values = {"count": 3, "rss_bytes": 12_288, "oldest_age_seconds": 1}
        cases = [
            (
                collector.ProcessPolicy(warning_count=3),
                "warning",
                "process_policy_count_high",
            ),
            (
                collector.ProcessPolicy(critical_count=3),
                "critical",
                "process_policy_count_critical",
            ),
            (
                collector.ProcessPolicy(warning_rss_bytes=12_288),
                "warning",
                "process_policy_rss_high",
            ),
            (
                collector.ProcessPolicy(critical_rss_bytes=12_288),
                "critical",
                "process_policy_rss_critical",
            ),
            (collector.ProcessPolicy(critical_count=4), "ok", None),
        ]

        for policy, expected_status, expected_reason in cases:
            with self.subTest(policy=policy):
                status, reasons = collector.evaluate_process_policy(values, policy)
                self.assertEqual(status, expected_status)
                if expected_reason is None:
                    self.assertEqual(reasons, [])
                else:
                    self.assertIn(expected_reason, reasons)

    def test_v2_process_scan_truncation_is_partial_not_negative_evidence(self) -> None:
        with TemporaryDirectory() as temporary:
            proc_root = make_proc_root(Path(temporary))
            for index in range(3):
                add_process(proc_root, 100 + index, "node", 1)
            with patch.object(collector, "MAX_PROCESSES_SCANNED", 2):
                result, _samples = collector.read_processes(
                    proc_root,
                    collector.parse_config(base_config_v2(process_policies={})),
                    page_size=4096,
                    clock_ticks=100,
                )

        self.assertTrue(result["truncated"])
        self.assertEqual(result["status"], "unknown")
        self.assertIn("processes_partial", result["reasons"])

    def test_v2_wildcard_default_warning_and_local_policy_violation_critical(self) -> None:
        with TemporaryDirectory() as temporary:
            proc_root = make_proc_root(Path(temporary))
            add_process(proc_root, 10, "node", 1, socket_inode="12345")
            (proc_root / "net" / "tcp").write_text(
                TCP_HEADER + tcp_row("00000000", 4242, "12345"),
                encoding="ascii",
            )
            samples = [collector.ProcessSample(10, "node", 4096, 1)]
            unconfigured = collector.read_listeners(
                proc_root,
                collector.parse_config(base_config_v2(tcp_listener_policies=[])),
                samples,
            )
            violated = collector.read_listeners(
                proc_root,
                collector.parse_config(
                    base_config_v2(
                        tcp_listener_policies=[
                            {"port": 4242, "allowed_scopes": ["loopback"]}
                        ]
                    )
                ),
                samples,
            )

        self.assertEqual(unconfigured["status"], "warning")
        self.assertEqual(unconfigured["items"][0]["policy_status"], "not_configured")
        self.assertEqual(unconfigured["items"][0]["bind_scope"], "wildcard")
        self.assertEqual(
            unconfigured["items"][0]["external_reachability"], "not_assessed"
        )
        self.assertEqual(violated["status"], "critical")
        self.assertEqual(violated["items"][0]["policy_status"], "violated")

    def test_v2_listener_ownership_and_tcp_read_partial_are_unknown_not_critical(self) -> None:
        with TemporaryDirectory() as temporary:
            proc_root = make_proc_root(Path(temporary))
            (proc_root / "net" / "tcp").write_text(
                TCP_HEADER + tcp_row("0100007F", 4242, "unmapped"),
                encoding="ascii",
            )
            config = collector.parse_config(base_config_v2())
            ownership = collector.read_listeners(proc_root, config, [])
            (proc_root / "net" / "tcp6").unlink()
            partial_read = collector.read_listeners(proc_root, config, [])

        self.assertEqual(ownership["items"][0]["status"], "ok")
        self.assertEqual(ownership["status"], "unknown")
        self.assertIn("listeners_partial", ownership["reasons"])
        self.assertNotEqual(partial_read["status"], "critical")
        self.assertIn("listeners_partial", partial_read["reasons"])

    def test_v2_docker_unavailable_remains_unknown_and_never_makes_snapshot_critical(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary:
            proc_root = make_proc_root(Path(temporary))
            write_memory(proc_root)
            add_process(proc_root, 1, "shell", 1)
            config = collector.parse_config(
                base_config_v2(
                    process_policies={},
                    docker={"enabled": True, "container_labels": {}},
                )
            )
            snapshot = collector.collect_snapshot(
                config,
                proc_root=proc_root,
                statvfs=os.statvfs,
                docker_runner=lambda: (_ for _ in ()).throw(PermissionError()),
                cpu_count=4,
                page_size=4096,
                clock_ticks=100,
                sleep=lambda _seconds: None,
                monotonic=sequence_clock(1, 1.01, 1.11, 1.12),
            )

        self.assertEqual(snapshot["docker"]["status"], "unknown")
        self.assertIn("docker_unavailable", snapshot["docker"]["reasons"])
        self.assertNotEqual(snapshot["status"], "critical")
        self.assertIn("docker_unavailable", snapshot["reasons"])

    def test_checked_in_v2_example_is_valid_and_contains_only_synthetic_values(self) -> None:
        example_path = SCRIPT.with_name("host-observability.example.json")
        payload = json.loads(example_path.read_text(encoding="utf-8"))

        config = collector.parse_config(payload)

        self.assertEqual(config.schema_version, 2)
        self.assertEqual(config.expected_listeners[0].port, 4242)
        self.assertTrue(all("example" in path.label.lower() for path in config.filesystems))

    def test_config_v1_fallback_and_v2_policies_are_both_accepted(self) -> None:
        legacy = collector.parse_config(base_config())
        evolved = collector.parse_config(base_config_v2())

        self.assertEqual(legacy.schema_version, 1)
        self.assertEqual(legacy.process_policies, {})
        self.assertEqual(evolved.schema_version, 2)
        self.assertEqual(evolved.swap_io_sample.duration_ms, 100)
        self.assertEqual(
            evolved.expected_listeners[0].scopes,
            frozenset({"loopback", "tailscale"}),
        )
        policy = evolved.process_policies["example-worker"]
        self.assertEqual(policy.critical_count, 12)
        self.assertEqual(policy.critical_rss_bytes, 2_147_483_648)
        self.assertEqual(evolved.process_labels["example-worker"], "Example worker")
        high_swap_warning = collector.parse_config(
            base_config_v2(thresholds={"swap_used_warning_percent": 90})
        )
        self.assertEqual(high_swap_warning.thresholds.swap_used_warning_percent, 90)

    def test_config_versions_fail_closed_on_mixed_unknown_or_invalid_fields(self) -> None:
        invalid = [
            base_config(schema_version=3),
            base_config(schema_version=True),
            {**base_config(), "process_policies": {}},
            {**base_config_v2(), "process_labels": {}},
            {
                **base_config_v2(),
                "thresholds": {"process_group_critical_count": 10},
            },
            {
                **base_config_v2(),
                "tcp_listener_policies": [
                    {"port": 4242, "allowed_scopes": ["loopback"], "firewall": "closed"}
                ],
            },
            {
                **base_config_v2(),
                "process_policies": {"worker": {"label": "Only a label"}},
            },
            {
                **base_config_v2(),
                "process_policies": {
                    "worker": {"warning_count": 20, "critical_count": 10}
                },
            },
            {
                **base_config_v2(),
                "process_policies": {"worker": {"critical_count": 4097}},
            },
            {
                **base_config_v2(),
                "process_policies": {"worker": {"critical_rss_bytes": 2**63}},
            },
            {
                **base_config_v2(),
                "swap_io_sample": {
                    "duration_ms": 501,
                    "warning_pages_delta": 1,
                    "critical_pages_delta": 128,
                },
            },
        ]
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(
                collector.CollectorConfigError
            ):
                collector.parse_config(payload)

    def test_config_v2_process_policy_limit_is_bounded(self) -> None:
        policies = {
            f"worker-{index}": {"critical_count": 10}
            for index in range(collector.MAX_PROCESS_LABELS + 1)
        }

        with self.assertRaises(collector.CollectorConfigError):
            collector.parse_config(base_config_v2(process_policies=policies))

    def test_nine_node_processes_are_visible_and_aggregated(self) -> None:
        with TemporaryDirectory() as temporary:
            proc_root = make_proc_root(Path(temporary))
            rss_bytes = 258 * 1024 * 1024
            rss_pages = rss_bytes // 4096
            for index in range(9):
                add_process(proc_root, 100 + index, "node", rss_pages, start_ticks=100 + index)
            for index in range(3):
                add_process(proc_root, 200 + index, "bash", 1, start_ticks=200 + index)
            config = collector.parse_config(base_config())
            snapshot = collector.collect_snapshot(
                config,
                proc_root=proc_root,
                statvfs=lambda _path: statvfs_with_usage(40),
                docker_runner=lambda: collector.DockerCommandResult(0, b""),
                cpu_count=4,
                page_size=4096,
                clock_ticks=100,
            )

        self.assertEqual(len(snapshot["processes"]["top"]), 10)
        group = snapshot["processes"]["groups"][0]
        self.assertEqual(group["name"], "node")
        self.assertEqual(group["label"], "Development server")
        self.assertEqual(group["count"], 9)
        self.assertEqual(group["rss_bytes"], 9 * rss_bytes)
        self.assertEqual(snapshot["processes"]["status"], "warning")
        self.assertLess(len(json.dumps(snapshot).encode()), collector.MAX_RESPONSE_BYTES)

    def test_listener_scopes_expected_and_wildcard_are_normalized(self) -> None:
        with TemporaryDirectory() as temporary:
            proc_root = make_proc_root(Path(temporary))
            add_process(proc_root, 10, "node", 100, socket_inode="12345")
            (proc_root / "net" / "tcp").write_text(
                TCP_HEADER
                + tcp_row("0100007F", 8081, "12345")
                + tcp_row("00000000", 43210, "67890"),
                encoding="ascii",
            )
            snapshot = collector.collect_snapshot(
                collector.parse_config(base_config()),
                proc_root=proc_root,
                statvfs=lambda _path: statvfs_with_usage(40),
                cpu_count=4,
                page_size=4096,
                clock_ticks=100,
            )

        listeners = snapshot["listeners"]
        self.assertEqual(listeners["status"], "critical")
        self.assertEqual(listeners["items"][0]["address_scope"], "loopback")
        self.assertTrue(listeners["items"][0]["expected"])
        self.assertEqual(listeners["items"][0]["process_name"], "node")
        self.assertEqual(listeners["items"][1]["address_scope"], "wildcard")
        serialized = json.dumps(snapshot)
        self.assertNotIn("127.0.0.1", serialized)
        self.assertNotIn("0.0.0.0", serialized)
        self.assertNotIn("12345", serialized)

    def test_partial_proc_and_disappearing_pid_are_reported_without_failure(self) -> None:
        with TemporaryDirectory() as temporary:
            proc_root = Path(temporary) / "proc"
            proc_root.mkdir()
            (proc_root / "loadavg").write_text("0.1 0.2 0.3 1/1 1\n", encoding="ascii")
            (proc_root / "uptime").write_text("100.0 0.0\n", encoding="ascii")
            add_process(proc_root, 1, "shell", 10)
            (proc_root / "2").mkdir()
            snapshot = collector.collect_snapshot(
                collector.parse_config(base_config(filesystems=[])),
                proc_root=proc_root,
                statvfs=os.statvfs,
                cpu_count=1,
                page_size=4096,
                clock_ticks=100,
            )

        self.assertEqual(snapshot["memory"]["status"], "unknown")
        self.assertEqual(snapshot["listeners"]["status"], "unknown")
        self.assertEqual(snapshot["processes"]["status"], "ok")
        self.assertEqual(snapshot["processes"]["skipped"], 1)
        self.assertEqual(snapshot["filesystems"]["status"], "unknown")
        self.assertNotEqual(snapshot["status"], "ok")

    def test_inaccessible_process_marks_process_component_unknown(self) -> None:
        with TemporaryDirectory() as temporary:
            proc_root = make_proc_root(Path(temporary))
            add_process(proc_root, 1, "shell", 10)
            add_process(proc_root, 2, "private", 20)
            (proc_root / "2" / "stat").chmod(0)
            result, _samples = collector.read_processes(
                proc_root,
                collector.parse_config(base_config()),
                page_size=4096,
                clock_ticks=100,
            )
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["inaccessible"], 1)
        self.assertIn("processes_partial", result["reasons"])

    def test_filesystem_failure_is_isolated_and_path_is_not_returned(self) -> None:
        payload = base_config(
            filesystems=[
                {"label": "Healthy", "path": "/private/a"},
                {"label": "Missing", "path": "/private/b"},
            ]
        )

        def fake_statvfs(path: str):
            if path.endswith("b"):
                raise FileNotFoundError
            return statvfs_with_usage(50)

        result = collector.read_filesystems(collector.parse_config(payload), fake_statvfs)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["items"][0]["status"], "ok")
        self.assertEqual(result["items"][1]["status"], "unknown")
        self.assertIn("filesystem_unavailable", result["reasons"])
        self.assertNotIn("/private", json.dumps(result))

    def test_filesystem_incoherent_counters_fail_closed_and_reasons_propagate(self) -> None:
        incoherent = os.statvfs_result((4096, 4096, 100, 110, 110, 1, 1, 1, 0, 255))
        config = collector.parse_config(base_config())
        result = collector.read_filesystems(config, lambda _path: incoherent)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["items"][0]["status"], "unknown")
        self.assertEqual(result["reasons"], ["filesystem_unavailable"])

    def test_filesystem_severity_and_reason_propagate_to_snapshot(self) -> None:
        with TemporaryDirectory() as temporary:
            proc_root = make_proc_root(Path(temporary))
            add_process(proc_root, 1, "shell", 10)
            snapshot = collector.collect_snapshot(
                collector.parse_config(base_config()),
                proc_root=proc_root,
                statvfs=lambda _path: statvfs_with_usage(95),
                cpu_count=4,
                page_size=4096,
                clock_ticks=100,
            )
        self.assertEqual(snapshot["filesystems"]["status"], "critical")
        self.assertIn("filesystem_used_critical", snapshot["filesystems"]["reasons"])
        self.assertEqual(snapshot["status"], "critical")
        self.assertIn("filesystem_used_critical", snapshot["reasons"])

    def test_docker_failures_are_unknown_and_never_expose_stderr(self) -> None:
        config = collector.parse_config(
            base_config(
                docker={
                    "enabled": True,
                    "container_labels": {"private-backend-name": "Backend"},
                }
            )
        ).docker
        cases = [
            lambda: (_ for _ in ()).throw(FileNotFoundError()),
            lambda: (_ for _ in ()).throw(subprocess.TimeoutExpired([], 2)),
            lambda: collector.DockerCommandResult(1, b""),
            lambda: collector.DockerCommandResult(0, b"x", excessive=True),
            lambda: collector.DockerCommandResult(0, b"\xff\xfe"),
            lambda: collector.DockerCommandResult(0, b"malformed-without-tab\n"),
        ]
        for runner in cases:
            with self.subTest(runner=runner):
                result = collector.read_docker(config, runner)
                self.assertEqual(result["status"], "unknown")
                self.assertFalse(result["available"])
                self.assertNotIn("secret", json.dumps(result))

    def test_docker_returns_only_configured_labels_and_normalized_state(self) -> None:
        config = collector.parse_config(
            base_config(
                docker={
                    "enabled": True,
                    "container_labels": {"private-backend-name": "Backend"},
                }
            )
        ).docker
        output = (
            b"private-backend-name\tUp 2 hours (unhealthy)\n"
            b"unlisted-private-name\tExited (1) 2 hours ago\n"
        )
        result = collector.read_docker(
            config, lambda: collector.DockerCommandResult(0, output)
        )
        serialized = json.dumps(result)
        self.assertEqual(result["status"], "critical")
        self.assertEqual(result["problematic"][0]["label"], "Backend")
        self.assertEqual(result["unmapped_problematic_count"], 1)
        self.assertNotIn("private-backend-name", serialized)
        self.assertNotIn("unlisted-private-name", serialized)
        self.assertNotIn("2 hours", serialized)

    def test_docker_command_is_fixed_bounded_and_discards_stderr(self) -> None:
        completed = collector.DockerCommandResult(0, b"")
        with patch.object(collector, "run_bounded_process", return_value=completed) as run:
            self.assertIs(collector.default_docker_runner(), completed)
        run.assert_called_once_with(
            [
                "/usr/bin/docker",
                "ps",
                "-a",
                "--format",
                "{{.Names}}\t{{.Status}}",
            ],
            timeout_seconds=2,
            max_output_bytes=collector.MAX_DOCKER_OUTPUT_BYTES,
        )

    def test_process_output_is_bounded_during_streaming(self) -> None:
        result = collector.run_bounded_process(
            [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'x' * 100000)"],
            timeout_seconds=2,
            max_output_bytes=1024,
        )
        self.assertTrue(result.excessive)
        self.assertLessEqual(len(result.stdout), 1025)

    def test_process_timeout_covers_lifecycle_after_stdout_eof(self) -> None:
        with TemporaryDirectory() as temporary:
            pid_path = Path(temporary) / "producer.pid"
            program = (
                "import os,time,pathlib; "
                f"pathlib.Path({str(pid_path)!r}).write_text(str(os.getpid())); "
                "os.close(1); time.sleep(1)"
            )
            started = time.monotonic()
            with self.assertRaises(subprocess.TimeoutExpired):
                collector.run_bounded_process(
                    [sys.executable, "-c", program],
                    timeout_seconds=0.1,
                    max_output_bytes=1024,
                )
            elapsed = time.monotonic() - started
            producer_pid = int(pid_path.read_text())
            with self.assertRaises(ChildProcessError):
                os.waitpid(producer_pid, os.WNOHANG)
        self.assertLess(elapsed, 0.5)

    def test_docker_failure_does_not_hide_other_components(self) -> None:
        with TemporaryDirectory() as temporary:
            proc_root = make_proc_root(Path(temporary))
            add_process(proc_root, 1, "shell", 10)
            config = collector.parse_config(
                base_config(docker={"enabled": True, "container_labels": {}})
            )
            snapshot = collector.collect_snapshot(
                config,
                proc_root=proc_root,
                statvfs=lambda _path: statvfs_with_usage(40),
                docker_runner=lambda: (_ for _ in ()).throw(PermissionError()),
                cpu_count=4,
                page_size=4096,
                clock_ticks=100,
            )

        self.assertEqual(snapshot["docker"]["status"], "unknown")
        self.assertEqual(snapshot["memory"]["status"], "ok")
        self.assertEqual(snapshot["filesystems"]["status"], "ok")
        self.assertEqual(snapshot["processes"]["status"], "ok")

    def test_listener_output_is_capped(self) -> None:
        with TemporaryDirectory() as temporary:
            proc_root = make_proc_root(Path(temporary))
            rows = TCP_HEADER + "".join(
                tcp_row("0100007F", 10000 + index, str(50000 + index))
                for index in range(60)
            )
            (proc_root / "net" / "tcp").write_text(rows, encoding="ascii")
            result = collector.read_listeners(
                proc_root, collector.parse_config(base_config()), []
            )
        self.assertEqual(len(result["items"]), collector.MAX_LISTENERS)
        self.assertTrue(result["truncated"])

    def test_missing_tcp6_marks_listener_scan_partial(self) -> None:
        with TemporaryDirectory() as temporary:
            proc_root = make_proc_root(Path(temporary))
            (proc_root / "net" / "tcp6").unlink()
            result = collector.read_listeners(
                proc_root, collector.parse_config(base_config()), []
            )
        self.assertEqual(result["status"], "unknown")
        self.assertIn("listeners_partial", result["reasons"])

    def test_empty_or_malformed_tcp_views_are_partial(self) -> None:
        with TemporaryDirectory() as temporary:
            proc_root = make_proc_root(Path(temporary))
            cases = [
                ("", ""),
                (TCP_HEADER + "not-a-proc-row\n", TCP_HEADER),
                ("invalid header\n", TCP_HEADER),
            ]
            for tcp, tcp6 in cases:
                (proc_root / "net" / "tcp").write_text(tcp, encoding="ascii")
                (proc_root / "net" / "tcp6").write_text(tcp6, encoding="ascii")
                with self.subTest(tcp=tcp[:20], tcp6=tcp6[:20]):
                    result = collector.read_listeners(
                        proc_root, collector.parse_config(base_config()), []
                    )
                    self.assertEqual(result["status"], "unknown")
                    self.assertIn("listeners_partial", result["reasons"])

    def test_listener_scan_beyond_cap_is_partial_and_never_ok(self) -> None:
        with TemporaryDirectory() as temporary:
            proc_root = make_proc_root(Path(temporary))
            rows = TCP_HEADER + tcp_row("0100007F", 8081, "12345") * (
                collector.MAX_LISTENERS_SCANNED + 1
            )
            (proc_root / "net" / "tcp").write_text(rows, encoding="ascii")
            result = collector.read_listeners(
                proc_root, collector.parse_config(base_config()), []
            )
        self.assertTrue(result["truncated"])
        self.assertEqual(result["status"], "unknown")
        self.assertIn("listeners_partial", result["reasons"])

    def test_config_is_strict_bounded_and_private_on_disk(self) -> None:
        invalid = [
            {**base_config(), "unknown": True},
            base_config(filesystems=[{"label": "Disk", "path": "relative"}]),
            base_config(expected_tcp_listeners=[{"port": 22, "scopes": ["raw-ip"]}]),
            base_config(process_labels={"node": "../../unsafe"}),
            base_config(filesystems=[{"label": f"Disk {index}", "path": "/"} for index in range(17)]),
        ]
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(collector.CollectorConfigError):
                collector.parse_config(payload)

        with TemporaryDirectory() as temporary:
            config_path = Path(temporary) / "config.json"
            config_path.write_text(json.dumps(base_config()), encoding="utf-8")
            for mode in (0o400, 0o644, 0o700):
                config_path.chmod(mode)
                with self.subTest(mode=oct(mode)), self.assertRaises(
                    collector.CollectorConfigError
                ):
                    collector.load_config(config_path)
            config_path.chmod(0o600)
            loaded = collector.load_config(config_path)
            self.assertEqual(loaded.filesystems[0].label, "System disk")
            symlink = Path(temporary) / "config-link.json"
            symlink.symlink_to(config_path)
            with self.assertRaises(collector.CollectorConfigError):
                collector.load_config(symlink)

            real_parent = Path(temporary) / "real-parent"
            real_parent.mkdir()
            parent_config = real_parent / "config.json"
            parent_config.write_text(json.dumps(base_config()), encoding="utf-8")
            parent_config.chmod(0o600)
            parent_link = Path(temporary) / "parent-link"
            parent_link.symlink_to(real_parent, target_is_directory=True)
            with self.assertRaises(collector.CollectorConfigError):
                collector.load_config(parent_link / "config.json")

            original_read = collector.os.read
            changed = False

            def racing_read(fd: int, size: int) -> bytes:
                nonlocal changed
                chunk = original_read(fd, size)
                if not changed:
                    changed = True
                    config_path.chmod(0o400)
                return chunk

            with patch.object(
                collector.os, "read", side_effect=racing_read
            ), self.assertRaises(collector.CollectorConfigError):
                collector.load_config(config_path)

            oversized = Path(temporary) / "oversized.json"
            oversized.write_bytes(b"x" * (collector.MAX_CONFIG_BYTES + 1))
            oversized.chmod(0o600)
            with self.assertRaises(collector.CollectorConfigError):
                collector.load_config(oversized)

    def test_address_classification_includes_tailscale_without_returning_ip(self) -> None:
        self.assertEqual(collector.address_scope("0100007F"), "loopback")
        self.assertEqual(collector.address_scope("00000000"), "wildcard")
        self.assertEqual(collector.address_scope("01004064"), "tailscale")
        self.assertEqual(collector.address_scope("00000000000000000000000001000000"), "loopback")
        address = ipaddress.IPv6Address("fd7a:115c:a1e0::1").packed
        proc_encoded = b"".join(
            address[index : index + 4][::-1] for index in range(0, 16, 4)
        ).hex().upper()
        self.assertEqual(collector.address_scope(proc_encoded), "tailscale")


if __name__ == "__main__":
    unittest.main()
