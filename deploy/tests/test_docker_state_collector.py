import importlib.util
import json
import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / "docker-state-collector.py"
SPEC = importlib.util.spec_from_file_location("docker_state_collector", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
docker_state = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(docker_state)


class DockerStateCollectorTest(unittest.TestCase):
    def test_memory_units_are_parsed_and_unknown_shapes_rejected(self) -> None:
        cases = [
            ("117MiB / 3.725GiB", 117 * 1024**2),
            ("4.648MiB / 3.725GiB", int(4.648 * 1024**2)),
            ("1.5GiB / 3.725GiB", int(1.5 * 1024**3)),
            ("512B / 3.725GiB", 512),
            ("2GB / 3.725GiB", 2 * 1000**3),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(docker_state.parse_memory(value), expected)
        for value in ["", "n/a", "-- / --", "117", "117 parsec", "1e9MiB / 2GiB"]:
            with self.subTest(value=value):
                self.assertIsNone(docker_state.parse_memory(value))

    def test_state_pairs_containers_with_their_memory(self) -> None:
        outputs = {
            "ps": ["web\tUp 3 hours", "worker\tExited (0) 5 minutes ago"],
            "stats": ["web\t117MiB / 3.725GiB"],
        }

        def fake_run(arguments, *, timeout_seconds):
            return outputs["ps" if arguments[0] == "ps" else "stats"]

        with patch.object(docker_state, "run_docker", side_effect=fake_run):
            state = docker_state.collect_state()

        self.assertTrue(state["available"])
        self.assertEqual(
            state["containers"],
            [
                {"name": "web", "status": "Up 3 hours", "memory_bytes": 117 * 1024**2},
                # fermo: `docker stats` non lo riporta, e restare None è diverso
                # dall'essere a zero
                {"name": "worker", "status": "Exited (0) 5 minutes ago", "memory_bytes": None},
            ],
        )

    def test_unusable_docker_still_writes_an_explicit_unavailable_state(self) -> None:
        with patch.object(docker_state, "run_docker", return_value=None):
            state = docker_state.collect_state()

        self.assertFalse(state["available"])
        self.assertEqual(state["containers"], [])
        self.assertIn("collected_at", state)

    def test_stats_failure_does_not_discard_container_states(self) -> None:
        def fake_run(arguments, *, timeout_seconds):
            return ["web\tUp 3 hours"] if arguments[0] == "ps" else None

        with patch.object(docker_state, "run_docker", side_effect=fake_run):
            state = docker_state.collect_state()

        self.assertTrue(state["available"])
        self.assertEqual(state["containers"][0]["memory_bytes"], None)

    def test_unparsable_rows_are_dropped_without_failing_the_whole_state(self) -> None:
        outputs = {
            "ps": [
                "web\tUp 3 hours",
                "no-tab-here",
                "../escape\tUp 1 hour",
                "toolong\t" + "x" * 300,
            ],
            "stats": [],
        }

        def fake_run(arguments, *, timeout_seconds):
            return outputs["ps" if arguments[0] == "ps" else "stats"]

        with patch.object(docker_state, "run_docker", side_effect=fake_run):
            state = docker_state.collect_state()

        self.assertEqual([item["name"] for item in state["containers"]], ["web"])

    def test_state_file_is_written_atomically_and_not_world_readable(self) -> None:
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "nested" / "docker-state.json"
            docker_state.write_state(output, {"schema_version": 1, "containers": []})

            mode = stat.S_IMODE(output.stat().st_mode)
            self.assertEqual(mode, 0o600)
            self.assertEqual(json.loads(output.read_text())["schema_version"], 1)
            self.assertFalse(output.with_suffix(".part").exists())

    def test_docker_is_invoked_with_a_fixed_argv_and_a_timeout(self) -> None:
        with patch.object(docker_state.subprocess, "run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = b"web\tUp 3 hours\n"
            docker_state.run_docker(["ps", "-a"], timeout_seconds=5)

        arguments, keywords = run.call_args
        self.assertEqual(arguments[0], ["/usr/bin/docker", "ps", "-a"])
        self.assertFalse(keywords["shell"])
        self.assertEqual(keywords["timeout"], 5)

    def test_oversized_or_failed_output_is_refused(self) -> None:
        cases = [
            (1, b""),
            (0, b"x" * (docker_state.MAX_OUTPUT_BYTES + 1)),
            (0, b"\xff\xfe"),
        ]
        for returncode, stdout in cases:
            with self.subTest(returncode=returncode):
                with patch.object(docker_state.subprocess, "run") as run:
                    run.return_value.returncode = returncode
                    run.return_value.stdout = stdout
                    self.assertIsNone(docker_state.run_docker(["ps"], timeout_seconds=5))


if __name__ == "__main__":
    unittest.main()
