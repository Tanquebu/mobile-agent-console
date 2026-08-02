import asyncio
import json
from pathlib import Path
from typing import Any


class UnixSocketJsonError(RuntimeError):
    """Errore sicuro e tipizzato di un boundary a socket Unix one-shot."""


class UnixSocketJsonTimeout(UnixSocketJsonError):
    pass


class UnixSocketJsonUnavailable(UnixSocketJsonError):
    pass


class UnixSocketJsonResponseError(UnixSocketJsonError):
    pass


class UnixSocketJsonClient:
    """Client di un collector one-shot attivato da socket (ADR 009, ADR 010).

    Le sottoclassi ridefiniscono le tre classi di errore per restare
    distinguibili nei rispettivi handler, mantenendo identici i messaggi.
    """

    timeout_error: type[UnixSocketJsonError] = UnixSocketJsonTimeout
    unavailable_error: type[UnixSocketJsonError] = UnixSocketJsonUnavailable
    response_error: type[UnixSocketJsonError] = UnixSocketJsonResponseError

    def __init__(
        self,
        socket_file: str,
        *,
        timeout_seconds: float = 3.0,
        max_response_bytes: int = 128 * 1024,
    ) -> None:
        path = Path(socket_file)
        if not path.is_absolute():
            raise ValueError("socket_file must be absolute")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")
        self._socket_file = str(path)
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes

    async def fetch(self) -> dict[str, Any]:
        writer: asyncio.StreamWriter | None = None
        try:
            async with asyncio.timeout(self._timeout_seconds):
                reader, writer = await asyncio.open_unix_connection(self._socket_file)
                payload = bytearray()
                while True:
                    chunk = await reader.read(
                        min(64 * 1024, self._max_response_bytes - len(payload) + 1)
                    )
                    if not chunk:
                        break
                    payload.extend(chunk)
                    if len(payload) > self._max_response_bytes:
                        raise self.response_error(
                            "host collector response exceeds size limit"
                        )
        except TimeoutError as exc:
            raise self.timeout_error("host collector timed out") from exc
        except (ConnectionError, OSError) as exc:
            raise self.unavailable_error("host collector unavailable") from exc
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()

        if not payload:
            raise self.response_error("host collector returned an empty response")
        try:
            decoded = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise self.response_error("host collector returned invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise self.response_error("host collector returned an invalid envelope")
        return decoded
