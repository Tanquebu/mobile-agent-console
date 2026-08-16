import argparse
import importlib.util
import json
import time
import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / "claude-history-collector.py"
SPEC = importlib.util.spec_from_file_location("claude_history_collector", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)

NOW_EPOCH = time.time()


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat().replace("+00:00", "Z")


def make_args(
    *,
    output: str = "/tmp/unused-output.json",
    tmux_socket_file: str = "/fake.sock",
    claude_projects_root: str = "/fake/claude/projects",
    claude_context_cache: str = "/fake/claude/context-window-cache",
) -> argparse.Namespace:
    return argparse.Namespace(
        output=output,
        tmux_socket_file=tmux_socket_file,
        claude_projects_root=claude_projects_root,
        claude_context_cache=claude_context_cache,
    )


def make_pane(
    *,
    session_id: str = "206",
    pane_id: str = "212",
    command: str = "claude",
    cwd: str = "/home/testuser/projects/demo",
    session_created: int | None = None,
) -> dict[str, object]:
    return {
        "session_id": session_id,
        "pane_id": pane_id,
        "command": command,
        "cwd": cwd,
        "session_created": int(session_created if session_created is not None else NOW_EPOCH),
    }


class ContextSessionsTest(unittest.TestCase):
    def test_parses_uuid_and_updated_at_from_pane_reference(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "50a9db1b-uuid.json").write_text(
                json.dumps({"tmux_pane": "%212", "updated_at": _iso(NOW_EPOCH)}),
                encoding="utf-8",
            )
            result = collector.context_sessions(root)

        session_id, updated_at = result["212"]
        self.assertEqual(session_id, "50a9db1b-uuid")
        self.assertAlmostEqual(updated_at, NOW_EPOCH, places=3)

    def test_missing_or_malformed_updated_at_yields_none_timestamp(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "no-timestamp.json").write_text(
                json.dumps({"tmux_pane": "%1"}), encoding="utf-8"
            )
            (root / "bad-timestamp.json").write_text(
                json.dumps({"tmux_pane": "%2", "updated_at": "not-a-date"}), encoding="utf-8"
            )
            result = collector.context_sessions(root)

        self.assertIsNone(result["1"][1])
        self.assertIsNone(result["2"][1])

    def test_missing_root_returns_empty(self) -> None:
        self.assertEqual(collector.context_sessions(Path("/nonexistent/path")), {})

    def test_duplicate_pane_id_keeps_most_recent_updated_at(self) -> None:
        # Bug osservato: due file per lo stesso pane_id (nessuna pulizia dei
        # vecchi), uno vecchio e uno fresco. Deve vincere il più recente,
        # non il primo incontrato dall'iterazione della directory.
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            old_epoch = NOW_EPOCH - 13 * 24 * 3600
            (root / "aaa-old-session.json").write_text(
                json.dumps({"tmux_pane": "%212", "updated_at": _iso(old_epoch)}),
                encoding="utf-8",
            )
            (root / "zzz-new-session.json").write_text(
                json.dumps({"tmux_pane": "%212", "updated_at": _iso(NOW_EPOCH)}),
                encoding="utf-8",
            )
            result_alphabetical = collector.context_sessions(root)

            # Riscrive gli stessi due file in ordine inverso di creazione,
            # per non dipendere da un'eventuale coincidenza tra ordine
            # alfabetico e ordine di iterazione della directory.
            (root / "aaa-old-session.json").unlink()
            (root / "zzz-new-session.json").unlink()
            (root / "zzz-new-session.json").write_text(
                json.dumps({"tmux_pane": "%9", "updated_at": _iso(NOW_EPOCH)}),
                encoding="utf-8",
            )
            (root / "aaa-old-session.json").write_text(
                json.dumps({"tmux_pane": "%9", "updated_at": _iso(old_epoch)}),
                encoding="utf-8",
            )
            result_reversed = collector.context_sessions(root)

        self.assertEqual(result_alphabetical["212"][0], "zzz-new-session")
        self.assertEqual(result_reversed["9"][0], "zzz-new-session")

    def test_duplicate_pane_id_valid_timestamp_beats_missing_one(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "no-timestamp.json").write_text(
                json.dumps({"tmux_pane": "%7"}), encoding="utf-8"
            )
            (root / "with-timestamp.json").write_text(
                json.dumps({"tmux_pane": "%7", "updated_at": _iso(NOW_EPOCH)}),
                encoding="utf-8",
            )
            result = collector.context_sessions(root)

        self.assertEqual(result["7"][0], "with-timestamp")


class CollectStaleCacheRegressionTest(unittest.TestCase):
    """Riproduce il bug osservato: pane nuovo (mai usato), Blocchi mostrava
    una conversazione chiusa 13 giorni prima perché #{pane_id} di tmux era
    stato riassegnato dopo un riavvio del server e il file di cache del
    vecchio pane era rimasto sotto context-window-cache."""

    def test_stale_cache_entry_older_than_session_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            context_cache = root / "context-window-cache"
            context_cache.mkdir()
            projects_root = root / "projects"
            claude_project = projects_root / "-home-testuser-projects-demo"
            claude_project.mkdir(parents=True)
            stale_epoch = NOW_EPOCH - 13 * 24 * 3600
            (context_cache / "old-session-uuid.json").write_text(
                json.dumps({"tmux_pane": "%212", "updated_at": _iso(stale_epoch)}),
                encoding="utf-8",
            )
            (claude_project / "old-session-uuid.jsonl").write_text(
                json.dumps(
                    {
                        "type": "user",
                        "message": {"role": "user", "content": "conversazione vecchia"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            args = make_args(
                claude_projects_root=str(projects_root),
                claude_context_cache=str(context_cache),
            )
            with patch.object(
                collector,
                "run_tmux",
                return_value=[make_pane(session_created=int(NOW_EPOCH))],
            ):
                result = collector.collect(args)

        # Il pane è nuovo (session_created ~ ora): la corrispondenza di 13
        # giorni prima deve essere rifiutata, nessuna sessione emessa per
        # quel pane invece di una col contenuto sbagliato.
        self.assertEqual(result["sessions"], [])

    def test_fresh_cache_entry_after_session_start_is_accepted(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            context_cache = root / "context-window-cache"
            context_cache.mkdir()
            projects_root = root / "projects"
            claude_project = projects_root / "-home-testuser-projects-demo"
            claude_project.mkdir(parents=True)
            session_created = int(NOW_EPOCH) - 60
            (context_cache / "new-session-uuid.json").write_text(
                json.dumps({"tmux_pane": "%212", "updated_at": _iso(NOW_EPOCH)}),
                encoding="utf-8",
            )
            (claude_project / "new-session-uuid.jsonl").write_text(
                json.dumps(
                    {
                        "type": "user",
                        "message": {"role": "user", "content": "conversazione nuova"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            args = make_args(
                claude_projects_root=str(projects_root),
                claude_context_cache=str(context_cache),
            )
            with patch.object(
                collector, "run_tmux", return_value=[make_pane(session_created=session_created)]
            ):
                result = collector.collect(args)

        self.assertEqual(len(result["sessions"]), 1)
        self.assertEqual(result["sessions"][0]["session_id"], "206")

    def test_no_cache_entry_for_pane_yields_no_session(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            context_cache = root / "context-window-cache"
            context_cache.mkdir()
            args = make_args(claude_context_cache=str(context_cache))
            with patch.object(collector, "run_tmux", return_value=[make_pane()]):
                result = collector.collect(args)

        self.assertEqual(result["sessions"], [])

    def test_non_claude_pane_is_ignored(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            context_cache = root / "context-window-cache"
            context_cache.mkdir()
            args = make_args(claude_context_cache=str(context_cache))
            with patch.object(
                collector, "run_tmux", return_value=[make_pane(command="bash")]
            ):
                result = collector.collect(args)

        self.assertEqual(result["sessions"], [])


if __name__ == "__main__":
    unittest.main()
