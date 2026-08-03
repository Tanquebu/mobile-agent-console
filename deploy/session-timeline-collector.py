#!/usr/bin/env python3
"""Drill-down "fase C" (BH-04, ADR 010): timeline dei turni di una sessione
in una finestra di 5 minuti, SOLO METADATI DI TURNO.

Collector one-shot attivato da socket (stesso pattern ADR 009/010 di
host-observability-collector.py e rate-limit-collector.py --stdout): systemd
lega stdin/stdout alla connessione accettata (`StandardInput=socket`,
`StandardOutput=socket`), il processo legge una singola richiesta JSON, cerca
il transcript e risponde, poi esce: nessun demone, nessuna persistenza nuova.

Confine approvato in GATE-BH-04 (addendum 03/08/2026): istanti dei turni,
modello, delta dei quattro contatori di token per turno, conteggi di
strumenti per categoria (tassonomia fissa, mai il nome grezzo), eventi di
compattazione del contesto, eventi di spawn di subagent (fatto + istante).
MAI testo di prompt/risposte/ragionamento, nomi o argomenti di strumenti,
percorsi di file. Il percorso del transcript risolto non viene mai incluso
nella risposta (ADR 010, "il boundary non si allarga").

La localizzazione dei transcript riusa lo stesso approccio di
`deploy/session-usage-collector.py` (discover_claude_files/discover_codex_files,
codex_session_uuid), adattato a una ricerca diretta per `session_uuid` invece
che per mtime recente.
"""
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

MAX_REQUEST_BYTES = 4096
MAX_SCAN_BYTES = 64 * 1024 * 1024
MAX_WINDOW_MINUTES = 30
SESSION_UUID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# Tassonomia fissa: mai il nome grezzo dello strumento nell'output, solo una
# di queste categorie interne (contratto docs/contracts/session-timeline-v1.md).
TOOL_CATEGORIES = {
    "file_read",
    "file_write",
    "exec",
    "network",
    "task_management",
    "subagent_orchestration",
    "other",
}

CLAUDE_TOOL_CATEGORY = {
    "Read": "file_read",
    "Glob": "file_read",
    "Grep": "file_read",
    "NotebookEdit": "file_write",
    "Write": "file_write",
    "Edit": "file_write",
    "Bash": "exec",
    "BashOutput": "exec",
    "KillShell": "exec",
    "WebFetch": "network",
    "WebSearch": "network",
    "TodoWrite": "task_management",
    "TaskCreate": "task_management",
    "TaskList": "task_management",
    "TaskOutput": "task_management",
    "TaskUpdate": "task_management",
    "TaskStop": "task_management",
    "ExitPlanMode": "task_management",
    "Agent": "subagent_orchestration",
    "Task": "subagent_orchestration",
    "SendMessage": "subagent_orchestration",
    "Monitor": "subagent_orchestration",
}
# I nomi che contano anche come evento di spawn di subagent (fatto + istante,
# mai il contenuto: GATE-BH-04 addendum, punto 5).
CLAUDE_SUBAGENT_SPAWN_TOOLS = {"Agent", "Task"}

CODEX_FUNCTION_CATEGORY = {
    "exec_command": "exec",
    "write_stdin": "exec",
    "run": "exec",
    "wait": "exec",
    "exec": "exec",
    "update_plan": "task_management",
    "view_image": "file_read",
    "spawn_agent": "subagent_orchestration",
    "wait_agent": "subagent_orchestration",
}
# `web_search_call`/`tool_search_call` non pubblicano un campo `name`
# categorizzabile (verificato su dati reali): il tipo di record stesso è già
# la categoria, senza bisogno di alcun nome.
CODEX_RECORD_TYPE_CATEGORY = {
    "web_search_call": "network",
    "tool_search_call": "other",
}


def parse_instant(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return instant.astimezone(UTC) if instant.tzinfo else instant.replace(tzinfo=UTC)


def _nonneg_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)) and value >= 0:
        return int(value)
    return 0


def _nonneg_int_or_none(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < 0:
        return None
    return int(value)


# ---------------------------------------------------------------------------
# Richiesta: una riga JSON letta dallo stdin legato al socket (Accept=yes).
# ---------------------------------------------------------------------------


def read_request(stream: Any, max_bytes: int = MAX_REQUEST_BYTES) -> dict[str, Any]:
    """Legge una singola riga JSON, un byte per volta.

    Una `read(n)` bloccante su uno stdin di socket atterebbe fino a `n` byte
    o EOF: il client scrive una riga breve e poi resta in attesa della
    risposta senza chiudere subito, quindi una lettura a blocco fisso
    resterebbe appesa. Si legge quindi byte per byte fino al newline o al
    tetto, accettabile per una richiesta di poche centinaia di byte.
    """
    raw = bytearray()
    while len(raw) < max_bytes:
        chunk = stream.read(1)
        if not chunk:
            break
        raw += chunk
        if chunk == b"\n":
            break
    try:
        data = json.loads(bytes(raw).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def validate_request(request: dict[str, Any]) -> tuple[str, str, datetime, datetime] | None:
    provider = request.get("provider")
    session_uuid = request.get("session_uuid")
    bucket_start = parse_instant(request.get("bucket_start"))
    bucket_end = parse_instant(request.get("bucket_end"))
    if provider not in ("claude", "codex"):
        return None
    if not isinstance(session_uuid, str) or not SESSION_UUID_RE.match(session_uuid):
        return None
    if bucket_start is None or bucket_end is None or bucket_end <= bucket_start:
        return None
    if bucket_end - bucket_start > timedelta(minutes=MAX_WINDOW_MINUTES):
        return None
    return provider, session_uuid, bucket_start, bucket_end


# ---------------------------------------------------------------------------
# Localizzazione diretta per session_uuid (non per mtime recente, a
# differenza di discover_claude_files/discover_codex_files in
# session-usage-collector.py: qui il chiamante indica esattamente quale
# sessione, quindi una ricerca mirata basta e non richiede una scansione
# periodica dell'intero albero).
# ---------------------------------------------------------------------------


def find_claude_transcript(root: Path, session_uuid: str) -> Path | None:
    if not root.is_dir():
        return None
    try:
        matches = sorted(root.glob(f"*/{session_uuid}.jsonl"))
    except OSError:
        return None
    return matches[0] if matches else None


def find_codex_transcript(root: Path, session_uuid: str) -> Path | None:
    """Cerca per nome file, come `codex_session_uuid()` in
    session-usage-collector.py: l'UUID compare nel nome del file
    (`rollout-...-<uuid>.jsonl`). Nessuna scansione di contenuto: se il nome
    non porta l'UUID il transcript è dichiarato non trovato, mai ricostruito
    con un fallback costoso su tutto l'albero.
    """
    if not root.is_dir():
        return None
    try:
        matches = sorted(root.rglob(f"*{session_uuid}*.jsonl"))
    except OSError:
        return None
    return matches[0] if matches else None


# ---------------------------------------------------------------------------
# Estrazione Claude.
# ---------------------------------------------------------------------------


def categorize_claude_tool(name: object) -> str:
    if not isinstance(name, str) or name.startswith("mcp__"):
        return "other"
    return CLAUDE_TOOL_CATEGORY.get(name, "other")


def scan_claude(
    path: Path, bucket_start: datetime, bucket_end: datetime, max_scan_bytes: int
) -> dict[str, Any]:
    turns_by_request: dict[str, dict[str, Any]] = {}
    compactions: list[dict[str, Any]] = []
    subagent_spawns: list[dict[str, Any]] = []
    tool_counts: dict[str, int] = {}
    truncated = False
    scanned = 0
    try:
        handle = path.open("rb")
    except OSError:
        return {
            "available": False,
            "unavailable_reason": "transcript_unreadable",
        }
    try:
        for raw_line in handle:
            scanned += len(raw_line)
            if scanned > max_scan_bytes:
                truncated = True
                break
            try:
                record = json.loads(raw_line.decode("utf-8", errors="ignore"))
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            timestamp = parse_instant(record.get("timestamp"))
            if timestamp is None:
                continue
            if timestamp < bucket_start:
                continue
            if timestamp >= bucket_end:
                break
            if record.get("type") == "system" and record.get("subtype") == "compact_boundary":
                meta = record.get("compactMetadata")
                meta = meta if isinstance(meta, dict) else {}
                compactions.append(
                    {
                        "timestamp": timestamp.isoformat(),
                        "pre_tokens": _nonneg_int_or_none(meta.get("preTokens")),
                        "post_tokens": _nonneg_int_or_none(meta.get("postTokens")),
                    }
                )
                continue
            if record.get("type") != "assistant":
                continue
            message = record.get("message")
            if not isinstance(message, dict):
                continue
            usage = message.get("usage")
            request_id = record.get("requestId")
            if not isinstance(usage, dict) or not isinstance(request_id, str) or not request_id:
                continue
            content = message.get("content")
            turn_tool_counts: dict[str, int] = {}
            turn_spawns: list[dict[str, Any]] = []
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    name = block.get("name")
                    if name in CLAUDE_SUBAGENT_SPAWN_TOOLS:
                        turn_tool_counts["subagent_orchestration"] = (
                            turn_tool_counts.get("subagent_orchestration", 0) + 1
                        )
                        turn_spawns.append({"timestamp": timestamp.isoformat()})
                    else:
                        category = categorize_claude_tool(name)
                        turn_tool_counts[category] = turn_tool_counts.get(category, 0) + 1
            # Dedup per requestId: le partial di streaming ripetono lo stesso
            # blocco su timestamp diversi (contratto storico budget v1);
            # l'ultima occorrenza per requestId vince, sostituendo l'intera
            # candidatura (token + conteggi tool + spawn) della precedente.
            turns_by_request[request_id] = {
                "timestamp": timestamp.isoformat(),
                "model": message.get("model") if isinstance(message.get("model"), str) else "",
                "input_tokens": _nonneg_int(usage.get("input_tokens")),
                "cache_creation_input_tokens": _nonneg_int(
                    usage.get("cache_creation_input_tokens")
                ),
                "cache_read_input_tokens": _nonneg_int(usage.get("cache_read_input_tokens")),
                "output_tokens": _nonneg_int(usage.get("output_tokens")),
                "_tool_counts": turn_tool_counts,
                "_spawns": turn_spawns,
            }
    finally:
        handle.close()

    turns = []
    for item in sorted(turns_by_request.values(), key=lambda entry: entry["timestamp"]):
        for category, count in item.pop("_tool_counts").items():
            tool_counts[category] = tool_counts.get(category, 0) + count
        subagent_spawns.extend(item.pop("_spawns"))
        turns.append(item)
    subagent_spawns.sort(key=lambda entry: entry["timestamp"])

    return {
        "available": True,
        "unavailable_reason": None,
        "turns": turns,
        "tool_counts": tool_counts,
        "compactions": compactions,
        "subagent_spawns": subagent_spawns,
        "truncated": truncated,
    }


# ---------------------------------------------------------------------------
# Estrazione Codex.
# ---------------------------------------------------------------------------


def categorize_codex_tool(record_type: str, name: object) -> str:
    if record_type in CODEX_RECORD_TYPE_CATEGORY:
        return CODEX_RECORD_TYPE_CATEGORY[record_type]
    if not isinstance(name, str):
        return "other"
    return CODEX_FUNCTION_CATEGORY.get(name, "other")


def scan_codex(
    path: Path, bucket_start: datetime, bucket_end: datetime, max_scan_bytes: int
) -> dict[str, Any]:
    turns_by_key: dict[str, dict[str, Any]] = {}
    compactions: list[dict[str, Any]] = []
    subagent_spawns: list[dict[str, Any]] = []
    tool_counts: dict[str, int] = {}
    truncated = False
    scanned = 0
    try:
        handle = path.open("rb")
    except OSError:
        return {"available": False, "unavailable_reason": "transcript_unreadable"}
    try:
        for raw_line in handle:
            scanned += len(raw_line)
            if scanned > max_scan_bytes:
                truncated = True
                break
            try:
                record = json.loads(raw_line.decode("utf-8", errors="ignore"))
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            # I record `type: "compacted"` portano `replacement_history`, testo
            # completo di turni precedenti: si scartano subito, senza mai
            # ispezionarne il payload (GATE-BH-04, nota vincolante).
            if record.get("type") == "compacted":
                continue
            timestamp = parse_instant(record.get("timestamp"))
            if timestamp is None:
                continue
            if timestamp < bucket_start:
                continue
            if timestamp >= bucket_end:
                break
            record_type = record.get("type")
            payload = record.get("payload")
            if not isinstance(payload, dict):
                continue
            payload_type = payload.get("type")

            if record_type == "event_msg" and payload_type == "context_compacted":
                # Codex non pubblica pre/post token count per la
                # compattazione (verificato su dati reali): resta n/d,
                # disponibile solo l'istante (GATE-BH-04).
                compactions.append(
                    {
                        "timestamp": timestamp.isoformat(),
                        "pre_tokens": None,
                        "post_tokens": None,
                    }
                )
                continue

            if record_type == "event_msg" and payload_type == "sub_agent_activity":
                if payload.get("kind") == "started":
                    occurred_at_ms = payload.get("occurred_at_ms")
                    if isinstance(occurred_at_ms, (int, float)) and not isinstance(
                        occurred_at_ms, bool
                    ):
                        spawn_instant = datetime.fromtimestamp(
                            occurred_at_ms / 1000, tz=UTC
                        )
                    else:
                        spawn_instant = timestamp
                    subagent_spawns.append({"timestamp": spawn_instant.isoformat()})
                continue

            if record_type == "event_msg" and payload_type == "token_count":
                info = payload.get("info")
                usage = info.get("last_token_usage") if isinstance(info, dict) else None
                if isinstance(usage, dict):
                    raw_input_tokens = _nonneg_int(usage.get("input_tokens"))
                    cached_tokens = _nonneg_int(usage.get("cached_input_tokens"))
                    cache_write_tokens = _nonneg_int(usage.get("cache_write_input_tokens"))
                    output_tokens = _nonneg_int(usage.get("output_tokens"))
                    # Stessa sottrazione di extract_codex_usage() in
                    # session-usage-collector.py: in Codex `cached_input_tokens`
                    # è un sottoinsieme di `input_tokens`, non un bucket
                    # disgiunto come in Claude (errore storico documentato in
                    # cima al protocollo dei subagent).
                    input_tokens = max(0, raw_input_tokens - cached_tokens)
                    dedup_key = (
                        f"{record.get('timestamp')}:{raw_input_tokens}:"
                        f"{cached_tokens}:{output_tokens}"
                    )
                    turns_by_key[dedup_key] = {
                        "timestamp": timestamp.isoformat(),
                        "model": info.get("model")
                        if isinstance(info.get("model"), str)
                        else "",
                        "input_tokens": input_tokens,
                        "cache_creation_input_tokens": cache_write_tokens,
                        "cache_read_input_tokens": cached_tokens,
                        "output_tokens": output_tokens,
                    }
                continue

            if record_type == "response_item" and payload_type in (
                "function_call",
                "custom_tool_call",
                "web_search_call",
                "tool_search_call",
            ):
                category = categorize_codex_tool(payload_type, payload.get("name"))
                tool_counts[category] = tool_counts.get(category, 0) + 1
                continue
    finally:
        handle.close()

    turns = sorted(turns_by_key.values(), key=lambda entry: entry["timestamp"])
    subagent_spawns.sort(key=lambda entry: entry["timestamp"])

    return {
        "available": True,
        "unavailable_reason": None,
        "turns": turns,
        "tool_counts": tool_counts,
        "compactions": compactions,
        "subagent_spawns": subagent_spawns,
        "truncated": truncated,
    }


# ---------------------------------------------------------------------------
# Ingresso.
# ---------------------------------------------------------------------------


def handle_request(
    request: dict[str, Any],
    claude_projects_root: Path,
    codex_sessions_root: Path,
    max_scan_bytes: int = MAX_SCAN_BYTES,
) -> dict[str, Any] | None:
    validated = validate_request(request)
    if validated is None:
        return None
    provider, session_uuid, bucket_start, bucket_end = validated
    if provider == "claude":
        transcript = find_claude_transcript(claude_projects_root, session_uuid)
        scanner = scan_claude
    else:
        transcript = find_codex_transcript(codex_sessions_root, session_uuid)
        scanner = scan_codex
    if transcript is None:
        return {"available": False, "unavailable_reason": "transcript_not_found"}
    return scanner(transcript, bucket_start, bucket_end, max_scan_bytes)


def main() -> None:
    import argparse
    import os

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--claude-projects-root", default=os.path.expanduser("~/.claude/projects")
    )
    parser.add_argument(
        "--codex-sessions-root", default=os.path.expanduser("~/.codex/sessions")
    )
    parser.add_argument("--max-scan-bytes", type=int, default=MAX_SCAN_BYTES)
    args = parser.parse_args()

    request = read_request(sys.stdin.buffer)
    result = handle_request(
        request,
        Path(args.claude_projects_root),
        Path(args.codex_sessions_root),
        args.max_scan_bytes,
    )
    if result is None:
        result = {"available": False, "unavailable_reason": "invalid_request"}
    sys.stdout.write(json.dumps(result))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
