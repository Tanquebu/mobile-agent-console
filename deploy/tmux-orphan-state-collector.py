#!/usr/bin/env python3
"""Rileva scope tmux ancora attivi dopo la scomparsa del relativo pane.

L'helper gira sull'host per poter raggiungere sia il socket tmux predefinito sia
il bus systemd utente. Nel file 0600 non scrive command line, cwd, nomi di
sessione o identificativi degli scope: solo il PID originario del pane, eta' e
contatori di risorse gia' aggregati da systemd.
"""

import argparse
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

SYSTEMCTL_BINARY = "/usr/bin/systemctl"
TMUX_BINARY = "/usr/bin/tmux"
UNIT_PATTERN = re.compile(r"^tmux-spawn-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\.scope$")
DESCRIPTION_PATTERN = re.compile(r"^tmux child pane ([1-9][0-9]{0,9}) launched by process [1-9][0-9]{0,9}$")
PROPERTIES = "Id,Description,ActiveEnterTimestampMonotonic,MemoryCurrent,MemoryPeak,MemorySwapCurrent,TasksCurrent"
MAX_SCOPES = 1000
MAX_OUTPUT_BYTES = 256 * 1024
TIMEOUT_SECONDS = 10


def run_command(argv: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            argv,
            shell=False,
            capture_output=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0 or len(completed.stdout) > MAX_OUTPUT_BYTES:
        return None
    try:
        return completed.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return None


def parse_blocks(output: str) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in output.splitlines():
        if not line:
            if current:
                blocks.append(current)
                current = {}
            continue
        key, separator, value = line.partition("=")
        if separator:
            current[key] = value
    if current:
        blocks.append(current)
    return blocks


def optional_integer(value: str, *, maximum: int = 2**63 - 2) -> int | None:
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if 0 <= parsed <= maximum else None


def collect_state(*, monotonic_seconds: float | None = None) -> dict[str, object]:
    pane_output = run_command([TMUX_BINARY, "list-panes", "-a", "-F", "#{pane_pid}"])
    scope_output = run_command(
        [SYSTEMCTL_BINARY, "--user", "show", "tmux-spawn-*.scope", "--property", PROPERTIES]
    )
    available = pane_output is not None and scope_output is not None
    live_panes = {
        int(line) for line in (pane_output or "").splitlines() if line.isascii() and line.isdigit()
    }
    now_monotonic_us = int(
        (monotonic_seconds if monotonic_seconds is not None else float(Path("/proc/uptime").read_text(encoding="ascii").split()[0]))
        * 1_000_000
    )
    orphans: list[dict[str, int | None]] = []
    scanned = 0
    if available:
        for block in parse_blocks(scope_output or ""):
            unit = block.get("Id", "")
            match = DESCRIPTION_PATTERN.fullmatch(block.get("Description", ""))
            if not UNIT_PATTERN.fullmatch(unit) or match is None:
                continue
            scanned += 1
            pane_pid = int(match.group(1))
            if pane_pid in live_panes:
                continue
            entered_us = optional_integer(block.get("ActiveEnterTimestampMonotonic", ""))
            age = 0 if entered_us is None else max(0, (now_monotonic_us - entered_us) // 1_000_000)
            orphans.append(
                {
                    "pane_pid": pane_pid,
                    "age_seconds": min(age, 2**31 - 1),
                    "tasks": optional_integer(block.get("TasksCurrent", ""), maximum=4096),
                    "memory_bytes": optional_integer(block.get("MemoryCurrent", "")),
                    "memory_peak_bytes": optional_integer(block.get("MemoryPeak", "")),
                    "swap_bytes": optional_integer(block.get("MemorySwapCurrent", "")),
                }
            )
    orphans.sort(key=lambda item: (-(item["memory_bytes"] or 0), item["pane_pid"]))
    return {
        "schema_version": 1,
        "collected_at": datetime.now(UTC).isoformat(),
        "available": available,
        "scanned_scopes": min(scanned, MAX_SCOPES),
        "orphans": orphans[:MAX_SCOPES],
        "truncated": len(orphans) > MAX_SCOPES,
    }


def write_state(output: Path, payload: dict[str, object]) -> None:
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = output.with_suffix(".part")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    write_state(Path(args.output).resolve(), collect_state())


if __name__ == "__main__":
    main()
