import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.services.session_timeline_socket_client import (
    SessionTimelineSocketClient,
    SessionTimelineSocketError,
)

Handler = Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]]


async def serve_once(socket_file: Path, handler: Handler) -> asyncio.AbstractServer:
    return await asyncio.start_unix_server(handler, path=socket_file)


async def test_client_sends_request_line_before_reading_response(tmp_path: Path) -> None:
    received: list[bytes] = []

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        line = await reader.readline()
        received.append(line)
        writer.write(json.dumps({"available": True, "turns": []}).encode())
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    socket_file = tmp_path / "session-timeline.sock"
    server = await serve_once(socket_file, handler)
    async with server:
        result = await SessionTimelineSocketClient(str(socket_file)).fetch_window(
            "claude",
            "5b84b3fa-a26f-4642-abf3-851fc35abf3f",
            datetime(2026, 8, 2, 9, 30, tzinfo=UTC),
            datetime(2026, 8, 2, 9, 35, tzinfo=UTC),
        )
    assert result == {"available": True, "turns": []}
    sent = json.loads(received[0])
    assert sent == {
        "provider": "claude",
        "session_uuid": "5b84b3fa-a26f-4642-abf3-851fc35abf3f",
        "bucket_start": "2026-08-02T09:30:00Z",
        "bucket_end": "2026-08-02T09:35:00Z",
    }


async def test_client_without_request_matches_base_behaviour(tmp_path: Path) -> None:
    async def handler(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(b'{"status":"ok"}')
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    socket_file = tmp_path / "session-timeline.sock"
    server = await serve_once(socket_file, handler)
    async with server:
        result = await SessionTimelineSocketClient(str(socket_file)).fetch()
    assert result == {"status": "ok"}


async def test_client_reports_unavailable_socket(tmp_path: Path) -> None:
    with pytest.raises(SessionTimelineSocketError, match="unavailable"):
        await SessionTimelineSocketClient(str(tmp_path / "missing.sock")).fetch_window(
            "claude",
            "abc",
            datetime(2026, 8, 2, 9, 30, tzinfo=UTC),
            datetime(2026, 8, 2, 9, 35, tzinfo=UTC),
        )


async def test_client_enforces_timeout(tmp_path: Path) -> None:
    release = asyncio.Event()

    async def handler(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await release.wait()
        finally:
            writer.close()
            await writer.wait_closed()

    socket_file = tmp_path / "session-timeline.sock"
    server = await serve_once(socket_file, handler)
    async with server:
        with pytest.raises(SessionTimelineSocketError, match="timed out"):
            await SessionTimelineSocketClient(
                str(socket_file), timeout_seconds=0.01
            ).fetch_window(
                "claude",
                "abc",
                datetime(2026, 8, 2, 9, 30, tzinfo=UTC),
                datetime(2026, 8, 2, 9, 35, tzinfo=UTC),
            )
        release.set()
