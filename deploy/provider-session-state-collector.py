#!/usr/bin/env python3
import argparse
import json
import os
import sqlite3
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


def _parse_updated_at(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _pane_context_cache(path: str | None) -> dict[str, tuple[str, float, float | None]]:
    if not path:
        return {}
    root = Path(path)
    if not root.is_dir():
        return {}
    # Più file possono riferire lo stesso pane_id (nessuna pulizia dei
    # vecchi): tra i duplicati vince quello con "updated_at" più recente,
    # non il primo incontrato da Path.glob() (ordine di iterazione della
    # directory, non garantito cronologico) — altrimenti un file vecchio
    # può "vincere" per puro ordine del filesystem anche quando ne esiste
    # uno fresco valido per lo stesso pane (stesso bug corretto in
    # claude-history-collector.py/context_sessions). Un updated_at
    # assente/non parsabile ha priorità minima.
    result: dict[str, tuple[str, float, float | None]] = {}
    for cache_file in root.glob("*.json"):
        try:
            item = json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        percent = item.get("used_percent") if isinstance(item, dict) else None
        pane_id = item.get("tmux_pane") if isinstance(item, dict) else None
        if not (
            isinstance(percent, (int, float))
            and isinstance(pane_id, str)
            and pane_id.removeprefix("%").isdigit()
        ):
            continue
        pane_key = pane_id.removeprefix("%")
        updated_at = _parse_updated_at(item.get("updated_at"))
        existing = result.get(pane_key)
        if existing is not None and existing[2] is not None:
            if updated_at is None or updated_at <= existing[2]:
                continue
        result[pane_key] = (
            cache_file.stem,
            max(0.0, min(100.0, float(percent))),
            updated_at,
        )
    return result


def _context_cache_is_fresh(updated_at: float | None, process_pid: str) -> bool:
    # #{pane_id} di tmux non è stabile: viene riassegnato da capo se il
    # server tmux riparte, quindi un pane NUOVO può ricevere lo stesso id di
    # un pane VECCHIO il cui file di cache è rimasto sotto
    # ~/.claude(o antigravity)/context-window-cache (nessuna pulizia nota).
    # Senza questo controllo un pane appena aperto mostrerebbe silenziosamente
    # il context% di settimane prima (stesso bug di correlazione risolto in
    # claude-history-collector.py, qui per il badge "ctx X%"). -5s di
    # tolleranza come già in opencode_context_percent, per lo stesso motivo
    # (scrittura della cache leggermente prima che /proc/<pid>/stat sia letto).
    if updated_at is None:
        return False
    return updated_at >= process_started_at(process_pid) - 5


def claude_context_cache(path: str | None) -> dict[str, tuple[str, float, float | None]]:
    return _pane_context_cache(path)


def antigravity_context_cache(path: str | None) -> dict[str, tuple[str, float, float | None]]:
    return _pane_context_cache(path)


def _opencode_model_context_limit(models_cache: str, provider_id: str, model_id: str) -> float | None:
    """Capienza (`limit.context`) del modello OpenCode dal cache di models.dev.

    Il file è quello usato da OpenCode stesso (`~/.cache/opencode/models.json`,
    rigenerato ogni ora): `{providerID: {models: {modelID: {limit: {context}}}}}`.
    `None` se il file manca o il modello non è nel catalogo: la percentuale non
    viene esposta, come fa la TUI per i limiti sconosciuti.
    """
    if not models_cache:
        return None
    path = Path(models_cache)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    provider = data.get(provider_id) if isinstance(data, dict) else None
    models = provider.get("models") if isinstance(provider, dict) else None
    model = models.get(model_id) if isinstance(models, dict) else None
    limit = model.get("limit") if isinstance(model, dict) else None
    context = limit.get("context") if isinstance(limit, dict) else None
    if isinstance(context, (int, float)) and context > 0:
        return float(context)
    return None


def opencode_context_percent(db_path: str, models_cache: str, cwd: str, pid: str) -> float | None:
    """Percentuale di contesto usata dal pane OpenCode, come la mostra la TUI.

    Replica la finestra del widget Context di OpenCode: l'ultimo messaggio
    assistant con `tokens.output > 0`, con token pari a input + output +
    reasoning + cache read/write, diviso `limit.context` del modello usato.
    La percentuale viene dall'ultimo turno e non dai totali cumulativi della
    sessione, che non azzerano alla compattazione e sovrastimerebbero il
    contesto dopo un `/compact`. La conversazione è quella nata dopo l'avvio
    del processo del pane, come in `OpencodeService.read_history`.
    """
    db = Path(db_path)
    if not db.is_file():
        return None
    norm_dir = str(Path(cwd).resolve())
    min_ms = int((process_started_at(pid) - 5) * 1000)
    try:
        conn = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True, timeout=2.0)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        session_row = cursor.execute(
            """
            SELECT id
            FROM session
            WHERE (directory = ? OR directory = ?) AND time_created >= ?
            ORDER BY time_created ASC LIMIT 1
            """,
            (norm_dir, cwd, min_ms),
        ).fetchone()
        if session_row is None:
            conn.close()
            return None
        message = None
        for row in cursor.execute(
            """
            SELECT data
            FROM message
            WHERE session_id = ?
            ORDER BY time_created DESC
            LIMIT 1000
            """,
            (str(session_row["id"]),),
        ):
            try:
                data = json.loads(row["data"])
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict) or data.get("role") != "assistant":
                continue
            tokens = data.get("tokens")
            if not isinstance(tokens, dict) or tokens.get("output", 0) <= 0:
                continue
            message = data
            break
        conn.close()
    except sqlite3.Error:
        return None
    if message is None:
        return None
    tokens = message.get("tokens")
    cache = tokens.get("cache") if isinstance(tokens, dict) else None
    if not isinstance(cache, dict):
        cache = {}
    used = sum(float(tokens.get(key, 0) or 0) for key in ("input", "output", "reasoning"))
    used += float(cache.get("read", 0) or 0) + float(cache.get("write", 0) or 0)
    if used <= 0:
        return None
    limit = _opencode_model_context_limit(
        models_cache,
        str(message.get("providerID", "")),
        str(message.get("modelID", "")),
    )
    if limit is None:
        return None
    return round(max(0.0, min(100.0, used / limit * 100)), 1)


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
            if cached_context is not None and _context_cache_is_fresh(cached_context[2], pane["pid"]):
                claude_session_id, context_used_percent, _updated_at = cached_context
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
            if cached_context is not None and _context_cache_is_fresh(cached_context[2], pane["pid"]):
                _antigravity_session_id, context_used_percent, _updated_at = cached_context
        elif "opencode" in pane["command"]:
            # La TUI OpenCode non espone un indicatore di modalità permessi
            # nella status bar: il profilo è conservativo e il classificatore
            # backend restituisce sempre "ask". Si emette lo stesso valore
            # per non degradare lo stato permessi già mostrato (main.py
            # lascia prevalere il collector quando l'entry esiste).
            provider = "opencode"
            normalized = ("ask", "Chiede conferma")
            if args.opencode_db:
                context_used_percent = opencode_context_percent(
                    args.opencode_db,
                    args.opencode_models_cache,
                    pane["cwd"],
                    pane["pid"],
                )
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
    parser.add_argument("--opencode-db")
    parser.add_argument("--opencode-models-cache")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = output.with_suffix(".part")
    temporary.write_text(json.dumps(collect(args), indent=2), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(output)


if __name__ == "__main__":
    main()
