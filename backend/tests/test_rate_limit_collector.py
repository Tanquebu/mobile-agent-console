import importlib.util
from pathlib import Path


def _collector_module():
    path = Path(__file__).parents[2] / "deploy" / "rate-limit-collector.py"
    spec = importlib.util.spec_from_file_location("rate_limit_collector", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_collector_caps_provider_percentages_above_one_hundred(monkeypatch) -> None:
    collector = _collector_module()

    class Result:
        returncode = 0
        stdout = "Aggiornato: 2026-07-30T09:06:56.126Z\n7d: 101% (reset soon)\n"
        stderr = ""

    monkeypatch.setattr(collector.subprocess, "run", lambda *args, **kwargs: Result())

    status = collector.collect("claude", "/not-used")

    assert status["available"] is True
    assert status["windows"] == [
        {"label": "7d", "used_percent": 100.0, "detail": "reset soon"}
    ]
