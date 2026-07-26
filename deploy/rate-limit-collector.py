#!/usr/bin/env python3
import argparse
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path


UPDATED = re.compile(r"^Aggiornato:\s+(\S+)")
WINDOW = re.compile(
    r"^(?P<label>5h|7d|primaria|secondaria):\s+"
    r"(?:(?P<used>[0-9]+(?:\.[0-9]+)?)%|n/d)"
    r"(?:\s+\((?P<detail>.*)\))?$"
)
REACHED = re.compile(r"^rate_limit_reached_type:\s+(.*)$")


def collect(name: str, script: str) -> dict[str, object]:
    try:
        result = subprocess.run(
            [script],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "LC_ALL": "C.UTF-8"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"provider": name, "available": False, "error": str(exc), "windows": []}
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    observed_at = None
    windows = []
    reached_type = None
    for line in lines:
        if match := UPDATED.match(line):
            observed_at = match.group(1)
        elif match := WINDOW.match(line):
            windows.append(
                {
                    "label": match.group("label"),
                    "used_percent": (
                        float(match.group("used")) if match.group("used") is not None else None
                    ),
                    "detail": match.group("detail"),
                }
            )
        elif match := REACHED.match(line):
            reached_type = match.group(1)
    available = result.returncode == 0 and bool(windows)
    error = None
    if not available:
        error = (result.stderr.strip() or "Nessun dato riconosciuto")[:500]
    return {
        "provider": name,
        "available": available,
        "observed_at": observed_at,
        "windows": windows,
        "reached_type": reached_type,
        "error": error,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--claude-script", required=True)
    parser.add_argument("--codex-script", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = {
        "collected_at": datetime.now(UTC).isoformat(),
        "providers": [
            collect("claude", args.claude_script),
            collect("codex", args.codex_script),
        ],
    }
    temporary = output.with_suffix(".part")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(output)


if __name__ == "__main__":
    main()
