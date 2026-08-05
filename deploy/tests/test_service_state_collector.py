import importlib.util
import json
import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / "service-state-collector.py"
SPEC = importlib.util.spec_from_file_location("service_state_collector", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
service_state = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(service_state)

SYSTEMD_OUTPUT = """Id=example-api.service
ActiveState=active
SubState=running
NRestarts=2
MemoryCurrent=22164000

Id=oneshot.service
ActiveState=active
SubState=exited
NRestarts=0
MemoryCurrent=[not set]
"""

PM2_OUTPUT = json.dumps(
    [
        {
            "name": "example-frontend",
            "pm2_env": {"status": "online", "restart_time": 1},
            "monit": {"memory": 34418688},
        }
    ]
)


class ServiceStateCollectorTest(unittest.TestCase):
    def test_systemd_blocks_are_split_on_blank_lines(self) -> None:
        blocks = service_state.parse_systemd_blocks(SYSTEMD_OUTPUT)

        self.assertEqual([block["Id"] for block in blocks], ["example-api.service", "oneshot.service"])
        self.assertEqual(blocks[0]["NRestarts"], "2")

    def test_unset_and_sentinel_integers_are_not_accertati(self) -> None:
        for value in ["[not set]", "", "n/a", str(2**64 - 1), "-1"]:
            with self.subTest(value=value):
                self.assertIsNone(service_state.parse_optional_integer(value))
        self.assertEqual(service_state.parse_optional_integer("0"), 0)
        self.assertEqual(service_state.parse_optional_integer("22164000"), 22164000)

    def test_raw_supervisor_status_is_kept_for_the_collector_to_classify(self) -> None:
        with patch.object(service_state, "run_command", return_value=SYSTEMD_OUTPUT):
            services = service_state.read_systemd("systemd_user", ["--user"])

        assert services is not None
        self.assertEqual(
            services[0],
            {
                "supervisor": "systemd_user",
                "name": "example-api.service",
                "status": "active:running",
                "restarts": 2,
                "memory_bytes": 22164000,
            },
        )
        # `active:exited` non viene interpretato qui: la traduzione appartiene
        # al collector, che e' il punto in cui esiste il contratto.
        self.assertEqual(services[1]["status"], "active:exited")
        self.assertIsNone(services[1]["memory_bytes"])

    def test_pm2_apps_are_reduced_to_name_status_restarts_and_memory(self) -> None:
        with patch.object(service_state, "run_command", return_value=PM2_OUTPUT):
            services = service_state.read_pm2("/opt/pm2")

        self.assertEqual(
            services,
            [
                {
                    "supervisor": "pm2",
                    "name": "example-frontend",
                    "status": "online",
                    "restarts": 1,
                    "memory_bytes": 34418688,
                }
            ],
        )

    def test_unusable_supervisor_is_none_and_never_an_empty_list(self) -> None:
        # La distinzione fra "non ha risposto" e "non ha servizi" e' l'intero
        # motivo per cui il file dichiara `supervisors`.
        with patch.object(service_state, "run_command", return_value=None):
            self.assertIsNone(service_state.read_systemd("systemd_system", []))
            self.assertIsNone(service_state.read_pm2("/opt/pm2"))
        for output in ["{}", "non json", '"stringa"']:
            with self.subTest(output=output):
                with patch.object(service_state, "run_command", return_value=output):
                    self.assertIsNone(service_state.read_pm2("/opt/pm2"))

    def test_state_declares_which_supervisors_answered(self) -> None:
        def fake_read_systemd(supervisor, extra):
            return [] if supervisor == "systemd_system" else None

        with (
            patch.object(service_state, "read_systemd", side_effect=fake_read_systemd),
            patch.object(service_state, "read_pm2", return_value=[{"supervisor": "pm2"}]),
        ):
            state = service_state.collect_state(pm2_binary="/opt/pm2")

        self.assertTrue(state["available"])
        self.assertEqual(
            state["supervisors"],
            {"systemd_system": True, "systemd_user": False, "pm2": True},
        )

    def test_pm2_absent_from_the_host_is_not_reported_as_unavailable(self) -> None:
        with patch.object(service_state, "read_systemd", return_value=[]):
            state = service_state.collect_state(pm2_binary=None)

        # Senza binario configurato pm2 non e' un supervisore muto: non esiste,
        # e non deve produrre "non accertato" per servizi che nessuno ha.
        self.assertNotIn("pm2", state["supervisors"])

    def test_no_supervisor_answering_still_writes_an_explicit_unavailable_state(self) -> None:
        with (
            patch.object(service_state, "read_systemd", return_value=None),
            patch.object(service_state, "read_pm2", return_value=None),
        ):
            state = service_state.collect_state(pm2_binary="/opt/pm2")

        self.assertFalse(state["available"])
        self.assertEqual(state["services"], [])
        self.assertIn("collected_at", state)

    def test_unparsable_rows_are_dropped_without_failing_the_whole_state(self) -> None:
        output = "Id=../escape.service\nActiveState=active\nSubState=running\n\nId=ok.service\nActiveState=active\nSubState=running\n"
        with patch.object(service_state, "run_command", return_value=output):
            services = service_state.read_systemd("systemd_system", [])

        assert services is not None
        self.assertEqual([service["name"] for service in services], ["ok.service"])

    def test_state_file_is_written_atomically_and_not_world_readable(self) -> None:
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "nested" / "service-state.json"
            service_state.write_state(output, {"schema_version": 1, "services": []})

            mode = stat.S_IMODE(output.stat().st_mode)
            self.assertEqual(mode, 0o600)
            self.assertEqual(json.loads(output.read_text())["schema_version"], 1)
            self.assertFalse(output.with_suffix(".part").exists())

    def test_supervisors_are_invoked_with_a_fixed_argv_and_a_timeout(self) -> None:
        with patch.object(service_state.subprocess, "run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = b""
            service_state.read_systemd("systemd_user", ["--user"])

        arguments, keywords = run.call_args
        self.assertEqual(
            arguments[0],
            [
                "/usr/bin/systemctl",
                "--user",
                "show",
                "*.service",
                "--property",
                "Id,ActiveState,SubState,NRestarts,MemoryCurrent",
            ],
        )
        self.assertFalse(keywords["shell"])
        self.assertEqual(keywords["timeout"], service_state.SYSTEMCTL_TIMEOUT_SECONDS)

    def test_oversized_or_failed_output_is_refused(self) -> None:
        cases = [
            (1, b""),
            (0, b"x" * (service_state.MAX_OUTPUT_BYTES + 1)),
            (0, b"\xff\xfe"),
        ]
        for returncode, stdout in cases:
            with self.subTest(returncode=returncode):
                with patch.object(service_state.subprocess, "run") as run:
                    run.return_value.returncode = returncode
                    run.return_value.stdout = stdout
                    self.assertIsNone(service_state.run_command(["/usr/bin/systemctl"], timeout_seconds=5))


if __name__ == "__main__":
    unittest.main()
