#!/usr/bin/env python3
"""Statusline custom per AGY che:
1. Mostra una statusline formattata nel TUI (stdout)
2. Inietta i dati di quota antigravity nel file provider-rate-limits.json di MAC

Configurare in ~/.gemini/antigravity-cli/settings.json:
  "statusLine": {"type": "command", "command": "/.../statusline.py", "enabled": true}

AGY invoca questo script ad ogni tick, passando su stdin un JSON con la
struttura del payload (model, quota, agent_state, context_window, ecc.).
"""

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

# Path del file rate-limits di MAC — stessa variabile usata dal collector.
# Accetta override via env per i test.
RATE_LIMITS_PATH = Path(
    os.environ.get(
        "MAC_PROVIDER_RATE_LIMITS_PATH",
        os.path.expanduser("~/.mobile-agent-console/provider-rate-limits.json"),
    )
)

# Label leggibili per le finestre di quota AGY
WINDOW_LABELS = {
    "3p-5h": "3p 5h",
    "3p-weekly": "3p 7d",
    "gemini-5h": "gemini 5h",
    "gemini-weekly": "gemini 7d",
}


def iso_to_epoch(iso_string: str) -> int | None:
    """Converte un timestamp ISO 8601 in epoch seconds."""
    try:
        dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
        return int(dt.timestamp())
    except (ValueError, AttributeError):
        return None


def build_mac_windows(quota: dict) -> list[dict]:
    """Converte le finestre di quota AGY nel formato MAC."""
    windows = []
    for key, info in sorted(quota.items()):
        if not isinstance(info, dict):
            continue
        remaining = info.get("remaining_fraction")
        if remaining is None:
            continue
        used_percent = round((1.0 - remaining) * 100.0, 2)
        used_percent = min(max(used_percent, 0.0), 100.0)
        reset_time = info.get("reset_time", "")
        resets_at = iso_to_epoch(reset_time) if reset_time else None
        reset_seconds = info.get("reset_in_seconds", 0)
        label = WINDOW_LABELS.get(key, key)
        # Dettaglio leggibile con il reset
        if reset_time:
            detail = f"reset {reset_time}"
        elif reset_seconds:
            hours = reset_seconds // 3600
            minutes = (reset_seconds % 3600) // 60
            detail = f"reset in {hours}h{minutes:02d}m"
        else:
            detail = None
        windows.append({
            "label": label,
            "used_percent": used_percent,
            "resets_at": resets_at,
            "detail": detail,
        })
    return windows


def inject_into_rate_limits(windows: list[dict], observed_at: str) -> None:
    """Inietta la entry antigravity nel file provider-rate-limits.json."""
    path = RATE_LIMITS_PATH
    if not path.parent.exists():
        # Se la directory non esiste, MAC non è configurato qui
        return

    # Leggi il file esistente (se c'è)
    existing: dict = {}
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass

    providers: list[dict] = existing.get("providers", [])

    # Rimuovi entry antigravity precedente
    providers = [p for p in providers if p.get("provider") != "antigravity"]

    # Aggiungi la nuova entry
    providers.append({
        "provider": "antigravity",
        "available": bool(windows),
        "observed_at": observed_at,
        "windows": windows,
        "reached_type": None,
        "error": None,
    })

    payload = {
        "collected_at": existing.get("collected_at", datetime.now(UTC).isoformat()),
        "providers": providers,
    }

    # Scrivi atomicamente
    tmp = path.with_suffix(".agy-part")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def format_statusline(data: dict) -> str:
    """Genera la riga di statusline per il TUI di AGY."""
    parts = []

    # Modello
    model = data.get("model", {})
    model_name = model.get("display_name", "") if isinstance(model, dict) else str(model)
    if model_name:
        parts.append(model_name)

    # Quota più critica (la più consumata)
    quota = data.get("quota", {})
    if quota:
        worst_key = ""
        worst_used = -1.0
        for key, info in quota.items():
            if isinstance(info, dict):
                remaining = info.get("remaining_fraction", 1.0)
                used = 1.0 - remaining
                if used > worst_used:
                    worst_used = used
                    worst_key = key
        if worst_key:
            label = WINDOW_LABELS.get(worst_key, worst_key)
            pct = round(worst_used * 100)
            parts.append(f"{label}: {pct}%")

    # Stato agente
    state = data.get("agent_state", "")
    if state:
        parts.append(state)

    return " · ".join(parts) if parts else "…"


def main() -> None:
    raw = sys.stdin.read()
    if not raw.strip():
        print("…")
        return

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        print("…")
        return

    # Stampa statusline per il TUI
    print(format_statusline(data))

    # Inietta quota in MAC rate-limits (best-effort, no crash)
    try:
        quota = data.get("quota", {})
        if quota:
            windows = build_mac_windows(quota)
            observed_at = datetime.now(UTC).isoformat()
            inject_into_rate_limits(windows, observed_at)
    except Exception:
        pass  # Non rompere la statusline per un errore di scrittura


if __name__ == "__main__":
    main()
