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
    assert service2.read_history("/different/path", "1") is None
