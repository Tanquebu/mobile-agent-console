#!/usr/bin/env python3
"""Scrive stato e memoria dei container Docker in un file di stato locale.

Esiste perche' il collector di osservabilita' host gira con un mount namespace
(`PrivateTmp`, `ProtectHome`, `ProtectSystem`): su Ubuntu 24.04 questo lo fa
ricadere nel profilo AppArmor `unprivileged_userns`, che nega la connect() sul
socket Docker rootless. Leggere un file gli e' invece permesso, quindi la
raccolta che ha bisogno del socket vive qui, in una unit separata con hardening
calibrato sul solo compito di interrogare Docker (ADR 011).

Il file contiene i nomi reali dei container: resta sull'host con permessi 0600
e non attraversa mai il boundary. La mappatura nome -> label e la
classificazione degli stati restano nel collector di osservabilita', che e' il
punto in cui il contratto vieta i nomi non mappati.
"""

import argparse
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

SAFE_CONTAINER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
# "117MiB", "4.648MiB", "1.2GiB": il valore prima della barra in MemUsage.
MEM_USAGE = re.compile(r"^(\d+(?:\.\d+)?)\s*([KMGT]?i?B|B)$", re.IGNORECASE)
UNIT_MULTIPLIERS = {
    "b": 1,
    "kb": 1000, "kib": 1024,
    "mb": 1000**2, "mib": 1024**2,
    "gb": 1000**3, "gib": 1024**3,
    "tb": 1000**4, "tib": 1024**4,
}
DOCKER_BINARY = "/usr/bin/docker"
MAX_CONTAINERS = 200
MAX_OUTPUT_BYTES = 64 * 1024
PS_TIMEOUT_SECONDS = 5
# `docker stats` interroga ogni container: sull'host di riferimento impiega
# circa 2s. E' accettabile solo perche' questa unit gira a timer, mai dentro la
# risposta a una richiesta.
STATS_TIMEOUT_SECONDS = 20


def run_docker(arguments: list[str], *, timeout_seconds: int) -> list[str] | None:
    """Righe di output, oppure None se il comando non e' utilizzabile."""
    try:
        completed = subprocess.run(  # noqa: S603 - argv fisso, mai una stringa di shell
            [DOCKER_BINARY, *arguments],
            shell=False,
            capture_output=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0 or len(completed.stdout) > MAX_OUTPUT_BYTES:
        return None
    try:
        return completed.stdout.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return None


def parse_memory(value: str) -> int | None:
    """Byte dalla porzione usata di MemUsage (`117MiB / 3.725GiB`)."""
    used, _, _limit = value.partition("/")
    match = MEM_USAGE.fullmatch(used.strip())
    if match is None:
        return None
    amount, unit = match.groups()
    multiplier = UNIT_MULTIPLIERS.get(unit.lower())
    if multiplier is None:
        return None
    return int(float(amount) * multiplier)


def read_memory_by_name() -> dict[str, int]:
    """Memoria per container in esecuzione; i fermi semplicemente non compaiono."""
    lines = run_docker(
        ["stats", "--no-stream", "--format", "{{.Name}}\t{{.MemUsage}}"],
        timeout_seconds=STATS_TIMEOUT_SECONDS,
    )
    if lines is None:
        return {}
    memory: dict[str, int] = {}
    for line in lines[:MAX_CONTAINERS]:
        name, separator, usage = line.partition("\t")
        if not separator or not SAFE_CONTAINER_NAME.fullmatch(name):
            continue
        parsed = parse_memory(usage)
        if parsed is not None:
            memory[name] = parsed
    return memory


def collect_state() -> dict[str, object]:
    collected_at = datetime.now(UTC).isoformat()
    lines = run_docker(
        ["ps", "-a", "--format", "{{.Names}}\t{{.Status}}"],
        timeout_seconds=PS_TIMEOUT_SECONDS,
    )
    if lines is None:
        # Il file viene scritto comunque: distingue "helper eseguito, Docker non
        # risponde" da "helper mai eseguito", che si vede solo dall'eta'.
        return {
            "schema_version": 1,
            "collected_at": collected_at,
            "available": False,
            "containers": [],
            "truncated": False,
        }
    memory = read_memory_by_name()
    containers: list[dict[str, object]] = []
    for line in lines[:MAX_CONTAINERS]:
        name, separator, status = line.partition("\t")
        if (
            not separator
            or not SAFE_CONTAINER_NAME.fullmatch(name)
            or not status
            or len(status) > 256
            or "\t" in status
        ):
            continue
        containers.append(
            {"name": name, "status": status, "memory_bytes": memory.get(name)}
        )
    return {
        "schema_version": 1,
        "collected_at": collected_at,
        "available": True,
        "containers": containers,
        "truncated": len(lines) > MAX_CONTAINERS,
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
