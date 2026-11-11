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
``self`` attribute, from a ``with`` block, wrapped in a class/``dict``/``partial``/
``closing``, through a same-module helper that returns its argument, as a nested def's
closure, or as another factory's client — is itself a constructor. Every call or uncalled
read of it, through any alias, re-export or module attribute, is a finding in the caller
(in-class callers included), so each caller needs its own exemption and no allowlist reason
can rest on "the callers behave". A factory method is matched by name (``._http_client``,
``._get_client``, ``._pinned_client`` …, as an attribute, through ``getattr`` or as a string
such as ``methodcaller("_http")``) unless it is the reading class's own non-factory member;
an attribute a bare client is kept in — a class's private one (``._client``, ``setattr``
included) or any one planted on another object — is a finding read off another object
(``vars(o).get(...)`` / ``o.__dict__`` included) or by a subclass, even one that sets it
too; a class whose construction leaves a bare client on a public attribute (or whose body
holds one) is a finding wherever it is built or subclassed; a module global holding one
(set at import, through ``global``, or filled into a module dict by a function) wherever it
is read.

**…and by where it is pointed** (round-4 review): a classified generic sender —
``_HttpxREST.request(method, url, **kw)`` — sent a caller's prompt to a caller's host, and
its callers were never findings. The host every bare-client send dials is now traced back
through locals, f-strings, concatenations, ``urlunsplit``, the client's ``base_url``,
factories, other senders, same-module helpers and the class's own attributes; only the part
of a URL that can move the host counts (a parameter in the path, query or body of a fixed
origin does not; ``base + path`` does). A function whose host one of its parameters decides
is a *sender*: every call of it that passes that parameter is a finding (a caller handing it
its own parameter is a sender in turn), a private sender method is matched by name like a
factory method, a class with a public one is gated like a client (built, subclassed, its
instances followed into locals and attributes), and a class whose host an attribute set from
a constructor parameter decides is a finding wherever it is built with that parameter. A
function on :data:`_PINNED_DESTINATIONS` refuses (or ledgers) every destination in its own
code, so a trace ends there. Stated limit: a *public* attribute holding a bare client is
followed only through that construction gate (``backend.client`` is the ledgered client of
every LLM backend, and the scanner has no types), so the set of them is closed and each one
refuses every other host in code (``test_every_public_bare_client_attribute_is_pinned_in_code``);
a sender instance or client handed in as a parameter is not typed either (whoever builds it
is the finding); a host returned by a function of another module counts as coming from that
call's arguments.

**…and a ledgered client turned bare** (round-5 review): httpx replaces every hook when
``client.event_hooks`` is assigned, so a backend adding its own logging hook that way drops the
egress recorder. Every store to, mutation of, deletion from or hand-off of a client's hooks
(``event_hooks`` / ``_event_hooks``: assignment, subscript store, ``.clear/.pop/.remove/.append``
…, ``del``, ``setattr``, ``vars()``/``__dict__``, any local or attribute alias of the hook dict or
of a hook list) is a finding anywhere in ``agents/`` unless its exact ``(file, qualname)`` is on
:data:`HOOK_REWIRING_ALLOWLIST`. ``sys.modules["httpx"]`` (or a model SDK key) counts like
``import_module``; a name another repo module re-exports from another HTTP stack (``from
.direct_transport import httpcore``) counts as importing that stack, and the four modules that
may import httpcore for identity checks may use it only in a type/identity position.

**Stated limit.** This is a static scan without types, so it does not catch every possible bare
client. A client built from a ledgered client's class (``type(client)(…)``,
``client.__class__(…)``) is a bare ``httpx.AsyncClient`` the scan does not follow, and a class
classified here because its host comes from a constructor argument is only a finding where it
is built *with* that argument: an instance built without it and given a host attribute
afterwards (``q = QdrantVectorStore(dimension=1); q.url = …``, ``setattr`` included) is not.

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
from collections import ChainMap
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
    # The callers of every send-through (a sender whose host its caller decides), checked
    # one by one: none of these reasons rests on a further caller (it passes no parameter
    # of its own as the host, or that caller is a finding too).
    ("agents/core/llm/router.py", "LLMRouter.detect"):
        "hands _check/_fetch_loaded_model the router's own lm_studio_url/ollama_url (default "
        "localhost) + /v1/models or /api/tags: header-less GETs, no prompt",
    ("agents/core/llm/router.py", "LLMRouter.refresh_availability"):
        "hands _check the router's own lm_studio_url/ollama_url + /v1/models or /api/tags",
    ("agents/core/llm/router.py", "LLMRouter.refresh_active_model"):
        "hands _fetch_loaded_model the router's own lm_studio_url/ollama_url + /v1/models or "
        "/api/tags to adopt the loaded model id; no prompt",
    ("agents/core/llm/hybrid_router.py", "HybridRouter.detect"):
        "calls the inherited LLMRouter._check on its own ollama_url + /api/tags (availability); "
        "header-less GET, no prompt",
    ("agents/core/llm/providers/packages.py", "ProviderPackageStore.authorize_native_egress"):
        "calls transport._check(request), the admitted native transport's own request check, not "
        "LLMRouter._check: private send-through methods are matched by name and the name is shared",
    ("agents/core/llm/lmstudio_control.py", "LMStudioController._available_models"):
        "hands _default_models the controller's own server_url (default loopback LM Studio) for "
        "GET /v1/models; header-less, no prompt",
    ("agents/core/llm/local_model_inventory.py", "_refresh_raw_provider_cache"):
        "hands _probe_providers the LM Studio/Ollama URLs it was given by _raw_provider_snapshot "
        "(itself a finding); catalog/residency GETs only",
    ("agents/core/llm/local_model_inventory.py", "_raw_provider_snapshot"):
        "forwards the LM Studio/Ollama URLs get_local_model_inventory read off the hub router "
        "(itself a finding) to the cache refresh; catalog/residency GETs only",
    ("agents/core/llm/local_model_inventory.py", "get_local_model_inventory"):
        "reads lm_studio_url/ollama_url off the hub router (the one handed in, else the "
        "orchestrator's; default localhost) for catalog/residency GETs; no prompt, image or "
        "credential (a caller passing router= is a finding of its own)",
    ("agents/core/workspace/llm.py", "HubEngine.posture"):
        "hands _server_answers the hub router's active backend: _probe_target admits only an LM "
        "Studio/Ollama backend and reads that backend's own base_url; a liveness GET, no prompt",
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
    "agents/cli/mcp_catalog.py": (
        "the one-shot loopback listener of `nerva mcp login`: a stdlib HTTP server on 127.0.0.1 that "
        "receives the sign-in redirect and serves one tiny page; it dials nothing and carries no prompt",
        frozenset({"_serve_until"})),
    "agents/core/acp/server.py": (
        "G11's ACP agent hands its own JSON-RPC dispatcher (AcpServer.handle_request, the "
        "editor's stdio requests) to its connection; it is not an httpx transport, dials "
        "nothing itself, and the prompt reaches the hub only through the Backend's hub routes",
        frozenset({"AcpServer.connect"})),
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
    "agents/core/channels/delivery_ledger.py": (
        "classifies a channel send failure for the delivery receipt: reads the httpx exception "
        "classes with isinstance and the error response's JSON body; it dials nothing and carries "
        "no prompt",
        frozenset({"classify_send_failure"})),
    "agents/core/channels/reconnect.py": (
        "classifies a channel connection failure for the reconnect backoff: reads the httpx "
        "exception classes with isinstance; it dials nothing and carries no prompt",
        frozenset({"classify_exception"})),
    "agents/core/channels/telegram.py": (
        "Telegram Bot API channel transport (messages to/from the owner's chat)",
        frozenset({"TelegramChannel.__init__", "TelegramChannel.start"})),
    "agents/core/cameras/frigate.py": (
        "Frigate NVR API on the owner's LAN", frozenset({"_FrigateHTTP.request_bytes"})),
    "agents/core/house/home_assistant.py": (
        "Home Assistant REST API on the owner's LAN. _HttpxREST.request refuses any destination "
        "but a literal LAN address before a client exists (test_the_house_transports_refuse_"
        "every_non_lan_destination); its callers are checked: __init__ builds it, snapshot "
        "hands it the validated origin pinned to its resolved LAN address (_runtime_endpoint)",
        frozenset({"_HttpxREST.request", "HomeAssistantAdapter.__init__",
                   "HomeAssistantAdapter.snapshot"})),
    "agents/core/house/actuation.py": (
        "POSTs an approved Home Assistant service call through the adapter's REST transport to "
        "the adapter's validated origin pinned to its resolved LAN address (_runtime_endpoint); "
        "the transport refuses any non-LAN destination itself",
        frozenset({"HomeAssistantServiceDriver._adapter_service_call"})),
    "agents/core/house/wled.py": (
        "WLED light controller JSON API on the LAN. HttpxJSONTransport refuses any destination "
        "whose origin fails validate_wled_origin (test_the_house_transports_refuse_every_non_lan_"
        "destination); its callers are checked: __init__ builds it with the bridge's allowlist, "
        "_apply hands it the validated origin + /json/state",
        frozenset({"HttpxJSONTransport.__call__", "WLEDBridge.__init__", "WLEDBridge._apply"})),
    "agents/core/routers/onboarding.py": (
        "local model inventory of the hub's own router (get_local_model_inventory(router="
        "llm_router)): catalog/residency GETs of its configured LM Studio/Ollama servers; no prompt",
        frozenset({"_model_snapshot"})),
    "agents/core/image_generation_runtime.py": (
        "hands the local image backend classes to the provider, which builds them from the "
        "registry config it re-checks (provider.config(args) == config); both backends refuse a "
        "non-loopback base_url before any send (ComfyUIBackend.generate, "
        "LocalOpenAIImageBackend.generate), so the image prompt stays on the machine",
        frozenset({"LocalImageRuntime.execute.comfyui"})),
    "agents/core/memory/graph.py": (
        "Neo4j HTTP transaction endpoint (graph database)",
        frozenset({"Neo4jGraph._check_connection", "Neo4jGraph._call_neo4j", "Neo4jGraph.clear"})),
    "agents/core/memory/qdrant_store.py": (
        "Qdrant vector database REST API", frozenset({"QdrantVectorStore.__init__"})),
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


# Functions whose own code refuses every destination outside a fixed set (or records it in
# the egress ledger under its row and checks it against that row's policy) before transport
# entry, so a host handed to them is not a caller-supplied hole: a destination's trace ends
# there (a factory on this list is still a finding to call). (file, qualname) -> the code that
# pins it and the test that proves it. A stale entry fails
# `test_every_exemption_is_still_needed_and_justified`.
_PINNED_DESTINATIONS: dict[tuple[str, str], str] = {
    ("agents/core/llm/model_setup.py", "_client"):
        "a non-loopback URL raises OllamaURLNotLoopback, and the client's request hook refuses "
        "every non-loopback destination before transport entry "
        "(test_the_model_setup_factory_refuses_every_non_loopback_destination)",
    ("agents/core/http_client.py", "PluginHTTPClient._request_pinned"):
        "the plugin egress choke point: _guard checks the host against the plugin's policy and "
        "records the plugin's ledger row before the pinned send (tests/test_plugin_egress.py)",
    ("agents/core/http_client.py", "PluginHTTPClient.stream"):
        "the streaming twin of _request_pinned: the same _guard policy check and plugin ledger "
        "row before the pinned send (tests/test_plugin_egress.py)",
    ("agents/core/house/home_assistant.py", "_validated_origin"):
        "returns only an owner-allowlisted or LAN-literal origin whose every resolved address is "
        "on the LAN, else raises HAConfigError (tests/test_h30_house_adapter.py)",
    ("agents/core/house/wled.py", "validate_wled_origin"):
        "the same LAN-only origin rule for the WLED strip, else WLEDConfigError "
        "(tests/test_wled_bridge.py)",
    ("agents/core/cameras/frigate.py", "_FrigateHTTP._resolve_pinned"):
        "re-resolves the configured Frigate origin before every attempt and refuses it unless "
        "every address is an allowed LAN IP (lan_origin_required); the send is pinned to it",
}


# Functions that store into, mutate or hand on a client's event hooks (round-5 review: a
# ledgered client whose hooks are replaced is a bare client). Anywhere in agents/, in or out
# of the prompt scope; (file, qualname) -> why that rewiring cannot drop the egress recorder or
# slip a hook past it. A stale key fails `test_every_exemption_is_still_needed_and_justified`.
HOOK_REWIRING_ALLOWLIST: dict[tuple[str, str], str] = {
    ("agents/core/llm/providers/native_transport.py", "native_admitted_client"):
        "replaces llm_async_client's last request hook with the same egress recorder labelled "
        "with the native protocol backend and wraps the quota hook so a refusal is recorded; then "
        "guard.seal_hooks() freezes both hook tuples and AdmittedNativeTransport._check refuses "
        "any request whose hooks differ from them or carry other than one recorder (hooks_intact)",
    ("agents/core/llm/deepinfra.py", "DeepInfraBackend.__init__"):
        "inserts the DeepInfra physical-request check BEFORE the egress recorder, after refusing "
        "a client whose last hook is not the recorder; _send and the stream refuse to send unless "
        "hooks[-2] is that check and hooks[-1] the recorder",
    ("agents/core/llm/video_policy.py", "native_video_request_scope"):
        "for one native video send: appends a final request hook after the egress recorder that "
        "refuses if any hook was added after it, wraps the response hooks so a failing one "
        "refuses (each wrapper calls the original), and restores both on exit; no request hook "
        "llm_async_client installed is removed or replaced",
    ("agents/core/llm/vision_policy.py", "_native_request_scope"):
        "for one vision send: appends a final request hook after the egress recorder that refuses "
        "if any hook was added after it, and removes only that hook on exit",
    ("agents/core/ingestion/embedding_policy.py", "install_hook"):
        "appends the ledger's own llm_sync_request_hook(provider) to the embedder's LM Studio "
        "client when it is missing; it only ever adds the ledger hook",
    ("agents/core/media_backends/local_openai_image.py", "LocalOpenAIImageBackend.generate"):
        "appends the physical-request check (direct transport, exact URL and body, no "
        "credentials) to its own literal-loopback image client, which has no ledger hook to drop "
        "(local image generation is outside the ledger; see PROMPT_SCOPE_ALLOWLIST)",
    ("agents/core/video_analysis.py", "VideoHTTPClient._pinned_client"):
        "appends the current-approval and no-credential request check to the plugin's pinned "
        "client; plugin egress rows are recorded by PluginHTTPClient._guard before the send, not "
        "by a hook, so no ledger hook is there to drop",
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
# is a class whose construction leaves one on a public attribute of the instance (or whose
# body holds one): building or subclassing it is a finding, but the instance is not itself a
# client (what reaches inside it is checked by name). "carrier:<rel>:<qualname>" is a class
# whose factory methods or private client attributes hold one: constructing it and calling
# its other methods is fine.
_FACTORY, _HOLDER, _CARRIER = "factory:", "holder:", "carrier:"
# A bare client is also followed by where it is pointed (round-4 review: a classified function
# that sends a caller's method, URL and body through a client it builds). The host a send
# dials is traced back through locals, f-strings, concatenations, urlunsplit, a client's
# base_url, factories, other senders and a class's own attributes. "sender:<rel>:<qualname>" is
# a repo function whose bare client dials a host one of its parameters decides: every read of
# it is a finding, like a factory's, and a caller handing it its own parameter is a sender too.
# "sendercls:<rel>:<qual>" is a class with such a method: building, subclassing or reading it is
# a finding, and its instances are followed like a client (a private attribute holding one, a
# method returning one). "injected:<rel>:<qual>" is a class whose bare client dials a host an
# attribute set from a method parameter decides (a constructor-injected URL): building or
# subclassing it is a finding.
_SENDER, _SENDER_CLS, _INJECTED = "sender:", "sendercls:", "injected:"
_CLASS_GATES = (_HOLDER, _SENDER_CLS, _INJECTED)    # building or subclassing one is a finding
_SELF = frozenset({"self", "cls"})
# Calls that wrap their arguments into the value they return (a class, ``dict``,
# ``functools.partial``, ``contextlib.closing``, an ``ExitStack``): a bare client handed to
# one is handed out with it.
_WRAPPERS = frozenset({"dict", "partial", "closing", "aclosing", "nullcontext", "cast",
                       "enter_context", "enter_async_context", "proxy", "SimpleNamespace"})
# httpx client methods that send (or build the request that is sent) to their URL argument.
_SEND_VERBS = frozenset({"get", "post", "put", "patch", "delete", "head", "options",
                         "request", "stream", "send", "build_request"})
_METHOD_FIRST = frozenset({"request", "stream", "build_request"})   # (method, url, …)
# Keywords that point a client (httpx ``base_url``, an SDK's ``base_url`` / ``host``).
_BASE_KEYWORDS = ("base_url", "host")


def _pieces(node: ast.AST) -> list:
    """A URL expression as the pieces it concatenates: str constants and expressions."""
    if isinstance(node, ast.JoinedStr):
        return [v.value for v in node.values]    # Constant -> its str, FormattedValue -> its expr
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return [*_pieces(node.left), *_pieces(node.right)]
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    return [node]


def _host_parts(node: ast.AST) -> list[ast.AST]:
    """The sub-expressions of a URL that can decide the host it dials: everything before the
    first ``/``, ``?`` or ``#`` after the scheme (a parameter only in the path or query
    cannot move the request), the scheme and netloc of ``urlunsplit``/``urlunparse``, the
    whole of any other expression."""
    if isinstance(node, ast.Call):
        name = (_attr_chain(node.func) or [""])[-1]
        if (name in {"urlunsplit", "urlunparse"} and node.args
                and isinstance(node.args[0], (ast.Tuple, ast.List))):
            return [p for e in node.args[0].elts[:2] for p in _host_parts(e)]
        if name in {"rstrip", "strip", "lower", "removesuffix"} and isinstance(node.func, ast.Attribute):
            return _host_parts(node.func.value)
        if name in {"str", "URL"} and len(node.args) == 1 and not node.keywords:
            return _host_parts(node.args[0])
        return [node]
    parts: list[ast.AST] = []
    scheme = False
    for piece in _pieces(node):
        if isinstance(piece, str):
            text = piece
            if not scheme and "://" in text:
                text, scheme = text.split("://", 1)[1], True
            if any(c in text for c in "/?#"):
                break
        else:
            parts.append(piece)
    return parts


def _url_args(call: ast.Call, verb: str) -> list[ast.AST]:
    """The URL argument of a client send (``url=``, by position, or a splat)."""
    url = _keyword(call, "url")
    if url is not None:
        return [url]
    index = 1 if verb in _METHOD_FIRST else 0
    for i, arg in enumerate(call.args):
        if isinstance(arg, ast.Starred):
            return [arg.value]
        if i == index:
            return [arg]
    return [k.value for k in call.keywords if k.arg is None]    # only a splat can carry it


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
    return kind in (_CTOR, _HELPER) or kind.startswith(
        (_SDK_CTOR, _SDK, _FACTORY, _CARRIER, _SENDER, *_CLASS_GATES))


def _hands_out_kind(kind: str) -> bool:
    """A resolved reference that is a bare client (or a sender), or builds one when called."""
    return kind in (_CTOR, _HELPER, _HTTPX) or kind.startswith(
        (_SDK_CTOR, _SDK, _FACTORY, _SENDER, _SENDER_CLS))


def _names(quals) -> str:
    return ", ".join(sorted(quals))


_GATE_WHAT = {
    _FACTORY: "hands out a bare client",
    _SENDER: "sends through a bare client to a host its caller decides",
    _HOLDER: "whose instances hold a bare client",
    _SENDER_CLS: "whose methods send through a bare client to a host their caller decides",
    _INJECTED: "whose bare client dials a host its constructor's caller decides",
}
_CLASS_KINDS = (_CARRIER, *_CLASS_GATES)


def _target(kind: str) -> str:
    """``rel:qual`` of a factory/sender/class kind."""
    return kind.split(":", 1)[1]


def _inherited(bindings, classdef: ast.ClassDef, facts) -> frozenset[str]:
    """Every carrier/holder/sender class ``classdef`` inherits from, at any depth."""
    out: set[str] = set()
    for base in classdef.bases:
        kind = bindings.resolve(base)
        if kind is not None and kind[0].startswith(_CLASS_KINDS):
            out.add(_target(kind[0]))
            out |= facts.ancestors.get(_target(kind[0]), frozenset())
    return frozenset(out)


class _Facts:
    """Where bare clients leave the code that builds them. Computed from every scanned
    module to a fixed point (a factory that returns another factory's client is one)."""

    def __init__(self, defs=None, methods=None, attrs=None, owners=frozenset(), dest=None,
                 calls=None, ancestors=None, pins=frozenset(), sends=None) -> None:
        # rel -> {name bound at module level: factory/holder/carrier/sender kind}
        self.defs: dict[str, dict[str, str]] = defs or {}
        # method name -> {"rel:Class.method"} that return/yield a bare client
        self.methods: dict[str, frozenset[str]] = methods or {}
        # attribute name -> {"rel:Class" or "rel:function"} that store a bare client (or a
        # sender instance) in it: a private attribute of a class, any attribute planted on
        # another object
        self.attrs: dict[str, frozenset[str]] = attrs or {}
        # (rel, Class, attribute): the class stores a bare client in that attribute itself
        self.owners: frozenset[tuple[str, str, str]] = owners
        # "rel:qual" of a sender, a factory pointed by a parameter, a sender method or an
        # injected class -> (its signature, the parameters that decide the host, whether a
        # call binds the first parameter)
        self.dest: dict[str, tuple[tuple, frozenset[str], bool]] = dest or {}
        # rel -> findings no reference resolves: a destination handed to a sender instance's
        # method or to the class's own sender method
        self.calls: dict[str, tuple[tuple[str, int, str], ...]] = calls or {}
        # "rel:Class" -> every carrier/holder/sender class it inherits from, at any depth
        self.ancestors: dict[str, frozenset[str]] = ancestors or {}
        # (rel, qual) of _PINNED_DESTINATIONS a destination actually flowed into
        self.pins: frozenset[tuple[str, str]] = pins
        # private method name -> {"rel:Class.method"} that send through a bare client to a
        # host their caller decides (matched by name, like a factory method; a public one
        # makes its class a sender class instead)
        self.sends: dict[str, frozenset[str]] = sends or {}

    def _key(self):
        return (self.defs, self.methods, self.attrs, self.owners, self.dest, self.calls,
                self.ancestors, self.pins, self.sends)

    def __eq__(self, other) -> bool:
        return isinstance(other, _Facts) and self._key() == other._key()

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
    """One ``def`` and what its own body (not a nested scope) binds, returns, stores and
    calls. ``scope`` sees the enclosing defs' locals too (a closure)."""

    __slots__ = ("qual", "node", "cls", "method", "bound", "parent", "positional", "params",
                 "signature", "local", "scope", "returns", "stores", "calls", "globals", "plain")

    def __init__(self, qual: str, node: ast.AST, cls: str | None, method: bool,
                 parent: _Function | None = None) -> None:
        self.qual, self.node, self.cls, self.method, self.parent = qual, node, cls, method, parent
        args = node.args
        self.positional = tuple(a.arg for a in (*args.posonlyargs, *args.args))
        static = any((_attr_chain(d) or [""])[-1] == "staticmethod" for d in node.decorator_list)
        self.bound = method and not static and bool(self.positional)
        # every parameter a caller fills (the bound ``self`` / ``cls`` is not one)
        self.params = frozenset((*self.positional[1 if self.bound else 0:],
                                 *(a.arg for a in args.kwonlyargs),
                                 *(a.arg for a in (args.vararg, args.kwarg) if a is not None)))
        # (positional, keyword-only, *args name, **kwargs name): how a call fills them
        self.signature = (self.positional, tuple(a.arg for a in args.kwonlyargs),
                          args.vararg.arg if args.vararg else None,
                          args.kwarg.arg if args.kwarg else None)
        self.local: dict[str, list[ast.AST]] = {}       # local name -> every value bound to it
        self.scope = ChainMap(self.local, *(parent.scope.maps if parent else ()))
        self.returns: list[ast.AST] = []                # every returned or yielded value
        self.stores: list[tuple[tuple[str, ...], ast.AST]] = []   # attribute chain <- value
        self.calls: list[ast.Call] = []                 # every call its own body makes
        self.globals: set[str] = set()                  # names it declares ``global``
        self.plain: set[str] = set()                    # names it binds as plain locals


_SCOPES = frozenset({ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda})
_RETURNS = frozenset({ast.Return, ast.Yield, ast.YieldFrom})
_BINDERS = frozenset({ast.Assign, ast.AnnAssign, ast.With, ast.AsyncWith})
_LOOP_BINDERS = frozenset({ast.For, ast.AsyncFor, ast.comprehension})


class _Item(ast.expr):
    """A value stored as an element of a container (``pool[key] = client``): the container
    holds a client, but is not one (``pool.get(key)`` is a dict read, not a send)."""

    _fields = ("value",)


def _own_nodes(body):
    """Every node of a body that is not inside a nested scope (the scope node itself is)."""
    pending = list(body)
    while pending:
        node = pending.pop()
        yield node
        if type(node) not in _SCOPES:
            pending.extend(ast.iter_child_nodes(node))


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
        self.fn_of: dict[int, _Function] = {}               # id(def node) -> its _Function
        self.defs: dict[str, _Function] = {}                # module-level def name -> function
        self.method_of: dict[tuple[str, str], _Function] = {}   # (class, method) -> function
        self.classes: dict[str, ast.ClassDef] = {}
        self.methods: dict[str, set[str]] = {}              # class -> method names it defines
        self.self_attrs: dict[str, set[str]] = {}           # class -> attributes it assigns on self
        self.self_values: dict[str, dict[tuple[str, ...], list[ast.AST]]] = {}
        # class -> attribute -> every (function that sets it or None for the class body, value)
        self.self_sources: dict[str, dict[str, list[tuple[_Function | None, ast.AST]]]] = {}
        self.class_body: dict[str, list[tuple[str, ast.AST]]] = {}
        # (global name, value, the function binding it or None at module level): a lazily set
        # ``global`` and a module dict/object a function fills count as module globals too
        self.globals: list[tuple[str, ast.AST, _Function | None]] = [
            (t.id, v, None) for node in self.tree.body for t, v in _assignments(node)
            if isinstance(t, ast.Name)]
        # Names bound to the sys module (`import sys as _s`) and to sys.modules (`from sys
        # import modules`): a lookup through either can hand on httpx without an import.
        self.sys_names = {alias.asname or "sys" for node in self.imports if isinstance(node, ast.Import)
                          for alias in node.names if alias.name == "sys"}
        self.sys_modules_names = {alias.asname or "modules" for node in self.imports
                                  if isinstance(node, ast.ImportFrom) and node.module == "sys"
                                  and not node.level for alias in node.names if alias.name == "modules"}
        self._index(self.tree.body, [], None, False, None)
        top = {name for name, _, _ in self.globals} | {n for fn in self.functions for n in fn.globals}
        for fn in self.functions:
            for chain, value in fn.stores:
                head = chain[0]
                if (head in top and head not in fn.params and head not in fn.plain
                        and head not in fn.globals and head not in _SELF):
                    self.globals.append((head, value, fn))      # `_POOL[k] = …`, `_REG.c = …`

    def _index(self, body, scope: list[str], cls: str | None, in_class: bool,
               parent: _Function | None) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = [*scope, node.name]
                fn = self._function(".".join(qual), node, cls, in_class, parent)
                self.functions.append(fn)
                self.fn_of[id(node)] = fn
                if in_class:
                    self.methods[cls].add(node.name)
                    self.method_of[(cls, node.name)] = fn
                elif parent is None and cls is None:
                    self.defs[node.name] = fn
                self._index(node.body, qual, cls, False, fn)
            elif isinstance(node, ast.ClassDef):
                qual = ".".join([*scope, node.name])
                self.classes[qual] = node
                self.methods.setdefault(qual, set())
                self.self_attrs.setdefault(qual, set())
                self.self_sources.setdefault(qual, {})
                values = self.self_values.setdefault(qual, {})
                self.class_body[qual] = [(t.id, v) for stmt in node.body
                                         for t, v in _assignments(stmt) if isinstance(t, ast.Name)]
                for name, value in self.class_body[qual]:
                    values.setdefault(("self", name), []).append(value)
                    self.self_sources[qual].setdefault(name, []).append((None, value))
                self._index(node.body, [*scope, node.name], qual, True, parent)
            else:
                for field in ("body", "orelse", "finalbody", "handlers", "cases"):
                    self._index(getattr(node, field, ()) or (), scope, cls, in_class, parent)

    def _function(self, qual: str, node: ast.AST, cls: str | None, method: bool,
                  parent: _Function | None) -> _Function:
        fn = _Function(qual, node, cls, method, parent)
        own = list(_own_nodes(node.body))
        fn.globals.update(n for child in own if isinstance(child, ast.Global) for n in child.names)
        for child in own:
            kind = type(child)
            if kind in _RETURNS:
                if child.value is not None:
                    fn.returns.append(child.value)
            elif kind is ast.NamedExpr:
                self._bind(child.target, child.value, fn)
            elif kind in _BINDERS:
                for target, value in _assignments(child):
                    self._bind(target, value, fn)
            elif kind in _LOOP_BINDERS:      # `for x in …`: x is a plain local, not a global
                fn.plain.update(n.id for n in ast.walk(child.target) if isinstance(n, ast.Name))
            elif kind in (ast.FunctionDef, ast.AsyncFunctionDef):
                fn.local.setdefault(child.name, []).append(child)   # a nested def is a value
                fn.plain.add(child.name)
            elif kind is ast.Call:
                fn.calls.append(child)
                args = child.args
                if (isinstance(child.func, ast.Name) and child.func.id == "setattr" and len(args) == 3
                        and isinstance(args[1], ast.Constant) and isinstance(args[1].value, str)):
                    # `setattr(self, "_c", client)` binds like `self._c = client`
                    self._bind(ast.Attribute(value=args[0], attr=args[1].value, ctx=ast.Store()),
                               args[2], fn)
        return fn

    def _bind(self, target: ast.AST, value: ast.AST, fn: _Function) -> None:
        if isinstance(target, ast.Starred):
            target = target.value
        if isinstance(target, ast.Name):
            fn.local.setdefault(target.id, []).append(value)
            if target.id in fn.globals:
                self.globals.append((target.id, value, fn))     # `global _C; _C = …`
            else:
                fn.plain.add(target.id)
            return
        if isinstance(target, (ast.Tuple, ast.List)):     # an unpaired unpack: any name may be it
            for element in target.elts:
                self._bind(element, value, fn)
            return
        if isinstance(target, ast.Subscript):
            value = _Item(value=value)
        chain = tuple(_attr_chain(target.value if isinstance(target, ast.Subscript) else target))
        if len(chain) == 1:                                # `clients[key] = client`
            fn.local.setdefault(chain[0], []).append(value)
            fn.stores.append((chain, value))
        elif chain:
            if chain[0] in _SELF and fn.cls is not None:   # `self._client = …`, `self._pool[k] = …`
                self.self_attrs[fn.cls].add(chain[1])
                self.self_values[fn.cls].setdefault(("self", *chain[1:]), []).append(value)
                self.self_sources[fn.cls].setdefault(chain[1], []).append((fn, value))
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
        if base[0].startswith((_FACTORY, _SENDER, *_CLASS_GATES)):
            return base     # a member of a factory, sender, gated class or client global reaches it
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


# ── a ledgered client turned bare (round-5 review) ──────────────────────────
# httpx replaces every hook when ``client.event_hooks`` is assigned, so a backend that adds its
# own logging hook that way drops the egress recorder llm_async_client installed, and a hook
# list cleared, popped or handed to a helper loses it the same way; a hook appended after the
# recorder can still rewrite the request it recorded. Every store to, mutation of, deletion
# from or hand-off of a client's hooks is a finding unless its exact (file, qualname) is on
# HOOK_REWIRING_ALLOWLIST. The hooks are reached through the attribute (``event_hooks`` or
# httpx's private ``_event_hooks``), ``getattr``/``setattr``/``vars()``/``__dict__``, and every
# local or attribute alias of the hook dict or of one of its hook lists.
_HOOK_ATTRS = frozenset({"event_hooks", "_event_hooks"})
_HOOK_MUTATORS = frozenset({"append", "extend", "insert", "remove", "pop", "clear", "update",
                            "setdefault", "popitem", "sort", "reverse", "__setitem__",
                            "__delitem__", "__iadd__", "__ior__", "__init__"})
# Calls that only read (or copy) a hook container handed to them.
_HOOK_READERS = frozenset({"tuple", "list", "dict", "len", "zip", "any", "all", "iter",
                           "reversed", "enumerate", "sorted", "set", "frozenset", "id", "type",
                           "repr", "str", "bool", "next", "isinstance", "getattr", "hasattr",
                           "callable"})
_HOOK_SETTERS = frozenset({"setattr", "delattr", "__setattr__", "__delattr__"})
_HOOKS_REWIRED = "rewires a client's event hooks (the egress ledger hook can be dropped or bypassed)"


def _callee(func: ast.AST) -> str:
    return func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""


def _const_str(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _instance_dict(node: ast.AST) -> bool:
    """``vars(obj)`` or ``obj.__dict__``: the dict httpx keeps ``_event_hooks`` in."""
    return ((isinstance(node, ast.Call) and _callee(node.func) == "vars")
            or (isinstance(node, ast.Attribute) and node.attr == "__dict__"))


class _HookRewirings:
    """Every place one module stores into, mutates, deletes from or hands on a client's event
    hooks. Flow-insensitive, like the rest of the scan: a name bound anywhere in a function
    (or an enclosing one) to the hook dict or to one hook list is an alias of it everywhere in
    that function, and an attribute chain bound to one (``self._hooks = c.event_hooks["request"]``)
    is an alias everywhere in the module."""

    def __init__(self, tree: ast.Module) -> None:
        self.findings: list[tuple[str, int, str]] = []
        self.chains: dict[tuple[str, ...], int] = {}
        self._scope: list[str] = []
        self._collect = True
        for _ in range(5):       # an attribute alias bound in one method and used in another
            before = dict(self.chains)
            self._visit(tree.body, {})
            if self.chains == before:
                break
        self._collect = False
        self._visit(tree.body, {})

    def depth(self, node: ast.AST, names: dict[str, int]) -> int | None:
        """0: a client's hook dict, 1: one of its hook lists, None: anything else (one hook, a
        copy, an unrelated value)."""
        if isinstance(node, ast.NamedExpr):
            return self.depth(node.value, names)
        if isinstance(node, ast.Attribute):
            if node.attr in _HOOK_ATTRS:
                return 0
            chain = tuple(_attr_chain(node))
            return self.chains.get(chain) if chain else None
        if isinstance(node, ast.Name):
            return names.get(node.id)
        if isinstance(node, ast.Subscript):
            if _instance_dict(node.value) and _const_str(node.slice) in _HOOK_ATTRS:
                return 0
            return 1 if self.depth(node.value, names) == 0 else None
        if isinstance(node, ast.Call):
            name = _callee(node.func)
            if name == "getattr" and len(node.args) >= 2 and _const_str(node.args[1]) in _HOOK_ATTRS:
                return 0
            if isinstance(node.func, ast.Attribute) and name in {"get", "setdefault"} and node.args:
                if _instance_dict(node.func.value) and _const_str(node.args[0]) in _HOOK_ATTRS:
                    return 0
                if self.depth(node.func.value, names) == 0:
                    return 1
            return None
        if isinstance(node, (ast.IfExp, ast.BoolOp)):
            options = [node.body, node.orelse] if isinstance(node, ast.IfExp) else node.values
            found = [d for d in (self.depth(o, names) for o in options) if d is not None]
            return min(found) if found else None
        return None

    def _aliases(self, nodes: list[ast.AST], inherited: dict[str, int]) -> dict[str, int]:
        names = dict(inherited)
        pairs = [pair for node in nodes if type(node) in _BINDERS for pair in _assignments(node)]
        pairs += [(node.target, node.value) for node in nodes if isinstance(node, ast.NamedExpr)]
        changed = True
        while changed:
            changed = False
            for target, value in pairs:
                depth = self.depth(value, names)
                if depth is None:
                    continue
                if isinstance(target, ast.Name):
                    key, store = target.id, names
                else:
                    key, store = tuple(_attr_chain(target)), self.chains
                    if len(key) < 2:
                        continue
                if store.get(key, 2) > depth:
                    store[key] = depth
                    changed = True
        return names

    def _visit(self, body: list[ast.AST], inherited: dict[str, int]) -> None:
        nodes = list(_own_nodes(body))
        names = self._aliases(nodes, inherited)
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self._scope.append(node.name)
                self._visit(node.body, names)
                self._scope.pop()
            elif isinstance(node, ast.Lambda):
                if not self._collect and self.depth(node.body, names) is not None:
                    self._hit(node, "a lambda hands a hook container out")
                self._visit([node.body], names)
            elif not self._collect:
                self._check(node, names)

    def _hit(self, node: ast.AST, how: str) -> None:
        self.findings.append((".".join(self._scope) or "<module>", getattr(node, "lineno", 0),
                              f"{_HOOKS_REWIRED}: {how}"))

    def _check(self, node: ast.AST, names: dict[str, int]) -> None:
        def depth(value: ast.AST) -> int | None:
            return self.depth(value, names)

        if isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(node.ctx, (ast.Store, ast.Del)):
            verb = "deletes" if isinstance(node.ctx, ast.Del) else "assigns"
            if isinstance(node, ast.Attribute) and node.attr in _HOOK_ATTRS:
                self._hit(node, f"{verb} .{node.attr}")
            elif isinstance(node, ast.Subscript) and (
                    depth(node.value) is not None
                    or (_instance_dict(node.value) and _const_str(node.slice) in _HOOK_ATTRS)):
                self._hit(node, f"{verb} an entry of a hook container")
        elif (isinstance(node, ast.AugAssign) and isinstance(node.target, (ast.Name, ast.Attribute))
              and getattr(node.target, "attr", None) not in _HOOK_ATTRS and depth(node.target) is not None):
            self._hit(node, "extends a hook container in place")
        elif (isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load)
              and node.attr in _HOOK_MUTATORS and depth(node.value) is not None):
            self._hit(node, f"reaches .{node.attr} of a hook container")
        elif isinstance(node, (ast.Return, ast.Yield)) and node.value is not None and depth(node.value) is not None:
            self._hit(node, "hands a hook container out of the function")
        elif isinstance(node, (ast.List, ast.Tuple, ast.Set, ast.Dict)) and isinstance(
                getattr(node, "ctx", ast.Load()), ast.Load) and any(
                v is not None and depth(v) is not None
                for v in (node.values if isinstance(node, ast.Dict) else node.elts)):
            self._hit(node, "puts a hook container in another container")
        elif isinstance(node, ast.Call):
            name = _callee(node.func)
            consts = {c for c in map(_const_str, node.args) if c is not None}
            if name in _HOOK_SETTERS and consts & _HOOK_ATTRS:
                self._hit(node, f"{name}s the hooks attribute by name")
            elif name == "getattr" and len(node.args) >= 2 and depth(node.args[0]) is not None and (
                    _const_str(node.args[1]) in _HOOK_MUTATORS):
                self._hit(node, f"reaches .{_const_str(node.args[1])} of a hook container by name")
            elif (isinstance(node.func, ast.Attribute) and _instance_dict(node.func.value)
                  and name in _HOOK_MUTATORS
                  and (consts | {k.arg for k in node.keywords if k.arg}) & _HOOK_ATTRS):
                self._hit(node, f"rewrites the hooks through the instance dict (.{name})")
            elif name not in _HOOK_READERS and not (
                    isinstance(node.func, ast.Attribute) and depth(node.func.value) is not None):
                handed = [a.value if isinstance(a, ast.Starred) else a for a in node.args]
                handed += [k.value for k in node.keywords]
                if any(depth(arg) is not None for arg in handed):
                    self._hit(node, f"hands a hook container to {name or 'a call'}")


def _hook_findings(module: _Module) -> list[tuple[str, int, str]]:
    found = getattr(module, "hook_findings", None)
    if found is None:
        found = module.hook_findings = _HookRewirings(module.tree).findings
    return found


class _Scanner:
    """Collect (qualname, line, shape) for every bare-client path in one module.

    The rule is inverted on purpose (see the module docstring): every read of a bare
    constructor is a finding except in a type-only position, so a new hand-off shape is
    caught without the scanner having to know it."""

    def __init__(self, bindings: _Bindings) -> None:
        self.b = bindings
        # What no reference resolves (a destination handed to a sender instance) comes from
        # the analysis; everything else is found by walking the module.
        self.findings: list[tuple[str, int, str]] = [
            *bindings.facts.calls.get(bindings.module.rel, ()), *_hook_findings(bindings.module)]
        self._scope: list[str] = []
        self._transport: list[bool] = []
        self._call: list[ast.Call] = []               # the call whose func is being visited
        # (class qualname, every carrier/holder/sender class it inherits from)
        self._classes: list[tuple[str, frozenset[str]]] = []

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
        elif kind[0].startswith((_FACTORY, _SENDER)):
            prefix = _FACTORY if kind[0].startswith(_FACTORY) else _SENDER
            target, what = kind[0][len(prefix):], _GATE_WHAT[prefix]
            if role == "call":
                if prefix == _FACTORY or self._points(target):
                    self._hit(node, f"calls {target}, which {what}")
            elif not safe:
                self._hit(node, f"reads {target}, which {what}")
        elif kind[0].startswith(_CLASS_GATES):
            prefix = next(p for p in _CLASS_GATES if kind[0].startswith(p))
            target, what = kind[0][len(prefix):], _GATE_WHAT[prefix]
            if role == "call":
                if prefix != _INJECTED or self._points(target):
                    self._hit(node, f"constructs {target}, {what}")
            elif role == "base":
                self._hit(node, f"subclasses {target}, {what}")
            elif not safe:
                self._hit(node, f"reads {target}, {what}")
        return True     # resolved (a repo module or a carrier class included): nothing below

    def _points(self, target: str) -> bool:
        """The call being visited hands a sender (or an injected class) one of the parameters
        that decide its host, or a splat: one that passes none dials the callee's own default."""
        info = self.b.facts.dest.get(target)
        return info is None or not self._call or _passes(self._call[-1], info)

    def _class(self) -> tuple[str | None, frozenset[str]]:
        return self._classes[-1] if self._classes else (None, frozenset())

    def _member(self, node: ast.AST, recv: ast.AST, attr: str, role: str = "") -> None:
        """``recv.<attr>`` (or ``getattr(recv, "<attr>")``): a bare-client factory method
        read anywhere but as the reading class's own non-factory member, and a private
        client attribute read off another object or inherited from a carrier class."""
        facts, module = self.b.facts, self.b.module
        cls, inherits = self._class()
        if attr in facts.methods and not _own_member(module, facts, cls, recv, attr):
            self._hit(node, f"reaches .{attr}, which hands out a bare client "
                            f"({_names(facts.methods[attr])})")
        own = isinstance(recv, ast.Name) and recv.id in _SELF and (
            attr in module.methods.get(cls, ()) or attr in module.self_attrs.get(cls, ()))
        # The class's own call is judged where it passes a host (the analysis's finding);
        # its own sender handed on uncalled (``register(cap, self._send)``) is a finding.
        if attr in facts.sends and not (own and (role == "call" or attr in module.self_attrs.get(cls, ()))):
            self._hit(node, f"reaches .{attr}, which sends through a bare client to a host its "
                            f"caller decides ({_names(facts.sends[attr])})")
        if attr in facts.attrs:
            if not (isinstance(recv, ast.Name) and recv.id in _SELF):
                self._hit(node, f"reads .{attr}, the bare client {_names(facts.attrs[attr])} holds")
            elif facts.attrs[attr] & inherits:
                # inherited, even where the subclass sets it too: the base's own methods may
                # (re)build the bare client in it at any time
                self._hit(node, f"reads self.{attr}, a bare client inherited from "
                                f"{_names(facts.attrs[attr] & inherits)}")

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
            self._member(node, node.value, node.attr, role)
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

    def _sys_modules(self, node: ast.AST, container: ast.AST, key: ast.AST | None) -> None:
        """``sys.modules["httpx"]`` (``.get``, ``.setdefault``, ``.pop``, through any alias of
        ``sys`` or ``from sys import modules``): the httpx package or a model SDK reached without
        an import statement, exactly like ``import_module``."""
        name = _const_str(key)
        if name is None:
            return
        module = self.b.module
        if isinstance(container, ast.Attribute) and container.attr == "modules":
            base = container.value
            via_sys = ((_attr_chain(base) or [""])[-1] == "sys" or (
                isinstance(base, ast.Name) and base.id in module.sys_names) or (
                isinstance(base, ast.Call) and _callee(base.func) in {"__import__", "import_module"}
                and base.args and _const_str(base.args[0]) == "sys"))
        else:
            via_sys = isinstance(container, ast.Name) and container.id in module.sys_modules_names
        if not via_sys:
            return
        if name.split(".")[0] == "httpx":
            self._hit(node, "reaches httpx through sys.modules")
        elif _model_sdk(name):
            self._hit(node, "reaches a model SDK through sys.modules")

    def _v_Subscript(self, node, safe, role):
        key = node.slice
        self._sys_modules(node, node.value, key)
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
        self._call.append(node)
        self.visit(node.func, False, "ledgered" if ledgered else "call")
        self._call.pop()
        type_args: set[int] = set()
        named: set[int] = set()       # an attribute name argument, judged by _member
        if name in {"isinstance", "issubclass"}:
            type_args = set(range(1, len(node.args)))
        elif name == "cast":
            type_args = {0}
        elif name in {"getattr", "hasattr", "setattr"} and len(node.args) >= 2:
            attr = node.args[1]
            named = {1}
            if isinstance(attr, ast.Constant) and isinstance(attr.value, str):
                if attr.value in _RAW_SENDS and not self._in_transport():
                    self._hit(node, "reaches a raw transport send by name")
                elif attr.value in _CONSTRUCTORS | _HELPERS and self.b.resolve(node.args[0]):
                    self._hit(node, "reaches the bare client by name")
                elif name == "getattr":
                    self._member(node, node.args[0], attr.value)
        elif (name in {"get", "setdefault", "pop", "__getitem__"} and node.args
              and isinstance(node.func, ast.Attribute)):
            self._sys_modules(node, node.func.value, node.args[0])
        elif name in {"import_module", "__import__"} and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and str(first.value).split(".")[0] == "httpx":
                self._hit(node, "imports httpx dynamically")
            elif isinstance(first, ast.Constant) and _model_sdk(str(first.value)):
                self._hit(node, "imports a model SDK dynamically")
        for index, arg in enumerate(node.args):
            self.visit(arg, index in type_args, "named" if index in named else "")
        for keyword in node.keywords:
            self.visit(keyword.value, name == "TypeVar" and keyword.arg == "bound")

    def _v_Constant(self, node, safe, role):
        """A string naming a client attribute or a factory method (``vars(o).get("_c")``,
        ``o.__dict__.get("_c")``, ``operator.methodcaller("_http")``, ``attrgetter``):
        a finding unless the reading class names its own member."""
        value, facts = node.value, self.b.facts
        if role == "named" or not isinstance(value, str) or (
                value not in facts.attrs and value not in facts.methods and value not in facts.sends):
            return
        cls, inherits = self._class()
        module = self.b.module
        own = cls is not None and (value in module.self_attrs.get(cls, ())
                                   or value in module.methods.get(cls, ()))
        if own and not (facts.attrs.get(value, frozenset()) & inherits) and (
                f"{module.rel}:{cls}.{value}" not in facts.methods.get(value, ())
                | facts.sends.get(value, frozenset())):
            return
        self._hit(node, f"names .{value} as a string, which holds or hands out a bare client")

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
        inherits = _inherited(self.b, node, self.b.facts)
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


def _argument(call: ast.Call, signature, bound: bool, name: str) -> ast.AST | None:
    """The expression a call passes for parameter ``name`` of a callee with ``signature``
    (``*`` = any of them; a splat may fill any parameter it can reach)."""
    positional, kwonly, vararg, kwarg = signature
    names = positional[1:] if bound else positional
    if name == "*":
        values = [a.value if isinstance(a, ast.Starred) else a for a in call.args]
        values += [k.value for k in call.keywords]
        return ast.Tuple(elts=values, ctx=ast.Load()) if values else None
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    if name == vararg:
        extra = call.args[len(names):]
        return ast.Tuple(elts=list(extra), ctx=ast.Load()) if extra else None
    if name == kwarg:
        extra = [k.value for k in call.keywords if k.arg not in (*names, *kwonly)]
        return ast.Tuple(elts=extra, ctx=ast.Load()) if extra else None
    if name in names:
        index = names.index(name)
        for position, arg in enumerate(call.args):
            if isinstance(arg, ast.Starred):
                return arg.value
            if position == index:
                return arg
    splat = [k.value for k in call.keywords if k.arg is None]
    return splat[0] if splat and (name in names or name in kwonly) else None


def _passes(call: ast.Call, info) -> bool:
    """The call hands its callee one of the parameters that decide the host (or a splat)."""
    signature, names, bound = info
    return any(_argument(call, signature, bound, name) is not None for name in names)


def _split(source: str) -> tuple[str, str]:
    kind, _, name = source.partition(":")
    return kind, name


_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)
_NONE: frozenset[str] = frozenset()


class _Detector:
    """Which defs, classes and globals of one module hand a bare client out of themselves,
    and which host every bare client it builds is pointed at.

    A value hands one out when it is (or holds, as a tuple/list/dict element, a branch of a
    conditional, an awaited or subscripted value, a comprehension element, or an argument to
    a class/``dict``/``partial``/``closing`` that wraps it, or to a same-module helper that
    returns its argument) a bare construction, an unledgered model SDK client, a sender
    instance, a call of a factory, a read of one uncalled, a nested def returning one, or a
    name or ``self`` attribute this function or class binds to one. Calls of any other
    function are uses, not hand-outs: ``return await probe(client)`` keeps the client inside.

    The host a send dials is traced to its *sources*: ``p:<name>`` (a parameter of the
    sending function or of a def enclosing it), ``ctor:<name>`` / ``ctor:*`` (an attribute
    its class sets from a parameter of ``__init__`` / of another method) and ``base:<name>``
    (the base_url of a client handed in as parameter ``<name>``). Only the parts of a URL
    that can move the host are followed (a parameter in the path or query cannot), and a
    function on :data:`_PINNED_DESTINATIONS` (its code refuses, or records in the ledger,
    every destination before transport entry) ends a trace."""

    def __init__(self, module: _Module, bindings: _Bindings, facts: _Facts) -> None:
        self.m, self.b, self.f = module, bindings, facts
        self.sdk = _Scanner(bindings)
        self._sends: dict[int, tuple[frozenset[str], dict[str, frozenset[str]]]] = {}
        self._busy: set[int] = set()
        self._memo: dict[tuple, bool] = {}
        self.pins: set[tuple[str, str]] = set()
        self.calls: dict[int, tuple[str, int, str]] = {}
        # the method names a sender instance can be pointed through (a cheap prefilter)
        classes = {_target(k) for d in facts.defs.values() for k in d.values() if k.startswith(_SENDER_CLS)}
        self._sender_methods = {t.rsplit(".", 1)[1] for t in facts.dest if t.rsplit(".", 1)[0] in classes}

    # ── what hands a bare client out ──────────────────────────────────────────
    def _method(self, node: ast.Attribute, cls: str | None) -> bool:
        return (node.attr in self.f.methods
                and not _own_member(self.m, self.f, cls, node.value, node.attr))

    def _client_call(self, call: ast.Call, cls: str | None) -> bool:
        kind = self.b.resolve(call.func)
        if kind is not None:
            if kind[0] == _CTOR or kind[0].startswith((_FACTORY, _SENDER_CLS)):
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

    def _callee(self, func: ast.AST, local, cls: str | None) -> tuple[_Function, bool] | None:
        """The def of this module a call reaches: a nested def, a module-level def by name, or
        a method of this class through ``self``; with whether the call binds ``self``."""
        if isinstance(func, ast.Name):
            values = local.get(func.id) if local else None
            if values:
                defs = [v for v in values if isinstance(v, _DEFS)]
                target = self.m.fn_of.get(id(defs[-1])) if defs else None
                return (target, False) if target is not None else None
            target = self.m.defs.get(func.id)
            return (target, False) if target is not None else None
        if (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
                and func.value.id in _SELF and cls is not None):
            target = self.m.method_of.get((cls, func.attr))
            if target is not None:
                return target, target.bound
        return None

    def _identity(self, node: ast.AST, fn: _Function, seen=frozenset()) -> set[str]:
        """The parameters of ``fn`` an expression can be, as is (``return c`` of ``_cfg(c)``)."""
        if isinstance(node, (ast.Await, ast.NamedExpr)):
            return self._identity(node.value, fn, seen)
        if isinstance(node, ast.IfExp):
            return self._identity(node.body, fn, seen) | self._identity(node.orelse, fn, seen)
        if isinstance(node, (ast.BoolOp, ast.Tuple, ast.List)):
            items = node.values if isinstance(node, ast.BoolOp) else node.elts
            return set().union(*(self._identity(v, fn, seen) for v in items))
        if not isinstance(node, ast.Name):
            return set()
        if node.id in fn.params:
            return {node.id}
        key = ("id", id(fn), node.id)
        if key in seen:
            return set()
        return set().union(*(self._identity(v, fn, seen | {key}) for v in fn.local.get(node.id, ())))

    def hands_out(self, node: ast.AST, local, cls, seen=frozenset(), strict=False) -> bool:
        """``node`` is (or, unless ``strict``, holds) a bare client or a sender instance."""
        if seen:
            return self._hands_out(node, local, cls, seen, strict)
        key = (id(node), id(local), cls, strict)
        if key not in self._memo:
            self._memo[key] = self._hands_out(node, local, cls, seen, strict)
        return self._memo[key]

    def _hands_out(self, node: ast.AST, local, cls, seen, strict) -> bool:
        def again(child):
            return self.hands_out(child, local, cls, seen, strict)
        if isinstance(node, (ast.Await, ast.Starred, ast.NamedExpr)):
            return again(node.value)
        if isinstance(node, ast.IfExp):
            return again(node.body) or again(node.orelse)
        if isinstance(node, ast.BoolOp):
            return any(map(again, node.values))
        if isinstance(node, ast.Subscript):     # an element of a container holding one is one
            return self.hands_out(node.value, local, cls, seen)
        if strict and isinstance(node, (_Item, ast.Tuple, ast.List, ast.Set, ast.Dict, ast.ListComp,
                                        ast.SetComp, ast.GeneratorExp, ast.DictComp, ast.Lambda)):
            return False                        # a container (or a factory), not a client
        if isinstance(node, _Item):
            return again(node.value)
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            return any(map(again, node.elts))
        if isinstance(node, ast.Dict):
            return any(map(again, node.values))
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            return again(node.elt)
        if isinstance(node, ast.DictComp):
            return again(node.value)
        if isinstance(node, ast.Lambda):
            return again(node.body)
        if isinstance(node, _DEFS):              # a nested def handed out: what it returns
            inner, key = self.m.fn_of.get(id(node)), ("def", id(node))
            if inner is None or key in seen:
                return False
            return any(self.hands_out(v, inner.scope, inner.cls, seen | {key}) for v in inner.returns)
        if isinstance(node, ast.Call):
            if self._client_call(node, cls):
                return True
            name = (_attr_chain(node.func) or [""])[-1]
            if (not strict and (name[:1].isupper() or name in _WRAPPERS)
                    and any(map(again, [*node.args, *(k.value for k in node.keywords)]))):
                return True
            callee = self._callee(node.func, local, cls)
            if callee is None or ("call", id(callee[0])) in seen:
                return False
            target, bound = callee
            deeper = seen | {("call", id(target))}
            if target.parent is not None and any(       # a nested def returning a client
                    self.hands_out(v, target.scope, target.cls, deeper) for v in target.returns):
                return True
            for param in set().union(*(self._identity(r, target) for r in target.returns)):
                arg = _argument(node, target.signature, bound, param)   # `_cfg(client)`
                if arg is not None and self.hands_out(arg, local, cls, deeper, strict):
                    return True
            return False
        if not isinstance(node, (ast.Name, ast.Attribute)):
            return False
        kind = self.b.resolve(node)
        if kind is not None:
            return _hands_out_kind(kind[0])
        if isinstance(node, ast.Attribute) and self._method(node, cls):
            return not strict                    # a bound factory method handed on uncalled
        chain = tuple(_attr_chain(node))
        if not chain or chain in seen:
            return False
        if len(chain) == 1:
            values = local.get(chain[0], ()) if local else ()
        elif chain[0] in _SELF and cls is not None:
            values = self.m.self_values.get(cls, {}).get(("self", *chain[1:]), ())
        else:
            return False
        return any(self.hands_out(v, local, cls, seen | {chain}, strict) for v in values)

    # ── where a bare client is pointed ────────────────────────────────────────
    def _pinned(self, fn: _Function, flows=True) -> bool:
        """``fn`` ends a trace (recorded as used when a destination would flow into it)."""
        key = (self.m.rel, fn.qual)
        if key not in _PINNED_DESTINATIONS:
            return False
        if flows:
            self.pins.add(key)
        return True

    def _sources(self, node: ast.AST, fn: _Function, seen) -> frozenset[str]:
        """Where the host a URL expression dials can come from."""
        out: set[str] = set()
        for part in _host_parts(node):
            out |= self._origin(part, fn, seen)
        return frozenset(out)

    def _param(self, name: str, fn: _Function) -> bool:
        """``name`` is a parameter of ``fn`` or of a def enclosing it (not shadowed)."""
        scope: _Function | None = fn
        while scope is not None:
            if name in scope.params:
                return True
            if name in scope.local:
                return False
            scope = scope.parent
        return False

    def _origin(self, node: ast.AST, fn: _Function, seen) -> frozenset[str]:
        """Where any part of an expression's value can come from."""
        if isinstance(node, ast.Name):
            if self._param(node.id, fn):
                return frozenset({f"p:{node.id}"})
            key = ("name", id(fn), node.id)
            if key in seen or node.id not in fn.scope:
                return _NONE
            return frozenset().union(*(self._sources(v, fn, seen | {key}) for v in fn.scope[node.id]
                                       if not isinstance(v, _DEFS)))
        chain = _attr_chain(node)
        if len(chain) >= 2 and chain[0] in _SELF and fn.cls is not None:
            return self._attribute(fn.cls, chain[1], seen, self._sources)
        if isinstance(node, ast.Call):
            return self._call_origin(node, fn, seen)
        if isinstance(node, (ast.Lambda, *_DEFS)):
            return _NONE
        out: set[str] = set()
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.expr, ast.comprehension, ast.keyword)):
                out |= self._origin(child, fn, seen)
        return frozenset(out)

    def _attribute(self, cls: str, attr: str, seen, follow) -> frozenset[str]:
        """``self.<attr>``: what any value the class stores in it comes from, as ``ctor:``."""
        key = (follow.__name__, cls, attr)
        if key in seen:
            return _NONE
        out: set[str] = set()
        for owner, value in self.m.self_sources.get(cls, {}).get(attr, ()):
            if owner is None:
                continue
            for source in follow(value, owner, seen | {key}):
                kind, name = _split(source)
                # A host a parameter decides; not a client object handed in (``rest=``,
                # ``client=``): whoever builds a bare client to hand in is a finding there.
                if kind == "p":
                    out.add(f"ctor:{name}" if owner.node.name == "__init__" and owner.parent is None
                            else "ctor:*")
                elif kind == "ctor":
                    out.add(source)
        return frozenset(out)

    def _map(self, sources, call: ast.Call, signature, bound: bool, fn: _Function, seen,
             keep_ctor: bool) -> frozenset[str]:
        """A callee's sources at one call: its parameters become the arguments passed."""
        out: set[str] = set()
        for source in sources:
            kind, name = _split(source)
            if kind in ("p", "base"):
                arg = _argument(call, signature, bound, name)
                if arg is not None:
                    out |= (self._sources if kind == "p" else self._base)(arg, fn, seen)
            elif kind == "ctor" and keep_ctor:
                out.add(source)
        return frozenset(out)

    def _call_origin(self, call: ast.Call, fn: _Function, seen) -> frozenset[str]:
        callee = self._callee(call.func, fn.scope, fn.cls)
        if callee is not None:
            target, bound = callee
            key = ("ret", id(target))
            if key in seen:
                return _NONE
            returned = frozenset().union(*(self._sources(r, target, seen | {key}) for r in target.returns))
            if self._pinned(target, bool(returned)):
                return _NONE        # a validator: what it returns is a checked destination
            return self._map(returned, call, target.signature, bound, fn, seen,
                             bound and target.cls == fn.cls)
        out: set[str] = set()
        if isinstance(call.func, ast.Attribute):
            out |= self._origin(call.func.value, fn, seen)
        for arg in call.args:
            out |= self._origin(arg.value if isinstance(arg, ast.Starred) else arg, fn, seen)
        for keyword in call.keywords:
            out |= self._origin(keyword.value, fn, seen)
        return frozenset(out)

    def _dest(self, target: str) -> frozenset[str]:
        info = self.f.dest.get(target)
        return frozenset(f"p:{n}" for n in info[1]) if info else _NONE

    def _base(self, node: ast.AST, fn: _Function, seen) -> frozenset[str]:
        """Where the base_url of a client value comes from."""
        def again(child):
            return self._base(child, fn, seen)
        if isinstance(node, (ast.Await, ast.NamedExpr, ast.Starred, _Item)):
            return again(node.value)
        if isinstance(node, ast.IfExp):
            return again(node.body) | again(node.orelse)
        if isinstance(node, (ast.BoolOp, ast.Tuple, ast.List, ast.Set, ast.Dict)):
            items = (node.values if isinstance(node, (ast.BoolOp, ast.Dict)) else node.elts)
            return frozenset().union(*map(again, items))
        if isinstance(node, ast.Subscript):
            return again(node.value)
        if isinstance(node, ast.Call):
            kind = self.b.resolve(node.func)
            if kind is not None:
                if kind[0] == _CTOR or kind[0].startswith(_SDK_CTOR):
                    out: set[str] = set()
                    for key in _BASE_KEYWORDS:
                        value = _keyword(node, key)
                        if value is not None:
                            out |= self._sources(value, fn, seen)
                    return frozenset(out)
                if kind[0].startswith((_FACTORY, *_CLASS_GATES)):
                    info = self.f.dest.get(_target(kind[0]))
                    return (self._map(self._dest(_target(kind[0])), node, info[0], info[2], fn, seen,
                                      False) if info else _NONE)
                return _NONE
            callee = self._callee(node.func, fn.scope, fn.cls)
            if callee is not None:
                target, bound = callee
                key = ("base", id(target))
                if key in seen:
                    return _NONE
                inner = frozenset().union(*(self._base(r, target, seen | {key}) for r in target.returns))
                if self._pinned(target, bool(inner)):
                    return _NONE
                return self._map(inner, node, target.signature, bound, fn, seen,
                                 bound and target.cls == fn.cls)
            name = (_attr_chain(node.func) or [""])[-1]
            if name[:1].isupper() or name in _WRAPPERS:
                return frozenset().union(*map(again, [*node.args, *(k.value for k in node.keywords)]))
            return _NONE
        if isinstance(node, ast.Name):
            if self._param(node.id, fn):
                return frozenset({f"base:{node.id}"})
            key = ("bname", id(fn), node.id)
            if key in seen or node.id not in fn.scope:
                return _NONE
            return frozenset().union(*(self._base(v, fn, seen | {key}) for v in fn.scope[node.id]
                                       if not isinstance(v, _DEFS)))
        chain = _attr_chain(node)
        if len(chain) >= 2 and chain[0] in _SELF and fn.cls is not None:
            return self._attribute(fn.cls, chain[1], seen, self._base)
        return _NONE

    def _instances(self, node: ast.AST, local, cls, seen=frozenset()) -> set[str]:
        """The sender classes an expression can be an instance of."""
        if isinstance(node, (ast.Await, ast.NamedExpr, ast.Starred)):
            return self._instances(node.value, local, cls, seen)
        if isinstance(node, ast.IfExp):
            return self._instances(node.body, local, cls, seen) | self._instances(node.orelse, local, cls, seen)
        if isinstance(node, ast.BoolOp):
            return set().union(*(self._instances(v, local, cls, seen) for v in node.values))
        if isinstance(node, ast.Call):
            kind = self.b.resolve(node.func)
            return {_target(kind[0])} if kind is not None and kind[0].startswith(_SENDER_CLS) else set()
        chain = tuple(_attr_chain(node))
        if not chain or chain in seen:
            return set()
        if len(chain) == 1:
            return set().union(*(self._instances(v, local, cls, seen | {chain})
                                 for v in (local.get(chain[0], ()) if local else ())))
        if len(chain) == 2 and chain[0] in _SELF and cls is not None:
            return set().union(*(self._instances(v, owner.scope if owner else {}, cls, seen | {chain})
                                 for owner, v in self.m.self_sources.get(cls, {}).get(chain[1], ())))
        return set()

    def _note(self, call: ast.Call, fn: _Function, target: str, info) -> None:
        """A finding no reference resolves: this call points a sender (it passes one of the
        parameters that decide the host, or a splat)."""
        if _passes(call, info):
            self.calls.setdefault(id(call), (fn.qual, call.lineno, (
                f"hands a host to {target}, which sends to it through a bare client")))

    def _send(self, call: ast.Call, fn: _Function):
        """The sources of the host one call dials through a bare client: a client send, a
        sender's call, a sender instance's method, or a def of this module that sends."""
        direct: set[str] = set()
        via: dict[str, set[str]] = {}
        func, seen = call.func, frozenset()
        if isinstance(func, ast.Attribute) and func.attr in _SEND_VERBS:
            recv = func.value
            urls = frozenset().union(*(self._sources(a, fn, seen) for a in _url_args(call, func.attr)))
            if isinstance(recv, ast.Name) and self._param(recv.id, fn):
                via.setdefault(recv.id, set()).update(urls | {f"base:{recv.id}"})   # a client handed in
            elif self.hands_out(recv, fn.scope, fn.cls, strict=True):
                direct |= urls | self._base(recv, fn, seen)
        kind = self.b.resolve(func)
        if kind is not None and kind[0].startswith((_SENDER, *_CLASS_GATES)):
            info = self.f.dest.get(_target(kind[0]))
            if info:
                direct |= self._map(self._dest(_target(kind[0])), call, info[0], info[2], fn, seen, False)
        forms = [(func, "__call__")]                  # `transport(url, body)`
        if isinstance(func, ast.Attribute):
            forms.append((func.value, func.attr))     # `rest.request("POST", url)`
        for recv, method in forms:
            if method not in self._sender_methods:
                continue
            for cls in self._instances(recv, fn.scope, fn.cls):
                target = f"{cls}.{method}"
                info = self.f.dest.get(target)
                if info:
                    self._note(call, fn, target, info)
                    direct |= self._map(self._dest(target), call, info[0], info[2], fn, seen, False)
        callee = self._callee(func, fn.scope, fn.cls)
        if callee is not None:
            target, bound = callee
            inner, inner_via = self._fn_sends(target)
            same = bound and target.cls == fn.cls
            names = frozenset(n for k, n in map(_split, inner) if k == "p")
            if bound and names:                       # the class's own sender method
                self._note(call, fn, f"{self.m.rel}:{target.qual}", (target.signature, names, bound))
            direct |= self._map(inner, call, target.signature, bound, fn, seen, same)
            for param, sources in inner_via.items():
                arg = _argument(call, target.signature, bound, param)
                if arg is None:
                    continue
                mapped = self._map(sources, call, target.signature, bound, fn, seen, same)
                if isinstance(arg, ast.Name) and self._param(arg.id, fn):
                    via.setdefault(arg.id, set()).update(mapped)
                elif self.hands_out(arg, fn.scope, fn.cls):
                    direct |= mapped
        return direct, via

    def _fn_sends(self, fn: _Function):
        key = id(fn)
        if key in self._sends:
            return self._sends[key]
        if key in self._busy:
            return _NONE, {}
        self._busy.add(key)
        direct: set[str] = set()
        via: dict[str, set[str]] = {}
        for call in fn.calls:
            d, v = self._send(call, fn)
            direct |= d
            for name, sources in v.items():
                via.setdefault(name, set()).update(sources)
        self._busy.discard(key)
        result = (_NONE, {}) if self._pinned(fn, bool(direct or via)) else (
            frozenset(direct), {k: frozenset(v) for k, v in via.items()})
        self._sends[key] = result
        return result

    # ── the module's facts ────────────────────────────────────────────────────
    def detect(self):
        m, rel, facts = self.m, self.m.rel, self.f
        defs: dict[str, str] = {}
        methods: dict[str, set[str]] = {}
        attrs: dict[str, set[str]] = {}
        owners: set[tuple[str, str, str]] = set()
        dest: dict[str, tuple[tuple, frozenset[str], bool]] = {}
        ancestors: dict[str, frozenset[str]] = {}
        constructing: set[str] = set()      # classes holding a client in a public attribute
        carrying: set[str] = set()          # classes with factory methods or client attributes
        sending: set[str] = set()           # classes with a public method its caller points
        sends: dict[str, set[str]] = {}     # private method name -> methods its caller points
        injected: dict[str, set[str]] = {}  # classes pointed by an attribute: ctor parameters
        ledger = _LEDGER_SOURCES.get(m.name, frozenset())

        def point(fn: _Function, names) -> None:
            entry = dest.get(f"{rel}:{fn.qual}")
            old = entry[1] if entry else frozenset()
            dest[f"{rel}:{fn.qual}"] = (fn.signature, old | frozenset(names), fn.bound)

        for fn in m.functions:
            if fn.qual in ledger:
                continue                    # the ledgered constructors themselves
            returns = any(self.hands_out(v, fn.scope, fn.cls) for v in fn.returns)
            stored = public = False
            for chain, value in fn.stores:
                if len(chain) < 2 or not self.hands_out(value, fn.scope, fn.cls):
                    continue
                if chain[0] in _SELF and fn.cls is not None:
                    owners.add((rel, fn.cls, chain[1]))
                    stored = True
                    public |= not chain[1].startswith("_")
                else:                       # planted on another object, public or private
                    attrs.setdefault(chain[-1], set()).add(f"{rel}:{fn.qual}")
            if returns:
                if fn.method:
                    methods.setdefault(fn.node.name, set()).add(f"{rel}:{fn.qual}")
                elif fn.parent is None:
                    defs[fn.node.name] = f"{_FACTORY}{rel}:{fn.qual}"
                if not self._pinned(fn):    # a factory its caller points (base_url=<param>)
                    pointed = frozenset().union(*(self._base(r, fn, frozenset()) for r in fn.returns))
                    names = {n for k, n in map(_split, pointed) if k == "p"}
                    if names:
                        point(fn, names)
                    if fn.cls is not None and any(_split(s)[0] == "ctor" for s in pointed):
                        injected.setdefault(fn.cls, set()).update(
                            n for k, n in map(_split, pointed) if k == "ctor")
            if fn.cls is not None and (stored or (returns and fn.method)):
                carrying.add(fn.cls)
                if public and not returns:
                    constructing.add(fn.cls)        # nothing hands it out: the instance does
            direct, _ = self._fn_sends(fn)
            names = {n for k, n in map(_split, direct) if k == "p"}
            for name in names:                       # a parameter of an enclosing def
                owner = fn
                while owner is not None and name not in owner.params:
                    owner = owner.parent
                if owner is None:
                    continue
                point(owner, {name})
                method = owner.node.name
                if owner.cls is not None and owner.method and method == "__init__":
                    injected.setdefault(owner.cls, set()).add(name)  # a constructor argument
                elif owner.cls is not None and owner.method and (
                        method.startswith("_") and not method.endswith("__")):
                    sends.setdefault(method, set()).add(f"{rel}:{owner.qual}")
                elif owner.cls is not None and owner.method:
                    sending.add(owner.cls)
                elif owner.parent is None and owner.cls is None:
                    defs.setdefault(owner.node.name, f"{_SENDER}{rel}:{owner.qual}")
            ctor = {n for k, n in map(_split, direct) if k == "ctor"}
            if ctor and fn.cls is not None:
                injected.setdefault(fn.cls, set()).update(ctor)
        for cls, node in m.classes.items():
            for name, value in m.class_body[cls]:
                if self.b.resolve(value) is None and self.hands_out(value, {}, cls):
                    owners.add((rel, cls, name))
                    constructing.add(cls)    # a class-attribute client: shared and public
            inherited = _inherited(self.b, node, facts)
            if inherited:
                ancestors[f"{rel}:{cls}"] = inherited
            for base in node.bases:
                kind = self.b.resolve(base)
                if kind is None:
                    continue
                if kind[0].startswith(_HOLDER):
                    constructing.add(cls)           # constructing it runs the base's __init__
                elif kind[0].startswith(_SENDER_CLS):
                    sending.add(cls)
                elif kind[0].startswith(_INJECTED):
                    injected.setdefault(cls, set()).add("*")
                elif kind[0].startswith(_CARRIER):
                    carrying.add(cls)
        for _, cls, attr in owners:
            if attr.startswith("_"):
                attrs.setdefault(attr, set()).add(f"{rel}:{cls}")
        for cls in carrying | constructing | sending | set(injected):
            prefix = (_SENDER_CLS if cls in sending else _HOLDER if cls in constructing
                      else _INJECTED if cls in injected else _CARRIER)
            defs[cls.rsplit(".", 1)[-1]] = f"{prefix}{rel}:{cls}"
        for cls, names in injected.items():
            init = m.method_of.get((cls, "__init__"))
            signature = init.signature if init is not None else (("self",), (), None, None)
            if "*" in names:
                names = {"*"}
            dest[f"{rel}:{cls}"] = (signature, frozenset(names), True)
        for name, value, owner in m.globals:
            local = owner.scope if owner is not None else {}
            if self.b.resolve(value) is None and self.hands_out(value, local, owner.cls if owner else None):
                defs[name] = f"{_FACTORY}{rel}:{name}"      # a module-level client object
        calls = tuple(sorted(self.calls.values()))
        return defs, methods, attrs, owners, dest, calls, ancestors, self.pins, sends


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
             start: _Facts = _NO_FACTS) -> tuple[dict[str, _Bindings], _Facts]:
    """Bindings and bare-client facts together, to a joint fixed point: a factory or sender
    found in one round is a constructor in the next, so whatever returns its client, or hands
    it its own parameter, is one too. ``start`` is a fixed point of a subset of ``modules``
    (the facts only grow as modules are added, so it is below this one)."""
    repo_modules = repo_modules if repo_modules is not None else _repo_module_names(modules)
    facts = start
    for _ in range(50):
        bindings = _bind_all(modules, repo_modules, facts)
        defs, methods, attrs, owners, dest, calls, ancestors, pins = {}, {}, {}, set(), {}, {}, {}, set()
        sends: dict[str, set[str]] = {}
        for rel, module in modules.items():
            d, mth, att, own, dst, cl, anc, pin, snd = _Detector(module, bindings[rel], facts).detect()
            for name, quals in snd.items():
                sends.setdefault(name, set()).update(quals)
            if d:
                defs[rel] = d
            for name, quals in mth.items():
                methods.setdefault(name, set()).update(quals)
            for name, quals in att.items():
                attrs.setdefault(name, set()).update(quals)
            owners |= own
            dest.update(dst)
            if cl:
                calls[rel] = cl
            ancestors.update(anc)
            pins |= pin
        found = _Facts(defs, {k: frozenset(v) for k, v in methods.items()},
                       {k: frozenset(v) for k, v in attrs.items()}, frozenset(owners), dest, calls,
                       ancestors, frozenset(pins), {k: frozenset(v) for k, v in sends.items()})
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
_SDK_HINT = re.compile(r"(?:\b(?:import|from)\s+|import_module\(\s*['\"]|__import__\(\s*['\"]"
                       r"|\bmodules\s*(?:\[|\.\w+\()\s*['\"])"
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
    hints = ("httpx", "event_hooks", *_RAW_SENDS, *_PRIVATE_SENDS, *_PROVIDER_IMPORT_HINTS)
    wanted = {rel for rel, src in sources.items()
              if rel.startswith(("agents/core/llm/", *PROVIDER_ROOTS))
              or any(h in src for h in hints) or _SDK_HINT.search(src)}
    modules: dict[str, _Module] = {}
    facts = _NO_FACTS
    while True:
        modules.update({rel: _parsed(rel, sources[rel]) for rel in wanted - modules.keys()})
        bindings, facts = _analyse(modules, repo_modules, facts)
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
    scan = _RepoScan((in_scope, outside, provider_modules))
    scan.facts = facts
    return scan


class _RepoScan(tuple):
    """(in_scope, outside, provider_modules), with the facts the scan reached."""

    facts: _Facts


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
    methods = {*facts.methods, *facts.sends}
    if methods:
        alternatives.append(r"\b(?:" + "|".join(map(re.escape, sorted(methods))) + r")\b")
    if facts.attrs:
        attrs = "|".join(map(re.escape, sorted(facts.attrs)))
        alternatives.append(r"(?<!\bself)(?<!\bcls)\.(?:" + attrs + r")\b|[\"'](?:" + attrs + r")[\"']")
    if not alternatives:
        return None
    return frozenset(bound) | frozenset(methods) | frozenset(facts.attrs), re.compile("|".join(alternatives))


_SCAN = None


def _scan():
    global _SCAN
    if _SCAN is None:
        _SCAN = _scan_repo()
    return _SCAN


# ── the rule ─────────────────────────────────────────────────────────────────

def _rewires_hooks(shape: str) -> bool:
    """A hook-rewiring finding: only HOOK_REWIRING_ALLOWLIST exempts it, in or out of scope."""
    return shape.startswith(_HOOKS_REWIRED)


def _prompt_offenders(in_scope) -> list[str]:
    """What fails the prompt-scope rule: a finding whose (file, qualname) is not allowlisted."""
    return [f"{rel}:{line} {qual} — {shape}"
            for rel, findings in in_scope.items()
            for qual, line, shape in findings
            if (rel, qual) not in (HOOK_REWIRING_ALLOWLIST if _rewires_hooks(shape)
                                   else PROMPT_SCOPE_ALLOWLIST)]


def _unclassified(outside) -> list[str]:
    """What fails the outside-scope rule: a finding in a function nobody classified."""
    return [f"{rel}:{line} {qual} — {shape}"
            for rel, findings in outside.items()
            for qual, line, shape in findings
            if ((rel, qual) not in HOOK_REWIRING_ALLOWLIST if _rewires_hooks(shape)
                else qual not in NOT_A_MODEL_PROVIDER.get(rel, ("", frozenset()))[1])]


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
    used = {(rel, qual) for rel, findings in in_scope.items() for qual, _, shape in findings
            if not _rewires_hooks(shape)}
    stale = sorted(set(PROMPT_SCOPE_ALLOWLIST) - used)
    assert stale == [], f"allowlist entries that no longer match a bare client: {stale}"
    rewired = {(rel, qual) for bucket in (in_scope, outside) for rel, findings in bucket.items()
               for qual, _, shape in findings if _rewires_hooks(shape)}
    stale_hooks = sorted(set(HOOK_REWIRING_ALLOWLIST) - rewired)
    assert stale_hooks == [], f"hook-rewiring entries that no longer rewire a client's hooks: {stale_hooks}"
    seen = {(rel, qual) for rel, findings in outside.items() for qual, _, shape in findings
            if not _rewires_hooks(shape)}
    classified = {(rel, qual) for rel, (_, quals) in NOT_A_MODEL_PROVIDER.items() for qual in quals}
    stale_classified = sorted(classified - seen)
    assert stale_classified == [], f"classified functions with no bare client left: {stale_classified}"
    misfiled = sorted(set(NOT_A_MODEL_PROVIDER) & provider_modules)
    assert misfiled == [], f"a provider module cannot be classified as not-a-provider: {misfiled}"
    stale_pins = sorted(set(_PINNED_DESTINATIONS) - _scan().facts.pins)
    assert stale_pins == [], f"pinned destinations no destination flows into any more: {stale_pins}"
    reasons = _reasons()
    for key, why in reasons:
        assert isinstance(why, str) and len(why.strip()) >= 30, f"{key} needs a real reason"
    # A reason that rests on a test must name one that exists (round-5 review: two cited
    # tests that were never written passed the length check).
    assert _citation_errors(reasons) == [], _citation_errors(reasons)


def _reasons() -> list[tuple[object, str]]:
    return [*PROMPT_SCOPE_ALLOWLIST.items(), *_PINNED_DESTINATIONS.items(),
            *HOOK_REWIRING_ALLOWLIST.items(),
            *((rel, why) for rel, (why, _) in NOT_A_MODEL_PROVIDER.items())]


_CITED_FILE = re.compile(r"\btests/[\w/]+\.py\b")
_CITED_TEST = re.compile(r"\btest_\w+")
_DEFINED_TESTS: frozenset[str] | None = None


def _defined_tests() -> frozenset[str]:
    """Every test function name defined under tests/."""
    global _DEFINED_TESTS
    if _DEFINED_TESTS is None:
        _DEFINED_TESTS = frozenset(
            name for path in (REPO / "tests").rglob("test_*.py")
            for name in re.findall(r"^[ \t]*(?:async[ \t]+)?def[ \t]+(test_\w+)",
                                   path.read_text(encoding="utf-8", errors="replace"), re.M))
    return _DEFINED_TESTS


def _citation_errors(reasons) -> list[str]:
    """Each ``tests/…py`` a reason cites must exist, and each ``test_…`` it names must be a
    test function some file under tests/ defines."""
    errors = []
    for key, why in reasons:
        for cited in _CITED_FILE.findall(why):
            if not (REPO / cited).is_file():
                errors.append(f"{key} cites {cited}, which does not exist")
        for name in _CITED_TEST.findall(_CITED_FILE.sub("", why)):
            if name not in _defined_tests():
                errors.append(f"{key} cites {name}, which no test defines")
    return errors


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


def _is_stack(name: str) -> bool:
    return name.startswith(_OTHER_HTTP_STACKS)


def _module_level(body):
    """The statements of a module outside every def and class (if/try/with blocks included):
    what another module can import from it."""
    pending = list(body)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        yield node
        for field in ("body", "orelse", "finalbody", "handlers", "cases"):
            pending.extend(getattr(node, field, ()) or ())


_TREES: dict[tuple[str, str], ast.Module] = {}


def _repo_module(name: str, extra: dict[str, str]) -> tuple[str, ast.Module] | None:
    """(rel, tree) of a repo module by its dotted name (a probe module before the disk)."""
    if not (name == "agents" or name.startswith("agents.")):
        return None
    for rel in (name.replace(".", "/") + ".py", name.replace(".", "/") + "/__init__.py"):
        if rel in extra:
            source = extra[rel]
        elif (REPO / rel).is_file():
            source = (REPO / rel).read_text(encoding="utf-8")
        else:
            continue
        parsed = _PARSED.get((rel, source))       # the scan parsed most of them already
        tree = parsed.tree if parsed is not None else _TREES.get((rel, source))
        if tree is None:
            tree = _TREES[(rel, source)] = ast.parse(source)
        return rel, tree
    return None


def _reexported_stack(name: str, attr: str, extra: dict[str, str], seen: frozenset = frozenset()) -> str | None:
    """The other HTTP stack repo module ``name`` binds at module level under ``attr`` — imported
    there, re-exported there from another repo module (absolute, relative or ``*``), or
    assigned there from one of those — so ``from <name> import <attr>`` or ``<name>.<attr>``
    hands it on (round-5 review: ``from .direct_transport import httpcore``)."""
    found = _repo_module(name, extra) if (name, attr) not in seen else None
    if found is None:
        return None
    rel, tree = found
    seen = seen | {(name, attr)}
    here, package = _module_name(rel), rel.endswith("/__init__.py")
    for node in _module_level(tree.body):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if (alias.asname or alias.name.split(".")[0]) == attr and _is_stack(alias.name):
                    return alias.name
        elif isinstance(node, ast.ImportFrom):
            source = _import_source(here, package, node)
            for alias in node.names:
                if alias.name == "*" or (alias.asname or alias.name) == attr:
                    member = attr if alias.name == "*" else alias.name
                    if _is_stack(source) or _is_stack(f"{source}.{member}"):
                        return source if _is_stack(source) else f"{source}.{member}"
                    if (inner := _reexported_stack(source, member, extra, seen)) is not None:
                        return inner
        else:
            for target, value in _assignments(node):
                chain = _attr_chain(value)
                if (isinstance(target, ast.Name) and target.id == attr and chain
                        and (inner := _reexported_stack(name, chain[0], extra, seen)) is not None):
                    return inner     # `_hc = httpcore`, `Pool = httpcore.AsyncConnectionPool`
    return None


def _star_names(name: str, extra: dict[str, str], seen: frozenset = frozenset()) -> set[str]:
    """The names ``from <name> import *`` binds: its ``__all__``, else every public name it
    binds at module level (star imports of other repo modules included)."""
    found = _repo_module(name, extra) if name not in seen else None
    if found is None:
        return set()
    rel, tree = found
    names: set[str] = set()
    for node in _module_level(tree.body):
        if isinstance(node, ast.Import):
            names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            source = _import_source(_module_name(rel), rel.endswith("/__init__.py"), node)
            for alias in node.names:
                names.update(_star_names(source, extra, seen | {name}) if alias.name == "*"
                             else {alias.asname or alias.name})
        else:
            for target, value in _assignments(node):
                if isinstance(target, ast.Name) and target.id == "__all__" and isinstance(
                        value, (ast.List, ast.Tuple)):
                    return {c for c in map(_const_str, value.elts) if c is not None}
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return {n for n in names if not n.startswith("_")}


def _httpcore_reads(module: _Module) -> list[str]:
    """In a module allowed to import httpcore for identity checks: every read of it that is not
    a type/identity position (an ``is``/``==``/``in`` operand, ``isinstance``'s class, an
    annotation, an ``except`` clause) — a call, a subclass, a hand-off, a patch."""
    bound = set()
    for node in module.imports:
        if isinstance(node, ast.Import):
            bound.update(alias.asname or alias.name.split(".")[0] for alias in node.names
                         if alias.name.split(".")[0] == "httpcore")
        elif not node.level and (node.module or "").split(".")[0] == "httpcore":
            bound.update(alias.asname or alias.name for alias in node.names)
    offenders: list[str] = []

    def visit(node: ast.AST, safe: bool = False) -> None:
        if isinstance(node, (ast.Name, ast.Attribute)) and (chain := _attr_chain(node)) and chain[0] in bound:
            if not (safe and isinstance(node.ctx, ast.Load)):
                offenders.append(f"{module.rel}:{node.lineno} uses {'.'.join(chain)} "
                                 "outside a type/identity check")
            return
        if isinstance(node, ast.Compare):
            identity = all(isinstance(op, _IDENTITY_OPS) for op in node.ops)
            for operand in [node.left, *node.comparators]:
                visit(operand, identity)
            return
        if isinstance(node, ast.Call) and _callee(node.func) in {"isinstance", "issubclass"}:
            visit(node.func)
            for index, arg in enumerate(node.args):
                visit(arg, index >= 1)
            return
        typed = {"annotation", "returns"} | ({"type"} if isinstance(node, ast.ExceptHandler) else set())
        keep = safe and isinstance(node, (ast.Tuple, ast.BinOp))   # `(A, B)`, `A | None`
        for field, value in ast.iter_fields(node):
            for child in value if isinstance(value, list) else [value]:
                if isinstance(child, ast.AST):
                    visit(child, keep or field in typed)

    visit(module.tree)
    return offenders


def _other_stack_imports(module: _Module, extra: dict[str, str] | None = None) -> list[str]:
    """Every way one provider module reaches another HTTP stack: an import of it (absolute or
    relative), a name another repo module re-exports from it (``from .direct_transport import
    httpcore``, ``direct_transport.httpcore``), and — in a module allowed to import httpcore
    for identity checks — any use of httpcore but such a check."""
    extra = extra or {}
    offenders = []
    repo: dict[str, str] = {}     # local name -> the repo module it is bound to
    for node in module.imports:
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
            for alias in node.names:
                if _repo_module(alias.name, extra) is not None:
                    repo[alias.asname or alias.name.split(".")[0]] = (
                        alias.name if alias.asname else alias.name.split(".")[0])
        else:                 # `from google import generativeai` names google.generativeai
            source = _import_source(module.name, module.is_package, node)
            names = [source, *(f"{source}.{alias.name}" for alias in node.names)]
            for alias in node.names:
                members = sorted(_star_names(source, extra)) if alias.name == "*" else [alias.name]
                if _repo_module(f"{source}.{alias.name}", extra) is not None:
                    repo[alias.asname or alias.name] = f"{source}.{alias.name}"
                    continue
                for member in members:
                    if (stack := _reexported_stack(source, member, extra)) is not None:
                        offenders.append(f"{module.rel}:{node.lineno} imports {stack} re-exported by {source}")
        name = next((n for n in names if _is_stack(n)), None)
        top_level_httpcore = (name if isinstance(node, ast.Import) else source) == "httpcore"
        if name and not (top_level_httpcore and module.rel in _HTTPCORE_IDENTITY_ONLY):
            offenders.append(f"{module.rel}:{node.lineno} imports {name}")
    for node in ast.walk(module.tree):     # `direct_transport.httpcore`, `getattr(dt, "httpcore")`
        if isinstance(node, ast.Attribute):
            chain = _attr_chain(node)
        elif (isinstance(node, ast.Call) and _callee(node.func) == "getattr" and len(node.args) >= 2
              and _const_str(node.args[1]) is not None):
            chain = [*_attr_chain(node.args[0]), _const_str(node.args[1])]
        else:
            continue
        if len(chain) < 2 or chain[0] not in repo:
            continue
        current = repo[chain[0]]
        for attr in chain[1:]:
            if _repo_module(f"{current}.{attr}", extra) is not None:
                current = f"{current}.{attr}"
                continue
            if (stack := _reexported_stack(current, attr, extra)) is not None:
                offenders.append(f"{module.rel}:{node.lineno} reads {stack} re-exported by {current}")
            break
    if module.rel in _HTTPCORE_IDENTITY_ONLY:
        offenders += _httpcore_reads(module)
    return list(dict.fromkeys(offenders))


def _other_stack_offenders(provider_modules, extra: dict[str, str] | None = None) -> list[str]:
    extra = extra or {}
    return [line for rel in sorted(provider_modules)
            for line in _other_stack_imports(
                _parsed(rel, extra[rel] if rel in extra else (REPO / rel).read_text(encoding="utf-8")),
                extra)]


def test_no_provider_module_switches_to_another_http_stack():
    """The httpx rule cannot be dodged by dialling with a different library, nor with a
    model SDK that does not dial through httpx, nor with httpcore handed on by a module that
    may import it for identity checks."""
    _, _, provider_modules = _scan()
    offenders = _other_stack_offenders(provider_modules)
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
    # ProbeController itself: OllamaController's host is its constructor's server_url, so
    # subclassing it is a finding as well (round 4).
    assert reach == {"via_re_export", "via_module_attribute", "via_client_attribute",
                     "via_getattr", "ProbeController", "ProbeController.ask", "via_holder"}, reach
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
    async def request(self):
        return await self._http().get("/api/tags")

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

async def probe():
    async with httpx.AsyncClient() as c:
        return (await c.get("http://127.0.0.1:11434/api/tags")).json()

async def show(name):
    async with httpx.AsyncClient(base_url="http://127.0.0.1:11434") as c:
        return await c.post(f"/api/show/{name}", json={"name": name})

async def send(url, body):
    async with httpx.AsyncClient() as c:
        return await c.post(url, json=body)

def at(origin):
    return httpx.AsyncClient(base_url=origin)

async def relay(url, body):
    return await send(url, body)

class REST:
    async def request(self, method, url, **kw):
        async with httpx.AsyncClient() as c:
            return await c.request(method, url, **kw)

class Pinned:
    def __init__(self, url="http://127.0.0.1:6333"):
        self.url = url
        self._c = httpx.Client()
    def upsert(self, points):
        return self._c.put(f"{self.url}/collections/x/points", json=points)

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
    # ── round-4 review: a bare client followed by where it is pointed ──
    "send-through function": "from agents.core.netx import send\nasync def f(p):\n    return await send('https://api.openai.com/v1/x', p)\n",
    "send-through forwarded": "from agents.core.netx import relay\nasync def f(p):\n    return await relay('https://api.openai.com/v1/x', p)\n",
    "send-through method": ("from agents.core.netx import REST\nasync def f(p):\n"
                            "    return await REST().request('POST', 'https://api.openai.com/v1/x', json=p)\n"),
    "send-through instance kept": ("from agents.core.netx import REST\nasync def f(p):\n"
                                   "    rest = REST()\n    return await rest.request('POST', 'https://x.test', json=p)\n"),
    "pointed factory": "from agents.core.netx import at\nasync def f(p):\n    return await at('https://api.openai.com').post('/v1/x', json=p)\n",
    "injected destination": "from agents.core.netx import Pinned\ndef f(p):\n    return Pinned('https://api.openai.com').upsert(p)\n",
}
# Uses of the same module that hand nothing out: none is a finding.
_FACTORY_SAFE_USER = '''\
from agents.core.llm.egress import llm_async_client
from agents.core.netx import Ctl, Holder, Pinned, ledgered, probe, show, use

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
    await ctl.request()
    await probe()
    await show("llama3")            # a parameter in the path or body never moves the host
    await use("http://127.0.0.1:1")
    Pinned().upsert(p)              # the injected class at its own default destination
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
    # A sender's own forwarding caller is a sender too (its callers are checked in turn).
    relays = [s for q, _, s in findings[_NETX] if q == "relay"]
    assert relays == ["calls agents/core/netx.py:send, which sends through a bare client to a "
                      "host its caller decides"], relays


# ── round-4 review: a bare client followed by where it is pointed ────────────

_VLM = "agents/core/llm/vlm.py"
_VLM_SEND = "        resp = await self.client.post(endpoint, json=payload, headers=self._headers())"
_VLM_IMPORT = "from .egress import llm_async_client\n"
_SEND_THROUGH = {
    # The reviewer's probes on the real VLM backend: its cloud prompt sent through the bare
    # client inside a classified generic sender instead of its ledgered client.
    "home assistant REST": (
        "        resp = await _HttpxREST().request('POST', self.base_url.rstrip('/') + endpoint, "
        "json=payload, headers=self._headers())",
        "from ..house.home_assistant import _HttpxREST\n"),
    "wled JSON transport": (
        "        resp = await HttpxJSONTransport()(endpoint, payload)",
        "from ..house.wled import HttpxJSONTransport\n"),
}
_SEND_PROBES = {
    # ... and a new llm/ module posting a prompt through each of them.
    "agents/core/llm/zz_probe_send.py": (
        "from agents.core.house.home_assistant import _HttpxREST\n"
        "from agents.core.house.wled import HttpxJSONTransport\n"
        "async def ask_rest(prompt):\n"
        "    return await _HttpxREST().request('POST', 'https://api.openai.com/v1/chat/completions',\n"
        "        json={'messages': [{'role': 'user', 'content': prompt}]})\n"
        "async def ask_wled(prompt):\n"
        "    return await HttpxJSONTransport()('https://api.openai.com/v1/chat/completions',\n"
        "        {'messages': [{'role': 'user', 'content': prompt}]})\n"),
    # A forwarding helper outside llm/ is a sender itself, so the llm/ module that hands it
    # the cloud URL is a finding even if the helper were ever classified.
    "agents/core/tools/zz_probe_relay.py": (
        "from agents.core.house.home_assistant import _HttpxREST\n"
        "async def relay(url, body):\n"
        "    return await _HttpxREST().request('POST', url, json=body)\n"),
    "agents/core/llm/zz_probe_relayed.py": (
        "from agents.core.tools.zz_probe_relay import relay\n"
        "async def ask(prompt):\n"
        "    return await relay('https://api.openai.com/v1/chat/completions', {'prompt': prompt})\n"),
}
_HA_SENDER = "agents/core/house/home_assistant.py:_HttpxREST"
_WLED_SENDER = "agents/core/house/wled.py:HttpxJSONTransport"


def test_the_reviewer_send_through_probes_fail_the_repo_rule():
    """Round-4 review's mutation, made permanent through the whole pipeline: the real VLM
    backend sending its prompt through ``_HttpxREST.request`` or
    ``HttpxJSONTransport.__call__`` (classified generic senders that take the method, URL and
    body from their caller) passed all 17 structural tests, because only a client leaving
    its function was followed. A function whose bare client dials a host its caller decides
    is a sender now, and every caller is a finding of its own."""
    source = (REPO / _VLM).read_text(encoding="utf-8")
    assert source.count(_VLM_SEND) == 1 and source.count(_VLM_IMPORT) == 1, (
        f"{_VLM} changed; update this mutation")
    # One scan: the HA swap in the real vlm.py, the WLED swap in a copy of it beside it.
    swaps = {}
    for (send, imported), rel in zip(_SEND_THROUGH.values(), (_VLM, "agents/core/llm/zz_vlm_copy.py"),
                                     strict=True):
        swaps[rel] = source.replace(_VLM_SEND, send).replace(_VLM_IMPORT, _VLM_IMPORT + imported)
    in_scope, outside, _ = _scan_repo({**swaps, **_SEND_PROBES})
    offenders = _prompt_offenders(in_scope)
    for rel, target in zip(swaps, (_HA_SENDER, _WLED_SENDER), strict=True):
        failing = [o for o in offenders if o.startswith(rel + ":")]
        assert any("VLMBackend.generate_vision_checked" in o and f"constructs {target}" in o
                   for o in failing), (rel, failing)
        assert any("VLMBackend.generate_vision_checked" in o and f"hands a host to {target}" in o
                   for o in failing), (rel, failing)
    probe = {o.split(" — ")[0].split(" ", 1)[1] for o in offenders
             if o.startswith("agents/core/llm/zz_probe_send.py:")}
    assert probe == {"ask_rest", "ask_wled"}, offenders
    relayed = [o.split(" — ")[1] for o in offenders if o.startswith("agents/core/llm/zz_probe_relayed.py:")]
    assert relayed == ["calls agents/core/tools/zz_probe_relay.py:relay, which sends through a "
                       "bare client to a host its caller decides"], relayed
    assert [o.split(" — ")[0].split(" ", 1)[1] for o in _unclassified(outside)
            if o.startswith("agents/core/tools/zz_probe_relay.py:")] == ["relay", "relay"]


def test_every_caller_of_a_send_through_is_checked():
    """No exemption rests on its callers: a new caller of a classified or allowlisted sender
    is a finding until it is exempted itself, in-class callers included, and a sender's own
    bound method handed on uncalled is one too."""
    rel = "agents/core/llm/router.py"
    source = (REPO / rel).read_text(encoding="utf-8")
    anchor = "    async def _check(self, url: str) -> bool:\n"
    assert source.count(anchor) == 1, f"{rel} changed; update this mutation"
    added = source.replace(anchor, (
        "    async def ping(self, url):\n"
        "        return await self._check(url)\n\n"
        "    def checker(self):\n"
        "        return self._check\n\n") + anchor)
    found = {q for q, _, s in scan_source(added, rel) if "sends" in s or "hands a host" in s}
    assert {"LLMRouter.ping", "LLMRouter.checker"} <= found, found
    assert not {(rel, "LLMRouter.ping"), (rel, "LLMRouter.checker")} & set(PROMPT_SCOPE_ALLOWLIST)
    # A new caller of the classified Home Assistant transport, in its own module.
    rel = "agents/core/house/home_assistant.py"
    source = (REPO / rel).read_text(encoding="utf-8") + (
        "\n\nasync def _raw(url, body):\n"
        "    return await _HttpxREST().request('POST', url, json=body)\n")
    new = {q for q, _, _ in scan_source(source, rel)} - NOT_A_MODEL_PROVIDER[rel][1]
    assert new == {"_raw"}, new


# The reviewer's further shapes (round 4): each user module must be a finding.
_ROUND4_NET, _ROUND4_USER = "agents/core/netq.py", "agents/core/llm/zz_user.py"
_ROUND4_SHAPES = {
    "nested closure factory": (
        "import httpx\ndef make():\n    c = httpx.AsyncClient()\n    def get():\n        return c\n    return get\n",
        "from agents.core.netq import make\nasync def f(p):\n    return await make()().post('https://api.openai.com/v1/x', json=p)\n"),
    "lazy module global read off the module": (
        "import httpx\n_C = None\ndef init():\n    global _C\n    _C = httpx.AsyncClient()\n",
        "from agents.core import netq\nasync def f(p):\n    return await netq._C.post('https://api.openai.com/v1/x', json=p)\n"),
    "lazy module dict pool read off the module": (
        "import httpx\n_POOL = {}\ndef warm(k):\n    _POOL[k] = httpx.AsyncClient()\n",
        "from agents.core import netq\nasync def f(p):\n    return await netq._POOL['x'].post('https://api.openai.com/v1/x', json=p)\n"),
    "client returned through a configuring helper": (
        "import httpx\ndef _cfg(c):\n    c.headers['x'] = 'y'\n    return c\ndef make():\n    return _cfg(httpx.AsyncClient())\n",
        "from agents.core.netq import make\nasync def f(p):\n    return await make().post('https://api.openai.com/v1/x', json=p)\n"),
    "contextlib.closing wrapper": (
        "import contextlib, httpx\ndef make():\n    return contextlib.closing(httpx.Client())\n",
        "from agents.core.netq import make\ndef f(p):\n    with make() as c:\n        return c.post('https://api.openai.com/v1/x', json=p)\n"),
    "generic send-through function": (
        "import httpx\nasync def send(url, body):\n    async with httpx.AsyncClient() as c:\n        return await c.post(url, json=body)\n",
        "from agents.core.netq import send\nasync def f(p):\n    return await send('https://api.openai.com/v1/x', p)\n"),
    "generic send-through method": (
        "import httpx\nclass REST:\n    async def request(self, m, url, **kw):\n        async with httpx.AsyncClient() as c:\n            return await c.request(m, url, **kw)\n",
        "from agents.core.netq import REST\nasync def f(p):\n    return await REST().request('POST', 'https://api.openai.com/v1/x', json=p)\n"),
    "setattr on self (private)": (
        "import httpx\nclass H:\n    def __init__(self):\n        setattr(self, '_c', httpx.AsyncClient())\n",
        "from agents.core.netq import H\nasync def f(p):\n    return await H()._c.post('https://api.openai.com/v1/x', json=p)\n"),
    "public attribute planted on another object": (
        "import httpx\ndef install(registry):\n    registry.clients = {'x': httpx.AsyncClient()}\n",
        "async def f(registry, p):\n    return await registry.clients['x'].post('https://api.openai.com/v1/x', json=p)\n"),
    "vars().get private attr": (
        "import httpx\nclass Ctl:\n    def __init__(self):\n        self._c = httpx.AsyncClient()\n",
        "async def f(ctl, p):\n    return await vars(ctl).get('_c').post('https://api.openai.com/v1/x', json=p)\n"),
    "__dict__.get private attr": (
        "import httpx\nclass Ctl:\n    def __init__(self):\n        self._c = httpx.AsyncClient()\n",
        "async def f(ctl, p):\n    return await ctl.__dict__.get('_c').post('https://api.openai.com/v1/x', json=p)\n"),
    "subclass sets own private attr then reads inherited client": (
        "import httpx\nclass Ctl:\n    def _http(self):\n        if getattr(self, '_c', None) is None:\n"
        "            self._c = httpx.AsyncClient()\n        return self._c\n"
        "    async def tags(self):\n        return await self._http().get('/api/tags')\n",
        "from agents.core.netq import Ctl\nclass Mine(Ctl):\n    def reset(self):\n        self._c = None\n"
        "    async def ask(self, p):\n        await self.tags()\n"
        "        return await self._c.post('https://api.openai.com/v1/x', json=p)\n"),
    "operator.methodcaller of a factory method": (
        "import httpx\nclass Ctl:\n    def _http(self):\n        return httpx.AsyncClient()\n",
        "import operator\ndef f(ctl):\n    return operator.methodcaller('_http')(ctl)\n"),
}


def test_the_scanner_catches_the_round_four_shapes():
    """The 13 further hand-off shapes the round-4 review found missed, made permanent: every
    user module is a finding once its builder is exempted."""
    missed = [name for name, (net, user) in _ROUND4_SHAPES.items()
              if not scan_modules({_ROUND4_NET: net, _ROUND4_USER: user})[_ROUND4_USER]]
    assert missed == [], f"the scanner misses: {missed}"


def test_only_a_host_moving_parameter_makes_a_sender():
    """The host a send dials is traced through what can move it: a parameter in the path,
    query or body of a fixed origin does not (``f"{BASE}/api/show/{name}"``), one before the
    first ``/`` does (``f"http://{host}/x"``, ``base + path`` — a path can graft on
    ``@host``), and so does a client's ``base_url``."""
    def senders(source):
        found = scan_modules({_ROUND4_NET: source, _ROUND4_USER: (
            "from agents.core.netq import go\ndef f(x):\n    return go(x)\n")})
        return [s for _, _, s in found[_ROUND4_USER] if "sends through" in s]
    fixed = ("import httpx\nBASE = 'http://127.0.0.1:11434'\n"
             "async def go(name):\n    async with httpx.AsyncClient() as c:\n"
             "        await c.get(f'{BASE}/api/show/{name}', params={'q': name})\n"
             "        await c.post(BASE + '/api/x/' + name, json={'name': name})\n"
             "        await c.get(urlunsplit(('http', '127.0.0.1:1', name, name, '')))\n")
    assert senders(fixed) == []
    for moving in ("        await c.get(f'http://{name}/x')\n",
                   "        await c.get(BASE + name)\n",
                   "        await c.get(urlunsplit(('http', name, '/x', '', '')))\n",
                   "        await c.request('GET', str(name).rstrip('/'))\n"):
        assert senders(fixed + moving), moving
    based = ("import httpx\nasync def go(origin):\n"
             "    async with httpx.AsyncClient(base_url=origin) as c:\n        await c.get('/api/tags')\n")
    assert senders(based)


_PUBLIC_CLIENT_PINS = {
    # (module, class, public attribute) -> the request hook that refuses every other host
    ("agents/core/channels/telegram.py", "TelegramChannel", "client"): "_bot_api_only",
}


def test_every_public_bare_client_attribute_is_pinned_in_code():
    """A bare client in a public attribute (``orch.channels["telegram"].client``) is reached
    through objects the scanner cannot type (the stated limit), so the set is closed: a new
    one fails here, and each one listed refuses every other host before transport entry in
    every construction stored in it."""
    public = {(rel, cls, attr) for rel, cls, attr in _scan().facts.owners if not attr.startswith("_")}
    assert public == set(_PUBLIC_CLIENT_PINS), sorted(public ^ set(_PUBLIC_CLIENT_PINS))
    for (rel, cls, attr), hook in _PUBLIC_CLIENT_PINS.items():
        module = _Module(rel, (REPO / rel).read_text(encoding="utf-8"))
        stored = [value for _, value in module.self_sources[cls][attr]]
        assert stored, (rel, cls, attr)
        for value in stored:
            hooks = _keyword(value, "event_hooks")
            request = _keyword(hooks, "request") if hooks is not None else None
            assert isinstance(request, ast.List) and any(
                isinstance(h, ast.Name) and h.id == hook for h in request.elts), (
                f"{rel}:{value.lineno} stores a {cls}.{attr} without the {hook} request hook")


def test_the_telegram_client_dials_only_the_bot_api(monkeypatch):
    """Round-4 review: ``orch.channels["telegram"].client`` posted a prompt to a cloud host
    unseen. The channel's client now refuses any host but HTTPS api.telegram.org."""
    import asyncio

    import httpx
    import pytest

    from agents.core.channels.telegram import TelegramChannel, TelegramHostRefused

    sent: list[str] = []

    async def wire(self, request):
        sent.append(str(request.url))
        return httpx.Response(200, json={"ok": True, "result": {}}, request=request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", wire)
    prompt = {"messages": [{"role": "user", "content": "secret prompt"}]}

    async def run():
        channel = TelegramChannel("123:abc")
        try:
            for url in ("https://api.openai.com/v1/chat/completions",
                        "http://api.telegram.org/bot123:abc/getMe",
                        "https://api.telegram.org.evil.test/x"):
                with pytest.raises(TelegramHostRefused):
                    await channel.client.post(url, json=prompt)
            assert (await channel.client.post(channel.api_base + "/getMe")).status_code == 200
        finally:
            await channel.client.aclose()

    asyncio.run(run())
    assert sent == ["https://api.telegram.org/bot123:abc/getMe"]


def test_the_house_transports_refuse_every_non_lan_destination(monkeypatch):
    """Round-4 review's runtime probe: both house transports POSTed a prompt to
    api.openai.com. Each now checks the destination itself, before a client exists."""
    import asyncio

    import httpx
    import pytest

    from agents.core.house import home_assistant as ha
    from agents.core.house import wled

    sent: list[str] = []

    async def wire(self, request):
        sent.append(str(request.url))
        return httpx.Response(200, json={"on": False}, request=request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", wire)
    prompt = {"messages": [{"role": "user", "content": "secret prompt"}]}
    public = wled.HttpxJSONTransport(resolver=lambda host, port: ["203.0.113.9"])

    async def run():
        for url in ("https://api.openai.com/v1/chat/completions", "http://8.8.8.8:8123/api",
                    "http://ha.home.local:8123/api/states", "http://user@192.168.1.44/api"):
            with pytest.raises(ha._RESTDestinationRefused):
                await ha._HttpxREST().request("POST", url, json=prompt)
        assert (await ha._HttpxREST().request("GET", "http://192.168.1.44:8123/api/states")).status_code == 200
        for url in ("https://api.openai.com/v1/chat/completions", "http://8.8.8.8/json/state",
                    "http://wled.local/json/state", "http://192.168.1.40/json/state?x=1"):
            assert await public(url, prompt) == {"ok": False, "reason": "wled_url_rejected"}, url
        assert (await wled.HttpxJSONTransport()("http://192.168.1.40/json/state", {"on": False}))["ok"]

    asyncio.run(run())
    assert sent == ["http://192.168.1.44:8123/api/states", "http://192.168.1.40/json/state"]


def test_the_comfyui_backend_refuses_a_non_loopback_config(tmp_path):
    """``ComfyUIConfig`` is a plain dataclass: only ``from_env`` admitted loopback alone, so a
    directly built config could point the image prompt anywhere. The backend checks it."""
    import asyncio

    import httpx
    import pytest

    from agents.core.media_backends.comfyui import (
        ComfyUIBackend,
        ComfyUIConfig,
        ImageGenerationError,
    )

    sent: list[str] = []
    transport = httpx.MockTransport(lambda request: sent.append(str(request.url)) or httpx.Response(200))
    for url in ("https://api.openai.com", "http://192.168.1.9:8188"):
        backend = ComfyUIBackend(ComfyUIConfig(url, "a.safetensors", tmp_path), transport=transport)
        with pytest.raises(ImageGenerationError) as refused:
            asyncio.run(backend.generate("a secret image prompt", {}))
        assert refused.value.reason == "invalid_endpoint"
    assert sent == []


# ── round-5 review: a ledgered client turned bare, and the other ways in ─────

_ANTHROPIC = "agents/core/llm/anthropic.py"
_ANTHROPIC_LEDGERED = '                       else llm_async_client("anthropic", timeout=120.0))\n'
_HOOKS_PROBES = {
    # A new llm/ module stripping the request hooks off its own ledgered client.
    "agents/core/llm/zz_probe_hooks.py": (
        "from agents.core.llm.egress import llm_async_client\n"
        "async def ask(prompt):\n"
        "    c = llm_async_client('openai')\n"
        "    c._event_hooks['request'] = []\n"
        "    return await c.post('https://api.openai.com/v1/chat/completions', json={'p': prompt})\n"),
    # A module outside the scope that never names httpx, quietening the hub's backend.
    "agents/core/tools/zz_probe_hooks_outside.py": (
        "def quiet(orchestrator, log):\n"
        "    orchestrator.llm.client.event_hooks = {'request': [log]}\n"),
    # A model SDK reached through sys.modules, without an import statement.
    "agents/core/tools/zz_probe_sysmod.py": (
        "import sys\n"
        "def ask(prompt):\n"
        "    return sys.modules['openai'].OpenAI().chat.completions.create(model='m', messages=[prompt])\n"),
}
_VLM_SYSMOD_SEND = (
    "        import sys as _s\n"
    "        async with _s.modules['httpx'].AsyncClient(timeout=60.0) as _bare:\n"
    "            resp = await _bare.post(self.base_url.rstrip('/') + endpoint, json=payload,\n"
    "                                    headers=self._headers())")


def test_the_round_five_probes_fail_the_repo_rule():
    """Round-5 review's mutations, made permanent through the whole pipeline (parse filter,
    scope, rule, allowlists): the real Claude backend overwriting ``self.client.event_hooks``
    (httpx replaces every hook, so the egress recorder llm_async_client installed is gone),
    the real VLM backend clearing its request hooks, a new llm/ module storing into
    ``_event_hooks``, a module outside the scope rewiring a backend's hooks, and the httpx
    package or a model SDK reached through ``sys.modules`` — each passed all 25 structural
    tests before."""
    source = (REPO / _ANTHROPIC).read_text(encoding="utf-8")
    vlm = (REPO / _VLM).read_text(encoding="utf-8")
    assert source.count(_ANTHROPIC_LEDGERED) == 1, f"{_ANTHROPIC} changed; update this mutation"
    assert vlm.count(_VLM_SEND) == 1, f"{_VLM} changed; update this mutation"
    swaps = {
        _ANTHROPIC: source.replace(_ANTHROPIC_LEDGERED, _ANTHROPIC_LEDGERED
                                   + '        self.client.event_hooks = {"response": []}\n'),
        _VLM: vlm.replace(_VLM_SEND, "        self.client.event_hooks['request'].clear()\n" + _VLM_SEND),
        "agents/core/llm/zz_vlm_sysmod.py": vlm.replace(_VLM_SEND, _VLM_SYSMOD_SEND),
    }
    in_scope, outside, provider_modules = _scan_repo({**swaps, **_HOOKS_PROBES})
    offenders = _prompt_offenders(in_scope)

    def failing(rel, bucket=offenders):
        return sorted(o.split(" ", 1)[1] for o in bucket if o.startswith(rel + ":"))

    rewired = f"— {_HOOKS_REWIRED}: "
    assert failing(_ANTHROPIC) == [f"ClaudeBackend.__init__ {rewired}assigns .event_hooks"]
    assert failing(_VLM) == [
        f"VLMBackend.generate_vision_checked {rewired}reaches .clear of a hook container"]
    assert failing("agents/core/llm/zz_probe_hooks.py") == [
        f"ask {rewired}assigns an entry of a hook container"]
    assert failing("agents/core/llm/zz_vlm_sysmod.py") == [
        "VLMBackend.generate_vision_checked — reaches httpx through sys.modules"]
    unclassified = _unclassified(outside)
    assert failing("agents/core/tools/zz_probe_hooks_outside.py", unclassified) == [
        f"quiet {rewired}assigns .event_hooks"]
    assert failing("agents/core/tools/zz_probe_sysmod.py", unclassified) == [
        "ask — reaches a model SDK through sys.modules"]
    assert not {"agents/core/tools/zz_probe_hooks_outside.py",
                "agents/core/tools/zz_probe_sysmod.py"} & provider_modules
    # A function allowlisted for a bare client is not thereby allowed to rewire hooks.
    assert not set(HOOK_REWIRING_ALLOWLIST) & {(_ANTHROPIC, "ClaudeBackend.__init__"),
                                               (_VLM, "VLMBackend.generate_vision_checked")}


_HOOK_SHAPES = {
    "assigned": "def f(c, log):\n    c.event_hooks = {'request': [log]}\n",
    "private attribute": "def f(c):\n    c._event_hooks = {}\n",
    "one event replaced": "def f(c):\n    c.event_hooks['request'] = []\n",
    "one hook replaced": "def f(c, log):\n    c.event_hooks['request'][-1] = log\n",
    "slice replaced": "def f(c):\n    c.event_hooks['request'][:] = []\n",
    "cleared": "def f(c):\n    c.event_hooks['request'].clear()\n",
    "popped": "def f(c):\n    c.event_hooks['request'].pop()\n",
    "removed": "def f(c, h):\n    c.event_hooks['request'].remove(h)\n",
    "event popped": "def f(c):\n    c.event_hooks.pop('request')\n",
    "dict updated": "def f(c):\n    c.event_hooks.update(request=[])\n",
    "appended after the recorder": "def f(c, log):\n    c.event_hooks['request'].append(log)\n",
    "deleted": "def f(c):\n    del c.event_hooks['request']\n",
    "attribute deleted": "def f(c):\n    del c._event_hooks\n",
    "augmented": "def f(c, log):\n    c.event_hooks['request'] += [log]\n",
    "local alias": "def f(c):\n    hooks = c.event_hooks['request']\n    hooks.clear()\n",
    "get alias": "def f(c):\n    hooks = c.event_hooks.get('request', [])\n    del hooks[0]\n",
    "alias of an alias": "def f(c):\n    h = c.event_hooks\n    r = h['request']\n    r.pop()\n",
    "alias extended": "def f(c, log):\n    hooks = c.event_hooks['request']\n    hooks += [log]\n",
    "walrus alias": "def f(c):\n    if (h := c.event_hooks['request']):\n        h.clear()\n",
    "conditional alias": "def f(c, x):\n    h = c.event_hooks['request'] if x else []\n    h.clear()\n",
    "closure alias": ("def f(c):\n    hooks = c.event_hooks['request']\n    def g():\n"
                      "        hooks.clear()\n    return g\n"),
    "attribute alias in another method": (
        "class B:\n    def __init__(self, c):\n        self._h = c.event_hooks['request']\n"
        "    def reset(self):\n        self._h.clear()\n"),
    "setattr": "def f(c):\n    setattr(c, 'event_hooks', {})\n",
    "object.__setattr__": "def f(c):\n    object.__setattr__(c, '_event_hooks', {})\n",
    "delattr": "def f(c):\n    delattr(c, '_event_hooks')\n",
    "getattr then stored": "def f(c):\n    getattr(c, 'event_hooks')['request'] = []\n",
    "vars stored": "def f(c):\n    vars(c)['_event_hooks'] = {}\n",
    "__dict__ stored": "def f(c):\n    c.__dict__['_event_hooks'] = {}\n",
    "__dict__ updated": "def f(c):\n    c.__dict__.update(_event_hooks={})\n",
    "vars get then cleared": "def f(c):\n    vars(c).get('_event_hooks')['request'].clear()\n",
    "bound mutator uncalled": "def f(c):\n    wipe = c.event_hooks['request'].clear\n    wipe()\n",
    "mutator by name": "def f(c):\n    getattr(c.event_hooks['request'], 'clear')()\n",
    "handed to a helper": "import operator\ndef f(c):\n    operator.setitem(c.event_hooks, 'request', [])\n",
    "unbound list method": "def f(c):\n    list.clear(c.event_hooks['request'])\n",
    "handed out": "def hooks(c):\n    return c.event_hooks['request']\n",
    "put in a container": "def f(c):\n    pair = (c.event_hooks['request'], 1)\n    pair[0].clear()\n",
    "in a lambda": "def f(c):\n    return lambda: c.event_hooks['request'].clear()\n",
    "at module level": "import app\napp.client.event_hooks = {}\n",
}

# Reads of a client's hooks (and a hook dict that is not a client's): none is a finding.
_HOOK_READS = (
    "from agents.core.llm.egress import llm_async_client\n"
    "def f(c, log, **kwargs):\n"
    "    hooks = c.event_hooks.get('request', ())\n"
    "    if not hooks or getattr(hooks[-1], '_nerva_egress_recorder', False) is not True:\n"
    "        raise ValueError('no recorder')\n"
    "    sealed = tuple(c.event_hooks['request'])\n"
    "    assert len(c.event_hooks['request']) == len(sealed) and c.event_hooks['request'][-1] is not log\n"
    "    assert all(a is b for a, b in zip(c.event_hooks['request'], sealed, strict=True))\n"
    "    assert sum(bool(getattr(h, '_x', False)) for h in hooks) == 1\n"
    "    for hook in c.event_hooks['response']:\n"
    "        print(hook)\n"
    "    final = hooks[-1]\n"
    "    copy = list(c.event_hooks['request'])\n"
    "    copy.append(log)\n"
    "    copy.clear()\n"
    "    event_hooks = dict(kwargs.pop('event_hooks', None) or {})\n"
    "    event_hooks['request'] = [*event_hooks.get('request', []), log]\n"
    "    return final, llm_async_client('openai', event_hooks=event_hooks)\n"
)


def test_the_scanner_catches_every_hook_rewiring_shape():
    """Every way to drop the egress recorder off a ledgered client (or slip a hook after it)
    is a hook-rewiring finding; reading the hooks, copying them and building a client's own
    hook dict are not."""
    for name, source in _HOOK_SHAPES.items():
        found = [shape for _, _, shape in scan_source(source)]
        assert any(_rewires_hooks(shape) for shape in found), f"the scanner misses the {name!r} shape"
    assert scan_source(_HOOK_READS) == []
    # The realistic regression: a backend adding a logging hook by assignment.
    assert [q for q, _, s in scan_source(
        "from agents.core.llm.egress import llm_async_client\nclass B:\n    def __init__(self, log):\n"
        "        self.client = llm_async_client('openai')\n"
        "        self.client.event_hooks = {'response': [log]}\n") if _rewires_hooks(s)] == ["B.__init__"]


_HC_SEND = ("async def ask(prompt):\n"
            "    async with _hc.AsyncConnectionPool() as pool:\n"
            "        return await pool.request('POST', 'https://llm.example.com/v1/chat/completions',\n"
            "                                  content=prompt.encode())\n")
_DIRECT = "agents/core/llm/direct_transport.py"
_HC_PROBES = {
    # The reviewer's probe: httpcore re-exported by the identity-only direct_transport.
    "agents/core/llm/zz_probe_hc.py": "from .direct_transport import httpcore as _hc\n" + _HC_SEND,
    "agents/core/llm/zz_probe_hc_abs.py": (
        "from agents.core.llm.direct_transport import httpcore as _hc\n" + _HC_SEND),
    "agents/core/llm/zz_probe_hc_attr.py": (
        "from . import direct_transport\n_hc = direct_transport.httpcore\n" + _HC_SEND),
    "agents/core/llm/zz_probe_hc_getattr.py": (
        "import agents.core.llm.direct_transport as dt\n_hc = getattr(dt, 'httpcore')\n" + _HC_SEND),
    "agents/core/llm/zz_probe_hc_star.py": (
        "from .direct_transport import *\n" + _HC_SEND.replace("_hc.", "httpcore.")),
    # ... and through a relay outside the scope (never checked itself) of another one of them.
    "agents/core/zz_hc_relay.py": "from agents.core.ingestion.embedding_policy import httpcore as hc\n",
    "agents/core/llm/zz_probe_hc_relayed.py": "from ..zz_hc_relay import hc as _hc\n" + _HC_SEND,
}


def test_httpcore_handed_on_by_an_identity_module_is_caught():
    """Round-5 review: the other-HTTP-stack rule skipped every relative import and let the four
    identity-check modules use httpcore however they liked, so ``from .direct_transport import
    httpcore`` in a new llm/ module, or a send appended to direct_transport.py itself, posted a
    prompt through httpcore and the rule stayed green. A name re-exported from another repo
    module counts as importing the stack, and in an identity module only a type/identity check
    of httpcore is admitted."""
    source = (REPO / _DIRECT).read_text(encoding="utf-8")
    assert "\nimport httpcore\n" in source, f"{_DIRECT} changed; update this probe"
    appended = {
        "send": source + "\n\n" + _HC_SEND.replace("_hc.", "httpcore."),
        "alias": source + "\n_POOL = httpcore.AsyncConnectionPool\n",
        "subclass": source + "\nclass _Pool(httpcore.AsyncConnectionPool):\n    pass\n",
    }
    for how, mutated in appended.items():
        assert [line.split(" ", 1)[1] for line in _httpcore_reads(_Module(_DIRECT, mutated))] == [
            "uses httpcore.AsyncConnectionPool outside a type/identity check"], how
    assert _httpcore_reads(_Module(_DIRECT, source)) == []
    probes = {rel: src for rel, src in _HC_PROBES.items() if rel.startswith("agents/core/llm/")}
    assert all(_is_provider_module(_Module(rel, src)) for rel, src in probes.items())
    assert not _is_provider_module(_Module("agents/core/zz_hc_relay.py", _HC_PROBES["agents/core/zz_hc_relay.py"]))
    offenders = _other_stack_offenders({*_scan()[2], *probes, _DIRECT},
                                       {**_HC_PROBES, _DIRECT: appended["send"]})
    for rel in probes:
        assert any(o.startswith(rel + ":") and "httpcore" in o for o in offenders), (rel, offenders)
    assert [o for o in offenders if o.startswith(_DIRECT + ":")] != []
    assert {o.split(":")[0] for o in offenders} == {*probes, _DIRECT}, offenders


def test_sys_modules_is_caught_like_import_module():
    """Round-5 review: ``sys.modules['httpx']`` handed the httpx package on without an import,
    and the real VLM backend posted its prompt through a bare client built that way."""
    shapes = {
        "subscript": "import sys\ndef f():\n    return sys.modules['httpx'].AsyncClient()\n",
        ".get": "import sys\ndef f():\n    return sys.modules.get('httpx').Client()\n",
        "sys alias": "import sys as _s\ndef f():\n    return _s.modules['httpx']\n",
        "from sys import modules": "from sys import modules as m\ndef f():\n    return m['httpx._client'].AsyncClient()\n",
        "os.sys": "import os\ndef f():\n    return os.sys.modules.setdefault('httpx', None)\n",
        "__import__('sys')": "def f():\n    return __import__('sys').modules['httpx']\n",
        "model SDK": "import sys\ndef f():\n    return sys.modules['openai'].OpenAI()\n",
        "model SDK submodule": "import sys\ndef f():\n    return sys.modules.get('google.genai').Client()\n",
    }
    for name, source in shapes.items():
        assert [s for _, _, s in scan_source(source) if "sys.modules" in s], name
    assert scan_source("import sys\ndef f():\n    return sys.modules.get('agents.web'), sys.modules[__name__]\n") == []
    assert _SDK_HINT.search("x = sys.modules['openai']") and _SDK_HINT.search("modules.get('ollama')")
    vlm = (REPO / _VLM).read_text(encoding="utf-8")
    assert vlm.count(_VLM_SEND) == 1, f"{_VLM} changed; update this mutation"
    assert scan_source(vlm, _VLM) == []
    assert [(q, s) for q, _, s in scan_source(vlm.replace(_VLM_SEND, _VLM_SYSMOD_SEND), _VLM)] == [
        ("VLMBackend.generate_vision_checked", "reaches httpx through sys.modules")]


def test_a_reason_must_cite_a_test_that_exists():
    """Round-5 review: two NOT_A_MODEL_PROVIDER reasons cited tests that were never written and
    the reason checker only measured length. A cited test name or tests/ file must exist."""
    old = [("agents/core/house/home_assistant.py",
            "refuses any destination but a literal LAN address before a client exists "
            "(test_ha_rest_transport_refuses_every_non_lan_destination)"),
           ("agents/core/house/wled.py",
            "refuses any destination whose origin fails validate_wled_origin "
            "(test_wled_transport_refuses_every_non_lan_destination)"),
           ("x", "pinned in code (tests/test_no_such_file.py)")]
    assert _citation_errors(old) == [
        "agents/core/house/home_assistant.py cites test_ha_rest_transport_refuses_every_non_lan_"
        "destination, which no test defines",
        "agents/core/house/wled.py cites test_wled_transport_refuses_every_non_lan_destination, "
        "which no test defines",
        "x cites tests/test_no_such_file.py, which does not exist"]
    for rel in ("agents/core/house/home_assistant.py", "agents/core/house/wled.py"):
        assert "test_the_house_transports_refuse_every_non_lan_destination" in NOT_A_MODEL_PROVIDER[rel][0]
    assert _citation_errors([("y", "see tests/test_plugin_egress.py and "
                                   "test_the_house_transports_refuse_every_non_lan_destination")]) == []


# ── the Adopt lane: vendored Hermes code is scanned like any other module ───────

_VENDORED = ("agents/vendor/hermes/", "agents/vendor/hermes_compat/")


def test_vendored_hermes_code_has_no_bare_client_and_no_exemption():
    """agents/vendor/ is under agents/, so the repo scan already covers it; this pins that
    it holds no finding at all and that no allowlist or classification exempts it. The
    vendored files reach the network only through the compat httpx, which owns no client
    and hands every request to the bound PluginHTTPClient (tests/test_hermes_adopt_lane.py)."""
    in_scope, outside, _ = _scan()
    assert [rel for rel in (*in_scope, *outside) if rel.startswith(_VENDORED)] == []
    assert [rel for rel in NOT_A_MODEL_PROVIDER if rel.startswith(_VENDORED)] == []
    assert [key for key in (*PROMPT_SCOPE_ALLOWLIST, *HOOK_REWIRING_ALLOWLIST)
            if key[0].startswith(_VENDORED)] == []
    vendored = sorted((REPO / "agents" / "vendor").rglob("*.py"))
    assert vendored, "the vendor tree moved; update this test"
    for path in vendored:
        rel = path.relative_to(REPO).as_posix()
        assert scan_source(path.read_text(encoding="utf-8"), rel) == [], rel


def test_a_vendored_file_keeping_the_real_httpx_is_caught():
    """The rewrite undone (``import httpx`` left as upstream wrote it) is a bare client."""
    rel = "agents/vendor/hermes/plugins/web/_common.py"
    findings = _mutated(rel, "from agents.vendor.hermes_compat import httpx\n", "import httpx\n")
    assert findings and all(q == "http_get_json" for q, _, _ in findings)
