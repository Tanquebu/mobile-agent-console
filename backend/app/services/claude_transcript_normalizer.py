import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_MESSAGES = 500
MAX_MESSAGE_CHARS = 32 * 1024


def utc_timestamp(value: float | None = None) -> str:
    instant = datetime.fromtimestamp(value, UTC) if value is not None else datetime.now(UTC)
    return instant.isoformat()


def read_tail(path: Path) -> tuple[list[str], bool]:
    size = path.stat().st_size
    start = max(0, size - MAX_SOURCE_BYTES)
    with path.open("rb") as handle:
        handle.seek(start)
        raw = handle.read(MAX_SOURCE_BYTES)
    if start:
        separator = raw.find(b"\n")
        raw = raw[separator + 1 :] if separator >= 0 else b""
    return raw.decode("utf-8", errors="ignore").splitlines(), start > 0


def text_content(record: dict[str, object]) -> tuple[str, str] | None:
    record_type = record.get("type")
    if (
        record_type not in {"user", "assistant"}
        or record.get("isSidechain") is True
        or record.get("isMeta") is True
    ):
        return None
    message = record.get("message")
    if not isinstance(message, dict):
        return None
    role = message.get("role")
    if role not in {"user", "assistant"} or role != record_type:
        return None
    content = message.get("content")
    if isinstance(content, str):
        parts = [content]
    elif isinstance(content, list):
        parts = [
            item["text"]
            for item in content
            if isinstance(item, dict)
            and item.get("type") == "text"
            and isinstance(item.get("text"), str)
        ]
    else:
        return None
    text = "\n".join(part for part in parts if part.strip()).strip()
    return (role, text) if text else None


def normalize_transcript(path: Path) -> dict[str, object]:
    lines, truncated = read_tail(path)
    messages = []
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        normalized = text_content(record)
        identifier = record.get("uuid")
        timestamp = record.get("timestamp")
        if (
            normalized is None
            or not isinstance(identifier, str)
            or not identifier
            or not isinstance(timestamp, str)
        ):
            continue
        role, content = normalized
        if len(content) > MAX_MESSAGE_CHARS:
            content = content[:MAX_MESSAGE_CHARS]
            truncated = True
        messages.append(
            {
                "id": identifier,
                "role": role,
                "content": content,
                "timestamp": timestamp,
            }
        )
    if len(messages) > MAX_MESSAGES:
        messages = messages[-MAX_MESSAGES:]
        truncated = True
    return {
        "source_updated_at": utc_timestamp(path.stat().st_mtime),
        "truncated": truncated,
        "messages": messages,
    }


def atomic_json_write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".claude-history-", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
