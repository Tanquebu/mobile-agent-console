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


def test_ask_user_question_survives_as_text_but_other_tools_dont() -> None:
    ask_tool_use = {
        "type": "tool_use",
        "id": "toolu_1",
        "name": "AskUserQuestion",
        "input": {
            "questions": [
                {
                    "header": "Approccio",
                    "question": "Quale preferisci?",
                    "options": [
                        {"label": "A", "description": "opzione A"},
                        {"label": "B", "description": "opzione B"},
                    ],
                }
            ]
        },
    }
    assert text_content(
        {"type": "assistant", "message": {"role": "assistant", "content": [ask_tool_use]}},
        frozenset(),
    ) == ("assistant", "Approccio: Quale preferisci?\n- A\n- B")
    assert text_content(
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_1", "content": "Ho scelto A"}
                ],
            },
        },
        frozenset({"toolu_1"}),
    ) == ("user", "Ho scelto A")
    # senza l'id noto (altro tool_use), il tool_result resta escluso.
    assert (
        text_content(
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "toolu_2", "content": "output bash"}
                    ],
                },
            },
            frozenset({"toolu_1"}),
        )
        is None
    )


def test_normalize_transcript_keeps_ask_user_question_qa(tmp_path) -> None:
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "assistant",
                        "uuid": "a1",
                        "timestamp": "2026-07-27T10:00:00Z",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "toolu_1",
                                    "name": "AskUserQuestion",
                                    "input": {
                                        "questions": [
                                            {"header": "H", "question": "Domanda?", "options": []}
                                        ]
                                    },
                                }
                            ],
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "u1",
                        "timestamp": "2026-07-27T10:00:01Z",
                        "message": {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": "toolu_1",
                                    "content": "Risposta scelta",
                                }
                            ],
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
                            "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}],
                        },
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    result = normalize_transcript(transcript)
    assert [(item["role"], item["content"]) for item in result["messages"]] == [
        ("assistant", "H: Domanda?"),
        ("user", "Risposta scelta"),
    ]


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
