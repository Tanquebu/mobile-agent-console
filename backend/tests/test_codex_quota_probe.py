"""Test per deploy/codex-quota-probe.py.

Il modulo viene caricato per path assoluto come tutti gli altri test dei
collector in deploy/, usando parents[2] che nel container Docker risolve a
/deploy/codex-quota-probe.py.

Copertura: gate decisionale, parsing JSONL, timeout/SIGTERM/SIGKILL/reap,
lock concorrente, riconciliazione task, persistenza atomica.
Nessun test effettua richieste reali al provider.
"""
import importlib.util
import json
import os
import signal
import subprocess
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch


def _probe_module():
    path = Path(__file__).parents[2] / "deploy" / "codex-quota-probe.py"
    spec = importlib.util.spec_from_file_location("codex_quota_probe", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = _probe_module()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_snapshot(used_percent=90.0, observed_at=None, windows=None):
    w = windows if windows is not None else [
        {"label": "7d", "used_percent": used_percent, "resets_at": None, "detail": None}
    ]
    return {
        "provider": "codex",
        "available": used_percent < 100.0,
        "observed_at": observed_at,
        "windows": w,
        "reached_type": None,
        "error": None,
    }


def old_ts(minutes: int = 90) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat()


def recent_ts(minutes: int = 30) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat()


# ---------------------------------------------------------------------------
# 1. Gate decisionale – should_probe
# ---------------------------------------------------------------------------

def test_snapshot_under_threshold_skipped() -> None:
    snap = make_snapshot(used_percent=70.0, observed_at=old_ts())
    result = probe.should_probe(snap, [], datetime.now(UTC), 80.0)
    assert result == "skipped_budget_available"


def test_snapshot_exactly_at_threshold_probes() -> None:
    snap = make_snapshot(used_percent=80.0, observed_at=old_ts())
    result = probe.should_probe(snap, [], datetime.now(UTC), 80.0)
    assert result == "probe"


def test_snapshot_above_threshold_probes() -> None:
    snap = make_snapshot(used_percent=95.0, observed_at=old_ts())
    result = probe.should_probe(snap, [], datetime.now(UTC), 80.0)
    assert result == "probe"


def test_recent_sample_blocks_probe() -> None:
    snap = make_snapshot(used_percent=95.0, observed_at=recent_ts(30))
    result = probe.should_probe(snap, [], datetime.now(UTC), 80.0)
    assert result == "skipped_recent_sample"


def test_boundary_59min59s_is_recent() -> None:
    ts = (datetime.now(UTC) - timedelta(minutes=59, seconds=59)).isoformat()
    snap = make_snapshot(used_percent=95.0, observed_at=ts)
    # threshold=80.0: 95.0 >= 80.0, quindi si arriva al gate temporale
    result = probe.should_probe(snap, [], datetime.now(UTC), 80.0)
    assert result == "skipped_recent_sample"


def test_boundary_exactly_60min_is_not_recent() -> None:
    ts = (datetime.now(UTC) - timedelta(minutes=60)).isoformat()
    snap = make_snapshot(used_percent=95.0, observed_at=ts)
    # threshold=80.0: 95.0 >= 80.0, quindi si arriva al gate temporale
    result = probe.should_probe(snap, [], datetime.now(UTC), 80.0)
    assert result == "probe"


def test_no_suspended_tasks_probe_admitted() -> None:
    snap = make_snapshot(used_percent=95.0, observed_at=old_ts())
    # threshold=80.0: verifica che l'assenza di task sospesi non blocchi la sonda
    result = probe.should_probe(snap, [], datetime.now(UTC), 80.0)
    assert result == "probe"


def test_empty_windows_skipped() -> None:
    snap = {"windows": [], "observed_at": old_ts()}
    result = probe.should_probe(snap, [], datetime.now(UTC), 100.0)
    assert result == "skipped_budget_available"


def test_missing_windows_key_skipped() -> None:
    result = probe.should_probe({}, [], datetime.now(UTC), 100.0)
    assert result == "skipped_budget_available"


def test_window_missing_percent_skipped() -> None:
    snap = {"windows": [{"label": "7d"}], "observed_at": old_ts()}
    result = probe.should_probe(snap, [], datetime.now(UTC), 100.0)
    assert result == "skipped_budget_available"


def test_invalid_observed_at_treated_as_old() -> None:
    snap = make_snapshot(used_percent=95.0, observed_at="not-a-date")
    # threshold=80.0: 95.0 >= 80.0, si arriva al gate temporale;
    # observed_at non parsabile deve essere trattato come stantio -> "probe"
    result = probe.should_probe(snap, [], datetime.now(UTC), 80.0)
    assert result == "probe"


# ---------------------------------------------------------------------------
# 2. effective_threshold
# ---------------------------------------------------------------------------

def test_no_tasks_returns_100() -> None:
    assert probe.effective_threshold({}, []) == 100.0


def test_task_with_more_restrictive_threshold() -> None:
    tasks = [{"provider": "codex", "status": "paused_provider", "capacity_threshold": 70.0}]
    assert probe.effective_threshold({}, tasks) == 70.0


def test_task_without_threshold_uses_default() -> None:
    tasks = [{"provider": "codex", "status": "paused_provider"}]
    assert probe.effective_threshold({}, tasks) == 100.0


def test_most_restrictive_threshold_wins() -> None:
    tasks = [
        {"provider": "codex", "status": "paused_provider", "capacity_threshold": 80.0},
        {"provider": "codex", "status": "paused_provider", "capacity_threshold": 60.0},
    ]
    assert probe.effective_threshold({}, tasks) == 60.0


def test_other_provider_threshold_ignored() -> None:
    tasks = [{"provider": "claude", "status": "paused_provider", "capacity_threshold": 10.0}]
    assert probe.effective_threshold({}, tasks) == 100.0


def test_non_paused_task_threshold_ignored() -> None:
    tasks = [{"provider": "codex", "status": "in_progress", "capacity_threshold": 10.0}]
    assert probe.effective_threshold({}, tasks) == 100.0


# ---------------------------------------------------------------------------
# 3. last_valid_codex_snapshot
# ---------------------------------------------------------------------------

def test_returns_codex_entry(tmp_path) -> None:
    p = tmp_path / "snap.json"
    p.write_text(json.dumps({"providers": [
        {"provider": "claude", "windows": []},
        {"provider": "codex", "windows": [{"label": "7d", "used_percent": 80.0}]},
    ]}), encoding="utf-8")
    result = probe.last_valid_codex_snapshot(str(p))
    assert result is not None
    assert result["provider"] == "codex"


def test_missing_snapshot_returns_none() -> None:
    assert probe.last_valid_codex_snapshot("/nonexistent/path.json") is None


def test_malformed_json_returns_none(tmp_path) -> None:
    p = tmp_path / "snap.json"
    p.write_text("not json", encoding="utf-8")
    assert probe.last_valid_codex_snapshot(str(p)) is None


def test_no_codex_provider_returns_none(tmp_path) -> None:
    p = tmp_path / "snap.json"
    p.write_text(json.dumps({"providers": [{"provider": "claude", "windows": []}]}), encoding="utf-8")
    assert probe.last_valid_codex_snapshot(str(p)) is None


def test_codex_without_windows_list_returns_none(tmp_path) -> None:
    p = tmp_path / "snap.json"
    p.write_text(json.dumps({"providers": [{"provider": "codex", "windows": "bad"}]}), encoding="utf-8")
    assert probe.last_valid_codex_snapshot(str(p)) is None


# ---------------------------------------------------------------------------
# 4. parse_rate_limits_from_jsonl
# ---------------------------------------------------------------------------

def test_extracts_last_valid_windows_event() -> None:
    data = (
        b'{"event": "other"}\n'
        b'{"windows": [{"used_percent": 50}], "updated_at": "2026-08-15T00:00:00+00:00"}\n'
        b'{"event": "after"}\n'
    )
    result = probe.parse_rate_limits_from_jsonl(data, 4096)
    assert result is not None
    assert result["windows"][0]["used_percent"] == 50


def test_multiple_windows_events_selects_last() -> None:
    data = (
        b'{"windows": [{"used_percent": 50}]}\n'
        b'{"windows": [{"used_percent": 99}]}\n'
    )
    result = probe.parse_rate_limits_from_jsonl(data, 4096)
    assert result is not None
    assert result["windows"][0]["used_percent"] == 99


def test_no_windows_event_returns_none() -> None:
    data = b'{"event": "foo"}\n{"bar": 1}\n'
    assert probe.parse_rate_limits_from_jsonl(data, 4096) is None


def test_empty_data_returns_none() -> None:
    assert probe.parse_rate_limits_from_jsonl(b"", 4096) is None


def test_max_bytes_truncates_input() -> None:
    # Evento valido completamente troncato a 5 byte: non parsabile
    valid_event = b'{"windows": [{"used_percent": 75}]}'
    result = probe.parse_rate_limits_from_jsonl(valid_event, 5)
    assert result is None


def test_partially_truncated_line_ignored() -> None:
    data = b'{"windows": [{"used_percent":'
    assert probe.parse_rate_limits_from_jsonl(data, 4096) is None


# ---------------------------------------------------------------------------
# 5. compute_reconciliation
# ---------------------------------------------------------------------------

def test_task_under_threshold_gets_resume() -> None:
    tasks = [{"task_id": "t1", "provider": "codex", "status": "paused_provider",
              "capacity_threshold": 80.0}]
    snap = {"windows": [{"used_percent": 70.0, "resets_at": None}]}
    muts = probe.compute_reconciliation(tasks, snap, datetime.now(UTC))
    assert len(muts) == 1
    assert muts[0]["action"] == "resume"
    assert muts[0]["status"] == "new"
    assert muts[0]["pause_reason"] is None
    assert muts[0]["next_attempt_at"] is None


def test_task_over_threshold_with_reset_gets_reschedule() -> None:
    future_reset = int(datetime.now(UTC).timestamp()) + 3600
    tasks = [{"task_id": "t1", "provider": "codex", "status": "paused_provider",
              "capacity_threshold": 80.0}]
    snap = {"windows": [{"used_percent": 90.0, "resets_at": future_reset}]}
    muts = probe.compute_reconciliation(tasks, snap, datetime.now(UTC))
    assert len(muts) == 1
    assert muts[0]["action"] == "reschedule"
    assert "next_attempt_at" in muts[0]


def test_task_over_threshold_no_reset_no_mutation() -> None:
    tasks = [{"task_id": "t1", "provider": "codex", "status": "paused_provider",
              "capacity_threshold": 80.0}]
    snap = {"windows": [{"used_percent": 90.0, "resets_at": None}]}
    muts = probe.compute_reconciliation(tasks, snap, datetime.now(UTC))
    assert len(muts) == 0


def test_no_suspended_tasks_no_mutations() -> None:
    muts = probe.compute_reconciliation([], {"windows": [{"used_percent": 10.0}]},
                                        datetime.now(UTC))
    assert muts == []


def test_multiple_tasks_different_thresholds() -> None:
    future_reset = int(datetime.now(UTC).timestamp()) + 3600
    tasks = [
        {"task_id": "t1", "provider": "codex", "status": "paused_provider",
         "capacity_threshold": 80.0},
        {"task_id": "t2", "provider": "codex", "status": "paused_provider",
         "capacity_threshold": 95.0},
    ]
    snap = {"windows": [{"used_percent": 90.0, "resets_at": future_reset}]}
    muts = probe.compute_reconciliation(tasks, snap, datetime.now(UTC))
    actions = {m["task_id"]: m["action"] for m in muts}
    assert actions["t1"] == "reschedule"
    assert actions["t2"] == "resume"


def test_provider_available_no_tasks_empty_mutations() -> None:
    muts = probe.compute_reconciliation([], {"windows": [{"used_percent": 5.0}]},
                                        datetime.now(UTC))
    assert muts == []


def test_other_provider_task_ignored_in_reconciliation() -> None:
    tasks = [{"task_id": "c1", "provider": "claude", "status": "paused_provider",
              "capacity_threshold": 10.0}]
    muts = probe.compute_reconciliation(tasks, {"windows": [{"used_percent": 5.0}]},
                                        datetime.now(UTC))
    assert muts == []


# ---------------------------------------------------------------------------
# 6. Lock concorrente
# ---------------------------------------------------------------------------

def test_lock_acquired(tmp_path) -> None:
    lp = str(tmp_path / "probe.lock")
    with probe.acquire_lock(lp) as fd:
        assert fd is not None


def test_concurrent_lock_blocked(tmp_path) -> None:
    lp = str(tmp_path / "probe.lock")
    with probe.acquire_lock(lp) as fd1:
        assert fd1 is not None
        with probe.acquire_lock(lp) as fd2:
            assert fd2 is None


def test_lock_released_after_context(tmp_path) -> None:
    lp = str(tmp_path / "probe.lock")
    with probe.acquire_lock(lp):
        pass
    with probe.acquire_lock(lp) as fd:
        assert fd is not None


def test_lock_released_on_exception(tmp_path) -> None:
    lp = str(tmp_path / "probe.lock")
    try:
        with probe.acquire_lock(lp):
            raise RuntimeError("test")
    except RuntimeError:
        pass
    with probe.acquire_lock(lp) as fd:
        assert fd is not None


def test_concurrent_lock_from_thread(tmp_path) -> None:
    """Doppia invocazione concorrente da thread: la seconda ottiene None."""
    lp = str(tmp_path / "probe.lock")
    results: list = []
    barrier = threading.Barrier(2)

    def second_thread():
        barrier.wait()  # aspetta che il thread principale abbia il lock
        with probe.acquire_lock(lp) as fd:
            results.append(fd)

    with probe.acquire_lock(lp) as fd1:
        assert fd1 is not None
        t = threading.Thread(target=second_thread)
        t.start()
        barrier.wait()
        t.join(timeout=3)

    assert results == [None]


# ---------------------------------------------------------------------------
# 7. run_probe – terminazione e sicurezza
# ---------------------------------------------------------------------------

def test_no_shell_flag_in_popen() -> None:
    """Verifica che Popen venga chiamato con shell=False."""
    with patch("subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_proc.pid = 999
        mock_proc.returncode = 0
        mock_proc.poll.return_value = 0
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.fileno.return_value = -1
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.fileno.return_value = -1
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        with patch("os.getpgid", return_value=999), \
             patch("selectors.DefaultSelector") as mock_sel_cls:
            mock_sel = MagicMock()
            mock_sel.get_map.return_value = {}
            mock_sel.select.return_value = []
            mock_sel_cls.return_value = mock_sel
            probe.run_probe("/fake/codex", 0, "/tmp", 1024)

    _, kwargs = mock_popen.call_args
    assert kwargs.get("shell", False) is False


def test_timeout_triggers_sigterm_then_sigkill() -> None:
    """Scadenza del timeout -> SIGTERM -> wait scade -> SIGKILL -> reap."""
    with patch("subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_proc.pid = 1234
        mock_proc.returncode = None
        mock_proc.poll.return_value = None
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.fileno.return_value = -1
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.fileno.return_value = -1
        mock_proc.wait.side_effect = [subprocess.TimeoutExpired("cmd", 5.0), None]
        mock_popen.return_value = mock_proc

        with patch("os.getpgid", return_value=1234), \
             patch("os.killpg") as mock_kill, \
             patch("selectors.DefaultSelector") as mock_sel_cls:
            mock_sel = MagicMock()
            mock_sel.get_map.return_value = {}
            mock_sel.select.return_value = []
            mock_sel_cls.return_value = mock_sel
            probe.run_probe("/fake/codex", 0, "/tmp", 1024)

    sigs = [c.args[1] for c in mock_kill.call_args_list]
    assert signal.SIGTERM in sigs
    assert signal.SIGKILL in sigs


def test_sigterm_not_sent_when_process_already_exited() -> None:
    """Se il processo è già terminato, SIGTERM non viene inviato al pgid."""
    with patch("subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_proc.pid = 4242
        mock_proc.returncode = 0
        mock_proc.poll.return_value = 0  # già terminato
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.fileno.return_value = -1
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.fileno.return_value = -1
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        with patch("os.getpgid", return_value=4242), \
             patch("os.killpg") as mock_kill, \
             patch("selectors.DefaultSelector") as mock_sel_cls:
            mock_sel = MagicMock()
            mock_sel.get_map.return_value = {}
            mock_sel.select.return_value = []
            mock_sel_cls.return_value = mock_sel
            probe.run_probe("/fake/codex", 0, "/tmp", 1024)

    sigs = [c.args[1] for c in mock_kill.call_args_list]
    assert signal.SIGTERM not in sigs


def test_oserror_on_popen_returns_false() -> None:
    with patch("subprocess.Popen", side_effect=OSError("no such file")):
        success, raw, _ = probe.run_probe("/nonexistent", 10, "/tmp", 1024)
    assert success is False
    assert raw == b""


def test_stdout_capped_at_max_bytes() -> None:
    """Il buffer stdout non supera max_output_bytes."""
    chunk = b"A" * 200

    with patch("subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_proc.pid = 5555
        mock_proc.returncode = 0
        mock_proc.poll.return_value = 0
        stdout_mock = MagicMock()
        stdout_mock.fileno.return_value = 10
        stderr_mock = MagicMock()
        stderr_mock.fileno.return_value = 11
        mock_proc.stdout = stdout_mock
        mock_proc.stderr = stderr_mock
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        with patch("os.getpgid", return_value=5555), \
             patch("selectors.DefaultSelector") as mock_sel_cls:
            mock_sel = MagicMock()
            stdout_key = MagicMock()
            stdout_key.fd = 10
            stdout_key.fileobj = stdout_mock
            stdout_key.data = "stdout"
            mock_sel.get_map.side_effect = [{"k": 1}, {}]
            mock_sel.select.return_value = [(stdout_key, None)]
            mock_sel_cls.return_value = mock_sel

            with patch("os.read", return_value=chunk):
                _, raw, _ = probe.run_probe("/fake", 10, "/tmp", 50)

    assert len(raw) <= 50


# ---------------------------------------------------------------------------
# 8. update_snapshot e append_history
# ---------------------------------------------------------------------------

def test_update_snapshot_replaces_codex_preserves_other(tmp_path) -> None:
    p = tmp_path / "snap.json"
    initial = {"collected_at": "old", "providers": [
        {"provider": "codex", "available": False, "windows": [],
         "observed_at": None, "reached_type": None, "error": "old"},
        {"provider": "claude", "available": True, "windows": [],
         "observed_at": None, "reached_type": None, "error": None},
    ]}
    p.write_text(json.dumps(initial), encoding="utf-8")
    new_codex = {"provider": "codex", "available": True,
                 "windows": [{"used_percent": 5.0}],
                 "observed_at": "now", "reached_type": None, "error": None}
    probe.update_snapshot(str(p), new_codex, "new_ts")
    result = json.loads(p.read_text())
    assert result["collected_at"] == "new_ts"
    codex_entries = [x for x in result["providers"] if x["provider"] == "codex"]
    assert len(codex_entries) == 1
    assert codex_entries[0]["available"] is True
    claude_entries = [x for x in result["providers"] if x["provider"] == "claude"]
    assert len(claude_entries) == 1


def test_update_snapshot_creates_file_if_missing(tmp_path) -> None:
    p = str(tmp_path / "snap.json")
    new_codex = {"provider": "codex", "available": True, "windows": [],
                 "observed_at": None, "reached_type": None, "error": None}
    probe.update_snapshot(p, new_codex, "ts")
    result = json.loads(Path(p).read_text())
    assert "providers" in result


def test_update_snapshot_permissions(tmp_path) -> None:
    p = str(tmp_path / "snap.json")
    probe.update_snapshot(p, {"provider": "codex", "windows": [], "available": True,
                               "observed_at": None, "reached_type": None, "error": None}, "ts")
    mode = os.stat(p).st_mode & 0o777
    assert mode == 0o600


def test_append_history_creates_jsonl(tmp_path) -> None:
    p = str(tmp_path / "history.jsonl")
    codex = {"windows": [{"label": "7d", "used_percent": 5.0,
                           "resets_at": None, "detail": None}],
             "observed_at": "obs_ts"}
    probe.append_history(p, codex, "sampled_ts")
    lines = Path(p).read_text().strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["source"] == "fresh"
    assert row["provider"] == "codex"
    assert row["stale"] is False


def test_append_history_permissions(tmp_path) -> None:
    p = str(tmp_path / "history.jsonl")
    probe.append_history(p, {"windows": [], "observed_at": None}, "ts")
    mode = os.stat(p).st_mode & 0o777
    assert mode == 0o600


# ---------------------------------------------------------------------------
# 9. run() – flusso principale
# ---------------------------------------------------------------------------

import argparse as _argparse


def _args(tmp_dir, **overrides):
    snap = str(Path(tmp_dir) / "snap.json")
    hist = str(Path(tmp_dir) / "hist.jsonl")
    lock = str(Path(tmp_dir) / "probe.lock")
    defaults = {
        "snapshot_path": snap,
        "history_path": hist,
        "codex_script": "/fake/codex",
        "lock_path": lock,
        "orchestrator_state_path": None,
        "timeout": 10,
        "dry_run": False,
        "log_level": "WARNING",
    }
    defaults.update(overrides)
    return _argparse.Namespace(**defaults)


def _write_snap(path, used_percent=100.0, observed_at=None):
    snap = {"collected_at": "old", "providers": [make_snapshot(used_percent, observed_at)]}
    Path(path).write_text(json.dumps(snap), encoding="utf-8")


def test_run_no_snapshot_no_probe(tmp_path) -> None:
    args = _args(str(tmp_path))
    with patch.object(probe, "run_probe") as mock_rp:
        probe.run(args)
    mock_rp.assert_not_called()


def test_run_budget_available_no_probe(tmp_path) -> None:
    args = _args(str(tmp_path))
    _write_snap(args.snapshot_path, used_percent=5.0, observed_at=old_ts())
    with patch.object(probe, "run_probe") as mock_rp:
        probe.run(args)
    mock_rp.assert_not_called()


def test_run_recent_sample_no_probe(tmp_path) -> None:
    args = _args(str(tmp_path))
    _write_snap(args.snapshot_path, used_percent=100.0, observed_at=recent_ts(30))
    with patch.object(probe, "run_probe") as mock_rp:
        probe.run(args)
    mock_rp.assert_not_called()


def test_run_dry_run_no_codex_call(tmp_path) -> None:
    args = _args(str(tmp_path), dry_run=True)
    _write_snap(args.snapshot_path, used_percent=100.0, observed_at=old_ts())
    with patch.object(probe, "run_probe") as mock_rp:
        probe.run(args)
    mock_rp.assert_not_called()


def test_run_valid_probe_updates_snapshot_and_history(tmp_path) -> None:
    args = _args(str(tmp_path))
    _write_snap(args.snapshot_path, used_percent=100.0, observed_at=old_ts())
    payload = (
        json.dumps({"windows": [{"label": "7d", "used_percent": 5.0, "resets_at": None}],
                    "updated_at": "2026-08-15T04:00:00+00:00"}) + "\n"
    )
    with patch.object(probe, "run_probe",
                      return_value=(True, payload.encode(), "2026-08-15T04:00:00+00:00")):
        probe.run(args)
    snap = json.loads(Path(args.snapshot_path).read_text())
    codex = next(p for p in snap["providers"] if p["provider"] == "codex")
    assert codex["available"] is True
    hist_lines = Path(args.history_path).read_text().strip().splitlines()
    assert len(hist_lines) == 1
    row = json.loads(hist_lines[0])
    assert row["source"] == "fresh"


def test_run_probe_failed_does_not_mutate_snapshot(tmp_path) -> None:
    args = _args(str(tmp_path))
    _write_snap(args.snapshot_path, used_percent=100.0, observed_at=old_ts())
    original = Path(args.snapshot_path).read_text()
    with patch.object(probe, "run_probe", return_value=(False, b"", None)):
        probe.run(args)
    assert Path(args.snapshot_path).read_text() == original
    assert not Path(args.history_path).exists()


def test_run_provider_available_without_tasks(tmp_path) -> None:
    """Provider tornato disponibile senza task sospesi: snapshot aggiornato."""
    args = _args(str(tmp_path))
    _write_snap(args.snapshot_path, used_percent=100.0, observed_at=old_ts())
    payload = json.dumps({"windows": [{"label": "7d", "used_percent": 5.0}]}) + "\n"
    with patch.object(probe, "run_probe", return_value=(True, payload.encode(), "ts")):
        probe.run(args)
    snap = json.loads(Path(args.snapshot_path).read_text())
    codex = next(p for p in snap["providers"] if p["provider"] == "codex")
    assert codex["available"] is True


def test_run_tasks_resumed_from_orchestrator_state_file(tmp_path) -> None:
    """Task sospesi letti dal file orchestratore vengono riconciliati."""
    args = _args(str(tmp_path))
    _write_snap(args.snapshot_path, used_percent=100.0, observed_at=old_ts())
    orch_path = str(tmp_path / "orch.json")
    args.orchestrator_state_path = orch_path
    orch = {"tasks": [
        {"task_id": "t1", "provider": "codex", "status": "paused_provider",
         "capacity_threshold": 80.0}
    ]}
    Path(orch_path).write_text(json.dumps(orch), encoding="utf-8")
    payload = json.dumps({"windows": [{"label": "7d", "used_percent": 5.0}]}) + "\n"
    with patch.object(probe, "run_probe", return_value=(True, payload.encode(), "ts")):
        probe.run(args)
    snap = json.loads(Path(args.snapshot_path).read_text())
    codex = next(p for p in snap["providers"] if p["provider"] == "codex")
    assert codex["available"] is True


def test_run_persistence_error_does_not_propagate_as_availability(tmp_path) -> None:
    """Un errore di persistenza non deve marcare il provider come disponibile."""
    args = _args(str(tmp_path))
    _write_snap(args.snapshot_path, used_percent=100.0, observed_at=old_ts())
    original = Path(args.snapshot_path).read_text()
    payload = json.dumps({"windows": [{"label": "7d", "used_percent": 5.0}]}) + "\n"

    with patch.object(probe, "run_probe", return_value=(True, payload.encode(), "ts")), \
         patch.object(probe, "update_snapshot", side_effect=OSError("disk full")):
        try:
            probe.run(args)
        except OSError:
            pass

    # Lo snapshot non è stato modificato
    assert Path(args.snapshot_path).read_text() == original


def test_run_invalid_payload_no_empty_windows_no_history(tmp_path) -> None:
    """Payload senza finestre valide: probe_failed, nessuna persistenza."""
    args = _args(str(tmp_path))
    _write_snap(args.snapshot_path, used_percent=100.0, observed_at=old_ts())
    payload = json.dumps({"windows": []}) + "\n"
    original = Path(args.snapshot_path).read_text()
    with patch.object(probe, "run_probe", return_value=(True, payload.encode(), "ts")):
        probe.run(args)
    assert Path(args.snapshot_path).read_text() == original
    assert not Path(args.history_path).exists()
