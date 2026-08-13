import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / "tmux-orphan-state-collector.py"
SPEC = importlib.util.spec_from_file_location("tmux_orphan_state_collector", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
collector = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = collector
SPEC.loader.exec_module(collector)


class TmuxOrphanStateCollectorTest(unittest.TestCase):
    def test_detects_only_scope_whose_pane_is_gone(self) -> None:
        scope_output = (
            "Id=tmux-spawn-11111111-1111-1111-1111-111111111111.scope\n"
            "Description=tmux child pane 101 launched by process 9\n"
            "ActiveEnterTimestampMonotonic=1000000\nMemoryCurrent=20\nMemoryPeak=30\n"
            "MemorySwapCurrent=4\nTasksCurrent=2\n\n"
            "Id=tmux-spawn-22222222-2222-2222-2222-222222222222.scope\n"
            "Description=tmux child pane 202 launched by process 9\n"
            "ActiveEnterTimestampMonotonic=2000000\nMemoryCurrent=40\nMemoryPeak=50\n"
            "MemorySwapCurrent=6\nTasksCurrent=3\n"
        )
        with patch.object(collector, "run_command", side_effect=["101\n", scope_output]):
            result = collector.collect_state(monotonic_seconds=12)

        self.assertTrue(result["available"])
        self.assertEqual(result["scanned_scopes"], 2)
        self.assertEqual(result["orphans"], [{
            "pane_pid": 202,
            "age_seconds": 10,
            "tasks": 3,
            "memory_bytes": 40,
            "memory_peak_bytes": 50,
            "swap_bytes": 6,
        }])

    def test_failed_source_is_unknown_not_empty_success(self) -> None:
        with patch.object(collector, "run_command", side_effect=[None, ""]):
            result = collector.collect_state(monotonic_seconds=12)
        self.assertFalse(result["available"])
        self.assertEqual(result["orphans"], [])

    def test_write_is_atomic_and_private(self) -> None:
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "nested" / "state.json"
            collector.write_state(output, {"schema_version": 1})
            self.assertEqual(json.loads(output.read_text()), {"schema_version": 1})
            self.assertEqual(os.stat(output).st_mode & 0o777, 0o600)
            self.assertFalse(output.with_suffix(".part").exists())


if __name__ == "__main__":
    unittest.main()
