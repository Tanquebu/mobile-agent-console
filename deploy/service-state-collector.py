#!/usr/bin/env python3
"""Scrive stato, riavvii e memoria dei servizi supervisionati in un file locale.

Esiste per la stessa ragione dell'helper Docker (ADR 011, ADR 012): il collector
di osservabilita' host gira con `PrivateTmp`, `ProtectHome` e `ProtectSystem`, e
su Ubuntu 24.04 questo lo confina nel profilo AppArmor `unprivileged_userns`,
che nega la connect() verso il bus utente di systemd e verso il socket del
demone pm2 in `~/.pm2`; `ProtectHome` da sola basterebbe a nascondere il
secondo. Leggere un file gli e' invece permesso.

Il file contiene i nomi reali di unit e app: resta sull'host con permessi 0600.
La mappatura nome -> label, la classificazione degli stati e il giudizio di
priorita' restano nel collector, che e' il punto in cui il contratto vieta i
nomi non mappati.
"""

import argparse
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

# Gli id delle unit ammettono `@` per i template e `\x2d` come escape; una unit
# che non rientra qui viene scartata invece di essere riscritta.
SAFE_UNIT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@\\-]{0,127}$")
SAFE_APP_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
SYSTEMCTL_BINARY = "/usr/bin/systemctl"
SYSTEMD_PROPERTIES = "Id,ActiveState,SubState,NRestarts,MemoryCurrent"
MAX_SERVICES = 400
MAX_OUTPUT_BYTES = 256 * 1024
SYSTEMCTL_TIMEOUT_SECONDS = 10
# `pm2 jlist` avvia un processo node: circa 0.7s sull'host di riferimento.
# Accettabile solo perche' questa unit gira a timer, mai dentro una richiesta.
PM2_TIMEOUT_SECONDS = 20


def run_command(argv: list[str], *, timeout_seconds: int) -> str | None:
    """stdout del comando, oppure None se il supervisore non e' interrogabile.

    None non significa "nessun servizio": significa che di quel supervisore non
    si sa nulla, ed e' una distinzione che arriva fino alla dashboard.
    """
    try:
        completed = subprocess.run(  # noqa: S603 - argv fisso, mai una stringa di shell
            argv,
            shell=False,
            capture_output=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0 or len(completed.stdout) > MAX_OUTPUT_BYTES:
        return None
    try:
        return completed.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return None


def parse_optional_integer(value: str) -> int | None:
    """`[not set]`, vuoto e i sentinella a 64 bit di systemd valgono "non noto"."""
    try:
        parsed = int(value)
    except ValueError:
        return None
    if parsed < 0 or parsed >= 2**63 - 1:
        return None
    return parsed


def parse_systemd_blocks(output: str) -> list[dict[str, str]]:
    """Blocchi `chiave=valore` separati da riga vuota, come li stampa `show`."""
    blocks: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in output.splitlines():
        if not line.strip():
            if current:
                blocks.append(current)
                current = {}
            continue
        key, separator, value = line.partition("=")
        if separator:
            current[key.strip()] = value.strip()
    if current:
        blocks.append(current)
    return blocks


def read_systemd(supervisor: str, extra: list[str]) -> list[dict[str, object]] | None:
    output = run_command(
        [SYSTEMCTL_BINARY, *extra, "show", "*.service", "--property", SYSTEMD_PROPERTIES],
        timeout_seconds=SYSTEMCTL_TIMEOUT_SECONDS,
    )
    if output is None:
        return None
    services: list[dict[str, object]] = []
    for block in parse_systemd_blocks(output)[:MAX_SERVICES]:
        name = block.get("Id", "")
        active = block.get("ActiveState", "")
        sub = block.get("SubState", "")
        if not SAFE_UNIT_NAME.fullmatch(name) or not active or ":" in active or ":" in sub:
            continue
        services.append(
            {
                "supervisor": supervisor,
                "name": name,
                # Stringa grezza del supervisore: la classificazione appartiene
                # al collector, come per lo stato dei container.
                "status": f"{active}:{sub}" if sub else active,
                "restarts": parse_optional_integer(block.get("NRestarts", "")),
                "memory_bytes": parse_optional_integer(block.get("MemoryCurrent", "")),
            }
        )
    return services


def read_pm2(binary: str) -> list[dict[str, object]] | None:
    output = run_command([binary, "jlist"], timeout_seconds=PM2_TIMEOUT_SECONDS)
    if output is None:
        return None
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, list):
        return None
    services: list[dict[str, object]] = []
    for item in payload[:MAX_SERVICES]:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        environment = item.get("pm2_env") if isinstance(item.get("pm2_env"), dict) else {}
        monitor = item.get("monit") if isinstance(item.get("monit"), dict) else {}
        status = environment.get("status")
        if not isinstance(name, str) or not SAFE_APP_NAME.fullmatch(name):
            continue
        restarts = environment.get("restart_time")
        memory = monitor.get("memory")
        services.append(
            {
                "supervisor": "pm2",
                "name": name,
                "status": status if isinstance(status, str) and status else "unknown",
                "restarts": restarts if isinstance(restarts, int) and 0 <= restarts else None,
                "memory_bytes": memory if isinstance(memory, int) and 0 <= memory else None,
            }
        )
    return services


def collect_state(*, pm2_binary: str | None) -> dict[str, object]:
    collected_at = datetime.now(UTC).isoformat()
    sources = {
        "systemd_system": read_systemd("systemd_system", []),
        "systemd_user": read_systemd("systemd_user", ["--user"]),
        # pm2 e' opzionale: senza binario configurato non e' "non raggiunto", e'
        # un supervisore che su questo host non esiste, quindi non compare.
        **({"pm2": read_pm2(pm2_binary)} if pm2_binary else {}),
    }
    services: list[dict[str, object]] = []
    for collected in sources.values():
        if collected is not None:
            services.extend(collected)
    return {
        "schema_version": 1,
        "collected_at": collected_at,
        # Il file viene scritto comunque: distingue "helper eseguito, nessun
        # supervisore risponde" da "helper mai eseguito", che si vede dall'eta'.
        "available": any(collected is not None for collected in sources.values()),
        # Quali supervisori hanno risposto: un supervisore muto non e' la prova
        # che i suoi servizi siano caduti, ed e' il collector a doverlo sapere.
        "supervisors": {name: collected is not None for name, collected in sources.items()},
        "services": services[:MAX_SERVICES],
        "truncated": len(services) > MAX_SERVICES,
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
    # Il path di pm2 e' locale all'utente e non appartiene al repository: arriva
    # dall'environment file privato del deployment. Vuoto = pm2 non installato.
    parser.add_argument("--pm2-binary", default="")
    args = parser.parse_args()
    pm2_binary = args.pm2_binary.strip()
    if pm2_binary and not Path(pm2_binary).is_absolute():
        parser.error("--pm2-binary must be an absolute path")
    write_state(
        Path(args.output).resolve(),
        collect_state(pm2_binary=pm2_binary or None),
    )


if __name__ == "__main__":
    main()
