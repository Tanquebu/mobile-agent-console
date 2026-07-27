#!/usr/bin/env python3
"""Pubblica una vista minimale dei transcript Claude associati ai pane tmux."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.claude_transcript_normalizer import (
    atomic_json_write,
    normalize_transcript,
    utc_timestamp,
)

MAX_OUTPUT_BYTES = 1536 * 1024


def run_tmux(socket_file: str) -> list[dict[str, str]]:
    result = subprocess.run(
        [
            "tmux",
            "-S",
            socket_file,
            "list-panes",
            "-a",
            "-F",
            "#{session_id}\t#{pane_id}\t#{pane_current_command}\t#{pane_current_path}",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        return []
    panes = []
    for line in result.stdout.splitlines():
        values = line.split("\t", 3)
        if len(values) != 4:
            continue
        session_id, pane_id, command, cwd = values
        if (
            session_id.startswith("$")
            and session_id[1:].isdigit()
            and pane_id.startswith("%")
            and pane_id[1:].isdigit()
        ):
            panes.append(
                {
                    "session_id": session_id[1:],
                    "pane_id": pane_id[1:],
                    "command": command.lower(),
                    "cwd": cwd,
                }
            )
    return panes


def context_sessions(root: Path) -> dict[str, str]:
    result = {}
    if not root.is_dir():
        return result
    for path in root.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        pane = payload.get("tmux_pane") if isinstance(payload, dict) else None
        if isinstance(pane, str) and pane.removeprefix("%").isdigit():
            result[pane.removeprefix("%")] = path.stem
    return result


def claude_project_dir(root: Path, cwd: str) -> Path:
    return root / cwd.replace("/", "-")


def collect(args: argparse.Namespace) -> dict[str, object]:
    sessions = []
    cache = context_sessions(Path(args.claude_context_cache))
    projects = Path(args.claude_projects_root)
    for pane in run_tmux(args.tmux_socket_file):
        if "claude" not in pane["command"]:
            continue
        claude_session_id = cache.get(pane["pane_id"])
        if not claude_session_id:
            continue
        transcript = (
            claude_project_dir(projects, pane["cwd"]) / f"{claude_session_id}.jsonl"
        )
        if not transcript.is_file():
            continue
        normalized = normalize_transcript(transcript)
        sessions.append(
            {
                "session_id": pane["session_id"],
                "provider": "claude",
                **normalized,
            }
        )
    payload: dict[str, object] = {
        "version": 1,
        "collected_at": utc_timestamp(),
        "sessions": sessions,
    }
    while len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > MAX_OUTPUT_BYTES:
        candidates = [
            item
            for item in sessions
            if isinstance(item.get("messages"), list) and item["messages"]
        ]
        if not candidates:
            break
        largest = max(candidates, key=lambda item: len(item["messages"]))
        largest["messages"].pop(0)
        largest["truncated"] = True
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--tmux-socket-file", required=True)
    parser.add_argument("--claude-projects-root", required=True)
    parser.add_argument("--claude-context-cache", required=True)
    args = parser.parse_args()
    atomic_json_write(Path(args.output).resolve(), collect(args))


if __name__ == "__main__":
    main()
