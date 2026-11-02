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

**Model SDKs are bare clients one call removed** (round-2 review): ``ollama.Client``
"creates a httpx client" from its own kwargs, ``openai.AsyncOpenAI`` /
``anthropic.AsyncAnthropic`` / ``google.genai.Client`` build ``httpx`` clients unless
handed one, and ``ollama.embed`` / ``openai.chat`` send through a module-level client
built without any hook. So every read of a constructor in :data:`_MODEL_SDKS` (same alias,
re-export and type-position rules) is a finding unless it is a call whose keywords hand the
SDK a ledgered client — a call of ``llm_async_client`` / ``llm_sync_client`` /
``native_admitted_client`` / ``custom_client`` imported from the ledger modules, or a name
only ever bound to one — or, for ollama, whose kwargs go straight to ``httpx.Client``,
``event_hooks={"request": [llm_sync_request_hook(...)]}``. Every read of an SDK's
module-level members (its module client) is a finding, a module importing a model SDK is a
provider module wherever it lives, and a model SDK that does not dial through httpx at all
counts as another HTTP stack.

**A bare client is followed out of the code that builds it** (round-3 review): a repo
function or method that returns or yields one — directly, in a tuple, through a local or a
``self`` attribute, from a ``with`` block, wrapped in a class/``dict``/``partial``, or as
another factory's client — is itself a constructor. Every call or uncalled read of it,
through any alias, re-export or module attribute, is a finding in the caller (in-class
callers included), so each caller needs its own exemption and no allowlist reason can rest
on "the callers behave". A factory method is matched by name (``._http_client``,
``._get_client``, ``._pinned_client`` …, as an attribute or through ``getattr``) unless it
is the reading class's own non-factory member; a private attribute a class keeps a bare
client in (``._client``) is a finding read off another object or inherited by a subclass;
a class whose construction leaves a bare client on the instance (or whose body holds one)
is a finding wherever it is built or subclassed; a module global holding one wherever it is
read. Stated limit: a *public* attribute holding a bare client (``TelegramChannel.client``)
is followed only through that construction gate — ``backend.client`` is the ledgered client
of every LLM backend, and the scanner has no types.

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
        "the loopback Ollama client for tags/pull/delete, loopback enforced in code at the "
        "factory: a non-loopback URL raises OllamaURLNotLoopback, and its request hook refuses "
        "any non-loopback destination (an absolute URL included) before transport entry "
        "(test_the_model_setup_factory_refuses_every_non_loopback_destination)",
    # Every caller of a bare-client factory is checked too, not only the factory.
    ("agents/core/llm/model_setup.py", "ollama_present"):
        "GET /api/tags on the loopback Ollama through _client (header-less, model names "
        "back); refuses a non-loopback URL first; no prompt, image or credential",
    ("agents/core/llm/model_setup.py", "ollama_pull"):
        "POST /api/pull {model, stream} on the loopback Ollama through _client: the body is a "
        "validated model tag (valid_model_tag), never a prompt; Action-Kernel gated pull",
    ("agents/core/llm/model_setup.py", "ollama_delete"):
        "DELETE /api/delete {model} on the loopback Ollama through _client (the pull's "
        "compensate rollback): a validated model tag, never a prompt",
    ("agents/core/llm/ollama_control.py", "OllamaController._http_client"):
        "the Ollama control-plane client on the configured server (default loopback); it is "
        "reached only by the three callers below, each one checked by this rule",
    ("agents/core/llm/ollama_control.py", "OllamaController.load_model"):
        "POST /api/generate {model, prompt: \"\", keep_alive: -1}: loads a validated model id "
        "with an EMPTY prompt (permission gate + Action-Kernel contract first); no content",
    ("agents/core/llm/ollama_control.py", "OllamaController.unload_model"):
        "POST /api/generate {model, prompt: \"\", keep_alive: 0}: unloads validated model ids "
        "with an EMPTY prompt (permission gate + Action-Kernel contract first); no content",
    ("agents/core/llm/ollama_control.py", "OllamaController._active_models"):
        "header-less GET /api/ps (resident model names) for unload_model; no prompt or content",
    ("agents/core/ingestion/embedder.py", "Embedder._policy_client"):
        "reads ollama.Client's own httpx client (ollama.Client._client), which Embedder._setup "
        "built with the ledger request hook, only to describe the embedding data-handling "
        "target; it sends nothing",
    ("agents/core/ingestion/embedder.py", "Embedder._embed_resilient"):
        "reads the same ledger-hooked ollama.Client._client to open the embedding policy "
        "request scope around the SDK's own send; the request still runs that client's "
        "ledger hook",
    ("agents/core/video_analysis.py", "VideoHTTPClient._pinned_client"):
        "extends PluginHTTPClient._pinned_client (super()) to add the current-approval and "
        "no-credential request hook; the pinned client is only sent through by "
        "PluginHTTPClient._request_pinned/stream after _guard records the plugin egress row",
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
        frozenset({"PluginHTTPClient._get_client", "PluginHTTPClient._pinned_client",
                   # the only senders through _pinned_client, each after _guard records
                   "PluginHTTPClient._request_pinned", "PluginHTTPClient.stream"})),
    "agents/core/acquisition/research.py": (
        "reads WebSearchPlugin._client, which is the plugin's PluginHTTPClient (the plugin "
        "egress choke point, every request recorded under the plugin row), not a bare client",
        frozenset({"WebSearchResearchBackend.__init__"})),
    "agents/core/memory/manager.py": (
        "constructs the Qdrant vector store (Qdrant REST API, memory vectors) for the memory "
        "manager; no model prompt",
        frozenset({"MemoryManager._init_qdrant"})),
    "agents/web.py": (
        "constructs the Telegram channel (Bot API transport to the owner's chat) at hub start",
        frozenset({"lifespan"})),
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

# The ledger's own constructors and hook, by the module that defines them. Only a name
# that resolves here counts as ledgered (a local function of the same name does not).
_LEDGER_SOURCES = {
    "agents.core.llm.egress": frozenset({"llm_async_client", "llm_sync_client",
                                         "llm_sync_request_hook"}),
    "agents.core.llm.providers.native_transport": frozenset({"native_admitted_client"}),
    "agents.core.llm.providers.custom_runtime": frozenset({"custom_client"}),
}
_LEDGER_CLIENTS = frozenset({"llm_async_client", "llm_sync_client", "native_admitted_client",
                             "custom_client"})
_LEDGER_HOOKS = frozenset({"llm_sync_request_hook"})

# Model SDKs that build their own httpx client. Package -> constructor -> the keyword paths
# that must ALL carry a ledgered client for a call to be clean (a path ending in
# ``event_hooks`` must carry the ledger's request hook instead: ollama hands its kwargs
# straight to ``httpx.Client``). ``None``: no ledgered form exists, every read is a finding
# — ollama's AsyncClient would need an async hook (``llm_sync_request_hook`` is sync), and
# the ``Default*Client`` helpers are httpx clients with the SDK's defaults.
_HTTP_CLIENT = (("http_client",),)
_SDK_DEFAULT_CLIENTS = dict.fromkeys(("DefaultHttpxClient", "DefaultAsyncHttpxClient",
                                      "DefaultAioHttpClient"))
_MODEL_SDKS: dict[str, dict[str, tuple[tuple[str, ...], ...] | None]] = {
    "ollama": {"Client": (("event_hooks",),), "AsyncClient": None},
    "openai": {**dict.fromkeys(("OpenAI", "AsyncOpenAI", "AzureOpenAI", "AsyncAzureOpenAI",
                                "Client", "AsyncClient"), _HTTP_CLIENT), **_SDK_DEFAULT_CLIENTS},
    "anthropic": {**dict.fromkeys(("Anthropic", "AsyncAnthropic", "AnthropicBedrock",
                                   "AsyncAnthropicBedrock", "AnthropicVertex",
                                   "AsyncAnthropicVertex", "Client", "AsyncClient"), _HTTP_CLIENT),
                  **_SDK_DEFAULT_CLIENTS},
    "groq": {**dict.fromkeys(("Groq", "AsyncGroq", "Client", "AsyncClient"), _HTTP_CLIENT),
             **_SDK_DEFAULT_CLIENTS},
    "mistralai": {"Mistral": (("client",), ("async_client",))},
    "cohere": dict.fromkeys(("Client", "ClientV2", "AsyncClient", "AsyncClientV2"),
                            (("httpx_client",),)),
    "google.genai": {"Client": (("http_options", "httpx_client"),
                                ("http_options", "httpx_async_client"))},
}
# Lowercase package members that are type/error namespaces, not a module-level client.
_SDK_INERT = frozenset({"types", "errors", "pagination", "version"})
# Model SDKs that do not dial through httpx (gRPC, google-api-core): no ledger hook can be
# hung on them, so they are another HTTP stack for a provider module.
_UNLEDGERED_MODEL_SDKS = ("google.generativeai", "google.ai.generativelanguage",
                          "google.cloud.aiplatform", "vertexai")

_CTOR, _HELPER, _HTTPX, _REPO = "ctor", "helper", "httpx", "repo"
# Kinds that carry their target in the kind itself (a re-export keeps only the kind):
# "sdk:<module path>" (an SDK package, submodule or module-level member),
# "sdkctor:<package>:<Name>", "ns:<namespace>" (``google`` of ``import google.genai``) and
# "ledger:<function>".
_SDK, _SDK_CTOR, _NS, _LEDGER = "sdk:", "sdkctor:", "ns:", "ledger:"
# A bare client that leaves the code building it (round-3 review) is followed, not just its
# construction. "factory:<rel>:<qualname>" is a repo function or method that returns or
# yields one, or a module global holding one: every non-type read of it is a finding, exactly
# like a constructor's, and its value is a bare client wherever it flows. "holder:<rel>:<qual>"
# is a class whose construction leaves one on the instance (or whose body holds one): building
# or subclassing it is a finding, but the instance is not itself a client (what reaches inside
# it is checked by name). "carrier:<rel>:<qualname>" is a class whose factory methods or
# private client attributes hold one: constructing it and calling its other methods is fine.
_FACTORY, _HOLDER, _CARRIER = "factory:", "holder:", "carrier:"
_SELF = frozenset({"self", "cls"})
# Calls that wrap their arguments into the value they return (a class, ``dict``,
# ``functools.partial``): a bare client handed to one is handed out with it.
_WRAPPERS = frozenset({"dict", "partial"})


def _sdk_root(path: str) -> str | None:
    return next((p for p in _MODEL_SDKS if path == p or path.startswith(p + ".")), None)


def _sdk_member(path: str, name: str) -> str | None:
    """The kind of a name read off a model SDK module (``path`` is the package or a
    submodule): a constructor, a deeper module path (a submodule or a module-level
    member such as ``ollama.chat``), or nothing (a type, an exception, a constant)."""
    root = _sdk_root(path)
    if root is None or name.startswith("__"):
        return None
    if name in _MODEL_SDKS[root]:
        return f"{_SDK_CTOR}{root}:{name}"
    if path == root and name in _SDK_INERT:
        return None
    if name[:1].islower() or name.startswith("_"):
        return f"{_SDK}{path}.{name}"
    return None


def _model_sdk(name: str) -> bool:
    """``name`` is (part of) a model SDK: an httpx-backed one or one no hook can see."""
    return _sdk_root(name) is not None or any(
        name == s or name.startswith(s + ".") for s in _UNLEDGERED_MODEL_SDKS)


def _keyword(node: ast.AST, key: str) -> ast.AST | None:
    """The value a call passes as ``key=`` or a dict literal holds under ``"key"``."""
    if isinstance(node, ast.Call):
        return next((k.value for k in node.keywords if k.arg == key), None)
    if isinstance(node, ast.Dict):
        return next((v for k, v in reversed(list(zip(node.keys, node.values, strict=True)))
                     if isinstance(k, ast.Constant) and k.value == key), None)
    return None


_SDK_UNLEDGERED = ("builds a model SDK client without a ledgered HTTP client "
                   "(the SDK's own httpx client skips the egress ledger)")


def _is_ctor(kind: str) -> bool:
    return kind == _CTOR or kind.startswith(_SDK_CTOR)


def _is_client_path(kind: str) -> bool:
    """A kind whose reads the scanner reports (re-exports of these are followed)."""
    return kind in (_CTOR, _HELPER) or kind.startswith((_SDK_CTOR, _SDK, _FACTORY, _HOLDER, _CARRIER))


def _hands_out_kind(kind: str) -> bool:
    """A resolved reference that is a bare client, or builds one when called."""
    return kind in (_CTOR, _HELPER, _HTTPX) or kind.startswith((_SDK_CTOR, _SDK, _FACTORY))


def _names(quals) -> str:
    return ", ".join(sorted(quals))


class _Facts:
    """Where bare clients leave the code that builds them. Computed from every scanned
    module to a fixed point (a factory that returns another factory's client is one)."""

    def __init__(self, defs=None, methods=None, attrs=None, owners=frozenset()) -> None:
        # rel -> {name bound at module level: factory/holder/carrier kind}
        self.defs: dict[str, dict[str, str]] = defs or {}
        # method name -> {"rel:Class.method"} that return/yield a bare client
        self.methods: dict[str, frozenset[str]] = methods or {}
        # private attribute name -> {"rel:Class"} that store a bare client in it
        self.attrs: dict[str, frozenset[str]] = attrs or {}
        # (rel, Class, attribute): the class stores a bare client in that attribute itself
        self.owners: frozenset[tuple[str, str, str]] = owners

    def __eq__(self, other) -> bool:
        return isinstance(other, _Facts) and (self.defs, self.methods, self.attrs, self.owners) == (
            other.defs, other.methods, other.attrs, other.owners)

    __hash__ = None


_NO_FACTS = _Facts()


def _own_member(module: _Module, facts: _Facts, cls: str | None, recv: ast.AST, attr: str) -> bool:
    """``self.<attr>`` inside a class that assigns that attribute itself, or defines a
    method of that name that is not a bare-client factory: the class's own member."""
    if cls is None or not (isinstance(recv, ast.Name) and recv.id in _SELF):
        return False
    if attr in module.self_attrs.get(cls, ()):
        return True
    return (attr in module.methods.get(cls, ())
            and f"{module.rel}:{cls}.{attr}" not in facts.methods.get(attr, ()))


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
    elif isinstance(node, (ast.With, ast.AsyncWith)):   # `with llm_async_client(…) as http:`
        pairs = [(item.optional_vars, item.context_expr) for item in node.items
                 if item.optional_vars is not None]
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


class _Function:
    """One ``def`` and what its own body (not a nested scope) binds, returns and stores."""

    __slots__ = ("qual", "node", "cls", "method", "local", "returns", "stores")

    def __init__(self, qual: str, node: ast.AST, cls: str | None, method: bool) -> None:
        self.qual, self.node, self.cls, self.method = qual, node, cls, method
        self.local: dict[str, list[ast.AST]] = {}       # local name -> every value bound to it
        self.returns: list[ast.AST] = []                # every returned or yielded value
        self.stores: list[tuple[tuple[str, ...], ast.AST]] = []   # attribute chain <- value


_SCOPES = frozenset({ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda})
_RETURNS = frozenset({ast.Return, ast.Yield, ast.YieldFrom})
_BINDERS = frozenset({ast.Assign, ast.AnnAssign, ast.With, ast.AsyncWith})


class _Module:
    """One parsed module, the statements that can bind a name, and its defs and classes."""

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
        # What a bare client can escape through: defs, classes and module globals.
        self.functions: list[_Function] = []
        self.classes: dict[str, ast.ClassDef] = {}
        self.methods: dict[str, set[str]] = {}              # class -> method names it defines
        self.self_attrs: dict[str, set[str]] = {}           # class -> attributes it assigns on self
        self.self_values: dict[str, dict[tuple[str, ...], list[ast.AST]]] = {}
        self.class_body: dict[str, list[tuple[str, ast.AST]]] = {}
        self.globals = [(t.id, v) for node in self.tree.body for t, v in _assignments(node)
                        if isinstance(t, ast.Name)]
        self._index(self.tree.body, [], None, False)

    def _index(self, body, scope: list[str], cls: str | None, in_class: bool) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = [*scope, node.name]
                self.functions.append(self._function(".".join(qual), node, cls, in_class))
                if in_class:
                    self.methods[cls].add(node.name)
                self._index(node.body, qual, cls, False)
            elif isinstance(node, ast.ClassDef):
                qual = ".".join([*scope, node.name])
                self.classes[qual] = node
                self.methods.setdefault(qual, set())
                self.self_attrs.setdefault(qual, set())
                values = self.self_values.setdefault(qual, {})
                self.class_body[qual] = [(t.id, v) for stmt in node.body
                                         for t, v in _assignments(stmt) if isinstance(t, ast.Name)]
                for name, value in self.class_body[qual]:
                    values.setdefault(("self", name), []).append(value)
                self._index(node.body, [*scope, node.name], qual, True)
            else:
                for field in ("body", "orelse", "finalbody", "handlers", "cases"):
                    self._index(getattr(node, field, ()) or (), scope, cls, in_class)

    def _function(self, qual: str, node: ast.AST, cls: str | None, method: bool) -> _Function:
        fn = _Function(qual, node, cls, method)
        pending = list(node.body)
        while pending:
            child = pending.pop()
            kind = type(child)
            if kind in _RETURNS:
                if child.value is not None:
                    fn.returns.append(child.value)
            elif kind is ast.NamedExpr:
                self._bind(child.target, child.value, fn)
            elif kind in _BINDERS:
                for target, value in _assignments(child):
                    self._bind(target, value, fn)
            if kind not in _SCOPES:
                pending.extend(ast.iter_child_nodes(child))
        return fn

    def _bind(self, target: ast.AST, value: ast.AST, fn: _Function) -> None:
        if isinstance(target, ast.Starred):
            target = target.value
        if isinstance(target, ast.Name):
            fn.local.setdefault(target.id, []).append(value)
            return
        if isinstance(target, (ast.Tuple, ast.List)):     # an unpaired unpack: any name may be it
            for element in target.elts:
                self._bind(element, value, fn)
            return
        chain = tuple(_attr_chain(target.value if isinstance(target, ast.Subscript) else target))
        if len(chain) == 1:                                # `clients[key] = client`
            fn.local.setdefault(chain[0], []).append(value)
        elif chain:
            if chain[0] in _SELF and fn.cls is not None:   # `self._client = …`, `self._pool[k] = …`
                self.self_attrs[fn.cls].add(chain[1])
                self.self_values[fn.cls].setdefault(("self", *chain[1:]), []).append(value)
            fn.stores.append((chain, value))


_PARSED: dict[tuple[str, str], _Module] = {}


def _parsed(rel: str, source: str) -> _Module:
    """Parse once per (path, source): the probes re-scan the repo with a few modules swapped."""
    module = _PARSED.get((rel, source))
    if module is None:
        module = _PARSED[(rel, source)] = _Module(rel, source)
    return module


class _Bindings:
    """Every name in one module bound to the httpx package, a bare client constructor,
    a request helper or a repo module. Flow-insensitive: a binding made anywhere (a
    function-local import, a class attribute, a tuple unpack, an annotated or walrus
    assignment, a re-export from another repo module) counts."""

    def __init__(self, module: _Module, exports: dict[str, dict[str, str]],
                 repo_modules: set[str], facts: _Facts = _NO_FACTS) -> None:
        self.names: dict[str, tuple[str, str]] = {}
        self.module = module
        self.facts = facts
        self.exports = exports
        self.repo_modules = repo_modules
        self.assignments = module.assignments
        for node in module.imports:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "httpx" or alias.name.startswith("httpx."):
                        self.names[alias.asname or "httpx"] = (_HTTPX, "httpx")
                    elif (root := _sdk_root(alias.name)) is not None:
                        # `import ollama._client` binds `ollama`; `import google.genai`
                        # binds the `google` namespace; `import x.y as z` binds x.y.
                        top = alias.name.split(".")[0]
                        kind = (f"{_SDK}{alias.name}" if alias.asname
                                else f"{_SDK}{root}" if top == root else f"{_NS}{top}")
                        self.names[alias.asname or top] = (kind, alias.name)
                    elif alias.name in repo_modules or alias.name in _LEDGER_SOURCES:
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
                elif (root := _sdk_root(source)) is not None:
                    if alias.name == "*":
                        self.names.update({n: (f"{_SDK_CTOR}{root}:{n}", n) for n in _MODEL_SDKS[root]})
                    elif (kind := _sdk_member(source, alias.name)) is not None:
                        self.names[bound] = (kind, alias.name)
                elif _sdk_root(f"{source}.{alias.name}") == f"{source}.{alias.name}":
                    self.names[bound] = (f"{_SDK}{source}.{alias.name}", alias.name)  # from google import genai
                elif alias.name in _LEDGER_SOURCES.get(source, ()):
                    self.names[bound] = (f"{_LEDGER}{alias.name}", alias.name)
                elif alias.name == "*":
                    for name, kind in exports.get(source, {}).items():
                        self.names[name] = (kind, name)
                elif alias.name in exports.get(source, {}):
                    self.names[bound] = (exports[source][alias.name], alias.name)
                elif f"{source}.{alias.name}" in repo_modules or f"{source}.{alias.name}" in _LEDGER_SOURCES:
                    self.names[bound] = (_REPO, f"{source}.{alias.name}")
        # This module's own bare-client factories, classes and client globals.
        for name, kind in facts.defs.get(module.rel, {}).items():
            self.names[name] = (kind, name)
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
        if base[0].startswith(_SDK):
            kind = _sdk_member(base[0][len(_SDK):], node.attr)
            return (kind, node.attr) if kind else None
        if base[0].startswith(_NS):
            sub = f"{base[0][len(_NS):]}.{node.attr}"
            if sub in _MODEL_SDKS:
                return (f"{_SDK}{sub}", node.attr)
            return (f"{_NS}{sub}", node.attr) if any(p.startswith(sub + ".") for p in _MODEL_SDKS) else None
        if base[0].startswith((_FACTORY, _HOLDER)):
            return base     # a member of a factory, client-holding class or client global reaches it
        if base[0].startswith(_CARRIER):
            return None     # `PluginHTTPClient.for_plugin`: what reaches inside is checked by name
        if base[0] == _REPO:
            if node.attr in _LEDGER_SOURCES.get(base[1], ()):
                return (f"{_LEDGER}{node.attr}", node.attr)
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
        self._classes: list[tuple[str, bool]] = []    # (class qualname, inherits a carrier)

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
            if (_is_ctor(kind[0]) or kind[0] == _HELPER) and isinstance(node, ast.Attribute):
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
        elif kind[0].startswith(_SDK_CTOR):
            if role == "call":
                self._hit(node, _SDK_UNLEDGERED)
            elif role == "base":
                self._hit(node, "subclasses a model SDK client")
            elif not safe and role != "ledgered":
                self._hit(node, "references a model SDK client constructor uncalled "
                                "(aliased, defaulted, returned or handed on)")
        elif kind[0].startswith(_SDK):
            if not safe:
                self._hit(node, "reaches a model SDK module or its module-level client "
                                "(built without the ledger hook)")
        elif kind[0] == _HELPER:
            self._hit(node, "uses a module-level httpx request helper" if role == "call"
                      else "references a module-level httpx request helper")
        elif kind[0] == _HTTPX:
            self._hit(node, "hands the httpx module object on")
        elif kind[0].startswith(_FACTORY):
            target = kind[0][len(_FACTORY):]
            if role == "call":
                self._hit(node, f"calls {target}, which hands out a bare client")
            elif not safe:
                self._hit(node, f"reads {target}, which hands out a bare client")
        elif kind[0].startswith(_HOLDER):
            target = kind[0][len(_HOLDER):]
            if role == "call":
                self._hit(node, f"constructs {target}, whose instances hold a bare client")
            elif role == "base":
                self._hit(node, f"subclasses {target}, whose instances hold a bare client")
            elif not safe:
                self._hit(node, f"reads {target}, whose instances hold a bare client")
        return True     # resolved (a repo module or a carrier class included): nothing below

    def _class(self) -> tuple[str | None, bool]:
        return self._classes[-1] if self._classes else (None, False)

    def _member(self, node: ast.AST, recv: ast.AST, attr: str) -> None:
        """``recv.<attr>`` (or ``getattr(recv, "<attr>")``): a bare-client factory method
        read anywhere but as the reading class's own non-factory member, and a private
        client attribute read off another object or inherited from a carrier class."""
        facts, module = self.b.facts, self.b.module
        cls, inherits = self._class()
        if attr in facts.methods and not _own_member(module, facts, cls, recv, attr):
            self._hit(node, f"reaches .{attr}, which hands out a bare client "
                            f"({_names(facts.methods[attr])})")
        if attr in facts.attrs:
            if not (isinstance(recv, ast.Name) and recv.id in _SELF):
                self._hit(node, f"reads .{attr}, the bare client {_names(facts.attrs[attr])} holds")
            elif inherits and attr not in module.self_attrs.get(cls, ()):
                self._hit(node, f"reads self.{attr}, a bare client inherited from "
                                f"{_names(facts.attrs[attr])}")

    def _v_Name(self, node, safe, role):
        self._reference(node, safe, role)

    def _v_Attribute(self, node, safe, role):
        if self._reference(node, safe, role):
            return
        if node.attr in _RAW_SENDS and not self._in_transport():
            self._hit(node, "sends through a raw transport outside a transport class")
        if node.attr in _PRIVATE_SENDS:
            self._hit(node, "skips the client's request hooks through a private send step")
        if isinstance(node.ctx, ast.Load):
            self._member(node, node.value, node.attr)
        base = self.b.resolve(node.value)
        if base is not None and _is_ctor(base[0]):
            if not isinstance(node.ctx, ast.Load):
                self._hit(node, "patches the httpx client class")
            elif node.attr in _CONSTRUCTION:
                self._reference(node.value, False, role if role == "call" else "")
            return      # `httpx.AsyncClient._transport_for_url`: an identity pin, not a client
        if base is not None:
            return      # a member that is not a client: `httpx.Timeout`, `egress.llm_async_client`
        self.visit(node.value)

    def _v_Subscript(self, node, safe, role):
        key = node.slice
        if (isinstance(node.ctx, ast.Load) and isinstance(key, ast.Constant)
                and isinstance(key.value, str)):
            self._member(node, node.value, key.value)   # `vars(obj)["_client"]`, `obj.__dict__[…]`
        self.visit(node.value, safe)
        self.visit(node.slice, True)     # `type[httpx.AsyncClient]`, `dict[str, Client]`

    def _v_Compare(self, node, safe, role):
        identity = all(isinstance(op, _IDENTITY_OPS) for op in node.ops)
        for operand in [node.left, *node.comparators]:
            self.visit(operand, identity)

    # ── model SDK calls ──────────────────────────────────────────────────────
    def _values(self, node: ast.AST, seen: tuple = ()) -> list[ast.AST]:
        """What an expression can be: itself, or (flow-insensitively) every value its name
        or attribute chain is ever bound to in this module. An unbound name (a parameter)
        stays itself, so it cannot prove anything."""
        if isinstance(node, ast.NamedExpr):
            return self._values(node.value, seen)
        chain = tuple(_attr_chain(node))
        if not chain or chain in seen or self.b.resolve(node) is not None:
            return [node]
        bound = [value for target, value in self.b.assignments if tuple(_attr_chain(target)) == chain]
        return [v for value in bound for v in self._values(value, (*seen, chain))] or [node]

    def _calls(self, node: ast.AST, names: frozenset[str]) -> bool:
        kind = self.b.resolve(node.func) if isinstance(node, ast.Call) else None
        return kind is not None and kind[0] in {f"{_LEDGER}{n}" for n in names}

    def _carries_ledger(self, node: ast.AST, path: tuple[str, ...]) -> bool:
        value = _keyword(node, path[0])
        if value is None:
            return False
        values = self._values(value)
        if len(path) > 1:
            return all(self._carries_ledger(v, path[1:]) for v in values)
        if path[0] == "event_hooks":
            return all(self._has_ledger_hook(v) for v in values)
        return all(self._calls(v, _LEDGER_CLIENTS) for v in values)

    def _has_ledger_hook(self, hooks: ast.AST) -> bool:
        """``{"request": [..., llm_sync_request_hook(...), ...]}`` (or ``dict(request=…)``)."""
        request = _keyword(hooks, "request")
        if request is None:
            return False
        return all(isinstance(hook_list, (ast.List, ast.Tuple)) and any(
                       all(self._calls(v, _LEDGER_HOOKS) for v in self._values(hook))
                       for hook in hook_list.elts)
                   for hook_list in self._values(request))

    def _sdk_call_ledgered(self, call: ast.Call, kind: str) -> bool:
        package, name = kind[len(_SDK_CTOR):].rsplit(":", 1)
        paths = _MODEL_SDKS[package].get(name)
        return bool(paths) and all(self._carries_ledger(call, path) for path in paths)

    def _v_Call(self, node, safe, role):
        name = (_attr_chain(node.func) or [""])[-1]
        kind = self.b.resolve(node.func)
        ledgered = (kind is not None and kind[0].startswith(_SDK_CTOR)
                    and self._sdk_call_ledgered(node, kind[0]))
        self.visit(node.func, False, "ledgered" if ledgered else "call")
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
                elif name == "getattr":
                    self._member(node, node.args[0], attr.value)
        elif name in {"import_module", "__import__"} and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and str(first.value).split(".")[0] == "httpx":
                self._hit(node, "imports httpx dynamically")
            elif isinstance(first, ast.Constant) and _model_sdk(str(first.value)):
                self._hit(node, "imports a model SDK dynamically")
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
        # Bases are attributed to the class itself, so an exemption names the class.
        self._scope.append(node.name)
        for base in node.bases:
            self.visit(base, False, "base")
        for keyword in node.keywords:
            self.visit(keyword.value)
        is_transport = any((_attr_chain(b) or [""])[-1] in _TRANSPORT_BASES for b in node.bases)
        inherits = any((kind := self.b.resolve(b)) is not None
                       and kind[0].startswith((_HOLDER, _CARRIER)) for b in node.bases)
        for param in getattr(node, "type_params", ()):
            self.visit(param)
        self._transport.append(is_transport)
        self._classes.append((self._qual(), inherits))
        for statement in node.body:
            self.visit(statement)
        self._classes.pop()
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


class _Detector:
    """Which defs, classes and globals of one module hand a bare client out of themselves.

    A value hands one out when it is (or holds, as a tuple/list/dict element, a branch of a
    conditional, an awaited or subscripted value, a comprehension element, or an argument
    to a class/``dict``/``partial`` that wraps it) a bare construction, an unledgered model
    SDK client, a call of a factory, a read of one uncalled, or a name or ``self`` attribute
    this function or class binds to one. Calls of any other function are uses, not
    hand-outs: ``return await probe(client)`` keeps the client inside."""

    def __init__(self, module: _Module, bindings: _Bindings, facts: _Facts) -> None:
        self.m, self.b, self.f = module, bindings, facts
        self.sdk = _Scanner(bindings)

    def _method(self, node: ast.Attribute, cls: str | None) -> bool:
        return (node.attr in self.f.methods
                and not _own_member(self.m, self.f, cls, node.value, node.attr))

    def _client_call(self, call: ast.Call, cls: str | None) -> bool:
        kind = self.b.resolve(call.func)
        if kind is not None:
            if kind[0] == _CTOR or kind[0].startswith(_FACTORY):
                return True
            if kind[0].startswith(_SDK_CTOR):
                return not self.sdk._sdk_call_ledgered(call, kind[0])
            return False            # a helper returns a response; a ledger call a ledgered client
        func = call.func
        if not isinstance(func, ast.Attribute):
            return False
        if func.attr in _CONSTRUCTION:           # `httpx.AsyncClient.__new__(…)`
            base = self.b.resolve(func.value)
            return base is not None and _is_ctor(base[0])
        if self._method(func, cls):
            return True
        chain = tuple(_attr_chain(func))         # `self._client_cls(…)` bound to a constructor
        if len(chain) > 1 and chain[0] in _SELF and cls is not None:
            return any((k := self.b.resolve(v)) is not None and _hands_out_kind(k[0])
                       for v in self.m.self_values.get(cls, {}).get(("self", *chain[1:]), ()))
        return False

    def hands_out(self, node: ast.AST, local, cls, seen=frozenset()) -> bool:
        def again(child):
            return self.hands_out(child, local, cls, seen)
        if isinstance(node, (ast.Await, ast.Starred, ast.NamedExpr)):
            return again(node.value)
        if isinstance(node, ast.IfExp):
            return again(node.body) or again(node.orelse)
        if isinstance(node, ast.BoolOp):
            return any(map(again, node.values))
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            return any(map(again, node.elts))
        if isinstance(node, ast.Dict):
            return any(map(again, node.values))
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            return again(node.elt)
        if isinstance(node, ast.DictComp):
            return again(node.value)
        if isinstance(node, ast.Subscript):
            return again(node.value)
        if isinstance(node, ast.Lambda):
            return again(node.body)
        if isinstance(node, ast.Call):
            if self._client_call(node, cls):
                return True
            name = (_attr_chain(node.func) or [""])[-1]
            return ((name[:1].isupper() or name in _WRAPPERS)
                    and any(map(again, [*node.args, *(k.value for k in node.keywords)])))
        if not isinstance(node, (ast.Name, ast.Attribute)):
            return False
        kind = self.b.resolve(node)
        if kind is not None:
            return _hands_out_kind(kind[0])
        if isinstance(node, ast.Attribute) and self._method(node, cls):
            return True                          # a bound factory method handed on uncalled
        chain = tuple(_attr_chain(node))
        if not chain or chain in seen:
            return False
        if len(chain) == 1:
            values = local.get(chain[0], ())
        elif chain[0] in _SELF and cls is not None:
            values = self.m.self_values.get(cls, {}).get(("self", *chain[1:]), ())
        else:
            return False
        return any(self.hands_out(v, local, cls, seen | {chain}) for v in values)

    def detect(self):
        m, rel = self.m, self.m.rel
        defs: dict[str, str] = {}
        methods: dict[str, set[str]] = {}
        attrs: dict[str, set[str]] = {}
        owners: set[tuple[str, str, str]] = set()
        constructing: set[str] = set()      # classes whose instances (or body) hold a client
        carrying: set[str] = set()          # classes with factory methods or client attributes
        ledger = _LEDGER_SOURCES.get(m.name, frozenset())
        for fn in m.functions:
            if fn.qual in ledger:
                continue                    # the ledgered constructors themselves
            returns = any(self.hands_out(v, fn.local, fn.cls) for v in fn.returns)
            stored = False
            for chain, value in fn.stores:
                if not self.hands_out(value, fn.local, fn.cls):
                    continue
                if chain[0] in _SELF and fn.cls is not None:
                    owners.add((rel, fn.cls, chain[1]))
                    stored = True
                elif chain[-1].startswith("_"):     # planted on another object
                    attrs.setdefault(chain[-1], set()).add(f"{rel}:{fn.qual}")
            if returns:
                if fn.method:
                    methods.setdefault(fn.node.name, set()).add(f"{rel}:{fn.qual}")
                else:
                    defs[fn.node.name] = f"{_FACTORY}{rel}:{fn.qual}"
            if fn.cls is not None and (stored or (returns and fn.method)):
                carrying.add(fn.cls)
                if stored and not returns:
                    constructing.add(fn.cls)        # nothing hands it out: the instance does
        for cls, node in m.classes.items():
            for name, value in m.class_body[cls]:
                if self.b.resolve(value) is None and self.hands_out(value, {}, cls):
                    owners.add((rel, cls, name))
                    constructing.add(cls)
            for base in node.bases:
                kind = self.b.resolve(base)
                if kind is not None and kind[0].startswith(_HOLDER):
                    constructing.add(cls)           # constructing it runs the base's __init__
                elif kind is not None and kind[0].startswith(_CARRIER):
                    carrying.add(cls)
        for _, cls, attr in owners:
            if attr.startswith("_"):
                attrs.setdefault(attr, set()).add(f"{rel}:{cls}")
        for cls in carrying | constructing:
            prefix = _HOLDER if cls in constructing else _CARRIER
            defs[cls.rsplit(".", 1)[-1]] = f"{prefix}{rel}:{cls}"
        for name, value in m.globals:
            if self.b.resolve(value) is None and self.hands_out(value, {}, None):
                defs[name] = f"{_FACTORY}{rel}:{name}"      # a module-level client object
        return defs, methods, attrs, owners


def _bind_all(modules: dict[str, _Module], repo_modules: set[str] | None = None,
              facts: _Facts = _NO_FACTS) -> dict[str, _Bindings]:
    """Bindings for every module, re-exports followed to a fixed point."""
    repo_modules = repo_modules if repo_modules is not None else _repo_module_names(modules)
    exports: dict[str, dict[str, str]] = {}
    while True:
        bindings = {rel: _Bindings(m, exports, repo_modules, facts) for rel, m in modules.items()}
        found = {modules[rel].name: b.exported() for rel, b in bindings.items() if b.exported()}
        if found == exports:
            return bindings
        exports = found


def _analyse(modules: dict[str, _Module], repo_modules: set[str] | None = None,
             ) -> tuple[dict[str, _Bindings], _Facts]:
    """Bindings and bare-client facts together, to a joint fixed point: a factory found in
    one round is a constructor in the next, so whatever returns its client is one too."""
    repo_modules = repo_modules if repo_modules is not None else _repo_module_names(modules)
    facts = _NO_FACTS
    for _ in range(50):
        bindings = _bind_all(modules, repo_modules, facts)
        defs, methods, attrs, owners = {}, {}, {}, set()
        for rel, module in modules.items():
            d, mth, att, own = _Detector(module, bindings[rel], facts).detect()
            if d:
                defs[rel] = d
            for name, quals in mth.items():
                methods.setdefault(name, set()).update(quals)
            for name, quals in att.items():
                attrs.setdefault(name, set()).update(quals)
            owners |= own
        found = _Facts(defs, {k: frozenset(v) for k, v in methods.items()},
                       {k: frozenset(v) for k, v in attrs.items()}, frozenset(owners))
        if found == facts:
            return bindings, facts
        facts = found
    raise AssertionError("the bare-client facts did not reach a fixed point")


def scan_modules(sources: dict[str, str]) -> dict[str, list[tuple[str, int, str]]]:
    """Scan several modules together (re-exports and factories resolve across them)."""
    modules = {rel: _parsed(rel, src) for rel, src in sources.items()}
    out = {}
    for rel, bindings in _analyse(modules)[0].items():
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


def _imported(module: _Module) -> set[str]:
    """Every module path one module imports (``from a import b`` names ``a`` and ``a.b``)."""
    out: set[str] = set()
    for node in module.imports:
        if isinstance(node, ast.Import):
            out.update(alias.name for alias in node.names)
        else:
            source = _import_source(module.name, module.is_package, node)
            out.add(source)
            out.update(f"{source}.{alias.name}" for alias in node.names)
    return out


def _is_provider_module(module: _Module) -> bool:
    if module.rel.startswith("agents/core/llm/") or module.rel.startswith(PROVIDER_ROOTS):
        return True
    if any(_model_sdk(name) for name in _imported(module)):
        return True     # a model SDK is a model provider wherever the module lives
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


_SDK_TOPS = sorted({name.split(".")[0] for name in (*_MODEL_SDKS, *_UNLEDGERED_MODEL_SDKS)})
# Text that can only be an import (static or dynamic) of a model SDK.
_SDK_HINT = re.compile(r"(?:\b(?:import|from)\s+|import_module\(\s*['\"]|__import__\(\s*['\"])"
                       r"(?:" + "|".join(_SDK_TOPS) + r")\b")


def _scan_repo(extra: dict[str, str] | None = None):
    """Scan ``agents/`` (plus ``extra`` probe modules, rel -> source, for the tests that
    prove the whole pipeline — parse filter, scope and rule — catches a new provider)."""
    sources = {_rel(p): p.read_text(encoding="utf-8") for p in _modules()}
    sources.update(extra or {})
    repo_modules = _repo_module_names(sources)
    # Parse only what can matter (parsing all ~1000 modules costs seconds): a module that
    # names httpx, a raw or private send, a provider by path or by import, a model SDK
    # import, and — to a fixed point — any module whose text names something another
    # parsed module binds to a bare constructor, helper, model SDK, bare-client factory or
    # carrier class (a re-export under a name that never mentions httpx), a factory method
    # (``._get_client``), or a private client attribute read off another object.
    hints = ("httpx", *_RAW_SENDS, *_PRIVATE_SENDS, *_PROVIDER_IMPORT_HINTS)
    wanted = {rel for rel, src in sources.items()
              if rel.startswith(("agents/core/llm/", *PROVIDER_ROOTS))
              or any(h in src for h in hints) or _SDK_HINT.search(src)}
    modules: dict[str, _Module] = {}
    while True:
        modules.update({rel: _parsed(rel, sources[rel]) for rel in wanted - modules.keys()})
        bindings, facts = _analyse(modules, repo_modules)
        reach = _named_pattern(bindings, facts)
        if reach is None:
            break
        words, named = reach
        more = {rel for rel, src in sources.items() if rel not in modules
                and not words.isdisjoint(_tokens(rel, src)) and named.search(src)}
        if not more:
            break
        wanted |= more
    in_scope: dict[str, list[tuple[str, int, str]]] = {}
    outside: dict[str, list[tuple[str, int, str]]] = {}
    provider_modules = {rel for rel, m in modules.items() if _is_provider_module(m)}
    for rel, module in modules.items():
        scanner = _Scanner(bindings[rel])
        scanner.visit(module.tree)
        if scanner.findings:
            (in_scope if rel in provider_modules else outside)[rel] = scanner.findings
    return in_scope, outside, provider_modules


_TOKENS: dict[tuple[str, str], frozenset[str]] = {}


def _tokens(rel: str, source: str) -> frozenset[str]:
    words = _TOKENS.get((rel, source))
    if words is None:
        words = _TOKENS[(rel, source)] = frozenset(re.findall(r"[A-Za-z_]\w*", source))
    return words


def _named_pattern(bindings: dict[str, _Bindings], facts: _Facts,
                   ) -> tuple[frozenset[str], re.Pattern] | None:
    """Text that can only reach what the parsed modules bind or hand out: the words (a
    cheap prefilter) and the pattern a module with one of them must match."""
    alternatives = []
    bound = {name for b in bindings.values() for name, (kind, _) in b.names.items()
             if _is_client_path(kind)}
    if bound:   # `self.<name>` is an attribute, never the bound name
        alternatives.append(r"(?<!\bself\.)(?<!\bcls\.)\b(?:" + "|".join(map(re.escape, sorted(bound))) + r")\b")
    if facts.methods:
        alternatives.append(r"\b(?:" + "|".join(map(re.escape, sorted(facts.methods))) + r")\b")
    if facts.attrs:
        attrs = "|".join(map(re.escape, sorted(facts.attrs)))
        alternatives.append(r"(?<!\bself)(?<!\bcls)\.(?:" + attrs + r")\b|[\"'](?:" + attrs + r")[\"']")
    if not alternatives:
        return None
    return frozenset(bound) | frozenset(facts.methods) | frozenset(facts.attrs), re.compile("|".join(alternatives))


_SCAN = None


def _scan():
    global _SCAN
    if _SCAN is None:
        _SCAN = _scan_repo()
    return _SCAN


# ── the rule ─────────────────────────────────────────────────────────────────

def _prompt_offenders(in_scope) -> list[str]:
    """What fails the prompt-scope rule: a finding whose (file, qualname) is not allowlisted."""
    return [f"{rel}:{line} {qual} — {shape}"
            for rel, findings in in_scope.items()
            for qual, line, shape in findings
            if (rel, qual) not in PROMPT_SCOPE_ALLOWLIST]


def _unclassified(outside) -> list[str]:
    """What fails the outside-scope rule: a finding in a function nobody classified."""
    return [f"{rel}:{line} {qual} — {shape}"
            for rel, findings in outside.items()
            for qual, line, shape in findings
            if qual not in NOT_A_MODEL_PROVIDER.get(rel, ("", frozenset()))[1]]


def test_no_prompt_carrying_module_dials_a_bare_httpx_client():
    in_scope, _, _ = _scan()
    offenders = _prompt_offenders(in_scope)
    assert offenders == [], (
        "a prompt-carrying module reaches the network without the egress ledger; build "
        "the client with agents.core.llm.egress.llm_async_client (or the admitted native "
        "transport), or add a justified PROMPT_SCOPE_ALLOWLIST entry:\n" + "\n".join(offenders))


def test_every_bare_client_outside_the_scope_is_classified():
    """A provider cannot dodge the rule by living outside llm/, nor by being added to a
    module already classified for something else: an unclassified (module, function)
    with a bare client fails until someone says why it is not a model provider."""
    _, outside, _ = _scan()
    unclassified = _unclassified(outside)
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


# Libraries a provider could dial with instead of httpx, including the model SDKs that do
# not go through httpx at all (gRPC / google-api-core, botocore): no ledger hook sees them.
_OTHER_HTTP_STACKS = ("requests", "aiohttp", "urllib.request", "urllib3", "http.client",
                      "httpcore", "websockets", "grpc", "boto3", "botocore", "aiobotocore",
                      *_UNLEDGERED_MODEL_SDKS)
# httpcore is imported by the admitted transports for TYPE IDENTITY checks only, never to send.
_HTTPCORE_IDENTITY_ONLY = frozenset({"agents/core/llm/direct_transport.py",
                                     "agents/core/llm/providers/native_transport.py",
                                     "agents/core/llm/providers/custom_runtime.py",
                                     "agents/core/ingestion/embedding_policy.py"})


def _other_stack_imports(module: _Module) -> list[str]:
    offenders = []
    for node in module.imports:
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif node.level:
            continue          # a repo-relative import
        else:                 # `from google import generativeai` names google.generativeai
            names = [node.module or "", *(f"{node.module}.{alias.name}" for alias in node.names)]
        name = next((n for n in names if n.startswith(_OTHER_HTTP_STACKS)), None)
        top_level_httpcore = (name if isinstance(node, ast.Import) else node.module) == "httpcore"
        if name and not (top_level_httpcore and module.rel in _HTTPCORE_IDENTITY_ONLY):
            offenders.append(f"{module.rel}:{node.lineno} imports {name}")
    return offenders


def test_no_provider_module_switches_to_another_http_stack():
    """The httpx rule cannot be dodged by dialling with a different library, nor with a
    model SDK that does not dial through httpx."""
    _, _, provider_modules = _scan()
    offenders = [line for rel in sorted(provider_modules)
                 for line in _other_stack_imports(_Module(rel, (REPO / rel).read_text(encoding="utf-8")))]
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
    # ── model SDKs (round-2 review): the SDK builds the bare httpx client ──
    "sdk openai provider": ("from openai import AsyncOpenAI\nclass P:\n    def __init__(self, k, u):\n"
                            "        self.client = AsyncOpenAI(api_key=k, base_url=u)\n"),
    "sdk anthropic": "import anthropic\ndef f():\n    return anthropic.AsyncAnthropic()\n",
    "sdk alias": "import anthropic as a\ndef f():\n    return a.Client()\n",
    "sdk private module": "import openai\ndef f():\n    return openai._client.OpenAI()\n",
    "sdk lib module": "from openai.lib.azure import AzureOpenAI\ndef f():\n    return AzureOpenAI()\n",
    "sdk star import": "from groq import *\ndef f():\n    return AsyncGroq()\n",
    "sdk ollama remote": "import ollama\ndef f():\n    return ollama.Client(host='https://ollama.com')\n",
    "sdk ollama no hook": ("from ollama import Client\ndef f(h):\n"
                           "    return Client(host=h, timeout=30.0, trust_env=False)\n"),
    "sdk ollama hook on response": (
        "import ollama\nfrom agents.core.llm.egress import llm_sync_request_hook\ndef f(h):\n"
        "    return ollama.Client(host=h, event_hooks={'response': [llm_sync_request_hook('o')]})\n"),
    "sdk ollama foreign hook": ("import ollama\ndef f(h, log):\n"
                                "    return ollama.Client(host=h, event_hooks={'request': [log]})\n"),
    "sdk ollama look-alike hook": (
        "import ollama\ndef llm_sync_request_hook(b):\n    return print\ndef f(h):\n"
        "    return ollama.Client(host=h, event_hooks={'request': [llm_sync_request_hook('o')]})\n"),
    "sdk ollama async": (
        "import ollama\nfrom agents.core.llm.egress import llm_sync_request_hook\ndef f(h):\n"
        "    return ollama.AsyncClient(host=h, event_hooks={'request': [llm_sync_request_hook('o')]})\n"),
    "sdk ollama module client": "import ollama\ndef f(t):\n    return ollama.embed(model='m', input=t)\n",
    "sdk ollama module function": "from ollama import chat\ndef f(m):\n    return chat(model='x', messages=m)\n",
    "sdk openai module client": ("import openai\ndef f(m):\n"
                                 "    return openai.chat.completions.create(model='x', messages=m)\n"),
    "sdk http_client from a parameter": ("import openai\ndef f(client):\n"
                                         "    return openai.OpenAI(http_client=client)\n"),
    "sdk http_client rebound": (
        "import openai\nfrom agents.core.llm.egress import llm_sync_client\ndef f(make):\n"
        "    h = llm_sync_client('openai')\n    h = make()\n    return openai.OpenAI(http_client=h)\n"),
    "sdk kwargs splat": ("import openai\nfrom agents.core.llm.egress import llm_sync_client\n"
                         "def f():\n    kw = {'http_client': llm_sync_client('openai')}\n"
                         "    return openai.OpenAI(**kw)\n"),
    "sdk default client": "import openai\ndef f():\n    return openai.OpenAI(http_client=openai.DefaultHttpxClient())\n",
    "sdk genai": "from google import genai\ndef f(k):\n    return genai.Client(api_key=k)\n",
    "sdk genai namespace import": "import google.genai\ndef f(k):\n    return google.genai.Client(api_key=k)\n",
    "sdk genai half ledgered": (
        "from google import genai\nfrom google.genai import types\n"
        "from agents.core.llm.egress import llm_sync_client\ndef f():\n"
        "    return genai.Client(http_options=types.HttpOptions(httpx_client=llm_sync_client('g')))\n"),
    "sdk mistral half ledgered": (
        "from mistralai import Mistral\nfrom agents.core.llm.egress import llm_sync_client\ndef f(k):\n"
        "    return Mistral(api_key=k, client=llm_sync_client('mistral'))\n"),
    "sdk class attribute": "import openai\nclass B:\n    _client_cls = openai.AsyncOpenAI\n",
    "sdk default parameter": "import cohere\ndef f(make=cohere.ClientV2):\n    return make()\n",
    "sdk subclass": "import anthropic\nclass Mine(anthropic.Anthropic):\n    pass\n",
    "sdk module handed on": "import openai\ndef f():\n    return getattr(openai, 'OpenAI')()\n",
    "sdk dynamic import": "import importlib\ndef f():\n    return importlib.import_module('openai').OpenAI()\n",
    "sdk explicit __init__": "import ollama\ndef f(c):\n    ollama.Client.__init__(c, host='https://ollama.com')\n",
}

# Ledgered SDK shapes and type-only SDK reads: none of these is a finding.
_SAFE_SDK = (
    "from agents.core.llm import egress\n"
    "from agents.core.llm.egress import llm_async_client, llm_sync_client, llm_sync_request_hook\n"
    "from agents.core.llm.providers.native_transport import native_admitted_client\n"
    "import anthropic, cohere, ollama, openai\n"
    "from google import genai\n"
    "from google.genai import types\n"
    "from mistralai import Mistral\n"
    "def f(h, k, profile, credential, model):\n"
    "    a = openai.AsyncOpenAI(api_key=k, http_client=llm_async_client('openai', base_url=h))\n"
    "    hook = llm_sync_request_hook('ollama')\n"
    "    b = ollama.Client(host=h, event_hooks={'request': [hook]})\n"
    "    b2 = ollama.Client(host=h, event_hooks=dict(request=[egress.llm_sync_request_hook('o')]))\n"
    "    c = genai.Client(http_options=types.HttpOptions(httpx_client=llm_sync_client('g'),\n"
    "                                                    httpx_async_client=llm_async_client('g')))\n"
    "    d = Mistral(api_key=k, client=llm_sync_client('m'), async_client=llm_async_client('m'))\n"
    "    e = cohere.ClientV2(k, httpx_client=llm_sync_client('cohere'))\n"
    "    g = openai.AsyncOpenAI(http_client=native_admitted_client(profile, credential, model))\n"
    "    if ollama is None or isinstance(b, ollama.Client) or type(a) is openai.AsyncOpenAI:\n"
    "        pass\n"
    "    try:\n"
    "        pass\n"
    "    except (ollama.ResponseError, openai.APIError):\n"
    "        pass\n"
    "    message: openai.types.chat.ChatCompletion | None = None\n"
    "    options = ollama.Options(temperature=0)\n"
    "    return a, b, b2, c, d, e, g, message, options, openai.NOT_GIVEN\n"
    "class Backend:\n"
    "    def __init__(self, k):\n"
    "        self.http = llm_async_client('anthropic')\n"
    "        self.client = anthropic.AsyncAnthropic(api_key=k, http_client=self.http)\n"
    "async def g(k):\n"
    "    async with llm_async_client('anthropic') as http:\n"
    "        return anthropic.AsyncAnthropic(api_key=k, http_client=http)\n"
)

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
    assert scan_source(_SAFE_SDK) == []


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


def test_the_real_ollama_embedder_without_its_ledger_hook_is_caught():
    """Round-2 review's mutation, on the real embedder: ``ollama.Client`` builds an
    ``httpx.Client`` from its own kwargs, so its ``event_hooks`` request hook is the only
    ledger, host-protocol and data-handling check on the path that sends document text
    (``OLLAMA_HOST`` may be ollama.com). Dropping the hook passed every test before."""
    rel = "agents/core/ingestion/embedder.py"
    hook = 'event_hooks={"request": [llm_sync_request_hook("ollama")]},'
    source = (REPO / rel).read_text(encoding="utf-8")
    assert source.count(hook) == 1, f"{rel} changed; update this mutation"
    assert scan_source(source, rel) == []
    for broken in ("",                                                         # hook removed
                   'event_hooks={"response": [llm_sync_request_hook("ollama")]},',  # wrong event
                   'event_hooks={"request": [logger.debug]},',                 # not the ledger
                   'event_hooks=hooks,'):                                      # unproven name
        findings = [(q, s) for q, _, s in scan_source(source.replace(hook, broken), rel)]
        assert [f for f in findings if f[0] == "Embedder._setup"] == [
            ("Embedder._setup", _SDK_UNLEDGERED)], broken
        # The unledgered SDK client is now stored on the embedder, so the reads of its
        # internal httpx client (`self._client._client`) are followed as well.
        assert {q for q, _ in findings} <= {"Embedder._setup", "Embedder._policy_client",
                                            "Embedder._embed_resilient"}, findings
    assert (rel, "Embedder._setup") not in PROMPT_SCOPE_ALLOWLIST
    # The in-scope rule itself fails on the mutation (the embedder is a provider module).
    assert _is_provider_module(_Module(rel, source.replace(hook, "")))


def test_a_new_model_sdk_provider_fails_the_repo_rule_wherever_it_lives():
    """Round-2 review's probe, through the whole pipeline (parse filter, scope, rule): a
    Hermes-style provider holding ``AsyncOpenAI(api_key, base_url)`` under llm/, an
    Anthropic SDK provider outside llm/ (in scope because it imports a model SDK), and a
    module calling ``ollama.embed`` (the SDK's module-level client) all fail the rule;
    their ledgered twins and a non-httpx model SDK are handled too."""
    probes = {
        "agents/core/llm/zz_probe_sdk.py": (
            "from openai import AsyncOpenAI\n"
            "class ProbeBackend:\n"
            "    def __init__(self, api_key, base_url):\n"
            "        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)\n"),
        "agents/core/tools/zz_probe_anthropic.py": (
            "import anthropic\n"
            "def ask(prompt):\n"
            "    return anthropic.Anthropic().messages.create(model='m', max_tokens=8,\n"
            "        messages=[{'role': 'user', 'content': prompt}])\n"),
        "agents/core/tools/zz_probe_ollama.py": (
            "import ollama\n"
            "def embed(text):\n"
            "    return ollama.embed(model='nomic-embed-text', input=text)\n"),
        "agents/core/tools/zz_probe_ledgered.py": (
            "import openai\n"
            "from agents.core.llm.egress import llm_async_client\n"
            "def client(key):\n"
            "    return openai.AsyncOpenAI(api_key=key, http_client=llm_async_client('openai'))\n"),
        "agents/core/tools/zz_probe_vertex.py": "import vertexai\n",
    }
    in_scope, outside, provider_modules = _scan_repo(probes)
    assert set(probes) <= provider_modules
    assert not set(probes) & set(outside)
    found = {rel: [(q, s) for q, _, s in in_scope.get(rel, [])] for rel in probes}
    assert found == {
        "agents/core/llm/zz_probe_sdk.py": [("ProbeBackend.__init__", _SDK_UNLEDGERED)],
        "agents/core/tools/zz_probe_anthropic.py": [("ask", _SDK_UNLEDGERED)],
        "agents/core/tools/zz_probe_ollama.py": [
            ("embed", "reaches a model SDK module or its module-level client "
                      "(built without the ledger hook)")],
        "agents/core/tools/zz_probe_ledgered.py": [],
        "agents/core/tools/zz_probe_vertex.py": [],
    }
    assert _other_stack_imports(_Module("agents/core/tools/zz_probe_vertex.py", "import vertexai\n")) == [
        "agents/core/tools/zz_probe_vertex.py:1 imports vertexai"]
    assert _other_stack_imports(_Module("agents/core/llm/zz.py", "from google import generativeai\n")) == [
        "agents/core/llm/zz.py:1 imports google.generativeai"]


def test_a_model_sdk_re_export_through_another_repo_module_is_caught():
    findings = scan_modules({
        "agents/core/compat_sdk.py": "from openai import AsyncOpenAI\nimport ollama as _ollama\n",
        "agents/core/llm/p1.py": ("from agents.core.compat_sdk import AsyncOpenAI\n"
                                  "def f():\n    return AsyncOpenAI()\n"),
        "agents/core/llm/p2.py": ("from agents.core import compat_sdk\n"
                                  "def f(t):\n    return compat_sdk._ollama.embed(model='m', input=t)\n"),
    })
    assert findings["agents/core/llm/p1.py"] == [("f", 3, _SDK_UNLEDGERED)]
    assert [q for q, _, _ in findings["agents/core/llm/p2.py"]] == ["f"]
    assert findings["agents/core/compat_sdk.py"] == []


# ── round-3 review: a bare client handed out by the function that builds it ─

_GEMINI = "agents/core/llm/gemini.py"
_GEMINI_LEDGERED = 'else llm_async_client("gemini", timeout=120.0))'
_GEMINI_IMPORT = "from .egress import llm_async_client\n"
_MODEL_SETUP_FACTORY = "calls agents/core/llm/model_setup.py:_client, which hands out a bare client"

_FACTORY_PROBES = {
    # The reviewer's second probe: a new llm/ provider sending a prompt through the plugin
    # client's lifecycle client and through the Ollama controller's control-plane client.
    "agents/core/llm/zz_probe_factory.py": (
        "from agents.core.http_client import PluginHTTPClient\n"
        "from agents.core.llm.ollama_control import OllamaController\n"
        "async def ask_plugin(prompt):\n"
        "    client = PluginHTTPClient('probe')._get_client()\n"
        "    return await client.post('https://api.openai.com/v1/chat/completions',\n"
        "                             json={'messages': [{'role': 'user', 'content': prompt}]})\n"
        "async def ask_ollama(controller: OllamaController, prompt):\n"
        "    return await controller._http_client().post(\n"
        "        'https://api.openai.com/v1/chat/completions',\n"
        "        json={'messages': [{'role': 'user', 'content': prompt}]})\n"),
    # The same factories reached other ways: a re-export through a module outside llm/ that
    # never names httpx, a module attribute, a client attribute, a subclass, a holder class.
    "agents/core/zz_probe_compat.py": "from agents.core.llm.model_setup import _client as ollama_http\n",
    "agents/core/llm/zz_probe_reach.py": (
        "from agents.core import zz_probe_compat\n"
        "from agents.core.llm import model_setup\n"
        "from agents.core.llm.ollama_control import OllamaController\n"
        "from agents.core.memory.qdrant_store import QdrantVectorStore\n"
        "def via_re_export():\n"
        "    return zz_probe_compat.ollama_http('http://127.0.0.1:11434', None, 5.0)\n"
        "def via_module_attribute():\n"
        "    return model_setup._client('http://127.0.0.1:11434', None, 5.0)\n"
        "async def via_client_attribute(controller, prompt):\n"
        "    return await controller._client.post('https://api.openai.com/v1/x', json={'p': prompt})\n"
        "def via_getattr(plugin):\n"
        "    return getattr(plugin, '_pinned_client')\n"
        "class ProbeController(OllamaController):\n"
        "    async def ask(self, prompt):\n"
        "        return await self._client.post('https://api.openai.com/v1/x', json={'p': prompt})\n"
        "def via_holder(prompt):\n"
        "    return QdrantVectorStore('https://api.openai.com')._client.post('/v1/x', json={'p': prompt})\n"),
    # A provider outside llm/ calling the factory is an unclassified outside finding.
    "agents/core/tools/zz_probe_outside.py": (
        "from agents.core.llm.model_setup import _client\n"
        "async def ask(prompt):\n"
        "    http, _ = _client('http://127.0.0.1:11434', None, 5.0)\n"
        "    return await http.post('https://api.openai.com/v1/x', json={'prompt': prompt})\n"),
}


def test_the_reviewer_factory_probes_fail_the_repo_rule():
    """Round-3 review's probes, made permanent and run through the whole pipeline (parse
    filter, scope, factories, allowlist). (1) The real Gemini backend sends its prompts
    through the bare client ``model_setup._client`` returns instead of its ledgered one;
    (2) a new llm/ module posts a prompt through ``PluginHTTPClient._get_client()`` and
    ``OllamaController._http_client()``. Both passed every structural test before, because
    a call of a repo function was never resolved: the client was only checked where built."""
    source = (REPO / _GEMINI).read_text(encoding="utf-8")
    assert source.count(_GEMINI_LEDGERED) == 1 and source.count(_GEMINI_IMPORT) == 1, (
        f"{_GEMINI} changed; update this mutation")
    swapped = source.replace(_GEMINI_LEDGERED, "else _client(GEMINI_API_BASE, None, 120.0)[0])").replace(
        _GEMINI_IMPORT, _GEMINI_IMPORT + "from .model_setup import _client\n")
    in_scope, outside, provider_modules = _scan_repo({_GEMINI: swapped, **_FACTORY_PROBES})
    offenders = _prompt_offenders(in_scope)

    def failing(rel):
        return sorted(o.split(" — ")[0].split(" ", 1)[1] + " — " + o.split(" — ")[1]
                      for o in offenders if o.startswith(rel + ":"))

    assert failing(_GEMINI) == [f"GeminiBackend.__init__ — {_MODEL_SETUP_FACTORY}"]
    assert failing("agents/core/llm/zz_probe_factory.py") == [
        "ask_ollama — reaches ._http_client, which hands out a bare client "
        "(agents/core/llm/ollama_control.py:OllamaController._http_client)",
        "ask_plugin — reaches ._get_client, which hands out a bare client "
        "(agents/core/http_client.py:PluginHTTPClient._get_client)",
    ]
    reach = {line.split(" — ")[0] for line in failing("agents/core/llm/zz_probe_reach.py")}
    assert reach == {"via_re_export", "via_module_attribute", "via_client_attribute",
                     "via_getattr", "ProbeController.ask", "via_holder"}, reach
    assert "agents/core/zz_probe_compat.py" not in in_scope     # a re-export alone sends nothing
    outside_hits = [o for o in _unclassified(outside)
                    if o.startswith("agents/core/tools/zz_probe_outside.py:")]
    assert [o.split(" — ")[1] for o in outside_hits] == [_MODEL_SETUP_FACTORY]
    assert "agents/core/tools/zz_probe_outside.py" not in provider_modules
    # The unswapped backend is clean, so the finding is the swap and nothing else.
    assert _prompt_offenders(_scan()[0]) == []


def test_every_caller_of_an_allowlisted_factory_is_checked():
    """An allowlisted factory's reason is no longer a promise about its callers: each
    caller is a finding of its own (in-class callers included), so a new caller of
    model_setup._client or OllamaController._http_client fails until it is justified."""
    in_scope, outside, _ = _scan()
    callers = {(rel, qual) for rel, findings in in_scope.items() for qual, _, shape in findings
               if "hands out a bare client" in shape}
    assert {("agents/core/llm/model_setup.py", "ollama_present"),
            ("agents/core/llm/model_setup.py", "ollama_pull"),
            ("agents/core/llm/model_setup.py", "ollama_delete"),
            ("agents/core/llm/ollama_control.py", "OllamaController.load_model"),
            ("agents/core/llm/ollama_control.py", "OllamaController.unload_model"),
            ("agents/core/llm/ollama_control.py", "OllamaController._active_models")} <= callers
    plugin = {qual for qual, _, shape in outside.get("agents/core/http_client.py", [])
              if "hands out a bare client" in shape}
    assert plugin == {"PluginHTTPClient._request_pinned", "PluginHTTPClient.stream"}, plugin
    rel = "agents/core/llm/ollama_control.py"
    source = (REPO / rel).read_text(encoding="utf-8")
    anchor = "    def _http_client(self):\n"
    assert source.count(anchor) == 1, f"{rel} changed; update this mutation"
    added = source.replace(anchor, (
        "    async def chat(self, prompt):\n"
        "        return await self._http_client().post('/api/chat', json={'messages': [prompt]})\n\n"
    ) + anchor)
    new = [q for q, _, s in scan_source(added, rel) if "hands out a bare client" in s]
    assert "OllamaController.chat" in new and (rel, "OllamaController.chat") not in PROMPT_SCOPE_ALLOWLIST


def test_the_model_setup_factory_refuses_every_non_loopback_destination():
    """``model_setup._client``'s exemption no longer rests on its callers: the factory
    refuses a non-loopback URL, and the client it builds refuses a non-loopback request
    (an absolute URL overrides ``base_url``) before transport entry."""
    import asyncio

    import httpx
    import pytest

    from agents.core.llm import model_setup as ms

    for url in ("https://generativelanguage.googleapis.com/v1beta", "http://192.168.1.9:11434",
                "http://localhost.evil.test:11434"):
        with pytest.raises(ms.OllamaURLNotLoopback):
            ms._client(url, None, 1.0)
        with pytest.raises(ms.OllamaURLNotLoopback):
            ms._client(url, object(), 1.0)      # an injected client is refused for it too
    http, owned = ms._client("http://127.0.0.1:11434", None, 1.0)
    assert owned
    sent: list[str] = []

    def handler(request):
        sent.append(str(request.url))
        return httpx.Response(200, json={"models": []})

    http._transport = httpx.MockTransport(handler)   # the would-be wire, observed

    async def run():
        try:
            assert (await http.get("/api/tags")).status_code == 200
            for target in ("https://generativelanguage.googleapis.com/v1beta/models/m:generateContent",
                           "http://192.168.1.9:11434/api/chat"):
                with pytest.raises(ms.OllamaURLNotLoopback):
                    await http.post(target, json={"contents": [{"parts": [{"text": "prompt"}]}]})
        finally:
            await http.aclose()

    asyncio.run(run())
    assert sent == ["http://127.0.0.1:11434/api/tags"]


# Factory shapes, scanned together: every user module must be a finding, and the
# defining module's own in-class caller is one too.
_NETX, _NETX2, _USER = "agents/core/netx.py", "agents/core/netx2.py", "agents/core/llm/zz_user.py"
_NETX_SRC = '''\
import contextlib, functools
import httpx
import openai
from agents.core.llm.egress import llm_async_client

def make(u):
    return httpx.AsyncClient(base_url=u)

def make_pair(u):
    return httpx.AsyncClient(base_url=u), True

def make_local():
    c = httpx.AsyncClient()
    return c

async def make_closed():
    async with httpx.AsyncClient() as c:
        return c

@contextlib.asynccontextmanager
async def session():
    async with httpx.AsyncClient() as c:
        yield c

def make_or(c=None):
    return c or httpx.AsyncClient()

class Box:
    def __init__(self, inner):
        self.inner = inner

def make_boxed():
    return Box(httpx.AsyncClient())

def make_partial():
    return functools.partial(httpx.AsyncClient, timeout=1)

def make_dict():
    return {"cloud": httpx.AsyncClient()}

make_lambda = lambda: httpx.AsyncClient()

def make_sdk(k):
    return openai.AsyncOpenAI(api_key=k)

CLIENT = httpx.AsyncClient()

class Ctl:
    def __init__(self):
        self._c = None
    def _http(self):
        if self._c is None:
            self._c = httpx.AsyncClient()
        return self._c
    def getter(self):
        return self._http
    async def request(self, path):
        return await self._http().get(path)

class Holder:
    def __init__(self):
        self.client = httpx.AsyncClient()

class Late:
    def start(self):
        self.client = httpx.AsyncClient()

class Shared:
    pool = httpx.AsyncClient()

class Build:
    @staticmethod
    def build():
        return httpx.AsyncClient()
    @property
    def http(self):
        return httpx.AsyncClient()

def ledgered():
    return llm_async_client("x")

async def probe(u):
    async with httpx.AsyncClient() as c:
        return (await c.get(u)).json()

async def _go(c):
    return await c.get("/")

async def use(u):
    async with httpx.AsyncClient() as c:
        return await _go(c)
'''
_NETX2_SRC = ("from agents.core.netx import make\nfrom agents.core.netx import make as build_again\n"
              "def again():\n    return make('u')\n")
_FACTORY_USERS = {
    "returned client": "from agents.core.netx import make\nasync def f(p):\n    return await make('u').post('/', json=p)\n",
    "returned in a tuple": "from agents.core.netx import make_pair\ndef f():\n    return make_pair('u')[0]\n",
    "returned through a local": "from agents.core.netx import make_local\ndef f():\n    return make_local()\n",
    "returned from a with block": "from agents.core.netx import make_closed\nasync def f():\n    return await make_closed()\n",
    "yielded by a context manager": ("from agents.core.netx import session\nasync def f(p):\n"
                                     "    async with session() as c:\n        return await c.post('/', json=p)\n"),
    "conditional": "from agents.core.netx import make_or\ndef f():\n    return make_or()\n",
    "wrapped in an object": "from agents.core.netx import make_boxed\ndef f():\n    return make_boxed().inner\n",
    "partial": "from agents.core.netx import make_partial\ndef f():\n    return make_partial()()\n",
    "dict entry": "from agents.core.netx import make_dict\ndef f():\n    return make_dict()['cloud']\n",
    "lambda global": "from agents.core.netx import make_lambda\ndef f():\n    return make_lambda()\n",
    "model SDK factory": "from agents.core.netx import make_sdk\ndef f(k):\n    return make_sdk(k)\n",
    "module-level client object": ("from agents.core.netx import CLIENT\nasync def f(p):\n"
                                   "    return await CLIENT.post('/', json=p)\n"),
    "transitive factory": "from agents.core.netx2 import again\ndef f():\n    return again()\n",
    "re-export": "from agents.core.netx2 import build_again\ndef f():\n    return build_again('u')\n",
    "module attribute": "from agents.core import netx\ndef f():\n    return netx.make('u')\n",
    "absolute module attribute": "import agents.core.netx\ndef f():\n    return agents.core.netx.make('u')\n",
    "alias": "from agents.core.netx import make\nm = make\ndef f():\n    return m('u')\n",
    "handed on uncalled": "from agents.core.netx import make\ndef f(run):\n    return run(factory=make)\n",
    "default parameter": "from agents.core.netx import make\ndef f(factory=make):\n    return factory('u')\n",
    "factory method": "from agents.core.netx import Ctl\nasync def f(p):\n    return await Ctl()._http().post('/', json=p)\n",
    "factory method on a parameter": "async def f(ctl, p):\n    return await ctl._http().post('/', json=p)\n",
    "factory method by getattr": "def f(ctl):\n    return getattr(ctl, '_http')()\n",
    "bound factory method handed out": "def f(ctl):\n    return ctl.getter()()\n",
    "private client attribute": "async def f(ctl, p):\n    return await ctl._c.post('/', json=p)\n",
    "private client attribute by getattr": "def f(ctl):\n    return getattr(ctl, '_c')\n",
    "private client attribute through vars()": "def f(ctl):\n    return vars(ctl)['_c']\n",
    "inherited factory method": ("from agents.core.netx import Ctl\nclass Mine(Ctl):\n"
                                 "    def f(self):\n        return self._http()\n"),
    "inherited client attribute": ("from agents.core.netx import Ctl\nclass Mine(Ctl):\n"
                                   "    def f(self):\n        return self._c\n"),
    "overridden factory method via super()": ("from agents.core.netx import Ctl\nclass Mine(Ctl):\n"
                                              "    def _http(self):\n        return super()._http()\n"),
    "holder construction": ("from agents.core.netx import Holder\nasync def f(p):\n"
                            "    return await Holder().client.post('/', json=p)\n"),
    "holder subclass": "from agents.core.netx import Holder\nclass Mine(Holder):\n    pass\n",
    "holder through a store-only method": ("from agents.core.netx import Late\ndef f():\n"
                                           "    late = Late()\n    late.start()\n    return late.client\n"),
    "class attribute client": "from agents.core.netx import Shared\ndef f():\n    return Shared.pool\n",
    "static factory method": "from agents.core.netx import Build\ndef f():\n    return Build.build()\n",
    "property factory": "def f(b):\n    return b.http\n",
}
# Uses of the same module that hand nothing out: none is a finding.
_FACTORY_SAFE_USER = '''\
from agents.core.llm.egress import llm_async_client
from agents.core.netx import Ctl, Holder, ledgered, probe, use

class Mine(Ctl):
    pass

class Own:
    def __init__(self):
        self._c = llm_async_client("own")
        self.http = llm_async_client("own")
    def _http(self):
        return llm_async_client("own")
    async def f(self, p):
        await self._http().post("/", json=p)
        await self.http.post("/", json=p)
        return await self._c.post("/", json=p)

async def ask(p, h: Holder | None = None):
    if isinstance(h, Holder):
        pass
    ctl = Ctl()
    await ctl.request("/api/tags")
    await probe("http://127.0.0.1:1")
    await use("http://127.0.0.1:1")
    return await ledgered().post("/", json=p)
'''


def test_the_scanner_follows_a_bare_client_out_of_its_factory():
    for name, user in _FACTORY_USERS.items():
        findings = scan_modules({_NETX: _NETX_SRC, _NETX2: _NETX2_SRC, _USER: user})
        assert findings[_USER], f"the scanner misses the {name!r} factory shape"
    findings = scan_modules({_NETX: _NETX_SRC, _NETX2: _NETX2_SRC, _USER: _FACTORY_SAFE_USER})
    assert findings[_USER] == [], findings[_USER]
    # The defining module's in-class caller is checked like any other caller, and a
    # function that only uses its client (or hands it to a helper) is not a factory.
    netx = {qual for qual, _, shape in findings[_NETX] if "hands out a bare client" in shape}
    assert netx == {"Ctl.request", "Ctl.getter"}, netx      # getter hands the bound factory on
    assert {qual for qual, _, _ in findings[_NETX2]} == {"again"}
