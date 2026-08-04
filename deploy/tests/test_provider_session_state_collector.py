import argparse
import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / "provider-session-state-collector.py"
SPEC = importlib.util.spec_from_file_location("provider_session_state_collector", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


def make_args(
    *,
    output: str = "/tmp/unused-output.json",
    tmux_socket_file: str = "/fake.sock",
    codex_sessions_root: str = "/fake/codex/sessions",
    claude_projects_root: str = "/fake/claude/projects",
    claude_context_cache: str | None = None,
    antigravity_context_cache: str | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        output=output,
        tmux_socket_file=tmux_socket_file,
        codex_sessions_root=codex_sessions_root,
        claude_projects_root=claude_projects_root,
        claude_context_cache=claude_context_cache,
        antigravity_context_cache=antigravity_context_cache,
    )


def make_pane(
    *,
    session_id: str = "162",
    pane_id: str = "3",
    pid: str = "4242",
    command: str = "agy",
    cwd: str = "/home/testuser/projects/demo",
) -> dict[str, str]:
    return {
        "session_id": session_id,
        "pane_id": pane_id,
        "pid": pid,
        "command": command,
        "cwd": cwd,
    }


class AntigravityContextCacheTest(unittest.TestCase):
    def test_parses_valid_cache_entries(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "session-a.json").write_text(
                json.dumps({"used_percent": 42.5, "tmux_pane": "%3"}), encoding="utf-8"
            )
            result = collector.antigravity_context_cache(str(root))

        self.assertEqual(result, {"3": ("session-a", 42.5)})

    def test_malformed_files_are_ignored(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "broken.json").write_text("not json", encoding="utf-8")
            (root / "missing-fields.json").write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
            (root / "wrong-types.json").write_text(
                json.dumps({"used_percent": "not-a-number", "tmux_pane": "%1"}),
                encoding="utf-8",
            )
            result = collector.antigravity_context_cache(str(root))

        self.assertEqual(result, {})

    def test_non_numeric_pane_id_is_ignored(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "session-b.json").write_text(
                json.dumps({"used_percent": 10.0, "tmux_pane": "not-a-pane"}),
                encoding="utf-8",
            )
            result = collector.antigravity_context_cache(str(root))

        self.assertEqual(result, {})

    def test_missing_or_no_path_returns_empty(self) -> None:
        self.assertEqual(collector.antigravity_context_cache(None), {})
        self.assertEqual(collector.antigravity_context_cache("/nonexistent/path"), {})

    def test_percent_is_clamped(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "session-c.json").write_text(
                json.dumps({"used_percent": 150, "tmux_pane": "%9"}), encoding="utf-8"
            )
            result = collector.antigravity_context_cache(str(root))

        self.assertEqual(result["9"], ("session-c", 100.0))


class CollectAntigravityTest(unittest.TestCase):
    def test_agy_pane_gets_antigravity_provider_and_context(self) -> None:
        with TemporaryDirectory() as temporary:
            context_cache_root = Path(temporary) / "antigravity-context"
            context_cache_root.mkdir()
            (context_cache_root / "a676aa0c.json").write_text(
                json.dumps({"used_percent": 37.0, "tmux_pane": "%3"}), encoding="utf-8"
            )
            args = make_args(antigravity_context_cache=str(context_cache_root))
            with patch.object(collector, "run_tmux", return_value=[make_pane()]):
                result = collector.collect(args)

        self.assertEqual(len(result["sessions"]), 1)
        session = result["sessions"][0]
        self.assertEqual(session["provider"], "antigravity")
        self.assertEqual(session["context_used_percent"], 37.0)
        self.assertEqual(session["permission_state"], "unknown")
        self.assertEqual(session["permission_detail"], "Livello permessi non rilevato")

    def test_antigravity_command_variant_is_also_recognized(self) -> None:
        args = make_args()
        with patch.object(
            collector, "run_tmux", return_value=[make_pane(command="antigravity")]
        ):
            result = collector.collect(args)

        self.assertEqual(result["sessions"][0]["provider"], "antigravity")

    def test_agy_pane_without_cached_context_has_none_percent(self) -> None:
        args = make_args()
        with patch.object(collector, "run_tmux", return_value=[make_pane()]):
            result = collector.collect(args)

        self.assertEqual(result["sessions"][0]["context_used_percent"], None)

    def test_unrecognized_command_is_dropped(self) -> None:
        args = make_args()
        with patch.object(collector, "run_tmux", return_value=[make_pane(command="bash")]):
            result = collector.collect(args)

        self.assertEqual(result["sessions"], [])


class CollectBaselineRegressionTest(unittest.TestCase):
    def test_claude_pane_without_cache_falls_back_to_transcript_lookup(self) -> None:
        args = make_args()
        with patch.object(
            collector, "run_tmux", return_value=[make_pane(command="claude", pid="1")]
        ), patch.object(collector, "claude_transcript", return_value=None):
            result = collector.collect(args)

        self.assertEqual(len(result["sessions"]), 1)
        session = result["sessions"][0]
        self.assertEqual(session["provider"], "claude")
        self.assertEqual(session["context_used_percent"], None)
        self.assertEqual(session["permission_state"], "unknown")

    def test_codex_pane_without_transcript_still_reports_provider(self) -> None:
        args = make_args()
        with patch.object(
            collector, "run_tmux", return_value=[make_pane(command="codex", pid="1")]
        ), patch.object(collector, "codex_transcript", return_value=None):
            result = collector.collect(args)

        self.assertEqual(len(result["sessions"]), 1)
        session = result["sessions"][0]
        self.assertEqual(session["provider"], "codex")
        self.assertEqual(session["context_used_percent"], None)


if __name__ == "__main__":
    unittest.main()
