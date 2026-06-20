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
  * **Reflected schemas (no hand-drift).** A tool's ``inputSchema`` is **derived
    from the route handler's own signature** (``inspect.signature`` + type hints,
    plus pydantic field defaults when a param is a pydantic model). This is
    lightweight — it reflects only the handler function, it does NOT import or
    build the whole FastAPI app graph / ``app.openapi()``. A drift-guard test
    asserts the derived schema matches the live handler, so a future signature
    change that nobody mirrors fails CI rather than silently going stale.

The route **handlers** are injected by the caller (``web.py``) so this module — and
the tests — need no live app or orchestrator.
"""

from __future__ import annotations

import inspect
import os
import types
import typing
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

ROUTE_TOOL_ENV = "JARVIS_MCP_ROUTE_TOOLS"
ROUTE_TOOL_PREFIX = "route_"

# H22.9 (mutating scope) — a SECOND, independent kill-switch. Mutating route
# tools are exposed only when BOTH this AND ``JARVIS_MCP_ROUTE_TOOLS`` are on.
MUTATING_TOOL_ENV = "JARVIS_MCP_MUTATING_TOOLS"

# A route handler: an async callable returning either a plain dict/list or an
# object with a ``.body`` (e.g. a Starlette ``JSONResponse``). It is called with
# only the keyword arguments named in the tool's ``input_schema`` properties.
RouteHandler = Callable[..., Awaitable[Any]]


@dataclass(frozen=True)
class RouteToolSpec:
    """Static description of an allow-listed read-only route, sans handler.

    ``name`` is the bare tool key (the MCP tool is ``route_<name>``). ``method``
    is documentation-only here — every allow-listed route is a read-only GET.

    Note: the input schema is **not** declared here — it is reflected from the
    bound handler's signature at build time (see ``derive_input_schema``), so it
    cannot drift from the route's real parameters.
    """

    name: str
    path: str
    summary: str
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
    ),
    RouteToolSpec(
        name="memory_search",
        path="/api/memory/search",
        summary="Fused recall over memory (vector + knowledge-graph). Read-only.",
    ),
    RouteToolSpec(
        name="dashboard",
        path="/dashboard",
        summary="HUD dashboard payload (weather, news, agent summary). Read-only.",
    ),
)

ALLOWLIST_BY_NAME: dict[str, RouteToolSpec] = {s.name: s for s in ROUTE_TOOL_ALLOWLIST}


# ── Signature → JSON-schema reflection ──────────────────────────────────────────
#
# Map a route handler's own parameters to a minimal JSON-schema. We reflect ONLY
# the handler function (inspect.signature + type hints); we never import/build the
# whole FastAPI app graph or call ``app.openapi()``.

# Python annotation → JSON-schema "type". Anything not here falls back to leaving
# the type out (an open "any") rather than guessing wrong — surfaced as a caveat.
_JSON_TYPE_BY_PY: dict[type, str] = {
    str: "string",
    bool: "boolean",
    int: "integer",
    float: "number",
    list: "array",
    dict: "object",
}

# FastAPI / Starlette parameters that are injected by the framework, not supplied
# by the MCP caller — skip them when reflecting (the in-process dispatch in
# server.py calls the handler with only the schema's properties as kwargs).
_INJECTED_PARAM_TYPE_NAMES = frozenset({"Request", "Response", "WebSocket", "BackgroundTasks"})


def _is_pydantic_model(tp: Any) -> bool:
    return isinstance(tp, type) and hasattr(tp, "model_fields")


def _json_type_for(annotation: Any) -> str | None:
    """Best-effort JSON-schema type for a Python annotation.

    Unwraps ``Optional[T]`` / ``T | None``. Returns ``None`` when the type can't
    be inferred (annotation missing or unknown), so callers can emit an open
    property instead of guessing.
    """
    if annotation is inspect.Parameter.empty or annotation is None:
        return None
    origin = typing.get_origin(annotation)
    if origin is typing.Union or origin is getattr(types, "UnionType", None):
        non_none = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(non_none) == 1:
            return _json_type_for(non_none[0])
        return None
    if origin in (list, tuple, set, frozenset):
        return "array"
    if origin is dict:
        return "object"
    if isinstance(annotation, type):
        return _JSON_TYPE_BY_PY.get(annotation)
    return None


def _should_skip_param(param: inspect.Parameter) -> bool:
    """True for params the framework injects (Request/Response/Depends/etc.)."""
    if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
        return True
    ann = param.annotation
    type_name = getattr(ann, "__name__", "")
    if type_name in _INJECTED_PARAM_TYPE_NAMES:
        return True
    # A ``Depends(...)`` / ``Security(...)`` default is a framework injection.
    default = param.default
    default_cls = type(default).__name__
    if default_cls in ("Depends", "Security"):
        return True
    return False


def _property_for(param: inspect.Parameter) -> dict:
    """Build the JSON-schema property object for one handler parameter."""
    prop: dict[str, Any] = {}
    jtype = _json_type_for(param.annotation)
    if jtype is not None:
        prop["type"] = jtype
    if param.default is not inspect.Parameter.empty and _is_jsonable_default(param.default):
        prop["default"] = param.default
    return prop


def _is_jsonable_default(value: Any) -> bool:
    """Only surface a default that is a plain JSON scalar/container.

    FastAPI markers (``Query(...)``, ``Depends(...)``) and arbitrary objects are
    excluded so we never leak a framework sentinel into the schema.
    """
    return isinstance(value, (str, int, float, bool, list, dict)) or value is None


def derive_input_schema(handler: RouteHandler) -> dict:
    """Reflect a route handler's signature into a minimal JSON input schema.

    * Walks ``inspect.signature`` + resolved type hints of the handler itself.
    * Skips framework-injected params (``Request``/``Depends``/``*args``/…).
    * If a remaining param is a **pydantic model**, expands its fields into
      properties (using each field's type + whether it is required), since FastAPI
      would flatten such a body/query model into individual parameters.
    * A param with no default is ``required``.

    Lightweight by design: only the handler function is reflected — no app build,
    no ``app.openapi()``.
    """
    schema: dict[str, Any] = {"type": "object", "properties": {}}
    properties: dict[str, dict] = schema["properties"]
    required: list[str] = []

    try:
        sig = inspect.signature(handler)
    except (TypeError, ValueError):
        return schema
    try:
        hints = typing.get_type_hints(handler)
    except Exception:
        hints = {}

    for pname, param in sig.parameters.items():
        if _should_skip_param(param):
            continue
        # Prefer a resolved type hint over the raw (possibly string) annotation.
        annotation = hints.get(pname, param.annotation)
        param = param.replace(annotation=annotation)

        if _is_pydantic_model(annotation):
            _expand_pydantic_model(annotation, properties, required)
            continue

        properties[pname] = _property_for(param)
        if param.default is inspect.Parameter.empty:
            required.append(pname)

    if required:
        schema["required"] = required
    return schema


def _expand_pydantic_model(model: Any, properties: dict, required: list) -> None:
    """Flatten a pydantic model's fields into schema properties (pydantic v2)."""
    for fname, field in model.model_fields.items():
        prop: dict[str, Any] = {}
        jtype = _json_type_for(field.annotation)
        if jtype is not None:
            prop["type"] = jtype
        if field.is_required():
            required.append(fname)
        else:
            default = getattr(field, "default", None)
            if _is_jsonable_default(default) and default is not None:
                prop["default"] = default
        properties[fname] = prop


def route_tools_enabled() -> bool:
    """Kill-switch: True only when ``JARVIS_MCP_ROUTE_TOOLS`` is a truthy value.

    Default OFF. Accepts ``1/true/yes/on`` (case-insensitive).
    """
    val = os.environ.get(ROUTE_TOOL_ENV, "").strip().lower()
    return val in ("1", "true", "yes", "on")


def mutating_tools_enabled() -> bool:
    """SECOND kill-switch for the MUTATING (write) scope. Default OFF.

    Independent of ``route_tools_enabled()``. Mutating route tools are exposed
    only when BOTH switches are on (see ``build_mutating_route_tools``), so a
    single flag can never widen the write surface by itself.
    """
    val = os.environ.get(MUTATING_TOOL_ENV, "").strip().lower()
    return val in ("1", "true", "yes", "on")


def route_tool_name(name: str) -> str:
    return f"{ROUTE_TOOL_PREFIX}{name}"


@dataclass
class RouteTool:
    """An allow-listed route bound to its in-process handler.

    The ``input_schema`` is **reflected from the bound handler's signature** at
    construction (see ``derive_input_schema``), so it can never drift from the
    route's real parameters — a CI drift-guard test enforces this.
    """

    spec: RouteToolSpec
    handler: RouteHandler
    input_schema: dict = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.input_schema is None:
            self.input_schema = derive_input_schema(self.handler)

    @property
    def tool_name(self) -> str:
        return route_tool_name(self.spec.name)

    def descriptor(self) -> dict:
        return {
            "name": self.tool_name,
            "description": self.spec.summary,
            "inputSchema": self.input_schema,
        }

    def filtered_kwargs(self, arguments: dict | None) -> dict:
        """Keep only arguments declared in the schema (defence in depth)."""
        allowed = set(self.input_schema.get("properties", {}).keys())
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


# ══════════════════════════════════════════════════════════════════════════════
# H22.9 — MUTATING (write) scope.  STACKED on the read-only scope above.
# ══════════════════════════════════════════════════════════════════════════════
#
# This exposes a SEPARATE, explicit allow-list of MUTATING (write) routes as MCP
# tools — but ONLY behind a SECOND, independent, default-OFF kill-switch
# (``JARVIS_MCP_MUTATING_TOOLS``) AND with the read-only switch
# (``JARVIS_MCP_ROUTE_TOOLS``) also on. With the mutating switch off the
# read-only behaviour above is 100% unchanged.
#
# Why a separate mechanism (not just more ``RouteToolSpec`` rows):
#   * Read-only tools dispatch by reflecting the handler signature and passing
#     schema kwargs. Real write handlers (e.g. ``memory_remember``) take a raw
#     Starlette ``Request`` and read ``await req.json()`` — they cannot be driven
#     by kwargs. So a mutating tool carries an explicit ``invoke`` adapter that
#     performs the same write the HTTP route would, plus an explicit input schema.
#   * Every mutating invocation is AUDITED through ``AuditLogger.log`` before the
#     result is returned, so the write surface always leaves a hash-chained trail.
#
# ⚠️  SECURITY CAVEAT — REMAINING HARDENING BEFORE NETWORK EXPOSURE  ⚠️
# There is NO ``Request`` object in this in-process dispatch path, so the HTTP
# route's per-identity guard (``Depends(user_guard)`` → token/cookie identity)
# is NOT enforced here. For now the gate is: (1) the explicit mutating allow-list,
# (2) the DOUBLE default-OFF kill-switch, and (3) the audit record. That is
# adequate ONLY for a LAN-only, single-trust-domain deployment. Before this is
# ever enabled on a network-exposed instance, real per-identity guard wiring
# (an identity/token threaded into ``invoke`` and checked the same way the HTTP
# guard checks it) MUST be added. Until then, keep ``JARVIS_MCP_MUTATING_TOOLS``
# OFF on anything reachable beyond localhost/LAN.

MUTATING_ROUTE_PREFIX = ROUTE_TOOL_PREFIX  # mutating tools share the route_ prefix


# An ``invoke`` adapter: ``async (arguments: dict) -> Any``. It performs the same
# write the HTTP route performs and returns a JSON-able payload (or a
# JSONResponse-like object with ``.body``; ``normalize_result`` decodes either).
MutatingInvoke = Callable[[dict], Awaitable[Any]]


@dataclass(frozen=True)
class MutatingRouteSpec:
    """Static description of an allow-listed MUTATING (write) route.

    Unlike ``RouteToolSpec``, the input schema is declared explicitly here: the
    real write handlers read their body off a ``Request`` (not kwargs), so there
    is no signature to reflect. ``method`` is documentation-only (always a write
    verb — POST/PUT/PATCH/DELETE).
    """

    name: str
    path: str
    summary: str
    input_schema: dict
    method: str = "POST"


# ── The MUTATING allow-list: curated, WRITE routes only ─────────────────────────
#
# Keep this SMALL and conservative — each entry widens the externally-drivable
# write surface of the hub. Every entry MUST be a clearly-bounded write.
#
# ``memory_remember`` (``POST /api/memory/remember``) is included: it stores a
# single text fact in long-term memory with optional metadata. It is bounded
# (append-only, no delete/overwrite of arbitrary state), genuinely useful for an
# agent, and its body is a simple ``{text, metadata?}`` — easy to schema and audit.
MUTATING_ROUTE_ALLOWLIST: tuple[MutatingRouteSpec, ...] = (
    MutatingRouteSpec(
        name="memory_remember",
        path="/api/memory/remember",
        summary="Store a single text fact in long-term memory (append-only write).",
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The fact to remember."},
                "metadata": {"type": "object", "description": "Optional metadata tags."},
            },
            "required": ["text"],
        },
    ),
)

MUTATING_ALLOWLIST_BY_NAME: dict[str, MutatingRouteSpec] = {
    s.name: s for s in MUTATING_ROUTE_ALLOWLIST
}


@dataclass
class MutatingRouteTool:
    """An allow-listed MUTATING route bound to its in-process write adapter.

    Every call is AUDITED (through the injected ``auditor.log``) before the
    result is returned. The descriptor is marked ``"mutating": True`` so a client
    can tell a write tool from a read tool.
    """

    spec: MutatingRouteSpec
    invoke: MutatingInvoke
    auditor: Any = None  # an AuditLogger-like object exposing ``log(SecurityEvent)``

    @property
    def tool_name(self) -> str:
        return route_tool_name(self.spec.name)

    def descriptor(self) -> dict:
        return {
            "name": self.tool_name,
            "description": self.spec.summary,
            "inputSchema": self.spec.input_schema,
            # Explicit marker: this tool WRITES. Read tools never carry this.
            "mutating": True,
        }

    def filtered_kwargs(self, arguments: dict | None) -> dict:
        """Keep only arguments declared in the schema (defence in depth)."""
        allowed = set(self.spec.input_schema.get("properties", {}).keys())
        return {k: v for k, v in (arguments or {}).items() if k in allowed}

    def _audit(self, arguments: dict, outcome: str) -> None:
        """Append one hash-chained audit row for this write invocation.

        Best-effort: an auditor failure must never break the tool call (the write
        either happened or not regardless), but it is logged. Reuses the same
        ``SecurityEvent``/``AuditLogger.log`` path the HTTP turn-loop uses.
        """
        if self.auditor is None:
            return
        try:
            import time

            from agents.core.security.types import SecurityEvent, SecurityEventType

            # Record the keys written, NOT the values — avoid persisting raw
            # user content (e.g. the remembered text) into the audit preview.
            keys = sorted(self.filtered_kwargs(arguments).keys())
            event = SecurityEvent(
                event_type=SecurityEventType.AUDIT_LOG,
                timestamp=time.time(),
                findings=[],
                content_preview=f"mcp mutating tool {self.tool_name} keys={keys}"[:100],
                action_taken=f"{self.spec.method} {self.spec.path} via mcp ({outcome})",
            )
            self.auditor.log(event)
        except Exception:  # pragma: no cover - auditing is best-effort
            import logging

            logging.getLogger(__name__).warning(
                "audit log failed for mutating tool %s", self.tool_name, exc_info=True
            )

    async def call(self, arguments: dict | None) -> Any:
        """Run the write adapter with schema-filtered args, auditing the call.

        The audit row is written whether the invoke succeeds or raises, so an
        attempted write is never invisible. Exceptions propagate to the server,
        which converts them to a tool error (no stack trace leaks to the client).
        """
        kwargs = self.filtered_kwargs(arguments)
        try:
            result = await self.invoke(kwargs)
        except Exception:
            self._audit(arguments, outcome="error")
            raise
        self._audit(arguments, outcome="ok")
        return result


def build_mutating_route_tools(
    invokers: dict[str, MutatingInvoke],
    auditor: Any = None,
    allowlist: tuple[MutatingRouteSpec, ...] = MUTATING_ROUTE_ALLOWLIST,
    *,
    read_only_enabled: bool | None = None,
    mutating_enabled: bool | None = None,
) -> list["MutatingRouteTool"]:
    """Bind allow-listed mutating specs to provided write adapters.

    The DOUBLE kill-switch is enforced here: unless BOTH the read-only switch AND
    the mutating switch are on, this returns ``[]`` (no mutating tools). By
    default the switches are read from the environment; tests may pass explicit
    booleans. A spec without a provided invoker is silently not offered.
    """
    if read_only_enabled is None:
        read_only_enabled = route_tools_enabled()
    if mutating_enabled is None:
        mutating_enabled = mutating_tools_enabled()
    if not (read_only_enabled and mutating_enabled):
        return []

    tools: list[MutatingRouteTool] = []
    for spec in allowlist:
        invoke = invokers.get(spec.name)
        if invoke is None:
            continue
        tools.append(MutatingRouteTool(spec=spec, invoke=invoke, auditor=auditor))
    return tools
