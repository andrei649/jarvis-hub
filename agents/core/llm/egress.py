"""egress.py — DRA-23: record model-backend HTTP traffic in the H23.16 egress ledger.

The plugin choke point (`core/http_client.py`) feeds `EGRESS_MONITOR` for every plugin
request, and the HUD network panel plus the support bundle present that ledger's
``external_egress_total`` / ``clean`` as proof this install is local-first. Every LLM
backend, though, dialled its own bare ``httpx.AsyncClient``, so a turn answered by
Anthropic or Gemini left the machine without the ledger seeing a thing: the panel could
read "0 external — local-only ✓" while a cloud model answered every question.

`llm_async_client` is the one constructor those backends use instead. It hangs an httpx
request event hook on the client, so the recorded host is the host actually dialled
rather than a guess made from config, and the hook fires for streaming and non-streaming
requests alike.

Scope is deliberate: **anything that carries a prompt, an image, or a model credential**.
The localhost control-plane pollers — router health checks, `ollama_control`,
`lmstudio_control`, `local_model_inventory` — are left out on purpose. They carry no
prompt content and run on a timer, so recording them would flood the 1000-entry ring
buffer and evict the events that matter.

Rows are namespaced ``llm:<provider id>``. ``allowed`` is always True and that is honest:
LLM backends have no plugin manifest and nothing gates them, so this ledger records what
actually left, never a block that did not happen. `EgressMonitor._local_only_violations`
looks each row up in ``BUILTIN_PLUGINS``, misses on the ``llm:`` prefix, and therefore
cannot turn a legitimate cloud call into a fabricated plugin violation.
"""

from __future__ import annotations

import httpx

from agents.core.observability.egress_monitor import EGRESS_MONITOR


def _recorder(backend: str):
    """Build the async httpx request hook that writes one ledger row per request."""

    async def _hook(request: httpx.Request) -> None:
        # Observability must never break generation — mirrors `_record_egress`.
        try:
            from agents.core.http_client import host_is_local
            host = (request.url.host or "").lower().rstrip(".")
            EGRESS_MONITOR.record(
                f"llm:{backend}",
                host,
                request.method,
                allowed=True,
                local=host_is_local(host),
            )
        except Exception:
            pass

    return _hook


def llm_async_client(backend: str, **kwargs) -> httpx.AsyncClient:
    """An ``httpx.AsyncClient`` whose requests land in the egress ledger.

    All other kwargs (``base_url``, ``timeout``, …) pass straight through, so callers
    keep the timeouts they already tuned.
    """
    event_hooks = dict(kwargs.pop("event_hooks", None) or {})
    event_hooks["request"] = [*event_hooks.get("request", []), _recorder(backend)]
    return httpx.AsyncClient(event_hooks=event_hooks, **kwargs)
