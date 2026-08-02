import json
import os
from pathlib import Path
from typing import Any


def read_tail_records(path: Path, max_bytes: int) -> list[dict[str, Any]]:
    """Legge la coda di un JSONL scritto host-side, riga per riga.

    Una riga troncata da una rotazione concorrente è un evento atteso, non un
    errore: viene scartata insieme a tutto ciò che non decodifica, senza mai
    propagare l'eccezione al chiamante (contratto storico budget v1).
    """
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
    records = []
    for line in raw.decode("utf-8", errors="ignore").splitlines():
        try:
            item = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(item, dict):
            records.append(item)
    return records
