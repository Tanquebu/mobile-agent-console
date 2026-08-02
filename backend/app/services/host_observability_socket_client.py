from .unix_socket_json_client import (
    UnixSocketJsonClient,
    UnixSocketJsonResponseError,
    UnixSocketJsonTimeout,
    UnixSocketJsonUnavailable,
)


class HostObservabilitySocketError(RuntimeError):
    """Errore sicuro e tipizzato del boundary host-observability."""


class HostObservabilitySocketTimeout(HostObservabilitySocketError, UnixSocketJsonTimeout):
    pass


class HostObservabilitySocketUnavailable(HostObservabilitySocketError, UnixSocketJsonUnavailable):
    pass


class HostObservabilitySocketResponseError(
    HostObservabilitySocketError, UnixSocketJsonResponseError
):
    pass


class HostObservabilitySocketClient(UnixSocketJsonClient):
    """Client one-shot del collector host-observability (ADR 009).

    Il trasporto socket è ora la base generica `UnixSocketJsonClient`; qui
    restano solo le classi di errore tipizzate per questo boundary, invariate
    nei messaggi (contratto testato in `test_host_observability_socket_client.py`).
    """

    timeout_error = HostObservabilitySocketTimeout
    unavailable_error = HostObservabilitySocketUnavailable
    response_error = HostObservabilitySocketResponseError
