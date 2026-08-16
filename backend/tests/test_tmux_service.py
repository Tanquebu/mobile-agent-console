import asyncio
import subprocess

import pytest

from app.services.tmux_service import (
    OPENCODE_MISSING_BINARY_MESSAGE,
    OPENCODE_PERMISSION_POLICY,
    SessionNotFound,
    TmuxError,
    TmuxPane,
    TmuxService,
    _missing_binary_shell_command,
)


class Recorder:
    """Intercetta create_subprocess_exec registrando argv e stdin."""

    def __init__(self, monkeypatch, stdout: bytes = b"", fail_with: dict[str, bytes] | None = None) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.stdins: list[bytes | None] = []
        fail = fail_with or {}
        recorder = self

        class Process:
            def __init__(self, argv: tuple[str, ...]) -> None:
                self.returncode = 0
                self._stderr = b""
                for keyword, message in fail.items():
                    if keyword in argv:
                        self.returncode = 1
                        self._stderr = message

            async def communicate(self, stdin: bytes | None) -> tuple[bytes, bytes]:
                recorder.stdins.append(stdin)
                return stdout, self._stderr

        async def fake_exec(*argv, **kwargs):
            recorder.calls.append(argv)
            return Process(argv)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)


@pytest.mark.parametrize(
    "value",
    [" bad", "bad ", "bad  name", "x;touch_pwned", "../demo", "bad:name", "", "x" * 65],
)
def test_rejects_unsafe_session_names(value: str) -> None:
    with pytest.raises(ValueError):
        TmuxService.validate_session_id(value)


def test_accepts_safe_session_names() -> None:
    assert TmuxService.validate_session_id("codex_project-1") == "codex_project-1"
    assert TmuxService.validate_session_id("Refactoring Codex") == "Refactoring Codex"
    assert TmuxService.validate_session_name("osservabilità") == "osservabilità"
    assert TmuxService.validate_session_name("osservabilita\u0300") == "osservabilità"


def test_target_accepts_numeric_ids() -> None:
    assert TmuxService.validate_target("3") == "$3"
    assert TmuxService.validate_target("0") == "$0"
    assert TmuxService.validate_pane_id("12") == "%12"


@pytest.mark.parametrize("value", ["$3", "", "demo", "3;x", "3.0", "1" * 11])
def test_target_rejects_non_numeric_ids(value: str) -> None:
    with pytest.raises(ValueError):
        TmuxService.validate_target(value)


def test_socket_prefix_variants(monkeypatch) -> None:
    recorder = Recorder(monkeypatch)
    asyncio.run(TmuxService("test").send_key("1", "Enter"))
    asyncio.run(TmuxService("name", socket_path="/tmux/").send_key("1", "Enter"))
    asyncio.run(TmuxService("name", socket_file="/tmp/tmux-1000/default").send_key("1", "Enter"))
    assert recorder.calls[0][:3] == ("tmux", "-L", "test")
    assert recorder.calls[1][:3] == ("tmux", "-S", "/tmux/name.sock")
    assert recorder.calls[2][:3] == ("tmux", "-S", "/tmp/tmux-1000/default")


def test_scroll_pane_sends_repeated_sgr_wheel_sequence(monkeypatch) -> None:
    recorder = Recorder(monkeypatch)
    service = TmuxService("test")
    asyncio.run(service.scroll_pane("1", "up", 3))
    call = recorder.calls[0]
    assert call[:3] == ("tmux", "-L", "test")
    assert call[3:] == ("send-keys", "-t", "$1", "\x1b[<64;1;1M" * 3)

    async def panes(_session_id: str) -> list[TmuxPane]:
        return [TmuxPane("12", 0, 0, True, "bash", "shell", 80, 24)]

    monkeypatch.setattr(service, "list_panes", panes)
    recorder.calls.clear()
    asyncio.run(service.scroll_pane("1", "down", 1, pane_id="12"))
    call = recorder.calls[0]
    assert call[3:] == ("send-keys", "-t", "%12", "\x1b[<65;1;1M")


def test_scroll_pane_rejects_unsupported_direction() -> None:
    service = TmuxService("test")
    with pytest.raises(ValueError):
        asyncio.run(service.scroll_pane("1", "sideways", 1))


def test_multiline_and_special_text_goes_through_stdin(monkeypatch) -> None:
    recorder = Recorder(monkeypatch)
    service = TmuxService("test")
    text = "line one\n$(touch /tmp/nope); ' \" à"
    asyncio.run(service.send_text("1", text))

    assert recorder.stdins[0] == text.encode()
    assert recorder.calls[0][:3] == ("tmux", "-L", "test")
    assert "paste-buffer" in recorder.calls[1]
    assert recorder.calls[1][recorder.calls[1].index("-t") + 1] == "$1"
    # Senza `-r`, tmux converte ogni LF in CR: il testo multilinea arriva alla
    # TUI come righe separate da Invio e la prima riga parte da sola. Osservato
    # in produzione su claude, antigravity e opencode. Vedi INC-PASTE-01.
    assert "-r" in recorder.calls[1]


def test_capture_targets_active_pane(monkeypatch) -> None:
    recorder = Recorder(monkeypatch)
    asyncio.run(TmuxService("test").capture_output("7"))
    call = recorder.calls[0]
    assert call[call.index("-t") + 1] == "$7"


def test_explicit_pane_is_checked_against_session(monkeypatch) -> None:
    recorder = Recorder(monkeypatch)
    service = TmuxService("test")

    async def panes(_session_id: str) -> list[TmuxPane]:
        return [TmuxPane("12", 1, 0, True, "bash", "shell", 80, 24)]

    monkeypatch.setattr(service, "list_panes", panes)
    asyncio.run(service.capture_output("7", pane_id="12"))
    assert recorder.calls[0][recorder.calls[0].index("-t") + 1] == "%12"
    with pytest.raises(SessionNotFound):
        asyncio.run(service.capture_output("7", pane_id="99"))


def test_list_and_resize_panes(monkeypatch) -> None:
    recorder = Recorder(monkeypatch, stdout=b"%12\t1\t2\t1\tpython\tworker\t120\t40\n")
    service = TmuxService("test")
    panes = asyncio.run(service.list_panes("7"))
    assert panes == [TmuxPane("12", 1, 2, True, "python", "worker", 120, 40)]
    asyncio.run(service.resize_pane("7", "12", 100, 30))
    resize_call = recorder.calls[-1]
    assert resize_call[-7:] == ("resize-pane", "-t", "%12", "-x", "100", "-y", "30")


def test_split_pane_uses_constant_login_shell(monkeypatch) -> None:
    output = b"%13\t0\t1\t0\tbash\tshell\t40\t24\n"
    recorder = Recorder(monkeypatch, stdout=output)
    created = asyncio.run(TmuxService("test").split_pane("7"))
    assert created.id == "13"
    assert recorder.calls[-1][-2:] == ("bash", "-l")
    assert "split-window" in recorder.calls[-1]


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        ("shell", ("bash", "-l")),
        ("codex", ("bash", "-l", "-c", "exec codex")),
        ("claude", ("bash", "-l", "-c", "exec claude")),
        ("antigravity", ("bash", "-l", "-c", "exec agy")),
        (
            "antigravity_yolo",
            ("bash", "-l", "-c", "exec agy --dangerously-skip-permissions"),
        ),
    ],
)
def test_create_session_uses_server_side_profile(monkeypatch, profile, expected) -> None:
    recorder = Recorder(monkeypatch)
    asyncio.run(TmuxService("test").create_session("demo", "/workspace", profile))
    assert recorder.calls[0][-len(expected) :] == expected


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        ("shell", ("bash", "-l")),
        ("codex", ("bash", "-l", "-c", "exec codex resume")),
        ("claude", ("bash", "-l", "-c", "exec claude --resume")),
        # `-c` e' l'alias breve di `--continue`: riprende l'ultima
        # conversazione, come `claude --resume` e `codex resume`. Prima il
        # profilo di ripresa di antigravity era identico a quello di avvio,
        # quindi "riprendi" apriva in realta' una sessione nuova.
        ("antigravity", ("bash", "-l", "-c", "exec agy -c")),
        (
            "antigravity_yolo",
            ("bash", "-l", "-c", "exec agy -c --dangerously-skip-permissions"),
        ),
    ],
)
def test_create_session_uses_server_side_resume_profile(
    monkeypatch, profile, expected
) -> None:
    recorder = Recorder(monkeypatch)
    asyncio.run(
        TmuxService("test").create_session(
            "demo", "/workspace", profile, resume=True
        )
    )
    assert recorder.calls[0][-len(expected) :] == expected


def test_opencode_create_and_resume_are_identical_and_do_not_use_continue(
    monkeypatch,
) -> None:
    # Decisione di ROOT (IMP-OC-01): lo store delle conversazioni OpenCode e'
    # globale per utente, quindi `--continue`/`--session` non vanno usati qui.
    # Il profilo di ripresa avvia OpenCode esattamente come un avvio nuovo.
    recorder = Recorder(monkeypatch)
    asyncio.run(TmuxService("test").create_session("demo", "/workspace", "opencode"))
    fresh_call = recorder.calls[0]

    recorder.calls.clear()
    asyncio.run(
        TmuxService("test").create_session(
            "demo", "/workspace", "opencode", resume=True
        )
    )
    resume_call = recorder.calls[0]

    assert fresh_call == resume_call
    assert "--continue" not in fresh_call
    assert "--session" not in fresh_call
    assert fresh_call[-2] == "-c"
    script = fresh_call[-1]
    assert "opencode" in script
    assert "--continue" not in script


def test_opencode_profile_ships_conservative_permission_policy(monkeypatch) -> None:
    # Sorveglianza del meccanismo (IMP-OC-01, punto vincolante): se
    # `OPENCODE_CONFIG_CONTENT` smette di essere passata a `new-session`, la
    # policy conservativa smette di applicarsi in silenzio. Questo test
    # fallisce in quel caso, invece di scoprirlo solo su un host reale.
    recorder = Recorder(monkeypatch)
    asyncio.run(TmuxService("test").create_session("demo", "/workspace", "opencode"))
    call = recorder.calls[0]
    assert "-e" in call
    env_index = call.index("-e")
    assert call[env_index + 1] == f"OPENCODE_CONFIG_CONTENT={OPENCODE_PERMISSION_POLICY}"
    # Letture libere, conferma per shell ed edit: la lettura fedele della
    # policy "conservativa per le operazioni mutative o esterne" approvata
    # in GATE-OC-00, scelta dall'utente il 03/08/2026.
    assert OPENCODE_PERMISSION_POLICY == '{"permission":{"bash":"ask","edit":"ask"}}'

    # Gli altri profili non ricevono questa (o alcuna) variabile: la policy
    # e' specifica di OpenCode, non un default globale.
    recorder.calls.clear()
    asyncio.run(TmuxService("test").create_session("demo", "/workspace", "codex"))
    assert "-e" not in recorder.calls[0]


def test_opencode_yolo_profile_uses_auto_and_no_conservative_policy(monkeypatch) -> None:
    # Il profilo YOLO e' l'opt-in deliberato per il flag documentato `--auto`
    # (controparte di `agy --dangerously-skip-permissions`): approva le
    # richieste non esplicitamente negate. Non deve ricevere la policy
    # conservativa di `opencode`, altrimenti il bypass dipenderebbe da una
    # variabile non documentata (OPENCODE_CONFIG_CONTENT) oltre che dal flag.
    recorder = Recorder(monkeypatch)
    asyncio.run(TmuxService("test").create_session("demo", "/workspace", "opencode_yolo"))
    fresh_call = recorder.calls[0]
    assert fresh_call[-2] == "-c"
    script = fresh_call[-1]
    assert "command -v opencode" in script
    assert "exec opencode --auto" in script
    assert "-e" not in fresh_call

    # Come `opencode`, anche il profilo YOLO riprende avviando OpenCode
    # normalmente (niente `--continue`/`--session`), conservando `--auto`.
    recorder.calls.clear()
    asyncio.run(
        TmuxService("test").create_session(
            "demo", "/workspace", "opencode_yolo", resume=True
        )
    )
    assert recorder.calls[0] == fresh_call
    assert "--continue" not in recorder.calls[0]
    assert "--session" not in recorder.calls[0]


@pytest.mark.parametrize("binary", ["opencode-does-not-exist-xyz", "definitely-missing"])
def test_missing_binary_script_reports_and_keeps_pane_alive(binary: str) -> None:
    # Verifica reale (non mockata) dello script usato da PROFILE_ARGV: senza
    # questo ramo, un binario assente termina il pane subito e la sessione
    # tmux sparisce in silenzio (osservato dal vivo il 03/08/2026). Eseguito
    # direttamente con `bash`, senza tmux: lo script e' puro bash, e questo
    # binario non esiste su nessun PATH per costruzione, quindi il test non
    # dipende dall'ambiente in cui gira la suite.
    message = f"messaggio di test per {binary}"
    script = _missing_binary_shell_command(binary, message)
    result = subprocess.run(
        ["/usr/bin/env", "bash", "--noprofile", "--norc", "-c", script],
        input=b"",
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.decode() == f"{message}\n"


def test_missing_binary_script_runs_the_binary_when_present() -> None:
    # Ramo positivo dello stesso script: un binario risolvibile (`true`,
    # sempre presente) viene eseguito, nessun messaggio stampato.
    script = _missing_binary_shell_command("true", "non dovrebbe mai comparire")
    result = subprocess.run(
        ["/usr/bin/env", "bash", "-c", script],
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout == b""
    assert result.stderr == b""


def test_opencode_missing_binary_message_is_the_one_shipped() -> None:
    assert "opencode" in OPENCODE_MISSING_BINARY_MESSAGE.lower()
    assert "docs/architecture.md" in OPENCODE_MISSING_BINARY_MESSAGE


def test_create_session_rejects_unknown_profile(monkeypatch) -> None:
    recorder = Recorder(monkeypatch)
    with pytest.raises(ValueError, match="Unsupported profile"):
        asyncio.run(TmuxService("test").create_session("demo", "/workspace", "custom"))
    assert recorder.calls == []


def test_rename_session_uses_numeric_target_and_separate_name_argv(monkeypatch) -> None:
    recorder = Recorder(monkeypatch)
    asyncio.run(TmuxService("test").rename_session("7", "Refactoring Codex"))
    assert recorder.calls[0][-4:] == ("rename-session", "-t", "$7", "Refactoring Codex")


def test_external_server_guard_blocks_autostart(monkeypatch) -> None:
    recorder = Recorder(monkeypatch, fail_with={"list-sessions": b"no server running on /tmp/tmux-1000/default"})
    service = TmuxService("test", socket_file="/tmp/tmux-1000/default", external_server=True)
    with pytest.raises(TmuxError):
        asyncio.run(service.create_session("demo", "/workspace"))
    assert all("new-session" not in call for call in recorder.calls)


def test_check_server_reports_errors(monkeypatch) -> None:
    Recorder(monkeypatch, fail_with={"list-sessions": b"protocol version mismatch (client 3.5, server 3.6)"})
    error = asyncio.run(TmuxService("test").check_server())
    assert error is not None and "protocol version mismatch" in error


def test_list_sessions_uses_ids_and_keeps_host_names(monkeypatch) -> None:
    lines = (
        b"$3\t1\t2\tnode\t1700000000\tnome con spazi\te tab\n"
        b"$4\t0\t1\tbash\t1700000000\t__runtime__\n"
        b"bad\t0\t1\tbash\t1700000000\tx\n"
    )
    recorder = Recorder(monkeypatch, stdout=lines)
    hosted = asyncio.run(TmuxService("test", external_server=True).list_sessions())
    assert [(s.id, s.name) for s in hosted] == [("3", "nome con spazi\te tab"), ("4", "__runtime__")]
    assert hosted[0].attached and not hosted[1].attached

    recorder.calls.clear()
    isolated = asyncio.run(TmuxService("test").list_sessions())
    assert [(s.id, s.name) for s in isolated] == [("3", "nome con spazi\te tab")]


def test_only_allowlisted_keys_are_supported(monkeypatch) -> None:
    recorder = Recorder(monkeypatch)
    service = TmuxService("test")
    for key in ("Enter", "Up", "Down", "Left", "Right", "Escape", "C-c", "Tab", "Shift-Tab"):
        asyncio.run(service.send_key("1", key))
    assert [call[-1] for call in recorder.calls] == [
        "Enter",
        "Up",
        "Down",
        "Left",
        "Right",
        "Escape",
        "C-c",
        "Tab",
        "BTab",
    ]
    with pytest.raises(ValueError):
        asyncio.run(service.send_key("1", "C-x"))


def test_terminate_targets_session_id(monkeypatch) -> None:
    # Il guard interroga prima list-sessions (nessun risultato = nessuna
    # sessione riservata con quell'id): la kill-session resta l'ultima call.
    recorder = Recorder(monkeypatch)
    asyncio.run(TmuxService("test").terminate_session("7"))
    assert recorder.calls[-1][-3:] == ("kill-session", "-t", "$7")


def test_list_sessions_filters_configured_host_keepalive_name(monkeypatch) -> None:
    lines = (
        b"$3\t1\t2\tnode\t1700000000\tdemo\n"
        b"$4\t0\t1\tbash\t1700000000\tkeepalive\n"
        b"$5\t0\t1\tbash\t1700000000\t__runtime__\n"
    )
    recorder = Recorder(monkeypatch, stdout=lines)
    service = TmuxService("test", external_server=True, reserved_host_session="keepalive")
    hosted = asyncio.run(service.list_sessions())
    # Solo "keepalive" è filtrato in modalità host con questo nome
    # configurato: "__runtime__" è un dettaglio della modalità docker e non
    # ha alcun significato speciale qui.
    assert [(s.id, s.name) for s in hosted] == [("3", "demo"), ("5", "__runtime__")]

    recorder.calls.clear()
    disabled = asyncio.run(
        TmuxService("test", external_server=True, reserved_host_session="").list_sessions()
    )
    assert [(s.id, s.name) for s in disabled] == [
        ("3", "demo"),
        ("4", "keepalive"),
        ("5", "__runtime__"),
    ]


def test_terminate_refuses_reserved_docker_runtime_session_even_by_known_id(
    monkeypatch,
) -> None:
    # Il guard chiede `#{session_id}\t#{session_name}`, non il formato più
    # ampio di list_sessions: due soli campi.
    recorder = Recorder(monkeypatch, stdout=b"$4\t__runtime__\n")
    with pytest.raises(TmuxError, match="Refusing to terminate"):
        asyncio.run(TmuxService("test").terminate_session("4"))
    assert all("kill-session" not in call for call in recorder.calls)


def test_terminate_refuses_configured_host_keepalive_session_even_by_known_id(
    monkeypatch,
) -> None:
    recorder = Recorder(monkeypatch, stdout=b"$9\tkeepalive\n")
    service = TmuxService("test", external_server=True, reserved_host_session="keepalive")
    with pytest.raises(TmuxError, match="Refusing to terminate"):
        asyncio.run(service.terminate_session("9"))
    assert all("kill-session" not in call for call in recorder.calls)


def test_terminate_allows_host_session_when_keepalive_filter_disabled(monkeypatch) -> None:
    recorder = Recorder(monkeypatch)
    service = TmuxService("test", external_server=True, reserved_host_session="")
    asyncio.run(service.terminate_session("9"))
    # Filtro disattivato (stringa vuota): niente lookup di guardia, un'unica
    # call diretta a kill-session.
    assert len(recorder.calls) == 1
    assert recorder.calls[0][-3:] == ("kill-session", "-t", "$9")


def test_pane_path_targets_active_pane(monkeypatch) -> None:
    recorder = Recorder(monkeypatch, stdout=b"/workspace/demo\n")
    path = asyncio.run(TmuxService("test").pane_path("7"))
    assert path == "/workspace/demo"
    call = recorder.calls[0]
    assert call[call.index("-t") + 1] == "$7"
    assert call[-1] == "#{pane_current_path}"
