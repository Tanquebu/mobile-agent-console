#!/usr/bin/env python3
"""Sonda giornaliera per rilevare reset anticipati della quota Codex.

Esegue al massimo una richiesta fresh al giorno, soltanto quando la cache
indica quota fuori soglia e non esiste una misura recente. Aggiorna
atomicamente lo snapshot canonico e lo storico; produce soltanto eventi
tipizzati privi di contenuto sensibile.
"""
import argparse
import contextlib
import errno
import fcntl
import json
import logging
import os
import selectors
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime

from collections.abc import Iterator

# ---------------------------------------------------------------------------
# Logging strutturato (JSON lines su stderr)
# ---------------------------------------------------------------------------
_handler = logging.StreamHandler(sys.stderr)
_handler.setFormatter(logging.Formatter("%(message)s"))
logger = logging.getLogger("codex-quota-probe")
logger.addHandler(_handler)
logger.propagate = False


def log_event(event_type: str, **kwargs: object) -> None:
    logger.info(json.dumps({"event_type": event_type, **kwargs}, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Funzioni pure
# ---------------------------------------------------------------------------

def last_valid_codex_snapshot(snapshot_path: str) -> dict | None:
    """Restituisce il dizionario provider Codex dall'ultimo snapshot, o None."""
    try:
        with open(snapshot_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    for provider in data.get("providers", []):
        if isinstance(provider, dict) and provider.get("provider") == "codex":
            windows = provider.get("windows")
            if isinstance(windows, list):
                return provider
    return None


def effective_threshold(snapshot: dict, tasks: list) -> float:
    """Soglia effettiva: la piu' restrittiva tra 100.0 e le soglie dei task sospesi."""
    threshold = 100.0
    for task in tasks:
        if (
            isinstance(task, dict)
            and task.get("provider") == "codex"
            and task.get("status") == "paused_provider"
        ):
            raw = task.get("capacity_threshold")
            if raw is not None:
                try:
                    val = float(raw)
                    if 0.0 <= val < threshold:
                        threshold = val
                except (TypeError, ValueError):
                    pass
    return threshold


def should_probe(
    snapshot: dict,
    tasks: list,
    now: datetime,
    threshold: float,
    recent_minutes: int = 60,
) -> str:
    """Ritorna la ragione di skip oppure 'probe'.

    Valori: 'skipped_budget_available', 'skipped_recent_sample', 'probe'.
    """
    windows = snapshot.get("windows") if isinstance(snapshot, dict) else None
    if not isinstance(windows, list) or not windows:
        return "skipped_budget_available"

    over_threshold = False
    for window in windows:
        if not isinstance(window, dict):
            continue
        raw_pct = window.get("used_percent")
        if raw_pct is None:
            continue
        try:
            if float(raw_pct) >= threshold:
                over_threshold = True
                break
        except (TypeError, ValueError):
            pass

    if not over_threshold:
        return "skipped_budget_available"

    observed_at_str = snapshot.get("observed_at") if isinstance(snapshot, dict) else None
    if isinstance(observed_at_str, str) and observed_at_str:
        try:
            observed_at = datetime.fromisoformat(observed_at_str)
            if observed_at.tzinfo is None:
                observed_at = observed_at.replace(tzinfo=UTC)
            age_seconds = (now - observed_at).total_seconds()
            if age_seconds < recent_minutes * 60:
                return "skipped_recent_sample"
        except (ValueError, OverflowError):
            pass

    return "probe"


def parse_rate_limits_from_jsonl(data: bytes, max_bytes: int) -> dict | None:
    """Estrae l'ultimo evento rate_limits valido da JSONL, rispettando max_bytes."""
    truncated = data[:max_bytes]
    try:
        text = truncated.decode("utf-8", errors="ignore")
    except (UnicodeDecodeError, ValueError):
        return None

    last_valid: dict | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("windows"), list):
            last_valid = payload
    return last_valid


def compute_reconciliation(
    tasks: list, new_snapshot: dict, now: datetime
) -> list[dict]:
    """Produce mutazioni di riconciliazione senza applicarle.

    Per ogni task Codex in paused_provider:
    - se nessuna finestra supera la soglia specifica -> resume
    - se ancora sopra soglia e reset noto -> reschedule
    - se ancora sopra soglia e reset ignoto -> nessuna mutazione (mantiene pausa)
    """
    mutations: list[dict] = []
    windows = new_snapshot.get("windows", [])
    if not isinstance(windows, list):
        windows = []

    MARGIN_SECONDS = 300

    for task in tasks:
        if not isinstance(task, dict):
            continue
        if task.get("provider") != "codex" or task.get("status") != "paused_provider":
            continue
        task_id = task.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            continue

        raw_thresh = task.get("capacity_threshold", 100.0)
        try:
            t_thresh = float(raw_thresh)
        except (TypeError, ValueError):
            t_thresh = 100.0

        over_threshold = False
        max_reset: int = 0
        for window in windows:
            if not isinstance(window, dict):
                continue
            raw_pct = window.get("used_percent")
            if raw_pct is None:
                continue
            try:
                pct = float(raw_pct)
            except (TypeError, ValueError):
                continue
            if pct >= t_thresh:
                over_threshold = True
                reset = window.get("resets_at")
                if isinstance(reset, int) and reset > 0 and reset > max_reset:
                    max_reset = reset

        if not over_threshold:
            mutations.append(
                {
                    "task_id": task_id,
                    "action": "resume",
                    "status": "new",
                    "pause_reason": None,
                    "next_attempt_at": None,
                }
            )
        elif max_reset > 0:
            next_attempt = datetime.fromtimestamp(
                max_reset + MARGIN_SECONDS, tz=UTC
            ).isoformat()
            mutations.append(
                {
                    "task_id": task_id,
                    "action": "reschedule",
                    "next_attempt_at": next_attempt,
                }
            )
        # se ancora sopra soglia ma reset ignoto: nessuna mutazione

    return mutations


# ---------------------------------------------------------------------------
# Lock non bloccante
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def acquire_lock(lock_path: str) -> Iterator[int | None]:
    """Context manager per lock esclusivo non bloccante.

    Yields l'fd se il lock e' acquisito, None se occupato.
    Garantisce unlock e chiusura dell'fd anche su eccezione.
    """
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    acquired = False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError as exc:
            if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES):
                yield None
                return
            raise
        yield fd
    finally:
        if acquired:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(fd)


# ---------------------------------------------------------------------------
# Runner della sonda
# ---------------------------------------------------------------------------

def run_probe(
    codex_script: str,
    timeout: int,
    workdir: str,
    max_output_bytes: int,
) -> tuple[bool, bytes, str | None]:
    """Esegue la CLI Codex in un process group dedicato.

    - argv fisso, shell=False
    - drena stdout/stderr con selectors per evitare deadlock su pipe satura
    - SIGTERM al process group se ancora vivo -> grace period -> SIGKILL in finally
    - garantisce reap del processo padre
    """
    argv = [
        codex_script,
        "--model", "gpt-5.6-sol",
        "--ephemeral",
        "--json",
        "--no-sandbox",
        "-p", "quota",
    ]

    try:
        proc = subprocess.Popen(
            argv,
            cwd=workdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            shell=False,
        )
    except OSError:
        return False, b"", None

    sel = selectors.DefaultSelector()
    stdout_buf = bytearray()
    deadline = time.monotonic() + timeout
    pgid: int | None = None

    try:
        try:
            pgid = os.getpgid(proc.pid)
        except OSError:
            pass

        if proc.stdout:
            sel.register(proc.stdout, selectors.EVENT_READ, data="stdout")
        if proc.stderr:
            sel.register(proc.stderr, selectors.EVENT_READ, data="stderr")

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if not sel.get_map() and proc.poll() is not None:
                break
            events = sel.select(timeout=min(remaining, 1.0))
            for key, _ in events:
                try:
                    chunk = os.read(key.fd, 8192)
                except OSError:
                    chunk = b""
                if not chunk:
                    sel.unregister(key.fileobj)
                elif key.data == "stdout":
                    cap = max_output_bytes - len(stdout_buf)
                    if cap > 0:
                        stdout_buf.extend(chunk[:cap])
                # stderr: drenato e scartato (evita pipe-full deadlock)

    finally:
        sel.close()

        # Termina il process group solo se il processo e' ancora vivo
        if proc.poll() is None and pgid is not None:
            try:
                os.killpg(pgid, signal.SIGTERM)
            except OSError:
                pass

        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            if pgid is not None:
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except OSError:
                    pass
            proc.wait()

        if proc.stdout:
            proc.stdout.close()
        if proc.stderr:
            proc.stderr.close()

    returncode = proc.returncode if proc.returncode is not None else -1
    return returncode == 0, bytes(stdout_buf), datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# Persistenza atomica
# ---------------------------------------------------------------------------

def update_snapshot(path: str, new_codex: dict, collected_at: str) -> None:
    """Aggiorna atomicamente lo snapshot sostituendo l'entry Codex."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            data = {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        data = {}

    data["collected_at"] = collected_at
    providers = data.get("providers", [])
    if not isinstance(providers, list):
        providers = []

    updated = False
    for i, p in enumerate(providers):
        if isinstance(p, dict) and p.get("provider") == "codex":
            providers[i] = new_codex
            updated = True
            break
    if not updated:
        providers.append(new_codex)
    data["providers"] = providers

    temp_path = path + ".part"
    with open(temp_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    os.chmod(temp_path, 0o600)
    os.replace(temp_path, path)


def append_history(path: str, new_codex: dict, sampled_at: str) -> None:
    """Appende una riga JSONL allo storico con source=fresh."""
    row = {
        "sampled_at": sampled_at,
        "provider": "codex",
        "source": "fresh",
        "observed_at": new_codex.get("observed_at"),
        "stale": False,
        "parse_mode": "structured",
        "windows": [
            {
                "label": w.get("label"),
                "used_percent": w.get("used_percent"),
                "resets_at": w.get("resets_at"),
            }
            for w in new_codex.get("windows", [])
            if isinstance(w, dict)
        ],
    }
    line = json.dumps(row, ensure_ascii=False) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


# ---------------------------------------------------------------------------
# Flusso principale
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> None:
    logger.setLevel(getattr(logging, args.log_level.upper(), logging.INFO))

    lock_dir = os.path.dirname(args.lock_path)
    if lock_dir:
        os.makedirs(lock_dir, mode=0o700, exist_ok=True)

    with acquire_lock(args.lock_path) as lock_fd:
        if lock_fd is None:
            log_event("skipped_locked")
            return

        now = datetime.now(UTC)
        snapshot = last_valid_codex_snapshot(args.snapshot_path)
        if snapshot is None:
            return

        # Legge i task dal file di stato orchestratore se configurato
        tasks: list = []
        orch_path = getattr(args, "orchestrator_state_path", None)
        if orch_path:
            try:
                with open(orch_path, "r", encoding="utf-8") as fh:
                    orch = json.load(fh)
                if isinstance(orch, dict):
                    tasks = [t for t in orch.get("tasks", []) if isinstance(t, dict)]
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                pass

        threshold = effective_threshold(snapshot, tasks)
        decision = should_probe(snapshot, tasks, now, threshold, recent_minutes=60)

        if decision != "probe":
            log_event(decision)
            return

        if args.dry_run:
            log_event("probe_started", dry_run=True)
            return

        log_event("probe_started")

        workdir = os.path.expanduser("~")
        success, raw_bytes, observed_at = run_probe(
            args.codex_script, args.timeout, workdir, 64 * 1024
        )

        payload = parse_rate_limits_from_jsonl(raw_bytes, 64 * 1024)
        if payload is None:
            log_event(
                "probe_failed",
                reason="invalid_payload" if success else "nonzero_exit_or_timeout",
            )
            return

        observed_at_final = (
            payload.get("updated_at")
            if isinstance(payload.get("updated_at"), str)
            else observed_at
        )

        windows_raw = payload.get("windows", [])
        windows: list[dict] = []
        for w in (windows_raw if isinstance(windows_raw, list) else []):
            if not isinstance(w, dict):
                continue
            label = w.get("label")
            used = w.get("used_percent")
            resets = w.get("resets_at")
            windows.append({
                "label": label[:32] if isinstance(label, str) else label,
                "used_percent": (
                    min(max(float(used), 0.0), 100.0)
                    if isinstance(used, (int, float))
                    else None
                ),
                "resets_at": resets if isinstance(resets, int) and resets >= 0 else None,
                "detail": None,
            })

        if not windows:
            log_event("probe_failed", reason="no_valid_windows")
            return

        reached_type = payload.get("reached_type")
        exhausted = (isinstance(reached_type, str) and bool(reached_type)) or any(
            isinstance(w.get("used_percent"), float) and w["used_percent"] >= 100.0
            for w in windows
        )

        new_codex: dict = {
            "provider": "codex",
            "available": not exhausted,
            "observed_at": observed_at_final,
            "windows": windows,
            "reached_type": reached_type if isinstance(reached_type, str) else None,
            "error": None,
        }

        if exhausted:
            log_event("probe_still_exhausted")
        else:
            log_event("probe_provider_available")

        update_snapshot(args.snapshot_path, new_codex, now.isoformat())
        append_history(args.history_path, new_codex, now.isoformat())

        mutations = compute_reconciliation(tasks, new_codex, now)
        resumed = sum(1 for m in mutations if m["action"] == "resume")
        rescheduled = sum(1 for m in mutations if m["action"] == "reschedule")
        if resumed > 0:
            log_event("probe_tasks_resumed", count=resumed)
        if rescheduled > 0:
            log_event("probe_tasks_rescheduled", count=rescheduled)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sonda giornaliera per reset anticipati della quota Codex."
    )
    parser.add_argument("--snapshot-path", required=True)
    parser.add_argument("--history-path", required=True)
    parser.add_argument("--codex-script", required=True)
    parser.add_argument("--lock-path", required=True)
    parser.add_argument("--orchestrator-state-path",
                        help="Path opzionale del file di stato orchestratore (JSON)")
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
