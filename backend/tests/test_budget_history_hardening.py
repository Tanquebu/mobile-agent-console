"""Difesa degli invarianti fail-closed dei due JSONL dello storico budget.

I file sono scritti host-side da collector che ruotano e appendono mentre il
backend legge: righe troncate, valori fuori contratto e residui di versioni
diverse sono eventi attesi, non errori. Il contratto (docs/contracts/
budget-history-v1.md) impone di scartarli riga per riga senza mai propagare
un'eccezione, restituire un 500 o inventare un valore.

Questi casi nascono da una prova adversariale eseguita a mano contro il
backend in esecuzione: sono qui perché restino difesi dalla CI.
"""

import json

from app.services.rate_limit_history_service import RateLimitHistoryService
from app.services.session_usage_service import SessionUsageService

HISTORY_VALID_FIRST = {
    "sampled_at": "2026-08-02T15:00:00Z",
    "provider": "claude",
    "source": "cache",
    "stale": False,
    "windows": [{"label": "5h", "used_percent": 50.0, "resets_at": 1}],
}
HISTORY_NAIVE_TIMESTAMP = {
    "sampled_at": "2026-08-02T16:00:00",
    "provider": "claude",
    "windows": [{"label": "5h", "used_percent": 51.0, "resets_at": 1}],
}
HISTORY_EXTRA_FIELD = {
    "sampled_at": "2026-08-02T16:03:00Z",
    "provider": "claude",
    "windows": [{"label": "5h", "used_percent": 52.0, "resets_at": 2}],
    "campo_sconosciuto": "di una versione futura",
}
HISTORY_REJECTED = [
    "non-json affatto",
    json.dumps([]),
    json.dumps({"sampled_at": "2026-08-02T16:01:00Z", "provider": "c", "windows": [
        {"label": "5h", "used_percent": 999.0}]}),
    json.dumps({"sampled_at": "2026-08-02T16:02:00Z", "provider": "c", "windows": [
        {"label": "5h", "used_percent": -5}]}),
    json.dumps({"sampled_at": "non-una-data", "provider": "c", "windows": []}),
    '{"sampled_at":"2026-08-02T16:04:00Z","provider":"c","windows":[{"label":"5h","used_pe',
]


def _write(path, records) -> str:
    lines = [item if isinstance(item, str) else json.dumps(item) for item in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def test_history_keeps_only_contract_conforming_rows(tmp_path) -> None:
    path = _write(
        tmp_path / "history.jsonl",
        [HISTORY_VALID_FIRST, *HISTORY_REJECTED, HISTORY_NAIVE_TIMESTAMP, HISTORY_EXTRA_FIELD],
    )

    result = RateLimitHistoryService(path).read(hours=99999, limit=100)

    assert [window.used_percent for sample in result.samples for window in sample.windows] == [
        50.0,
        51.0,
        52.0,
    ]
    # Un timestamp naive viene normalizzato a UTC invece di essere scartato: i
    # collector scrivono sempre UTC, e un confronto fra naive e aware
    # solleverebbe a runtime durante il filtro per ore.
    assert all(sample.sampled_at.tzinfo is not None for sample in result.samples)


def test_history_survives_a_truncated_final_line(tmp_path) -> None:
    path = tmp_path / "history.jsonl"
    path.write_text(json.dumps(HISTORY_VALID_FIRST) + "\n" + '{"sampled_at":"2026', "utf-8")

    assert len(RateLimitHistoryService(str(path)).read(hours=99999, limit=100).samples) == 1


def test_session_usage_rejects_negative_counters_and_rolls_up_subagents(tmp_path) -> None:
    base = {
        "bucket_start": "2026-08-02T16:00:00Z",
        "provider": "claude",
        "origin": "mac",
        "project": "p",
        "model": "m",
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    path = _write(
        tmp_path / "usage.jsonl",
        [
            {**base, "session_uuid": "a", "is_subagent": False, "turns": 1,
             "input_tokens": 10, "output_tokens": 5},
            {**base, "session_uuid": "b", "is_subagent": False, "turns": 1,
             "input_tokens": -99, "output_tokens": 5},
            {**base, "session_uuid": "a", "is_subagent": True, "turns": 2,
             "input_tokens": 7, "output_tokens": 3},
            {"rotto": True},
        ],
    )

    entries = SessionUsageService(path).read(hours=99999, limit=10).entries

    assert [entry.session_uuid for entry in entries] == ["a"]
    entry = entries[0]
    assert (entry.own.ranking_tokens, entry.subagents.ranking_tokens) == (15, 10)
    assert entry.total.ranking_tokens == 25


def test_missing_and_empty_files_read_as_empty(tmp_path) -> None:
    empty = tmp_path / "empty.jsonl"
    empty.touch()
    missing = str(tmp_path / "assente.jsonl")

    assert RateLimitHistoryService(missing).read(hours=24, limit=10).samples == []
    assert RateLimitHistoryService(str(empty)).read(hours=24, limit=10).samples == []
    assert SessionUsageService(missing).read(hours=6, limit=10).entries == []
    assert SessionUsageService(str(empty)).read(hours=6, limit=10).entries == []
