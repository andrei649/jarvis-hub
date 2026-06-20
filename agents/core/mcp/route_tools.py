"""route_tools.py — H22.9 (read-only scope) agent-native route tools.

Exposes an **allow-listed, READ-ONLY** subset of the hub's FastAPI routes as MCP
tools (``route_<name>``) alongside the existing ``ask_<agent>`` agent tools, so an
MCP client can read hub state through governed tools.

Design (mirrors the agent allow-list in ``server.py``):

  * **Allow-list, never auto-expose.** A route is reachable over MCP only if it is
    in ``ROUTE_TOOL_ALLOWLIST``. Nothing else is exposed. **Mutating routes are
    out of scope** (post-1.0) — every entry here is read-only (HTTP GET).
  * **In-process dispatch**, not a loopback HTTP call: ``call_tool`` invokes the
    route's handler coroutine directly and normalises the return to JSON.
  * **Kill-switch.** ``JARVIS_MCP_ROUTE_TOOLS`` (default OFF). When off, the MCP
    server exposes only the agent tools — today's behaviour, unchanged.
  * **Hand-declared minimal schemas.** Rather than pull full OpenAPI extraction
    into the server (heavy, and the app-build import cycle makes it awkward), each
    allow-listed entry carries a small, correct ``input_schema``. Read-only GET
    routes take few/no params, so the schemas stay tiny and are unit-tested.

The route **handlers** are injected by the caller (``web.py``) so this module — and
the tests — need no live app or orchestrator.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

ROUTE_TOOL_ENV = "JARVIS_MCP_ROUTE_TOOLS"
ROUTE_TOOL_PREFIX = "route_"

# A route handler: an async callable returning either a plain dict/list or an
# object with a ``.body`` (e.g. a Starlette ``JSONResponse``). It is called with
# only the keyword arguments named in the tool's ``input_schema`` properties.
RouteHandler = Callable[..., Awaitable[Any]]


@dataclass(frozen=True)
class RouteToolSpec:
    """Static description of an allow-listed read-only route, sans handler.

    ``name`` is the bare tool key (the MCP tool is ``route_<name>``). ``method``
    is documentation-only here — every allow-listed route is a read-only GET.
    """

    name: str
    path: str
    summary: str
    input_schema: dict
    method: str = "GET"


# ── The allow-list: curated, READ-ONLY routes only ──────────────────────────────
#
# Keep this small and explicit. Every entry MUST be a read-only (GET) route.
# Never add a mutating route here (that is post-1.0, out of H22.9 scope).
ROUTE_TOOL_ALLOWLIST: tuple[RouteToolSpec, ...] = (
    RouteToolSpec(
        name="status",
        path="/status",
        summary="Hub health: version, system info, LLM/model state, agent roster.",
        input_schema={"type": "object", "properties": {}},
    ),
    RouteToolSpec(
        name="memory_search",
        path="/api/memory/search",
        summary="Fused recall over memory (vector + knowledge-graph). Read-only.",
        input_schema={
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "Search query."},
                "top_k": {
                    "type": "integer",
                    "description": "Max results (1-50).",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 10,
                },
            },
        },
    ),
    RouteToolSpec(
        name="dashboard",
        path="/dashboard",
        summary="HUD dashboard payload (weather, news, agent summary). Read-only.",
        input_schema={"type": "object", "properties": {}},
    ),
)

ALLOWLIST_BY_NAME: dict[str, RouteToolSpec] = {s.name: s for s in ROUTE_TOOL_ALLOWLIST}


def route_tools_enabled() -> bool:
    """Kill-switch: True only when ``JARVIS_MCP_ROUTE_TOOLS`` is a truthy value.

    Default OFF. Accepts ``1/true/yes/on`` (case-insensitive).
    """
    val = os.environ.get(ROUTE_TOOL_ENV, "").strip().lower()
    return val in ("1", "true", "yes", "on")


def route_tool_name(name: str) -> str:
    return f"{ROUTE_TOOL_PREFIX}{name}"


@dataclass
class RouteTool:
    """An allow-listed route bound to its in-process handler."""

    spec: RouteToolSpec
    handler: RouteHandler

    @property
    def tool_name(self) -> str:
        return route_tool_name(self.spec.name)

    def descriptor(self) -> dict:
        return {
            "name": self.tool_name,
            "description": self.spec.summary,
            "inputSchema": self.spec.input_schema,
        }

    def filtered_kwargs(self, arguments: dict | None) -> dict:
        """Keep only arguments declared in the schema (defence in depth)."""
        allowed = set(self.spec.input_schema.get("properties", {}).keys())
        return {k: v for k, v in (arguments or {}).items() if k in allowed}


def build_route_tools(
    handlers: dict[str, RouteHandler],
    allowlist: tuple[RouteToolSpec, ...] = ROUTE_TOOL_ALLOWLIST,
) -> list["RouteTool"]:
    """Bind allow-listed specs to provided handlers.

    Only entries with a handler are returned; a missing handler silently drops
    that tool (a route the app does not expose is simply not offered over MCP).
    """
    tools: list[RouteTool] = []
    for spec in allowlist:
        handler = handlers.get(spec.name)
        if handler is None:
            continue
        tools.append(RouteTool(spec=spec, handler=handler))
    return tools


def normalize_result(result: Any) -> Any:
    """Turn a route handler's return value into JSON-able content.

    Handlers return either a plain dict/list (FastAPI would JSON-encode it) or a
    Starlette ``JSONResponse`` whose ``.body`` is encoded bytes. Decode the
    latter so the MCP tool result carries the same payload as the HTTP endpoint.
    """
    body = getattr(result, "body", None)
    if body is not None:
        import json

        raw = body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else str(body)
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return raw
    return result
