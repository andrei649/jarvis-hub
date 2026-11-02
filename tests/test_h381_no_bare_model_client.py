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

This is the structural rule. Every ``*.py`` under ``agents/`` is parsed, and every way
of reaching the network without the ledgered constructor is found:

* a call to ``httpx.AsyncClient`` / ``httpx.Client`` (any alias of the module, any name
  imported from it, any local name assigned from it);
* a module-level request helper (``httpx.get``, ``httpx.post``, ``httpx.stream`` …),
  which builds a bare client internally;
* the constructor handed on uncalled (``partial(httpx.AsyncClient, …)``,
  ``factory=httpx.AsyncClient``) or subclassed;
* a raw ``transport.handle_async_request(...)`` outside an ``httpx`` transport class
  (a transport mounted on a ledgered client is the only place a raw send is admitted).

A finding in the **prompt-carrying scope** — ``agents/core/llm/**`` plus every provider
module (any module that builds model clients through the ledgered constructor, the
admitted native transport or the direct-transport proof, and the provider roots named
below) — fails unless its exact ``(file, enclosing function)`` is on
:data:`PROMPT_SCOPE_ALLOWLIST` with a reason. A finding anywhere else fails unless its
module is classified in :data:`NOT_A_MODEL_PROVIDER`, so a provider written somewhere new
cannot slip past the scope by living outside ``llm/``.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
AGENTS = REPO / "agents"

_CONSTRUCTORS = frozenset({"AsyncClient", "Client"})
_HELPERS = frozenset({"get", "post", "put", "patch", "delete", "head", "options",
                      "request", "stream"})
_TRANSPORT_BASES = frozenset({"AsyncBaseTransport", "BaseTransport"})
_RAW_SENDS = frozenset({"handle_async_request", "handle_request"})
_LEDGER_MARKERS = frozenset({"llm_async_client", "llm_sync_client", "llm_sync_request_hook",
                             "native_admitted_client", "require_direct_async_transport",
                             "custom_client"})

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
# none of them sends a model prompt. Module path -> what the client talks to.
NOT_A_MODEL_PROVIDER: dict[str, str] = {
    "agents/core/http_client.py":
        "the plugin egress choke point itself; every request it sends is recorded in the "
        "same ledger under the plugin's row (cloud image providers dial through it)",
    "agents/core/channels/telegram.py":
        "Telegram Bot API channel transport (messages to/from the owner's chat)",
    "agents/core/cameras/frigate.py": "Frigate NVR API on the owner's LAN",
    "agents/core/house/home_assistant.py": "Home Assistant REST API on the owner's LAN",
    "agents/core/house/wled.py": "WLED light controller JSON API on the LAN",
    "agents/core/memory/graph.py": "Neo4j HTTP transaction endpoint (graph database)",
    "agents/core/memory/qdrant_store.py": "Qdrant vector database REST API",
    "agents/core/skills/importer.py": "skill source fetch from GitHub/registries (no prompt)",
    "agents/core/voice/tts.py":
        "speech synthesis of reply text, not a model prompt; its cloud vendors are a "
        "recorded, separate ledger gap (GET /api/admin/network/calls docstring)",
    "agents/core/routers/admin.py":
        "POST /api/admin/llm/test: header-less GET of the fixed localhost LM Studio "
        "/v1/models and Ollama /api/tags URLs (no prompt)",
}


def _attr_chain(node: ast.AST) -> list[str]:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return parts[::-1]
    return []


class _Scanner(ast.NodeVisitor):
    """Collect (qualname, line, shape) for every bare-client path in one module."""

    def __init__(self) -> None:
        self.httpx_names: set[str] = set()
        self.ctor_names: set[str] = set()      # names bound to AsyncClient/Client
        self.helper_names: set[str] = set()    # names bound to httpx.get/post/...
        self.findings: list[tuple[str, int, str]] = []
        self._scope: list[str] = []
        self._classes: list[bool] = []         # is the enclosing class an httpx transport?

    # ── bindings ─────────────────────────────────────────────────────────────
    def collect(self, tree: ast.AST) -> None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "httpx":
                        self.httpx_names.add(alias.asname or "httpx")
            elif isinstance(node, ast.ImportFrom) and node.module == "httpx":
                for alias in node.names:
                    if alias.name in _CONSTRUCTORS:
                        self.ctor_names.add(alias.asname or alias.name)
                    elif alias.name in _HELPERS:
                        self.helper_names.add(alias.asname or alias.name)
        # Second pass: plain aliases (`Client = httpx.AsyncClient`).
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and self._is_ctor_ref(node.value):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.ctor_names.add(target.id)

    def _is_ctor_ref(self, node: ast.AST) -> bool:
        chain = _attr_chain(node)
        if len(chain) == 2 and chain[0] in self.httpx_names and chain[1] in _CONSTRUCTORS:
            return True
        return isinstance(node, ast.Name) and node.id in self.ctor_names

    def _is_helper_ref(self, node: ast.AST) -> bool:
        chain = _attr_chain(node)
        if len(chain) == 2 and chain[0] in self.httpx_names and chain[1] in _HELPERS:
            return True
        return isinstance(node, ast.Name) and node.id in self.helper_names

    # ── scopes ───────────────────────────────────────────────────────────────
    def _qual(self) -> str:
        return ".".join(self._scope) or "<module>"

    def _hit(self, node: ast.AST, shape: str) -> None:
        self.findings.append((self._qual(), getattr(node, "lineno", 0), shape))

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for base in node.bases:
            if self._is_ctor_ref(base):
                self._hit(node, "subclasses the bare client")
        is_transport = any(_attr_chain(b)[-1:] and _attr_chain(b)[-1] in _TRANSPORT_BASES
                           for b in node.bases)
        self._scope.append(node.name)
        self._classes.append(is_transport)
        self.generic_visit(node)
        self._classes.pop()
        self._scope.pop()

    def _visit_function(self, node) -> None:
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if self._is_ctor_ref(func):
            self._hit(node, "builds a bare httpx client")
        elif self._is_helper_ref(func):
            self._hit(node, "uses a module-level httpx request helper")
        elif (isinstance(func, ast.Attribute) and func.attr in _RAW_SENDS
              and not (self._classes and self._classes[-1])):
            self._hit(node, "sends through a raw transport outside a transport class")
        identity_check = isinstance(func, ast.Name) and func.id in {"isinstance", "issubclass", "type"}
        if not identity_check:
            for value in [*node.args, *(k.value for k in node.keywords)]:
                if self._is_ctor_ref(value):
                    self._hit(node, "hands the bare client constructor on uncalled")
        self.generic_visit(node)


def scan_tree(tree: ast.AST) -> list[tuple[str, int, str]]:
    scanner = _Scanner()
    scanner.collect(tree)
    scanner.visit(tree)
    return scanner.findings


def scan_source(source: str) -> list[tuple[str, int, str]]:
    return scan_tree(ast.parse(source))


def _rel(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def _modules() -> list[Path]:
    return sorted(p for p in AGENTS.rglob("*.py")
                  if "__pycache__" not in p.parts and not _rel(p).startswith("agents/web/"))


_PROVIDER_IMPORT_HINTS = ("egress", "direct_transport", "native_transport", "custom_runtime",
                          *_LEDGER_MARKERS)


def _is_provider_module(rel: str, tree: ast.AST | None) -> bool:
    if rel.startswith("agents/core/llm/") or rel.startswith(PROVIDER_ROOTS):
        return True
    if tree is None:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if (module.endswith(("llm.egress", "llm.direct_transport",
                                 "providers.native_transport", "providers.custom_runtime"))
                    or (node.level and module in {"egress", "direct_transport"})):
                return True
            if any(alias.name in _LEDGER_MARKERS for alias in node.names):
                return True
    return False


def _scan_repo():
    in_scope: dict[str, list[tuple[str, int, str]]] = {}
    outside: dict[str, list[tuple[str, int, str]]] = {}
    provider_modules: set[str] = set()
    for path in _modules():
        source = path.read_text(encoding="utf-8")
        rel = _rel(path)
        # Parse only what can matter: a module that names httpx (a finding) or one of the
        # ledgered entry points (a provider). Everything else has neither by construction.
        relevant = "httpx" in source or any(hint in source for hint in _PROVIDER_IMPORT_HINTS)
        tree = ast.parse(source) if relevant else None
        provider = _is_provider_module(rel, tree)
        if provider:
            provider_modules.add(rel)
        if tree is None or "httpx" not in source:
            continue
        findings = scan_tree(tree)
        if findings:
            (in_scope if provider else outside)[rel] = findings
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
    """A provider cannot dodge the rule by living outside llm/: an unclassified module
    with a bare client fails until someone says why it is not a model provider."""
    _, outside, _ = _scan()
    unclassified = [f"{rel}:{line} {qual} — {shape}"
                    for rel, findings in outside.items()
                    for qual, line, shape in findings
                    if rel not in NOT_A_MODEL_PROVIDER]
    assert unclassified == [], (
        "a module outside the prompt-carrying scope dials a bare httpx client; if it "
        "carries a prompt, route it through llm_async_client; otherwise classify it in "
        "NOT_A_MODEL_PROVIDER with what it talks to:\n" + "\n".join(unclassified))


def test_every_exemption_is_still_needed_and_justified():
    in_scope, outside, provider_modules = _scan()
    used = {(rel, qual) for rel, findings in in_scope.items() for qual, _, _ in findings}
    stale = sorted(set(PROMPT_SCOPE_ALLOWLIST) - used)
    assert stale == [], f"allowlist entries that no longer match a bare client: {stale}"
    stale_modules = sorted(set(NOT_A_MODEL_PROVIDER) - set(outside))
    assert stale_modules == [], f"classified modules with no bare client left: {stale_modules}"
    misfiled = sorted(set(NOT_A_MODEL_PROVIDER) & provider_modules)
    assert misfiled == [], f"a provider module cannot be classified as not-a-provider: {misfiled}"
    for key, why in [*PROMPT_SCOPE_ALLOWLIST.items(), *NOT_A_MODEL_PROVIDER.items()]:
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
    "helper": "import httpx\ndef f(u):\n    return httpx.post(u, json={})\n",
    "stream helper": "import httpx\ndef f(u):\n    return httpx.stream('POST', u)\n",
    "assigned alias": "import httpx\nMake = httpx.AsyncClient\ndef f():\n    return Make()\n",
    "partial": "import functools, httpx\nf = functools.partial(httpx.AsyncClient, timeout=1)\n",
    "factory kwarg": "import httpx\ndef f(build):\n    return build(factory=httpx.AsyncClient)\n",
    "subclass": "import httpx\nclass Mine(httpx.AsyncClient):\n    pass\n",
    "raw transport": ("import httpx\nasync def f(req):\n"
                      "    return await httpx.AsyncHTTPTransport().handle_async_request(req)\n"),
}

_SAFE = (
    "from agents.core.llm.egress import llm_async_client\n"
    "import httpx\n"
    "def f(c: httpx.AsyncClient) -> httpx.AsyncClient:\n"
    "    assert isinstance(c, httpx.AsyncClient) and type(c) is httpx.AsyncClient\n"
    "    return llm_async_client('anthropic', transport=httpx.MockTransport(lambda r: None))\n"
    "class T(httpx.AsyncBaseTransport):\n"
    "    async def handle_async_request(self, request):\n"
    "        return await self.inner.handle_async_request(request)\n"
)


def test_the_scanner_catches_every_bypass_shape():
    for name, source in _BYPASSES.items():
        assert scan_source(source), f"the scanner misses the {name!r} shape"
    assert scan_source(_SAFE) == []


def test_reverting_a_real_backend_to_a_bare_client_is_caught():
    """The pre-DRA-23 shape, applied to the real Claude backend source."""
    source = (REPO / "agents/core/llm/anthropic.py").read_text(encoding="utf-8")
    ledgered = 'llm_async_client("anthropic", timeout=120.0)'
    assert ledgered in source
    findings = scan_source(source.replace(ledgered, "httpx.AsyncClient(timeout=120.0)"))
    assert [(q, s) for q, _, s in findings] == [("ClaudeBackend.__init__", "builds a bare httpx client")]
    assert ("agents/core/llm/anthropic.py", "ClaudeBackend.__init__") not in PROMPT_SCOPE_ALLOWLIST
