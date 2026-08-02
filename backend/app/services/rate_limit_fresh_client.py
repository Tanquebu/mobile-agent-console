from pydantic import BaseModel, ValidationError

from .rate_limit_history_service import RateLimitSample
from .unix_socket_json_client import (
    UnixSocketJsonClient,
    UnixSocketJsonResponseError,
    UnixSocketJsonTimeout,
    UnixSocketJsonUnavailable,
)


class RateLimitFreshError(RuntimeError):
    """Errore sicuro e tipizzato dell'aggiornamento on-demand della quota (ADR 010)."""


class RateLimitFreshTimeout(RateLimitFreshError, UnixSocketJsonTimeout):
    pass


class RateLimitFreshUnavailable(RateLimitFreshError, UnixSocketJsonUnavailable):
    pass


class RateLimitFreshResponseError(RateLimitFreshError, UnixSocketJsonResponseError):
    pass


class RateLimitFreshResult(BaseModel):
    """Risposta del collector invocato con `--stdout` (contratto storico budget v1)."""

    collected_at: str
    samples: list[RateLimitSample]


class RateLimitFreshClient(UnixSocketJsonClient):
    """Client one-shot dell'aggiornamento on-demand della quota (ADR 010, ADR 009)."""

    timeout_error = RateLimitFreshTimeout
    unavailable_error = RateLimitFreshUnavailable
    response_error = RateLimitFreshResponseError

    async def fetch_fresh(self) -> RateLimitFreshResult:
        payload = await self.fetch()
        try:
            return RateLimitFreshResult.model_validate(payload)
        except ValidationError as exc:
            raise self.response_error(
                "rate limit collector returned an invalid payload"
            ) from exc
