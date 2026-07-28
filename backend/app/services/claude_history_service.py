import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

MAX_HISTORY_FILE_BYTES = 2 * 1024 * 1024
MAX_MESSAGES_PER_SESSION = 500
MAX_MESSAGE_CHARS = 32 * 1024


@dataclass(frozen=True)
class ClaudeHistoryMessage:
    id: str
    role: Literal["user", "assistant"]
    content: str
    timestamp: datetime
    kind: Literal["message", "activity"] = "message"
    pending: bool = False


@dataclass(frozen=True)
class ClaudeHistory:
    collected_at: datetime
    source_updated_at: datetime
    truncated: bool
    messages: list[ClaudeHistoryMessage]


class ClaudeHistoryService:
    def __init__(self, path: str, max_age_seconds: int) -> None:
        self.path = Path(path)
        self.max_age_seconds = max_age_seconds

    def read(self, session_id: str) -> ClaudeHistory | None:
        try:
            if self.path.stat().st_size > MAX_HISTORY_FILE_BYTES:
                return None
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict) or payload.get("version") != 1:
            return None
        collected_at = _timestamp(payload.get("collected_at"))
        if collected_at is None:
            return None
        age = (datetime.now(UTC) - collected_at).total_seconds()
        if age < -5 or age > self.max_age_seconds:
            return None
        sessions = payload.get("sessions")
        if not isinstance(sessions, list):
            return None
        for item in sessions:
            parsed = _session(item, collected_at)
            if (
                isinstance(item, dict)
                and item.get("session_id") == session_id
                and parsed is not None
            ):
                return parsed
        return None


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _session(item: object, collected_at: datetime) -> ClaudeHistory | None:
    if not isinstance(item, dict) or item.get("provider") != "claude":
        return None
    source_updated_at = _timestamp(item.get("source_updated_at"))
    messages = item.get("messages")
    if source_updated_at is None or not isinstance(messages, list):
        return None
    parsed: list[ClaudeHistoryMessage] = []
    for message in messages[-MAX_MESSAGES_PER_SESSION:]:
        if not isinstance(message, dict):
            return None
        identifier = message.get("id")
        role = message.get("role")
        content = message.get("content")
        timestamp = _timestamp(message.get("timestamp"))
        kind = message.get("kind", "message")
        pending = message.get("pending", False)
        if (
            not isinstance(identifier, str)
            or not identifier
            or role not in {"user", "assistant"}
            or not isinstance(content, str)
            or not content.strip()
            or len(content) > MAX_MESSAGE_CHARS
            or timestamp is None
            or kind not in {"message", "activity"}
            or not isinstance(pending, bool)
        ):
            return None
        parsed.append(
            ClaudeHistoryMessage(
                id=identifier,
                role=role,
                content=content,
                timestamp=timestamp,
                kind=kind,
                pending=pending,
            )
        )
    return ClaudeHistory(
        collected_at=collected_at,
        source_updated_at=source_updated_at,
        truncated=item.get("truncated") is True,
        messages=parsed,
    )
