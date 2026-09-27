"""Prove the asynchronous HTTPX route selected for one actual request URL."""
from __future__ import annotations

import httpcore
import httpx

from .data_handling import DataHandlingRefused

_NATIVE_ASYNC_CLIENT = httpx.AsyncClient
_NATIVE_ROUTE_SELECTOR = httpx.AsyncClient._transport_for_url


def require_direct_async_transport(client, url) -> None:
    """Refuse proxies and opaque injection without dispatching or mutating clients.

    Exact native transport/pool types bind this proof to the installed HTTPX
    implementation. Exact MockTransport is the supported offline testing seam.
    Policy/consent and URL/auth checks remain the caller's responsibility.
    """
    try:
        if type(client) is not _NATIVE_ASYNC_CLIENT:
            raise ValueError('unsupported client')
        selector = client._transport_for_url
        if (getattr(selector, '__func__', None) is not _NATIVE_ROUTE_SELECTOR
                or getattr(selector, '__self__', None) is not client):
            raise ValueError('unsupported route selector')
        transport = selector(httpx.URL(url))
        direct = (type(transport) is httpx.MockTransport
                  or (type(transport) is httpx.AsyncHTTPTransport
                      and type(transport._pool) is httpcore.AsyncConnectionPool))
        if not direct:
            raise ValueError('unsupported selected transport')
    except Exception as exc:
        raise DataHandlingRefused('model transport is not proven direct') from exc
