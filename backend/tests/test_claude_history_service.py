import json
from datetime import UTC, datetime, timedelta

from app.services.claude_history_service import ClaudeHistoryService


def payload(collected_at: datetime) -> dict[str, object]:
    return {
        "version": 1,
        "collected_at": collected_at.isoformat(),
        "sessions": [
            {
                "session_id": "43",
                "provider": "claude",
                "source_updated_at": collected_at.isoformat(),
                "truncated": False,
                "messages": [
                    {
                        "id": "message-1",
                        "role": "user",
                        "content": "Domanda",
                        "timestamp": collected_at.isoformat(),
                    },
                    {
                        "id": "message-2",
                        "role": "assistant",
                        "content": "Risposta",
                        "timestamp": collected_at.isoformat(),
                    },
                ],
            }
        ],
    }


def test_reads_only_valid_normalized_history(tmp_path) -> None:
    path = tmp_path / "history.json"
    now = datetime.now(UTC)
    path.write_text(json.dumps(payload(now)), encoding="utf-8")
    history = ClaudeHistoryService(str(path), 30).read("43")
    assert history is not None
    assert [message.role for message in history.messages] == ["user", "assistant"]
    assert [message.content for message in history.messages] == ["Domanda", "Risposta"]


def test_rejects_stale_malformed_and_oversized_messages(tmp_path) -> None:
    path = tmp_path / "history.json"
    stale = datetime.now(UTC) - timedelta(minutes=2)
    path.write_text(json.dumps(payload(stale)), encoding="utf-8")
    service = ClaudeHistoryService(str(path), 30)
    assert service.read("43") is None

    current = payload(datetime.now(UTC))
    current["sessions"][0]["messages"][0]["role"] = "tool"
    path.write_text(json.dumps(current), encoding="utf-8")
    assert service.read("43") is None

    current = payload(datetime.now(UTC))
    current["sessions"][0]["messages"][0]["content"] = "x" * (32 * 1024 + 1)
    path.write_text(json.dumps(current), encoding="utf-8")
    assert service.read("43") is None


def test_activity_kind_and_pending_round_trip(tmp_path) -> None:
    path = tmp_path / "history.json"
    now = datetime.now(UTC)
    current = payload(now)
    current["sessions"][0]["messages"].append(
        {
            "id": "message-3",
            "role": "assistant",
            "content": "Bash",
            "timestamp": now.isoformat(),
            "kind": "activity",
            "pending": True,
        }
    )
    path.write_text(json.dumps(current), encoding="utf-8")
    history = ClaudeHistoryService(str(path), 30).read("43")
    assert history is not None
    last = history.messages[-1]
    assert (last.kind, last.pending) == ("activity", True)

    current = payload(now)
    current["sessions"][0]["messages"][0]["kind"] = "not-a-real-kind"
    path.write_text(json.dumps(current), encoding="utf-8")
    assert ClaudeHistoryService(str(path), 30).read("43") is None


def test_missing_invalid_or_unknown_session_is_unavailable(tmp_path) -> None:
    path = tmp_path / "history.json"
    service = ClaudeHistoryService(str(path), 30)
    assert service.read("43") is None
    path.write_text("not-json", encoding="utf-8")
    assert service.read("43") is None
    path.write_text(json.dumps(payload(datetime.now(UTC))), encoding="utf-8")
    assert service.read("99") is None
