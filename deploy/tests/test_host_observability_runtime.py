import importlib.util
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / "host-observability-runtime.py"
SPEC = importlib.util.spec_from_file_location("host_observability_runtime", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)
SYNTHETIC_ROOTLESS_UID = 2_000_001


class HostObservabilityRuntimeTest(unittest.TestCase):
    def test_parse_rootless_uid(self) -> None:
        self.assertIsNone(runtime.parse_rootless_uid(None))
        self.assertIsNone(runtime.parse_rootless_uid(""))
        value = str(SYNTHETIC_ROOTLESS_UID)
        self.assertEqual(runtime.parse_rootless_uid(value), SYNTHETIC_ROOTLESS_UID)
        for invalid in ("0", "-1", "1.5", "uid"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                runtime.parse_rootless_uid(invalid)

    def test_prepare_runtime_sets_private_mode(self) -> None:
        with TemporaryDirectory() as temporary, patch.object(
            runtime.shutil, "which", return_value="/usr/bin/setfacl"
        ), patch.object(runtime.subprocess, "run"):
            directory = Path(temporary) / "runtime"
            runtime.prepare_runtime(directory, None)
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)

    def test_prepare_runtime_adds_narrow_rootless_acl(self) -> None:
        expected_acl = (
            "g::---,d:g::---,u:10001:r-x,d:u:10001:rw-,"
            f"u:{SYNTHETIC_ROOTLESS_UID}:r-x,d:u:{SYNTHETIC_ROOTLESS_UID}:rw-"
        )
        with TemporaryDirectory() as temporary, patch.object(
            runtime.shutil, "which", return_value="/usr/bin/setfacl"
        ), patch.object(runtime.subprocess, "run") as run:
            directory = Path(temporary) / "runtime"
            runtime.prepare_runtime(directory, SYNTHETIC_ROOTLESS_UID)
            self.assertEqual(run.call_count, 2)
            run.assert_any_call(
                ["/usr/bin/setfacl", "-b", "-k", str(directory)],
                check=True,
                shell=False,
                timeout=5,
            )
            run.assert_any_call(
                [
                    "/usr/bin/setfacl",
                    "-m",
                    expected_acl,
                    str(directory),
                ],
                check=True,
                shell=False,
                timeout=5,
            )


if __name__ == "__main__":
    unittest.main()
