#!/usr/bin/env python3
"""Write a sanitized free-space snapshot of the configured host filesystems.

Pensato per un timer orario: il backend legge il file prodotto e la PWA
mostra un alert quando un filesystem scende sotto la soglia. I path restano
nel file di environment della unit; nel JSON finiscono solo le etichette.
"""

import argparse
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

MAX_FILESYSTEMS = 16
LABEL = re.compile(r"^[A-Za-z0-9 _./()-]{1,64}$")
GIB = 1024**3


def parse_filesystems(value: str) -> list[tuple[str, Path]]:
    """Parse `label=path,label=path` (stesso formato di MAC_WORKSPACE_PRESETS)."""
    items: list[tuple[str, Path]] = []
    for raw in value.split(","):
        raw = raw.strip()
        if not raw:
            continue
        label, separator, path = raw.partition("=")
        label, path = label.strip(), path.strip()
        if not separator or not LABEL.fullmatch(label) or not path.startswith("/"):
            raise ValueError(f"voce filesystem non valida: {raw!r}")
        items.append((label, Path(path)))
    if not items:
        raise ValueError("nessun filesystem configurato")
    if len(items) > MAX_FILESYSTEMS:
        raise ValueError("troppi filesystem configurati")
    return items


def measure(
    label: str,
    path: Path,
    min_free_bytes: int,
    max_used_percent: float | None,
    statvfs=os.statvfs,
) -> dict[str, object]:
    try:
        stats = statvfs(str(path))
    except OSError:
        return {"label": label, "available": False, "alert": True, "reasons": ["unavailable"]}
    total = stats.f_blocks * stats.f_frsize
    # f_bavail (non f_bfree): lo spazio riservato a root non è utilizzabile
    # dai processi utente, ed è quello che finisce per primo.
    free = stats.f_bavail * stats.f_frsize
    used_percent = round(100 * (total - free) / total, 1) if total else 100.0
    reasons = []
    if free < min_free_bytes:
        reasons.append("min_free")
    if max_used_percent is not None and used_percent >= max_used_percent:
        reasons.append("used_percent")
    return {
        "label": label,
        "available": True,
        "total_bytes": total,
        "free_bytes": free,
        "used_percent": used_percent,
        "alert": bool(reasons),
        "reasons": reasons,
    }


def collect(
    filesystems: list[tuple[str, Path]],
    min_free_bytes: int,
    max_used_percent: float | None,
    statvfs=os.statvfs,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "collected_at": datetime.now(UTC).isoformat(),
        "min_free_bytes": min_free_bytes,
        "max_used_percent": max_used_percent,
        "filesystems": [
            measure(label, path, min_free_bytes, max_used_percent, statvfs)
            for label, path in filesystems
        ],
    }


def write_atomic(output: Path, payload: dict[str, object]) -> None:
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = output.with_suffix(".part")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        filesystems = parse_filesystems(os.environ.get("MAC_DISK_SPACE_FILESYSTEMS", ""))
        min_free_gb = float(os.environ.get("MAC_DISK_SPACE_MIN_FREE_GB", "5"))
        raw_percent = os.environ.get("MAC_DISK_SPACE_MAX_USED_PERCENT", "").strip()
        max_used_percent = float(raw_percent) if raw_percent else None
    except ValueError as exc:
        raise SystemExit(f"configurazione disk-space non valida: {exc}") from exc
    if min_free_gb < 0 or (max_used_percent is not None and not 0 < max_used_percent <= 100):
        raise SystemExit("soglie disk-space fuori intervallo")
    payload = collect(filesystems, int(min_free_gb * GIB), max_used_percent)
    # Proprio quando il disco è pieno la scrittura può fallire: meglio un
    # errore esplicito nel journal che un file troncato. Il backend tratta
    # il file vecchio come scaduto e la PWA lo segnala comunque.
    write_atomic(Path(args.output).resolve(), payload)


if __name__ == "__main__":
    main()
