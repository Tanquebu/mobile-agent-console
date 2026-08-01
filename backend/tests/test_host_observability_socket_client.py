import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from app.config import Settings
from app.services.host_observability_socket_client import (
    HostObservabilitySocketClient,
    HostObservabilitySocketError,
)

Handler = Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]]


async def serve_once(socket_file: Path, handler: Handler) -> asyncio.AbstractServer:
    return await asyncio.start_unix_server(handler, path=socket_file)


async def write_response(
    _reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    writer.write(b'{"schema_version":1,"source":"socket-activation-spike","status":"ok"}')
    await writer.drain()
    writer.close()
    await writer.wait_closed()


async def test_client_reads_json_from_unix_socket(tmp_path: Path) -> None:
    socket_file = tmp_path / "collector.sock"
    server = await serve_once(socket_file, write_response)
    async with server:
        result = await HostObservabilitySocketClient(str(socket_file)).fetch()
    assert result == {
        "schema_version": 1,
        "source": "socket-activation-spike",
        "status": "ok",
    }


async def test_client_supports_concurrent_connections(tmp_path: Path) -> None:
    socket_file = tmp_path / "collector.sock"
    server = await serve_once(socket_file, write_response)
    client = HostObservabilitySocketClient(str(socket_file))
    async with server:
        responses = await asyncio.gather(*(client.fetch() for _ in range(4)))
    assert len(responses) == 4
    assert all(response["status"] == "ok" for response in responses)


@pytest.mark.parametrize(
    ("payload", "message", "limit"),
    [
        (b"not-json", "invalid JSON", 1024),
        (json.dumps(["not", "an", "object"]).encode(), "invalid envelope", 1024),
        (b"x" * 1025, "exceeds size limit", 1024),
        (b"", "empty response", 1024),
    ],
)
async def test_client_rejects_invalid_responses(
    tmp_path: Path, payload: bytes, message: str, limit: int
) -> None:
    async def handler(
        _reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        writer.write(payload)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    socket_file = tmp_path / "collector.sock"
    server = await serve_once(socket_file, handler)
    async with server:
        with pytest.raises(HostObservabilitySocketError, match=message):
            await HostObservabilitySocketClient(
                str(socket_file), max_response_bytes=limit
            ).fetch()


async def test_client_rejects_delayed_bytes_beyond_size_limit(tmp_path: Path) -> None:
    first_chunk_written = asyncio.Event()
    release_tail = asyncio.Event()

    async def handler(
        _reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        writer.write(b'{"status":"ok"}')
        await writer.drain()
        first_chunk_written.set()
        await release_tail.wait()
        writer.write(b"x" * 2048)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    socket_file = tmp_path / "collector.sock"
    server = await serve_once(socket_file, handler)
    client = HostObservabilitySocketClient(
        str(socket_file), timeout_seconds=1, max_response_bytes=1024
    )
    async with server:
        fetch = asyncio.create_task(client.fetch())
        await first_chunk_written.wait()
        await asyncio.sleep(0)
        assert not fetch.done()
        release_tail.set()
        with pytest.raises(HostObservabilitySocketError, match="exceeds size limit"):
            await fetch


async def test_client_enforces_timeout(tmp_path: Path) -> None:
    release = asyncio.Event()

    async def handler(
        _reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            await release.wait()
        finally:
            writer.close()
            await writer.wait_closed()

    socket_file = tmp_path / "collector.sock"
    server = await serve_once(socket_file, handler)
    async with server:
        with pytest.raises(HostObservabilitySocketError, match="timed out"):
            await HostObservabilitySocketClient(
                str(socket_file), timeout_seconds=0.01
            ).fetch()
        release.set()


async def test_client_reports_unavailable_socket(tmp_path: Path) -> None:
    with pytest.raises(HostObservabilitySocketError, match="unavailable"):
        await HostObservabilitySocketClient(str(tmp_path / "missing.sock")).fetch()


def test_settings_validate_host_observability_socket_configuration() -> None:
    settings = Settings(
        host_observability_socket_file="/run/mac/host.sock",
        host_observability_socket_timeout_seconds=2.5,
        host_observability_max_response_bytes=4096,
    )
    assert settings.host_observability_socket_file == "/run/mac/host.sock"
    assert settings.host_observability_socket_timeout_seconds == 2.5
    assert settings.host_observability_max_response_bytes == 4096

    with pytest.raises(ValueError, match="absolute path"):
        Settings(host_observability_socket_file="relative.sock")
    with pytest.raises(ValueError, match="absolute path"):
        Settings(host_observability_socket_file="/run/mac/../private.sock")
    with pytest.raises(ValueError):
        Settings(host_observability_max_response_bytes=128 * 1024 + 1)
