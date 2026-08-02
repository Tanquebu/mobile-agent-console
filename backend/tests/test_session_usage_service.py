import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.services.session_usage_service import SessionUsageService


def write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def usage_row(
    bucket_start: str,
    session_uuid: str = "5b84b3fa-a26f-4642-abf3-851fc35abf3f",
    **overrides: object,
) -> dict:
    row = {
        "bucket_start": bucket_start,
        "provider": "claude",
        "session_uuid": session_uuid,
        "origin": "headless",
        "project": "mobile-agent-console",
        "model": "claude-opus-5",
        "is_subagent": False,
        "turns": 1,
        "input_tokens": 10,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "output_tokens": 5,
    }
    row.update(overrides)
    return row


def test_missing_file_returns_empty_report(tmp_path: Path) -> None:
    service = SessionUsageService(str(tmp_path / "session-usage-history.jsonl"))
    report = service.read(hours=6, limit=50)
    assert report.entries == []
    assert report.buckets == []


def test_reads_valid_rows_and_ranks_sessions_by_ranking_tokens(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    now = datetime.now(UTC)
    write_lines(
        path,
        [
            json.dumps(usage_row(now.isoformat(), session_uuid="low", input_tokens=1)),
            json.dumps(usage_row(now.isoformat(), session_uuid="high", input_tokens=1000)),
        ],
    )
    report = SessionUsageService(str(path)).read(hours=6, limit=50)
    assert [entry.session_uuid for entry in report.entries] == ["high", "low"]


def test_corrupted_and_truncated_lines_are_ignored_without_raising(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    now = datetime.now(UTC)
    lines = [
        "not even json",
        json.dumps({"session_uuid": "x"}),  # manca bucket_start: riga non valida
        '{"bucket_start": "2026-08-02T09:00',  # riga troncata da rotazione concorrente
        json.dumps(usage_row(now.isoformat())),
    ]
    write_lines(path, lines)
    report = SessionUsageService(str(path)).read(hours=6, limit=50)
    assert len(report.buckets) == 1
    assert len(report.entries) == 1


def test_filters_rows_outside_the_requested_horizon(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    now = datetime.now(UTC)
    old = now - timedelta(hours=48)
    write_lines(
        path,
        [
            json.dumps(usage_row(old.isoformat(), session_uuid="stale")),
            json.dumps(usage_row(now.isoformat(), session_uuid="fresh")),
        ],
    )
    report = SessionUsageService(str(path)).read(hours=6, limit=50)
    assert [entry.session_uuid for entry in report.entries] == ["fresh"]


def test_subagent_rows_are_aggregated_separately_from_own(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    now = datetime.now(UTC)
    write_lines(
        path,
        [
            json.dumps(usage_row(now.isoformat(), is_subagent=False, input_tokens=10)),
            json.dumps(usage_row(now.isoformat(), is_subagent=True, input_tokens=500)),
        ],
    )
    report = SessionUsageService(str(path)).read(hours=6, limit=50)
    assert len(report.entries) == 1
    entry = report.entries[0]
    assert entry.own.input_tokens == 10
    assert entry.subagents.input_tokens == 500
    assert entry.total.input_tokens == 510


def test_origin_mac_sticks_even_if_some_buckets_were_collected_while_headless(
    tmp_path: Path,
) -> None:
    path = tmp_path / "history.jsonl"
    now = datetime.now(UTC)
    write_lines(
        path,
        [
            json.dumps(usage_row(now.isoformat(), origin="headless")),
            json.dumps(
                usage_row(
                    (now - timedelta(minutes=5)).isoformat(),
                    origin="mac",
                    tmux_session_id="162",
                )
            ),
        ],
    )
    report = SessionUsageService(str(path)).read(hours=6, limit=50)
    assert report.entries[0].origin == "mac"
    assert report.entries[0].tmux_session_id == "162"


def test_limit_caps_the_number_of_ranked_entries_not_raw_buckets(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    now = datetime.now(UTC)
    lines = [
        json.dumps(usage_row(now.isoformat(), session_uuid=f"session-{i}", input_tokens=i))
        for i in range(10)
    ]
    write_lines(path, lines)
    report = SessionUsageService(str(path)).read(hours=6, limit=3)
    assert len(report.entries) == 3
    assert len(report.buckets) == 10


def test_non_utc_offset_timestamp_is_discarded(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    now = datetime.now(UTC)
    # Stesso istante di `now`, ma scritto con un offset esplicito +02:00
    # invece che Z: deve essere scartato riga per riga, non accettato con
    # l'offset originale né normalizzato in silenzio.
    non_utc = (now + timedelta(hours=2)).replace(tzinfo=None).isoformat() + "+02:00"
    write_lines(
        path,
        [
            json.dumps(usage_row(non_utc, session_uuid="offset")),
            json.dumps(usage_row(now.isoformat(), session_uuid="utc")),
        ],
    )
    report = SessionUsageService(str(path)).read(hours=6, limit=50)
    # La riga con offset esplicito non-UTC va scartata riga per riga (contratto
    # budget-history-v1), non normalizzata né propagata come eccezione.
    assert len(report.buckets) == 1
    assert report.buckets[0].session_uuid == "utc"
    assert report.buckets[0].bucket_start.utcoffset() == timedelta(0)


def test_naive_timestamp_is_normalized_to_utc(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    naive = datetime.now(UTC).replace(tzinfo=None)
    write_lines(path, [json.dumps(usage_row(naive.isoformat()))])
    report = SessionUsageService(str(path)).read(hours=6, limit=50)
    assert len(report.buckets) == 1
    assert report.buckets[0].bucket_start.tzinfo is not None
