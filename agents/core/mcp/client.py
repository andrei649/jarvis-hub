"""
client.py — Model Context Protocol (MCP) client.
Connects to MCP servers over the stdio transport and — behind the owner flag
``JARVIS_MCP_HTTP_CLIENT`` (default off) — over Streamable HTTP
(``agents/core/mcp/http_transport.py``, DRA-25). The deprecated HTTP+SSE
transport pair is NOT implemented and never will be: the spec replaced it with
Streamable HTTP. The tool-call contract below admits ``stdio`` always and
``streamable-http`` only while the flag is set, so a config persisted while the
flag was on cannot keep calling out after the owner unsets it.

Stdio subprocess environment (Hermes parity, governed): a spawned MCP server is
*handed* only an allow-listed baseline (PATH/HOME/locale/temp/platform plumbing)
plus the per-server ``env`` overrides — it is not handed the hub's API keys and
tokens. **Default on** (H502): a third-party binary the owner attached is not a
reason to hand it every provider credential on the box.

**Scope of the guarantee — read this before calling it containment.** The child
runs as the *same UID* as the hub, in no namespace and no sandbox, so a hostile
server recovers the withheld keys by two routes, not one:

* the parent's whole environment out of ``/proc/<ppid>/environ`` on Linux;
* the **filesystem**, which this module does not narrow at all. ``cwd`` defaults to
  the hub's own working directory, so ``open(".env")`` in the child reaches the very
  file most of those keys were read from (``plugin_manager.build`` loads
  ``<repo>/.env`` and ``<user home>/.env``). Withholding a variable does not take
  away read access to the file that set it, and nothing here claims it does —
  :func:`cwd_secret_files` exists so the owner is told when the two are the same
  directory, rather than inferring a protection from the withheld count alone.

So: this baseline is **defence in depth, not a security boundary**. It
is a real fix for a careless or over-broad third-party server, for a server that
echoes its environment into logs, and for leakage into crash reports — it is not a
defence against a backdoor wearing an MCP costume. That boundary needs the
still-unshipped command screener plus real process isolation (separate UID,
namespace or container), which is the only thing that closes the filesystem route
as well as the ``/proc`` one.

The drop is announced once per connect at INFO as a COUNT, so a server that breaks
because it relied on an inherited credential is diagnosable. The owner's narrow
remedy is ``JARVIS_MCP_STDIO_ALLOWED_ENV`` (see :func:`stdio_env_extra_allowed`):
a comma-separated list of host variable names stdio MCP servers may keep
inheriting. The per-server ``env`` block also wins over the baseline, but it has no
owner-facing configuration surface today — it is settable only in-process and is
not persisted (see :meth:`MCPManager.to_config`), so only in-process callers can supply it. ``JARVIS_MCP_STDIO_ENV_BASELINE=0`` is the
blunt escape hatch back to the historical full-inherit behaviour, for every server
on the box at once.
"""

import asyncio
import fnmatch
import json
import logging
import os
import re
import shlex
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

from agents.core.automation_contracts import (
    ContractTemplate,
    contract_denial,
    field_present,
    one_of,
    predicate,
)
from agents.core.env_alias import canonical
from agents.core.env_config import env_flag, env_list, resolve_spellings
from agents.core.mcp.host_requests import (
    ElicitationConfig,
    MCPHost,
    SamplingConfig,
)
from agents.core.mcp.http_transport import (
    CLIENT_INFO,
    CLIENT_PROTOCOL_VERSION,
    HTTP_CLIENT_FLAG,
    MAX_CONTENT_REPLY_BYTES,
    SUPPORTED_TRANSPORTS,
    TRANSPORT_STDIO,
    TRANSPORT_STREAMABLE_HTTP,
    MCPTransportError,
    MCPUnauthorized,
    StreamableHttpTransport,
    http_client_enabled,
    normalize_transport,
    transport_allowed,
    validate_mcp_url,
)
from agents.core.mcp.resilience import ReconnectPolicy, ServerHealth, halted
from agents.core.mcp.resources import (
    UTILITY_OPS,
    ResourceError,
    bound_tool_result,
    cache_result_blocks,
    run_utility,
    utility_ops_for,
    warm_cleaner,
)
from agents.core.mcp.schema_normalize import (
    PROVIDER_NAME_PREFIX,
    mcp_provider_name,
    normalize_mcp_input_schema,
)

logger = logging.getLogger("jarvis.mcp")

_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.:/@\-]{1,200}$")
_SHELL_METACHARS = frozenset(";&|<>`\n\r")

#: Owner flag: spawn stdio MCP servers with the allow-listed env baseline only.
#: Default ON — set it to ``0`` to go back to full inheritance.
STDIO_ENV_BASELINE_FLAG = "JARVIS_MCP_STDIO_ENV_BASELINE"

#: Owner flag: a comma-separated list of host variable NAMES stdio MCP servers may keep
#: inheriting on top of :data:`STDIO_ENV_ALLOWLIST`. This is the *narrow* remedy for a
#: server that legitimately needs one hub credential after the H502 default flip — the
#: alternative, ``JARVIS_MCP_STDIO_ENV_BASELINE=0``, surrenders the whole environment to
#: every stdio server at once. Host-wide, not per-server: a name listed here reaches
#: every stdio MCP server the hub spawns, so list the minimum.
STDIO_ENV_ALLOW_FLAG = "JARVIS_MCP_STDIO_ALLOWED_ENV"

#: Trust tiers (Hermes absorption 4b). A server is *read-only* unless the owner says
#: otherwise: only a tool whose ``annotations.readOnlyHint`` is true may be called on it;
#: an unannotated, unlisted or mutating tool is refused by name before any request leaves.
#: ``full`` lets every tool through to the contract and kernel checks that already govern
#: it. The hint is the server's own claim, so it can only ever *narrow* what a tier allows.
TRUST_READ_ONLY = "read-only"
TRUST_FULL = "full"
TRUST_TIERS: tuple[str, ...] = (TRUST_READ_ONLY, TRUST_FULL)
_TRUST_ALIASES = {
    "read-only": TRUST_READ_ONLY, "readonly": TRUST_READ_ONLY, "read_only": TRUST_READ_ONLY,
    "ro": TRUST_READ_ONLY,
    "full": TRUST_FULL, "read-write": TRUST_FULL, "rw": TRUST_FULL,
}


def normalize_trust(raw: object) -> str | None:
    """Canonical trust tier for *raw*, or None when it names no tier."""
    return _TRUST_ALIASES.get(str(raw or "").strip().lower())


MAX_TOOL_PATTERNS = 64
MAX_TOOL_PATTERN_CHARS = 128


def _clean_tool_patterns(raw: object) -> list[str] | None:
    """A bounded list of non-empty string patterns; None stays None (no filter); anything
    else that is not a list narrows to nothing rather than to everything."""
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)):
        return []
    out = [
        item.strip() for item in raw
        if isinstance(item, str) and item.strip() and len(item) <= MAX_TOOL_PATTERN_CHARS
    ]
    return out[:MAX_TOOL_PATTERNS]


def tool_patterns_over_bounds(raw: object) -> int:
    """How many usable patterns in *raw* the bounds would drop (0 when it fits).

    A pattern past :data:`MAX_TOOL_PATTERN_CHARS` and every one past the
    :data:`MAX_TOOL_PATTERNS`-th counts; a non-list counts as one, since it cannot
    be kept at all. Blank and non-string entries are malformed, not over the
    bounds, and are not counted (they are dropped as before). The add route refuses
    any count above zero; :class:`MCPServer` uses it on the deny side, where a
    dropped pattern would make the tool it named visible again.
    """
    if raw is None:
        return 0
    if not isinstance(raw, (list, tuple)):
        return 1
    usable = [item for item in raw if isinstance(item, str) and item.strip()]
    too_long = sum(1 for item in usable if len(item) > MAX_TOOL_PATTERN_CHARS)
    return too_long + max(0, len(usable) - too_long - MAX_TOOL_PATTERNS)

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
    """The default since H502: an MCP server the owner attached is a third-party
    binary, and handing it ``os.environ`` handed it every provider key on the box.

    Two escape hatches, deliberately unequal. ``JARVIS_MCP_STDIO_ALLOWED_ENV`` names
    the individual host variables that may keep flowing and is the one to reach for.
    ``JARVIS_MCP_STDIO_ENV_BASELINE=0`` turns the baseline off for every stdio server
    at once and is the blunt last resort. (The per-server ``env`` block also wins over
    the baseline, but it is in-process only — it has no admin-API or config surface,
    so it is not a remedy an owner can reach.)
    """
    return env_flag(STDIO_ENV_BASELINE_FLAG, True)


#: Sentinel: "no explicit value given", distinct from an explicit ``None``/empty flag.
_NO_RAW = object()


def stdio_env_extra_allowed(raw: object = _NO_RAW) -> frozenset[str]:
    """Upper-cased host variable names the owner named in ``JARVIS_MCP_STDIO_ALLOWED_ENV``.

    With no argument the hub's own environment is read through
    :func:`agents.core.env_config.env_list` (the sanctioned accessor — AUD-14 caps raw
    ``os.environ`` reads). *raw* is the flag's value read out of some other environment
    mapping, which is how :func:`stdio_env_baseline` keeps the owner's declaration and
    the values it governs in one place. Empty, unset or whitespace-only → the empty set,
    i.e. the allow-list alone.
    """
    parts = env_list(STDIO_ENV_ALLOW_FLAG) if raw is _NO_RAW else str(raw or "").split(",")
    # RB-2: a hub variable the owner names as NERVA_<X> is the JARVIS_<X> the hub's
    # environment holds, so the child receives exactly what the old spelling passes.
    return frozenset(canonical(part.strip().upper()) for part in parts if part.strip())


#: Config files that hold exactly what the env baseline withholds. ``plugin_manager.build``
#: reads the hub's provider keys out of ``<repo>/.env`` and ``<user home>/.env``, and a stdio
#: child with no ``cwd`` of its own inherits the hub's — so the same keys are one ``open()``
#: away from a server that was carefully not handed them.
_CWD_SECRET_FILES = (".env", ".env.local")


def cwd_secret_files(cwd: "str | None" = None) -> list[str]:
    """Credential files a stdio child could read straight out of its working directory.

    Not a check that can fail closed, and it is not offered as one: refusing to spawn a
    server because a ``.env`` sits in the directory would break every dev checkout, and
    pointing the child somewhere else would break every server that resolves a relative
    path. The module's whole posture here is to *withhold and say so* (see the connect-time
    count in :meth:`MCPServer._merged_env`), and the count on its own reads as more
    protection than there is while the file the values came from is still readable. This
    makes that visible, in the same breath, once per connect.

    *cwd* is the server's configured working directory; ``None`` means it inherits the
    hub's, which is the default and the case that matters. Unreadable and missing files are
    both "not there" — the point is what the child can open, not what exists.
    """
    root = Path(cwd) if cwd else Path.cwd()
    found = []
    for name in _CWD_SECRET_FILES:
        candidate = root / name
        try:
            if candidate.is_file() and os.access(candidate, os.R_OK):
                found.append(name)
        except OSError:
            continue
    return found


def stdio_env_baseline(
    environ: dict | None = None, overrides: dict | None = None,
) -> dict[str, str]:
    """Allow-listed environment for a stdio MCP subprocess plus explicit *overrides*.

    Names are matched case-insensitively (Windows env is case-insensitive) but
    passed through with their original spelling. A name on the allow-list that
    nevertheless looks like a credential is still dropped — belt and braces
    against an odd platform variable. Explicit per-server overrides always win:
    they are the operator's deliberate hand-off (e.g. a shared secret).

    A name the owner listed in ``JARVIS_MCP_STDIO_ALLOWED_ENV`` (read from *environ*
    itself, so the declaration and the values always come from one environment) is
    passed through even when it looks like a credential: naming a credential the
    server needs is the entire point of that flag, and it is how an owner recovers
    from the H502 default flip without reaching for the global off switch.
    """
    source = os.environ if environ is None else environ
    extra_allowed = (
        stdio_env_extra_allowed()
        if environ is None
        else stdio_env_extra_allowed(resolve_spellings(source, STDIO_ENV_ALLOW_FLAG)[0])
    )
    baseline: dict[str, str] = {}
    for key, value in source.items():
        name = str(key)
        upper = name.upper()
        if canonical(upper) in extra_allowed:
            # under the name the hub reads (RB-2), whichever spelling this mapping holds
            baseline[name if canonical(upper) == upper else canonical(upper)] = str(value)
            continue
        if upper not in STDIO_ENV_ALLOWLIST or _SECRET_LIKE.search(name):
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


def _is_server_request(msg: dict) -> bool:
    """A JSON-RPC request *from* the server: a method and an id, no result or error."""
    return ("method" in msg and "id" in msg and msg.get("id") is not None
            and "result" not in msg and "error" not in msg)


def _permanent_refusal(reason: str | None) -> bool:
    """A connect refusal no retry can fix: the configuration itself is refused."""
    text = str(reason or "")
    return text in {"unsafe_command", "missing_command", "oauth_required", "secret_missing",
                    "token_origin_mismatch"} or text.startswith(
        ("unsupported_transport", "transport_disabled"))


#: H552 — the longest JSON-RPC line read off a stdio server: a 50 MiB resource as base64
#: plus its envelope. asyncio's default (64 KiB) failed every larger reply and left the
#: rest of the line in the pipe. Memory per read stays bounded by this limit; a longer
#: line drops the connection (it cannot be resynchronised) and the supervisor reconnects.
STDIO_LINE_LIMIT = 72 * 1024 * 1024
#: The reader's limit while no request is in flight (and so at most about twice this is
#: buffered from an idle server: asyncio pauses the pipe there), and for ordinary
#: requests. Only a content read (resources/read, prompts/get) raises it to
#: STDIO_LINE_LIMIT, and at most CONTENT_READS_AT_ONCE of those run at once, hub-wide.
STDIO_IDLE_LINE_LIMIT = 1024 * 1024
STDIO_CALL_LINE_LIMIT = 16 * 1024 * 1024
CONTENT_READS_AT_ONCE = 2
#: A reply line longer than this is parsed on a worker thread.
_THREAD_PARSE_BYTES = 1024 * 1024
_CONTENT_GATES: dict[int, asyncio.Semaphore] = {}


def _content_gate() -> asyncio.Semaphore:
    """The hub-wide bound on concurrent large content reads (one per event loop)."""
    loop = asyncio.get_running_loop()
    gate = _CONTENT_GATES.get(id(loop))
    if gate is None:
        _CONTENT_GATES.clear()
        gate = _CONTENT_GATES[id(loop)] = asyncio.Semaphore(CONTENT_READS_AT_ONCE)
    return gate


def _set_line_limit(reader: Any, limit: int) -> None:
    if reader is not None and hasattr(reader, "_limit"):
        reader._limit = int(limit)
#: H552 — the content reads whose replies may be large on Streamable HTTP too.
_CONTENT_METHODS = frozenset({"resources/read", "prompts/get"})
#: H553 — server requests (sampling, elicitation) answered per client call; more are refused.
MAX_HOST_REQUESTS_PER_CALL = 2

#: H556 — parallel connects at once, and the supervisor's cadence.
CONNECT_CONCURRENCY = 4
SUPERVISOR_INTERVAL = 5.0
KEEPALIVE_INTERVAL = 60.0


class MCPTool:
    def __init__(
        self,
        name: str,
        description: str,
        input_schema: dict,
        server: str,
        annotations: dict | None = None,
        *,
        utility: bool = False,
    ):
        self.name = name
        #: H552 — one of the four resource/prompt tools this client adds, not the server's own.
        self.utility = bool(utility)
        self.description = description
        #: What the server sent, kept for diagnostics only — never offered to a model.
        self.raw_input_schema = input_schema
        #: The provider-agnostic repair (H557): applied here, at registration, so every
        #: dialect serializer downstream ships the same safe schema.
        self.input_schema = normalize_mcp_input_schema(input_schema)
        self.server = server
        #: The server's own claims about the tool (``readOnlyHint``, ``destructiveHint``, …).
        self.annotations: dict = dict(annotations) if isinstance(annotations, dict) else {}

    @property
    def read_only(self) -> bool:
        """True only when the server declared ``readOnlyHint: true`` — never assumed."""
        return self.annotations.get("readOnlyHint") is True

    @property
    def qualified_name(self) -> str:
        """``server/tool`` — the name that stays unambiguous across servers."""
        return f"{self.server}/{self.name}"

    @property
    def provider_name(self) -> str:
        """``mcp__<server>__<tool>`` — the model-facing function name, legal for every
        provider and outside the built-in tool namespace. :meth:`MCPManager.model_tools`
        disambiguates the rare pairs that sanitize to the same text."""
        return mcp_provider_name(self.server, self.name)


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
        trust: str = TRUST_READ_ONLY,
        tools_allow: list[str] | None = None,
        tools_deny: list[str] | None = None,
        sampling: object = None,
        elicitation: object = None,
        auth: str | None = None,
        secret_env: list[str] | None = None,
        secret_headers: dict[str, str] | None = None,
        oauth: dict | None = None,
        origin: dict | None = None,
    ):
        """
        ``transport`` is normalised (``"HTTP"`` → ``streamable-http``); an unknown
        spelling is kept verbatim so ``connect()``/the contract refuse it by name.
        ``headers`` (HTTP only, e.g. a bearer token) live in memory — ``to_config``
        never persists them. ``http_transport_factory(url, headers, name=)`` is the
        test seam for the Streamable HTTP transport. ``trust`` is the owner's tier for
        this server (:data:`TRUST_TIERS`; default read-only, fail closed).
        """
        normalized_trust = normalize_trust(trust)
        if normalized_trust is None:
            raise ValueError(f"unknown MCP trust tier: {trust!r}")
        self.trust = normalized_trust
        # Hermes absorption 4c — attaching a server is not attaching every one of its
        # tools: glob patterns on the tool name; ``tools_allow`` None = all, a deny always
        # wins. Applied at tools/list (hidden tools are never offered) and again at call
        # time, so a name the model or a caller remembers cannot go around the filter.
        self.tools_allow: list[str] | None = _clean_tool_patterns(tools_allow)
        self.tools_deny: list[str] = _clean_tool_patterns(tools_deny) or []
        # Capping a deny list widens it: a dropped deny makes its tool visible again.
        # So a deny that does not fit the bounds narrows the server to nothing, the
        # module's rule for a filter it cannot honour (a malformed allow does the same).
        # The add route refuses such a filter outright; this covers a hand-edited config.
        dropped = tool_patterns_over_bounds(tools_deny)
        if dropped:
            self.tools_allow = []
            logger.warning(
                "MCP server %s: tools_deny does not fit the bounds (%d pattern(s) over %d "
                "chars or past %d entries); every tool is hidden until the filter is fixed",
                name, dropped, MAX_TOOL_PATTERN_CHARS, MAX_TOOL_PATTERNS,
            )
        self.name = name
        self.transport = normalize_transport(transport)
        self.command = command
        self.url = url
        self.cwd = cwd
        self.env = dict(env or {})
        self.headers = dict(headers or {})
        #: G9 — how this server authenticates (``none`` / ``oauth`` / ``api_key``), the names
        #: of its secrets in the encrypted store (``mcp.secret.<server>.<NAME>``: values are
        #: read at spawn/connect, never kept in the config), header templates filled from
        #: them (``Bearer ${NAME}``), OAuth client pins, and where it was installed from.
        self.auth = str(auth or "none")
        self.secret_env = [str(n) for n in (secret_env or []) if isinstance(n, str)]
        self.secret_headers = {str(k): str(v) for k, v in dict(secret_headers or {}).items()}
        self.oauth = dict(oauth or {})
        self.origin = dict(origin or {})
        self.tools: list[MCPTool] = []
        #: H552 — list_resources / read_resource / list_prompts / get_prompt, offered only
        #: for the capabilities the server declared on ``initialize``.
        self.utility_tools: list[MCPTool] = []
        #: What the server declared on ``initialize`` (``resources``, ``prompts`` …).
        self.server_capabilities: dict = {}
        #: H553 — the owner's settings for requests the server sends back to Nerva.
        self.sampling = SamplingConfig.from_config(sampling)
        self.elicitation = ElicitationConfig.from_config(elicitation)
        #: Host services (approval queue, model router, kill switch); set by the manager.
        self.host: MCPHost | None = None
        #: H556 — connection health, bounded connect, per-request deadline.
        self.health = ServerHealth()
        self.connect_timeout = 30.0
        self.request_timeout = 10.0
        #: The owner (or autoconnect) wants this server up: the supervisor reconnects it.
        self.wanted = False
        self._stderr_task: asyncio.Task | None = None
        #: H553 — the reply to send when a call is cancelled after the owner answered.
        self._cancel_reply: dict | None = None
        #: Bumped by every owner disconnect: a connect that started before it is undone.
        self._epoch = 0
        #: One connect at a time per server, so a check made under it holds for the spawn.
        self._connect_lock = asyncio.Lock()
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

    def _halted(self, *, include_estop: bool = True) -> str | None:
        kill = self.host.kill_switch() if self.host is not None else None
        return halted(kill, "mcp", server=self.name, include_estop=include_estop)

    async def connect(self, *, require_wanted: bool = False) -> bool:
        """Connect within :attr:`connect_timeout`, recording the outcome on :attr:`health`.

        A server that hangs on spawn or on ``initialize`` is torn down at the deadline
        (``connect_timeout``) instead of holding the caller. A configuration refusal
        (unsafe command, transport switched off) is not retried by the supervisor.

        Only the owner decides whether a server should be up (:attr:`wanted`, set by
        :meth:`MCPManager.connect_server` / ``connect_all``); this method never sets it.
        Under the per-server lock it re-checks, right before spawning, the e-stop, both
        kill-switch scopes and — for the supervisor (*require_wanted*) — that the owner
        still wants the server. An owner disconnect during the connect undoes it.
        """
        async with self._connect_lock:
            stop = self._halted()
            if stop:
                self.last_error = stop
                return False
            if require_wanted and not self.wanted:
                return False
            epoch = self._epoch
            ok = await self._connect_guarded()
            if ok and (self._epoch != epoch or (require_wanted and not self.wanted)):
                # The owner disconnected or removed the server while it was connecting.
                await self._teardown()
                self.health.stopped()
                self.last_error = "closed_by_owner"
                return False
            return ok

    async def _connect_guarded(self) -> bool:
        self.health.begin()
        started = time.monotonic()
        try:
            ok = bool(await asyncio.wait_for(self._connect_impl(), timeout=self.connect_timeout))
        except TimeoutError:
            logger.warning("MCP server %s did not connect within %.0fs", self.name, self.connect_timeout)
            self.last_error = "connect_timeout"
            await self._teardown()
            ok = False
        except asyncio.CancelledError:
            await self._teardown()
            raise
        except Exception as exc:
            logger.warning("MCP connect failed (%s): %s", self.name, type(exc).__name__)
            self.last_error = "connect_error"
            await self._teardown()
            ok = False
        if ok:
            self.health.succeeded(connect_ms=(time.monotonic() - started) * 1000.0)
        elif _permanent_refusal(self.last_error):
            self.health.refused(self.last_error or "refused")
        else:
            self.health.failed(self.last_error or "connect_failed")
        return ok

    async def _connect_impl(self):
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
                await self._teardown()
            # A reconnect re-lists from scratch (the HTTP path does the same): the old
            # list would otherwise be duplicated, and every duplicated pair is withheld
            # from the model as ambiguous (H557).
            self.tools = []
            self.utility_tools = []
            self._proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.cwd or None,
                env=self._merged_env(),
                limit=STDIO_IDLE_LINE_LIMIT,
            )
            self._start_stderr_drain()
            await self._initialize()
            logger.info(f"MCP server connected: {self.name} ({len(self.tools)} tools, "
                        f"{len(self.utility_tools)} resource/prompt tools)")
            # Nothing offered → the handshake failed; report failure so the caller stops
            # treating a dead server as available. A server that publishes only resources
            # or prompts is a live server (H552).
            if not (self.tools or self.utility_tools):
                self.last_error = "handshake_failed"
            return bool(self.tools or self.utility_tools)
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
            await self._teardown()
        self.tools = []
        self.utility_tools = []
        from agents.core.mcp.oauth_client import connect_headers

        headers, refusal = await connect_headers(self)
        if refusal:
            self.last_error = refusal
            return False
        try:
            self._http = self._http_factory(self.url, headers, name=self.name)
            result = await self._http.initialize()
            if result:
                # No server-to-client channel is read on this transport, so nothing is
                # declared for sampling or elicitation; resources and prompts still work.
                self._record_capabilities(result)
                await self._list_tools()
                self._refresh_utilities()
        except MCPTransportError as exc:
            logger.warning("MCP HTTP connect refused (%s): %s", self.name, exc.reason)
            self.last_error = exc.reason
            if isinstance(exc, MCPUnauthorized):
                # G9: the server wants (another) sign-in. A held token is refreshed on the
                # next connect; with none, the owner signs in from the MCP panel.
                from agents.core.mcp.oauth_client import mark_rejected

                mark_rejected(self.name)
            self._http = None
            return False
        if not (self.tools or self.utility_tools):
            self.last_error = "handshake_failed"
            return False
        logger.info(f"MCP server connected: {self.name} ({len(self.tools)} tools, streamable-http)")
        return True

    def is_connected(self) -> bool:
        """Transport-aware liveness (the admin list used to read ``_proc`` directly)."""
        if self.transport == TRANSPORT_STREAMABLE_HTTP:
            return self._http is not None and self._http.initialized and bool(self.tools or self.utility_tools)
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

        Baseline on (default) → allow-listed baseline + the owner's
        ``JARVIS_MCP_STDIO_ALLOWED_ENV`` names + per-server overrides only.
        Flag explicitly ``0`` → historical behaviour: inherit everything (``None``)
        or the full parent env plus overrides.

        Not a boundary: the child is same-UID, so on Linux it can still read the
        hub's real environment from ``/proc/<ppid>/environ``. See the module
        docstring — this withholds, it does not contain.
        """
        overrides = dict(self.env)
        if self.secret_env:
            # G9: the server's own secrets, read from the encrypted store at spawn time.
            from agents.core.mcp.catalog import secret_env_values

            overrides.update(secret_env_values(self.name, self.secret_env))
        if stdio_env_baseline_enabled():
            env = stdio_env_baseline(None, overrides)
            # The default drops variables, so it must not drop them silently: a
            # server that stops working because it relied on an inherited credential
            # otherwise reports a bare auth error with nothing pointing back here.
            # COUNT only — never a name and never a value, because the *names* alone
            # enumerate which provider keys this box holds.
            # Count host *values* the child does not receive, not names the child does
            # not see: a per-server override that shadows a host variable keeps the
            # name but withholds the host's value, and the owner reading this line is
            # very often debugging exactly that case.
            withheld = sum(1 for name, value in os.environ.items() if env.get(name) != value)
            if withheld:
                logger.info(
                    "MCP %s: %d host variables withheld (allowlist baseline)",
                    self.name, withheld,
                )
                # ...and immediately say what that count is NOT worth here. The child
                # inherits this directory, so a config file in it hands back what the
                # baseline just withheld. Filenames only: a *variable* name enumerates
                # which provider keys this box holds, which is why the line above is a
                # bare count, but ".env" says nothing the owner does not already know.
                readable = cwd_secret_files(self.cwd)
                if readable:
                    logger.warning(
                        "MCP %s: withholding is undercut — %s readable in the server's "
                        "working directory; the child can read what it was not handed",
                        self.name, ", ".join(readable),
                    )
            return env
        if not overrides:
            return None
        merged = os.environ.copy()
        merged.update({str(k): str(v) for k, v in overrides.items()})
        return merged

    def client_capabilities(self) -> dict:
        """What this client declares on ``initialize`` (H553): sampling only when the owner
        turned it on for this server, elicitation only when an approval queue can take it."""
        if self.host is None:
            return {}
        return self.host.client_capabilities(self.sampling, self.elicitation)

    def _record_capabilities(self, result: object) -> None:
        caps = result.get("capabilities") if isinstance(result, dict) else None
        self.server_capabilities = dict(caps) if isinstance(caps, dict) else {}

    async def _initialize(self):
        resp = await self._send({"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {
            "protocolVersion": CLIENT_PROTOCOL_VERSION,
            "capabilities": self.client_capabilities(),
            "clientInfo": dict(CLIENT_INFO),
        }})
        if resp:
            self._record_capabilities(resp.get("result"))
            await self._notify("notifications/initialized")
            await self._list_tools()
            self._refresh_utilities()

    async def _notify(self, method: str, params: dict | None = None) -> None:
        if self._proc is None or self._proc.stdin.is_closing():
            return
        try:
            line = json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}}) + "\n"
            self._proc.stdin.write(line.encode())
            await self._proc.stdin.drain()
        except Exception:
            logger.debug("MCP %s: notification %s not sent", self.name, method, exc_info=True)

    def _start_stderr_drain(self) -> None:
        """Read the child's stderr into the log (H556): an unread pipe fills and blocks it."""
        stream = getattr(self._proc, "stderr", None)
        if stream is None or not hasattr(stream, "read"):
            return

        async def drain() -> None:
            # Read in chunks, not lines: one line longer than the reader's limit would
            # raise and end the drain, and the child would block on a full pipe again.
            logged = 0
            try:
                while True:
                    chunk = await stream.read(65536)
                    if not chunk:
                        return
                    self.health.bump("stderr_bytes", len(chunk))
                    if logged < 200:
                        logged += 1
                        logger.debug("MCP %s stderr: %s", self.name,
                                     chunk[:200].decode("utf-8", "replace").rstrip())
            except (asyncio.CancelledError, Exception):
                return

        self._stderr_task = asyncio.get_running_loop().create_task(drain())

    def _refresh_utilities(self) -> None:
        """H552 — the resource/prompt tools the declared capabilities admit, minus any name a
        server tool already uses and any name the owner's filter hides."""
        own = {t.name for t in self.tools}
        rows = []
        for op in utility_ops_for(self.server_capabilities):
            if op in own or not self.tool_visible(op):
                continue
            _cap, description, schema = UTILITY_OPS[op]
            rows.append(MCPTool(op, description, schema, self.name,
                                annotations={"readOnlyHint": True}, utility=True))
        self.utility_tools = rows

    def utility(self, name: str) -> MCPTool | None:
        return next((t for t in self.utility_tools if t.name == name), None)

    def has_tool(self, name: str) -> bool:
        return any(t.name == name for t in self.tools) or self.utility(name) is not None

    def all_tools(self) -> list[MCPTool]:
        return list(self.tools) + list(self.utility_tools)

    async def request(self, method: str, params: dict | None = None) -> dict:
        """One JSON-RPC round trip on whichever transport this server speaks."""
        return await self._send({"jsonrpc": "2.0", "method": method, "params": params or {}, "id": 0})

    async def _list_tools(self):
        resp = await self._send({"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": 2})
        if resp and "result" in resp:
            hidden = 0
            listed: list[MCPTool] = []
            seen_names: set[str] = set()
            for t in resp["result"].get("tools", []):
                tool = MCPTool(
                    name=t.get("name", "unknown"),
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {}),
                    server=self.name,
                    annotations=t.get("annotations"),
                )
                if not self.tool_visible(tool.name):
                    hidden += 1
                    continue
                if tool.name in seen_names:
                    # A server listing one name twice: the first entry answers to it.
                    continue
                seen_names.add(tool.name)
                listed.append(tool)
            # A listing replaces the previous one (H557): appending made every reconnect
            # (or a tools/list refresh) duplicate each tool.
            self.tools = listed
            self._refresh_utilities()
            if hidden:
                logger.info("MCP server %s: %d tool(s) hidden by the owner's filter", self.name, hidden)

    def tool_visible(self, name: str) -> bool:
        """Does the owner's include / exclude filter let *name* through?"""
        text = str(name or "")
        if any(fnmatch.fnmatchcase(text, pattern) for pattern in self.tools_deny):
            return False
        if self.tools_allow is None:
            return True
        return any(fnmatch.fnmatchcase(text, pattern) for pattern in self.tools_allow)

    async def call_tool(self, name: str, arguments: dict = None) -> Any:
        arguments = arguments or {}
        if not isinstance(arguments, dict):
            return {"error": "bad_args", "tool": name, "server": self.name}
        if not self.tool_visible(name):
            return {"error": "tool_filtered", "tool": name, "server": self.name}
        denied = self._trust_denial(name)
        if denied is not None:
            return denied
        blocked = self._tool_call_blocked(name, arguments)
        if blocked is not None:
            return blocked
        if self.utility(name) is not None and not any(t.name == name for t in self.tools):
            return await self._call_utility(name, arguments)
        resp = await self._send({
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
            "id": 3,
        })
        if resp and "result" in resp:
            # A remote server's text is untrusted: invisible TAG characters can carry an
            # instruction the owner never sees (Hermes absorption 4a).
            # H552 — bounded (blocks, total text) and stripped off the event loop; image,
            # audio and embedded binary blocks go to disk and the model gets a path.
            return await cache_result_blocks(self.name, await bound_tool_result(resp["result"]))
        return resp

    async def _call_utility(self, op: str, arguments: dict) -> dict:
        """H552 — run one resource/prompt op; its text comes back scanned and tainted."""
        try:
            return await run_utility(op, arguments, self.request, server=self.name)
        except ResourceError as exc:
            return {"error": exc.reason, "tool": op, "server": self.name}
        except OSError:
            logger.warning("MCP %s: %s could not store a binary block", self.name, op, exc_info=True)
            return {"error": "cache_write_failed", "tool": op, "server": self.name}

    def _trust_denial(self, name: str) -> dict | None:
        """On a read-only server only a tool the server itself marked read-only may run.
        The resource/prompt tools read, so both tiers allow them."""
        if self.trust == TRUST_FULL:
            return None
        tool = next((t for t in self.tools if t.name == name), None) or self.utility(name)
        if tool is not None and tool.read_only:
            return None
        return {
            "error": "trust_denied",
            "tool": name,
            "server": self.name,
            "trust": self.trust,
            "reason": "unlisted_tool" if tool is None else "readOnlyHint_required",
        }

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
                method = msg.get("method", "")
                cap = MAX_CONTENT_REPLY_BYTES if method in _CONTENT_METHODS else None
                try:
                    return await self._http.request(method, msg.get("params") or {}, max_bytes=cap)
                except MCPUnauthorized as exc:
                    # G9: the token expired mid-session. A 401 means the server did not act,
                    # so the one retry with the refreshed token cannot run anything twice.
                    if not await self._renew_bearer(exc.sent):
                        raise
                    return await self._http.request(method, msg.get("params") or {}, max_bytes=cap)
            except MCPTransportError as exc:
                logger.warning("MCP HTTP call refused (%s): %s", self.name, exc.reason)
                return {"error": {"code": -32000, "message": exc.reason}}
        if not self._proc or self._proc.stdin.is_closing():
            logger.warning(f"MCP server {self.name} not connected")
            return {}
        if msg.get("method") in _CONTENT_METHODS:
            async with _content_gate():
                return await self._send_stdio(msg, STDIO_LINE_LIMIT)
        return await self._send_stdio(msg, STDIO_CALL_LINE_LIMIT)

    async def _renew_bearer(self, sent: str) -> bool:
        """G9 — refresh this server's OAuth token after a 401 (one refresh per server at a
        time, shared with every other caller) and put it on the live transport."""
        from agents.core.mcp import oauth_client

        if self._http is None or (self.auth != "oauth" and not oauth_client.has_tokens(self.name)):
            return False
        refused = sent[7:] if sent.startswith("Bearer ") else ""
        token, _reason = await oauth_client.access_token(self.name, self.url, rejected=refused,
                                                         pins=self.oauth)
        if not token or self._http is None or token == refused:
            return False
        for key in [k for k in self._http.headers if k.lower() == "authorization"]:
            self._http.headers.pop(key)
        self._http.headers["Authorization"] = f"Bearer {token}"
        return True

    async def _send_stdio(self, msg: dict, line_limit: int) -> dict:
        async with self._io_lock:
            if self._proc is None:
                return {}
            reader = self._proc.stdout
            buffered = len(getattr(reader, "_buffer", b"") or b"")
            if buffered >= STDIO_IDLE_LINE_LIMIT:
                # Unsolicited output while idle, up to the point asyncio paused the pipe:
                # a server flooding the hub. Drop it rather than read it.
                logger.warning("MCP %s wrote %d unsolicited bytes; disconnecting", self.name, buffered)
                self.last_error = "unsolicited_output"
                self.health.lost("unsolicited_output")
                await self._teardown()
                return {"error": {"code": -32000, "message": "unsolicited_output"}}
            _set_line_limit(reader, line_limit)
            try:
                self._next_id += 1
                req_id = self._next_id
                line = json.dumps({**msg, "id": req_id}) + "\n"
                self._proc.stdin.write(line.encode())
                await self._proc.stdin.drain()
                loop = asyncio.get_running_loop()
                deadline = loop.time() + self.request_timeout
                # Read until the reply whose id matches ours, skipping
                # notifications and any stale reply from a timed-out call.
                # Bounded so a peer echoing a fixed id can't spin forever.
                host_requests = 0
                for _ in range(32):
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        return {}
                    try:
                        raw = await asyncio.wait_for(
                            self._proc.stdout.readline(), timeout=remaining
                        )
                    except (ValueError, asyncio.LimitOverrunError):
                        # A line past STDIO_LINE_LIMIT: the reader has dropped part of it,
                        # so the pipe cannot be resynchronised. Drop the connection; the
                        # supervisor reconnects a server the owner wants.
                        logger.warning("MCP %s sent a message over %d bytes; disconnecting",
                                       self.name, line_limit)
                        self.last_error = "message_too_large"
                        self.health.lost("message_too_large")
                        await self._teardown()
                        return {"error": {"code": -32000, "message": "message_too_large"}}
                    if not raw:
                        return {}
                    try:
                        if len(raw) > _THREAD_PARSE_BYTES:
                            resp = await asyncio.to_thread(json.loads, raw)
                        else:
                            resp = json.loads(raw)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
                    if not isinstance(resp, dict):
                        continue
                    if _is_server_request(resp):
                        # H553 — the server asks the client something mid-call (sampling,
                        # elicitation, ping). It is answered here, on the same pipe, and the
                        # time the owner or the model took does not count against our call.
                        host_requests += 1
                        started = loop.time()
                        await self._answer_server_request(
                            resp, refuse=host_requests > MAX_HOST_REQUESTS_PER_CALL)
                        # Bounded: at most MAX_HOST_REQUESTS_PER_CALL waits extend it.
                        deadline += loop.time() - started
                        continue
                    if resp.get("id") == req_id:
                        return resp
                return {}
            except Exception as e:
                logger.warning(f"MCP error ({self.name}): {e}")
                return {}
            finally:
                # Back to the idle limit: an idle server can park at most ~2 MiB here.
                if self._proc is not None:
                    _set_line_limit(self._proc.stdout, STDIO_IDLE_LINE_LIMIT)

    async def _answer_server_request(self, req: dict, *, refuse: bool = False) -> None:
        method = str(req.get("method") or "")
        if self.host is None:
            out = {"error": {"code": -32601, "message": "method not supported by this client"}}
        elif refuse and method != "ping":
            out = MCPHost.refusal(method, "too many requests in one call")
        else:
            self._cancel_reply = None
            try:
                out = await self.host.handle(self, method, req.get("params"))
            except asyncio.CancelledError:
                # The call that was waiting ended (the tool loop's deadline, a stop): tell
                # the server so it does not wait forever, then let the cancel go on. If
                # the owner's answer had already been accepted, that answer is sent.
                late, self._cancel_reply = self._cancel_reply, None
                self._write_reply(req, late or MCPHost.refusal(method, "the request was withdrawn"))
                raise
            except Exception:
                logger.warning("MCP %s: answering %s failed", self.name, method[:60], exc_info=True)
                out = {"error": {"code": -32603, "message": "internal error"}}
        self._write_reply(req, out)
        try:
            await self._proc.stdin.drain()
        except Exception:
            logger.warning("MCP %s: reply to %s not written", self.name, method[:60])

    def _write_reply(self, req: dict, out: dict) -> None:
        try:
            line = json.dumps({"jsonrpc": "2.0", "id": req.get("id"), **out}) + "\n"
            self._proc.stdin.write(line.encode())
        except Exception:
            logger.warning("MCP %s: reply not written", self.name)

    async def ping(self) -> bool:
        """Keepalive (H556): False when the server did not answer within the deadline."""
        resp = await self._send({"jsonrpc": "2.0", "method": "ping", "params": {}, "id": 0})
        return bool(resp) and "result" in resp

    async def _teardown(self) -> None:
        """Stop the transport without changing whether the owner wants the server up."""
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            self._stderr_task = None
        if self._proc:
            proc, self._proc = self._proc, None
            try:
                if proc.returncode is None:
                    proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except TimeoutError:
                    proc.kill()
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
            except (TimeoutError, ProcessLookupError, AttributeError):
                pass
            # Close the pipes too: a reader paused by a full buffer never sees EOF, and
            # its transport would otherwise outlive the process.
            transport = getattr(proc, "_transport", None)
            if transport is not None:
                with suppress(Exception):
                    transport.close()
            logger.info(f"MCP server closed: {self.name}")
        if self._http is not None:
            http, self._http = self._http, None
            await http.close()
            logger.info(f"MCP server closed: {self.name}")

    async def close(self):
        """The owner's disconnect: stop the transport and stop reconnecting. A connect in
        flight sees the bumped epoch and undoes itself."""
        self.wanted = False
        self._epoch += 1
        self.health.stopped()
        await self._teardown()


class MCPManager:
    def __init__(self, *, host: MCPHost | None = None, policy: ReconnectPolicy | None = None):
        self.servers: dict[str, MCPServer] = {}
        #: Built-in governed tool names an MCP tool may never answer to (H557).
        self.reserved_names: frozenset[str] = frozenset()
        #: H553 — approval queue, model router and kill switch for server-initiated requests.
        self.host: MCPHost = host or MCPHost()
        #: H556 — the reconnect numbers every server's health record uses.
        self.policy = policy or ReconnectPolicy()
        self.connect_concurrency = CONNECT_CONCURRENCY
        self.keepalive_interval = KEEPALIVE_INTERVAL
        self._supervisor: asyncio.Task | None = None
        self._last_ping: dict[str, float] = {}

    def attach_host(self, host: MCPHost) -> None:
        self.host = host
        for srv in self.servers.values():
            srv.host = host

    def _adopt(self, srv: "MCPServer") -> "MCPServer":
        """Give a server the manager's host and reconnect policy (idempotent)."""
        srv.host = self.host
        if srv.health.policy is not self.policy:
            srv.health.policy = self.policy
        return srv

    def _halted(self, server: str | None = None) -> str | None:
        return halted(self.host.kill_switch(), "mcp", server=server)

    def reserve_names(self, names) -> None:
        """Declare the built-in tool names a third-party MCP tool may never shadow."""
        self.reserved_names = frozenset(str(n) for n in (names or ()) if str(n))

    def _provider_index(self) -> dict[str, tuple["MCPServer", MCPTool]]:
        """Model-facing name → (server, tool), collision-free.

        Pairs that sanitize to the same name are re-named with a digest of their raw
        pair; any name still shared after that is withheld from every holder (fail
        closed) instead of silently routing to whichever server came first.
        """
        pairs: list[tuple[MCPServer, MCPTool]] = []
        listed: set[tuple[str, str]] = set()
        for srv in self.servers.values():
            for tool in srv.all_tools():
                # The same (server, tool) listed twice is one tool, not a collision: the
                # first entry answers to it, as it does for dispatch.
                key = (srv.name, tool.name)
                if key in listed:
                    continue
                listed.add(key)
                pairs.append((srv, tool))
        counts: dict[str, int] = {}
        for _srv, tool in pairs:
            counts[tool.provider_name] = counts.get(tool.provider_name, 0) + 1
        named: list[tuple[str, MCPServer, MCPTool]] = []
        for srv, tool in pairs:
            name = tool.provider_name
            if counts[name] > 1:
                name = mcp_provider_name(tool.server, tool.name, hashed=True)
            named.append((name, srv, tool))
        final: dict[str, int] = {}
        for name, _srv, _tool in named:
            final[name] = final.get(name, 0) + 1
        index: dict[str, tuple[MCPServer, MCPTool]] = {}
        for name, srv, tool in named:
            if final[name] > 1:
                logger.warning("MCP tool name %s is ambiguous after sanitizing; withheld", name)
                continue
            index[name] = (srv, tool)
        return index

    def model_tools(self, reserved_names=None) -> list[dict[str, Any]]:
        """The MCP tools as model-offer rows (H557): provider-legal ``name``, the
        registration-normalized ``input_schema``, ``gated`` unless the server declared
        the tool read-only, and ``untrusted_output`` always (third-party output).

        A row whose name equals a built-in governed tool name (``reserved_names`` plus
        :meth:`reserve_names`) is withheld — a third-party tool never shadows one — and
        so is a tool the server's trust tier refuses (a mutating tool on a read-only
        server), which every call would fail on.
        """
        reserved = self.reserved_names | frozenset(str(n) for n in (reserved_names or ()))
        rows: list[dict[str, Any]] = []
        for name, (srv, tool) in self._provider_index().items():
            if name in reserved:
                logger.warning("MCP tool %s shadows a built-in tool name; withheld", name)
                continue
            if srv._trust_denial(tool.name) is not None:
                # The owner's trust tier would refuse every call: never offer it.
                continue
            rows.append({
                "name": name,
                "description": tool.description,
                "input_schema": tool.input_schema,
                "gated": not tool.read_only,
                "untrusted_output": True,
                "server": srv.name,
                "tool": tool.name,
                "qualified_name": tool.qualified_name,
                **({"utility": True} if tool.utility else {}),
            })
        return rows

    def register(self, server: MCPServer):
        self.servers[server.name] = self._adopt(server)

    # ── H556: parallel bounded connects, reconnect with backoff, keepalive ──

    async def _connect_one(self, srv: MCPServer, gate: asyncio.Semaphore, *,
                           supervised: bool = False) -> bool:
        async with gate:
            self._adopt(srv)
            await warm_cleaner()          # build the cleaner's character table off the loop
            try:
                ok = await srv.connect(require_wanted=supervised)
            except Exception as e:                       # connect() records; this is a last net
                logger.warning(f"MCP connect failed ({srv.name}): {type(e).__name__}")
                return False
            if self.servers.get(srv.name) is not srv:
                # Removed while connecting: never leave a child running outside `servers`.
                await srv.close()
                return False
            return ok

    async def remove_server(self, name: str) -> bool:
        """The owner removes a server: closed in every state (connected, connecting,
        backing off), so no child is left running outside :attr:`servers`."""
        srv = self.servers.pop(name, None)
        if srv is None:
            return False
        await srv.close()
        return True

    async def connect_all(self, names=None) -> dict[str, bool]:
        """Connect every server (or *names*) at once, at most :attr:`connect_concurrency`
        in flight. Each connect has its own deadline (``connect_timeout``), so one hung
        server costs its own slot, never the others' answers."""
        if self._halted():
            logger.warning("MCP connect_all refused: %s", self._halted())
            return {}
        chosen = [srv for name, srv in self.servers.items() if names is None or name in names]
        for srv in chosen:
            srv.wanted = True                            # the owner's (or autoconnect's) ask
        gate = asyncio.Semaphore(max(1, int(self.connect_concurrency)))
        results = await asyncio.gather(*(self._connect_one(srv, gate) for srv in chosen))
        return {srv.name: bool(ok) for srv, ok in zip(chosen, results, strict=True)}

    async def connect_server(self, name: str) -> bool:
        srv = self.servers.get(name)
        if srv is None:
            return False
        srv.wanted = True                                # only the owner sets this
        return await self._connect_one(srv, asyncio.Semaphore(1))

    async def tick(self, now: float | None = None) -> dict[str, str]:
        """One supervisor pass: reconnect what is due, ping what is idle. Returns what it did.

        Nothing is spawned or pinged while the e-stop or kill switch is engaged."""
        if self._halted():
            return {}
        now = time.time() if now is None else now
        done: dict[str, str] = {}
        due: list[MCPServer] = []
        for srv in list(self.servers.values()):
            if not srv.wanted or self._halted(srv.name):
                continue
            if srv.is_connected():
                if (srv.transport == TRANSPORT_STDIO and not srv._io_lock.locked()
                        and now - self._last_ping.get(srv.name, 0.0) >= self.keepalive_interval):
                    self._last_ping[srv.name] = now
                    if await srv.ping():
                        done[srv.name] = "ping_ok"
                    else:
                        srv.health.lost("keepalive_failed", now=now)
                        await srv._teardown()
                        done[srv.name] = "ping_failed"
                continue
            srv.health.lost("transport_lost", now=now)
            if srv.health.retry_due(now):
                due.append(srv)
        if due:
            gate = asyncio.Semaphore(max(1, int(self.connect_concurrency)))
            # Each connect re-checks, under its server's lock and right before spawning,
            # that the owner still wants it and nothing is halted: a disconnect made while
            # this pass was pinging another server is not undone.
            results = await asyncio.gather(*(self._connect_one(srv, gate, supervised=True)
                                             for srv in due))
            for srv, ok in zip(due, results, strict=True):
                done[srv.name] = "reconnected" if ok else "retry_failed"
        return done

    async def _supervise(self, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("MCP supervisor pass failed", exc_info=True)

    def start(self, *, autoconnect: bool = False, interval: float = SUPERVISOR_INTERVAL) -> None:
        """Start the reconnect/keepalive supervisor; with *autoconnect*, connect every saved
        server in the background first (boot never waits on an MCP server)."""
        for srv in self.servers.values():
            self._adopt(srv)
        if self._supervisor is not None and not self._supervisor.done():
            return
        loop = asyncio.get_running_loop()

        async def run() -> None:
            if autoconnect:
                try:
                    await self.connect_all()
                except Exception:
                    logger.warning("MCP background connect failed", exc_info=True)
            await self._supervise(interval)

        self._supervisor = loop.create_task(run())

    def health(self) -> dict[str, dict]:
        """One status for every surface: per server, connection health and host counters."""
        return {name: {"connected": srv.is_connected(), **srv.health.status()}
                for name, srv in self.servers.items()}

    def get_tools(self) -> list[MCPTool]:
        tools = []
        for srv in self.servers.values():
            tools.extend(srv.tools)
        return tools

    def _resolve(self, name: str, server: str | None) -> tuple[MCPServer | None, str, dict | None]:
        """``(server, bare tool name, error)`` for *name*.

        A ``server/tool`` name, or an explicit ``server=``, pins the server. A bare name is
        accepted only when exactly one server offers it: dispatch used to pick whichever
        server came first in dict order, so adding a second server could silently redirect
        an existing call (Hermes absorption 4a).
        """
        bare = str(name or "")
        if server is None and bare in self.reserved_names:
            # H557: a bare or model-facing name equal to a built-in governed tool
            # never dispatches to a third-party server.
            return None, bare, {"error": "shadows_builtin", "tool": bare}
        if server is None and bare.startswith(PROVIDER_NAME_PREFIX):
            hit = self._provider_index().get(bare)
            if hit is not None:
                return hit[0], hit[1].name, None
        if server is None and "/" in bare:
            prefix, _, rest = bare.partition("/")
            if prefix in self.servers and rest:
                server, bare = prefix, rest
        if server is not None:
            srv = self.servers.get(server)
            if srv is None:
                return None, bare, {"error": "server_not_found", "tool": bare, "server": server}
            if not srv.has_tool(bare):
                return None, bare, {"error": f"Tool '{bare}' not found", "server": server}
            return srv, bare, None
        offering = [srv for srv in self.servers.values() if srv.has_tool(bare)]
        if not offering:
            return None, bare, {"error": f"Tool '{bare}' not found"}
        if len(offering) > 1:
            return None, bare, {
                "error": "ambiguous_tool",
                "tool": bare,
                "servers": [srv.name for srv in offering],
            }
        return offering[0], bare, None

    def find_tool(self, name: str, *, server: str | None = None) -> MCPTool:
        srv, bare, error = self._resolve(name, server)
        if error is not None or srv is None:
            return None
        for t in srv.all_tools():
            if t.name == bare:
                return t
        return None

    async def call_tool(self, name: str, arguments: dict = None, *, server: str | None = None) -> Any:
        srv, bare, error = self._resolve(name, server)
        if error is not None or srv is None:
            return error
        if srv._halted(include_estop=False):
            # Both kill-switch scopes (``mcp`` and ``mcp:<server>``) stop calls too. The
            # e-stop does not: it pauses new autonomous work, not the owner's chat.
            return {"error": "kill_switch_engaged", "tool": bare, "server": srv.name}
        if srv.wanted and not srv.is_connected() and not self._halted(srv.name):
            # H556 — a server that dropped is reconnected on its next use, when its
            # backoff allows; otherwise the call answers at once instead of waiting.
            srv.health.lost("transport_lost")
            if srv.health.retry_due():
                await self._connect_one(srv, asyncio.Semaphore(1), supervised=True)
        return await srv.call_tool(bare, arguments)

    async def close_all(self):
        task, self._supervisor = self._supervisor, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task
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
                "trust": srv.trust,
                "tools_allow": srv.tools_allow,
                "tools_deny": srv.tools_deny,
                "sampling": srv.sampling.to_config(),
                "elicitation": srv.elicitation.to_config(),
                # G9 — written only when set, so a config saved before stays byte-identical.
                **({"auth": srv.auth} if srv.auth != "none" else {}),
                **({"env": dict(srv.env)} if srv.env and srv.origin else {}),
                **({"secret_env": list(srv.secret_env)} if srv.secret_env else {}),
                **({"secret_headers": dict(srv.secret_headers)} if srv.secret_headers else {}),
                **({"oauth": dict(srv.oauth)} if srv.oauth else {}),
                **({"origin": dict(srv.origin)} if srv.origin else {}),
            }
            for srv in self.servers.values()
        ]

    def load_from_config(self, configs: list[dict]):
        """Load servers from config list."""
        self.servers.clear()
        for cfg in configs if isinstance(configs, list) else []:
            # A saved entry the loader cannot read is skipped, never a stop at start
            # (review-H157 m2: an import or a hand edit could store one).
            if not isinstance(cfg, dict) or not isinstance(cfg.get("name"), str) \
                    or not cfg["name"].strip():
                logger.warning("MCP servers setting: skipped an entry with no name")
                continue
            headers = cfg.get("headers")
            raw_trust = cfg.get("trust")
            trust = normalize_trust(raw_trust)
            if trust is None:
                if raw_trust is None:
                    # A config saved before trust tiers existed: keep it working as it
                    # did (every tool reachable) and say so, rather than break the
                    # owner's setup on upgrade. New servers default to read-only.
                    trust = TRUST_FULL
                    logger.warning(
                        "MCP server %s has no trust tier in its saved config; treated as "
                        "full for compatibility — set it to read-only or full explicitly",
                        cfg.get("name"),
                    )
                else:
                    trust = TRUST_READ_ONLY
                    logger.warning(
                        "MCP server %s: unknown trust tier %r; treated as read-only",
                        cfg.get("name"), raw_trust,
                    )
            srv = MCPServer(
                name=cfg["name"],
                transport=cfg.get("transport", "stdio"),
                command=cfg.get("command"),
                url=cfg.get("url"),
                cwd=cfg.get("cwd"),
                headers=headers if isinstance(headers, dict) else None,
                trust=trust,
                tools_allow=cfg.get("tools_allow"),
                tools_deny=cfg.get("tools_deny"),
                sampling=cfg.get("sampling"),
                elicitation=cfg.get("elicitation"),
                **_g9_fields(cfg),
            )
            self.servers[srv.name] = self._adopt(srv)


def _g9_fields(cfg: dict) -> dict:
    """G9 — the catalog/OAuth fields of a saved server, each kept only in its expected shape.
    ``env`` is read back only for a server installed through the catalog (``origin``): its
    values are the manifest's static, non-secret settings."""
    out: dict = {}
    auth = cfg.get("auth")
    if auth in ("none", "oauth", "api_key"):
        out["auth"] = auth
    origin = cfg.get("origin")
    if isinstance(origin, dict):
        out["origin"] = {str(k): v for k, v in origin.items() if isinstance(v, (str, int, type(None)))}
        env = cfg.get("env")
        if isinstance(env, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
            out["env"] = dict(env)
    names = cfg.get("secret_env")
    if isinstance(names, list):
        out["secret_env"] = [n for n in names if isinstance(n, str)]
    headers = cfg.get("secret_headers")
    if isinstance(headers, dict):
        out["secret_headers"] = {k: v for k, v in headers.items() if isinstance(k, str) and isinstance(v, str)}
    oauth = cfg.get("oauth")
    if isinstance(oauth, dict):
        out["oauth"] = {k: v for k, v in oauth.items() if isinstance(k, str) and isinstance(v, (str, int))}
    return out
