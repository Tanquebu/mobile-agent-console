import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path


def _collector_module():
    path = Path(__file__).parents[2] / "deploy" / "rate-limit-collector.py"
    spec = importlib.util.spec_from_file_location("rate_limit_collector", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Result:
    def __init__(self, stdout: str, returncode: int = 0, stderr: str = "") -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def _script_stub(monkeypatch, collector, responses: dict[str, str]) -> list[list[str]]:
    """Risponde in base alla presenza di `--json` nell'argv, registrando le chiamate."""
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        calls.append(list(argv))
        key = "json" if "--json" in argv else "text"
        if key not in responses:
            return _Result("", returncode=2, stderr="unknown option")
        return _Result(responses[key])

    monkeypatch.setattr(collector.subprocess, "run", fake_run)
    return calls


def test_collector_caps_provider_percentages_above_one_hundred(monkeypatch) -> None:
    collector = _collector_module()
    _script_stub(
        monkeypatch,
        collector,
        {"text": "Aggiornato: 2026-07-30T09:06:56.126Z\n7d: 101% (reset soon)\n"},
    )

    status = collector.collect("claude", "/not-used")

    assert status["available"] is True
    # Il contratto pubblicato di `provider-rate-limits.json` non cambia: la
    # proiezione dello snapshot resta esattamente quella storica.
    assert collector.snapshot_provider(status)["windows"] == [
        {"label": "7d", "used_percent": 100.0, "detail": "reset soon"}
    ]


def test_collector_prefers_structured_form_and_keeps_reset_epoch(monkeypatch) -> None:
    collector = _collector_module()
    payload = json.dumps(
        {
            "updated_at": "2026-08-02T12:56:13.758Z",
            "source": "fresh",
            "windows": [
                {
                    "label": "5h",
                    "used_percent": 91,
                    "resets_at": 1785679200,
                    "detail": "reset 8/2/2026, 4:00:00 PM",
                }
            ],
        }
    )
    calls = _script_stub(monkeypatch, collector, {"json": payload})

    status = collector.collect("claude", "/not-used")

    assert [call[-1] for call in calls] == ["--json"]
    assert status["source"] == "fresh"
    assert status["windows"][0]["resets_at"] == 1785679200
    assert collector.snapshot_provider(status)["windows"] == [
        {"label": "5h", "used_percent": 91.0, "detail": "reset 8/2/2026, 4:00:00 PM"}
    ]


def test_collector_reuses_text_output_when_script_ignores_json_flag(monkeypatch) -> None:
    collector = _collector_module()
    text = "Aggiornato: 2026-08-02T12:56:13.758Z [cache statusline]\n5h: 42%\n"
    calls = _script_stub(monkeypatch, collector, {"json": text, "text": text})

    status = collector.collect("claude", "/not-used")

    # Uno script che ignora gli argomenti sconosciuti ha già stampato la forma
    # testuale: non si paga una seconda esecuzione.
    assert len(calls) == 1
    assert status["available"] is True
    assert status["windows"][0]["resets_at"] is None


def test_collector_falls_back_when_script_rejects_json_flag(monkeypatch) -> None:
    collector = _collector_module()
    calls = _script_stub(
        monkeypatch, collector, {"text": "Aggiornato: 2026-08-02T12:00:00Z\n5h: 7%\n"}
    )

    status = collector.collect("codex", "/not-used")

    assert len(calls) == 2
    assert calls[1] == ["/not-used"]
    assert status["available"] is True


def test_history_row_marks_a_frozen_source_as_stale() -> None:
    collector = _collector_module()
    sampled_at = datetime(2026, 8, 2, 13, 0, tzinfo=UTC)
    collected = {
        "provider": "claude",
        "available": True,
        "error": None,
        "source": "cache",
        "observed_at": "2026-08-02T12:00:00Z",
        "windows": [{"label": "5h", "used_percent": 58.0, "resets_at": 1, "detail": None}],
    }

    fresh = collector.history_row(collected, sampled_at, 7200)
    stale = collector.history_row(collected, sampled_at, 600)

    assert fresh["stale"] is False
    assert stale["stale"] is True
    assert stale["windows"] == [{"label": "5h", "used_percent": 58.0, "resets_at": 1}]


def test_history_appends_only_changed_observations(tmp_path, monkeypatch) -> None:
    collector = _collector_module()
    history = tmp_path / "history.jsonl"
    text = "Aggiornato: 2026-08-02T12:00:00Z\n5h: 42%\n"
    _script_stub(monkeypatch, collector, {"text": text, "json": text})
    monkeypatch.setattr(
        "sys.argv",
        [
            "rate-limit-collector.py",
            "--output",
            str(tmp_path / "snapshot.json"),
            "--history-output",
            str(history),
            "--claude-script",
            "/not-used",
            "--codex-script",
            "/not-used",
        ],
    )

    collector.main()
    collector.main()

    rows = [json.loads(line) for line in history.read_text().splitlines()]
    # Due provider al primo giro, nessuna riga al secondo: una sorgente ferma
    # non produce campioni.
    assert len(rows) == 2
    assert {row["provider"] for row in rows} == {"claude", "codex"}
    assert history.stat().st_mode & 0o777 == 0o600
