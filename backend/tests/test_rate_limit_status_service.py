import json
from pathlib import Path

from app.services.rate_limit_status_service import RateLimitStatusService


def test_rate_limit_status_reads_valid_sanitized_payload(tmp_path: Path) -> None:
    path = tmp_path / "provider-rate-limits.json"
    path.write_text(
        json.dumps(
            {
                "collected_at": "2026-07-26T15:30:00+00:00",
                "providers": [
                    {
                        "provider": "codex",
                        "available": True,
                        "observed_at": "2026-07-26T17:21:41+02:00",
                        "windows": [
                            {
                                "label": "primaria",
                                "used_percent": 42,
                                "resets_at": 1786231416,
                                "detail": "finestra 10080 min",
                            }
                        ],
                        "reached_type": "nessuno",
                        "error": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    status = RateLimitStatusService(str(path)).read()
    assert status is not None
    assert status.providers[0].windows[0].used_percent == 42
    assert status.providers[0].windows[0].resets_at == 1786231416


def test_rate_limit_status_ignores_missing_or_invalid_payload(tmp_path: Path) -> None:
    path = tmp_path / "provider-rate-limits.json"
    service = RateLimitStatusService(str(path))
    assert service.read() is None
    path.write_text('{"providers":[]}', encoding="utf-8")
    assert service.read() is None
    path.write_text(
        '{"collected_at":"now","providers":[{"provider":"codex","available":true,'
        '"windows":[{"label":"primary","used_percent":101}]}]}',
        encoding="utf-8",
    )
    assert service.read() is None


def test_rate_limit_status_accepts_provider_usage_capped_at_one_hundred(tmp_path: Path) -> None:
    path = tmp_path / "provider-rate-limits.json"
    path.write_text(
        '{"collected_at":"now","providers":[{"provider":"claude","available":true,'
        '"windows":[{"label":"7d","used_percent":100}]}]}',
        encoding="utf-8",
    )
    status = RateLimitStatusService(str(path)).read()
    assert status is not None
    assert status.providers[0].windows[0].used_percent == 100


def test_rate_limit_status_accepts_legacy_window_without_reset(tmp_path: Path) -> None:
    path = tmp_path / "provider-rate-limits.json"
    path.write_text(
        '{"collected_at":"now","providers":[{"provider":"codex","available":true,'
        '"windows":[{"label":"primaria","used_percent":42}]}]}',
        encoding="utf-8",
    )
    status = RateLimitStatusService(str(path)).read()
    assert status is not None
    assert status.providers[0].windows[0].resets_at is None


def test_rate_limit_status_rejects_negative_reset_epoch(tmp_path: Path) -> None:
    path = tmp_path / "provider-rate-limits.json"
    path.write_text(
        '{"collected_at":"now","providers":[{"provider":"codex","available":true,'
        '"windows":[{"label":"primaria","used_percent":42,"resets_at":-1}]}]}',
        encoding="utf-8",
    )
    assert RateLimitStatusService(str(path)).read() is None
