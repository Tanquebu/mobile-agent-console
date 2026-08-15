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
            time_updated INTEGER
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
        "INSERT INTO session VALUES (?, ?, ?, ?, ?)",
        ("ses_test_123", directory, "Test session", 1700000000000, 1700000050000),
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
        "INSERT INTO session VALUES (?, ?, ?, ?, ?)",
        ("ses_new_123", "/workspace", "Nuova", 1700000120000, 1700000120000),
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
