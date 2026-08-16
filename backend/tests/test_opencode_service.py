import json
import sqlite3
from pathlib import Path

from app.services.opencode_service import OpencodeService


def _create_sample_opencode_db(db_path: Path, directory: str = "/workspace/proj") -> None:
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE session (
            id TEXT PRIMARY KEY,
            directory TEXT,
            title TEXT,
            time_created INTEGER,
            time_updated INTEGER,
            model TEXT
        )
        """
    )
    c.execute(
        """
        CREATE TABLE message (
            id TEXT PRIMARY KEY,
            session_id TEXT,
            time_created INTEGER,
            data TEXT
        )
        """
    )
    c.execute(
        """
        CREATE TABLE part (
            id TEXT PRIMARY KEY,
            message_id TEXT,
            session_id TEXT,
            time_created INTEGER,
            data TEXT
        )
        """
    )

    # Insert sample session
    c.execute(
        "INSERT INTO session (id, directory, title, time_created, time_updated, model) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            "ses_test_123",
            directory,
            "Test session",
            1700000000000,
            1700000050000,
            json.dumps({"id": "anthropic/claude-sonnet-4-5", "providerID": "anthropic"}),
        ),
    )

    # Message 1 (user)
    c.execute(
        "INSERT INTO message VALUES (?, ?, ?, ?)",
        ("msg_1", "ses_test_123", 1700000001000, json.dumps({"role": "user"})),
    )
    c.execute(
        "INSERT INTO part VALUES (?, ?, ?, ?, ?)",
        ("prt_1", "msg_1", "ses_test_123", 1700000001100, json.dumps({"type": "text", "text": "Ciao, puoi creare un file?"})),
    )

    # Message 2 (assistant with tool and answer)
    c.execute(
        "INSERT INTO message VALUES (?, ?, ?, ?)",
        ("msg_2", "ses_test_123", 1700000002000, json.dumps({"role": "assistant"})),
    )
    c.execute(
        "INSERT INTO part VALUES (?, ?, ?, ?, ?)",
        (
            "prt_2",
            "msg_2",
            "ses_test_123",
            1700000002100,
            json.dumps({
                "type": "tool",
                "tool": "bash",
                "state": {"status": "completed", "input": {"command": "echo test > file.txt"}, "output": "ok"}
            }),
        ),
    )
    c.execute(
        "INSERT INTO part VALUES (?, ?, ?, ?, ?)",
        ("prt_3", "msg_2", "ses_test_123", 1700000002200, json.dumps({"type": "text", "text": "File creato con successo."})),
    )

    conn.commit()
    conn.close()


def test_opencode_service_reads_valid_db(tmp_path: Path) -> None:
    db_file = tmp_path / "opencode.db"
    _create_sample_opencode_db(db_file, str(tmp_path / "workspace"))

    service = OpencodeService(str(db_file))
    history = service.read_history(str(tmp_path / "workspace"), "1")

    assert history is not None
    assert history.session_id == "1"
    assert history.opencode_session_id == "ses_test_123"
    assert history.title == "Test session"
    assert len(history.blocks) == 3

    assert history.blocks[0].kind == "user"
    assert history.blocks[0].content == "Ciao, puoi creare un file?"

    assert history.blocks[1].kind == "activity"
    assert "$ echo test > file.txt" in history.blocks[1].content
    assert "ok" in history.blocks[1].content

    assert history.blocks[2].kind == "agent"
    assert history.blocks[2].content == "File creato con successo."


def test_opencode_service_missing_file_or_wrong_directory(tmp_path: Path) -> None:
    service = OpencodeService(str(tmp_path / "non_existent.db"))
    assert service.read_history("/some/path", "1") is None

    db_file = tmp_path / "opencode.db"
    _create_sample_opencode_db(db_file, "/path/one")
    service2 = OpencodeService(str(db_file))
    history = service2.read_history("/different/path", "1")
    assert history is not None
    assert history.blocks == []


def test_opencode_service_min_timestamp_filter(tmp_path: Path) -> None:
    from datetime import UTC, datetime
    db_file = tmp_path / "opencode.db"
    _create_sample_opencode_db(db_file, "/workspace")
    service = OpencodeService(str(db_file))

    # time_created in sample db is 1700000000000 (1700000000 seconds)
    before = datetime.fromtimestamp(1700000000, tz=UTC)
    after = datetime.fromtimestamp(1700000100, tz=UTC)

    # With min_timestamp before session creation, it matches
    assert service.read_history("/workspace", "1", min_timestamp=before) is not None

    # With min_timestamp after session creation, the old session is excluded
    # and the history is empty (new session not materialized yet)
    history = service.read_history("/workspace", "1", min_timestamp=after)
    assert history is not None
    assert history.blocks == []


def test_opencode_service_new_session_does_not_inherit_previous_blocks(tmp_path: Path) -> None:
    from datetime import UTC, datetime
    db_file = tmp_path / "opencode.db"
    _create_sample_opencode_db(db_file, "/workspace")
    service = OpencodeService(str(db_file))
    tmux_start = datetime.fromtimestamp(1700000100, tz=UTC)

    # Prima della materializzazione della nuova conversazione, con la sola
    # sessione precedente (creata prima dell'avvio del pane) in archivio, la
    # cronologia deve restare vuota e non ereditare i blocchi della vecchia.
    history = service.read_history("/workspace", "1", min_timestamp=tmux_start)
    assert history is not None
    assert history.blocks == []

    # Appena la nuova conversazione (creata dopo l'avvio del pane) compare,
    # vince la correlazione e i blocchi sono quelli della nuova sessione.
    conn = sqlite3.connect(db_file)
    c = conn.cursor()
    c.execute(
        "INSERT INTO session (id, directory, title, time_created, time_updated, model) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("ses_new_123", "/workspace", "Nuova", 1700000120000, 1700000120000, "openai/gpt-5-codex"),
    )
    c.execute(
        "INSERT INTO message VALUES (?, ?, ?, ?)",
        ("msg_n1", "ses_new_123", 1700000121000, json.dumps({"role": "user"})),
    )
    c.execute(
        "INSERT INTO part VALUES (?, ?, ?, ?, ?)",
        ("prt_n1", "msg_n1", "ses_new_123", 1700000121100, json.dumps({"type": "text", "text": "Primo prompt della nuova sessione"})),
    )
    conn.commit()
    conn.close()

    history = service.read_history("/workspace", "1", min_timestamp=tmux_start)
    assert history is not None
    assert history.opencode_session_id == "ses_new_123"
    assert len(history.blocks) == 1
    assert history.blocks[0].kind == "user"
    assert history.blocks[0].content == "Primo prompt della nuova sessione"


def test_opencode_service_picks_conversation_born_after_pane_start_not_most_recently_updated(
    tmp_path: Path,
) -> None:
    from datetime import UTC, datetime
    db_file = tmp_path / "opencode.db"
    _create_sample_opencode_db(db_file, "/workspace")
    service = OpencodeService(str(db_file))
    # Il pane tmux avviato a 1700000100 ha prodotto due conversazioni nella
    # stessa directory: una nata subito (1700000120) e una successiva
    # (1700000130) che apparteneva a un'altra sessione tmux, poi chiusa.
    # La seconda ha time_updated piu' recente: con la vecchia selezione
    # (time_updated DESC) avrebbe vinto lei, mostrando blocchi altrui.
    conn = sqlite3.connect(db_file)
    c = conn.cursor()
    c.execute(
        "INSERT INTO session (id, directory, title, time_created, time_updated, model) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            "ses_born_first",
            "/workspace",
            "Nata per prima",
            1700000120000,
            1700000120000,
            json.dumps({"id": "anthropic/claude-opus-4-1", "providerID": "anthropic"}),
        ),
    )
    c.execute(
        "INSERT INTO message VALUES (?, ?, ?, ?)",
        ("msg_b1", "ses_born_first", 1700000121000, json.dumps({"role": "user"})),
    )
    c.execute(
        "INSERT INTO part VALUES (?, ?, ?, ?, ?)",
        ("prt_b1", "msg_b1", "ses_born_first", 1700000121100, json.dumps({"type": "text", "text": "Blocco della conversazione corretta"})),
    )
    c.execute(
        "INSERT INTO session (id, directory, title, time_created, time_updated, model) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            "ses_born_later",
            "/workspace",
            "Altra sessione",
            1700000130000,
            1700000140000,
            json.dumps({"id": "openai/gpt-5", "providerID": "openai"}),
        ),
    )
    c.execute(
        "INSERT INTO message VALUES (?, ?, ?, ?)",
        ("msg_b2", "ses_born_later", 1700000131000, json.dumps({"role": "user"})),
    )
    c.execute(
        "INSERT INTO part VALUES (?, ?, ?, ?, ?)",
        ("prt_b2", "msg_b2", "ses_born_later", 1700000131100, json.dumps({"type": "text", "text": "Blocco di una sessione chiusa"})),
    )
    conn.commit()
    conn.close()

    tmux_start = datetime.fromtimestamp(1700000100, tz=UTC)
    history = service.read_history("/workspace", "1", min_timestamp=tmux_start)
    assert history is not None
    assert history.opencode_session_id == "ses_born_first"
    assert len(history.blocks) == 1
    assert history.blocks[0].content == "Blocco della conversazione corretta"


def test_read_session_model_returns_correlated_model(tmp_path: Path) -> None:
    db_file = tmp_path / "opencode.db"
    _create_sample_opencode_db(db_file, "/workspace")
    service = OpencodeService(str(db_file))

    assert service.read_session_model("/workspace", "1") == "anthropic/claude-sonnet-4-5"


def test_read_session_model_respects_min_timestamp_correlation(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    db_file = tmp_path / "opencode.db"
    _create_sample_opencode_db(db_file, "/workspace")
    service = OpencodeService(str(db_file))

    conn = sqlite3.connect(db_file)
    c = conn.cursor()
    c.execute(
        "INSERT INTO session (id, directory, title, time_created, time_updated, model) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            "ses_new_123",
            "/workspace",
            "Nuova",
            1700000120000,
            1700000120000,
            json.dumps({"id": "openai/gpt-5-codex", "providerID": "openai"}),
        ),
    )
    conn.commit()
    conn.close()

    tmux_start = datetime.fromtimestamp(1700000100, tz=UTC)
    # La conversazione precedente (nata prima dell'avvio del pane) non deve
    # vincere la correlazione: stessa regola di read_history.
    assert service.read_session_model("/workspace", "1", min_timestamp=tmux_start) == (
        "openai/gpt-5-codex"
    )


def test_read_session_model_missing_db_or_directory_returns_none(tmp_path: Path) -> None:
    service = OpencodeService(str(tmp_path / "non_existent.db"))
    assert service.read_session_model("/some/path", "1") is None

    db_file = tmp_path / "opencode.db"
    _create_sample_opencode_db(db_file, "/path/one")
    service2 = OpencodeService(str(db_file))
    assert service2.read_session_model("/different/path", "1") is None


def test_read_session_model_missing_model_column_does_not_raise(tmp_path: Path) -> None:
    # DB con schema piu' vecchio/diverso (colonna model assente): niente
    # eccezione, solo None, come per qualunque altro errore sqlite.
    db_file = tmp_path / "opencode.db"
    conn = sqlite3.connect(db_file)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE session (
            id TEXT PRIMARY KEY,
            directory TEXT,
            title TEXT,
            time_created INTEGER,
            time_updated INTEGER
        )
        """
    )
    c.execute(
        "INSERT INTO session VALUES (?, ?, ?, ?, ?)",
        ("ses_no_model", "/workspace", "Senza colonna model", 1700000000000, 1700000050000),
    )
    conn.commit()
    conn.close()

    service = OpencodeService(str(db_file))
    assert service.read_session_model("/workspace", "1") is None


def test_read_session_model_parses_real_opencode_json_shape(tmp_path: Path) -> None:
    # Formato reale di OpenCode (schema `session.model` su disco): un JSON
    # con `id`/`providerID` (a volte anche `variant`), non una stringa nuda.
    # Verificato leggendo un opencode.db reale — vedi commit che introduce
    # questo test per il contesto del bug.
    db_file = tmp_path / "opencode.db"
    _create_sample_opencode_db(db_file, "/workspace")
    conn = sqlite3.connect(db_file)
    c = conn.cursor()
    c.execute(
        "UPDATE session SET model = ? WHERE id = ?",
        (
            json.dumps(
                {"id": "deepseek-v4-flash-free", "providerID": "opencode", "variant": "default"}
            ),
            "ses_test_123",
        ),
    )
    conn.commit()
    conn.close()

    service = OpencodeService(str(db_file))
    assert service.read_session_model("/workspace", "1") == "deepseek-v4-flash-free"


def test_read_session_model_non_json_string_falls_back_to_raw_value(tmp_path: Path) -> None:
    db_file = tmp_path / "opencode.db"
    _create_sample_opencode_db(db_file, "/workspace")
    conn = sqlite3.connect(db_file)
    c = conn.cursor()
    c.execute(
        "UPDATE session SET model = ? WHERE id = ?",
        ("anthropic/claude-sonnet-4-5", "ses_test_123"),
    )
    conn.commit()
    conn.close()

    service = OpencodeService(str(db_file))
    # Formato non-JSON (schema piu' vecchio/diverso): meglio mostrare la
    # stringa grezza che nascondere il dato.
    assert service.read_session_model("/workspace", "1") == "anthropic/claude-sonnet-4-5"


def test_read_session_model_json_without_id_returns_none(tmp_path: Path) -> None:
    db_file = tmp_path / "opencode.db"
    _create_sample_opencode_db(db_file, "/workspace")
    conn = sqlite3.connect(db_file)
    c = conn.cursor()
    c.execute(
        "UPDATE session SET model = ? WHERE id = ?",
        (json.dumps({"providerID": "opencode"}), "ses_test_123"),
    )
    conn.commit()
    conn.close()

    service = OpencodeService(str(db_file))
    assert service.read_session_model("/workspace", "1") is None
