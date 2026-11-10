# The Adopt lane: running Hermes code inside Nerva

The Adopt lane (`feature-integration-plan-2026-11-10.md`) runs selected Hermes Agent source
files (MIT, NousResearch/hermes-agent) as they are, instead of re-writing them. Two rules hold:

1. **A vendored file stays upstream text.** The only change is a mechanical, recorded rewrite
   of its imports. A fix goes upstream, or the file is not adopted.
2. **Every effect still crosses Nerva's controls.** The rewritten imports point at the compat
   layer, and the compat layer maps each Hermes interface onto a Nerva control. Vendored code
   reaches no network client, no secret and no registry of its own.

## Layout

| Path | What it is |
|---|---|
| `agents/vendor/hermes/` | Vendored files at their upstream paths (`plugins/web/exa/provider.py` …), plus `LICENSE`, `NOTICE.md` (pinned commit) and `MANIFEST.json`. |
| `agents/vendor/hermes/MANIFEST.json` | Pinned commit, the rewrite rules, and per file: upstream sha256, vendored sha256, the rules applied. |
| `agents/vendor/hermes_compat/` | The shims vendored code imports. Nerva code, reviewed like any other. |
| `scripts/hermes_vendor.py` | `status`, `diff`, `pull`. |
| `tests/test_hermes_adopt_lane.py` | Behaviour, egress, structure and sync-script tests. |

The first slice (pinned `9c0560f8`) adopts three search providers: **Exa**, **Brave Search
(free tier)** and **Parallel**, with `plugins/web/_common.py`. Tavily, SearXNG and DuckDuckGo
are not adopted because Nerva has its own.

## The compat layer

| Hermes import | Compat module | Nerva control |
|---|---|---|
| `httpx` | `hermes_compat.httpx` | Owns no client. Each request goes to the `PluginHTTPClient` the adapter bound for the call, so the manifest allowlist, SSRF resolution with IP pinning, the breaker, the egress ledger and the kernel's `plugin.egress` hook apply. With nothing bound it refuses. The first refusal is recorded and repeated for the rest of the call, so a vendored `except Exception` cannot turn it into a retry or a rescue. Each wait is polled, so a worker stops when its caller leaves or the call's deadline passes. A request carrying a credential header is never sent with `follow_redirects`. |
| `exa_py`, `parallel` (SDKs) | `hermes_compat.sdk` | The real SDKs build their own HTTP clients, so they are never imported. Stand-ins implement the one call each provider makes (`Exa.search`, `Parallel.beta.search`) over the documented REST endpoint, through the compat `httpx`. |
| `agent.web_search_provider` | `hermes_compat.web_search_provider` | The `WebSearchProvider` base. `get_provider_env` reads a key through `agents.core.env_config` at call time, and only the key of the provider the adapter is running (`provider_scope`): Exa reads `EXA_API_KEY`, Brave `BRAVE_SEARCH_API_KEY`, Parallel `PARALLEL_API_KEY`. Any other name, another provider's key or a read outside a scope reads as unset. |
| `os` | `hermes_compat.os_env` | `getenv` only, for `PARALLEL_SEARCH_MODE` only, inside Parallel's scope. |
| `plugins.web.keyless_mcp` | `hermes_compat.keyless_mcp` | Off. Hermes's anonymous keyless tier is never used: a search goes only to a backend the owner configured. |
| `tools.interrupt`, `tools.web_tools`, `pm` | same names under `hermes_compat` | No interrupt flag (the e-stop acts at egress), the SDK cache slots, and no runtime installs. |
| plugin `ctx` | `hermes_compat.plugin_ctx` | `register_web_search_provider` wraps the provider in an adapter (`HermesSearchProvider`, a Nerva `SearchProvider`) and calls `register_search_provider`. The adapter sets the egress identity (`websearch`) and the tier from a reviewed table: all three count as paid, Brave too, since a `BRAVE_SEARCH_API_KEY` may be a paid-plan key. It never marks a provider keyless. It runs the synchronous vendored search on its own 4-thread executor, at most 3 at a time, never on the default executor the egress client needs for DNS. A search has 25 s (the tool loop cuts at 30 s) and its worker gives up when the caller leaves. It turns Hermes rows into Nerva rows (`title` / `url` / `snippet`), raises `PolicyBlock` from the recorded refusal and `ProviderFailure` with a reason code otherwise. A logging filter on each vendored logger drops records below WARNING, because upstream logs each query at INFO; a later `dictConfig` does not remove it. |

`agents/core/plugins/web_providers.py` loads the adopted providers after its built-ins
(`ADOPTED_PROVIDERS`). The hosts (`api.exa.ai`, `api.search.brave.com`, `api.parallel.ai`)
are on the `websearch` manifest allowlist, the same way the built-ins' hosts are.

## Rewrite rules

The rules live in `REWRITE_RULES` in `scripts/hermes_vendor.py` and are copied into the
manifest. `status` fails if the two differ. Each rule rewrites one import line in place, so
line numbers stay the same and upstream diffs stay readable. No replacement matches any
pattern, so the rewrite is idempotent. All rules but one rewrite an import. The exception,
`exa-integration-tag`, changes the caller name the Exa provider sends.

| Rule | Upstream line | Becomes |
|---|---|---|
| `httpx` | `import httpx` | `from agents.vendor.hermes_compat import httpx` Each wait is polled, so a worker stops when its caller leaves or the call's deadline passes. A request carrying a credential header is never sent with `follow_redirects`. |
| `os-env` | `import os` | `from agents.vendor.hermes_compat import os_env as os` |
| `web-search-provider` | `from agent.web_search_provider import …` | `from agents.vendor.hermes_compat.web_search_provider import …` |
| `keyless-mcp` | `from plugins.web.keyless_mcp import …` | `from agents.vendor.hermes_compat.keyless_mcp import …` |
| `plugins-web` | `from plugins.web.… import …` | `from agents.vendor.hermes.plugins.web.… import …` |
| `interrupt` | `from tools.interrupt import …` | `from agents.vendor.hermes_compat.interrupt import …` |
| `web-tools-slots` | `import tools.web_tools as …` | `import agents.vendor.hermes_compat.web_tools as …` |
| `pm` | `import pm` | `from agents.vendor.hermes_compat import pm` |
| `exa-sdk` | `from exa_py import …` | `from agents.vendor.hermes_compat.sdk.exa_py import …` |
| `exa-integration-tag` | `client.headers["x-exa-integration"] = "hermes-agent"` | `… = "nerva"` |
| `parallel-sdk` | `import parallel` | `from agents.vendor.hermes_compat.sdk import parallel` |

A new rule is a code change to the script and needs a compat module behind it. It is never a
hand edit to a vendored file.

## Vendoring a file / updating

```bash
# where things stand: hashes vs manifest, local edits, unlisted files
python scripts/hermes_vendor.py status
python scripts/hermes_vendor.py status --upstream ~/src/hermes-agent   # also: still == rewritten upstream?

# what an update would change, per file, with the rewrites applied (review this diff)
python scripts/hermes_vendor.py diff --upstream ~/src/hermes-agent

# take it (or vendor a new file): rewrites, writes, updates MANIFEST.json
python scripts/hermes_vendor.py pull --upstream ~/src/hermes-agent plugins/web/exa/provider.py
```

`pull` reads the clone's commit with `git rev-parse` (or takes `--commit`). It refuses a
symlink, or a path that resolves outside the clone. It refuses a file with local edits unless
you pass `--force`. It refuses a file that, after the rewrite, falls outside the
**allowlist**:

- a `.py` file may import only `SAFE_STDLIB`, the listed compat modules and vendored
  siblings;
- `os` is allowed only as `os_env as os`;
- the only relative import allowed is `from .x import y`;
- no network, process or import-machinery names, as attributes or strings;
- any other file must be YAML, JSON, Markdown or text that parses as plain data.

`status` applies the same allowlist and checks `rules_applied` against the bytes.
`tests/test_hermes_adopt_lane.py` runs it over the whole vendored tree on every CI pass. Its
output is deterministic: the manifest is written with sorted keys, and pulling the same text
twice leaves it byte-identical. After a pull:

1. Read the `diff` output. A change that adds an import, a host or a new `ctx.register_*`
   call needs the compat layer (and possibly the manifest allowlist) to cover it first.
2. Update `NOTICE.md` if the pinned commit moved.
3. Run `pytest tests/test_hermes_adopt_lane.py tests/test_h381_no_bare_model_client.py
   tests/test_websearch.py tests/test_h310_web_parity.py tests/test_plugin_egress.py`.

## What may be adopted

- **Yes:** leaf modules whose Hermes imports are few and map onto an existing Nerva control:
  search and extract providers, leaf tools such as `todo` and `clarify` (through a future
  `tools.registry` shim onto the kernel-gated tool server), plugins whose `register(ctx)` uses
  only `ctx` methods the compat layer offers, and SKILL.md skills (through the skills importer).
- **No:** anything that needs a network client, a subprocess, the filesystem or a secret store
  that is not behind a compat shim mapped onto a Nerva control. Also no modules tangled with
  `hermes_state`, `hermes_cli.config`, the gateway or the agent loop (the Run lane covers them
  through the sidecar), and no file that needs editing to work here.
- **Security-sensitive areas** (approvals, memory writes, execution, delegation, credentials)
  get adversarial review even when adopted.

## Limits of the first slice

- Only **search** is wired. The vendored files also contain Exa and Parallel `extract`. Their
  SDK calls (`Exa.get_contents`, `AsyncParallel`) are not in the stand-ins, so they would
  return an error entry. Nerva's `web_extract` uses its own reader.
- The SDK stand-ins follow the vendors' documented REST APIs and are tested against a fake
  transport only. No live call was made.
- `parallel/provider.py` reads `PARALLEL_SEARCH_MODE` with `os.getenv`. The `os-env` rule
  points that read at the allowlisted shim, but the line still counts in the AUD-14 raw-read
  ratchet.

## Model providers (slice 2)

Hermes keeps what it knows about each inference provider in a small `ProviderProfile`
subclass under `plugins/model-providers/<name>/`: the base URL, the model ids it offers, the
key names, and the request extras that vendor wants (DeepSeek's `thinking` toggle, GLM's
effort scale, Fireworks's top-level `reasoning_effort`, DashScope's `preserve_thinking` …).
Slice 2 (same pin, `9c0560f8`) runs those profiles as they are for the providers Nerva had no
native support for. Nerva's OpenAI-compatible backend (`OpenRouterBackend`) sends the request.

### Inventory

**Native in Nerva, kept native** (the Hermes profile is not used): `anthropic`, `gemini`,
`openrouter`, `deepinfra`, `xai`, `nous` (Nerva's Nous vision route), `lmstudio` and local
`ollama`, `custom` (Nerva's custom endpoints).

**Adopted** (24 provider ids from 19 profile modules). Each depends only on
`providers/base.py`, the registry and `agent/reasoning_effort.py`, all vendored or covered
by the compat layer:

| Provider id | Profile module | Key names (first set wins) | What the profile adds to a request |
|---|---|---|---|
| `deepseek` | `deepseek` | `DEEPSEEK_API_KEY` | V4: `thinking` on/off + `reasoning_effort` (low…max) |
| `zai` | `zai` | `GLM_API_KEY`, `ZAI_API_KEY`, `Z_AI_API_KEY` | GLM-4.5+: `thinking` on/off (`clear_thinking: false`); GLM-5.2/5.3: `reasoning_effort` |
| `kimi-coding` | `kimi-coding` | `KIMI_API_KEY`, `KIMI_CODING_API_KEY` | `reasoning_effort` (low/high/max) or `thinking`; temperature omitted; output cap 32000 |
| `kimi-coding-cn` | `kimi-coding` | `KIMI_CN_API_KEY` | same, mainland-China host |
| `fireworks` | `fireworks` | `FIREWORKS_API_KEY` | top-level `reasoning_effort` (`none` turns it off) |
| `ollama-cloud` | `ollama-cloud` | `OLLAMA_API_KEY` | top-level `reasoning_effort` (`none` turns it off) |
| `nebius-token-factory` | `nebius-token-factory` | `NEBIUS_API_KEY`, `NEBIUS_TOKEN_FACTORY_API_KEY` | `reasoning_effort` (low/medium/high) for reasoning families |
| `upstage` | `upstage` | `UPSTAGE_API_KEY` | `reasoning_effort` (low/medium/high) |
| `ai-gateway` | `ai-gateway` | `AI_GATEWAY_API_KEY` | `reasoning` object passthrough |
| `commandcode` | `commandcode` | `COMMANDCODE_API_KEY` | DeepSeek ids reuse the `deepseek` profile's controls |
| `alibaba`, `alibaba-cn`, `alibaba-token-plan`, `alibaba-token-plan-cn` | `alibaba` | `DASHSCOPE_API_KEY` / `ALIBABA_TOKEN_PLAN_*_API_KEY` | `preserve_thinking` / `clear_thinking` for models that replay reasoning |
| `alibaba-coding-plan`, `alibaba-coding-plan-cn` | `alibaba-coding-plan` | `ALIBABA_CODING_PLAN_*_API_KEY`, then `DASHSCOPE_API_KEY` | same |
| `nvidia` | `nvidia` | `NVIDIA_API_KEY` | strips `name` from tool messages; output cap 16384 |
| `huggingface`, `kilocode`, `novita`, `gmi`, `arcee`, `stepfun`, `xiaomi` | same names | `HF_TOKEN`, `KILOCODE_API_KEY`, `NOVITA_API_KEY`, `GMI_API_KEY`, `ARCEEAI_API_KEY`, `STEPFUN_API_KEY`, `XIAOMI_API_KEY` | base URL and model list only |

The table lives in `agents/core/llm/hermes_provider_table.py` (pure data: settings, the
managed-key list and the bridge read it). `tests/test_hermes_model_providers.py` pins every row
against the vendored profile.

**Not adopted in this slice:**

| Profile | Why |
|---|---|
| `actual` | needs `sys`, `agent.ssl_verify` and `hermes_cli.auth` (a local relay with its own TLS bundle) |
| `azure-foundry` | no fixed host: the base URL is per resource, typed by the user |
| `bedrock` | AWS SDK credentials and the Bedrock Converse wire, not OpenAI-compatible HTTP |
| `minimax`, `minimax-cn`, `minimax-oauth` | Anthropic Messages wire (`/anthropic` base URLs); Nerva's Anthropic backend is pinned to Anthropic's host |
| `commandcode-anthropic` | Anthropic Messages wire (its chat sibling `commandcode` is adopted) |
| `meta-ai` | Responses wire (`codex_responses`); Nerva's Responses backend is pinned to OpenAI's host |
| `qwen-oauth` | OAuth sign-in (`oauth_external`), no API key |
| `openai-codex` | ChatGPT OAuth sign-in on the Responses wire; Nerva's `openai-responses` route serves OpenAI API keys |
| `tencent-tokenhub` | the profile has no base URL; the endpoint lives in `hermes_cli/auth.py` |
| `opencode-zen` | needs `httpx` (account usage) and `hermes_cli.runtime_provider` |
| `router` | needs `hermes_constants`, `hermes_cli.config`, disk caches and its own catalog fetches |
| `solstice` | OAuth PKCE plugin and its own transport |
| `vertex` | Gemini wire through `agent.transports` |
| `custom` | needs `utils`; Nerva's custom endpoints cover it |

### How a request is built

`agents/core/llm/hermes_profiles.py` loads the vendored modules into the compat registry
(`hermes_compat.providers`) and wraps each profile in `HermesAdoptedProfile`, a Nerva
`ProviderProfile` registered in `DEFAULT_REGISTRY` after the built-ins. From the Hermes
profile: the base URL (fixed; a profile's `*_BASE_URL` override is not read), fallback models,
`prepare_messages`, `build_extra_body`, `build_api_kwargs_extras`, `get_max_tokens`, the fixed
temperature. Everything else is Nerva's: the client, streaming, tool calls, retries, cost,
the kernel, the request headers and the key.

- **Destination.** `adopted_client` is `egress.llm_async_client` (ledger, quota guard, TLS
  anchor, host protocol, data-handling gate) plus a first request hook that refuses any origin
  other than the profile's own `https://<host>:443`, and the host if the egress SSRF resolver
  (`security.ssrf.resolve_and_validate`, run off the event loop) finds any non-public address
  for it; a DNS failure fails closed as unreachable. A refusal is a ledger row with
  `allowed=False` and the request never reaches the transport. The resolved address is not
  pinned for the connection, so a rebinding between the check and the dial is a known limit.
  `OpenRouterBackend` refuses an adopted profile on another base URL or with a client that
  lacks that hook, so the router, `construct_backend` and tests all get the pin.
- **Key checks.** `provider_probe.probe_all` (the HUD's "check keys") probes an adopted
  provider only when it is the selected one: its key names are shared across hosts
  (`DASHSCOPE_API_KEY` serves the international and the mainland endpoint; `HF_TOKEN` and
  Kimi keys have other uses). The probe client takes the same destination pin, and the probe
  reads every key name of the provider.
- **Signed packages.** The adopted profiles are not built-ins of the signed provider registry
  (`install_service.admitted_builtins`): a package the owner signed with an id such as
  `deepseek` or an alias such as `zai` keeps winning and stays selectable, and no alias can
  collide with an adopted id.
- **Choosing one is acknowledged.** Like a custom endpoint or a signed package, choosing an
  adopted provider's model needs `acknowledge_training` (its data handling is unverified; an
  audited consent row) and `confirm_expensive` when Nerva has no price for the model
  (`selection_guards.adopted_data_policy_guard` / `adopted_price_guard`).
- **Keys.** Only the names in the provider's table row, read through `env_config` at
  construction. A Kimi Code key (`sk-kimi-…`) is refused on the `kimi-coding` routes with a
  message: it belongs to `api.kimi.com/coding`, which those routes do not reach. A provider is off until one is set and the owner picks it in
  `llm.compatible_provider` (the settings select lists the ids). The names are managed
  (`code_env`), so a skill cannot be granted them, and the support bundle lists them.
- **Headers.** `User-Agent`, `HTTP-Referer`, `X-Title` (Hermes Agent attribution) and
  `Accept-Encoding` are dropped. The compat `hermes_user_agent` answers "Nerva" anyway.
- **Reasoning.** Sent only when the owner turned on `llm.compatible_reasoning_enabled` and chose
  `llm.reasoning_effort`. Nerva first clamps the choice to the levels the profile sends
  verbatim for that model (`derived_efforts`, probed from the profile itself, pure): nearest
  weaker, below the minimum refused. Then the profile shapes the wire, and `check_reasoning`
  lets through only a restatement: an on/off toggle that matches the choice, or a level no
  stronger than it ("off" always passes). With no effort chosen, no reasoning field is sent,
  except DeepSeek's explicit "on" toggle (DeepSeek and CommandCode's DeepSeek ids): the server
  thinks by default and an omitted toggle then demands `reasoning_content` echoes, so the toggle
  restates the default. Hermes's own upward roundings (Kimi K3 `medium → high`, `xhigh → max`,
  GLM-5.2 floor `high`) do not apply: Nerva clamps down or refuses, as for every other provider.
  - *On/off-only models* (GLM-4.5/4.6/5, whose profile has a toggle and no levels): a bare "on"
    is full thinking, so `minimal` and `low` are sent as "off", `medium` and up as "on". A model
    whose profile cannot say "off" refuses `minimal`/`low` instead of thinking.
  - *Profiles without a model gate* (`fireworks`, `ai-gateway`, `ollama-cloud`): Hermes asks its
    core catalog whether a model reasons; Nerva has none, so these send an effort only for a model
    the owner declared in `llm.compatible_effort_declarations` (`{"model": ["low", "high"]}`).
- **Data policy.** `unknown` for every adopted provider until someone checks the vendor terms.

### Compat and rule additions

| Hermes import | Rule | Becomes |
|---|---|---|
| `from providers.base import …` | `providers-base` | the vendored `agents.vendor.hermes.providers.base` |
| `from providers import …` | `providers-registry` | `hermes_compat.providers` (a dict; the bridge reads it) |
| `from agent.reasoning_effort import …` / `from agent import reasoning_effort` | `reasoning-effort`, `reasoning-effort-module` | the vendored `agents.vendor.hermes.agent.reasoning_effort` (pure) |
| `from agent.account_usage import …` | `account-usage` | `hermes_compat.account_usage` (type names only) |
| `from hermes_cli.{version_info,auth,urllib_security,chat_catalog} import …` | `hermes-cli-leaf` | `hermes_compat.hermes_cli`: user agent "Nerva", empty credential pool, `open_credentialed_url` refused |
| `import threading` | `threading-locks` | `hermes_compat.locks` (`Lock`, `RLock` only) |
| `import urllib.request` | `urllib-request` | `hermes_compat.urllib_refused` (an inert `Request`, no opener) |

`urllib.parse` joined `SAFE_STDLIB`, but only as `from urllib.parse import …`: `import
urllib.parse` binds `urllib`, so it is refused, as is any `import a.b` whose `a` is not
allowed. `urllib.request` (and `.error`, `.response`) is refused on any name not bound to a
compat module. `urlopen`, `urlretrieve`, `build_opener`, `install_opener`, `OpenerDirector`,
and modules reached as attributes (`.os`, `.sys`, `.socket`, `.ssl`, `.http`, `.subprocess`,
`.system`, `.popen`, `.Thread` …) joined the denied names. `providers/__init__.py` and
`agent/__init__.py` under the vendor tree are Nerva-written package markers (the upstream ones
are a plugin loader and a JSON preloader); `status` refuses them if they hold more than a
docstring. So `ProviderProfile.fetch_models` exists in the vendored base but cannot reach the
network: it builds an inert request and the compat opener refuses it.

### Adding a model provider

1. Check the profile's imports: `python scripts/hermes_vendor.py diff --upstream <clone>
   plugins/model-providers/<name>/__init__.py` prints `!!!` for anything outside the allowlist.
   It must be `api_mode="chat_completions"`, `auth_type="api_key"`, with a fixed HTTPS
   `base_url`.
2. `python scripts/hermes_vendor.py pull --upstream <clone> plugins/model-providers/<name>/__init__.py
   plugins/model-providers/<name>/plugin.yaml`.
3. Add a row to `ADOPTED_MODEL_PROVIDERS` (id, directory, key names without `*_BASE_URL`,
   display name if the profile has none) and a case to `CASES` in
   `tests/test_hermes_model_providers.py` (a representative model and effort).
4. Document the key in `.env.example` and run `pytest tests/test_hermes_model_providers.py
   tests/test_hermes_adopt_lane.py tests/test_h381_no_bare_model_client.py`.

### Limits of slice 2

- Model lists are the profiles' static `fallback_models`; no live catalog fetch.
- `xiaomi` is vision-capable in Hermes; it is not offered for Nerva's vision routes.
- GLM-5.3 cannot turn thinking off, so `reasoning_effort=none` on it is refused, not ignored.
- Kimi Code keys are refused rather than routed to `api.kimi.com/coding` (a second pinned id for
  that host would be the way to add it).
- Tested against a fake transport only. No live call to any of these providers was made.
