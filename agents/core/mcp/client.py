"""
client.py — Model Context Protocol (MCP) client.
Connects to MCP servers over the stdio transport and — behind the owner flag
``JARVIS_MCP_HTTP_CLIENT`` (default off) — over Streamable HTTP
(``agents/core/mcp/http_transport.py``, DRA-25). The deprecated HTTP+SSE
transport pair is NOT implemented and never will be: the spec replaced it with
Streamable HTTP. The tool-call contract below admits ``stdio`` always and
``streamable-http`` only while the flag is set, so a config persisted while the
flag was on cannot keep calling out after the owner unsets it.

Stdio subprocess environment (Hermes parity, governed): with
``JARVIS_MCP_STDIO_ENV_BASELINE`` set, a spawned MCP server inherits only an
allow-listed baseline (PATH/HOME/locale/temp/platform plumbing) plus the
per-server ``env`` overrides — never the hub's API keys and tokens. Default
off (the historical full-inherit behaviour) because a server that relied on
inheriting a credential would otherwise break silently.
"""

import asyncio
import json
import logging
import os
import re
import shlex
from collections.abc import Callable
from typing import Any

from agents.core.automation_contracts import (
    ContractTemplate,
    contract_denial,
    field_present,
    one_of,
    predicate,
)
from agents.core.env_config import env_flag
from agents.core.mcp.http_transport import (
    HTTP_CLIENT_FLAG,
    SUPPORTED_TRANSPORTS,
    TRANSPORT_STDIO,
    TRANSPORT_STREAMABLE_HTTP,
    MCPTransportError,
    StreamableHttpTransport,
    http_client_enabled,
    normalize_transport,
    transport_allowed,
    validate_mcp_url,
)

logger = logging.getLogger("jarvis.mcp")

_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.:/@\-]{1,200}$")
_SHELL_METACHARS = frozenset(";&|<>`\n\r")

#: Owner flag: spawn stdio MCP servers with the allow-listed env baseline only.
STDIO_ENV_BASELINE_FLAG = "JARVIS_MCP_STDIO_ENV_BASELINE"

#: Variables a stdio MCP subprocess may inherit under the baseline: process
#: plumbing (path, home, locale, temp, terminal), platform essentials
#: (Windows system dirs, XDG dirs, display/session buses), interpreter and
#: toolchain roots, and TLS trust roots. Deliberately absent: proxies (may embed
#: credentials), every ``JARVIS_*`` / ``NERVA_*`` setting, and any provider key.
STDIO_ENV_ALLOWLIST = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "TERM", "TZ",
    "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "LC_MESSAGES",
    "TMPDIR", "TEMP", "TMP",
    "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT",
    "APPDATA", "LOCALAPPDATA", "USERPROFILE", "PROGRAMDATA", "PROGRAMFILES",
    "PROGRAMFILES(X86)", "HOMEDRIVE", "HOMEPATH",
    "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR",
    "DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS",
    "PYTHONIOENCODING", "PYTHONUTF8", "VIRTUAL_ENV", "CONDA_PREFIX",
    "NODE_PATH", "NVM_DIR", "NVM_BIN", "JAVA_HOME", "GOPATH", "CARGO_HOME",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS",
})
_SECRET_LIKE = re.compile(
    r"(TOKEN|SECRET|PASSW|PASSWD|CREDENTIAL|API_?KEY|PRIVATE_?KEY|AUTH)", re.IGNORECASE
)


def stdio_env_baseline_enabled() -> bool:
    return env_flag(STDIO_ENV_BASELINE_FLAG)


def stdio_env_baseline(
    environ: dict | None = None, overrides: dict | None = None,
) -> dict[str, str]:
    """Allow-listed environment for a stdio MCP subprocess plus explicit *overrides*.

    Names are matched case-insensitively (Windows env is case-insensitive) but
    passed through with their original spelling. A name on the allow-list that
    nevertheless looks like a credential is still dropped — belt and braces
    against an odd platform variable. Explicit per-server overrides always win:
    they are the operator's deliberate hand-off (e.g. a shared secret).
    """
    source = os.environ if environ is None else environ
    baseline: dict[str, str] = {}
    for key, value in source.items():
        name = str(key)
        if name.upper() not in STDIO_ENV_ALLOWLIST or _SECRET_LIKE.search(name):
            continue
        baseline[name] = str(value)
    for key, value in dict(overrides or {}).items():
        baseline[str(key)] = str(value)
    return baseline


def _safe_name(value: Any) -> bool:
    return bool(_SAFE_NAME.match(str(value or "")))


def _tool_call_names_safe(view, now) -> bool:
    return _safe_name(view.get("server")) and _safe_name(view.get("tool"))


def _args_keys_safe(view, now) -> bool:
    keys = view.get("args_keys")
    if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
        return False
    return (
        keys == sorted(keys)
        and all(_safe_name(k) for k in keys)
    )


def _transport_armed(view, now) -> bool:
    # stdio always; streamable-http only while the owner flag is set. Evaluated
    # per call, so unsetting the flag revokes a persisted HTTP server at once.
    return transport_allowed(view.get("transport"))


def _mcp_tool_call_contract_template() -> ContractTemplate:
    """The historical, stdio-only gate — what every call sees with the flag off."""
    return ContractTemplate(
        kind="mcp.tool_call",
        description="Outbound MCP client tool-call gate.",
        constraints=(
            field_present("server", "tool", "transport"),
            one_of("transport", {"stdio"}),
            predicate("tool_call_names_safe", _tool_call_names_safe, reason="invalid_name"),
            predicate("args_keys_safe", _args_keys_safe, reason="bad_args_keys"),
        ),
    )


def _mcp_tool_call_contract_template_http() -> ContractTemplate:
    """The widened gate: stdio + streamable-http, selected only while the flag is set."""
    return ContractTemplate(
        kind="mcp.tool_call",
        description="Outbound MCP client tool-call gate (stdio + streamable-http).",
        constraints=(
            field_present("server", "tool", "transport"),
            one_of("transport", set(SUPPORTED_TRANSPORTS)),
            predicate("transport_armed", _transport_armed, reason="transport_disabled"),
            predicate("tool_call_names_safe", _tool_call_names_safe, reason="invalid_name"),
            predicate("args_keys_safe", _args_keys_safe, reason="bad_args_keys"),
        ),
    )


MCP_TOOL_CALL_CONTRACT = _mcp_tool_call_contract_template()
MCP_TOOL_CALL_CONTRACT_HTTP = _mcp_tool_call_contract_template_http()


def active_tool_call_contract() -> ContractTemplate:
    """Contract for *this* call: byte-identical to the stdio-only gate unless
    ``JARVIS_MCP_HTTP_CLIENT`` is set right now (re-read per call, never cached)."""
    return MCP_TOOL_CALL_CONTRACT_HTTP if http_client_enabled() else MCP_TOOL_CALL_CONTRACT


class MCPTool:
    def __init__(self, name: str, description: str, input_schema: dict, server: str):
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.server = server


class MCPServer:
    def __init__(
        self,
        name: str,
        transport: str = "stdio",
        command: str = None,
        url: str = None,
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        http_transport_factory: Callable[..., StreamableHttpTransport] | None = None,
    ):
        """
        ``transport`` is normalised (``"HTTP"`` → ``streamable-http``); an unknown
        spelling is kept verbatim so ``connect()``/the contract refuse it by name.
        ``headers`` (HTTP only, e.g. a bearer token) live in memory — ``to_config``
        never persists them. ``http_transport_factory(url, headers, name=)`` is the
        test seam for the Streamable HTTP transport.
        """
        self.name = name
        self.transport = normalize_transport(transport)
        self.command = command
        self.url = url
        self.cwd = cwd
        self.env = dict(env or {})
        self.headers = dict(headers or {})
        self.tools: list[MCPTool] = []
        self._proc = None
        self._http: StreamableHttpTransport | None = None
        self._http_factory = http_transport_factory or StreamableHttpTransport
        #: Stable reason for the last refused/failed ``connect()`` (None = fine).
        self.last_error: str | None = None
        # Serialize stdio round-trips and match responses by JSON-RPC id so
        # concurrent (or previously timed-out) calls can't read each other's
        # replies off the shared pipe.
        self._io_lock = asyncio.Lock()
        self._next_id = 0

    async def connect(self):
        self.last_error = None
        if self.transport == TRANSPORT_STREAMABLE_HTTP:
            return await self._connect_http()
        if self.transport == TRANSPORT_STDIO and self.command:
            argv = self._command_argv()
            if not argv:
                logger.warning("MCP stdio command rejected as unsafe: %s", self.name)
                self.last_error = "unsafe_command"
                return False
            # Terminate any prior process first, or a server that connects but
            # registers no tools gets a fresh subprocess spawned (and the old one
            # orphaned) on every reconnect attempt.
            if self._proc is not None:
                await self.close()
            self._proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.cwd or None,
                env=self._merged_env(),
            )
            await self._initialize()
            logger.info(f"MCP server connected: {self.name} ({len(self.tools)} tools)")
            # No tools registered → the handshake failed; report failure so the
            # caller stops treating a dead server as available.
            if not self.tools:
                self.last_error = "handshake_failed"
            return bool(self.tools)
        elif self.transport != TRANSPORT_STDIO:
            # Anything that is not stdio or streamable-http (e.g. the deprecated
            # "sse" pair) is refused by name, loudly, rather than as a quiet False
            # that reads like a connection failure.
            logger.warning(
                "MCP transport %r is not implemented; server %s stays disconnected",
                self.transport, self.name,
            )
            self.last_error = f"unsupported_transport:{self.transport}"
        else:
            self.last_error = "missing_command"
        return False

    async def _connect_http(self) -> bool:
        """Streamable HTTP handshake — owner-flag gated, SSRF-guarded, no tools → False."""
        if not http_client_enabled():
            logger.warning(
                "MCP server %s uses streamable-http but %s is not set; staying disconnected",
                self.name, HTTP_CLIENT_FLAG,
            )
            self.last_error = f"transport_disabled:{HTTP_CLIENT_FLAG}"
            return False
        reason = validate_mcp_url(self.url)
        if reason:
            self.last_error = reason
            return False
        if self._http is not None:
            await self.close()
        self.tools = []
        try:
            self._http = self._http_factory(self.url, self.headers, name=self.name)
            result = await self._http.initialize()
            if result:
                await self._list_tools()
        except MCPTransportError as exc:
            logger.warning("MCP HTTP connect refused (%s): %s", self.name, exc.reason)
            self.last_error = exc.reason
            self._http = None
            return False
        if not self.tools:
            self.last_error = "handshake_failed"
            return False
        logger.info(f"MCP server connected: {self.name} ({len(self.tools)} tools, streamable-http)")
        return True

    def is_connected(self) -> bool:
        """Transport-aware liveness (the admin list used to read ``_proc`` directly)."""
        if self.transport == TRANSPORT_STREAMABLE_HTTP:
            return self._http is not None and self._http.initialized and bool(self.tools)
        return self._proc is not None and self._proc.returncode is None

    def _command_argv(self) -> list[str] | None:
        command = (self.command or "").strip()
        if not command or any(ch in command for ch in _SHELL_METACHARS):
            return None
        try:
            argv = shlex.split(command)
        except ValueError:
            return None
        if not argv or any("\x00" in part for part in argv):
            return None
        return argv

    def _merged_env(self) -> dict[str, str] | None:
        """Environment for the stdio subprocess.

        Baseline flag on → allow-listed baseline + per-server overrides only.
        Flag off (default) → historical behaviour: inherit everything (``None``)
        or the full parent env plus overrides.
        """
        if stdio_env_baseline_enabled():
            return stdio_env_baseline(None, self.env)
        if not self.env:
            return None
        merged = os.environ.copy()
        merged.update({str(k): str(v) for k, v in self.env.items()})
        return merged

    async def _initialize(self):
        resp = await self._send({"jsonrpc": "2.0", "method": "initialize", "params": {}, "id": 1})
        if resp:
            await self._list_tools()

    async def _list_tools(self):
        resp = await self._send({"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": 2})
        if resp and "result" in resp:
            for t in resp["result"].get("tools", []):
                self.tools.append(MCPTool(
                    name=t.get("name", "unknown"),
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {}),
                    server=self.name,
                ))

    async def call_tool(self, name: str, arguments: dict = None) -> Any:
        arguments = arguments or {}
        if not isinstance(arguments, dict):
            return {"error": "bad_args", "tool": name, "server": self.name}
        blocked = self._tool_call_blocked(name, arguments)
        if blocked is not None:
            return blocked
        resp = await self._send({
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
            "id": 3,
        })
        if resp and "result" in resp:
            return resp["result"]
        return resp

    def _tool_call_blocked(self, name: str, arguments: dict) -> dict | None:
        arg_keys = list(arguments.keys())
        if all(isinstance(k, str) for k in arg_keys):
            arg_keys = sorted(arg_keys)
        payload = {
            "kind": "mcp.tool_call",
            "server": self.name,
            "tool": name,
            "transport": self.transport,
            "args_keys": arg_keys,
        }
        try:
            decision = active_tool_call_contract().evaluate(payload)
        except Exception:
            logger.warning("MCP tool-call contract evaluation failed", exc_info=True)
            return {"error": "contract_error", "tool": name, "server": self.name}
        reason = contract_denial(decision)
        if reason:
            return {"error": reason, "tool": name, "server": self.name}
        return None

    async def _send(self, msg: dict) -> dict:
        if self.transport == TRANSPORT_STREAMABLE_HTTP:
            if self._http is None:
                logger.warning(f"MCP server {self.name} not connected")
                return {}
            try:
                return await self._http.request(msg.get("method", ""), msg.get("params") or {})
            except MCPTransportError as exc:
                logger.warning("MCP HTTP call refused (%s): %s", self.name, exc.reason)
                return {"error": {"code": -32000, "message": exc.reason}}
        if not self._proc or self._proc.stdin.is_closing():
            logger.warning(f"MCP server {self.name} not connected")
            return {}
        async with self._io_lock:
            try:
                self._next_id += 1
                req_id = self._next_id
                line = json.dumps({**msg, "id": req_id}) + "\n"
                self._proc.stdin.write(line.encode())
                await self._proc.stdin.drain()
                loop = asyncio.get_running_loop()
                deadline = loop.time() + 10.0
                # Read until the reply whose id matches ours, skipping
                # notifications and any stale reply from a timed-out call.
                # Bounded so a peer echoing a fixed id can't spin forever.
                for _ in range(32):
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        return {}
                    raw = await asyncio.wait_for(
                        self._proc.stdout.readline(), timeout=remaining
                    )
                    if not raw:
                        return {}
                    try:
                        resp = json.loads(raw.decode())
                    except json.JSONDecodeError:
                        continue
                    if isinstance(resp, dict) and resp.get("id") == req_id:
                        return resp
                return {}
            except Exception as e:
                logger.warning(f"MCP error ({self.name}): {e}")
                return {}

    async def close(self):
        if self._proc:
            self._proc.terminate()
            await self._proc.wait()
            logger.info(f"MCP server closed: {self.name}")
        if self._http is not None:
            http, self._http = self._http, None
            await http.close()
            logger.info(f"MCP server closed: {self.name}")


class MCPManager:
    def __init__(self):
        self.servers: dict[str, MCPServer] = {}

    def register(self, server: MCPServer):
        self.servers[server.name] = server

    async def connect_all(self):
        for srv in self.servers.values():
            try:
                await srv.connect()
            except Exception as e:
                logger.warning(f"MCP connect failed ({srv.name}): {e}")

    def get_tools(self) -> list[MCPTool]:
        tools = []
        for srv in self.servers.values():
            tools.extend(srv.tools)
        return tools

    def find_tool(self, name: str) -> MCPTool:
        for srv in self.servers.values():
            for t in srv.tools:
                if t.name == name:
                    return t
        return None

    async def call_tool(self, name: str, arguments: dict = None) -> Any:
        for srv in self.servers.values():
            for t in srv.tools:
                if t.name == name:
                    return await srv.call_tool(name, arguments)
        return {"error": f"Tool '{name}' not found"}

    async def close_all(self):
        for srv in self.servers.values():
            await srv.close()

    def to_config(self) -> list[dict]:
        """Export all servers to config format for persistence."""
        return [
            {
                "name": srv.name,
                "transport": srv.transport,
                "command": srv.command,
                "url": srv.url,
                "cwd": srv.cwd,
            }
            for srv in self.servers.values()
        ]

    def load_from_config(self, configs: list[dict]):
        """Load servers from config list."""
        self.servers.clear()
        for cfg in configs:
            headers = cfg.get("headers")
            srv = MCPServer(
                name=cfg["name"],
                transport=cfg.get("transport", "stdio"),
                command=cfg.get("command"),
                url=cfg.get("url"),
                cwd=cfg.get("cwd"),
                headers=headers if isinstance(headers, dict) else None,
            )
            self.servers[srv.name] = srv
