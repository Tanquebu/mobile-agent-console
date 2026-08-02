import argparse
import importlib.util
import json
import os
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / "session-usage-collector.py"
SPEC = importlib.util.spec_from_file_location("session_usage_collector", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


def assistant_record(
    *,
    session_id: str = "5b84b3fa-a26f-4642-abf3-851fc35abf3f",
    request_id: str = "req-1",
    timestamp: str = "2026-08-02T09:31:00Z",
    model: str = "claude-opus-5",
    cwd: str = "/home/testuser/projects/demo-project",
    input_tokens: int = 1,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
    output_tokens: int = 1,
) -> dict:
    return {
        "type": "assistant",
        "timestamp": timestamp,
        "sessionId": session_id,
        "cwd": cwd,
        "requestId": request_id,
        "message": {
            "model": model,
            "usage": {
                "input_tokens": input_tokens,
                "cache_creation_input_tokens": cache_creation_input_tokens,
                "cache_read_input_tokens": cache_read_input_tokens,
                "output_tokens": output_tokens,
            },
        },
    }


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as target:
        for record in records:
            target.write(json.dumps(record) + "\n")


def make_args(
    root: Path,
    *,
    claude_projects_root: Path | None = None,
    codex_sessions_root: Path | None = None,
    claude_context_cache: Path | None = None,
    tmux_socket_file: str | None = None,
    lookback_minutes: int = 90,
    retention_days: int = 14,
    max_bytes: int = 4 * 1024 * 1024,
) -> argparse.Namespace:
    return argparse.Namespace(
        output=str(root / "session-usage-history.jsonl"),
        cursor_file=str(root / "cursors.json"),
        claude_projects_root=str(claude_projects_root or root / "claude" / "projects"),
        codex_sessions_root=str(codex_sessions_root or root / "codex" / "sessions"),
        claude_context_cache=str(claude_context_cache) if claude_context_cache else None,
        tmux_socket_file=tmux_socket_file,
        lookback_minutes=lookback_minutes,
        retention_days=retention_days,
        max_bytes=max_bytes,
    )


def run_once(args: argparse.Namespace, proc_root: Path | None = None) -> list[dict]:
    output = Path(args.output)
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    rows = collector.collect(args) if proc_root is None else collector.collect(args, proc_root)
    collector.append_rows(output, rows)
    collector.rotate(output, args.retention_days, args.max_bytes)
    return rows


def codex_record(
    *,
    timestamp: str = "2026-08-02T09:31:00Z",
    input_tokens: int = 22725,
    cached_input_tokens: int = 11008,
    cache_write_input_tokens: int = 0,
    output_tokens: int = 391,
    reasoning_output_tokens: int = 66,
) -> dict:
    return {
        "timestamp": timestamp,
        "payload": {
            "type": "token_count",
            "info": {
                "last_token_usage": {
                    "input_tokens": input_tokens,
                    "cached_input_tokens": cached_input_tokens,
                    "cache_write_input_tokens": cache_write_input_tokens,
                    "output_tokens": output_tokens,
                    "reasoning_output_tokens": reasoning_output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                },
                # Cumulativo dall'inizio della sessione: il collector non
                # deve mai usarlo, solo `last_token_usage`.
                "total_token_usage": {
                    "input_tokens": input_tokens * 5,
                    "cached_input_tokens": cached_input_tokens * 5,
                    "output_tokens": output_tokens * 5,
                    "total_tokens": (input_tokens + output_tokens) * 5,
                },
            },
        },
    }


def read_output_lines(args: argparse.Namespace) -> list[dict]:
    path = Path(args.output)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class SessionUsageCollectorTest(unittest.TestCase):
    def test_dedup_by_request_id_within_a_single_batch_counts_once(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript = root / "claude" / "projects" / "demo" / "5b84b3fa-a26f-4642-abf3-851fc35abf3f.jsonl"
            write_jsonl(
                transcript,
                [
                    assistant_record(request_id="req-1", input_tokens=1, output_tokens=1),
                    assistant_record(request_id="req-1", input_tokens=5, output_tokens=2),
                    assistant_record(request_id="req-1", input_tokens=9, output_tokens=4),
                ],
            )
            args = make_args(root)
            rows = run_once(args)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["turns"], 1)
        # Vince l'ultima occorrenza del lotto, non la prima né la somma.
        self.assertEqual(rows[0]["input_tokens"], 9)
        self.assertEqual(rows[0]["output_tokens"], 4)

    def test_dedup_survives_across_two_collector_runs(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript = root / "claude" / "projects" / "demo" / "5b84b3fa-a26f-4642-abf3-851fc35abf3f.jsonl"
            write_jsonl(transcript, [assistant_record(request_id="req-1", input_tokens=1)])
            args = make_args(root)
            first_rows = run_once(args)

            # La stessa richiesta ricompare in un secondo ciclo di lettura
            # (partial a cavallo di due cicli): non deve essere ricontata.
            write_jsonl(transcript, [assistant_record(request_id="req-1", input_tokens=999)])
            second_rows = run_once(args)

            write_jsonl(transcript, [assistant_record(request_id="req-2", input_tokens=3)])
            third_rows = run_once(args)

            all_rows = read_output_lines(args)

        self.assertEqual(first_rows[0]["input_tokens"], 1)
        self.assertEqual(second_rows, [])
        self.assertEqual(third_rows[0]["input_tokens"], 3)
        total_input_tokens = sum(row["input_tokens"] for row in all_rows)
        self.assertEqual(total_input_tokens, 1 + 3)

    def test_subagent_rolls_up_under_parent_session_from_path(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent_uuid = "11111111-1111-1111-1111-111111111111"
            parent_file = root / "claude" / "projects" / "demo" / f"{parent_uuid}.jsonl"
            subagent_file = (
                root
                / "claude"
                / "projects"
                / "demo"
                / parent_uuid
                / "subagents"
                / "agent-1.jsonl"
            )
            write_jsonl(
                parent_file,
                [assistant_record(session_id=parent_uuid, request_id="req-parent", input_tokens=10)],
            )
            write_jsonl(
                subagent_file,
                [
                    assistant_record(
                        session_id="22222222-2222-2222-2222-222222222222",
                        request_id="req-subagent",
                        input_tokens=500,
                    )
                ],
            )
            args = make_args(root)
            rows = run_once(args)

        by_subagent_flag = {row["is_subagent"]: row for row in rows}
        self.assertEqual(len(rows), 2)
        self.assertEqual(by_subagent_flag[False]["session_uuid"], parent_uuid)
        self.assertEqual(by_subagent_flag[False]["input_tokens"], 10)
        # Il subagent è arrotolato sotto il parent ricavato dal percorso, non
        # sotto il proprio sessionId.
        self.assertEqual(by_subagent_flag[True]["session_uuid"], parent_uuid)
        self.assertEqual(by_subagent_flag[True]["input_tokens"], 500)

    def test_origin_is_headless_without_a_live_pane(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript = root / "claude" / "projects" / "demo" / "5b84b3fa-a26f-4642-abf3-851fc35abf3f.jsonl"
            write_jsonl(transcript, [assistant_record()])
            args = make_args(root, tmux_socket_file="/nonexistent/tmux.sock")
            rows = run_once(args)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["origin"], "headless")
        self.assertNotIn("tmux_session_id", rows[0])

    def test_origin_is_mac_with_tmux_session_id_when_pane_is_live(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            session_uuid = "5b84b3fa-a26f-4642-abf3-851fc35abf3f"
            transcript = root / "claude" / "projects" / "demo" / f"{session_uuid}.jsonl"
            write_jsonl(transcript, [assistant_record(session_id=session_uuid)])

            context_cache = root / "context-window-cache"
            context_cache.mkdir(parents=True)
            (context_cache / f"{session_uuid}.json").write_text(
                json.dumps({"tmux_pane": "%5", "used_percent": 12.0}), encoding="utf-8"
            )

            args = make_args(root, claude_context_cache=context_cache, tmux_socket_file="/fake.sock")

            class FakeResult:
                returncode = 0
                stdout = "$162\t%5\t4242\tclaude\n"

            with patch.object(collector.subprocess, "run", return_value=FakeResult()):
                rows = run_once(args)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["origin"], "mac")
        self.assertEqual(rows[0]["tmux_session_id"], "162")

    def test_resumes_reading_from_the_saved_cursor_offset(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript = root / "claude" / "projects" / "demo" / "5b84b3fa-a26f-4642-abf3-851fc35abf3f.jsonl"
            write_jsonl(transcript, [assistant_record(request_id="req-1", input_tokens=1)])
            args = make_args(root)
            run_once(args)

            cursors = json.loads((root / "cursors.json").read_text(encoding="utf-8"))
            recorded_offset = cursors[str(transcript.resolve())]["offset"]
            self.assertEqual(recorded_offset, transcript.stat().st_size)

            write_jsonl(transcript, [assistant_record(request_id="req-2", input_tokens=2)])
            second_rows = run_once(args)

        # Solo la seconda richiesta è nuova: la prima non viene riletta.
        self.assertEqual(len(second_rows), 1)
        self.assertEqual(second_rows[0]["input_tokens"], 2)

    def test_cursor_is_reset_when_the_inode_no_longer_matches(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript = root / "claude" / "projects" / "demo" / "5b84b3fa-a26f-4642-abf3-851fc35abf3f.jsonl"
            write_jsonl(transcript, [assistant_record(request_id="req-1", input_tokens=7)])
            args = make_args(root)

            # Simula un cursore stantio con un inode diverso da quello reale,
            # come accadrebbe dopo una rotazione del file da parte di terzi.
            cursor_path = Path(args.cursor_file)
            cursor_path.parent.mkdir(parents=True, exist_ok=True)
            cursor_path.write_text(
                json.dumps(
                    {
                        str(transcript.resolve()): {
                            "inode": transcript.stat().st_ino + 999999,
                            "offset": transcript.stat().st_size,
                            "recent_request_ids": ["req-1"],
                        }
                    }
                ),
                encoding="utf-8",
            )

            rows = run_once(args)

        # L'inode non combacia: il file viene riletto per intero invece di
        # essere considerato già completamente consumato.
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["input_tokens"], 7)

    def test_cursor_is_reset_when_the_file_shrinks(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript = root / "claude" / "projects" / "demo" / "5b84b3fa-a26f-4642-abf3-851fc35abf3f.jsonl"
            write_jsonl(
                transcript,
                [assistant_record(request_id="req-1", input_tokens=1) for _ in range(20)],
            )
            args = make_args(root)
            run_once(args)

            # Il file viene troncato (stesso inode, dimensione crollata sotto
            # l'offset registrato) e poi riscritto con un contenuto nuovo.
            os.truncate(transcript, 0)
            write_jsonl(transcript, [assistant_record(request_id="req-new", input_tokens=42)])

            rows = run_once(args)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["input_tokens"], 42)

    def test_cursors_drop_paths_that_no_longer_exist(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript = root / "claude" / "projects" / "demo" / "5b84b3fa-a26f-4642-abf3-851fc35abf3f.jsonl"
            write_jsonl(transcript, [assistant_record()])
            args = make_args(root)
            run_once(args)

            transcript.unlink()
            run_once(args)

            cursors = json.loads((root / "cursors.json").read_text(encoding="utf-8"))

        self.assertEqual(cursors, {})

    def test_corrupted_cursor_entry_is_dropped_for_its_path_only(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            corrupted_uuid = "33333333-3333-3333-3333-333333333333"
            healthy_uuid = "44444444-4444-4444-4444-444444444444"
            corrupted_transcript = root / "claude" / "projects" / "demo" / f"{corrupted_uuid}.jsonl"
            healthy_transcript = root / "claude" / "projects" / "demo" / f"{healthy_uuid}.jsonl"
            write_jsonl(
                corrupted_transcript,
                [assistant_record(session_id=corrupted_uuid, request_id="req-a1", input_tokens=1)],
            )
            write_jsonl(
                healthy_transcript,
                [assistant_record(session_id=healthy_uuid, request_id="req-b1", input_tokens=2)],
            )
            args = make_args(root)
            run_once(args)

            # Corrompe a mano l'entrata del cursore per un solo percorso
            # (valore stringa invece dell'oggetto atteso), come accadrebbe
            # con un file cursori scritto a metà o modificato a mano.
            cursor_path = Path(args.cursor_file)
            cursors = json.loads(cursor_path.read_text(encoding="utf-8"))
            healthy_key = str(healthy_transcript.resolve())
            self.assertIsInstance(cursors[healthy_key], dict)
            cursors[str(corrupted_transcript.resolve())] = "CORRUPTED-NOT-A-DICT"
            cursor_path.write_text(json.dumps(cursors), encoding="utf-8")

            write_jsonl(
                corrupted_transcript,
                [assistant_record(session_id=corrupted_uuid, request_id="req-a2", input_tokens=10)],
            )
            write_jsonl(
                healthy_transcript,
                [assistant_record(session_id=healthy_uuid, request_id="req-b2", input_tokens=20)],
            )

            # Non deve sollevare AttributeError né interrompere il ciclo per
            # il percorso sano.
            second_rows = run_once(args)

        rows_by_session = {row["session_uuid"]: row for row in second_rows}
        # Il percorso con il cursore corrotto riparte da cursore vuoto:
        # l'intero file viene riletto, incluse le righe già viste in
        # precedenza, perché l'informazione di dedup andava persa insieme
        # all'entrata scartata.
        self.assertEqual(rows_by_session[corrupted_uuid]["turns"], 2)
        self.assertEqual(rows_by_session[corrupted_uuid]["input_tokens"], 1 + 10)
        # Il percorso sano non viene toccato dalla corruzione altrove nel
        # file dei cursori: solo la riga nuova viene letta, a partire dal
        # proprio cursore salvato.
        self.assertEqual(rows_by_session[healthy_uuid]["turns"], 1)
        self.assertEqual(rows_by_session[healthy_uuid]["input_tokens"], 20)

    def test_buckets_align_to_five_minutes_and_sum_within_bucket(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript = root / "claude" / "projects" / "demo" / "5b84b3fa-a26f-4642-abf3-851fc35abf3f.jsonl"
            write_jsonl(
                transcript,
                [
                    assistant_record(request_id="req-1", timestamp="2026-08-02T09:31:00Z", input_tokens=10),
                    assistant_record(request_id="req-2", timestamp="2026-08-02T09:33:59Z", input_tokens=20),
                    assistant_record(request_id="req-3", timestamp="2026-08-02T09:36:00Z", input_tokens=5),
                ],
            )
            args = make_args(root)
            rows = run_once(args)

        rows_by_bucket = {row["bucket_start"]: row for row in rows}
        self.assertEqual(len(rows), 2)
        first_bucket = datetime(2026, 8, 2, 9, 30, tzinfo=UTC).isoformat()
        second_bucket = datetime(2026, 8, 2, 9, 35, tzinfo=UTC).isoformat()
        self.assertIn(first_bucket, rows_by_bucket)
        self.assertIn(second_bucket, rows_by_bucket)
        self.assertEqual(rows_by_bucket[first_bucket]["turns"], 2)
        self.assertEqual(rows_by_bucket[first_bucket]["input_tokens"], 30)
        self.assertEqual(rows_by_bucket[second_bucket]["turns"], 1)
        self.assertEqual(rows_by_bucket[second_bucket]["input_tokens"], 5)

    def test_codex_cached_tokens_are_a_subset_of_input_not_a_separate_bucket(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            session_uuid = "33333333-3333-3333-3333-333333333333"
            transcript = root / "codex" / "sessions" / f"rollout-2026-08-02T09-00-00-{session_uuid}.jsonl"
            write_jsonl(
                transcript,
                [
                    codex_record(
                        input_tokens=22725,
                        cached_input_tokens=11008,
                        cache_write_input_tokens=0,
                        output_tokens=391,
                        reasoning_output_tokens=66,
                    )
                ],
            )
            args = make_args(root)
            rows = run_once(args)

        self.assertEqual(len(rows), 1)
        # `cached_input_tokens` è un sottoinsieme di `input_tokens` in Codex:
        # l'input fresco è la differenza, non il valore grezzo.
        self.assertEqual(rows[0]["input_tokens"], 22725 - 11008)
        self.assertEqual(rows[0]["cache_read_input_tokens"], 11008)
        self.assertEqual(rows[0]["cache_creation_input_tokens"], 0)
        # `reasoning_output_tokens` è un sottoinsieme di `output_tokens` e non
        # va sommato a parte: deve restare 391, non 391 + 66.
        self.assertEqual(rows[0]["output_tokens"], 391)

    def test_codex_input_less_than_cached_clamps_to_zero(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            session_uuid = "44444444-4444-4444-4444-444444444444"
            transcript = root / "codex" / "sessions" / f"rollout-2026-08-02T09-00-00-{session_uuid}.jsonl"
            write_jsonl(
                transcript,
                [codex_record(input_tokens=100, cached_input_tokens=500, output_tokens=10)],
            )
            args = make_args(root)
            rows = run_once(args)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["input_tokens"], 0)
        self.assertEqual(rows[0]["cache_read_input_tokens"], 500)

    def test_origin_is_mac_for_a_codex_session_with_a_live_pane(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            session_uuid = "55555555-5555-5555-5555-555555555555"
            transcript = (
                root
                / "codex"
                / "sessions"
                / f"rollout-2026-08-02T09-00-00-{session_uuid}.jsonl"
            )
            write_jsonl(transcript, [codex_record()])

            # Nessuna cache di contesto Claude copre Codex: la mappatura passa
            # dal pid del pane, risalendo l'albero dei processi fino a un
            # descrittore aperto sul transcript, come in
            # provider-session-state-collector.py.
            proc_root = root / "proc"
            pid = "4242"
            (proc_root / pid / "task" / pid).mkdir(parents=True)
            (proc_root / pid / "task" / pid / "children").write_text("")
            (proc_root / pid / "fd").mkdir(parents=True)
            (proc_root / pid / "fd" / "3").symlink_to(transcript.resolve())

            args = make_args(root, tmux_socket_file="/fake.sock")

            class FakeResult:
                returncode = 0
                stdout = f"$162\t%5\t{pid}\tcodex\n"

            with patch.object(collector.subprocess, "run", return_value=FakeResult()):
                rows = run_once(args, proc_root=proc_root)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["origin"], "mac")
        self.assertEqual(rows[0]["tmux_session_id"], "162")

    def test_rotate_drops_rows_beyond_retention_and_keeps_recent_ones(self) -> None:
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "session-usage-history.jsonl"
            now = datetime.now(UTC)
            old_row = {
                "bucket_start": (now - timedelta(days=30)).isoformat(),
                "provider": "claude",
                "session_uuid": "old-session",
                "origin": "headless",
                "project": "demo",
                "model": "claude-opus-5",
                "is_subagent": False,
                "turns": 1,
                "input_tokens": 1,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "output_tokens": 1,
            }
            recent_row = {**old_row, "bucket_start": now.isoformat(), "session_uuid": "recent-session"}
            collector.append_rows(output, [old_row, recent_row])

            collector.rotate(output, retention_days=14, max_bytes=1)

            kept = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["session_uuid"], "recent-session")

    def test_output_never_contains_paths_pids_or_conversation_content(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            secret_prompt = "SECRET-PROMPT-CONTENT-MUST-NOT-LEAK"
            transcript = root / "claude" / "projects" / "demo" / "5b84b3fa-a26f-4642-abf3-851fc35abf3f.jsonl"
            record = assistant_record(cwd="/home/testuser/projects/demo-project")
            record["message"]["content"] = [{"type": "text", "text": secret_prompt}]
            record["pid"] = 424242
            write_jsonl(transcript, [record])
            args = make_args(root)
            run_once(args)

            serialized = Path(args.output).read_text(encoding="utf-8")

        self.assertNotIn(secret_prompt, serialized)
        self.assertNotIn(str(root), serialized)
        self.assertNotIn("/home/testuser", serialized)
        self.assertNotIn("424242", serialized)
        self.assertIn("demo-project", serialized)


if __name__ == "__main__":
    unittest.main()
