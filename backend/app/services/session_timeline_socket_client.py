from datetime import datetime

from .unix_socket_json_client import (
    UnixSocketJsonClient,
    UnixSocketJsonResponseError,
    UnixSocketJsonTimeout,
    UnixSocketJsonUnavailable,
)


class SessionTimelineSocketError(RuntimeError):
    """Errore sicuro e tipizzato del boundary session-timeline (BH-04, ADR 010)."""


class SessionTimelineSocketTimeout(SessionTimelineSocketError, UnixSocketJsonTimeout):
    pass


class SessionTimelineSocketUnavailable(SessionTimelineSocketError, UnixSocketJsonUnavailable):
    pass


class SessionTimelineSocketResponseError(
    SessionTimelineSocketError, UnixSocketJsonResponseError
):
    pass


def _iso_utc(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


class SessionTimelineSocketClient(UnixSocketJsonClient):
    """Client one-shot del collector session-timeline (BH-04, ADR 009/010).

    A differenza di host-observability/rate-limit-fresh, la richiesta è
    parametrica: `session_uuid`/`provider`/finestra vanno indicati per ogni
    chiamata, quindi il client invia una riga di richiesta JSON prima di
    leggere la risposta (estensione additiva di `UnixSocketJsonClient.fetch`,
    invariata per gli altri boundary che non passano `request`).
    """

    timeout_error = SessionTimelineSocketTimeout
    unavailable_error = SessionTimelineSocketUnavailable
    response_error = SessionTimelineSocketResponseError

    async def fetch_window(
        self,
        provider: str,
        session_uuid: str,
        bucket_start: datetime,
        bucket_end: datetime,
    ) -> dict[str, object]:
        return await self.fetch(
            {
                "provider": provider,
                "session_uuid": session_uuid,
                "bucket_start": _iso_utc(bucket_start),
                "bucket_end": _iso_utc(bucket_end),
            }
        )
