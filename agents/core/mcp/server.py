"""
server.py — H10.5 MCP Server Mode.

Exposes Jarvis agents as **governed** Model Context Protocol tools so any MCP
client (Claude Desktop, Cursor, another Jarvis) can call a Jarvis agent as a
tool. This is the inverse of ``client.py`` (which consumes external MCP tools).

Design goals:
  * **Transport-agnostic core** — ``handle()`` dispatches a JSON-RPC 2.0 message
    (initialize / tools/list / tools/call). The HTTP route in ``routers/mcp.py``
    and the stdio loop below (``serve_stdio`` / ``run_stdio_loop``) just feed
    messages in and write results out. ``scripts/nerva_mcp_stdio.py`` is the
    stdio bridge a desktop MCP client launches to reach a running hub.
  * **Governed** — only allow-listed agents are exposed; calls route through the
    orchestrator (so guardrails + permission gate still apply). LAN-only by
    default (a deployment/bind concern surfaced in ``status()``).
  * **Offline-testable** — the runner is injected, so tests need no orchestrator.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from agents.core.mcp.route_tools import (
    ROUTE_TOOL_PREFIX,
    MutatingIdentityError,
    MutatingRouteTool,
    RouteTool,
    normalize_result,
)

PROTOCOL_VERSION = "2025-11-25"
SERVER_NAME = "jarvis-hub"
SERVER_VERSION = "1.0"

# JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

#: One newline-delimited JSON-RPC frame may not exceed this (stdio transport).
MAX_STDIO_LINE_BYTES = 4 * 1024 * 1024

logger = logging.getLogger("jarvis.mcp.server")

# Agent runner: ``async (agent_id, text) -> str``
AgentRunner = Callable[[str, str], Awaitable[str]]
AgentRequestGuard = Callable[[str, str, object | None], Optional[str]]


@dataclass(frozen=True)
class VerifiedMCPIdentity:
    """Transport-verified MCP identity, constructed only after OAuth validation.

    A distinct type avoids treating an attacker-controlled header string such as
    ``"oauth:anyone"`` as proof that the resource-server signature, audience and
    scope checks succeeded.
    """

    subject: str
    mechanism: str = "oauth2.1"


_agent_request_authorized: ContextVar[bool] = ContextVar(
    "jarvis_mcp_agent_request_authorized", default=False
)


def current_mcp_agent_request_authorized() -> bool:
    """Whether the current MCP ``ask_*`` call passed its production guard."""

    return bool(_agent_request_authorized.get())


def _tool_name(agent_id: str) -> str:
    return f"ask_{agent_id}"


class JarvisMCPServer:
    def __init__(
        self,
        runner: AgentRunner,
        agents: dict[str, str],
        allowed_agents: Optional[list[str]] = None,
        lan_only: bool = True,
        route_tools: Optional[list[RouteTool]] = None,
        mutating_route_tools: Optional[list[MutatingRouteTool]] = None,
        agent_request_guard: Optional[AgentRequestGuard] = None,
    ) -> None:
        """
        Parameters
        ----------
        runner: ``async (agent_id, text) -> str`` — routes through the orchestrator.
        agents: ``{agent_id: human-description}`` of all known agents.
        allowed_agents: subset exposed as tools (None → all).
        lan_only: advisory flag surfaced in status (binding is enforced elsewhere).
        route_tools: H22.9 — allow-listed READ-ONLY route tools (``route_<name>``)
            exposed alongside the agent tools. ``None``/empty → today's behaviour
            (agent tools only). The caller gates this on the
            ``JARVIS_MCP_ROUTE_TOOLS`` kill-switch.
        mutating_route_tools: H22.9 (mutating scope) — allow-listed MUTATING
            (write) route tools (``route_<name>``, marked ``"mutating": True``).
            ``None``/empty → no write tools. The caller gates these on BOTH the
            ``JARVIS_MCP_ROUTE_TOOLS`` AND ``JARVIS_MCP_MUTATING_TOOLS`` switches
            (see ``build_mutating_route_tools``). Every adapter invocation requires
            a successful durable audit authorization row first.
        """
        self.runner = runner
        self.agents = agents
        self.allowed = set(allowed_agents if allowed_agents is not None else agents.keys())
        self.lan_only = lan_only
        self.agent_request_guard = agent_request_guard
        # Map ``route_<name>`` → RouteTool. Only allow-listed, read-only routes
        # ever land here (the allow-list IS the gate — see route_tools.py).
        self.route_tools: dict[str, RouteTool] = {
            rt.tool_name: rt for rt in (route_tools or [])
        }
        # Map ``route_<name>`` → MutatingRouteTool. Only allow-listed WRITE routes,
        # and only when BOTH kill-switches were on at build time (the caller
        # enforces that via build_mutating_route_tools). Disjoint from read tools.
        self.mutating_route_tools: dict[str, MutatingRouteTool] = {
            rt.tool_name: rt for rt in (mutating_route_tools or [])
        }
        # SEC (review F4): a name in BOTH sets would let the read path (no identity,
        # no audit) shadow the mutating path in call_tool — refuse to build rather
        # than silently bypass the write gate.
        _collision = set(self.route_tools) & set(self.mutating_route_tools)
        if _collision:
            raise ValueError(
                f"route tool name(s) in both read-only and mutating sets: {sorted(_collision)}")

    # ── tools ────────────────────────────────────────────────────────────────

    def _exposed(self) -> list[str]:
        return [a for a in self.agents if a in self.allowed]

    def list_tools(self) -> list[dict]:
        """MCP tool descriptors: one per exposed agent, plus allow-listed routes.

        Route tools are appended only when this server was built with them (the
        ``JARVIS_MCP_ROUTE_TOOLS`` kill-switch is owned by the caller). With the
        switch off, ``self.route_tools`` is empty and the output is unchanged.
        """
        tools = []
        for agent_id in self._exposed():
            tools.append({
                "name": _tool_name(agent_id),
                "description": self.agents.get(agent_id) or f"Ask the {agent_id} agent.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "The request for the agent."}
                    },
                    "required": ["text"],
                },
            })
        for rt in self.route_tools.values():
            tools.append(rt.descriptor())
        # Mutating (write) tools — present only when BOTH kill-switches were on
        # at build time; each descriptor is marked ``"mutating": True``.
        for mt in self.mutating_route_tools.values():
            tools.append(mt.descriptor())
        return tools

    async def call_tool(
        self,
        name: str,
        arguments: Optional[dict] = None,
        identity: object | None = None,
    ) -> dict:
        """Run a tool; return an MCP tool-result ({content, isError}).

        ``identity`` is the caller's presented credential (e.g. ``JARVIS_USER_TOKEN``)
        or a :class:`VerifiedMCPIdentity` produced by the OAuth transport. It is
        threaded into mutating route gates and the agent-request guard. Agent
        conversation remains identity-optional, but any lifecycle mutation
        hidden in an ``ask_*`` request can therefore require verified authority.
        """
        arguments = arguments or {}
        if name.startswith(ROUTE_TOOL_PREFIX):
            return await self._call_route_tool(name, arguments, identity)
        agent_id = name[len("ask_"):] if name.startswith("ask_") else ""
        if not agent_id or agent_id not in self.agents:
            return self._tool_error(f"unknown tool: {name}")
        if agent_id not in self.allowed:
            return self._tool_error(f"agent '{agent_id}' is not exposed over MCP")
        text = arguments.get("text")
        if not isinstance(text, str) or not text.strip():
            return self._tool_error("missing required string argument: text")
        if self.agent_request_guard is not None:
            try:
                refusal = self.agent_request_guard(agent_id, text, identity)
            except Exception:
                return self._tool_error("agent request guard unavailable")
            if refusal:
                return self._tool_error(str(refusal))
        # The marker is scoped to this awaited runner call and cannot be forged by
        # calling Orchestrator.handle_input(channel="mcp") directly. Lifecycle
        # control checks it again immediately before kernel authorization.
        authority_token = _agent_request_authorized.set(
            self.agent_request_guard is not None
        )
        try:
            reply = await self.runner(agent_id, text)
        except Exception as exc:  # never leak a stack trace to an external client
            return self._tool_error(f"agent error: {exc}")
        finally:
            _agent_request_authorized.reset(authority_token)
        return {"content": [{"type": "text", "text": str(reply)}], "isError": False}

    async def _call_route_tool(
        self, name: str, arguments: dict, identity: object | None = None
    ) -> dict:
        """Dispatch an allow-listed route tool IN-PROCESS (read or write).

        The allow-list is the gate: a ``route_<name>`` that is not in
        ``self.route_tools`` (read) or ``self.mutating_route_tools`` (write) is
        refused, so a non-allow-listed route name can never reach a handler. The
        handler is called directly (no loopback HTTP), and its JSON payload is
        returned as text content.

        Read-only tools need no identity. Mutating tools enforce ``identity``
        with the same rule as the HTTP ``user_guard`` (and audit every call,
        including a refusal); an invalid identity is refused without writing.
        """
        rt = self.route_tools.get(name)
        if rt is not None:
            kwargs = rt.filtered_kwargs(arguments)
            try:
                raw = await rt.handler(**kwargs)
                payload = normalize_result(raw)
            except Exception as exc:  # never leak a stack trace to an external client
                return self._tool_error(f"route error: {exc}")
            return {
                "content": [{"type": "text", "text": json.dumps(payload, default=str)}],
                "isError": False,
            }

        mt = self.mutating_route_tools.get(name)
        if mt is not None:
            try:
                # Per-identity gate runs inside call(); audits the refusal too.
                raw = await mt.call(arguments, token=identity)
                payload = normalize_result(raw)
            except MutatingIdentityError as exc:
                # A write refused for want of a valid identity — clear error,
                # no stack trace, no write performed (audited as refused).
                return self._tool_error(f"identity required: {exc}")
            except Exception as exc:  # never leak a stack trace to an external client
                return self._tool_error(f"route error: {exc}")
            return {
                "content": [{"type": "text", "text": json.dumps(payload, default=str)}],
                "isError": False,
            }

        return self._tool_error(f"route '{name}' is not exposed over MCP")

    @staticmethod
    def _tool_error(message: str) -> dict:
        return {"content": [{"type": "text", "text": message}], "isError": True}

    # ── JSON-RPC dispatch ────────────────────────────────────────────────────

    async def handle(self, message: dict, identity: object | None = None) -> Optional[dict]:
        """Dispatch one JSON-RPC 2.0 message; return the response (or None for a notification).

        ``identity`` is the caller's credential, supplied by the transport (the
        HTTP/SSE route in web.py reads the ``X-User-Token``/``X-Admin-Token``
        header; a stdio loop may pass it explicitly). It is forwarded to
        ``call_tool`` and enforced by mutating route tools and any hidden
        lifecycle intent inside an agent request.
        """
        msg_id = message.get("id")
        method = message.get("method", "")
        params = message.get("params") or {}

        if method == "initialize":
            return self._ok(msg_id, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            })
        if method in ("notifications/initialized", "initialized"):
            return None  # notification — no response
        if method == "tools/list":
            return self._ok(msg_id, {"tools": self.list_tools()})
        if method == "tools/call":
            name = params.get("name", "")
            result = await self.call_tool(name, params.get("arguments"), identity=identity)
            return self._ok(msg_id, result)
        if method == "ping":
            return self._ok(msg_id, {})
        return self._err(msg_id, METHOD_NOT_FOUND, f"method not found: {method}")

    @staticmethod
    def _ok(msg_id, result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    @staticmethod
    def _err(msg_id, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}

    # ── stdio transport (H10.5) ──────────────────────────────────────────────

    async def serve_stdio(
        self,
        reader: object | None = None,
        writer: object | None = None,
        *,
        identity: object | None = None,
        max_line_bytes: int = MAX_STDIO_LINE_BYTES,
    ) -> int:
        """Serve newline-delimited JSON-RPC over stdio until EOF; return frames handled.

        ``reader``/``writer`` default to this process's stdin/stdout (see
        ``open_stdio_streams``); tests pass an ``asyncio.StreamReader`` and any
        object with ``write(bytes)`` + ``async drain()``. ``identity`` is the
        transport-level credential handed to every ``tools/call`` — a stdio peer
        is the local user who launched the process, so the caller decides what,
        if anything, that is worth (``None`` = no verified identity: mutating
        route tools refuse, agent lifecycle control refuses).
        """
        if reader is None or writer is None:
            reader, writer = await open_stdio_streams(max_line_bytes=max_line_bytes)

        async def _handle(message: dict) -> Optional[dict]:
            return await self.handle(message, identity=identity)

        return await run_stdio_loop(_handle, reader, writer, max_line_bytes=max_line_bytes)

    # ── introspection ────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "server": SERVER_NAME,
            "version": SERVER_VERSION,
            "protocol": PROTOCOL_VERSION,
            "lan_only": self.lan_only,
            "exposed_agents": self._exposed(),
            "exposed_routes": [rt.spec.name for rt in self.route_tools.values()],
            "exposed_mutating_routes": [
                mt.spec.name for mt in self.mutating_route_tools.values()
            ],
            "tools": [t["name"] for t in self.list_tools()],
            "tool_inventory": self.tool_inventory(),
        }

    def tool_inventory(self) -> list[dict]:
        """Complete state-effect inventory for the exposed MCP tool surface.

        ``direct_route_mutation`` is deliberately narrower than
        ``persistent_state``: agent calls do not invoke a route adapter directly,
        but the production orchestrator persists conversation turns and may
        dispatch separately governed downstream actions.
        """
        inventory = []
        for agent_id in self._exposed():
            controls = ["agent_allowlist", "orchestrator_runner"]
            governed = self.agent_request_guard is not None
            if governed:
                controls.extend([
                    "direct_skill_commands_refused",
                    "local_model_lifecycle_identity_required",
                    "local_model_lifecycle_kernel_grant_only",
                    "local_model_lifecycle_audit_preflight",
                ])
            inventory.append({
                "name": _tool_name(agent_id),
                "tool_class": "agent",
                "persistent_state": True,
                "direct_route_mutation": False,
                "state_effects": [
                    "conversation_user_turn",
                    "conversation_assistant_turn",
                    "possible_downstream_governed_actions",
                    "local_model_lifecycle_when_explicitly_requested",
                ],
                "authority_boundary": (
                    "conversation persistence uses the orchestrator retention boundary; "
                    "local-model lifecycle additionally requires verified MCP owner "
                    "identity, system-control permission, host contract, Action Kernel "
                    "GRANT and durable audit preflight; other downstream actions retain "
                    "their own authority gates"
                ),
                "identity_posture": (
                    "conversation uses MCP transport policy; local-model lifecycle "
                    "requires the per-call owner identity gate"
                ),
                "audit_posture": (
                    "conversation turns have no audit precondition; local-model lifecycle "
                    "requires a durable authorization row before effect"
                ),
                "retention_posture": "conversation transcript retention settings",
                "kernel_posture": (
                    "conversation persistence is outside Action Kernel; local-model "
                    "lifecycle requires enabled/bound host.control GRANT; other downstream "
                    "actions keep action-specific kernel/authority gates"
                ),
                "governance": "governed" if governed else "runner_defined",
                "controls": controls,
            })
        for tool in self.route_tools.values():
            inventory.append({
                "name": tool.tool_name,
                "tool_class": "route",
                "persistent_state": False,
                "direct_route_mutation": False,
                "state_effects": [],
                "authority_boundary": "read-only allow-listed route",
                "identity_posture": f"route guard: {tool.spec.guard}",
                "audit_posture": "no mutation audit",
                "retention_posture": "no state written",
                "kernel_posture": "not applicable to read-only dispatch",
                "governance": "governed",
                "controls": ["read_only_allowlist", "schema_reflection"],
            })
        for tool in self.mutating_route_tools.values():
            controls = [
                "mutating_allowlist",
                "contract_required",
                "identity_required",
                "audit_preflight_required",
                "action_kernel_required",
            ]
            controls.append(
                "identity_policy_bound" if callable(tool.identity_check)
                else "identity_unavailable_fail_closed"
            )
            controls.append(
                "audit_sink_bound" if callable(getattr(tool.auditor, "log", None))
                else "audit_sink_unavailable_fail_closed"
            )
            controls.append(
                "kernel_bound_grant_only" if callable(tool.kernel)
                else "kernel_unavailable_fail_closed"
            )
            inventory.append({
                "name": tool.tool_name,
                "tool_class": "route",
                "persistent_state": True,
                "direct_route_mutation": True,
                "state_effects": ["long_term_memory"],
                "authority_boundary": (
                    "identity, contract, durable audit preflight, and explicit "
                    "Action Kernel GRANT are required before adapter execution"
                ),
                "identity_posture": f"route guard: {tool.spec.guard}; per-tool gate required",
                "audit_posture": "durable authorization row required before mutation",
                "retention_posture": "target-store retention policy",
                "kernel_posture": "enabled, bound, explicit GRANT required",
                "governance": "governed",
                "controls": controls,
            })
        return inventory


# ── stdio transport plumbing ─────────────────────────────────────────────────
#
# Newline-delimited JSON-RPC (the MCP stdio framing): one message — or one
# batch array — per line, no embedded newlines, stdout carries nothing else.
# Logging goes to stderr (the launcher script configures that), so a stray
# log line can never corrupt the protocol stream.

MessageHandler = Callable[[dict], Awaitable[Optional[dict]]]


def _rpc_error(msg_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def encode_stdio_frame(message: object) -> bytes:
    """Serialise one response (or batch) as a single line — never multi-line."""
    return (json.dumps(message, separators=(",", ":"), ensure_ascii=False, default=str) + "\n").encode("utf-8")


async def _write_frame(writer, message: object) -> None:
    writer.write(encode_stdio_frame(message))
    drain = getattr(writer, "drain", None)
    if drain is not None:
        await drain()


async def run_stdio_loop(
    handler: MessageHandler,
    reader,
    writer,
    *,
    max_line_bytes: int = MAX_STDIO_LINE_BYTES,
) -> int:
    """Pump frames from *reader* through *handler* to *writer* until EOF.

    * malformed JSON → ``-32700`` parse error (id ``null``), loop continues;
    * a frame that is neither object nor array → ``-32600`` invalid request;
    * a batch (JSON array) is dispatched item by item and answered as one array
      (or nothing, when every item was a notification);
    * a handler exception → ``-32603`` with the exception *type* only — never a
      stack trace to an external client;
    * an over-long line (beyond the reader limit / *max_line_bytes*) is refused
      with ``-32600`` and the loop ends, because the framing cannot be resynced.

    Returns the number of JSON-RPC messages dispatched to *handler*.
    """
    handled = 0
    while True:
        try:
            raw = await reader.readline()
        except (asyncio.LimitOverrunError, ValueError):
            await _write_frame(writer, _rpc_error(None, INVALID_REQUEST, "frame too long"))
            return handled
        if not raw:
            return handled
        if len(raw) > max_line_bytes:
            await _write_frame(writer, _rpc_error(None, INVALID_REQUEST, "frame too long"))
            return handled
        line = raw.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            await _write_frame(writer, _rpc_error(None, PARSE_ERROR, "parse error"))
            continue
        is_batch = isinstance(parsed, list)
        items = parsed if is_batch else [parsed]
        if is_batch and not items:
            await _write_frame(writer, _rpc_error(None, INVALID_REQUEST, "empty batch"))
            continue
        responses: list[dict] = []
        for item in items:
            if not isinstance(item, dict):
                responses.append(_rpc_error(None, INVALID_REQUEST, "expected a JSON-RPC object"))
                continue
            handled += 1
            try:
                response = await handler(item)
            except Exception as exc:  # never leak a stack trace to an external client
                logger.warning("MCP stdio handler failed (type=%s)", type(exc).__name__)
                response = _rpc_error(item.get("id"), INTERNAL_ERROR, f"internal error: {type(exc).__name__}")
            if response is not None:
                responses.append(response)
        if is_batch:
            if responses:
                await _write_frame(writer, responses)
        else:
            for response in responses:
                await _write_frame(writer, response)


class _ThreadLineReader:
    """``readline()`` off the event loop for a blocking binary stream (Windows console fallback)."""

    def __init__(self, stream) -> None:
        self._stream = stream

    async def readline(self) -> bytes:
        return await asyncio.to_thread(self._stream.readline)


class _BlockingWriter:
    """``write``/``drain`` over a blocking binary stream; ``drain`` flushes off-loop."""

    def __init__(self, stream) -> None:
        self._stream = stream

    def write(self, data: bytes) -> None:
        self._stream.write(data)

    async def drain(self) -> None:
        await asyncio.to_thread(self._stream.flush)


async def open_stdio_streams(
    *, max_line_bytes: int = MAX_STDIO_LINE_BYTES, stdin=None, stdout=None,
) -> tuple[object, object]:
    """Wrap this process's stdin/stdout as an async reader and writer.

    Prefers the event loop's pipe transports (no threads); where the loop cannot
    attach to the handle (Windows console, some launchers) it degrades to a
    thread-backed reader and a blocking writer whose ``drain`` flushes off-loop,
    so the protocol still works — just without loop-native backpressure.
    """
    stdin = sys.stdin.buffer if stdin is None else stdin
    stdout = sys.stdout.buffer if stdout is None else stdout
    loop = asyncio.get_running_loop()
    try:
        reader = asyncio.StreamReader(limit=max_line_bytes)
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, stdin)
        w_transport, w_protocol = await loop.connect_write_pipe(
            asyncio.streams.FlowControlMixin, stdout,
        )
        writer = asyncio.StreamWriter(w_transport, w_protocol, None, loop)
        return reader, writer
    except (NotImplementedError, OSError, ValueError, AttributeError) as exc:
        logger.info("stdio pipe transport unavailable (%s); using thread fallback", type(exc).__name__)
        return _ThreadLineReader(stdin), _BlockingWriter(stdout)
