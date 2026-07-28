#!/usr/bin/env python3
"""Copy an external orchestrator's read-only state into a sanitized workspace."""

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


PROVIDERS = {"claude", "codex"}
STATUSES = {"new", "draft", "in_progress", "paused_provider", "error", "failed"}


def string(value: object, limit: int) -> str | None:
    return value if isinstance(value, str) and len(value) <= limit else None


def window(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    used = value.get("used_percent")
    minutes = value.get("window_minutes")
    reset = value.get("resets_at")
    if not isinstance(used, (int, float)) or not 0 <= used <= 100:
        return None
    if minutes is not None and (not isinstance(minutes, int) or not 0 <= minutes <= 20000):
        return None
    if reset is not None and (not isinstance(reset, int) or reset < 0):
        return None
    return {"used_percent": float(used), "window_minutes": minutes, "resets_at": reset}


def sanitize(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("payload non valido")
    providers = []
    for item in payload.get("providers", []):
        if not isinstance(item, dict) or item.get("provider") not in PROVIDERS:
            continue
        available = item.get("available")
        if available is not None and not isinstance(available, bool):
            continue
        providers.append({
            "provider": item["provider"],
            "available": available,
            "observed_at": string(item.get("observed_at"), 64),
            "primary": window(item.get("primary")),
            "secondary": window(item.get("secondary")),
        })
    tasks = []
    for item in payload.get("tasks", []):
        if not isinstance(item, dict):
            continue
        task_id = string(item.get("task_id"), 64)
        task_kind = string(item.get("task_kind"), 128)
        provider = item.get("provider")
        status = item.get("status")
        if not task_id or task_kind is None or provider not in PROVIDERS or status not in STATUSES:
            continue
        phase = item.get("phase")
        safe_phase = None
        if isinstance(phase, dict):
            index, total, name, interruptible = (
                phase.get("index"), phase.get("total"), phase.get("name"), phase.get("interruptible")
            )
            if (
                isinstance(index, int) and isinstance(total, int) and 0 <= index <= total <= 100
                and isinstance(name, str) and len(name) <= 128 and isinstance(interruptible, bool)
            ):
                safe_phase = {"index": index, "total": total, "name": name, "interruptible": interruptible}
        fallbacks = item.get("fallback_providers")
        if not isinstance(fallbacks, list):
            fallbacks = []
        tasks.append({
            "task_id": task_id,
            "task_kind": task_kind,
            "status": status,
            "provider": provider,
            "execution_mode": "phased" if item.get("execution_mode") == "phased" else "atomic",
            "phase": safe_phase,
            "capacity_paused": item.get("capacity_paused") is True,
            "next_attempt_at": string(item.get("next_attempt_at"), 64),
            "fallback_providers": [provider for provider in fallbacks if provider in PROVIDERS],
            "checkpoint_present": item.get("checkpoint_present") is True,
        })
    return {
        "schema_version": 1,
        "collected_at": datetime.now(UTC).isoformat(),
        "providers": providers,
        "tasks": tasks,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    url = os.environ.get("MAC_ORCHESTRATOR_STATE_URL")
    token = os.environ.get("MAC_ORCHESTRATOR_STATE_TOKEN")
    token_header = os.environ.get("MAC_ORCHESTRATOR_STATE_TOKEN_HEADER", "Authorization")
    if not url:
        raise SystemExit("MAC_ORCHESTRATOR_STATE_URL non configurata")
    if not token:
        raise SystemExit("MAC_ORCHESTRATOR_STATE_TOKEN non configurata")
    request = Request(url, headers={token_header: token})
    try:
        with urlopen(request, timeout=10) as response:
            raw = response.read(256 * 1024 + 1)
    except URLError as exc:
        raise SystemExit(f"orchestratore non disponibile: {exc.reason}") from exc
    if len(raw) > 256 * 1024:
        raise SystemExit("risposta orchestratore troppo grande")
    try:
        payload = sanitize(json.loads(raw))
    except (ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"risposta orchestratore non valida: {exc}") from exc
    output = Path(args.output).resolve()
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = output.with_suffix(".part")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(output)


if __name__ == "__main__":
    main()
