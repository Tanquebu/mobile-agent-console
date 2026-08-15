import argparse
import importlib.util
import json
import sqlite3
import time
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
    opencode_db: str | None = None,
    opencode_models_cache: str | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        output=output,
        tmux_socket_file=tmux_socket_file,
        codex_sessions_root=codex_sessions_root,
        claude_projects_root=claude_projects_root,
        claude_context_cache=claude_context_cache,
        antigravity_context_cache=antigravity_context_cache,
        opencode_db=opencode_db,
        opencode_models_cache=opencode_models_cache,
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


def make_opencode_db(
    path: Path,
    *,
    sessions: list[tuple[str, str, int]],
    messages: list[tuple[int, dict]],
) -> None:
    """DB opencode minimale per i test: sessioni e messaggi con le colonne usate."""
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE session (id TEXT PRIMARY KEY, directory TEXT, time_created INTEGER)"
    )
    cur.execute(
        "CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER, data TEXT)"
    )
    for sid, directory, created in sessions:
        cur.execute("INSERT INTO session VALUES (?, ?, ?)", (sid, directory, created))
    for index, (created, data) in enumerate(messages):
        cur.execute(
            "INSERT INTO message VALUES (?, ?, ?, ?)",
            (f"msg-{index}", sessions[0][0], created, json.dumps(data)),
        )
    conn.commit()
    conn.close()


def make_models_cache(path: Path, *, context: float = 200000.0) -> None:
    path.write_text(
        json.dumps(
            {
                "opencode": {
                    "id": "opencode",
                    "models": {
                        "deepseek-v4-flash-free": {
                            "id": "deepseek-v4-flash-free",
                            "limit": {"context": context, "output": 128000},
                        }
                    },
                }
            }
        ),
        encoding="utf-8",
    )


def assistant_message(
    *,
    provider_id: str = "opencode",
    model_id: str = "deepseek-v4-flash-free",
    input_tokens: int = 0,
    output_tokens: int = 1,
    reasoning_tokens: int = 0,
    cache_read: int = 0,
    cache_write: int = 0,
) -> dict:
    return {
        "role": "assistant",
        "providerID": provider_id,
        "modelID": model_id,
        "tokens": {
            "input": input_tokens,
            "output": output_tokens,
            "reasoning": reasoning_tokens,
            "cache": {"read": cache_read, "write": cache_write},
        },
    }


NOW_EPOCH = time.time()


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


class OpencodeContextTest(unittest.TestCase):
    def _percent(
        self,
        root: Path,
        *,
        sessions: list[tuple[str, str, int]],
        messages: list[tuple[str, int, dict]],
        context: float = 200000.0,
        pid: str = "4242",
    ) -> float | None:
        make_opencode_db(root / "opencode.db", sessions=sessions, messages=messages)
        make_models_cache(root / "models.json", context=context)
        with patch.object(collector, "process_started_at", return_value=NOW_EPOCH):
            return collector.opencode_context_percent(
                str(root / "opencode.db"),
                str(root / "models.json"),
                "/home/testuser/projects/demo",
                pid,
            )

    def _session(self, created: int, session_id: str = "ses-1") -> list[tuple[str, str, int]]:
        return [(session_id, "/home/testuser/projects/demo", created)]

    def test_uses_last_assistant_message_with_output(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            created = int(NOW_EPOCH * 1000)
            messages = [
                (created - 2000, assistant_message(output_tokens=0)),
                (
                    created - 1000,
                    assistant_message(
                        input_tokens=100000,
                        output_tokens=5000,
                        reasoning_tokens=1000,
                        cache_read=90000,
                        cache_write=1000,
                    ),
                ),
                (created, {"role": "user", "text": "domanda"}),
            ]
            percent = self._percent(root, sessions=self._session(created), messages=messages)

        # 100000 + 5000 + 1000 + 90000 + 1000 = 197000 -> 98.5%
        self.assertEqual(percent, 98.5)

    def test_takes_the_latest_of_multiple_assistant_outputs(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            created = int(NOW_EPOCH * 1000)
            messages = [
                (created - 2000, assistant_message(input_tokens=40000, output_tokens=10000)),
                (created - 1000, assistant_message(input_tokens=90000, output_tokens=10000)),
            ]
            percent = self._percent(root, sessions=self._session(created), messages=messages)

        self.assertEqual(percent, 50.0)

    def test_clamps_above_context_window(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            created = int(NOW_EPOCH * 1000)
            messages = [(created, assistant_message(input_tokens=199000, output_tokens=5000))]
            percent = self._percent(root, sessions=self._session(created), messages=messages)

        self.assertEqual(percent, 100.0)

    def test_rounds_to_one_decimal(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            created = int(NOW_EPOCH * 1000)
            messages = [(created, assistant_message(input_tokens=33333))]
            percent = self._percent(root, sessions=self._session(created), messages=messages)

        # 33334 / 200000 = 16.667% -> 16.7
        self.assertEqual(percent, 16.7)

    def test_unknown_model_returns_none(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            created = int(NOW_EPOCH * 1000)
            messages = [
                (created, assistant_message(model_id="custom-not-in-catalog", output_tokens=50))
            ]
            percent = self._percent(root, sessions=self._session(created), messages=messages)

        self.assertIsNone(percent)

    def test_conversation_born_before_pane_start_is_ignored(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = int((NOW_EPOCH - 3600) * 1000)
            messages = [(old, assistant_message(input_tokens=100000, output_tokens=50000))]
            percent = self._percent(root, sessions=self._session(old), messages=messages)

        self.assertIsNone(percent)

    def test_missing_db_models_or_messages_return_none(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertIsNone(
                collector.opencode_context_percent(
                    str(root / "missing.db"),
                    str(root / "missing.json"),
                    "/home/testuser/projects/demo",
                    "4242",
                )
            )
            make_opencode_db(root / "opencode.db", sessions=[], messages=[])
            self.assertIsNone(
                collector.opencode_context_percent(
                    str(root / "opencode.db"),
                    str(root / "missing.json"),
                    "/home/testuser/projects/demo",
                    "4242",
                )
            )
            make_models_cache(root / "models.json")
            make_opencode_db(
                root / "empty.db",
                sessions=self._session(int(NOW_EPOCH * 1000)),
                messages=[],
            )
            self.assertIsNone(
                collector.opencode_context_percent(
                    str(root / "empty.db"),
                    str(root / "models.json"),
                    "/home/testuser/projects/demo",
                    "4242",
                )
            )


class CollectOpencodeTest(unittest.TestCase):
    def test_opencode_pane_gets_provider_ask_and_context(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            created = int(NOW_EPOCH * 1000)
            make_opencode_db(
                root / "opencode.db",
                sessions=[("ses-1", "/home/testuser/projects/demo", created)],
                messages=[(created, assistant_message(input_tokens=90000, output_tokens=10000))],
            )
            make_models_cache(root / "models.json")
            args = make_args(
                opencode_db=str(root / "opencode.db"),
                opencode_models_cache=str(root / "models.json"),
            )
            with patch.object(collector, "run_tmux", return_value=[make_pane(command="opencode")]), patch.object(
                collector, "process_started_at", return_value=NOW_EPOCH
            ):
                result = collector.collect(args)

        self.assertEqual(len(result["sessions"]), 1)
        session = result["sessions"][0]
        self.assertEqual(session["provider"], "opencode")
        self.assertEqual(session["permission_state"], "ask")
        self.assertEqual(session["permission_detail"], "Chiede conferma")
        self.assertEqual(session["context_used_percent"], 50.0)

    def test_opencode_pane_without_db_still_reports_provider(self) -> None:
        args = make_args()
        with patch.object(
            collector, "run_tmux", return_value=[make_pane(command="opencode")]
        ):
            result = collector.collect(args)

        self.assertEqual(len(result["sessions"]), 1)
        session = result["sessions"][0]
        self.assertEqual(session["provider"], "opencode")
        self.assertEqual(session["permission_state"], "ask")
        self.assertEqual(session["context_used_percent"], None)

    def test_opencode_command_variant_is_also_recognized(self) -> None:
        args = make_args()
        with patch.object(
            collector, "run_tmux", return_value=[make_pane(command="opencode --auto")]
        ):
            result = collector.collect(args)

        self.assertEqual(result["sessions"][0]["provider"], "opencode")


if __name__ == "__main__":
    unittest.main()
