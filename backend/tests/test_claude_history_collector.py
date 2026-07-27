import json

from app.services.claude_transcript_normalizer import (
    atomic_json_write,
    normalize_transcript,
    text_content,
)


def test_extracts_only_user_and_assistant_text() -> None:
    assert text_content(
        {
            "type": "user",
            "message": {"role": "user", "content": " domanda "},
        }
    ) == ("user", "domanda")
    assert text_content(
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "privato"},
                    {"type": "tool_use", "input": {"secret": "privato"}},
                    {"type": "text", "text": "risposta"},
                ],
            },
        }
    ) == ("assistant", "risposta")
    assert text_content(
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "content": "segreto"}],
            },
        }
    ) is None
    assert text_content(
        {
            "type": "assistant",
            "isSidechain": True,
            "message": {"role": "assistant", "content": "subagent"},
        }
    ) is None


def test_normalizes_with_limits_and_ignores_invalid_records(tmp_path) -> None:
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        "\n".join(
            [
                "invalid",
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "u1",
                        "timestamp": "2026-07-27T10:00:00Z",
                        "message": {"role": "user", "content": "Domanda"},
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "uuid": "a1",
                        "timestamp": "2026-07-27T10:00:01Z",
                        "message": {
                            "role": "assistant",
                            "content": [{"type": "text", "text": "Risposta"}],
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "uuid": "a2",
                        "timestamp": "2026-07-27T10:00:02Z",
                        "message": {
                            "role": "assistant",
                            "content": [{"type": "tool_use", "input": "mai"}],
                        },
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    result = normalize_transcript(transcript)
    assert [(item["role"], item["content"]) for item in result["messages"]] == [
        ("user", "Domanda"),
        ("assistant", "Risposta"),
    ]
    assert result["truncated"] is False


def test_atomic_write_is_private_and_replaces_previous_file(tmp_path) -> None:
    output = tmp_path / "history.json"
    atomic_json_write(output, {"version": 1, "sessions": []})
    assert output.stat().st_mode & 0o777 == 0o600
    atomic_json_write(output, {"version": 1, "sessions": [{"session_id": "1"}]})
    assert '"session_id":"1"' in output.read_text(encoding="utf-8")
    assert not list(tmp_path.glob(".claude-history-*"))
