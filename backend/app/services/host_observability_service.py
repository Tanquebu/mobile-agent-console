from pydantic import ValidationError

from .host_observability_contract import HostObservabilitySnapshot
from .host_observability_socket_client import (
    HostObservabilitySocketClient,
    HostObservabilitySocketResponseError,
    HostObservabilitySocketTimeout,
    HostObservabilitySocketUnavailable,
)


class HostObservabilityUnavailable(RuntimeError):
    pass


class HostObservabilityTimeout(RuntimeError):
    pass


class HostObservabilityInvalidResponse(RuntimeError):
    pass


class HostObservabilityService:
    def __init__(self, client: HostObservabilitySocketClient) -> None:
        self._client = client

    async def read(self) -> HostObservabilitySnapshot:
        try:
            payload = await self._client.fetch()
        except HostObservabilitySocketTimeout as exc:
            raise HostObservabilityTimeout from exc
        except HostObservabilitySocketUnavailable as exc:
            raise HostObservabilityUnavailable from exc
        except HostObservabilitySocketResponseError as exc:
            raise HostObservabilityInvalidResponse from exc
        try:
            return HostObservabilitySnapshot.model_validate(payload)
        except ValidationError as exc:
            raise HostObservabilityInvalidResponse from exc
