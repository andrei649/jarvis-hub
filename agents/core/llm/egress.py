"""egress.py — DRA-23: record model-backend HTTP traffic in the H23.16 egress ledger.

The plugin choke point (`core/http_client.py`) feeds `EGRESS_MONITOR` for every plugin
request, and the HUD network panel plus the support bundle present that ledger's
``external_egress_total`` / ``clean`` as proof this install is local-first. Every LLM
backend, though, dialled its own bare ``httpx.AsyncClient``, so a turn answered by
Anthropic or Gemini left the machine without the ledger seeing a thing: the panel could
read "0 external — local-only ✓" while a cloud model answered every question.

`llm_async_client` is the one constructor those backends use instead. It verifies
against the one TLS trust anchor (H504, ``agents/core/tls_trust.verify_for``) and hangs an
httpx request event hook on the client, so the recorded host is the host actually dialled
rather than a guess made from config, and the hook fires for streaming and non-streaming
requests alike.

Scope is deliberate: **anything that carries a prompt, an image, or a model credential**.
The localhost control-plane pollers — router health checks, `ollama_control`,
`lmstudio_control`, `local_model_inventory` — are left out on purpose. They carry no
prompt content and run on a timer, so recording them would flood the 1000-entry ring
buffer and evict the events that matter.

Rows are namespaced ``llm:<provider id>``. LLM backends have no plugin manifest, so the
only thing that gates them here is H368's host-mandated protocol (``host_protocol``): a
host that accepts one protocol only (``api.anthropic.com``, the ``api.openai.com``
family, ``bedrock-runtime.<region>.amazonaws.com``) is never sent another one. That check
runs in the same hook, before the transport, and a refusal is recorded as a row with
``allowed=False`` and the reason — the request, and the credential in its auth header,
never left. Every other row is ``allowed=True``, which is honest: it records what
actually left. `EgressMonitor._local_only_violations` looks each row up in
``BUILTIN_PLUGINS``, misses on the ``llm:`` prefix, and therefore cannot turn a
legitimate cloud call into a fabricated plugin violation.
"""

from __future__ import annotations

import httpx

from agents.core.observability.egress_monitor import EGRESS_MONITOR

from .host_protocol import HostProtocolRefused, protocol_refusal


def _record(backend: str, request: httpx.Request, *, allowed: bool, reason: str = "") -> None:
    # Observability must never break generation — mirrors `_record_egress`.
    try:
        from agents.core.http_client import host_is_local
        host = (request.url.host or "").lower().rstrip(".")
        EGRESS_MONITOR.record(
            f"llm:{backend}",
            host,
            request.method,
            allowed=allowed,
            local=host_is_local(host),
            reason=reason,
        )
    except Exception:
        pass


def _recorder(backend: str):
    """Build the async httpx request hook: refuse a protocol/host mismatch, then record.

    httpx runs request hooks before each dispatch — including every hop of a followed
    redirect — so a raise here means the transport never sees the request.
    """

    async def _hook(request: httpx.Request) -> None:
        reason = protocol_refusal(backend, request.url)
        if reason:
            _record(backend, request, allowed=False, reason=reason)
            raise HostProtocolRefused(reason)
        _record(backend, request, allowed=True)

    return _hook


def llm_async_client(backend: str, **kwargs) -> httpx.AsyncClient:
    """An ``httpx.AsyncClient`` whose requests land in the egress ledger.

    All other kwargs (``base_url``, ``timeout``, …) pass straight through, so callers
    keep the timeouts they already tuned. The ledger hook is appended last, so it sees
    the request exactly as it is about to be dispatched.
    """
    from .quota import request_hook, response_hook

    event_hooks = dict(kwargs.pop("event_hooks", None) or {})
    # H373: the shared 429 guard refuses first (a refused request never left, so it is not
    # an egress row); every cloud response's quota headers are then recorded.
    event_hooks["request"] = [*event_hooks.get("request", []), request_hook(backend), _recorder(backend)]
    event_hooks["response"] = [*event_hooks.get("response", []), response_hook(backend)]
    # H504: every model client verifies against the one trust anchor (JARVIS_CA_BUNDLE
    # included). An explicit SSLContext also means httpx never reads SSL_CERT_FILE on its
    # own, so a client that keeps trust_env for the owner's proxy cannot fail on an
    # unnamed file. A test's own transport, or a caller's own verify, is left alone.
    if "verify" not in kwargs and kwargs.get("transport") is None:
        from agents.core.tls_trust import verify_for

        kwargs["verify"] = verify_for(backend, kwargs.get("base_url"))
    return httpx.AsyncClient(event_hooks=event_hooks, **kwargs)
