import importlib.util
import io
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / "agy-statusline.py"
SPEC = importlib.util.spec_from_file_location("agy_statusline", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
statusline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(statusline)


def real_payload(**overrides) -> dict:
    payload = {
        "cwd": "/home/testuser/projects/demo",
        "session_id": "a676aa0c-7042-4d81-b2b8-9c5d934bad83",
        "model": {"id": "gemini-x", "display_name": "Gemini X"},
        "context_window": {
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "context_window_size": 250000,
            "used_percentage": 42.5,
            "remaining_percentage": 57.5,
            "current_usage": None,
        },
        "quota": {
            "3p-5h": {
                "remaining_fraction": 0.59,
                "reset_time": "2026-08-04T21:00:00Z",
                "reset_in_seconds": 123,
            }
        },
        "agent_state": "idle",
    }
    payload.update(overrides)
    return payload


class ContextUsedPercentTest(unittest.TestCase):
    def test_valid_payload_returns_percent(self) -> None:
        self.assertEqual(statusline.context_used_percent(real_payload()), 42.5)

    def test_missing_context_window_returns_none(self) -> None:
        self.assertIsNone(statusline.context_used_percent({}))

    def test_malformed_used_percentage_returns_none(self) -> None:
        cases = [
            {"context_window": {"used_percentage": "not-a-number"}},
            {"context_window": {"used_percentage": None}},
            {"context_window": {}},
            {"context_window": "not-a-dict"},
            {"context_window": {"used_percentage": True}},
        ]
        for data in cases:
            with self.subTest(data=data):
                self.assertIsNone(statusline.context_used_percent(data))

    def test_out_of_range_is_clamped(self) -> None:
        self.assertEqual(
            statusline.context_used_percent({"context_window": {"used_percentage": 150}}),
            100.0,
        )
        self.assertEqual(
            statusline.context_used_percent({"context_window": {"used_percentage": -5}}),
            0.0,
        )


class WriteContextCacheTest(unittest.TestCase):
    def test_writes_expected_file_when_tmux_pane_set(self) -> None:
        with TemporaryDirectory() as temporary:
            cache_dir = Path(temporary) / "context-window-cache"
            with patch.object(statusline, "ANTIGRAVITY_CONTEXT_CACHE_PATH", cache_dir), \
                patch.dict(os.environ, {"TMUX_PANE": "%7"}):
                statusline.write_context_cache("a676aa0c-7042-4d81-b2b8-9c5d934bad83", 42.5)

            target = cache_dir / "a676aa0c-7042-4d81-b2b8-9c5d934bad83.json"
            self.assertTrue(target.is_file())
            mode = target.stat().st_mode & 0o777
            self.assertEqual(mode, 0o600)
            content = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(content["used_percent"], 42.5)
            self.assertEqual(content["tmux_pane"], "%7")
            self.assertIn("updated_at", content)
            # Nessun file temporaneo residuo dopo la replace atomica.
            self.assertEqual(list(cache_dir.glob("*.part")), [])

    def test_does_not_write_without_tmux_pane(self) -> None:
        with TemporaryDirectory() as temporary:
            cache_dir = Path(temporary) / "context-window-cache"
            with patch.object(statusline, "ANTIGRAVITY_CONTEXT_CACHE_PATH", cache_dir), \
                patch.dict(os.environ, {}, clear=False):
                os.environ.pop("TMUX_PANE", None)
                statusline.write_context_cache("a676aa0c-7042-4d81-b2b8-9c5d934bad83", 10.0)

            self.assertFalse(cache_dir.exists())

    def test_does_not_write_with_invalid_session_id(self) -> None:
        with TemporaryDirectory() as temporary:
            cache_dir = Path(temporary) / "context-window-cache"
            with patch.object(statusline, "ANTIGRAVITY_CONTEXT_CACHE_PATH", cache_dir), \
                patch.dict(os.environ, {"TMUX_PANE": "%7"}):
                statusline.write_context_cache("../../etc/passwd", 10.0)
                statusline.write_context_cache("has spaces", 10.0)
                statusline.write_context_cache("x" * 129, 10.0)

            self.assertEqual(list(cache_dir.glob("*.json")) if cache_dir.exists() else [], [])


class MainEndToEndTest(unittest.TestCase):
    def test_context_cache_and_rate_limit_injection_coexist(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            context_cache_dir = root / "context-window-cache"
            rate_limits_path = root / "mobile-agent-console" / "provider-rate-limits.json"
            rate_limits_path.parent.mkdir(parents=True)

            payload = real_payload()
            env = {
                "MAC_ANTIGRAVITY_CONTEXT_CACHE_PATH": str(context_cache_dir),
                "MAC_PROVIDER_RATE_LIMITS_PATH": str(rate_limits_path),
                "TMUX_PANE": "%3",
            }
            with patch.object(statusline, "ANTIGRAVITY_CONTEXT_CACHE_PATH", context_cache_dir), \
                patch.object(statusline, "RATE_LIMITS_PATH", rate_limits_path), \
                patch.dict(os.environ, env), \
                patch("sys.stdin", io.StringIO(json.dumps(payload))), \
                patch("sys.stdout", new_callable=io.StringIO) as stdout:
                statusline.main()

            printed = stdout.getvalue().strip()
            self.assertIn("Gemini X", printed)

            context_file = context_cache_dir / f"{payload['session_id']}.json"
            self.assertTrue(context_file.is_file())
            context_content = json.loads(context_file.read_text(encoding="utf-8"))
            self.assertEqual(context_content["used_percent"], 42.5)
            self.assertEqual(context_content["tmux_pane"], "%3")

            self.assertTrue(rate_limits_path.is_file())
            rate_limits_content = json.loads(rate_limits_path.read_text(encoding="utf-8"))
            providers = {p["provider"]: p for p in rate_limits_content["providers"]}
            self.assertIn("antigravity", providers)
            self.assertTrue(providers["antigravity"]["available"])

    def test_main_does_not_crash_on_empty_stdin(self) -> None:
        with patch("sys.stdin", io.StringIO("")), \
            patch("sys.stdout", new_callable=io.StringIO) as stdout:
            statusline.main()
        self.assertEqual(stdout.getvalue().strip(), "…")


if __name__ == "__main__":
    unittest.main()
