"""H381 — no prompt-carrying module dials a bare HTTPX client.

DRA-23 closed the hole where every LLM backend built its own ``httpx.AsyncClient`` and
a cloud turn left the machine without the egress ledger seeing it: model traffic now
goes through ``agents.core.llm.egress.llm_async_client`` / ``llm_sync_client`` (the
request hook records the dialled host, enforces the host-mandated protocol and the
routed data-handling gate before transport entry) or through the admitted native
transport (``agents/core/llm/providers/native_transport.py``), which records at the
signed leased transport. Nothing kept it closed: a new provider client, catalog fetch,
health probe or OAuth refresh written with a bare ``httpx.AsyncClient`` re-opened it and
every test still passed.

This is the structural rule. Every ``*.py`` under ``agents/`` is parsed and the rule is
**inverted**: every read of a bare constructor (``httpx.AsyncClient`` / ``httpx.Client``,
through any alias of the package or of a private submodule such as ``httpx._client``,
any name imported from it, any name assigned from it anywhere, any re-export through
another repo module) is a finding unless it can only be a *type* — an annotation, the
class argument of ``isinstance``/``issubclass``, an identity/equality/membership
comparison, a subscript (``type[httpx.AsyncClient]``), ``cast``'s type or a ``TypeVar``
bound. So a call, a subclass, a class attribute, a default parameter, a tuple or
annotated assignment, a returned constructor, a ``partial`` or a dict entry are all
caught without the scanner having to list the shape. Also caught: every read of a
module-level request helper (``httpx.get`` / ``post`` / ``stream`` …, which build a bare
client internally), the httpx package handed on as an object (``getattr(httpx, …)``),
``import_module("httpx")``, rebinding ``httpx.AsyncClient``, and a raw
``transport.handle_async_request`` read outside an ``httpx`` transport class (a transport
mounted on a ledgered client is the only place a raw send is admitted).

A finding in the **prompt-carrying scope** — ``agents/core/llm/**`` plus every provider
module (any module that builds model clients through the ledgered constructor, the
admitted native transport or the direct-transport proof, and the provider roots named
below) — fails unless its exact ``(file, enclosing function)`` is on
:data:`PROMPT_SCOPE_ALLOWLIST` with a reason. A finding anywhere else fails unless its
exact ``(file, enclosing function)`` is classified in :data:`NOT_A_MODEL_PROVIDER`, so a
provider written somewhere new — or a new client added to a classified module — cannot
slip past the scope by living outside ``llm/``.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
AGENTS = REPO / "agents"

# Provider roots outside ``llm/`` that carry a prompt (or an image prompt) to a model
# even where they do not (yet) import the ledgered constructor.
PROVIDER_ROOTS = (
    "agents/core/media_backends/",      # image-generation backends: the prompt is the payload
    "agents/core/workspace/llm.py",     # Nerva Workspace model engine
    "agents/core/ingestion/",           # embedding providers (document text is the payload)
)

# Each entry: (repo-relative file, enclosing qualname) -> why that bare client is not a
# hole in the ledger. Exact keys only; a stale key fails `test_every_exemption_is_still_needed`.
PROMPT_SCOPE_ALLOWLIST: dict[tuple[str, str], str] = {
    ("agents/core/llm/direct_transport.py", "<module>"):
        "`_NATIVE_ASYNC_CLIENT = httpx.AsyncClient` pins the installed class at import so "
        "require_direct_async_transport can refuse any other client type with `is not`; "
        "it is only ever compared, never called (a call through the alias is a finding)",
    ("agents/core/llm/egress.py", "llm_async_client"):
        "the ledgered constructor itself: it installs the recording/protocol/data-handling "
        "request hook and the H504 trust anchor before returning the client",
    ("agents/core/llm/egress.py", "llm_sync_client"):
        "the synchronous twin of llm_async_client (same hook, same trust anchor)",
    ("agents/core/llm/lmstudio_control.py", "_default_models"):
        "header-less GET /v1/models on the configured LM Studio server (default loopback) "
        "to resolve a model id; no prompt, image or credential (control-plane poller — "
        "the scope note in egress.py keeps these out of the ledger on purpose)",
    ("agents/core/llm/local_model_inventory.py", "_probe_providers"):
        "header-less GETs of catalog/residency (/v1/models, /api/v0/models, /api/tags, "
        "/api/ps) on the configured LM Studio/Ollama servers; no prompt, image or credential",
    ("agents/core/llm/model_setup.py", "_client"):
        "Ollama tags/pull/delete; every caller refuses a non-loopback URL first "
        "(is_loopback_url) and the body is a model tag, never a prompt (trust_env=False)",
    ("agents/core/llm/ollama_control.py", "OllamaController._http_client"):
        "Ollama control plane on the configured server (default loopback): list, pull, and "
        "load/unload via /api/generate with an EMPTY prompt and keep_alive; no content",
    ("agents/core/llm/router.py", "LLMRouter._check"):
        "router health check: header-less GET on the configured LM Studio/Ollama URL; no prompt",
    ("agents/core/llm/router.py", "LLMRouter._fetch_loaded_model"):
        "router model detection: header-less GET /v1/models or /api/tags; no prompt",
    ("agents/core/workspace/llm.py", "_server_answers"):
        "workspace posture liveness GET (/v1/models or /api/tags) of an LM Studio/Ollama "
        "backend only (_probe_target returns None for every other backend); no prompt or "
        "credential — workspace prompts go through the hub router's ledgered backends",
    ("agents/core/media_backends/comfyui.py", "ComfyUIBackend.generate"):
        "image prompt to a literal-loopback ComfyUI server (ComfyUIConfig admits only a "
        "loopback URL, trust_env=False, no redirects): it cannot leave the machine; not a "
        "ledger row (local image generation is outside the model-egress ledger)",
    ("agents/core/media_backends/local_openai_image.py", "LocalOpenAIImageBackend.generate"):
        "image prompt to a literal-loopback OpenAI-images server (registry.local_endpoint, "
        "require_direct_async_transport on every send, trust_env=False): it cannot leave "
        "the machine; not a ledger row (local image generation is outside the ledger)",
}

# Modules outside the prompt-carrying scope that legitimately dial their own client:
# none of them sends a model prompt. Module path -> (what the client talks to, the
# exact enclosing qualnames that may do it). A new bare client anywhere else in a
# classified module fails until it is classified here too.
NOT_A_MODEL_PROVIDER: dict[str, tuple[str, frozenset[str]]] = {
    "agents/core/http_client.py": (
        "the plugin egress choke point itself; every request it sends is recorded in the "
        "same ledger under the plugin's row (cloud image providers dial through it)",
        frozenset({"PluginHTTPClient._get_client", "PluginHTTPClient._pinned_client"})),
    "agents/core/channels/telegram.py": (
        "Telegram Bot API channel transport (messages to/from the owner's chat)",
        frozenset({"TelegramChannel.__init__", "TelegramChannel.start"})),
    "agents/core/cameras/frigate.py": (
        "Frigate NVR API on the owner's LAN", frozenset({"_FrigateHTTP.request_bytes"})),
    "agents/core/house/home_assistant.py": (
        "Home Assistant REST API on the owner's LAN", frozenset({"_HttpxREST.request"})),
    "agents/core/house/wled.py": (
        "WLED light controller JSON API on the LAN", frozenset({"HttpxJSONTransport.__call__"})),
    "agents/core/memory/graph.py": (
        "Neo4j HTTP transaction endpoint (graph database)",
        frozenset({"Neo4jGraph._check_connection", "Neo4jGraph._call_neo4j", "Neo4jGraph.clear"})),
    "agents/core/memory/qdrant_store.py": (
        "Qdrant vector database REST API", frozenset({"QdrantVectorStore.__init__"})),
    "agents/core/skills/importer.py": (
        "skill source fetch from GitHub/registries (no prompt)",
        frozenset({"SkillImporter.import_from_hermes", "SkillImporter._import_from_github",
                   "SkillImporter._sync_from_hermes", "SkillImporter.sync_source"})),
    "agents/core/voice/tts.py": (
        "speech synthesis of reply text, not a model prompt; its cloud vendors are a "
        "recorded, separate ledger gap (GET /api/admin/network/calls docstring)",
        frozenset({"TTSEngine._speak_xtts", "TTSEngine._speak_elevenlabs", "TTSEngine._speak_fish"})),
    "agents/core/routers/admin.py": (
        "POST /api/admin/llm/test: header-less GET of the fixed localhost LM Studio "
        "/v1/models and Ollama /api/tags URLs (no prompt)",
        frozenset({"admin_llm_test"})),
    "agents/core/observability/fault_injection.py": (
        "the llm_down chaos drill wraps httpx.AsyncClient.send/Client.send to REFUSE matching "
        "hosts and restores the originals; every request it lets through runs the original "
        "send, request hooks (the ledger) included, and it sends nothing itself",
        frozenset({"_apply_llm_down", "_apply_llm_down.restore"})),
}


# ── the scanner ──────────────────────────────────────────────────────────────

_CONSTRUCTORS = frozenset({"AsyncClient", "Client"})
_HELPERS = frozenset({"get", "post", "put", "patch", "delete", "head", "options",
                      "request", "stream"})
_TRANSPORT_BASES = frozenset({"AsyncBaseTransport", "BaseTransport"})
_RAW_SENDS = frozenset({"handle_async_request", "handle_request"})
# A client's private send steps run AFTER its request hooks: calling one directly on a
# ledgered client would skip the ledger, the protocol check and the data-handling gate.
_PRIVATE_SENDS = frozenset({"_send_single_request", "_send_handling_redirects",
                            "_send_handling_auth"})
# Reading these off the class constructs an instance; any other member read
# (`httpx.AsyncClient.send`, `._transport_for_url`) is an identity pin or a method.
_CONSTRUCTION = frozenset({"__new__", "__init__", "__call__"})
_IDENTITY_OPS = (ast.Is, ast.IsNot, ast.Eq, ast.NotEq, ast.In, ast.NotIn)
_LEDGER_MARKERS = frozenset({"llm_async_client", "llm_sync_client", "llm_sync_request_hook",
                             "native_admitted_client", "require_direct_async_transport",
                             "custom_client"})

_CTOR, _HELPER, _HTTPX, _REPO = "ctor", "helper", "httpx", "repo"


def _attr_chain(node: ast.AST) -> list[str]:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return parts[::-1]
    return []


def _httpx_member(name: str) -> str | None:
    """What a name read off the httpx package (or one of its submodules) is."""
    if name in _CONSTRUCTORS:
        return _CTOR
    if name in _HELPERS:
        return _HELPER
    if name.startswith("_") and not name.startswith("__"):
        return _HTTPX          # a private submodule (``httpx._client``, ``httpx._api``)
    return None


def _module_name(rel: str) -> str:
    parts = rel[:-3].split("/")
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _import_source(module: str, is_package: bool, node: ast.ImportFrom) -> str:
    if not node.level:
        return node.module or ""
    base = module.split(".") if is_package else module.split(".")[:-1]
    if node.level > 1:
        base = base[: len(base) - (node.level - 1)]
    return ".".join([*base, *([node.module] if node.module else [])])


def _assignments(node: ast.AST) -> list[tuple[ast.AST, ast.AST]]:
    """(target, value) pairs one statement binds, tuple unpacks paired element-wise."""
    if isinstance(node, ast.Assign):
        pairs = [(t, node.value) for t in node.targets]
    elif isinstance(node, ast.AnnAssign) and node.value is not None:
        pairs = [(node.target, node.value)]
    else:
        return []
    out = []
    while pairs:
        target, value = pairs.pop()
        if (isinstance(target, (ast.Tuple, ast.List)) and isinstance(value, (ast.Tuple, ast.List))
                and len(target.elts) == len(value.elts)):
            pairs.extend(zip(target.elts, value.elts, strict=True))
        else:
            out.append((target, value))
    return out


class _Module:
    """One parsed module and the statements that can bind a name."""

    def __init__(self, rel: str, source: str) -> None:
        self.rel = rel
        self.name = _module_name(rel)
        self.is_package = rel.endswith("/__init__.py")
        self.source = source
        self.tree = ast.parse(source)
        self.imports: list[ast.Import | ast.ImportFrom] = []
        self.assignments: list[tuple[ast.AST, ast.AST]] = []
        # Bindings are statements, so only statement lists are walked (an expression-level
        # walrus binding needs no tracking: its value is itself an uncalled reference).
        pending = list(self.tree.body)
        while pending:
            node = pending.pop()
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                self.imports.append(node)
                continue
            self.assignments.extend(_assignments(node))
            for field in ("body", "orelse", "finalbody", "handlers", "cases"):
                pending.extend(getattr(node, field, ()) or ())


class _Bindings:
    """Every name in one module bound to the httpx package, a bare client constructor,
    a request helper or a repo module. Flow-insensitive: a binding made anywhere (a
    function-local import, a class attribute, a tuple unpack, an annotated or walrus
    assignment, a re-export from another repo module) counts."""

    def __init__(self, module: _Module, exports: dict[str, dict[str, str]],
                 repo_modules: set[str]) -> None:
        self.names: dict[str, tuple[str, str]] = {}
        self.exports = exports
        self.repo_modules = repo_modules
        for node in module.imports:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "httpx" or alias.name.startswith("httpx."):
                        self.names[alias.asname or "httpx"] = (_HTTPX, "httpx")
                    elif alias.name in repo_modules:
                        bound = alias.asname or alias.name.split(".")[0]
                        self.names[bound] = (_REPO, alias.name if alias.asname else bound)
                continue
            source = _import_source(module.name, module.is_package, node)
            for alias in node.names:
                bound = alias.asname or alias.name
                if source == "httpx" or source.startswith("httpx."):
                    if alias.name == "*":
                        self.names.update({n: (_CTOR, n) for n in _CONSTRUCTORS})
                        self.names.update({n: (_HELPER, n) for n in _HELPERS})
                    elif (kind := _httpx_member(alias.name)) is not None:
                        self.names[bound] = (kind, alias.name)
                elif alias.name == "*":
                    for name, kind in exports.get(source, {}).items():
                        self.names[name] = (kind, name)
                elif alias.name in exports.get(source, {}):
                    self.names[bound] = (exports[source][alias.name], alias.name)
                elif f"{source}.{alias.name}" in repo_modules:
                    self.names[bound] = (_REPO, f"{source}.{alias.name}")
        for _ in range(3):  # aliases of aliases (`A = httpx.AsyncClient; B = A`)
            for target, value in module.assignments:
                kind = self.resolve(value)
                if kind is not None and kind[0] != _REPO and isinstance(target, ast.Name):
                    self.names[target.id] = kind

    def resolve(self, node: ast.AST) -> tuple[str, str] | None:
        if isinstance(node, ast.Name):
            return self.names.get(node.id)
        if not isinstance(node, ast.Attribute):
            return None
        base = self.resolve(node.value)
        if base is None:
            return None
        if base[0] == _HTTPX:
            kind = _httpx_member(node.attr)
            return (kind, node.attr) if kind else None
        if base[0] == _REPO:
            exported = self.exports.get(base[1], {}).get(node.attr)
            if exported:
                return (exported, node.attr)
            sub = f"{base[1]}.{node.attr}"
            return (_REPO, sub) if sub in self.repo_modules else None
        return None

    def exported(self) -> dict[str, str]:
        return {name: kind for name, (kind, _) in self.names.items() if kind != _REPO}


class _Scanner:
    """Collect (qualname, line, shape) for every bare-client path in one module.

    The rule is inverted on purpose (see the module docstring): every read of a bare
    constructor is a finding except in a type-only position, so a new hand-off shape is
    caught without the scanner having to know it."""

    def __init__(self, bindings: _Bindings) -> None:
        self.b = bindings
        self.findings: list[tuple[str, int, str]] = []
        self._scope: list[str] = []
        self._transport: list[bool] = []

    def _qual(self) -> str:
        return ".".join(self._scope) or "<module>"

    def _hit(self, node: ast.AST, shape: str) -> None:
        self.findings.append((self._qual(), getattr(node, "lineno", 0), shape))

    def _in_transport(self) -> bool:
        return bool(self._transport and self._transport[-1])

    def visit(self, node: ast.AST, safe: bool = False, role: str = "") -> None:
        handler = getattr(self, "_v_" + type(node).__name__, None)
        if handler is not None:
            handler(node, safe, role)
            return
        # Only a literal grouping keeps a type position (`(A, B)`, `A | None`).
        keep = safe and isinstance(node, (ast.Tuple, ast.List, ast.Set, ast.BinOp, ast.Starred))
        for child in ast.iter_child_nodes(node):
            self.visit(child, keep)

    # ── references ───────────────────────────────────────────────────────────
    def _reference(self, node: ast.Name | ast.Attribute, safe: bool, role: str) -> bool:
        kind = self.b.resolve(node)
        if kind is None:
            return False
        if not isinstance(node.ctx, ast.Load):
            if kind[0] in (_CTOR, _HELPER) and isinstance(node, ast.Attribute):
                self._hit(node, "rebinds the httpx client constructor or helper")
            return True
        if kind[0] == _CTOR:
            if role == "call":
                self._hit(node, "builds a bare httpx client")
            elif role == "base":
                self._hit(node, "subclasses the bare client")
            elif not safe:
                self._hit(node, "references the bare client constructor uncalled "
                                "(aliased, defaulted, returned or handed on)")
        elif kind[0] == _HELPER:
            self._hit(node, "uses a module-level httpx request helper" if role == "call"
                      else "references a module-level httpx request helper")
        elif kind[0] == _HTTPX:
            self._hit(node, "hands the httpx module object on")
        return True     # resolved (a repo module included): nothing below it to see

    def _v_Name(self, node, safe, role):
        self._reference(node, safe, role)

    def _v_Attribute(self, node, safe, role):
        if self._reference(node, safe, role):
            return
        if node.attr in _RAW_SENDS and not self._in_transport():
            self._hit(node, "sends through a raw transport outside a transport class")
        if node.attr in _PRIVATE_SENDS:
            self._hit(node, "skips the client's request hooks through a private send step")
        base = self.b.resolve(node.value)
        if base is not None and base[0] == _CTOR:
            if not isinstance(node.ctx, ast.Load):
                self._hit(node, "patches the httpx client class")
            elif node.attr in _CONSTRUCTION:
                self._reference(node.value, False, role if role == "call" else "")
            return      # `httpx.AsyncClient._transport_for_url`: an identity pin, not a client
        if base is not None:
            return      # a member that is not a client: `httpx.Timeout`, `egress.llm_async_client`
        self.visit(node.value)

    def _v_Subscript(self, node, safe, role):
        self.visit(node.value, safe)
        self.visit(node.slice, True)     # `type[httpx.AsyncClient]`, `dict[str, Client]`

    def _v_Compare(self, node, safe, role):
        identity = all(isinstance(op, _IDENTITY_OPS) for op in node.ops)
        for operand in [node.left, *node.comparators]:
            self.visit(operand, identity)

    def _v_Call(self, node, safe, role):
        name = (_attr_chain(node.func) or [""])[-1]
        self.visit(node.func, False, "call")
        type_args: set[int] = set()
        if name in {"isinstance", "issubclass"}:
            type_args = set(range(1, len(node.args)))
        elif name == "cast":
            type_args = {0}
        elif name in {"getattr", "hasattr", "setattr"} and len(node.args) >= 2:
            attr = node.args[1]
            if isinstance(attr, ast.Constant) and isinstance(attr.value, str):
                if attr.value in _RAW_SENDS and not self._in_transport():
                    self._hit(node, "reaches a raw transport send by name")
                elif attr.value in _CONSTRUCTORS | _HELPERS and self.b.resolve(node.args[0]):
                    self._hit(node, "reaches the bare client by name")
        elif name in {"import_module", "__import__"} and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and str(first.value).split(".")[0] == "httpx":
                self._hit(node, "imports httpx dynamically")
        for index, arg in enumerate(node.args):
            self.visit(arg, index in type_args)
        for keyword in node.keywords:
            self.visit(keyword.value, name == "TypeVar" and keyword.arg == "bound")

    # ── definitions ──────────────────────────────────────────────────────────
    def _arguments(self, args: ast.arguments) -> None:
        for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs,
                    *([args.vararg] if args.vararg else []), *([args.kwarg] if args.kwarg else [])]:
            if arg.annotation is not None:
                self.visit(arg.annotation, True)
        for default in [*args.defaults, *(d for d in args.kw_defaults if d is not None)]:
            self.visit(default)

    def _v_FunctionDef(self, node, safe, role):
        for decorator in node.decorator_list:
            self.visit(decorator)
        self._scope.append(node.name)
        for param in getattr(node, "type_params", ()):
            self.visit(param)
        self._arguments(node.args)
        if node.returns is not None:
            self.visit(node.returns, True)
        for statement in node.body:
            self.visit(statement)
        self._scope.pop()

    _v_AsyncFunctionDef = _v_FunctionDef

    def _v_Lambda(self, node, safe, role):
        self._arguments(node.args)
        self.visit(node.body)

    def _v_ClassDef(self, node, safe, role):
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base, False, "base")
        for keyword in node.keywords:
            self.visit(keyword.value)
        is_transport = any((_attr_chain(b) or [""])[-1] in _TRANSPORT_BASES for b in node.bases)
        self._scope.append(node.name)
        for param in getattr(node, "type_params", ()):
            self.visit(param)
        self._transport.append(is_transport)
        for statement in node.body:
            self.visit(statement)
        self._transport.pop()
        self._scope.pop()

    def _v_AnnAssign(self, node, safe, role):
        self.visit(node.annotation, True)
        self.visit(node.target)
        if node.value is not None:
            self.visit(node.value)

    def _v_TypeAlias(self, node, safe, role):
        self.visit(node.value, True)

    def _v_TypeVar(self, node, safe, role):
        if getattr(node, "bound", None) is not None:
            self.visit(node.bound, True)


def _repo_module_names(rels) -> set[str]:
    names: set[str] = set()
    for rel in rels:
        parts = _module_name(rel).split(".")
        names.update(".".join(parts[:i]) for i in range(1, len(parts) + 1))
    return names


def _bind_all(modules: dict[str, _Module], repo_modules: set[str] | None = None,
              ) -> dict[str, _Bindings]:
    """Bindings for every module, re-exports followed to a fixed point."""
    repo_modules = repo_modules if repo_modules is not None else _repo_module_names(modules)
    exports: dict[str, dict[str, str]] = {}
    while True:
        bindings = {rel: _Bindings(m, exports, repo_modules) for rel, m in modules.items()}
        found = {modules[rel].name: b.exported() for rel, b in bindings.items() if b.exported()}
        if found == exports:
            return bindings
        exports = found


def scan_modules(sources: dict[str, str]) -> dict[str, list[tuple[str, int, str]]]:
    """Scan several modules together (re-exports resolve across them)."""
    modules = {rel: _Module(rel, src) for rel, src in sources.items()}
    out = {}
    for rel, bindings in _bind_all(modules).items():
        scanner = _Scanner(bindings)
        scanner.visit(modules[rel].tree)
        out[rel] = scanner.findings
    return out


def scan_source(source: str, rel: str = "agents/core/llm/_probe.py") -> list[tuple[str, int, str]]:
    return scan_modules({rel: source})[rel]


def _rel(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def _modules() -> list[Path]:
    return sorted(p for p in AGENTS.rglob("*.py")
                  if "__pycache__" not in p.parts and not _rel(p).startswith("agents/web/"))


def _is_provider_module(module: _Module) -> bool:
    if module.rel.startswith("agents/core/llm/") or module.rel.startswith(PROVIDER_ROOTS):
        return True
    for node in module.imports:
        if isinstance(node, ast.ImportFrom):
            source = node.module or ""
            if (source.endswith(("llm.egress", "llm.direct_transport",
                                 "providers.native_transport", "providers.custom_runtime"))
                    or (node.level and source in {"egress", "direct_transport"})):
                return True
            if any(alias.name in _LEDGER_MARKERS for alias in node.names):
                return True
    return False


_PROVIDER_IMPORT_HINTS = ("egress", "direct_transport", "native_transport", "custom_runtime",
                          *_LEDGER_MARKERS)


def _scan_repo():
    sources = {_rel(p): p.read_text(encoding="utf-8") for p in _modules()}
    repo_modules = _repo_module_names(sources)
    # Parse only what can matter (parsing all ~1000 modules costs seconds): a module that
    # names httpx or a raw send, a provider by path or by import, and — to a fixed point —
    # any module whose text names something another parsed module binds to a bare
    # constructor or helper (a re-export under a name that never mentions httpx).
    hints = ("httpx", *_RAW_SENDS, *_PROVIDER_IMPORT_HINTS)
    wanted = {rel for rel, src in sources.items()
              if rel.startswith(("agents/core/llm/", *PROVIDER_ROOTS)) or any(h in src for h in hints)}
    modules: dict[str, _Module] = {}
    while True:
        modules.update({rel: _Module(rel, sources[rel]) for rel in wanted - modules.keys()})
        bindings = _bind_all(modules, repo_modules)
        bound = {name for b in bindings.values() for name, (kind, _) in b.names.items()
                 if kind in (_CTOR, _HELPER)}
        if not bound:
            break
        named = re.compile(r"\b(?:" + "|".join(map(re.escape, sorted(bound))) + r")\b")
        more = {rel for rel, src in sources.items() if rel not in modules and named.search(src)}
        if not more:
            break
        wanted |= more
    in_scope: dict[str, list[tuple[str, int, str]]] = {}
    outside: dict[str, list[tuple[str, int, str]]] = {}
    provider_modules = {rel for rel, m in modules.items() if _is_provider_module(m)}
    for rel, module in modules.items():
        # A module with no httpx-bound name and no raw-send text has nothing to find.
        if not bindings[rel].exported() and not any(s in module.source for s in _RAW_SENDS):
            continue
        scanner = _Scanner(bindings[rel])
        scanner.visit(module.tree)
        if scanner.findings:
            (in_scope if rel in provider_modules else outside)[rel] = scanner.findings
    return in_scope, outside, provider_modules


_SCAN = None


def _scan():
    global _SCAN
    if _SCAN is None:
        _SCAN = _scan_repo()
    return _SCAN


# ── the rule ─────────────────────────────────────────────────────────────────

def test_no_prompt_carrying_module_dials_a_bare_httpx_client():
    in_scope, _, _ = _scan()
    offenders = [f"{rel}:{line} {qual} — {shape}"
                 for rel, findings in in_scope.items()
                 for qual, line, shape in findings
                 if (rel, qual) not in PROMPT_SCOPE_ALLOWLIST]
    assert offenders == [], (
        "a prompt-carrying module reaches the network without the egress ledger; build "
        "the client with agents.core.llm.egress.llm_async_client (or the admitted native "
        "transport), or add a justified PROMPT_SCOPE_ALLOWLIST entry:\n" + "\n".join(offenders))


def test_every_bare_client_outside_the_scope_is_classified():
    """A provider cannot dodge the rule by living outside llm/, nor by being added to a
    module already classified for something else: an unclassified (module, function)
    with a bare client fails until someone says why it is not a model provider."""
    _, outside, _ = _scan()
    unclassified = [f"{rel}:{line} {qual} — {shape}"
                    for rel, findings in outside.items()
                    for qual, line, shape in findings
                    if qual not in NOT_A_MODEL_PROVIDER.get(rel, ("", frozenset()))[1]]
    assert unclassified == [], (
        "a module outside the prompt-carrying scope dials a bare httpx client; if it "
        "carries a prompt, route it through llm_async_client; otherwise classify that "
        "function in NOT_A_MODEL_PROVIDER with what it talks to:\n" + "\n".join(unclassified))


def test_every_exemption_is_still_needed_and_justified():
    in_scope, outside, provider_modules = _scan()
    used = {(rel, qual) for rel, findings in in_scope.items() for qual, _, _ in findings}
    stale = sorted(set(PROMPT_SCOPE_ALLOWLIST) - used)
    assert stale == [], f"allowlist entries that no longer match a bare client: {stale}"
    seen = {(rel, qual) for rel, findings in outside.items() for qual, _, _ in findings}
    classified = {(rel, qual) for rel, (_, quals) in NOT_A_MODEL_PROVIDER.items() for qual in quals}
    stale_classified = sorted(classified - seen)
    assert stale_classified == [], f"classified functions with no bare client left: {stale_classified}"
    misfiled = sorted(set(NOT_A_MODEL_PROVIDER) & provider_modules)
    assert misfiled == [], f"a provider module cannot be classified as not-a-provider: {misfiled}"
    reasons = [*PROMPT_SCOPE_ALLOWLIST.items(),
               *((rel, why) for rel, (why, _) in NOT_A_MODEL_PROVIDER.items())]
    for key, why in reasons:
        assert isinstance(why, str) and len(why.strip()) >= 30, f"{key} needs a real reason"


_OTHER_HTTP_STACKS = ("requests", "aiohttp", "urllib.request", "urllib3", "http.client",
                      "httpcore", "websockets")


def test_no_provider_module_switches_to_another_http_stack():
    """The httpx rule cannot be dodged by dialling with a different library. (httpcore is
    imported by the admitted transports for TYPE IDENTITY checks only, never to send.)"""
    identity_only = {"agents/core/llm/direct_transport.py",
                     "agents/core/llm/providers/native_transport.py",
                     "agents/core/llm/providers/custom_runtime.py",
                     "agents/core/ingestion/embedding_policy.py"}
    _, _, provider_modules = _scan()
    offenders = []
    for rel in sorted(provider_modules):
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] if isinstance(node, ast.ImportFrom) and not node.level
                     else [])
            for name in names:
                if name.startswith(_OTHER_HTTP_STACKS) and not (
                        name == "httpcore" and rel in identity_only):
                    offenders.append(f"{rel}:{node.lineno} imports {name}")
    assert offenders == [], "\n".join(offenders)


def test_the_scope_covers_the_model_providers():
    _, _, provider_modules = _scan()
    expected = {
        "agents/core/llm/anthropic.py", "agents/core/llm/gemini.py", "agents/core/llm/openrouter.py",
        "agents/core/llm/base.py", "agents/core/llm/xai.py", "agents/core/llm/deepinfra.py",
        "agents/core/llm/nous_auth.py", "agents/core/llm/nous_models.py",
        "agents/core/llm/provider_probe.py", "agents/core/llm/vlm.py",
        "agents/core/llm/providers/native_transport.py", "agents/core/llm/providers/custom_runtime.py",
        "agents/core/ingestion/embedder.py", "agents/core/video_analysis.py",
        "agents/core/autonomy/approval_judge.py", "agents/core/workspace/llm.py",
        "agents/core/media_backends/comfyui.py", "agents/core/media_backends/local_openai_image.py",
    }
    assert expected <= provider_modules, sorted(expected - provider_modules)
    assert sum(m.startswith("agents/core/llm/") for m in provider_modules) >= 60


# ── the scanner itself ───────────────────────────────────────────────────────

_BYPASSES = {
    "direct": "import httpx\nasync def f():\n    return httpx.AsyncClient(timeout=3)\n",
    "sync": "import httpx\ndef f():\n    return httpx.Client()\n",
    "module alias": "import httpx as h\ndef f():\n    return h.AsyncClient()\n",
    "from-import": "from httpx import AsyncClient\ndef f():\n    return AsyncClient()\n",
    "from-import alias": "from httpx import Client as C\ndef f():\n    return C()\n",
    "star import": "from httpx import *\ndef f():\n    return AsyncClient()\n",
    "local import": "def f():\n    from httpx import AsyncClient\n    return AsyncClient()\n",
    "private submodule": "import httpx\ndef f():\n    return httpx._client.AsyncClient()\n",
    "submodule import": "import httpx._client as hc\ndef f():\n    return hc.AsyncClient()\n",
    "from submodule": "from httpx._client import AsyncClient\ndef f():\n    return AsyncClient()\n",
    "from package submodule": "from httpx import _client\ndef f():\n    return _client.AsyncClient()\n",
    "helper": "import httpx\ndef f(u):\n    return httpx.post(u, json={})\n",
    "stream helper": "import httpx\ndef f(u):\n    return httpx.stream('POST', u)\n",
    "private helper": "import httpx\ndef f(u):\n    return httpx._api.post(u)\n",
    "helper alias": "import httpx\nsend = httpx.post\ndef f(u):\n    return send(u)\n",
    "helper handed on": "import functools, httpx\ng = functools.partial(httpx.get, timeout=1)\n",
    "assigned alias": "import httpx\nMake = httpx.AsyncClient\ndef f():\n    return Make()\n",
    "alias of alias": "import httpx\nA = httpx.AsyncClient\nB = A\ndef f():\n    return B()\n",
    "partial": "import functools, httpx\nf = functools.partial(httpx.AsyncClient, timeout=1)\n",
    "factory kwarg": "import httpx\ndef f(build):\n    return build(factory=httpx.AsyncClient)\n",
    "subclass": "import httpx\nclass Mine(httpx.AsyncClient):\n    pass\n",
    "class attribute": ("import httpx\nclass B:\n    _client_cls = httpx.AsyncClient\n"
                        "    def __init__(self):\n        self.client = self._client_cls()\n"),
    "instance attribute": ("import httpx\nclass B:\n    def __init__(self):\n"
                           "        self.cls = httpx.AsyncClient\n"),
    "default parameter": ("import httpx\nclass B:\n    def __init__(self, factory=httpx.AsyncClient):\n"
                          "        self.c = factory()\n"),
    "keyword-only default": ("import httpx\ndef f(*, factory=httpx.Client):\n"
                             "    return factory()\n"),
    "annotated default": ("import httpx\ndef f(factory: type[httpx.AsyncClient] = httpx.AsyncClient):\n"
                          "    return factory()\n"),
    "tuple assignment": "import httpx\nA, B = httpx.AsyncClient, 1\ndef f():\n    return A()\n",
    "annotated assignment": "import httpx\nA: type = httpx.AsyncClient\ndef f():\n    return A()\n",
    "walrus": "import httpx\ndef f():\n    return (c := httpx.AsyncClient)()\n",
    "returned constructor": "import httpx\ndef ctor():\n    return httpx.AsyncClient\n",
    "conditional expression": "import httpx\ndef f(x):\n    return (httpx.AsyncClient if x else None)()\n",
    "dict entry": "import httpx\nFACTORIES = {'cloud': httpx.AsyncClient}\n",
    "list entry": "import httpx\nFACTORIES = [httpx.AsyncClient]\n",
    "lambda": "import httpx\nmake = lambda: httpx.AsyncClient\n",
    "explicit __new__": ("import httpx\ndef f():\n    c = httpx.AsyncClient.__new__(object)\n"
                         "    httpx.Client.__init__(c)\n    return c\n"),
    "class patch": "import httpx\nhttpx.AsyncClient._send_single_request = lambda *a: None\n",
    "private send": "async def f(client, req):\n    return await client._send_single_request(req)\n",
    "module handed on": "import httpx\ndef f():\n    return getattr(httpx, 'AsyncClient')()\n",
    "module object": "import httpx\nmod = httpx\n",
    "dynamic import": "import importlib\ndef f():\n    return importlib.import_module('httpx').AsyncClient()\n",
    "rebinding": "import httpx\nhttpx.AsyncClient = object\n",
    "raw transport": ("import httpx\nasync def f(req):\n"
                      "    return await httpx.AsyncHTTPTransport().handle_async_request(req)\n"),
    "raw send uncalled": ("import httpx\nasync def f(req):\n"
                          "    send = httpx.AsyncHTTPTransport().handle_async_request\n"
                          "    return await send(req)\n"),
    "raw send by name": ("async def f(t, req):\n"
                         "    return await getattr(t, 'handle_async_request')(req)\n"),
}

_SAFE = (
    "from agents.core.llm.egress import llm_async_client\n"
    "import httpx\n"
    "from httpx import AsyncClient\n"
    "from typing import TypeVar, cast\n"
    "C = TypeVar('C', bound=httpx.AsyncClient)\n"
    "SLOT: httpx.AsyncClient | None = None\n"
    "def f(c: httpx.AsyncClient, k: type[httpx.Client] | None = None,\n"
    "      d: dict[str, AsyncClient] | None = None) -> httpx.AsyncClient:\n"
    "    assert isinstance(c, httpx.AsyncClient) and type(c) is httpx.AsyncClient\n"
    "    assert isinstance(c, (httpx.AsyncClient, httpx.Client)) and type(c) in (AsyncClient,)\n"
    "    assert issubclass(type(c), httpx.Client) or c.__class__ == httpx.AsyncClient\n"
    "    assert type(c)._transport_for_url is httpx.AsyncClient._transport_for_url\n"
    "    original = httpx.AsyncClient.send\n"
    "    cast(httpx.AsyncClient, c)\n"
    "    try:\n"
    "        timeout = httpx.Timeout(3)\n"
    "    except httpx.HTTPError:\n"
    "        pass\n"
    "    return llm_async_client('anthropic', timeout=timeout,\n"
    "                            transport=httpx.MockTransport(lambda r: None))\n"
    "class T(httpx.AsyncBaseTransport):\n"
    "    async def handle_async_request(self, request):\n"
    "        return await self.inner.handle_async_request(request)\n"
)


def test_the_scanner_catches_every_bypass_shape():
    for name, source in _BYPASSES.items():
        assert scan_source(source), f"the scanner misses the {name!r} shape"
    assert scan_source(_SAFE) == []


def test_a_re_export_through_another_repo_module_is_caught():
    """`from httpx import AsyncClient` in one module and `from that_module import
    AsyncClient` in a provider: the provider's call is found, at any depth of re-export
    (absolute, relative and module-attribute forms)."""
    findings = scan_modules({
        "agents/core/compat_http.py": "from httpx import AsyncClient\n",
        "agents/core/compat_again.py": "from .compat_http import AsyncClient as Ctor\n",
        "agents/core/llm/p1.py": ("from agents.core.compat_http import AsyncClient\n"
                                  "def f():\n    return AsyncClient()\n"),
        "agents/core/llm/p2.py": ("from ..compat_again import Ctor\n"
                                  "def f():\n    return Ctor()\n"),
        "agents/core/llm/p3.py": ("from agents.core import compat_http\n"
                                  "def f():\n    return compat_http.AsyncClient()\n"),
        "agents/core/llm/p4.py": ("import agents.core.compat_http\n"
                                  "def f():\n    return agents.core.compat_http.AsyncClient()\n"),
        "agents/core/llm/p5.py": ("from agents.core.llm import egress\n"
                                  "def f():\n    return egress.httpx.AsyncClient()\n"),
        "agents/core/llm/egress.py": "import httpx\n",
    })
    for rel in ("p1", "p2", "p3", "p4", "p5"):
        assert findings[f"agents/core/llm/{rel}.py"] == [("f", 3, "builds a bare httpx client")], rel
    assert findings["agents/core/compat_http.py"] == []   # an import alone sends nothing


def _mutated(rel: str, old: str, new: str) -> list[tuple[str, int, str]]:
    source = (REPO / rel).read_text(encoding="utf-8")
    assert old in source, f"{rel} no longer has {old!r}; update this mutation"
    return scan_source(source.replace(old, new), rel)


def test_reverting_a_real_backend_to_a_bare_client_is_caught():
    """The pre-DRA-23 shape, applied to the real Claude backend source."""
    findings = _mutated("agents/core/llm/anthropic.py", 'llm_async_client("anthropic", timeout=120.0)',
                        "httpx.AsyncClient(timeout=120.0)")
    assert [(q, s) for q, _, s in findings] == [("ClaudeBackend.__init__", "builds a bare httpx client")]
    assert ("agents/core/llm/anthropic.py", "ClaudeBackend.__init__") not in PROMPT_SCOPE_ALLOWLIST


def test_a_real_cloud_backend_hiding_the_constructor_is_caught():
    """The round-1 review's mutation, on the real xAI backend: the constructor held as a
    class attribute (or a default parameter) and called through ``self``. The old
    call-site scanner passed both; the xAI prompt path then skipped the ledger, the
    host-protocol check and the data-handling gate."""
    rel = "agents/core/llm/xai.py"
    ledgered = ("self.client = llm_async_client('xai', timeout=TIMEOUT, transport=transport,\n"
                "                                          follow_redirects=False, trust_env=False)")
    hidden = ("self.client = self._client_cls(timeout=TIMEOUT, transport=transport,\n"
              "                                          follow_redirects=False, trust_env=False)")
    source = (REPO / rel).read_text(encoding="utf-8")
    for anchor in (ledgered, "class XAIBackend(ResponsesBackend):\n",
                   "transport=None, profile=None, model=None):"):
        assert anchor in source, f"{rel} changed; update this mutation ({anchor!r})"
    assert scan_source(source, rel) == []
    as_class_attribute = source.replace(ledgered, hidden).replace(
        "class XAIBackend(ResponsesBackend):\n",
        "class XAIBackend(ResponsesBackend):\n    _client_cls = httpx.AsyncClient\n")
    findings = scan_source(as_class_attribute, rel)
    assert [q for q, _, _ in findings] == ["XAIBackend"], findings
    assert (rel, "XAIBackend") not in PROMPT_SCOPE_ALLOWLIST

    as_default = source.replace(ledgered, hidden.replace("self._client_cls", "client_cls")).replace(
        "transport=None, profile=None, model=None):",
        "transport=None, profile=None, model=None, client_cls=httpx.AsyncClient):")
    findings = scan_source(as_default, rel)
    assert [q for q, _, _ in findings] == ["XAIBackend.__init__"], findings
    assert (rel, "XAIBackend.__init__") not in PROMPT_SCOPE_ALLOWLIST


def test_a_new_client_in_a_classified_module_is_not_covered_by_its_classification():
    """Round 1 classified whole modules, so a prompt-carrying client added anywhere in
    routers/admin.py or voice/tts.py passed. Classification is per function now."""
    rel = "agents/core/routers/admin.py"
    source = (REPO / rel).read_text(encoding="utf-8") + (
        "\n\nasync def _new_cloud_probe(prompt):\n"
        "    async with httpx.AsyncClient() as client:\n"
        "        return await client.post('https://api.example.test/v1', json={'prompt': prompt})\n")
    findings = scan_source(source, rel)
    uncovered = [qual for qual, _, _ in findings if qual not in NOT_A_MODEL_PROVIDER[rel][1]]
    assert uncovered == ["_new_cloud_probe"], findings
