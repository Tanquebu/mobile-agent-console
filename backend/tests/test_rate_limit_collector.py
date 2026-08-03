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
    # Il campo opzionale del reset estende in modo compatibile lo snapshot:
    # il fallback testuale non conosce l'epoch e pubblica quindi `None`.
    assert collector.snapshot_provider(status)["windows"] == [
        {
            "label": "7d",
            "used_percent": 100.0,
            "resets_at": None,
            "detail": "reset soon",
        }
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
    # BH-03: il parsing riuscito con la forma strutturata è un fatto
    # pubblicato, non solo interno alla funzione.
    assert status["parse_mode"] == "structured"
    assert collector.snapshot_provider(status)["windows"] == [
        {
            "label": "5h",
            "used_percent": 91.0,
            "resets_at": 1785679200,
            "detail": "reset 8/2/2026, 4:00:00 PM",
        }
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
    # Anche se `--json` è stato invocato, il contenuto restituito è testuale:
    # il fatto pubblicato deve riflettere la forma realmente usata, non
    # l'argomento passato allo script.
    assert status["parse_mode"] == "text"


def test_collector_falls_back_when_script_rejects_json_flag(monkeypatch) -> None:
    collector = _collector_module()
    calls = _script_stub(
        monkeypatch, collector, {"text": "Aggiornato: 2026-08-02T12:00:00Z\n5h: 7%\n"}
    )

    status = collector.collect("codex", "/not-used")

    assert len(calls) == 2
    assert calls[1] == ["/not-used"]
    assert status["available"] is True
    assert status["parse_mode"] == "text"


def test_collector_final_fallback_does_not_claim_text_mode_without_windows(monkeypatch) -> None:
    collector = _collector_module()
    # Script che rifiuta `--json` (exit code != 0) e fallisce anche alla
    # riesecuzione senza `--json`: nessuna delle due invocazioni produce testo
    # utile, quindi `parse_text(...)["windows"]` è vuoto sul ramo finale di
    # fallback. Difetto secondario TEST-BH-03/IMP-BH-03-R1: questo ramo
    # marcava comunque `parse_mode: "text"`, a differenza del ramo gemello
    # (script che ignora `--json` e stampa comunque testo), che già lascia
    # `parse_mode` non impostato quando il testo non produce finestre.
    calls = _script_stub(monkeypatch, collector, {})

    status = collector.collect("codex", "/not-used")

    assert len(calls) == 2
    assert calls[1] == ["/not-used"]
    assert status["available"] is False
    assert status["windows"] == []
    assert status["parse_mode"] is None


def test_collector_reports_no_parse_mode_when_the_script_cannot_run_at_all(monkeypatch) -> None:
    collector = _collector_module()

    def fake_run(argv, **_kwargs):
        raise OSError("no such file or directory")

    monkeypatch.setattr(collector.subprocess, "run", fake_run)

    status = collector.collect("codex", "/does-not-exist")

    assert status["available"] is False
    # Nessun parsing è mai stato tentato: il fatto pubblicato è "non noto",
    # non "testuale", altrimenti un'installazione senza lo script
    # apparirebbe indistinguibile da un fallback in corso.
    assert "parse_mode" not in status


def test_history_row_marks_a_frozen_source_as_stale() -> None:
    collector = _collector_module()
    sampled_at = datetime(2026, 8, 2, 13, 0, tzinfo=UTC)
    collected = {
        "provider": "claude",
        "available": True,
        "error": None,
        "source": "cache",
        "observed_at": "2026-08-02T12:00:00Z",
        "parse_mode": "structured",
        "windows": [{"label": "5h", "used_percent": 58.0, "resets_at": 1, "detail": None}],
    }

    fresh = collector.history_row(collected, sampled_at, 7200)
    stale = collector.history_row(collected, sampled_at, 600)

    assert fresh["stale"] is False
    assert stale["stale"] is True
    assert stale["windows"] == [{"label": "5h", "used_percent": 58.0, "resets_at": 1}]
    # BH-03: la riga storica pubblica quale forma ha prodotto il campione.
    assert fresh["parse_mode"] == "structured"


def test_history_row_propagates_absent_parse_mode_as_none() -> None:
    collector = _collector_module()
    sampled_at = datetime(2026, 8, 2, 13, 0, tzinfo=UTC)
    collected = {
        "provider": "codex",
        "available": False,
        "error": "no such file or directory",
        "windows": [],
    }

    row = collector.history_row(collected, sampled_at, 600)

    assert row["parse_mode"] is None


def test_observation_key_changes_when_only_parse_mode_changes() -> None:
    collector = _collector_module()
    base = {
        "observed_at": "2026-08-02T12:00:00Z",
        "error": None,
        "windows": [{"label": "5h", "used_percent": 58.0, "resets_at": None}],
    }
    structured = {**base, "parse_mode": "structured"}
    textual = {**base, "parse_mode": "text"}

    # Stessi `observed_at`/`error`/`windows`: se cambia soltanto la forma con
    # cui la riga è stata prodotta, è comunque un fatto nuovo da pubblicare
    # (contratto BH-03), non un duplicato da scartare in deduplica.
    assert collector.observation_key(structured) != collector.observation_key(textual)


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


def test_history_appends_a_new_row_when_only_parse_mode_changes(tmp_path, monkeypatch) -> None:
    collector = _collector_module()
    history = tmp_path / "history.jsonl"
    text = "Aggiornato: 2026-08-02T12:00:00Z\n5h: 42%\n"
    structured = json.dumps(
        {
            "updated_at": "2026-08-02T12:00:00Z",
            "source": "cache",
            "windows": [{"label": "5h", "used_percent": 42, "resets_at": None}],
        }
    )
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

    # Primo giro: la forma strutturata riesce.
    _script_stub(monkeypatch, collector, {"json": structured})
    collector.main()
    # Secondo giro: stessa osservazione (`observed_at`/percentuali invariati),
    # ma la sorgente è degradata al parsing testuale.
    _script_stub(monkeypatch, collector, {"text": text})
    collector.main()

    rows = [json.loads(line) for line in history.read_text().splitlines()]
    claude_rows = [row for row in rows if row["provider"] == "claude"]
    # Il fallback silenzioso è esattamente ciò che BH-03 chiude: una
    # transizione da strutturato a testuale, a parità di `observed_at` e
    # percentuali, deve produrre una seconda riga, non essere scartata dalla
    # deduplica come se nulla fosse cambiato.
    assert [row["parse_mode"] for row in claude_rows] == ["structured", "text"]
