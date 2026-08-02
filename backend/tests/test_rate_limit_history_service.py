import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.services.rate_limit_history_service import RateLimitHistoryService


def write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def sample_row(sampled_at: str, provider: str = "claude", **overrides: object) -> dict:
    row = {
        "sampled_at": sampled_at,
        "provider": provider,
        "source": "cache",
        "observed_at": sampled_at,
        "stale": False,
        "windows": [{"label": "5h", "used_percent": 42.0, "resets_at": 1785679200}],
    }
    row.update(overrides)
    return row


def test_missing_file_returns_empty_history(tmp_path: Path) -> None:
    service = RateLimitHistoryService(str(tmp_path / "provider-rate-limits-history.jsonl"))
    history = service.read(hours=24, limit=100)
    assert history.samples == []


def test_reads_valid_jsonl_rows(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    now = datetime.now(UTC)
    write_lines(
        path,
        [
            json.dumps(sample_row(now.isoformat())),
            json.dumps(sample_row(now.isoformat(), provider="codex")),
        ],
    )
    history = RateLimitHistoryService(str(path)).read(hours=24, limit=100)
    assert len(history.samples) == 2
    assert {sample.provider for sample in history.samples} == {"claude", "codex"}


def test_corrupted_and_truncated_lines_are_ignored_without_raising(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    now = datetime.now(UTC)
    lines = [
        "not even json",
        json.dumps({"provider": "claude"}),  # manca sampled_at: riga non valida
        '{"sampled_at": "2026-08-02T09:00',  # riga troncata da una rotazione concorrente
        json.dumps(sample_row(now.isoformat())),
    ]
    write_lines(path, lines)
    history = RateLimitHistoryService(str(path)).read(hours=24, limit=100)
    assert len(history.samples) == 1
    assert history.samples[0].provider == "claude"


def test_filters_samples_outside_the_requested_horizon(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    now = datetime.now(UTC)
    old = now - timedelta(hours=48)
    write_lines(
        path,
        [
            json.dumps(sample_row(old.isoformat())),
            json.dumps(sample_row(now.isoformat())),
        ],
    )
    history = RateLimitHistoryService(str(path)).read(hours=24, limit=100)
    assert len(history.samples) == 1
    assert history.samples[0].sampled_at >= now - timedelta(hours=24)


def test_limit_caps_the_number_of_returned_samples(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    now = datetime.now(UTC)
    rows = [
        json.dumps(sample_row((now - timedelta(minutes=i)).isoformat()))
        for i in range(10, 0, -1)
    ]
    write_lines(path, rows)
    history = RateLimitHistoryService(str(path)).read(hours=24, limit=3)
    assert len(history.samples) == 3
    # Il tetto conserva la coda più recente, non le prime righe del file.
    assert history.samples[-1].sampled_at > history.samples[0].sampled_at


def test_naive_timestamp_is_normalized_to_utc(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    naive = datetime.now(UTC).replace(tzinfo=None)
    write_lines(path, [json.dumps(sample_row(naive.isoformat()))])
    history = RateLimitHistoryService(str(path)).read(hours=24, limit=100)
    assert len(history.samples) == 1
    assert history.samples[0].sampled_at.tzinfo is not None


def test_read_respects_a_byte_tail_cap(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    now = datetime.now(UTC)
    old_rows = [
        json.dumps(sample_row((now - timedelta(hours=1)).isoformat(), provider=f"p{i}"))
        for i in range(50)
    ]
    recent_row = sample_row(now.isoformat(), provider="claude")
    write_lines(path, [*old_rows, json.dumps(recent_row)])
    small_tail_bytes = len(json.dumps(recent_row).encode("utf-8")) + 40
    service = RateLimitHistoryService(str(path), max_tail_bytes=small_tail_bytes)
    history = service.read(hours=24, limit=100)
    assert len(history.samples) == 1
    assert history.samples[0].provider == "claude"
