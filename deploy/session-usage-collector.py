#!/usr/bin/env python3
"""Attribuisce il consumo di token per sessione (ADR 010, contratto v1).

Scopre i transcript per tempo di modifica, non a partire dai pane tmux: è la
scelta che rende osservabile il consumo delle sessioni headless, che oggi
nessun collector vede. La lettura è incrementale con un cursore per percorso,
inode e offset perché un transcript può pesare decine di megabyte e una
rilettura integrale a ogni ciclo sarebbe insostenibile.
"""
import argparse
import json
import os
import re
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

DEFAULT_LOOKBACK_MINUTES = 90
DEFAULT_RETENTION_DAYS = 14
DEFAULT_MAX_BYTES = 4 * 1024 * 1024
# Quanti requestId recenti tenere nel cursore per riconoscere le ripetizioni
# fra un ciclo e il successivo (vedi `dedup_new_records`).
MAX_RECENT_REQUEST_IDS = 64
BUCKET_MINUTES = 5

UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def parse_instant(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return instant if instant.tzinfo else instant.replace(tzinfo=UTC)


def floor_bucket(instant: datetime) -> datetime:
    aligned_minute = (instant.minute // BUCKET_MINUTES) * BUCKET_MINUTES
    return instant.astimezone(UTC).replace(minute=aligned_minute, second=0, microsecond=0)


def _nonneg_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)) and value >= 0:
        return int(value)
    return 0


# ---------------------------------------------------------------------------
# Cursori: stato interno del collector, non attraversa mai il boundary.
# ---------------------------------------------------------------------------


def load_cursors(path: Path) -> dict[str, dict[str, Any]]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    # Stesso principio fail-closed del parsing delle righe JSONL: un'entrata
    # per-percorso malformata (non un oggetto) viene scartata singolarmente
    # invece di propagarsi come AttributeError in `read_new_lines()` e
    # abbattere l'intero ciclo del collector per tutti i file tracciati.
    return {key: value for key, value in data.items() if isinstance(value, dict)}


def save_cursors(path: Path, cursors: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(cursors), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def read_new_lines(path: Path, cursor: dict[str, Any] | None) -> tuple[list[str], dict[str, Any]]:
    """Legge solo i byte aggiunti dal ciclo precedente.

    Un inode diverso o una dimensione inferiore all'offset salvato indicano
    che il file è stato ruotato o troncato: si riparte da zero azzerando
    anche i `requestId` già contabilizzati per quel percorso.
    """
    try:
        stat_result = path.stat()
    except OSError:
        empty_cursor = {"inode": 0, "offset": 0, "recent_request_ids": []}
        return [], (cursor or empty_cursor)
    inode = stat_result.st_ino
    size = stat_result.st_size
    offset = 0
    recent_ids: list[str] = []
    cursor_offset = int(cursor.get("offset", 0)) if cursor is not None else 0
    if cursor is not None and cursor.get("inode") == inode and cursor_offset <= size:
        offset = cursor_offset
        recent_ids = [
            item for item in cursor.get("recent_request_ids", []) if isinstance(item, str)
        ]
    try:
        with path.open("rb") as source:
            source.seek(offset)
            data = source.read()
    except OSError:
        return [], {"inode": inode, "offset": offset, "recent_request_ids": recent_ids}
    if data.endswith(b"\n"):
        complete = data
        new_offset = offset + len(data)
    else:
        # L'ultima riga non è ancora stata scritta per intero: la si lascia
        # per il prossimo ciclo invece di provare a deserializzarla a metà.
        split_at = data.rfind(b"\n")
        if split_at == -1:
            complete = b""
            new_offset = offset
        else:
            complete = data[: split_at + 1]
            new_offset = offset + split_at + 1
    lines = complete.decode("utf-8", errors="ignore").splitlines()
    return lines, {"inode": inode, "offset": new_offset, "recent_request_ids": recent_ids}


def dedup_new_records(
    records: list[dict[str, Any]], recent_ids: list[str]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Deduplica per `request_id` tenendo l'ultima occorrenza del lotto letto.

    Le partial di streaming ripetono lo stesso blocco di utilizzo su
    timestamp diversi: senza deduplica il consumo risulterebbe moltiplicato
    (contratto storico budget v1). La deduplica regge anche fra cicli
    successivi perché il cursore porta gli ultimi `MAX_RECENT_REQUEST_IDS`
    identificativi già contabilizzati per quel percorso: un requestId già lì
    presente viene ignorato anche se ricompare, così una richiesta le cui
    partial cadono a cavallo di due letture incrementali non viene ricontata.
    """
    last_by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for record in records:
        request_id = record["request_id"]
        if request_id not in last_by_id:
            order.append(request_id)
        last_by_id[request_id] = record
    already_seen = set(recent_ids)
    counted = []
    newly_seen = []
    for request_id in order:
        if request_id in already_seen:
            continue
        counted.append(last_by_id[request_id])
        newly_seen.append(request_id)
    updated_recent = (recent_ids + newly_seen)[-MAX_RECENT_REQUEST_IDS:]
    return counted, updated_recent


# ---------------------------------------------------------------------------
# Scoperta per mtime, mai a partire dai pane tmux.
# ---------------------------------------------------------------------------


def discover_claude_files(root: Path, lookback_seconds: float) -> list[tuple[Path, str | None]]:
    """Ritorna (percorso, parent_uuid) dei transcript toccati di recente.

    `parent_uuid` è valorizzato solo per i transcript dei subagent, ricavato
    dal percorso `<progetto>/<parent-uuid>/subagents/agent-*.jsonl`; per i
    transcript diretti resta `None` e l'attribuzione userà `sessionId`.
    """
    if not root.is_dir():
        return []
    horizon = time.time() - lookback_seconds
    found: list[tuple[Path, str | None]] = []
    try:
        projects = [item for item in root.iterdir() if item.is_dir()]
    except OSError:
        return []
    for project in projects:
        try:
            entries = list(project.iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_file() and entry.suffix == ".jsonl" and entry.stat().st_mtime >= horizon:
                    found.append((entry, None))
                    continue
            except OSError:
                continue
            if not entry.is_dir():
                continue
            subagents_dir = entry / "subagents"
            if not subagents_dir.is_dir():
                continue
            parent_uuid = entry.name
            try:
                agent_files = list(subagents_dir.glob("agent-*.jsonl"))
            except OSError:
                continue
            for agent_file in agent_files:
                try:
                    if agent_file.is_file() and agent_file.stat().st_mtime >= horizon:
                        found.append((agent_file, parent_uuid))
                except OSError:
                    continue
    return found


def discover_codex_files(root: Path, lookback_seconds: float) -> list[Path]:
    if not root.is_dir():
        return []
    horizon = time.time() - lookback_seconds
    found = []
    try:
        candidates = list(root.rglob("*.jsonl"))
    except OSError:
        return []
    for candidate in candidates:
        try:
            if candidate.is_file() and candidate.stat().st_mtime >= horizon:
                found.append(candidate)
        except OSError:
            continue
    return found


# ---------------------------------------------------------------------------
# Estrazione Claude: unica fonte con contratto pienamente noto.
# ---------------------------------------------------------------------------


def extract_claude_usage(record: dict[str, Any]) -> dict[str, Any] | None:
    if record.get("type") != "assistant":
        return None
    message = record.get("message")
    if not isinstance(message, dict):
        return None
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None
    timestamp = parse_instant(record.get("timestamp"))
    if timestamp is None:
        return None
    request_id = record.get("requestId")
    if not isinstance(request_id, str) or not request_id:
        return None
    session_id = record.get("sessionId")
    cwd = record.get("cwd")
    model = message.get("model")
    return {
        "request_id": request_id,
        "timestamp": timestamp,
        "session_id": session_id if isinstance(session_id, str) and session_id else None,
        "project": Path(cwd).name if isinstance(cwd, str) and cwd else "",
        "model": model if isinstance(model, str) else "",
        "input_tokens": _nonneg_int(usage.get("input_tokens")),
        "cache_creation_input_tokens": _nonneg_int(usage.get("cache_creation_input_tokens")),
        "cache_read_input_tokens": _nonneg_int(usage.get("cache_read_input_tokens")),
        "output_tokens": _nonneg_int(usage.get("output_tokens")),
    }


def process_claude_file(
    path: Path, parent_uuid: str | None, cursor: dict[str, Any] | None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    lines, next_cursor = read_new_lines(path, cursor)
    candidates = []
    for line in lines:
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(record, dict):
            continue
        usage = extract_claude_usage(record)
        if usage is not None:
            candidates.append(usage)
    counted, updated_ids = dedup_new_records(
        candidates, next_cursor.get("recent_request_ids", [])
    )
    next_cursor["recent_request_ids"] = updated_ids
    results = []
    for item in counted:
        session_uuid = parent_uuid or item["session_id"] or path.stem
        results.append(
            {
                **item,
                "session_uuid": session_uuid[:64],
                "is_subagent": parent_uuid is not None,
                "provider": "claude",
            }
        )
    return results, next_cursor


# ---------------------------------------------------------------------------
# Estrazione Codex: best-effort, si salta quando la struttura non è nota.
# ---------------------------------------------------------------------------


def codex_session_uuid(path: Path, record: dict[str, Any]) -> str | None:
    match = UUID_RE.search(path.name)
    if match:
        return match.group(0)
    session_id = record.get("session_id") or record.get("sessionId")
    return session_id if isinstance(session_id, str) and session_id else None


def extract_codex_usage(
    record: dict[str, Any], session_uuid: str, project: str
) -> dict[str, Any] | None:
    payload = record.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "token_count":
        return None
    info = payload.get("info")
    if not isinstance(info, dict):
        return None
    usage = info.get("last_token_usage")
    if not isinstance(usage, dict):
        return None
    timestamp = parse_instant(record.get("timestamp"))
    if timestamp is None:
        return None
    raw_input_tokens = _nonneg_int(usage.get("input_tokens"))
    cached_tokens = _nonneg_int(usage.get("cached_input_tokens"))
    cache_write_tokens = _nonneg_int(usage.get("cache_write_input_tokens"))
    output_tokens = _nonneg_int(usage.get("output_tokens"))
    # A differenza di Claude (dove `input_tokens` e `cache_read_input_tokens`
    # sono disgiunti), in Codex `cached_input_tokens` è un SOTTOINSIEME di
    # `input_tokens` (verificato sul campo: input_tokens + output_tokens ==
    # total_tokens, senza sommare `reasoning_output_tokens` a parte, che è a
    # sua volta un sottoinsieme di `output_tokens`). Mappare `input_tokens`
    # direttamente al contatore "input fresco" del contratto conterebbe due
    # volte la parte in cache e, ripetendosi il contesto ad ogni turno,
    # l'errore si moltiplica turno dopo turno. Si sottrae quindi la quota in
    # cache dall'input grezzo, clampando a 0 se il dato sorgente è incoerente.
    input_tokens = max(0, raw_input_tokens - cached_tokens)
    # Codex non pubblica un identificativo di richiesta: il best-effort usa
    # istante e contatori grezzi come chiave di deduplica, sufficiente a non
    # ricontare la stessa riga se il collector la rilegge per errore.
    dedup_key = f"{record.get('timestamp')}:{raw_input_tokens}:{cached_tokens}:{output_tokens}"
    return {
        "request_id": dedup_key,
        "timestamp": timestamp,
        "session_id": session_uuid,
        "project": project,
        "model": info.get("model") if isinstance(info.get("model"), str) else "",
        "input_tokens": input_tokens,
        "cache_creation_input_tokens": cache_write_tokens,
        "cache_read_input_tokens": cached_tokens,
        "output_tokens": output_tokens,
    }


def process_codex_file(
    path: Path, cursor: dict[str, Any] | None, codex_panes: dict[str, str]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    lines, next_cursor = read_new_lines(path, cursor)
    candidates = []
    current_project = ""
    for line in lines:
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(record, dict):
            continue
        payload = record.get("payload")
        if isinstance(payload, dict) and isinstance(payload.get("cwd"), str) and payload["cwd"]:
            current_project = Path(payload["cwd"]).name
        session_uuid = codex_session_uuid(path, record)
        if session_uuid is None:
            continue
        usage = extract_codex_usage(record, session_uuid, current_project)
        if usage is not None:
            candidates.append(usage)
    counted, updated_ids = dedup_new_records(
        candidates, next_cursor.get("recent_request_ids", [])
    )
    next_cursor["recent_request_ids"] = updated_ids
    # La cache di contesto Claude non copre Codex: l'origine si risolve qui,
    # per percorso di transcript, con la mappa costruita risalendo l'albero
    # dei processi dai pane tmux vivi (`codex_pane_transcript_sessions`).
    tmux_session_id = codex_panes.get(str(path.resolve()))
    origin = "mac" if tmux_session_id else "headless"
    results = [
        {
            **item,
            "session_uuid": item["session_id"][:64],
            "is_subagent": False,
            "provider": "codex",
            "origin": origin,
            "tmux_session_id": tmux_session_id,
        }
        for item in counted
    ]
    return results, next_cursor


# ---------------------------------------------------------------------------
# Origine: mac quando il session_uuid è mappato a un pane tmux vivo.
# ---------------------------------------------------------------------------


def context_cache_pane_map(path: str | None) -> dict[str, str]:
    """uuid di sessione -> pane_id (senza `%`) dalla cache di contesto Claude."""
    if not path:
        return {}
    root = Path(path)
    if not root.is_dir():
        return {}
    result: dict[str, str] = {}
    try:
        cache_files = list(root.glob("*.json"))
    except OSError:
        return {}
    for cache_file in cache_files:
        try:
            item = json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        pane_id = item.get("tmux_pane") if isinstance(item, dict) else None
        if isinstance(pane_id, str) and pane_id.removeprefix("%").isdigit():
            result[cache_file.stem] = pane_id.removeprefix("%")
    return result


def run_tmux_panes(socket_file: str | None) -> list[dict[str, str]]:
    """Un'unica interrogazione tmux: alimenta sia la mappatura Claude (via
    pane_id) sia quella Codex (via pid + albero dei processi)."""
    if not socket_file:
        return []
    try:
        result = subprocess.run(
            [
                "tmux",
                "-S",
                socket_file,
                "list-panes",
                "-a",
                "-F",
                "#{session_id}\t#{pane_id}\t#{pane_pid}\t#{pane_current_command}",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    panes: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        values = line.split("\t", 3)
        if len(values) != 4:
            continue
        session_id, pane_id, pid, command = values
        session_id = session_id.removeprefix("$")
        pane_id = pane_id.removeprefix("%")
        if session_id.isdigit() and pane_id.isdigit() and pid.isdigit():
            panes.append(
                {
                    "session_id": session_id,
                    "pane_id": pane_id,
                    "pid": pid,
                    "command": command.lower(),
                }
            )
    return panes


def live_pane_sessions(panes: list[dict[str, str]]) -> dict[str, str]:
    """pane_id (senza `%`) -> session_id (senza `$`) dei pane vivi."""
    return {pane["pane_id"]: pane["session_id"] for pane in panes}


def process_tree(root_pid: str, proc_root: Path = Path("/proc")) -> list[str]:
    pending = [root_pid]
    result: list[str] = []
    while pending and len(result) < 64:
        pid = pending.pop()
        if pid in result:
            continue
        result.append(pid)
        try:
            children = (proc_root / pid / "task" / pid / "children").read_text().split()
        except OSError:
            children = []
        pending.extend(children)
    return result


def codex_transcript_for_pid(
    pid: str, codex_root: Path, proc_root: Path = Path("/proc")
) -> Path | None:
    try:
        resolved_root = codex_root.resolve()
    except OSError:
        return None
    for process_pid in process_tree(pid, proc_root):
        fd_root = proc_root / process_pid / "fd"
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


def codex_pane_transcript_sessions(
    codex_root: Path, panes: list[dict[str, str]], proc_root: Path = Path("/proc")
) -> dict[str, str]:
    """percorso transcript (risolto) -> session_id tmux, per i pane Codex vivi.

    Stessa tecnica di `provider-session-state-collector.py` (`process_tree` +
    scansione di `/proc/<pid>/fd`): la cache di contesto di Claude non copre
    Codex, quindi dal pid del pane si risale l'albero dei processi cercando
    un descrittore aperto su un file `.jsonl` sotto la root delle sessioni
    Codex. Se l'albero dei processi non espone il descrittore (permessi,
    processo già terminato, redirection insolita) la sessione resta
    `headless`: è un mancato rilevamento silenzioso, non un errore.
    """
    result: dict[str, str] = {}
    for pane in panes:
        if "codex" not in pane["command"]:
            continue
        transcript = codex_transcript_for_pid(pane["pid"], codex_root, proc_root)
        if transcript is not None:
            result[str(transcript.resolve())] = pane["session_id"]
    return result


def resolve_origin(
    session_uuid: str, context_panes: dict[str, str], live_panes: dict[str, str]
) -> tuple[str, str | None]:
    pane_id = context_panes.get(session_uuid)
    if pane_id is None:
        return "headless", None
    tmux_session_id = live_panes.get(pane_id)
    if tmux_session_id is None:
        return "headless", None
    return "mac", tmux_session_id


# ---------------------------------------------------------------------------
# Aggregazione per bucket di cinque minuti.
# ---------------------------------------------------------------------------


def aggregate(records: list[dict[str, Any]]) -> dict[tuple[Any, ...], dict[str, Any]]:
    buckets: dict[tuple[Any, ...], dict[str, Any]] = {}
    for record in records:
        bucket_start = floor_bucket(record["timestamp"])
        key = (
            bucket_start,
            record["provider"],
            record["session_uuid"],
            record["model"],
            record["is_subagent"],
        )
        row = buckets.get(key)
        if row is None:
            row = {
                "bucket_start": bucket_start,
                "provider": record["provider"],
                "session_uuid": record["session_uuid"],
                "origin": record.get("origin", "headless"),
                "tmux_session_id": record.get("tmux_session_id"),
                "project": "",
                "model": record["model"],
                "is_subagent": record["is_subagent"],
                "turns": 0,
                "input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "output_tokens": 0,
            }
            buckets[key] = row
        row["turns"] += 1
        row["input_tokens"] += record["input_tokens"]
        row["cache_creation_input_tokens"] += record["cache_creation_input_tokens"]
        row["cache_read_input_tokens"] += record["cache_read_input_tokens"]
        row["output_tokens"] += record["output_tokens"]
        if not row["project"] and record.get("project"):
            row["project"] = record["project"]
    return buckets


# ---------------------------------------------------------------------------
# Scrittura: stessa semantica di append/rotate di rate-limit-collector.py.
# ---------------------------------------------------------------------------


def append_rows(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    payload = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(descriptor, payload.encode("utf-8"))
    finally:
        os.close(descriptor)


def rotate(path: Path, retention_days: int, max_bytes: int) -> None:
    try:
        if path.stat().st_size <= max_bytes:
            return
    except OSError:
        return
    horizon = datetime.now(UTC) - timedelta(days=retention_days)
    kept = []
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as source:
            for line in source:
                try:
                    item = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                bucket_start = (
                    parse_instant(item.get("bucket_start")) if isinstance(item, dict) else None
                )
                if bucket_start is not None and bucket_start >= horizon:
                    kept.append(line if line.endswith("\n") else line + "\n")
    except OSError:
        return
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text("".join(kept), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def collect(
    args: argparse.Namespace, proc_root: Path = Path("/proc")
) -> list[dict[str, object]]:
    claude_root = Path(args.claude_projects_root)
    codex_root = Path(args.codex_sessions_root)
    lookback_seconds = max(0, args.lookback_minutes) * 60

    cursor_path = Path(args.cursor_file).resolve()
    cursors = load_cursors(cursor_path)

    panes = run_tmux_panes(args.tmux_socket_file)
    live_panes = live_pane_sessions(panes)
    codex_panes = codex_pane_transcript_sessions(codex_root, panes, proc_root)

    all_records: list[dict[str, Any]] = []

    for path, parent_uuid in discover_claude_files(claude_root, lookback_seconds):
        key = str(path.resolve())
        records, next_cursor = process_claude_file(path, parent_uuid, cursors.get(key))
        cursors[key] = next_cursor
        all_records.extend(records)

    for path in discover_codex_files(codex_root, lookback_seconds):
        key = str(path.resolve())
        records, next_cursor = process_codex_file(path, cursors.get(key), codex_panes)
        cursors[key] = next_cursor
        all_records.extend(records)

    # Rimuovi dai cursori i percorsi non più esistenti: uno stato per un
    # transcript ruotato via o cancellato non serve più a nulla.
    for key in list(cursors):
        if not Path(key).exists():
            del cursors[key]

    # Le sessioni Codex hanno già origine/tmux_session_id risolti in
    # `process_codex_file` (per percorso di transcript); qui si risolvono
    # solo quelle Claude, tramite la cache di contesto.
    context_panes = context_cache_pane_map(args.claude_context_cache)
    origin_cache: dict[str, tuple[str, str | None]] = {}
    for record in all_records:
        if record.get("origin") is not None:
            continue
        session_uuid = record["session_uuid"]
        if session_uuid not in origin_cache:
            origin_cache[session_uuid] = resolve_origin(session_uuid, context_panes, live_panes)
        origin, tmux_session_id = origin_cache[session_uuid]
        record["origin"] = origin
        record["tmux_session_id"] = tmux_session_id

    buckets = aggregate(all_records)
    rows = []
    for row in sorted(
        buckets.values(),
        key=lambda item: (
            item["bucket_start"],
            item["session_uuid"],
            item["model"],
            item["is_subagent"],
        ),
    ):
        payload: dict[str, object] = {
            "bucket_start": row["bucket_start"].isoformat(),
            "provider": row["provider"][:32],
            "session_uuid": row["session_uuid"][:64],
        }
        if row["origin"] == "mac" and row["tmux_session_id"]:
            payload["tmux_session_id"] = row["tmux_session_id"][:10]
        payload.update(
            {
                "origin": row["origin"][:16],
                "project": row["project"][:128],
                "model": row["model"][:64],
                "is_subagent": row["is_subagent"],
                "turns": row["turns"],
                "input_tokens": row["input_tokens"],
                "cache_creation_input_tokens": row["cache_creation_input_tokens"],
                "cache_read_input_tokens": row["cache_read_input_tokens"],
                "output_tokens": row["output_tokens"],
            }
        )
        rows.append(payload)

    save_cursors(cursor_path, cursors)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--cursor-file",
        default=os.path.expanduser(
            "~/.local/state/mobile-agent-console/session-usage-cursors.json"
        ),
    )
    parser.add_argument(
        "--claude-projects-root", default=os.path.expanduser("~/.claude/projects")
    )
    parser.add_argument(
        "--claude-context-cache", default=os.path.expanduser("~/.claude/context-window-cache")
    )
    parser.add_argument(
        "--codex-sessions-root", default=os.path.expanduser("~/.codex/sessions")
    )
    parser.add_argument("--tmux-socket-file")
    parser.add_argument("--lookback-minutes", type=int, default=DEFAULT_LOOKBACK_MINUTES)
    parser.add_argument("--retention-days", type=int, default=DEFAULT_RETENTION_DAYS)
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    args = parser.parse_args()

    output = Path(args.output).resolve()
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

    rows = collect(args)
    append_rows(output, rows)
    rotate(output, args.retention_days, args.max_bytes)


if __name__ == "__main__":
    main()
