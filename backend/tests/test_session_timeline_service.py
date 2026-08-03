from datetime import UTC, datetime

import pytest

from app.services.session_timeline_service import (
    SessionTimelineInvalidResponse,
    SessionTimelineService,
    SessionTimelineTimeout,
    SessionTimelineUnavailable,
    SessionTimelineWindow,
)
from app.services.session_timeline_socket_client import (
    SessionTimelineSocketResponseError,
    SessionTimelineSocketTimeout,
    SessionTimelineSocketUnavailable,
)


class StubClient:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[tuple] = []

    async def fetch_window(self, provider, session_uuid, bucket_start, bucket_end):
        self.calls.append((provider, session_uuid, bucket_start, bucket_end))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


async def test_read_computes_five_minute_window_and_validates_payload() -> None:
    stub = StubClient(
        {
            "available": True,
            "turns": [
                {
                    "timestamp": "2026-08-02T09:30:12.500Z",
                    "model": "claude-opus-5",
                    "input_tokens": 2,
                    "cache_creation_input_tokens": 1,
                    "cache_read_input_tokens": 3,
                    "output_tokens": 4,
                }
            ],
            "tool_counts": {"file_read": 2},
            "compactions": [],
            "subagent_spawns": [],
        }
    )
    service = SessionTimelineService(stub)
    result = await service.read("claude", "5b84b3fa-a26f-4642-abf3-851fc35abf3f", datetime(2026, 8, 2, 9, 30, tzinfo=UTC))
    assert isinstance(result, SessionTimelineWindow)
    assert result.bucket_start == datetime(2026, 8, 2, 9, 30, tzinfo=UTC)
    assert result.bucket_end == datetime(2026, 8, 2, 9, 35, tzinfo=UTC)
    assert result.turns[0].output_tokens == 4
    assert stub.calls[0][2] == datetime(2026, 8, 2, 9, 30, tzinfo=UTC)
    assert stub.calls[0][3] == datetime(2026, 8, 2, 9, 35, tzinfo=UTC)


async def test_unknown_tool_categories_are_dropped_defense_in_depth() -> None:
    stub = StubClient(
        {
            "available": True,
            "turns": [],
            "tool_counts": {"file_read": 1, "raw_tool_name_leak": 5, "not_a_category": -1},
            "compactions": [],
            "subagent_spawns": [],
        }
    )
    service = SessionTimelineService(stub)
    result = await service.read("codex", "abc", datetime(2026, 8, 2, 9, 30, tzinfo=UTC))
    assert result.tool_counts == {"file_read": 1}


async def test_unavailable_reason_is_preserved_as_declared_state() -> None:
    stub = StubClient({"available": False, "unavailable_reason": "transcript_not_found"})
    service = SessionTimelineService(stub)
    result = await service.read("claude", "abc", datetime(2026, 8, 2, 9, 30, tzinfo=UTC))
    assert result.available is False
    assert result.unavailable_reason == "transcript_not_found"
    assert result.turns == []


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (SessionTimelineSocketTimeout("x"), SessionTimelineTimeout),
        (SessionTimelineSocketUnavailable("x"), SessionTimelineUnavailable),
        (SessionTimelineSocketResponseError("x"), SessionTimelineInvalidResponse),
    ],
)
async def test_socket_errors_map_to_typed_service_errors(raised, expected) -> None:
    stub = StubClient(raised)
    service = SessionTimelineService(stub)
    with pytest.raises(expected):
        await service.read("claude", "abc", datetime(2026, 8, 2, 9, 30, tzinfo=UTC))


async def test_invalid_payload_shape_raises_invalid_response() -> None:
    stub = StubClient({"available": "not-a-bool"})
    service = SessionTimelineService(stub)
    with pytest.raises(SessionTimelineInvalidResponse):
        await service.read("claude", "abc", datetime(2026, 8, 2, 9, 30, tzinfo=UTC))
