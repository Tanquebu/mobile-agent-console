#!/usr/bin/env python3
import argparse
import json
import os
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path


UPDATED = re.compile(r"^Aggiornato:\s+(?P<observed_at>\S+)(?:\s+\[(?P<source>[^\]]+)\])?")
WINDOW = re.compile(
    r"^(?P<label>5h|7d|primaria|secondaria):\s+"
    r"(?:(?P<used>[0-9]+(?:\.[0-9]+)?)%|n/d)"
    r"(?:\s+\((?P<detail>.*)\))?$"
)
REACHED = re.compile(r"^rate_limit_reached_type:\s+(.*)$")

# Il campione dichiara la propria freschezza invece di simularla: oltre questa
# distanza fra rilevazione e osservazione la sorgente è ferma, e il consumatore
# deve rappresentare l'intervallo come non osservato (contratto storico v1).
DEFAULT_STALE_AFTER_SECONDS = 600
DEFAULT_RETENTION_DAYS = 14
DEFAULT_HISTORY_MAX_BYTES = 4 * 1024 * 1024
TAIL_BYTES = 64 * 1024


def normalized_percent(value: float) -> float:
    """Keep provider rounding quirks within the API contract's 0-100 range."""
    return min(max(float(value), 0.0), 100.0)


def parse_instant(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return instant if instant.tzinfo else instant.replace(tzinfo=UTC)


def normalized_source(value: object) -> str:
    return "fresh" if isinstance(value, str) and "fresh" in value.lower() else "cache"


def run_script(argv: list[str]) -> subprocess.CompletedProcess[str] | OSError:
    try:
        return subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "LC_ALL": "C.UTF-8"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return exc if isinstance(exc, OSError) else OSError(str(exc))


def parse_structured(stdout: str) -> dict[str, object] | None:
    """Forma strutturata (`--json`): l'unica che porta `resets_at` come epoch."""
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("windows"), list):
        return None
    windows = []
    for item in payload["windows"]:
        if not isinstance(item, dict) or not isinstance(item.get("label"), str):
            continue
        used = item.get("used_percent")
        reset = item.get("resets_at")
        windows.append(
            {
                "label": item["label"][:32],
                "used_percent": (
                    normalized_percent(used) if isinstance(used, (int, float)) else None
                ),
                "resets_at": reset if isinstance(reset, int) and reset >= 0 else None,
                "detail": item.get("detail") if isinstance(item.get("detail"), str) else None,
            }
        )
    if not windows:
        return None
    reached = payload.get("reached_type")
    return {
        "observed_at": payload.get("updated_at")
        if isinstance(payload.get("updated_at"), str)
        else None,
        "source": normalized_source(payload.get("source")),
        "windows": windows,
        "reached_type": reached if isinstance(reached, str) else None,
    }


def parse_text(stdout: str) -> dict[str, object]:
    """Forma testuale storica: nessun `resets_at` strutturato, solo `detail`."""
    observed_at = None
    source = "cache"
    windows = []
    reached_type = None
    for line in (raw.strip() for raw in stdout.splitlines()):
        if not line:
            continue
        if match := UPDATED.match(line):
            observed_at = match.group("observed_at")
            source = normalized_source(match.group("source"))
        elif match := WINDOW.match(line):
            windows.append(
                {
                    "label": match.group("label"),
                    "used_percent": (
                        normalized_percent(float(match.group("used")))
                        if match.group("used") is not None
                        else None
                    ),
                    "resets_at": None,
                    "detail": match.group("detail"),
                }
            )
        elif match := REACHED.match(line):
            reached_type = match.group(1)
    return {
        "observed_at": observed_at,
        "source": source,
        "windows": windows,
        "reached_type": reached_type,
    }


def collect(name: str, script: str, *, fresh: bool = False) -> dict[str, object]:
    argv = [script] + (["--fresh"] if fresh else []) + ["--json"]
    result = run_script(argv)
    if isinstance(result, OSError):
        return {"provider": name, "available": False, "error": str(result), "windows": []}
    parsed = parse_structured(result.stdout) if result.returncode == 0 else None
    # `parse_mode` pubblica quale delle due forme ha prodotto la riga: è il
    # contratto di degradazione fra la sorgente strutturata (fuori dal
    # repository, negli script quote dell'utente) e il parsing testuale
    # storico. Senza questo fatto pubblicato il fallback è silenzioso (vedi
    # BH-03 nel backlog).
    parse_mode = "structured" if parsed is not None else None
    if parsed is None and result.returncode == 0:
        # Uno script che ignora gli argomenti sconosciuti ha già stampato la
        # forma testuale: si usa quella senza pagare una seconda esecuzione.
        textual = parse_text(result.stdout)
        parsed = textual if textual["windows"] else None
        if parsed is not None:
            parse_mode = "text"
    if parsed is None:
        # Lo script ha rifiutato `--json`: si ricade sull'invocazione storica.
        # Il `--fresh` non viene ripetuto, l'eventuale prima esecuzione ha già
        # aggiornato la cache che la forma testuale rilegge.
        result = run_script([script])
        if isinstance(result, OSError):
            return {"provider": name, "available": False, "error": str(result), "windows": []}
        parsed = parse_text(result.stdout)
        # Coerente col ramo gemello sopra: "text" pubblica solo un parsing
        # testuale che ha davvero estratto finestre, non un tentativo andato
        # a vuoto (script sempre fallito). Senza finestre nessun parsing è
        # realmente riuscito, quindi `parse_mode` resta `None`.
        parse_mode = "text" if parsed["windows"] else None
    available = result.returncode == 0 and bool(parsed["windows"])
    error = None
    if not available:
        error = (result.stderr.strip() or "Nessun dato riconosciuto")[:500]
    return {
        "provider": name,
        "available": available,
        "error": error,
        "parse_mode": parse_mode,
        **parsed,
    }


def snapshot_provider(collected: dict[str, object]) -> dict[str, object]:
    """Proiezione sul contratto compatibile di `provider-rate-limits.json`."""
    return {
        "provider": collected["provider"],
        "available": collected["available"],
        "observed_at": collected.get("observed_at"),
        "windows": [
            {
                "label": window["label"],
                "used_percent": window["used_percent"],
                "resets_at": window["resets_at"],
                "detail": window["detail"],
            }
            for window in collected.get("windows", [])
        ],
        "reached_type": collected.get("reached_type"),
        "error": collected["error"],
    }


def history_row(
    collected: dict[str, object], sampled_at: datetime, stale_after_seconds: int
) -> dict[str, object]:
    observed = parse_instant(collected.get("observed_at"))
    row: dict[str, object] = {
        "sampled_at": sampled_at.isoformat(),
        "provider": collected["provider"],
        "source": collected.get("source", "cache"),
        "observed_at": collected.get("observed_at"),
        "stale": observed is None
        or (sampled_at - observed) > timedelta(seconds=stale_after_seconds),
        "parse_mode": collected.get("parse_mode"),
        "windows": [
            {
                "label": window["label"],
                "used_percent": window["used_percent"],
                "resets_at": window["resets_at"],
            }
            for window in collected.get("windows", [])
        ],
    }
    if collected.get("error"):
        row["error"] = collected["error"]
    return row


def tail_lines(path: Path, max_bytes: int = TAIL_BYTES) -> list[str]:
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
    return raw.decode("utf-8", errors="ignore").splitlines()


def last_row_per_provider(path: Path) -> dict[str, dict[str, object]]:
    latest: dict[str, dict[str, object]] = {}
    for line in tail_lines(path):
        try:
            item = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(item, dict) and isinstance(item.get("provider"), str):
            latest[item["provider"]] = item
    return latest


def observation_key(row: dict[str, object]) -> tuple[object, ...]:
    windows = row.get("windows")
    windows = windows if isinstance(windows, list) else []
    return (
        row.get("observed_at"),
        row.get("error"),
        row.get("parse_mode"),
        tuple(
            (item.get("label"), item.get("used_percent"), item.get("resets_at"))
            for item in windows
            if isinstance(item, dict)
        ),
    )


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
                sampled = parse_instant(item.get("sampled_at")) if isinstance(item, dict) else None
                if sampled is not None and sampled >= horizon:
                    kept.append(line if line.endswith("\n") else line + "\n")
    except OSError:
        return
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text("".join(kept), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def write_snapshot(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_suffix(".part")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--claude-script", required=True)
    parser.add_argument("--codex-script", required=True)
    parser.add_argument("--history-output")
    parser.add_argument("--history-retention-days", type=int, default=DEFAULT_RETENTION_DAYS)
    parser.add_argument("--history-max-bytes", type=int, default=DEFAULT_HISTORY_MAX_BYTES)
    parser.add_argument("--stale-after-seconds", type=int, default=DEFAULT_STALE_AFTER_SECONDS)
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args()

    output = Path(args.output).resolve()
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    sampled_at = datetime.now(UTC)
    collected = [
        collect("claude", args.claude_script, fresh=args.fresh),
        collect("codex", args.codex_script, fresh=args.fresh),
    ]
    write_snapshot(
        output,
        {
            "collected_at": sampled_at.isoformat(),
            "providers": [snapshot_provider(item) for item in collected],
        },
    )

    rows = [history_row(item, sampled_at, args.stale_after_seconds) for item in collected]
    if args.history_output:
        history = Path(args.history_output).resolve()
        history.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        previous = last_row_per_provider(history)
        # Una sorgente ferma non produce righe: l'assenza di campioni è essa
        # stessa l'informazione che nulla è stato osservato.
        changed = [
            row
            for row in rows
            if observation_key(row) != observation_key(previous.get(str(row["provider"]), {}))
        ]
        append_rows(history, changed)
        rotate(history, args.history_retention_days, args.history_max_bytes)

    if args.stdout:
        print(json.dumps({"collected_at": sampled_at.isoformat(), "samples": rows}))


if __name__ == "__main__":
    main()
