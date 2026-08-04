#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def run_tmux(socket_file: str) -> list[dict[str, str]]:
    result = subprocess.run(
        [
            "tmux",
            "-S",
            socket_file,
            "list-panes",
            "-a",
            "-F",
            "#{session_id}\t#{pane_id}\t#{pane_pid}\t#{pane_current_command}\t#{pane_current_path}",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        return []
    panes = []
    for line in result.stdout.splitlines():
        values = line.split("\t", 4)
        if len(values) != 5:
            continue
        session_id, pane_id, pid, command, cwd = values
        if session_id.startswith("$") and session_id[1:].isdigit() and pid.isdigit():
            panes.append(
                {
                    "session_id": session_id[1:],
                    "pane_id": pane_id.removeprefix("%"),
                    "pid": pid,
                    "command": command.lower(),
                    "cwd": cwd,
                }
            )
    return panes


def recent_json_records(path: Path, max_bytes: int = 512 * 1024) -> list[dict[str, Any]]:
    try:
        with path.open("rb") as source:
            source.seek(0, os.SEEK_END)
            size = source.tell()
            source.seek(max(0, size - max_bytes))
            raw = source.read()
    except OSError:
        return []
    if size > max_bytes:
        raw = raw.split(b"\n", 1)[-1]
    records = []
    for line in raw.splitlines():
        try:
            item = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(item, dict):
            records.append(item)
    return records


def process_tree(root_pid: str) -> list[str]:
    pending = [root_pid]
    result = []
    while pending and len(result) < 64:
        pid = pending.pop()
        if pid in result:
            continue
        result.append(pid)
        try:
            children = (
                Path("/proc") / pid / "task" / pid / "children"
            ).read_text().split()
        except OSError:
            children = []
        pending.extend(children)
    return result


def codex_transcript(pid: str, codex_root: Path) -> Path | None:
    resolved_root = codex_root.resolve()
    for process_pid in process_tree(pid):
        fd_root = Path("/proc") / process_pid / "fd"
        try:
            descriptors = list(fd_root.iterdir())
        except OSError:
            continue
        for descriptor in descriptors:
            try:
                target = descriptor.resolve()
                target.relative_to(resolved_root)
            except (OSError, ValueError):
                continue
            if target.suffix == ".jsonl":
                return target
    return None


def process_started_at(pid: str) -> float:
    try:
        stat = (Path("/proc") / pid / "stat").read_text().split()
        boot_time = next(
            float(line.split()[1])
            for line in Path("/proc/stat").read_text().splitlines()
            if line.startswith("btime ")
        )
        ticks = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
        return boot_time + int(stat[21]) / ticks
    except (OSError, ValueError, StopIteration, IndexError):
        return time.time()


def claude_project_dir(claude_root: Path, cwd: str) -> Path:
    return claude_root / cwd.replace("/", "-")


def claude_transcript(pid: str, cwd: str, claude_root: Path) -> Path | None:
    project = claude_project_dir(claude_root, cwd)
    started_at = process_started_at(pid)
    try:
        candidates = [
            path
            for path in project.glob("*.jsonl")
            if path.is_file() and path.stat().st_mtime >= started_at - 60
        ]
    except OSError:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime, default=None)


def normalize_codex(path: Path) -> tuple[str, str] | None:
    contexts = []
    for item in recent_json_records(path):
        payload = item.get("payload")
        if item.get("type") == "turn_context" and isinstance(payload, dict):
            contexts.append(payload)
    if not contexts:
        return None
    context = contexts[-1]
    approval = context.get("approval_policy")
    sandbox = context.get("sandbox_policy")
    sandbox_type = sandbox.get("type") if isinstance(sandbox, dict) else sandbox
    if sandbox_type == "danger-full-access" and approval == "never":
        return "bypass", "Accesso completo"
    if sandbox_type == "read-only":
        return "restricted", "Sola lettura"
    if sandbox_type == "workspace-write" and approval == "never":
        return "elevated", "Workspace automatico"
    if sandbox_type == "workspace-write":
        return "ask", "Chiede approvazione"
    return "unknown", "Policy Codex non riconosciuta"


def normalize_claude(path: Path) -> tuple[str, str] | None:
    modes = [
        item.get("permissionMode")
        for item in recent_json_records(path)
        if item.get("type") == "permission-mode"
        and isinstance(item.get("permissionMode"), str)
    ]
    if not modes:
        return None
    mapping = {
        "plan": ("plan", "Plan mode"),
        "bypassPermissions": ("bypass", "Bypass autorizzazioni"),
        "acceptEdits": ("accept_edits", "Accetta modifiche"),
        "dontAsk": ("dont_ask", "Non chiedere"),
        "auto": ("auto", "Auto"),
        "default": ("manual", "Permessi standard"),
        "manual": ("manual", "Permessi manuali"),
    }
    return mapping.get(modes[-1], ("unknown", "Modalità Claude non riconosciuta"))


def codex_context_percent(path: Path) -> float | None:
    for item in reversed(recent_json_records(path)):
        payload = item.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "token_count":
            continue
        info = payload.get("info")
        if not isinstance(info, dict):
            continue
        usage = info.get("last_token_usage")
        total = usage.get("total_tokens") if isinstance(usage, dict) else None
        window = info.get("model_context_window")
        if isinstance(total, (int, float)) and isinstance(window, (int, float)) and window > 0:
            return round(max(0.0, min(100.0, total / window * 100)), 1)
    return None


def _pane_context_cache(path: str | None) -> dict[str, tuple[str, float]]:
    if not path:
        return {}
    root = Path(path)
    if not root.is_dir():
        return {}
    result: dict[str, tuple[str, float]] = {}
    for cache_file in root.glob("*.json"):
        try:
            item = json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        percent = item.get("used_percent") if isinstance(item, dict) else None
        pane_id = item.get("tmux_pane") if isinstance(item, dict) else None
        if (
            isinstance(percent, (int, float))
            and isinstance(pane_id, str)
            and pane_id.removeprefix("%").isdigit()
        ):
            result[pane_id.removeprefix("%")] = (
                cache_file.stem,
                max(0.0, min(100.0, float(percent))),
            )
    return result


def claude_context_cache(path: str | None) -> dict[str, tuple[str, float]]:
    return _pane_context_cache(path)


def antigravity_context_cache(path: str | None) -> dict[str, tuple[str, float]]:
    return _pane_context_cache(path)


def collect(args: argparse.Namespace) -> dict[str, object]:
    sessions = []
    codex_root = Path(args.codex_sessions_root)
    claude_root = Path(args.claude_projects_root)
    claude_context = claude_context_cache(args.claude_context_cache)
    antigravity_context = antigravity_context_cache(args.antigravity_context_cache)
    for pane in run_tmux(args.tmux_socket_file):
        provider = None
        transcript = None
        normalized = None
        context_used_percent = None
        if "codex" in pane["command"]:
            provider = "codex"
            transcript = codex_transcript(pane["pid"], codex_root)
            if transcript is not None:
                normalized = normalize_codex(transcript)
                context_used_percent = codex_context_percent(transcript)
        elif "claude" in pane["command"]:
            provider = "claude"
            cached_context = claude_context.get(pane["pane_id"])
            if cached_context is not None:
                claude_session_id, context_used_percent = cached_context
                candidate = claude_project_dir(claude_root, pane["cwd"]) / (
                    f"{claude_session_id}.jsonl"
                )
                transcript = candidate if candidate.is_file() else None
            else:
                transcript = claude_transcript(pane["pid"], pane["cwd"], claude_root)
            if transcript is not None:
                normalized = normalize_claude(transcript)
        elif "agy" in pane["command"] or "antigravity" in pane["command"]:
            provider = "antigravity"
            cached_context = antigravity_context.get(pane["pane_id"])
            if cached_context is not None:
                _antigravity_session_id, context_used_percent = cached_context
        if provider is None:
            continue
        state, detail = normalized or ("unknown", "Livello permessi non rilevato")
        sessions.append(
            {
                "session_id": pane["session_id"],
                "provider": provider,
                "permission_state": state,
                "permission_detail": detail,
                "context_used_percent": context_used_percent,
            }
        )
    return {
        "collected_at": datetime.now(UTC).isoformat(),
        "sessions": sessions,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--tmux-socket-file", required=True)
    parser.add_argument("--codex-sessions-root", required=True)
    parser.add_argument("--claude-projects-root", required=True)
    parser.add_argument("--claude-context-cache")
    parser.add_argument("--antigravity-context-cache")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = output.with_suffix(".part")
    temporary.write_text(json.dumps(collect(args), indent=2), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(output)


if __name__ == "__main__":
    main()
