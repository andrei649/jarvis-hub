# Model Providers, Model Catalog, Routing, Credentials & Billing

This shard documents everything Hermes Agent v2026.8.31 knows about *where inference comes from and
who pays for it*: the `ProviderProfile` plugin system and all 48 registered provider profiles
(shipped from 40 plugin directories under `plugins/model-providers/`), the per-provider wire adapters
(`agent/*_adapter.py`, `agent/codex_*`, `agent/anthropic_*`), the model catalog and metadata layers
(`agent/models_dev.py`, `agent/model_metadata.py`, `hermes_cli/model_catalog.py`), the `hermes model`
picker and `hermes setup model` flows, the fallback chain, Mixture-of-Agents (`/moa`), the local
OpenAI-compatible proxy (`hermes proxy`), OAuth logins (Nous, OpenAI Codex, xAI, Qwen, MiniMax,
Copilot, Vercel), the credential pool / rotation / rate-limit trackers, and the whole
billing/subscription/top-up/usage-reporting surface (`/topup`, `/usage`, `hermes insights`,
`--usage-file`).
Deliberately left to sibling shards: the generic Config page and every non-provider config key
(config-a/config-b), the dashboard SPA chrome and non-billing pages (web-*), the desktop Electron
shell (desktop-*), gateway slash-command plumbing that is not billing/model related (gw-slash),
tools/toolsets (tools), and image-gen / TTS / STT / transcription / web-search provider registries
(those are separate `*_registry.py` subsystems, not model providers).

---

## 1. Provider plugin system

### Provider profile registry (`providers/`)  `id: providers.registry`
- **Surface:** Core
- **Where:** Python package `providers/` — `providers.register_provider()`, `providers.get_provider_profile(name)`, `providers.list_providers()`. Not user-facing directly; every provider-aware surface (setup wizard, `hermes model`, `hermes doctor`, transports) reads it.
- **What it does:** Holds one declarative `ProviderProfile` per inference provider so that auth resolution, transport kwargs, model listing and runtime routing all read from a single object instead of parallel hard-coded tables.
- **How it works:** `providers/__init__.py:45-48` keeps `_REGISTRY: dict[str, ProviderProfile]`, `_ALIASES: dict[str,str]`, `_PROVIDER_LIST_CACHE` and a `_discovered` flag. `register_provider()` (`providers/__init__.py:56-67`) writes `_REGISTRY[profile.name] = profile`, maps every alias, invalidates the list cache — **last writer wins**, which is how user plugins override bundled ones. `get_provider_profile()` (`:70-78`) resolves alias→canonical then looks up; returns `None` for unknown providers (caller falls back to generic behaviour). `list_providers()` (`:81-97`) dedups by `id(profile)` so an alias never yields a duplicate row. Discovery is lazy and runs once (`_discover_providers()`, `:271-341`) in a fixed precedence order: **(0)** pip entry-point plugins in group `hermes_agent.plugins` (`_discover_entry_point_providers()`, `:149-244`), **(1)** bundled `<repo>/plugins/model-providers/<name>/`, **(2)** user `$HERMES_HOME/plugins/model-providers/<name>/`, **(3)** legacy single-file `providers/<name>.py` modules via `pkgutil.iter_modules`. Because registration is last-writer-wins, pip packages have the LOWEST precedence and can never hijack a first-party provider name.
- **Inputs / options:** `register_provider(profile)`; `get_provider_profile(name_or_alias)`; `list_providers()`. Directory names may not start with `_` or `.` (`:305-307`, `:315-317`).
- **Outputs / side effects:** Imports arbitrary Python from plugin directories. Bundled plugins get the stable module name `plugins.model_providers.<safe_name>` (dashes → underscores); user plugins get `_hermes_user_provider_<safe_name>` so two HERMES_HOMEs cannot alias each other (`:120-128`). A failed plugin import is logged at WARNING (`Failed to load %s provider plugin %s: %s`) and popped from `sys.modules` (`:142-146`) — one broken plugin never breaks discovery.
- **Config / env:** `HERMES_HOME` (via `hermes_constants.get_hermes_home()`) locates user plugins. `plugins.enabled` / `plugins.disabled` gate entry-point providers (`:190-197`) — the entry-point scan returns immediately when `plugins.enabled` is empty (opt-in default).
- **Edge cases / guards:** Entry-point targets that require arguments are skipped (`_requires_arguments()`, `:247-268`) because `register(ctx)`-style general plugins share the same entry-point group and belong to `PluginManager`, not here. Unintrospectable C callables are treated as zero-arg. `_user_plugins_dir()` returns `None` when `$HERMES_HOME/plugins/model-providers` does not exist.
- **Rebuild notes:** A dict registry + alias map + lazy filesystem scan with documented precedence. A better version would hash-verify third-party plugin directories, sandbox the import, and expose a `hermes providers list` command that shows origin (bundled/user/pip) per profile.

### `ProviderProfile` dataclass  `id: providers.profile-dataclass`
- **Surface:** Core
- **Where:** `providers/base.py:38-296`. Subclassed by ~20 provider plugins.
- **What it does:** Declares everything about one inference provider in one place — identity, auth, endpoints, client quirks, request quirks — so the transport reads a profile instead of receiving 20+ boolean flags.
- **How it works:** Frozen-by-convention (not `frozen=True`) dataclass. Fields and defaults, verbatim from `providers/base.py`:
  - **Identity:** `name: str` (required, `:43`); `api_mode: str = "chat_completions"` (`:44`) — one of `chat_completions` | `anthropic_messages` | `codex_responses` | `bedrock_converse`; `aliases: tuple = ()` (`:45`).
  - **Metadata:** `display_name: str = ""` (`:48`, shown in picker/labels); `description: str = ""` (`:49`, picker subtitle); `signup_url: str = ""` (`:50`, shown during setup).
  - **Auth & endpoints:** `env_vars: tuple = ()` (`:53`); `base_url: str = ""` (`:54`); `models_url: str = ""` (`:55`, falls back to `{base_url}/models`); `auth_type: str = "api_key"` (`:56`) — documented set `api_key|oauth_device_code|oauth_external|copilot|aws_sdk` plus the shipped extras `vertex` and `external_process`; `supports_health_check: bool = True` (`:57`) — `False` makes `hermes doctor` skip the `/models` probe.
  - **Vision:** `supports_vision: bool = False` (`:66`) — provider API accepts image content in tool-result messages natively; `supports_vision_tool_messages: bool = True` (`:73`) — `False` for providers that accept multimodal user messages but reject list-type tool content (Xiaomi MiMo returns 400 `"text is not set"`).
  - **Caching:** `supports_prompt_cache_key: bool = False` (`:79`) — opt-in because many OpenAI-compatible endpoints reject unknown top-level fields.
  - **Catalog:** `fallback_models: tuple = ()` (`:84`, curated list for the `/model` picker when live fetch fails — tool-calling models only); `hostname: str = ""` (`:88`, for URL→provider reverse mapping; derived from `base_url` when empty).
  - **Client quirks:** `default_headers: dict[str,str] = {}` (`:91`).
  - **Request quirks:** `fixed_temperature: Any = None` (`:95`; the module-level sentinel `OMIT_TEMPERATURE = object()` at `:21` means "don't send temperature at all" — used by Kimi); `default_max_tokens: int | None = None` (`:96`); `default_aux_model: str = ""` (`:97`, cheap model for compression/vision/titles; empty = use main model).
- **Inputs / options:** Nine overridable hooks: `resolve_aux_model(*, vision=False) -> str` (`:104-118`, must cache, never raise, `""` = fall through to `default_aux_model`); `get_hostname() -> str` (`:120-131`); `prepare_messages(messages) -> list` (`:133-139`, runs AFTER codex field sanitization, BEFORE developer-role swap); `build_extra_body(*, session_id=None, **context) -> dict` (`:141-148`); `build_api_kwargs_extras(*, reasoning_config=None, **context) -> (extra_body_additions, top_level_kwargs)` (`:150-168`); `default_vision_model() -> str|None` (`:170-181`); `get_max_tokens(model) -> int|None` (`:183-195`); `supported_reasoning_efforts(model) -> tuple|None` (`:197-224`, tri-state: `None`=unknown/defer, `()`=model takes no reasoning params at all, non-empty tuple=clamp target; must be cache-only, no network on hot path); `fetch_models(*, api_key=None, base_url=None, timeout=8.0) -> list[str]|None` (`:226-296`).
- **Outputs / side effects:** `fetch_models` default implementation performs one HTTP GET. URL resolution order (`:259-271`): (1) `caller_base + "/models"` only when the caller's `base_url` differs from `self.base_url` (i.e. user configured a proxy); (2) `self.models_url`; (3) `self.base_url + "/models"`. Sends `Authorization: Bearer <api_key>` when a key is given, `Accept: application/json`, `User-Agent: hermes-cli/<version>` (from `_profile_user_agent()`, `:24-35` — needed because some providers' WAFs 403 the default `Python-urllib/<ver>` UA), plus every `default_headers` entry. Parses `data` as a list or `{"data":[...]}` and returns `[m["id"] ...]`. All exceptions → `logger.debug` + `None`.
- **Config / env:** n/a (the profile is the config).
- **Edge cases / guards:** `open_credentialed_url` from `hermes_cli.urllib_security` wraps the request (SSRF/redirect guard for credentialed URLs). Callers **must** fall back to the static `_PROVIDER_MODELS` list when `fetch_models` returns `None`.
- **Rebuild notes:** One dataclass + eight hooks covers 48 providers. A better version would make `api_mode` an enum, add a `supports_tools`/`supports_parallel_tools` tri-state, and make `fetch_models` async with a shared connection pool and a per-provider ETag cache.

### Bundled provider plugin layout & manifest  `id: providers.plugin-layout`
- **Surface:** Config
- **Where:** `plugins/model-providers/<name>/__init__.py` + `plugins/model-providers/<name>/plugin.yaml`; documented in `plugins/model-providers/README.md`.
- **What it does:** Defines the on-disk contract for adding or replacing a model provider without editing repo code.
- **How it works:** `__init__.py` must call `providers.register_provider(profile)` at import time. `plugin.yaml` is the manifest read for introspection by `PluginManager` (which records model-provider manifests but deliberately does NOT import them — provider lifecycle belongs to `providers/__init__.py`).
- **Inputs / options:** `plugin.yaml` keys observed across all 40 bundled plugins: `name` (e.g. `openrouter-provider`), `kind: model-provider` (constant), `version` (all `1.0.0`), `description`, `author` (values seen: `Nous Research`, `Alex Jestin Taylor (@alex-fireworks) + Hermes Agent`, `Georgi Atsev`, `Beto de Paola`, `Upstage AI`, `Actual Computer`, `bilboquet`, `Steve Lawton (@slawt), Hermes Agent`, `Neel Patel (Ramp)`), and optionally `homepage` (only `meta-ai`: `https://github.com/albertodepaola/hermes-meta-provider`).
- **Outputs / side effects:** Dropping a directory under `$HERMES_HOME/plugins/model-providers/<name>/` overrides the bundled profile of the same name.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** Directory names beginning `_` or `.` are skipped. Relative imports inside a bundled plugin work because the module is imported as `plugins.model_providers.<safe_name>` with `submodule_search_locations` set.
- **Rebuild notes:** Directory + `__init__.py` + YAML manifest. A better version would validate `plugin.yaml` against a JSON Schema at load time and refuse a manifest whose `name`/`kind` disagree with the registered profile.

### Pip-installed provider plugins (entry point `hermes_agent.plugins`)  `id: providers.entrypoint-plugins`
- **Surface:** Config
- **Where:** A distribution declares `[project.entry-points."hermes_agent.plugins"] acme-inference = "acme_hermes_plugin:register"`.
- **What it does:** Lets a `pip install`ed package register a provider profile.
- **How it works:** `providers/__init__.py:149-244`. Runs FIRST (lowest precedence). Target may be a callable (`module:func`, invoked with zero args) or a bare module (imported for side effect).
- **Inputs / options:** Entry-point `name` must appear in config `plugins.enabled` and must not appear in `plugins.disabled`.
- **Outputs / side effects:** Calls `register_provider()`; failures logged as `Failed to load entry-point provider plugin %r: %s` or `Entry-point provider plugin %r raised on invocation: %s`.
- **Config / env:** `plugins.enabled` (list), `plugins.disabled` (list). When `plugins.enabled` is falsy the whole scan returns immediately — a pip package is never imported just because it is installed.
- **Edge cases / guards:** Python 3.10+ uses `entry_points().select(group=...)`; older uses the dict-like `.get(group, [])`. Callables requiring arguments are skipped (they belong to `PluginManager`).
- **Rebuild notes:** Entry-point scan + allow-list gate + zero-arg signature check. A better version would show pip-provided providers in `hermes doctor` with their distribution name and version.

### Provider identity resolution (`hermes_cli/providers.py`)  `id: providers.identity-resolution`
- **Surface:** Core
- **Where:** `hermes_cli/providers.py` — used by `--provider`, `/model`, model-switch, setup, doctor.
- **What it does:** Merges three data sources into one `ProviderDef` per provider: the models.dev catalog (109+ providers with base URLs, env vars, display names, model metadata), the Hermes overlay table (transport, auth pattern, aggregator flag, extra env vars), and the user's `providers:` / `custom_providers:` config.
- **How it works:** `HermesOverlay` frozen dataclass (`:34-44`) fields: `transport` (`openai_chat`|`anthropic_messages`|`codex_responses`, default `openai_chat`), `is_aggregator: bool = False`, `auth_type` (`api_key`|`oauth_device_code`|`oauth_external`|`external_process`, default `api_key`), `extra_env_vars: tuple`, `base_url_override: str`, `base_url_env_var: str`, `keyless: bool = False`. `HERMES_OVERLAYS` (`:47-266`) holds 38 entries — `moa`, `openrouter`, `nous`, `openai-codex`, `openai-api`, `xai-oauth`, `qwen-oauth`, `lmstudio`, `copilot-acp`, `github-copilot`, `anthropic`, `zai`, `kimi-for-coding`, `stepfun`, `minimax`, `minimax-oauth`, `minimax-cn`, `deepseek`, `alibaba`, `alibaba-coding-plan`, `vercel`, `opencode`, `opencode-go`, `opencode-free`, `kilo`, `huggingface`, `novita`, `xai`, `nvidia`, `xiaomi`, `tencent-tokenhub`, `tencent-tokenplan`, `arcee`, `gmi`, `fireworks`, `actual`, `upstage`, `nebius-token-factory`, `ollama-cloud`, `azure-foundry`, `bedrock`, `vertex`. `get_provider(name, *, allow_network=True)` (`:488-592`) resolves: models.dev + overlay merge → overlay-only ("hermes" source) → plugin profile fallback (only when the profile has a non-empty `base_url`, so the endpoint-less `custom` placeholder is left to `resolve_provider_full`) → `None`. `resolve_provider_full(name, user_providers, custom_providers)` (`:942-1042`) adds step **0** (raw name against user `providers:` — a configured `providers.openai` beats the alias `openai → openrouter`), step **0.5** (exact Hermes provider IDs win over LOSSY alias collapsing — only when multiple auth-registry providers normalize to the same canonical name, e.g. `kimi-coding-cn` vs `kimi-coding`), then built-in, user config, `custom_providers`, and a direct models.dev lookup.
- **Inputs / options:** `ALIASES` (`:292-436`) — the human-friendly/legacy name map, 88 entries: `openai→openrouter`; `glm|z-ai|z.ai|zhipu→zai`; `x-ai|x.ai|grok→xai`; `grok-oauth|xai-oauth|x-ai-oauth|xai-grok-oauth→xai-oauth`; `nim|nvidia-nim|build-nvidia|nemotron→nvidia`; `kimi|kimi-coding|kimi-coding-cn|moonshot→kimi-for-coding`; `step|stepfun-coding-plan→stepfun`; `minimax-china|minimax_cn→minimax-cn`; `claude|claude-code→anthropic`; `copilot|github→github-copilot`; `github-copilot-acp→copilot-acp`; `ai-gateway|aigateway|vercel-ai-gateway→vercel`; `opencode-zen|zen→opencode`; `go|opencode-go-sub→opencode-go`; `free|opencode_free→opencode-free`; `kilocode|kilo-code|kilo-gateway→kilo`; `deep-seek→deepseek`; `dashscope|aliyun|qwen|alibaba-cloud→alibaba`; `alibaba_coding|alibaba-coding|alibaba_coding_plan→alibaba-coding-plan`; `hf|hugging-face|huggingface-hub→huggingface`; `novita-ai|novitaai→novita`; `mimo|xiaomi-mimo→xiaomi`; `tencent|tokenhub|tencent-cloud|tencentmaas→tencent-tokenhub`; `tokenplan|tencent-lkeap→tencent-tokenplan`; `aws|aws-bedrock|amazon-bedrock|amazon→bedrock`; `arcee-ai|arceeai→arcee`; `gmi-cloud|gmicloud→gmi`; `fireworks-ai|fw→fireworks`; `solar→upstage`; `actual-computer|actualcomputer|aci→actual`; `nebius|nebius-tokenfactory|nebius-tf|token-factory|tokenfactory→nebius-token-factory`; `lmstudio|lm-studio|lm_studio→lmstudio`; `ollama→custom`; `vllm|llamacpp|llama.cpp|llama-cpp→local`.
- **Outputs / side effects:** `ProviderDef(id, name, transport, api_key_env_vars, base_url, base_url_env_var, is_aggregator, auth_type, doc, source)`; `source` ∈ `models.dev` | `hermes` | `plugin-profile` | `user-config` | `hermes-auth-registry`.
- **Config / env:** config.yaml `providers:` (dict keyed by name, fields `name`, `api`/`url`/`base_url`, `key_env`/`api_key_env`, `transport`) and `custom_providers:` (list of `{name, base_url|url|api, key_env, provider_key}`).
- **Edge cases / guards:** `custom_provider_slug()` (`:831-841`) builds a stable `custom:<key-or-name>` identity so a renamed display name does not break the identity; `custom_provider_aliases()` (`:844-860`) returns every current+legacy accepted spelling; a corrupt bare `"custom"` provider self-heals to the first valid `custom_providers` entry (GH #17478). `_LABEL_OVERRIDES` (`:444-464`) supplies 20 display labels: `moa`→"Mixture of Agents", `nous`→"Nous Portal", `openai-codex`→"ChatGPT or Codex Subscription", `copilot-acp`→"GitHub Copilot ACP", `stepfun`→"StepFun Step Plan", `xiaomi`→"Xiaomi MiMo", `gmi`→"GMI Cloud", `upstage`→"Upstage Solar", `actual`→"Actual Computer", `tencent-tokenhub`→"Tencent TokenHub", `nebius-token-factory`→"Nebius Token Factory", `tencent-tokenplan`→"Tencent TokenPlan", `lmstudio`→"LM Studio", `local`→"Local endpoint", `bedrock`→"AWS Bedrock", `vertex`→"Google Vertex AI", `ollama-cloud`→"Ollama Cloud", `xai-oauth`→"xAI Grok OAuth (SuperGrok / Premium+)", `opencode-free`→"OpenCode Free".
- **Rebuild notes:** Three-layer merge (catalog / overlay / user) with alias normalisation and a stable slug for user endpoints. A better version would publish `ProviderDef` as JSON on `/api/providers` so every surface (desktop, TUI, web) reads the same resolved identity instead of re-deriving it.

### Host-mandated API mode  `id: providers.host-mandated-api-mode`
- **Surface:** Core
- **Where:** `hermes_cli/providers.py:678-732` (`host_mandated_api_mode`), `:754-787` (`determine_api_mode`), `:735-751` (`nous_api_mode`), `:657-675` (`is_official_openai_host`).
- **What it does:** Forces the wire protocol for endpoints that only accept one protocol, overriding any stale `api_mode` carried by a session after a `/model` switch.
- **How it works:** Hostname-parsed matching (never substring — #32243 spoofing fix, delegated to `utils.base_url_host_matches` / `base_url_hostname`). Rules in order: `api.kimi.com` + path contains `/coding` → `anthropic_messages`; hostname `api.anthropic.com` **or** URL ends with `/anthropic` → `anthropic_messages`; official OpenAI host family (`api.openai.com` plus `<region>.api.openai.com` such as `us.` / `eu.`) → `codex_responses`; `api.meta.ai` → `codex_responses` (Responses is the only wire that achieves prompt-cache hits: measured 0% on chat/completions vs 93–99% on `/responses` with `prompt_cache_retention`); `api.router.com` → `codex_responses`; hostname starts `bedrock-runtime.` and host matches `amazonaws.com` → `bedrock_converse`; otherwise `None`. `determine_api_mode(provider, base_url, model)` order: host mandate → Nous dual-wire (`nous`/`nous-portal`/`nousresearch`: model id starting `anthropic/` → `anthropic_messages`, else `chat_completions`) → `TRANSPORT_TO_API_MODE[pdef.transport]` → explicit `bedrock` check → default `chat_completions`.
- **Inputs / options:** `provider`, `base_url`, `model`.
- **Outputs / side effects:** Returns one of `chat_completions` | `anthropic_messages` | `codex_responses` | `bedrock_converse`.
- **Config / env:** `model.api_mode` in config.yaml is honoured only for endpoints with no host mandate.
- **Edge cases / guards:** Lookalike hosts (`api.openai.com.attacker.test`) and path-segment spoofs (`proxy.test/api.openai.com/v1`) are rejected. `TRANSPORT_TO_API_MODE` (`:469-474`) maps `openai_chat→chat_completions`, `anthropic_messages→anthropic_messages`, `codex_responses→codex_responses`, `bedrock_converse→bedrock_converse`.
- **Rebuild notes:** A hostname allow-table returning a protocol enum. A better version would probe once and cache the negotiated protocol per (host, model) instead of hard-coding vendor hosts.

### Aggregator vs flat-namespace reseller classification  `id: providers.aggregator-classification`
- **Surface:** Core
- **Where:** `hermes_cli/providers.py:613-654` (`is_aggregator`, `is_routing_aggregator`, `_FLAT_NAMESPACE_RESELLERS`).
- **What it does:** Distinguishes true routing aggregators (OpenRouter, `custom:*` proxies — selecting one of their models re-routes the call to another vendor's endpoint) from flat-namespace resellers (`opencode`, `opencode-go` — bare model IDs, but every model is first-party under their own subscription).
- **How it works:** `is_aggregator(provider)` returns True for anything whose normalized id starts `custom:` or whose `ProviderDef.is_aggregator` is set. `_FLAT_NAMESPACE_RESELLERS = frozenset({"opencode-go", "opencode"})`. `is_routing_aggregator()` returns False for those two and otherwise defers to `is_aggregator`.
- **Inputs / options:** provider id or alias.
- **Outputs / side effects:** Consumed by `model_switch.py` step (d) (flat-catalog search) and by the `/model` picker dedup in `build_models_payload` — a reseller's first-party `minimax-m3` must not be stripped just because a user proxy also serves a same-named model.
- **Config / env:** n/a.
- **Edge cases / guards:** Aggregators marked in `HERMES_OVERLAYS`: `openrouter`, `vercel`, `opencode`, `opencode-go`, `opencode-free`, `kilo`, `huggingface`, `novita`.
- **Rebuild notes:** Two booleans on the provider record. A better version would derive "routing" from whether the catalog's model ids carry a `vendor/` prefix, rather than a hard-coded set.

### Canonical reasoning-effort ladder & clamp  `id: providers.reasoning-effort-ladder`
- **Surface:** Core
- **Where:** `agent/reasoning_effort.py` — imported by ~12 provider profiles and both transports.
- **What it does:** One vocabulary and one clamping policy so an internal effort level never leaks to a wire that rejects it (HTTP 400) and a stronger request never resolves weaker than a weaker one.
- **How it works:** `EFFORT_LADDER = ("none","minimal","low","medium","high","xhigh","max","ultra")` (`:50-52`). `clamp_effort(effort, supported, overrides=None)` (`:162-215`): pass through when unsupported-set is unknown/empty or the request is already supported; consult `overrides` first (declared vendor translations); pass bespoke non-ladder levels through unchanged; otherwise take the **nearest weaker** supported level, never escalating, and when nothing weaker exists take the weakest supported level. `"none"` is never a degradation target (clamping `minimal→none` would silently disable thinking). `requested_effort(reasoning_config)` (`:218-230`) returns the explicit effort or `None` when absent/disabled.
- **Inputs / options:** Declared wire vocabularies (all constants, verbatim): `OPENAI_COMPAT_WIRE_EFFORTS = (none, minimal, low, medium, high, xhigh, max)`; `CODEX_GPT56_EFFORTS = (none, low, medium, high, xhigh, max)`; `CODEX_LEGACY_EFFORTS = (none, low, medium, high, xhigh)`; `CODEX_RESPONSES_EFFORTS` (alias of GPT56); `XAI_GROK46_EFFORTS = (low, medium, high, xhigh)`; `XAI_LEGACY_EFFORTS = (low, medium, high)`; `ACTUAL_RELAY_EFFORTS = (none, low, medium, high, max)`; `KIMI_K3_EFFORTS = (low, high, max)` with `KIMI_K3_OVERRIDES = {medium: high, xhigh: max}`; `KIMI_K2_EFFORTS = (low, medium, high)`; `OX_ALPHA_EFFORTS = (low, high, max)` with `OX_ALPHA_OVERRIDES = {xhigh: max}`; `TOKENHUB_EFFORTS = (low, medium, high)`; `NEBIUS_EFFORTS = (low, medium, high)`; `GLM52_EFFORTS = (high, max)` with `GLM52_OVERRIDES = {xhigh: max}`; `GLM53_EFFORTS = (low, medium, high, max)` with `GLM53_OVERRIDES = {xhigh: max}`; `DEEPSEEK_V4_EFFORTS = (low, medium, high, max)` with `DEEPSEEK_V4_OVERRIDES = {xhigh: max}`; `OLLAMA_CLOUD_EFFORTS = (none, low, medium, high, max)` with `OLLAMA_CLOUD_OVERRIDES = {xhigh: max}`; `META_AI_EFFORTS = (minimal, low, medium, high, xhigh)`; `SOLAR_EFFORTS = (low, medium, high)`. Helper selectors: `codex_supported_efforts(model)` — `gpt-5.6` in name → GPT56 set, else legacy; `kimi_supported_efforts(model)` — regex `(?:^|[^a-z0-9])k3(?:[^a-z0-9]|$)` on the last path segment → K3 set, else K2 set.
- **Outputs / side effects:** A string effort, or the input unchanged.
- **Config / env:** `agent.reasoning_effort` / `/reasoning <level>` produce the `reasoning_config` dict this consumes. `hermes_constants.VALID_REASONING_EFFORTS` is the internal ladder minus `none`.
- **Edge cases / guards:** `ultra` is Hermes-internal (the Codex product tier) and is accepted by NO wire — every declared set stops at `max`, so `ultra` always clamps down.
- **Rebuild notes:** An ordered tuple + a nearest-weaker search + per-wire declared sets. A better version would fetch supported levels from each provider's catalog (as Ramp Router and OpenRouter already publish) and drop the hand-maintained constants entirely.

---

## 2. The 48 registered provider profiles

All 48 are listed by `providers.list_providers()` after discovery; they ship from 40 bundled plugin
directories (eight directories register more than one profile: `alibaba` ×4, `alibaba-coding-plan` ×2,
`commandcode` ×2, `kimi-coding` ×2, `minimax` ×3, `opencode-zen` ×2). Each entry below gives the exact
values a reimplementation needs. Common to all: selecting one writes `model.provider` (and
`model.name`, `model.base_url`, `model.api_mode`) into `~/.hermes/config.yaml`; the picker is
`hermes model` / `/model`; API keys are stored per `hermes auth add <provider>`.

### Actual Computer  `id: providers.actual`
- **Surface:** Provider
- **Where:** `hermes model` → provider list row "Actual Computer"; `model.provider: actual`; plugin `plugins/model-providers/actual/`.
- **What it does:** Routes inference to Actual Computer, either hosted at `api.actual.inc` or to a local offline Actual client.
- **How it works:** `plugins/model-providers/actual/__init__.py:76-89`. `ActualProfile(ProviderProfile)` with `api_mode="codex_responses"` (Responses wire). `fetch_models()` (`:45-73`) normalises the base URL through `_normalize_actual_base_url()` (`:20-34`): `ACTUAL_BASE_URL` env wins over the caller's base_url which wins over `self.base_url`; bare `https://api.actual.inc` or a bare loopback host (`localhost`, `127.0.0.1`, `::1`, `0.0.0.0`) gets `/v1` appended. Then GET `<base>/models` with `Authorization: Bearer`, `Accept: application/json`, `User-Agent: hermes-cli/<ver>` through `open_credentialed_url`. Constants: `DEFAULT_ACTUAL_BASE_URL = "https://api.actual.inc/v1"`, `DEFAULT_ACTUAL_LOCAL_BASE_URL = "http://127.0.0.1:8080/v1"` (`:16-17`).
- **Inputs / options:** `name="actual"`; aliases `actual-computer`, `actualcomputer`, `aci`; `display_name="Actual Computer"`; `description="Actual Computer - hosted inference via api.actual.inc, or local offline inference via ACTUAL_BASE_URL"`; `signup_url="https://actual.inc"`; `auth_type="api_key"`; `base_url="https://api.actual.inc/v1"`; no `fallback_models`; no `default_aux_model`.
- **Outputs / side effects:** One HTTP GET per catalog refresh; result cached by the picker.
- **Config / env:** `ACTUAL_API_KEY`, `ACTUAL_BASE_URL`. Overlay `actual` (`hermes_cli/providers.py:220-225`): `transport="codex_responses"`, `base_url_override="https://api.actual.inc/v1"`, `base_url_env_var="ACTUAL_BASE_URL"`. `ACTUAL_RELAY_EFFORTS = (none, low, medium, high, max)` governs its reasoning clamp.
- **Edge cases / guards:** Local inference is only exposed by the Actual client in offline mode, so the user must opt in by setting `ACTUAL_BASE_URL`. Malformed URLs fall through to the raw string.
- **Rebuild notes:** OpenAI-Responses client + base-URL normaliser. A better version would auto-detect a running local Actual client on `127.0.0.1:8080` and offer it in the picker.

### Vercel AI Gateway  `id: providers.ai-gateway`
- **Surface:** Provider
- **Where:** `model.provider: ai-gateway` (or alias `vercel`); plugin `plugins/model-providers/ai-gateway/`.
- **What it does:** Routes to Vercel's AI Gateway, which fronts many upstream backends, with Hermes attribution headers and reasoning passthrough.
- **How it works:** `VercelAIGatewayProfile.build_api_kwargs_extras()` (`ai-gateway/__init__.py:16-28`): when `supports_reasoning` and `reasoning_config is not None`, emits `extra_body["reasoning"] = dict(reasoning_config)`; when `supports_reasoning` and no config, emits `extra_body["reasoning"] = {"enabled": True, "effort": "medium"}`; returns `(extra_body, {})`.
- **Inputs / options:** `name="ai-gateway"`; aliases `vercel`, `vercel-ai-gateway`, `ai_gateway`, `aigateway`; `api_mode="chat_completions"`; `auth_type="api_key"`; `base_url="https://ai-gateway.vercel.sh/v1"`; `default_aux_model="google/gemini-3-flash"`; `default_headers={"HTTP-Referer": "https://hermes-agent.nousresearch.com", "X-Title": "Hermes Agent"}`.
- **Outputs / side effects:** Attribution headers on every request.
- **Config / env:** `AI_GATEWAY_API_KEY`. Overlay `vercel`: `is_aggregator=True`. OAuth-ish key provisioning helper: `hermes_cli/vercel_auth.py`.
- **Edge cases / guards:** Reasoning is always sent when the model supports it — there is no omit path, so a gateway backend that rejects `reasoning` will 400.
- **Rebuild notes:** OpenAI client + two headers + reasoning passthrough. A better version would read the gateway's per-model capability list instead of defaulting everything to `medium`.

### Alibaba Cloud DashScope (international)  `id: providers.alibaba`
- **Surface:** Provider
- **Where:** `model.provider: alibaba`; plugin `plugins/model-providers/alibaba/__init__.py:22-27`.
- **What it does:** Qwen and other DashScope models over the OpenAI-compatible DashScope endpoint (international region).
- **How it works:** Plain `ProviderProfile`, no hooks. Name matches the models.dev catalog key exactly so model metadata lines up (issue #73265).
- **Inputs / options:** aliases `dashscope`, `alibaba-cloud`, `qwen-dashscope`; `api_mode="chat_completions"`; `auth_type="api_key"`; `base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"`; no aux model; no fallback models.
- **Outputs / side effects:** n/a beyond standard chat completions.
- **Config / env:** `DASHSCOPE_API_KEY`; overlay `alibaba` sets `base_url_env_var="DASHSCOPE_BASE_URL"`.
- **Edge cases / guards:** Shares its API key with the CN and coding-plan variants.
- **Rebuild notes:** Bare OpenAI-compatible profile.

### Alibaba Cloud DashScope (China)  `id: providers.alibaba-cn`
- **Surface:** Provider
- **Where:** `model.provider: alibaba-cn`; `plugins/model-providers/alibaba/__init__.py:29-36`.
- **What it does:** Same DashScope service on the mainland-China endpoint.
- **How it works:** Plain profile; separate registration so `model.provider: alibaba-cn` resolves at runtime.
- **Inputs / options:** aliases `dashscope-cn`, `alibaba-cloud-cn`; `display_name="Alibaba Cloud DashScope (China)"`; `description="Alibaba Cloud DashScope, mainland-China endpoint"`; `base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"`.
- **Outputs / side effects:** n/a.
- **Config / env:** `DASHSCOPE_API_KEY`, `DASHSCOPE_CN_BASE_URL`.
- **Edge cases / guards:** Region split shares the key with `alibaba`.
- **Rebuild notes:** Duplicate profile with a different base URL.

### Alibaba Cloud (Coding Plan)  `id: providers.alibaba-coding-plan`
- **Surface:** Provider
- **Where:** `model.provider: alibaba-coding-plan`; `plugins/model-providers/alibaba-coding-plan/__init__.py:17-26`.
- **What it does:** Dedicated coding tier of Alibaba Model Studio with its own API-key tier and endpoint.
- **How it works:** Plain profile; separate from `alibaba` because it hits `coding-intl.dashscope.aliyuncs.com` with a dedicated key tier.
- **Inputs / options:** aliases `alibaba_coding`, `alibaba-coding`, `dashscope-coding`; `display_name="Alibaba Cloud (Coding Plan)"`; `description="Alibaba Cloud Coding Plan (Dedicated coding tier)"`; `signup_url="https://help.aliyun.com/zh/model-studio/"`; `base_url="https://coding-intl.dashscope.aliyuncs.com/v1"`; `auth_type="api_key"`.
- **Outputs / side effects:** n/a.
- **Config / env:** `ALIBABA_CODING_PLAN_API_KEY`, `DASHSCOPE_API_KEY`, `ALIBABA_CODING_PLAN_BASE_URL`; overlay `alibaba-coding-plan` sets `base_url_env_var="ALIBABA_CODING_PLAN_BASE_URL"`.
- **Edge cases / guards:** Falls back to `DASHSCOPE_API_KEY` when the dedicated key is unset.
- **Rebuild notes:** Same as `alibaba` with a different host + key precedence.

### Alibaba Cloud (Coding Plan, China)  `id: providers.alibaba-coding-plan-cn`
- **Surface:** Provider
- **Where:** `model.provider: alibaba-coding-plan-cn`; `plugins/model-providers/alibaba-coding-plan/__init__.py:28-37`.
- **What it does:** Mainland-China endpoint of the coding-plan tier.
- **How it works:** Plain profile.
- **Inputs / options:** aliases `alibaba-coding-cn`, `dashscope-coding-cn`; `display_name="Alibaba Cloud (Coding Plan, China)"`; `description="Alibaba Cloud Coding Plan, mainland-China endpoint"`; `base_url="https://coding.dashscope.aliyuncs.com/v1"`.
- **Outputs / side effects:** n/a.
- **Config / env:** `ALIBABA_CODING_PLAN_API_KEY`, `DASHSCOPE_API_KEY`, `ALIBABA_CODING_PLAN_CN_BASE_URL`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Region twin.

### Alibaba Cloud (Token Plan)  `id: providers.alibaba-token-plan`
- **Surface:** Provider
- **Where:** `model.provider: alibaba-token-plan`; `plugins/model-providers/alibaba/__init__.py:41-50`.
- **What it does:** Flat-token tier of Alibaba Model Studio (same vendor/protocol, own key and endpoints).
- **How it works:** Registered from the `alibaba` module rather than a new directory — one module per vendor.
- **Inputs / options:** alias `dashscope-token-plan`; `display_name="Alibaba Cloud (Token Plan)"`; `description="Alibaba Cloud Model Studio Token Plan (flat-token tier)"`; `signup_url="https://help.aliyun.com/zh/model-studio/"`; `base_url="https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"`; `auth_type="api_key"`.
- **Outputs / side effects:** n/a.
- **Config / env:** `ALIBABA_TOKEN_PLAN_API_KEY`, `ALIBABA_TOKEN_PLAN_BASE_URL`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Bare profile.

### Alibaba Cloud (Token Plan, China)  `id: providers.alibaba-token-plan-cn`
- **Surface:** Provider
- **Where:** `model.provider: alibaba-token-plan-cn`; `plugins/model-providers/alibaba/__init__.py:52-61`.
- **What it does:** Beijing endpoint of the flat-token tier.
- **How it works:** Plain profile.
- **Inputs / options:** alias `dashscope-token-plan-cn`; `display_name="Alibaba Cloud (Token Plan, China)"`; `description="Alibaba Cloud Model Studio Token Plan, mainland-China endpoint"`; `base_url="https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"`.
- **Outputs / side effects:** n/a.
- **Config / env:** `ALIBABA_TOKEN_PLAN_API_KEY`, `ALIBABA_TOKEN_PLAN_CN_BASE_URL`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Region twin.

### Anthropic (Claude)  `id: providers.anthropic`
- **Surface:** Provider
- **Where:** `model.provider: anthropic`; plugin `plugins/model-providers/anthropic/`.
- **What it does:** Native Anthropic Messages API — Claude models via API key, an `ANTHROPIC_TOKEN`, or a Claude Code OAuth token.
- **How it works:** `AnthropicProfile.fetch_models()` (`anthropic/__init__.py:17-41`) is overridden because Anthropic uses `x-api-key`, not Bearer: GET `https://api.anthropic.com/v1/models` with headers `x-api-key: <key>`, `anthropic-version: 2023-06-01`, `Accept: application/json` through `open_credentialed_url`; returns `[m["id"] for m in data["data"]]`; returns `None` when no key. The runtime wire lives in `agent/anthropic_adapter.py` + `agent/anthropic_message_convert.py` + `agent/anthropic_endpoints.py` + `agent/anthropic_credentials.py` (documented separately below).
- **Inputs / options:** aliases `claude`, `claude-oauth`, `claude-code`; `api_mode="anthropic_messages"`; `auth_type="api_key"`; `base_url="https://api.anthropic.com"`; `default_aux_model="claude-haiku-4-5-20251001"`.
- **Outputs / side effects:** One authenticated catalog GET.
- **Config / env:** `ANTHROPIC_API_KEY`, `ANTHROPIC_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN`; overlay `anthropic` adds `ANTHROPIC_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN` as extra env vars with `transport="anthropic_messages"`.
- **Edge cases / guards:** `host_mandated_api_mode` forces `anthropic_messages` for `api.anthropic.com` and for any base URL ending `/anthropic`.
- **Rebuild notes:** Messages-API client with `x-api-key`+`anthropic-version` headers. A better version would surface the OAuth (Claude Pro/Max) path as a first-class picker row rather than an env var.

### Arcee AI  `id: providers.arcee`
- **Surface:** Provider
- **Where:** `model.provider: arcee`; plugin `plugins/model-providers/arcee/` (13 lines — the smallest profile).
- **What it does:** Arcee AI's OpenAI-compatible inference endpoint.
- **How it works:** Bare `ProviderProfile`, default `fetch_models`.
- **Inputs / options:** aliases `arcee-ai`, `arceeai`; `api_mode="chat_completions"`; `auth_type="api_key"`; `base_url="https://api.arcee.ai/api/v1"`; no display name/description/signup URL; no aux/fallback models.
- **Outputs / side effects:** n/a.
- **Config / env:** `ARCEEAI_API_KEY`; overlay `arcee` sets `base_url_override="https://api.arcee.ai/api/v1"`, `base_url_env_var="ARCEE_BASE_URL"`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Five-field profile — the minimum a new provider needs.

### Azure Foundry (Microsoft Foundry)  `id: providers.azure-foundry`
- **Surface:** Provider
- **Where:** `model.provider: azure-foundry`; plugin `plugins/model-providers/azure-foundry/`.
- **What it does:** Microsoft Foundry's OpenAI-compatible endpoint; because endpoints are per-resource, the user supplies the base URL during setup.
- **How it works:** `base_url=""` — the profile ships no default; the setup wizard prompts for it and stores `model.base_url`. Auth can also be Entra ID via `agent/azure_identity_adapter.py`.
- **Inputs / options:** aliases `azure`, `azure-ai-foundry`, `azure-ai`; `display_name="Azure Foundry"`; `description="Microsoft Foundry - OpenAI-compatible endpoint (user-supplied base URL)"`; `signup_url="https://ai.azure.com/"`; `auth_type="api_key"`.
- **Outputs / side effects:** Live `/models` fetch only once a base URL is configured.
- **Config / env:** `AZURE_FOUNDRY_API_KEY`, `AZURE_FOUNDRY_BASE_URL`; overlay `azure-foundry` sets `transport="openai_chat"` as a *default* that config.yaml `model.api_mode` overrides — Foundry supports both OpenAI-style and Anthropic-style endpoints.
- **Edge cases / guards:** Without a base URL, `get_provider("azure-foundry")` still resolves via the overlay but `fetch_models` returns `None`.
- **Rebuild notes:** Profile with an empty base URL + wizard prompt. A better version would auto-discover the deployment list from the Azure control plane.

### AWS Bedrock  `id: providers.bedrock`
- **Surface:** Provider
- **Where:** `model.provider: bedrock`; plugin `plugins/model-providers/bedrock/`.
- **What it does:** Runs models through Amazon Bedrock's Converse API using AWS SDK credentials rather than an API key.
- **How it works:** `BedrockProfile.fetch_models()` (`bedrock/__init__.py:10-18`) always returns `None` — Bedrock has no REST `/v1/models`; listing requires the AWS SDK, which `agent/bedrock_adapter.py` + the `bedrock.discovery.*` config own.
- **Inputs / options:** aliases `aws`, `aws-bedrock`, `amazon-bedrock`, `amazon`; `api_mode="bedrock_converse"`; `auth_type="aws_sdk"`; `env_vars=()` (AWS SDK credentials, not env vars); `base_url="https://bedrock-runtime.us-east-1.amazonaws.com"`.
- **Outputs / side effects:** Model listing done through boto3.
- **Config / env:** `bedrock.region` (default `""`), `bedrock.discovery.enabled` (`true`), `bedrock.discovery.provider_filter` (`[]`), `bedrock.discovery.refresh_interval` (`3600`), `bedrock.guardrail.guardrail_identifier` (`""`), `bedrock.guardrail.guardrail_version` (`""`), `bedrock.guardrail.stream_processing_mode` (`"async"`), `bedrock.guardrail.trace` (`"disabled"`). Standard AWS env (`AWS_PROFILE`, `AWS_REGION`, `AWS_ACCESS_KEY_ID`, …) via the SDK chain.
- **Edge cases / guards:** `host_mandated_api_mode` forces `bedrock_converse` for any `bedrock-runtime.*.amazonaws.com` host.
- **Rebuild notes:** SDK-backed provider whose profile deliberately returns `None` from `fetch_models`. A better version would surface Bedrock inference-profile ARNs (cross-region routing) in the picker.

### CommandCode  `id: providers.commandcode`
- **Surface:** Provider
- **Where:** `model.provider: commandcode`; plugin `plugins/model-providers/commandcode/__init__.py:101-125`.
- **What it does:** A unified API fronting 20+ models (DeepSeek, Qwen, Kimi, GLM, MiniMax, StepFun, Xiaomi MiMo, Gemini, GPT) over one base URL and one key, on the OpenAI chat-completions surface.
- **How it works:** `CommandCodeProfile.fetch_models()` calls the module-level `_fetch_commandcode_models()` (`:48-82`) — **no auth required**, the `/models` endpoint is public. It uses `_COMMANDCODE_MODELS_URL` unless the caller passed a base URL that differs from `_COMMANDCODE_BASE` (i.e. the user configured a proxy), in which case `<caller_base>/models`. Headers: `Accept: application/json`, `User-Agent: hermes-cli/<ver>`. Response shape `{"object": "list", "data": [{"id": ...}]}`.
- **Inputs / options:** alias `commandcode-chat`; `api_mode="chat_completions"`; `display_name="CommandCode"`; `description="CommandCode — 20+ models via OpenAI-compatible API"`; `signup_url="https://commandcode.ai/"`; `base_url="https://api.commandcode.ai/provider/v1"`; `models_url="https://api.commandcode.ai/provider/v1/models"`; `default_aux_model="deepseek/deepseek-v4-flash"`; `fallback_models=("deepseek/deepseek-v4-pro", "deepseek/deepseek-v4-flash", "Qwen/Qwen3.7-Max", "Qwen/Qwen3.6-Plus", "moonshotai/Kimi-K2.6", "zai-org/GLM-5.1", "MiniMaxAI/MiniMax-M2.7", "stepfun/Step-3.5-Flash", "xiaomi/mimo-v2.5-pro", "google/gemini-3.5-flash", "gpt-5.5")`.
- **Outputs / side effects:** Unauthenticated catalog GET (uses plain `urllib.request.urlopen`, not `open_credentialed_url`, because no credential is sent).
- **Config / env:** `COMMANDCODE_API_KEY`, `COMMANDCODE_BASE_URL`.
- **Edge cases / guards:** Both CommandCode profiles share `COMMANDCODE_API_KEY`; each carries its own base-URL override var so each renders its own card on the desktop Keys tab (rows are keyed by env var).
- **Rebuild notes:** OpenAI client + a public catalog endpoint. A better version would let the picker show which upstream vendor each model routes to.

### CommandCode (Anthropic)  `id: providers.commandcode-anthropic`
- **Surface:** Provider
- **Where:** `model.provider: commandcode-anthropic`; `plugins/model-providers/commandcode/__init__.py:155-171`.
- **What it does:** The same CommandCode account exposed on an Anthropic Messages-compatible endpoint, for Claude models.
- **How it works:** `CommandCodeAnthropicProfile.fetch_models()` (`:138-152`) fetches the same public catalog and filters to `m.startswith("claude-")`. Bearer auth (NOT Anthropic's `x-api-key`) — this only works because `agent/anthropic_adapter.py` recognises the `api.commandcode.ai` hostname as a Bearer-auth domain.
- **Inputs / options:** alias `commandcode-claude`; `api_mode="anthropic_messages"`; `display_name="CommandCode (Anthropic)"`; `description="CommandCode — Claude models via Anthropic Messages API"`; `signup_url="https://commandcode.ai/"`; `base_url="https://api.commandcode.ai/provider/v1"`; `models_url` same as above; `default_aux_model="claude-haiku-4-5-20251001"`; `fallback_models=("claude-sonnet-4-6", "claude-opus-4-7", "claude-haiku-4-5-20251001")`.
- **Outputs / side effects:** Filtered catalog list.
- **Config / env:** `COMMANDCODE_API_KEY`, `COMMANDCODE_ANTHROPIC_BASE_URL`.
- **Edge cases / guards:** If the adapter's Bearer-domain list loses `api.commandcode.ai`, every request 401s.
- **Rebuild notes:** Anthropic Messages client with Bearer auth + a catalog prefix filter.

### GitHub Copilot / GitHub Models  `id: providers.copilot`
- **Surface:** Provider
- **Where:** `model.provider: copilot` (label "GitHub Copilot"); plugin `plugins/model-providers/copilot/`.
- **What it does:** Uses a GitHub Copilot subscription as an inference provider, with editor-attribution headers and catalog-gated reasoning.
- **How it works:** Copilot uses **per-model api_mode routing**: GPT-5+/Codex models → `codex_responses`, Claude models → `anthropic_messages`, everything else → `chat_completions` (this profile). `CopilotProfile.build_api_kwargs_extras()` (`copilot/__init__.py:22-69`): when `supports_reasoning` and a model is given, calls `hermes_cli.models.github_model_reasoning_efforts(model)`; if the live Copilot catalog lists the requested effort it is honoured verbatim (gpt-5.5/gpt-5.4 DO support `xhigh`); otherwise `clamp_reasoning_effort_to_supported()` picks the nearest **weaker** supported level, then falls back to `"medium"` if present, else `supported_efforts[0]`; emits `extra_body["reasoning"] = {"effort": <effort>}`. With no `reasoning_config` but a reasoning-capable model it emits `{"effort": "medium"}`. Auth: `hermes_cli/copilot_auth.py` implements GitHub's OAuth device-code flow with **VS Code's GitHub App client id `Iv1.b507a08c87ecfe98`** (`:41`) — the previous opencode OAuth App id produced `gho_*` tokens that cannot be exchanged for Copilot API JWTs (404 on `/copilot_internal/v2/token`); VS Code's App id produces `ghu_*` tokens that support exchange, which is required for internal-only models (e.g. `claude-opus-4.6-1m`) and enterprise endpoints. Poll interval 5 s with a 3 s safety margin (`:50-51`).
- **Inputs / options:** aliases `github-copilot`, `github-models`, `github-model`, `github`; `api_mode="chat_completions"`; `auth_type="copilot"`; `base_url="https://api.githubcopilot.com"`. Supported token prefixes: `gho_` (OAuth, default via `copilot login`), `github_pat_` (fine-grained PAT, needs the Copilot Requests permission), `ghu_` (GitHub App token, via env var). **`ghp_` classic PATs are rejected** with the message `"Classic Personal Access Tokens (ghp_*) are not supported by the Copilot API. Use one of:\n  → `copilot login` or `hermes model` to authenticate via OAuth\n  → A fine-grained PAT (github_pat_*) with Copilot Requests permission\n  → `gh auth login` with the default device code flow (produces gho_* tokens)"` (`copilot_auth.py:63-70`). Credential search order (`:12-16`, `:47`): `COPILOT_GITHUB_TOKEN` → `GH_TOKEN` → `GITHUB_TOKEN` → `gh auth token` CLI fallback.
- **Outputs / side effects:** Every request carries `copilot_request_headers()` (`copilot_auth.py:717-736`): `Editor-Version: vscode/1.104.1`, `User-Agent: HermesAgent/1.0`, `Copilot-Integration-Id: vscode-chat`, `Openai-Intent: conversation-edits`, `x-initiator: agent|user` (per turn origin), plus `Copilot-Vision-Request: true` on vision calls. `hermes_cli/models.py:40` pins `COPILOT_EDITOR_VERSION = "vscode/1.104.1"`; the fallback header set at `models.py:4802-4807` drops `Copilot-Integration-Id`.
- **Config / env:** `COPILOT_GITHUB_TOKEN`, `GH_TOKEN`, `GITHUB_TOKEN`; overlay `github-copilot` adds `COPILOT_GITHUB_TOKEN`, `GH_TOKEN` as extra env vars.
- **Edge cases / guards:** Catalog filtering via `_copilot_catalog_item_is_text_model()` (`models.py:4810+`) drops items with `model_picker_enabled: false`, a `capabilities.type` other than `chat`, or unsupported `supported_endpoints`. `#74295` fixed a ladder inversion where `ultra` used to resolve weaker than an explicit `high`.
- **Rebuild notes:** Device-code OAuth + JWT exchange + editor headers + catalog-driven effort clamping. A better version would cache the exchanged Copilot JWT with its real expiry and refresh proactively rather than on 401.

### GitHub Copilot ACP  `id: providers.copilot-acp`
- **Surface:** Provider
- **Where:** `model.provider: copilot-acp` (label "GitHub Copilot ACP"); plugin `plugins/model-providers/copilot-acp/`; runtime in `agent/copilot_acp_client.py`; CLI `hermes acp`.
- **What it does:** Drives GitHub Copilot through an external **ACP (Agent Client Protocol) subprocess** rather than an HTTP API.
- **How it works:** `CopilotACPProfile.fetch_models()` returns `None` — model listing is done by the ACP subprocess. `api_mode="chat_completions"` is only the routing label; `run_agent.py` handles `copilot_acp` separately. `base_url="acp://copilot"` is an internal scheme, not a real URL.
- **Inputs / options:** aliases `github-copilot-acp`, `copilot-acp-agent`; `auth_type="external_process"`; `env_vars=()` (credentials managed by the subprocess).
- **Outputs / side effects:** Spawns and manages a subprocess; JSON-RPC over stdio.
- **Config / env:** overlay `copilot-acp`: `transport="codex_responses"`, `base_url_override="acp://copilot"`, `base_url_env_var="COPILOT_ACP_BASE_URL"`.
- **Edge cases / guards:** The overlay's transport (`codex_responses`) and the profile's `api_mode` (`chat_completions`) deliberately disagree — the ACP path is chosen before either is consulted.
- **Rebuild notes:** Subprocess bridge speaking ACP. A better version would expose the subprocess's model list to the picker instead of returning `None`.

### Custom / Ollama / local OpenAI-compatible endpoint  `id: providers.custom`
- **Surface:** Provider
- **Where:** `model.provider: custom` or `custom:<slug>`; aliases `ollama`, `local`, `vllm`, `llamacpp`; plugin `plugins/model-providers/custom/`.
- **What it does:** Covers any user-configured OpenAI-compatible endpoint — local Ollama, vLLM, llama.cpp, LM Studio, or a hosted reasoning endpoint like GLM-5.2 on Volcengine ARK.
- **How it works:** `CustomProfile.build_api_kwargs_extras()` (`custom/__init__.py:55-115`):
  1. `ollama_num_ctx` (when passed) → `extra_body["options"]["num_ctx"]`.
  2. Reasoning **disabled** (`effort == "none"` or `enabled is False`) → top-level `reasoning_effort: "none"` ALWAYS, plus `extra_body["think"] = False` **only** when `_looks_like_ollama_endpoint(base_url)` is true — Ollama's `/v1/chat/completions` silently ignores `extra_body.think` (only `/api/chat` honours it, ollama#14820) but respects top-level `reasoning_effort` (#25758); Mistral (`extra=forbid`) and Groq return HTTP 422 on unknown fields, so `think` stays URL-gated.
  3. Reasoning **enabled with an effort** → top-level `reasoning_effort = clamp_effort(effort, OPENAI_COMPAT_WIRE_EFFORTS)` — GLM/ARK, vLLM and SGLang all top out at `max`, so forwarding `ultra` verbatim is a guaranteed 400 (#89503).
  4. Reasoning enabled with **no** effort → emit nothing so the endpoint's own default applies. `think=True` is deliberately never emitted (Ollama-only flag; forcing it risks a 400 on GLM/vLLM).
  `_looks_like_ollama_endpoint()` (`:22-49`) matches only explicit Ollama signatures — port **11434**, hostname `ollama.com` or a `*.ollama.com` subdomain, or `ollama` as a dot-separated hostname label — **not** arbitrary localhost (llama.cpp / vLLM / LM Studio). A `ValueError` from a malformed port means "not Ollama". `fetch_models()` (`:117-127`) returns `None` when no base URL is configured, else delegates to the base implementation.
- **Inputs / options:** aliases `ollama`, `local`, `vllm`, `llamacpp`, `llama.cpp`, `llama-cpp`; `env_vars=()`; `base_url=""` (user-configured); `default_max_tokens=65536` — without it no `max_tokens` is sent and Ollama falls back to its internal `num_predict=128`, truncating responses after a few tokens (#39281). This is only a floor when `model.max_tokens` is unset.
- **Outputs / side effects:** Writes `custom_providers:` entries in config.yaml (name, base_url, key_env, provider_key) with a stable `custom:<slug>` identity.
- **Config / env:** No fixed key. `providers:` / `custom_providers:` in config.yaml; `model.base_url`; `model.max_tokens`; the Ollama context knob arrives as `ollama_num_ctx`.
- **Edge cases / guards:** `ALIASES` maps bare `ollama → custom` (local) while `ollama-cloud` stays a distinct provider; `vllm`/`llamacpp`/`llama.cpp`/`llama-cpp → local`. `get_provider()` skips plugin-profile resolution for `custom` because its `base_url` is empty, so `resolve_provider_full`'s custom-provider step is not preempted (keyed `custom:local-…` ids survive).
- **Rebuild notes:** Generic OpenAI client + endpoint sniffing for Ollama-only fields + a generous `max_tokens` floor. A better version would probe `/api/show` once and cache the model's real capability set rather than sniffing the URL.

### DeepInfra  `id: providers.deepinfra`
- **Surface:** Provider
- **Where:** `model.provider: deepinfra`; plugin `plugins/model-providers/deepinfra/`.
- **What it does:** 100+ open models on a pay-per-use OpenAI-compatible gateway (Step, GLM, Kimi, DeepSeek, MiniMax, Nemotron, Mistral, Qwen…), plus image-gen/TTS/STT/embedding surfaces wired through other subsystems.
- **How it works:** `_DeepInfraProfile.default_vision_model()` (`deepinfra/__init__.py:24-48`) discovers the vision default live rather than pinning one: it is **key-gated** (returns `None` when `DEEPINFRA_API_KEY` is empty, so a box without a key never pays the catalog round-trip), calls `hermes_cli.models._fetch_deepinfra_models_by_tag("chat")`, and returns the first item whose `metadata.tags` contains `"vision"`. Requiring the `chat` surface tag prevents an image-gen/edit model that merely carries a `vision` tag from being picked as a chat-completions vision backend.
- **Inputs / options:** aliases `deep-infra`, `deepinfra-ai`; `display_name="DeepInfra"`; `description="DeepInfra — 100+ open models, pay-per-use"`; `signup_url="https://deepinfra.com/dash/api_keys"`; `base_url="https://api.deepinfra.com/v1/openai"`; `auth_type="api_key"`; `default_max_tokens=None` (deliberate — the catalog spans models with different output limits, so DeepInfra applies its own documented per-model cap); `default_aux_model="deepseek-ai/DeepSeek-V4-Flash"` (the *only* hardcoded DeepInfra model, because aux resolution is synchronous); `fallback_models=()` deliberately empty — when the live fetch fails the picker shows no options rather than routing to a possibly-retired model.
- **Outputs / side effects:** Live catalog from `api.deepinfra.com/v1/openai/models?filter=true&sort_by=hermes` drives the chat picker, image-gen, TTS, STT and pricing.
- **Config / env:** `DEEPINFRA_API_KEY`, `DEEPINFRA_BASE_URL`; `tts.deepinfra.model` (default `""`), `stt.deepinfra.model` (default `""`).
- **Edge cases / guards:** `agent.secret_scope.get_secret("DEEPINFRA_API_KEY")` is the gate, so a scoped secret counts.
- **Rebuild notes:** OpenAI client + tag-filtered live catalog + provider-owned vision discovery hook. A better version would cache the tag query with an ETag and expose the tag filter to the picker UI.

### DeepSeek  `id: providers.deepseek`
- **Surface:** Provider
- **Where:** `model.provider: deepseek`; plugin `plugins/model-providers/deepseek/`.
- **What it does:** DeepSeek's native API with correct thinking-mode wiring so the V4 family does not trip the "reasoning_content must be passed back" HTTP 400.
- **How it works:** `_model_supports_thinking(model)` (`deepseek/__init__.py:32-46`): true when the id starts `deepseek-v` and NOT `deepseek-v3` — i.e. every V4+ generation. `DeepSeekProfile.build_api_kwargs_extras()` (`:52-93`): non-thinking models are a no-op; otherwise always emits `extra_body["thinking"] = {"type": "enabled"|"disabled"}` explicitly (the API's own default is enabled, but sending it explicitly avoids the `reasoning_content` echo trap on subsequent turns — issues #15700, #17212, #17825); when enabled and an effort was requested, `clamp_effort(effort, DEEPSEEK_V4_EFFORTS, DEEPSEEK_V4_OVERRIDES)` → top-level `reasoning_effort`; with no effort the field is omitted so DeepSeek's server default (currently `high`) applies.
- **Inputs / options:** alias `deepseek-chat`; `display_name="DeepSeek"`; `description="DeepSeek — native DeepSeek API"`; `signup_url="https://platform.deepseek.com/"`; `base_url="https://api.deepseek.com/v1"`; `default_aux_model="deepseek-v4-flash"`; `fallback_models=("deepseek-v4-pro", "deepseek-v4-flash")`.
- **Outputs / side effects:** Wire shape `{"reasoning_effort": "<low|medium|high|max>", "extra_body": {"thinking": {"type": "enabled"|"disabled"}}}`.
- **Config / env:** `DEEPSEEK_API_KEY`; overlay `deepseek` sets `base_url_env_var="DEEPSEEK_BASE_URL"`.
- **Edge cases / guards:** The legacy aliases `deepseek-chat` / `deepseek-reasoner` were retired 2026-07-24; Hermes remaps the retired ids in `hermes_cli/model_normalize.py`.
- **Rebuild notes:** Explicit `thinking` toggle + clamped `reasoning_effort`; never both silently defaulted. A better version would read DeepSeek's own capability endpoint instead of a name prefix test.

### Fireworks AI  `id: providers.fireworks`
- **Surface:** Provider
- **Where:** `model.provider: fireworks`; plugin `plugins/model-providers/fireworks/`.
- **What it does:** Fast production inference for open and proprietary models over an OpenAI-compatible chat-completions endpoint; models are addressed by their catalog ID (`accounts/fireworks/models/<name>`).
- **How it works:** Plain `ProviderProfile` with attribution headers applied through the generic `default_headers` path so they survive `switch_model` and credential rotation.
- **Inputs / options:** aliases `fireworks-ai`, `fw`; `display_name="Fireworks AI"`; `description="Fireworks AI — OpenAI-compatible direct model API"`; `signup_url="https://app.fireworks.ai/settings/users/api-keys"`; `base_url="https://api.fireworks.ai/inference/v1"`; `auth_type="api_key"`; `default_headers={"HTTP-Referer": "https://hermes-agent.nousresearch.com", "X-Title": "Hermes Agent", "User-Agent": "HermesAgent/<hermes_cli.__version__>"}`; `default_aux_model="accounts/fireworks/models/glm-5p2"`; `fallback_models=("accounts/fireworks/models/kimi-k2p6", "accounts/fireworks/models/glm-5p2", "accounts/fireworks/models/kimi-k2p7-code")`.
- **Outputs / side effects:** Attribution headers on every request.
- **Config / env:** `FIREWORKS_API_KEY`; overlay `fireworks` adds `FIREWORKS_API_KEY` and `base_url_override="https://api.fireworks.ai/inference/v1"`. `plugin.yaml` author: `Alex Jestin Taylor (@alex-fireworks) + Hermes Agent`.
- **Edge cases / guards:** Fireworks model ids use `p` for a decimal point (`glm-5p2` = GLM-5.2), which the Z.AI effort detector explicitly recognises.
- **Rebuild notes:** Bare profile + three headers.

### Google Gemini (AI Studio)  `id: providers.gemini`
- **Surface:** Provider
- **Where:** `model.provider: gemini`; plugin `plugins/model-providers/gemini/`; native client in `agent/gemini_native_adapter.py`.
- **What it does:** Google AI Studio Gemini models via API key, using a custom native client that bypasses the standard OpenAI transport, with reasoning translated to Gemini's `thinking_config`.
- **How it works:** `GeminiProfile.build_extra_body()` (`gemini/__init__.py:21-48`) imports `_build_gemini_thinking_config`, `_is_gemini_openai_compat_base_url` and `_snake_case_gemini_thinking_config` from `agent/transports/chat_completions.py`. It builds the raw thinking config from `(model, reasoning_config)`; when the profile is `gemini` **and** the base URL is the OpenAI-compat `/openai` subpath it emits `{"extra_body": {"google": {"thinking_config": <snake_cased>}}}`, otherwise it emits `{"thinking_config": <raw>}` (native shape). Empty config → `{}`.
- **Inputs / options:** aliases `google`, `google-gemini`, `google-ai-studio`; `api_mode="chat_completions"` (reported, but the native client is used); `auth_type="api_key"`; `base_url="https://generativelanguage.googleapis.com/v1beta"`; `default_aux_model="gemini-3.6-flash"`.
- **Outputs / side effects:** `thinking_config` in the request body; reasoning summaries surfaced through the native adapter.
- **Config / env:** `GOOGLE_API_KEY`, `GEMINI_API_KEY`; `tts.gemini.model` (`gemini-2.5-flash-preview-tts`), `tts.gemini.voice` (`Kore`), `tts.gemini.audio_tags` (`false`), `tts.gemini.persona_prompt_file` (`""`) are separate TTS keys.
- **Edge cases / guards:** The plugin docstring notes Cloud Code OAuth support in the manifest description ("Google Gemini (API key + Cloud Code OAuth)"), while the shipped profile carries only the API-key path.
- **Rebuild notes:** Native Gemini client + a `thinking_config` translation with two output shapes. A better version would use one shape and let the transport adapt.

### GMI Cloud  `id: providers.gmi`
- **Surface:** Provider
- **Where:** `model.provider: gmi` (label "GMI Cloud"); plugin `plugins/model-providers/gmi/`.
- **What it does:** GMI Cloud's multi-model direct API, addressed with slash-form model IDs.
- **How it works:** Plain profile; the attribution `User-Agent` is picked up by the generic `profile.default_headers` fallback in `run_agent.py` and `agent/auxiliary_client.py` at client construction time.
- **Inputs / options:** aliases `gmi-cloud`, `gmicloud`; `display_name="GMI Cloud"`; `description="GMI Cloud — multi-model direct API (slash-form model IDs)"`; `signup_url="https://www.gmicloud.ai/"`; `base_url="https://api.gmi-serving.com/v1"`; `auth_type="api_key"`; `default_headers={"User-Agent": "HermesAgent/<version>"}`; `default_aux_model="google/gemini-3.1-flash-lite-preview"`; `fallback_models=("zai-org/GLM-5.1-FP8", "deepseek-ai/DeepSeek-V3.2", "moonshotai/Kimi-K2.5", "google/gemini-3.1-flash-lite-preview", "anthropic/claude-sonnet-5", "anthropic/claude-sonnet-4.6", "openai/gpt-5.4")`.
- **Outputs / side effects:** Identifies Hermes traffic to GMI.
- **Config / env:** `GMI_API_KEY`, `GMI_BASE_URL`; overlay `gmi` adds `GMI_API_KEY` and `base_url_env_var="GMI_BASE_URL"`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Bare profile + UA header.

### HuggingFace Inference  `id: providers.huggingface`
- **Surface:** Provider
- **Where:** `model.provider: huggingface`; plugin `plugins/model-providers/huggingface/`.
- **What it does:** Routes to HuggingFace's Inference Providers router (an aggregator over many hosted backends).
- **How it works:** Plain profile against the router base URL.
- **Inputs / options:** aliases `hf`, `hugging-face`, `huggingface-hub`; `display_name="HuggingFace"`; `description="HuggingFace Inference API"`; `signup_url="https://huggingface.co/settings/tokens"`; `base_url="https://router.huggingface.co/v1"`; `fallback_models=("Qwen/Qwen3.5-72B-Instruct", "deepseek-ai/DeepSeek-V3.2")`.
- **Outputs / side effects:** n/a.
- **Config / env:** `HF_TOKEN`; overlay `huggingface`: `is_aggregator=True`, `base_url_env_var="HF_BASE_URL"`.
- **Edge cases / guards:** Marked an aggregator, so picker dedup treats its rows as routing rows.
- **Rebuild notes:** Bare profile with a Bearer `HF_TOKEN`.

### Kilo Code  `id: providers.kilocode`
- **Surface:** Provider
- **Where:** `model.provider: kilocode`; plugin `plugins/model-providers/kilocode/`.
- **What it does:** Routes through the Kilo Code gateway.
- **How it works:** Plain profile.
- **Inputs / options:** aliases `kilo-code`, `kilo`, `kilo-gateway`; `base_url="https://api.kilo.ai/api/gateway"`; `default_aux_model="google/gemini-3.6-flash"`.
- **Outputs / side effects:** n/a.
- **Config / env:** `KILOCODE_API_KEY`; overlay `kilo`: `is_aggregator=True`, `base_url_env_var="KILOCODE_BASE_URL"`. `ALIASES` collapses `kilocode|kilo-code|kilo-gateway → kilo`.
- **Edge cases / guards:** The profile name (`kilocode`) and the canonical identity id (`kilo`) differ — the plugin profile is looked up by `kilocode`, `providers.py` by `kilo`.
- **Rebuild notes:** Bare profile.

### Moonshot Kimi Coding (global)  `id: providers.kimi-coding`
- **Surface:** Provider
- **Where:** `model.provider: kimi-coding`; plugin `plugins/model-providers/kimi-coding/__init__.py:113-126`.
- **What it does:** Moonshot/Kimi models on the OpenAI-compatible `/v1` endpoint, with the Kimi-specific "thinking XOR reasoning_effort" rule and temperature omitted.
- **How it works:** `KimiProfile.fetch_models()` (`:40-59`): resolves the effective base URL; `_is_confirmed_kimi_coding_url()` (`:18-34`) accepts only `https://api.kimi.com` on port 443/None with no userinfo, no query, no fragment and a path of exactly `/coding` or `/coding/v1`; when the path is `/coding` it appends `/v1` for discovery. On a non-coding endpoint it filters out the bare model id `k3` (case-insensitive). `build_api_kwargs_extras()` (`:61-110`): no config → `extra_body["thinking"] = {"type":"enabled"}` only; `enabled is False` → `{"type":"disabled"}`; enabled with a recognised effort → top-level `reasoning_effort = clamp_effort(effort, KIMI_K3_EFFORTS, KIMI_K3_OVERRIDES)` and **no** `thinking` key; enabled without a recognised effort → `thinking: enabled`. Sending both `thinking` and `reasoning_effort` risks HTTP 400 `"cannot specify both 'thinking' and 'reasoning_effort'"`.
- **Inputs / options:** aliases `kimi`, `moonshot`, `kimi-for-coding`; `base_url="https://api.moonshot.ai/v1"`; `fixed_temperature=OMIT_TEMPERATURE` (temperature is never sent — the server manages it); `default_max_tokens=32000`; `default_headers={"HTTP-Referer": "https://hermes-agent.nousresearch.com", "X-Title": "Hermes Agent", "User-Agent": "HermesAgent/<version>"}`; `default_aux_model="kimi-k2-turbo-preview"`.
- **Outputs / side effects:** n/a beyond the wire shape.
- **Config / env:** `KIMI_API_KEY`, `KIMI_CODING_API_KEY`; overlay `kimi-for-coding` sets `base_url_env_var="KIMI_BASE_URL"`. `host_mandated_api_mode` forces `anthropic_messages` for `api.kimi.com` + `/coding` — the dual-endpoint split is `sk-kimi-*` keys → `api.kimi.com/coding` (Anthropic Messages) vs legacy keys → `api.moonshot.ai/v1` (OpenAI chat completions).
- **Edge cases / guards:** K3 effort vocabulary is `(low, high, max)` with documented rounding `medium→high` (K3's positional middle and server default) and `xhigh→max`.
- **Rebuild notes:** Strict URL validation + XOR reasoning fields + omitted temperature. A better version would negotiate the endpoint from the key prefix automatically.

### Moonshot Kimi Coding (China)  `id: providers.kimi-coding-cn`
- **Surface:** Provider
- **Where:** `model.provider: kimi-coding-cn`; `plugins/model-providers/kimi-coding/__init__.py:128-141`.
- **What it does:** The mainland-China Moonshot endpoint with the identical Kimi wire quirks.
- **How it works:** Same `KimiProfile` class, different base URL and key.
- **Inputs / options:** aliases `kimi-cn`, `moonshot-cn`; `base_url="https://api.moonshot.cn/v1"`; `fixed_temperature=OMIT_TEMPERATURE`; `default_max_tokens=32000`; same three attribution headers; `default_aux_model="kimi-k2-turbo-preview"`.
- **Outputs / side effects:** n/a.
- **Config / env:** `KIMI_CN_API_KEY`.
- **Edge cases / guards:** `resolve_provider_full` step 0.5 exists precisely so `kimi-coding-cn` does not collapse into `kimi-for-coding` via the lossy alias table.
- **Rebuild notes:** Region twin of `kimi-coding`.

### Meta Model API (Muse Spark)  `id: providers.meta-ai`
- **Surface:** Provider
- **Where:** `model.provider: meta-ai`; plugin `plugins/model-providers/meta-ai/` (bundled from `https://github.com/albertodepaola/hermes-meta-provider`).
- **What it does:** Meta Superintelligence Labs' Muse Spark family on the OpenAI-compatible Meta Model API.
- **How it works:** `MetaAIProfile.build_api_kwargs_extras()` (`meta-ai/__init__.py:61-75`) always returns `({}, {"reasoning_effort": _resolve_effort(reasoning_config)})` — it deliberately **ignores** the core `supports_reasoning` gate, because that flag is driven by a hard-coded host allowlist in `AIAgent._supports_reasoning_extra_body` that an out-of-tree plugin must not edit. `_resolve_effort()` (`:38-55`): `enabled is False` → `"minimal"`; empty effort → `"medium"`; explicit `"none"` → `"minimal"` (Muse **rejects** `none` with a 400); otherwise `clamp_effort(effort, META_AI_EFFORTS)` falling back to `"medium"`. `_base_url()` (`:78-80`) allows `META_BASE_URL` to override `https://api.meta.ai/v1` without editing config.
- **Inputs / options:** aliases `meta`, `muse`, `muse-spark`, `model-api`, `msl`; `display_name="Meta Model API"`; `description="Meta Muse Spark family (Meta Superintelligence Labs)"`; `signup_url="https://developer.meta.com/ai/"`; `api_mode="codex_responses"`; `auth_type="api_key"`; `supports_vision=True` (Muse Spark is natively multimodal — image/video/pdf/audio in, text out); `default_aux_model="muse-spark-1.2-contributor"`; `default_max_tokens=16384` (Muse spends completion budget on hidden reasoning tokens first; a low cap can finish with empty content); `fallback_models=("muse-spark-1.2", "muse-spark-1.2-contributor")`.
- **Outputs / side effects:** Top-level `reasoning_effort` on every request.
- **Config / env:** `MODEL_API_KEY` (Meta's documented var), `META_API_KEY`, `META_MODEL_API_KEY`, `META_BASE_URL`.
- **Edge cases / guards:** `host_mandated_api_mode` pins `api.meta.ai` to `codex_responses` because Responses is the only wire that engages Muse prompt caching (measured 0 cached tokens on `/v1/chat/completions` vs 93–99% cache hits on `/v1/responses` with `prompt_cache_retention`). A non-`api.meta.ai` base URL falls through to chat-completions, where the profile's hook still applies. Context window (1M), reasoning and vision capabilities resolve from models.dev for the muse-spark family, so no static table entry is required.
- **Rebuild notes:** Responses client + a self-gating effort mapper. A better version would not need the `supports_reasoning` bypass — the core gate would be data-driven.

### MiniMax (international)  `id: providers.minimax`
- **Surface:** Provider
- **Where:** `model.provider: minimax`; `plugins/model-providers/minimax/__init__.py:62-70`.
- **What it does:** MiniMax M-series models on MiniMax's Anthropic-compatible endpoint by default, with an opt-in OpenAI-compatible route for MiniMax-M3.
- **How it works:** `MiniMaxProfile.build_api_kwargs_extras()` (`:32-59`) only fires when `_is_minimax_global_openai_base_url(base_url)` (hostname exactly `api.minimax.io` and path exactly `/v1`, `:16-21`) **and** `_is_minimax_m3(model)` (`minimax-m3` or `minimax/minimax-m3`, `:24-26`). Then: always `extra_body["reasoning_split"] = True` (M3's OpenAI-compatible endpoint keeps thinking inline unless the split format is requested); `enabled is False` → `extra_body["thinking"] = {"type": "disabled"}`; any other non-None config → `{"type": "adaptive"}`. Hermes effort levels are not a MiniMax depth knob here — they only select adaptive vs disabled.
- **Inputs / options:** alias `mini-max`; `api_mode="anthropic_messages"`; `auth_type="api_key"`; `base_url="https://api.minimax.io/anthropic"`; `default_aux_model="MiniMax-M3"`.
- **Outputs / side effects:** `reasoning_split` / `thinking` in `extra_body` on the OpenAI route only.
- **Config / env:** `MINIMAX_API_KEY`; overlay `minimax`: `transport="anthropic_messages"`, `base_url_env_var="MINIMAX_BASE_URL"`; `tts.minimax.model` default `speech-02-hd` is a separate TTS key.
- **Edge cases / guards:** The `/anthropic` base-URL suffix triggers `host_mandated_api_mode → anthropic_messages`.
- **Rebuild notes:** Anthropic-compatible client + a narrow OpenAI-route carve-out for one model.

### MiniMax (China)  `id: providers.minimax-cn`
- **Surface:** Provider
- **Where:** `model.provider: minimax-cn`; `plugins/model-providers/minimax/__init__.py:72-80`.
- **What it does:** MiniMax on the mainland-China host.
- **How it works:** Same `MiniMaxProfile`.
- **Inputs / options:** aliases `minimax-china`, `minimax_cn`; `api_mode="anthropic_messages"`; `base_url="https://api.minimaxi.com/anthropic"`; `default_aux_model="MiniMax-M3"`.
- **Outputs / side effects:** n/a.
- **Config / env:** `MINIMAX_CN_API_KEY`; overlay `minimax-cn` sets `base_url_env_var="MINIMAX_CN_BASE_URL"`.
- **Edge cases / guards:** The M3 OpenAI carve-out never fires here (hostname check is `api.minimax.io` only).
- **Rebuild notes:** Region twin.

### MiniMax (OAuth)  `id: providers.minimax-oauth`
- **Surface:** Provider
- **Where:** `model.provider: minimax-oauth`; `plugins/model-providers/minimax/__init__.py:82-93`.
- **What it does:** MiniMax through a browser OAuth flow — no API key needed.
- **How it works:** Same `MiniMaxProfile`; `auth_type="oauth_external"` so tokens live in `auth.json`, not env.
- **Inputs / options:** aliases `minimax_oauth`, `minimax-oauth-io`; `display_name="MiniMax (OAuth)"`; `description="MiniMax via OAuth browser flow — no API key required"`; `signup_url="https://api.minimax.io/"`; `env_vars=()`; `base_url="https://api.minimax.io/anthropic"`; `default_aux_model="MiniMax-M2.7"`.
- **Outputs / side effects:** Writes OAuth tokens to the credential store.
- **Config / env:** none (tokens only); overlay `minimax-oauth`: `auth_type="oauth_external"`, `base_url_override="https://api.minimax.io/anthropic"`.
- **Edge cases / guards:** Different default aux model (`MiniMax-M2.7`) from the keyed profiles (`MiniMax-M3`).
- **Rebuild notes:** OAuth-external variant of the same endpoint.

### Nebius Token Factory  `id: providers.nebius-token-factory`
- **Surface:** Provider
- **Where:** `model.provider: nebius-token-factory` (label "Nebius Token Factory"); plugin `plugins/model-providers/nebius-token-factory/`.
- **What it does:** Nebius's OpenAI-compatible inference with a top-level `reasoning_effort` knob for the reasoning-capable subset of its catalog.
- **How it works:** `_model_supports_reasoning_effort(model)` (`:16-33`) is a conservative substring allowlist on the last path segment: `deepseek-r1`, `deepseek-v4`, `deepseek-reasoner`, `gpt-oss`, `glm-5`, `kimi-k2`, `minimax-m2`, `qwen3`. `NebiusTokenFactoryProfile.build_api_kwargs_extras()` (`:39-67`): bail when neither `supports_reasoning` nor the allowlist matches; default `enabled=True`, `effort="medium"`; `enabled is False` or effort in `{none, off, disabled}` → emit nothing; otherwise `clamp_effort(effort, NEBIUS_EFFORTS) or "medium"` → top-level `reasoning_effort`.
- **Inputs / options:** aliases `nebius`, `nebius-tokenfactory`, `nebius-tf`, `token-factory`, `tokenfactory`; `display_name="Nebius Token Factory"`; `description="Nebius Token Factory — OpenAI-compatible inference"`; `signup_url="https://tokenfactory.nebius.com/"`; `base_url="https://api.tokenfactory.nebius.com/v1"`; `models_url="https://api.tokenfactory.nebius.com/v1/models?verbose=true"`; `auth_type="api_key"`; `default_aux_model="nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"`; `fallback_models=("Qwen/Qwen3.5-397B-A17B-fast", "deepseek-ai/DeepSeek-V4-Pro", "zai-org/GLM-5.1", "moonshotai/Kimi-K2.5-fast", "MiniMaxAI/MiniMax-M2.5-fast", "deepseek-ai/DeepSeek-V3.2-fast", "NousResearch/Hermes-4-70B", "openai/gpt-oss-120b-fast", "meta-llama/Llama-3.3-70B-Instruct")`.
- **Outputs / side effects:** Verbose catalog fetch (`?verbose=true`) supplies richer metadata.
- **Config / env:** `NEBIUS_API_KEY`, `NEBIUS_TOKEN_FACTORY_API_KEY`, `NEBIUS_BASE_URL`; overlay adds both key vars and `base_url_env_var="NEBIUS_BASE_URL"`.
- **Edge cases / guards:** The canonical clamp replaced a hand-rolled map that inverted the ladder (`ultra` fell to `medium` while `xhigh` mapped to `high`).
- **Rebuild notes:** Allowlist + clamp + verbose catalog URL.

### Nous Research Portal  `id: providers.nous`
- **Surface:** Provider
- **Where:** `model.provider: nous` (label "Nous Portal"); plugin `plugins/model-providers/nous/`; CLI `hermes portal`, `hermes model`, `hermes auth add nous --type oauth`.
- **What it does:** Nous Research's own inference Portal — the first-party provider, with OAuth device-code login, product tags, sticky routing, live recommended-model discovery and reasoning-mandatory awareness.
- **How it works:** `NousProfile` (`nous/__init__.py:11-124`):
  - `resolve_aux_model(*, vision=False)` (`:14-28`) asks `hermes_cli.models.get_nous_recommended_aux_model(vision=…)`, which reads the Portal's `/api/nous/recommended-models` (tier-aware: free vs paid) — memory- and disk-cached with last-known-good fallback, so it is cheap and safe offline.
  - `build_extra_body()` (`:30-66`) emits `{"tags": nous_portal_tags(session_id=…)}`; a top-level `session_id` sticky routing key from `_cache_scope_from_session_id(get_conversation_context() or session_id)` — resolved from the **ambient conversation contextvar first**, explicit argument as fallback, which is what makes auxiliary calls (compression, title generation, vision, `web_extract`, `session_search`, MoA slots) route to the same upstream endpoint as their parent conversation (#70820); and `{"provider": provider_preferences}` when preferences are passed.
  - `_cannot_disable_reasoning(model)` (`:68-96`): consults `hermes_cli.models.nous_model_reasoning_capabilities(model)` (cache-only); a cold/unknown catalog answers **True** and kicks `warm_nous_reasoning_caps_async()`, so a cold first turn errs toward omitting rather than risking a 400 `"Reasoning is mandatory for this model"`; also True when the catalog says the route takes no reasoning parameter or marks it mandatory.
  - `build_api_kwargs_extras()` (`:98-124`): when `supports_reasoning`, passes the FULL `reasoning_config` (including `{"enabled": false}` — the Portal is the only wire that honours a disable) unless `_cannot_disable_reasoning` vetoes it; with no config it sends `{"enabled": True, "effort": "medium"}`.
- **Inputs / options:** aliases `nous-portal`, `nousresearch`; `api_mode="chat_completions"` (dual-wire: `anthropic/*` model ids go to `anthropic_messages` per `nous_api_mode()`); `auth_type="oauth_device_code"`; `display_name="Nous Research"`; `description="Nous Research — Hermes model family"`; `signup_url="https://nousresearch.com/"`; `base_url="https://inference-api.nousresearch.com/v1"`; `fallback_models=("hermes-3-405b", "hermes-3-70b")`.
- **Outputs / side effects:** Every request carries `tags` (product attribution) and a sticky `session_id`.
- **Config / env:** `NOUS_API_KEY`; `cron.chronos.portal_url` default `https://portal.nousresearch.com`; `dashboard.oauth.portal_url` (default `""`).
- **Edge cases / guards:** With `compression.in_place: true` (the default, #38763) the ambient root and the session id agree; the ambient root additionally keeps the key stable for installs that opt back into rotating compaction and across delegate-subagent trees.
- **Rebuild notes:** OAuth device-code + tag injection + sticky routing key + catalog-driven reasoning capability. A better version would publish the sticky key and tags as first-class request metadata rather than `extra_body` fields.

### NovitaAI  `id: providers.novita`
- **Surface:** Provider
- **Where:** `model.provider: novita`; plugin `plugins/model-providers/novita/`.
- **What it does:** NovitaAI's OpenAI-compatible cloud for builders and agents.
- **How it works:** Plain profile.
- **Inputs / options:** aliases `novita-ai`, `novitaai`; `display_name="NovitaAI"`; `description="NovitaAI — AI-native cloud for builders and agents"`; `signup_url="https://novita.ai/settings/key-management"`; `base_url="https://api.novita.ai/openai/v1"`; `auth_type="api_key"`; `default_aux_model="deepseek/deepseek-v3-0324"`; `fallback_models=("moonshotai/kimi-k2.5", "minimax/minimax-m2.7", "zai-org/glm-5", "deepseek/deepseek-v3-0324", "deepseek/deepseek-r1-0528", "qwen/qwen3-235b-a22b-fp8")`.
- **Outputs / side effects:** n/a.
- **Config / env:** `NOVITA_API_KEY`, `NOVITA_BASE_URL`; overlay `novita`: `is_aggregator=True`, `base_url_env_var="NOVITA_BASE_URL"`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Bare profile.

### NVIDIA NIM  `id: providers.nvidia`
- **Surface:** Provider
- **Where:** `model.provider: nvidia`; plugin `plugins/model-providers/nvidia/`.
- **What it does:** NVIDIA's accelerated inference endpoints, with tool-message sanitisation for NIM's stricter schema.
- **How it works:** `NvidiaProviderProfile.prepare_messages()` (`nvidia/__init__.py:12-41`) drops `name` and `tool_name` from `role: "tool"` messages, which NIM rejects. It uses copy-on-write — a shallow outer-list copy plus a shallow dict copy only for the messages that actually need a field removed — so large tool outputs and attachments are never deep-copied; it early-returns when no message needs sanitising.
- **Inputs / options:** alias `nvidia-nim`; `display_name="NVIDIA NIM"`; `description="NVIDIA NIM — accelerated inference"`; `signup_url="https://build.nvidia.com/"`; `base_url="https://integrate.api.nvidia.com/v1"`; `default_max_tokens=16384`; `fallback_models=("nvidia/llama-3.1-nemotron-70b-instruct", "nvidia/llama-3.3-70b-instruct")`.
- **Outputs / side effects:** Sanitised message list on the wire.
- **Config / env:** `NVIDIA_API_KEY`; overlay `nvidia`: `base_url_override="https://integrate.api.nvidia.com/v1"`, `base_url_env_var="NVIDIA_BASE_URL"`.
- **Edge cases / guards:** Matches the copy-on-write pattern used by the shared sanitizer in `agent/transports/chat_completions.py` and `QwenProfile.prepare_messages()`.
- **Rebuild notes:** Message preprocessor that removes two keys. A better version would validate the whole message against the provider's published JSON schema before sending.

### Ollama Cloud  `id: providers.ollama-cloud`
- **Surface:** Provider
- **Where:** `model.provider: ollama-cloud` (label "Ollama Cloud"); plugin `plugins/model-providers/ollama-cloud/`.
- **What it does:** Ollama's hosted cloud endpoint, mapping Hermes's `xhigh` onto Ollama's undocumented-but-real `max` thinking tier.
- **How it works:** `OllamaCloudProfile.build_api_kwargs_extras()` (`:29-84`) is gated on `supports_reasoning`, which the transport resolves from the model's native `/api/show` `capabilities` (`thinking`) — models without it (`gemma3`, `qwen3-coder`) get nothing. Then: `enabled is False` → top-level `reasoning_effort: "none"` (Ollama Cloud defaults thinking ON and **ignores** `extra_body.thinking:{type:disabled}`; only top-level `reasoning_effort:"none"` actually suppresses it); no effort → emit nothing; effort `"none"` → `reasoning_effort:"none"`; otherwise `clamp_effort(effort, OLLAMA_CLOUD_EFFORTS, OLLAMA_CLOUD_OVERRIDES)` and emit only if the result is in the accepted set. `max` produces ~2.5× more thinking tokens than `high` on DeepSeek V4.
- **Inputs / options:** alias `ollama_cloud`; `base_url="https://ollama.com/v1"`; `default_aux_model="nemotron-3-nano:30b"`.
- **Outputs / side effects:** Top-level `reasoning_effort`.
- **Config / env:** `OLLAMA_API_KEY`; overlay `ollama-cloud`: `base_url_override="https://ollama.com/v1"`, `base_url_env_var="OLLAMA_BASE_URL"`.
- **Edge cases / guards:** `minimal` is rejected with HTTP 400 → clamps to `low`. Bespoke levels outside the ladder are omitted so the model applies its own default rather than triggering a hard 400.
- **Rebuild notes:** Capability probe + top-level effort with an explicit off switch.

### OpenAI Codex (ChatGPT / Codex subscription)  `id: providers.openai-codex`
- **Surface:** Provider
- **Where:** `model.provider: openai-codex` (label "ChatGPT or Codex Subscription"); plugin `plugins/model-providers/openai-codex/`; runtime in `agent/codex_runtime.py`, `agent/codex_responses_adapter.py`, `agent/codex_headers.py`.
- **What it does:** Uses a ChatGPT/Codex subscription (not an API key) as the inference backend over OpenAI's Responses API.
- **How it works:** Profile is minimal (`api_mode="codex_responses"`, `auth_type="oauth_external"`, `env_vars=()` — "OAuth external — no API key"). Everything else lives in the codex runtime modules and `hermes_cli/codex_models.py`.
- **Inputs / options:** aliases `codex`, `openai_codex`; `base_url="https://chatgpt.com/backend-api/codex"`.
- **Outputs / side effects:** Tokens persisted by the credential store; `hermes logout --provider openai-codex` clears them.
- **Config / env:** none directly; `compression.codex_gpt55_autoraise` (`true`), `compression.codex_gpt55_autoraise_notice` (`true`), `compression.codex_app_server_auto` (`"native"`), `compression.codex_responses_native` (`false`), `compression.codex_responses_compact_threshold` (`null`).
- **Edge cases / guards:** `host_mandated_api_mode` pins `api.openai.com` (and regional `us.`/`eu.` variants) to `codex_responses`. Effort vocabulary: `codex_supported_efforts(model)` → `(none, low, medium, high, xhigh, max)` for `gpt-5.6`, `(none, low, medium, high, xhigh)` otherwise; `minimal` is rejected by both generations and clamps to `low`.
- **Rebuild notes:** Responses-API client + subscription OAuth + per-generation effort vocabulary.

### OpenCode Free (keyless)  `id: providers.opencode-free`
- **Surface:** Provider
- **Where:** `model.provider: opencode-free` (label "OpenCode Free"); selectable via `hermes model` or `/model free`; plugin `plugins/model-providers/opencode-free/`.
- **What it does:** OpenCode's free model tier on the Zen relay — **keyless**: no OpenCode account, no credential of any kind.
- **How it works:** The relay serves free-tier models anonymously and **rejects any Authorization bearer it does not recognise with 401**, so the profile pins an empty `Authorization` header to keep the SDK's `Bearer <placeholder>` off the wire. `_KEYLESS_HEADERS` (`:21-26`) = `{"Authorization": "", "HTTP-Referer": "https://hermes-agent.nousresearch.com", "X-Title": "Hermes Agent", "User-Agent": "HermesAgent/<version>"}`. The runtime resolver pins the keyless placeholder in `hermes_cli.models.opencode_zen_free_runtime`. `OpenCodeFreeProfile.build_api_kwargs_extras()` (`:39-51`) delegates to the zen plugin's `_build_ox_alpha_reasoning_extras()` by resolving the registered `opencode-zen` profile's module through `sys.modules`, so the two providers can never drift.
- **Inputs / options:** aliases `free`, `opencode_free`; `env_vars=()`; `base_url="https://opencode.ai/zen/v1"`; `display_name="OpenCode Free"`; `description="OpenCode free models — keyless, no account needed"`; `default_aux_model="laguna-s-2.1-free"` — laguna is the fastest non-UA-gated free model; `big-pickle` 429s every client except the opencode CLI's own User-Agent (verified 2026-08-21).
- **Outputs / side effects:** Requests carry an explicitly empty `Authorization` header.
- **Config / env:** none; overlay `opencode-free`: `is_aggregator=True`, `base_url_override="https://opencode.ai/zen/v1"`, `keyless=True`.
- **Edge cases / guards:** Ox Alpha (`x-preview-f-free`) accepts exactly `low`/`high`/`max`; anything else 400s.
- **Rebuild notes:** Keyless client with a blanked Authorization header. A better version would advertise the free tier's rate limits in the picker.

### OpenCode Go  `id: providers.opencode-go`
- **Surface:** Provider
- **Where:** `model.provider: opencode-go`; `plugins/model-providers/opencode-zen/__init__.py:211-218`.
- **What it does:** OpenCode's Go subscription relay, with per-model reasoning translation for GLM-5.2, Kimi K2 and DeepSeek thinking models.
- **How it works:** `OpenCodeGoProfile` (`:52-158`). `get_max_tokens(model)` (`:64-68`) consults `_MODEL_MAX_TOKENS = {"mimo-v2.5-pro": 131072}` (`:60-62`) — the relay's default `max_tokens=262144` exceeds Xiaomi's 131072 completion-token limit and 400s. `build_api_kwargs_extras()` branches:
  - **GLM-5.2** (`_is_glm_5_2_model`, matches `glm-5.2` / `glm-5-2` / `glm-5p2` in the flattened name): no config, disabled, or empty/`none` effort → leave server defaults; otherwise `clamp_effort(effort, GLM52_EFFORTS, GLM52_OVERRIDES)` → top-level `reasoning_effort`, defaulting to `"high"` when the clamp lands outside the set.
  - **Kimi K2** (`_is_kimi_k2_model`, flattened name starts `kimi-k2`): no config → leave defaults; disabled → `extra_body["thinking"]={"type":"disabled"}`; enabled + effort → `clamp_effort(effort, KIMI_K2_EFFORTS)` → top-level `reasoning_effort`; `thinking:{enabled}` added **only** when no `reasoning_effort` was set (avoids the 400 `"cannot specify both 'thinking' and 'reasoning_effort'"`).
  - **DeepSeek thinking** (`_is_deepseek_thinking_model`: starts `deepseek-v` and not `deepseek-v3`, or equals `deepseek-reasoner`): disabled → `thinking:{disabled}`; else `clamp_effort(effort, DEEPSEEK_V4_EFFORTS, DEEPSEEK_V4_OVERRIDES)` → `reasoning_effort`, and `thinking:{enabled}` only when no effort was set.
  - Anything else → no-op.
  Per-model api_mode routing on Go: GPT / Grok / Muse Spark → `codex_responses`, MiniMax / Qwen → `anthropic_messages`, GLM / Kimi / DeepSeek / MiMo → `chat_completions`.
- **Inputs / options:** aliases `opencode_go`, `go`, `opencode-go-sub`; `base_url="https://opencode.ai/zen/go/v1"`; `default_headers` = the shared `_ATTRIBUTION_HEADERS` (`HTTP-Referer`, `X-Title`, `User-Agent: HermesAgent/<version>`); `default_aux_model="glm-5"`.
- **Outputs / side effects:** Per-model wire shape as above.
- **Config / env:** `OPENCODE_GO_API_KEY`; overlay `opencode-go`: `is_aggregator=True`, `base_url_env_var="OPENCODE_GO_BASE_URL"`.
- **Edge cases / guards:** `_flat_model_name()` takes the last `/`-separated segment lowercased, so aggregator prefixes are tolerated. Classified as a flat-namespace **reseller**, not a routing aggregator, so the picker never dedups its first-party models against user proxies.
- **Rebuild notes:** One profile with three model-family branches and a per-model token cap.

### OpenCode Zen  `id: providers.opencode-zen`
- **Surface:** Provider
- **Where:** `model.provider: opencode-zen`; `plugins/model-providers/opencode-zen/__init__.py:202-209`.
- **What it does:** OpenCode's Zen relay with the Ox Alpha reasoning translation.
- **How it works:** `OpenCodeZenProfile.build_api_kwargs_extras()` (`:196-199`) delegates entirely to `_build_ox_alpha_reasoning_extras(reasoning_config, model)` (`:161-190`), which fires only for the flattened model name `x-preview-f-free`: skip on no-config / disabled / empty-or-`none` effort; otherwise `clamp_effort(effort, OX_ALPHA_EFFORTS, OX_ALPHA_OVERRIDES)` → top-level `reasoning_effort` when it lands in the set. Ox Alpha's wire error message is `"This model always engages in thinking and cannot be disabled; please use low, high, or max"`. Per-model api_mode routing on Zen: Claude → `anthropic_messages`, GPT-5/Codex/Grok → `codex_responses`, Muse Spark → `codex_responses`, everything else → `chat_completions`.
- **Inputs / options:** aliases `opencode`, `opencode_zen`, `zen`; `base_url="https://opencode.ai/zen/v1"`; `default_headers` = `_ATTRIBUTION_HEADERS`; `default_aux_model="gemini-3-flash"`.
- **Outputs / side effects:** Attribution headers; Ox Alpha effort.
- **Config / env:** `OPENCODE_ZEN_API_KEY`; overlay `opencode`: `is_aggregator=True`, `base_url_env_var="OPENCODE_ZEN_BASE_URL"`.
- **Edge cases / guards:** The profile's `fetch_models` inherits the base implementation, whose UA override exists precisely because OpenCode Zen sits behind a WAF that 403s `Python-urllib`.
- **Rebuild notes:** Shared translation function used by two profiles.

### OpenRouter  `id: providers.openrouter`
- **Surface:** Provider
- **Where:** `model.provider: openrouter` (alias `or`); plugin `plugins/model-providers/openrouter/`.
- **What it does:** OpenRouter's unified API for 200+ models, with catalog-driven reasoning clamping, sticky routing, Anthropic-adaptive-thinking handling, xAI cache pinning and the Pareto Code router plugin.
- **How it works:** `OpenRouterProfile` (`openrouter/__init__.py:49-231`):
  - `fetch_models()` (`:89-113`) hits the **public** catalog with no auth and memoises the result in a module-level `_CACHE`. Tool-call capability filtering is applied elsewhere (`hermes_cli/models.py::fetch_openrouter_models → _openrouter_model_supports_tools`).
  - `build_extra_body()` (`:115-159`) emits `session_id` (OpenRouter's documented sticky routing key, resolved as `_cache_scope_from_session_id(get_conversation_context() or session_id)` — the ambient-first resolution closes the auxiliary-call gap of #70820), `provider` when `provider_preferences` are passed, and — **only** for `model == "openrouter/pareto-code"` — `plugins: [{"id": "pareto-router", "min_coding_score": <float 0.0–1.0>}]`.
  - `build_api_kwargs_extras()` (`:161-231`): for reasoning-mandatory Anthropic models (`_anthropic_reasoning_is_mandatory`, `:34-46`) it sends **no** `reasoning` field at all — any enabled form on a tool-continuation turn whose prior assistant tool_call carries no thinking block makes OpenRouter emit Anthropic's `thinking: {type:"disabled"}`, which those models 400 on (#42991 and its tool-replay follow-up) — and instead routes the requested effort onto top-level `verbosity` (which maps to Anthropic's `output_config.effort`; `reasoning.effort` is accepted but ignored, confirmed by OpenRouter's Claude migration docs and a live token-spend probe, #43432). Otherwise it passes `reasoning_config` through `_clamp_reasoning_to_catalog()` (`:52-87`), which reads `openrouter_model_reasoning_capabilities(model)` and clamps `effort` to the nearest LOWER catalog-advertised level (ported from PrimeIntellect-ai/prime-agent#1258); with no config it sends `{"enabled": True, "effort": "medium"}`. It also attaches `extra_headers["x-grok-conv-id"] = <sticky key>` for models starting `x-ai/grok-` or `xai/grok-` so xAI's prompt cache stays pinned to one backend server.
  - `_ANTHROPIC_REASONING_OPTIONAL_SUBSTRINGS` (`:23-31`) — the explicit legacy allowlist of Claude models that CAN still be told to stop thinking: `claude-3`, `claude-opus-4-0`, `claude-opus-4.0`, `claude-opus-4-1`, `claude-opus-4.1`, `claude-sonnet-4-0`, `claude-sonnet-4.0`, `claude-opus-4-2025`, `claude-sonnet-4-2025`, `claude-opus-4-5`, `claude-opus-4.5`, `claude-sonnet-4-5`, `claude-sonnet-4.5`, `claude-haiku-4-5`, `claude-haiku-4.5`. Unknown/new Anthropic names default to **mandatory**.
- **Inputs / options:** alias `or`; `display_name="OpenRouter"`; `description="OpenRouter — unified API for 200+ models"`; `signup_url="https://openrouter.ai/keys"`; `base_url="https://openrouter.ai/api/v1"`; `models_url="https://openrouter.ai/api/v1/models"`; `fallback_models=("anthropic/claude-sonnet-4.6", "openai/gpt-5.4", "deepseek/deepseek-chat", "google/gemini-3.7-flash", "qwen/qwen3-plus")`.
- **Outputs / side effects:** `extra_body.reasoning` / `extra_body.session_id` / `extra_body.provider` / `extra_body.plugins`; `verbosity`; `x-grok-conv-id` header.
- **Config / env:** `OPENROUTER_API_KEY`; `openrouter.response_cache` (default `true`), `openrouter.response_cache_ttl` (`300`), `openrouter.min_coding_score` (`0.65`); `auxiliary.openrouter_model` (`""`); overlay `openrouter`: `is_aggregator=True`, `base_url_env_var="OPENROUTER_BASE_URL"`.
- **Edge cases / guards:** `min_coding_score` is only forwarded when it parses as a float in `[0.0, 1.0]`. `ALIASES` maps bare `openai → openrouter` unless the user declares `providers.openai` in config.yaml.
- **Rebuild notes:** Catalog-clamped reasoning + sticky key + per-family carve-outs. A better version would make the Anthropic-mandatory list catalog-derived instead of a substring allowlist.

### Qwen Portal (OAuth)  `id: providers.qwen-oauth`
- **Surface:** Provider
- **Where:** `model.provider: qwen-oauth`; plugin `plugins/model-providers/qwen-oauth/`.
- **What it does:** Qwen Portal via OAuth, with message normalisation, prompt-cache breakpoints and high-resolution vision.
- **How it works:** `QwenProfile` (`qwen-oauth/__init__.py:8-96`):
  - `prepare_messages()` (`:20-78`) normalises every `content` to a list of dicts: a plain string becomes `[{"type":"text","text": …}]`; string parts inside a list become text parts; dict parts with an `image_url` dict are copied so the request stays mutable (`_copy_part_if_request_mutable`, `:11-18`). It then injects `cache_control: {"type": "ephemeral"}` onto the LAST part of the FIRST `role: "system"` message. Mirrors `run_agent.py:_qwen_prepare_chat_messages()`.
  - `build_extra_body()` (`:80-83`) always emits `{"vl_high_resolution_images": True}`.
  - `build_api_kwargs_extras()` (`:85-96`) puts `qwen_session_metadata` on **top-level** `api_kwargs["metadata"]`, not in `extra_body`.
- **Inputs / options:** aliases `qwen`, `qwen-portal`, `qwen-cli`; `auth_type="oauth_external"`; `base_url="https://portal.qwen.ai/v1"`; `default_max_tokens=65536`.
- **Outputs / side effects:** Rewritten message list; `vl_high_resolution_images`; top-level `metadata`.
- **Config / env:** `QWEN_API_KEY`; overlay `qwen-oauth`: `auth_type="oauth_external"`, `base_url_override="https://portal.qwen.ai/v1"`, `base_url_env_var="HERMES_QWEN_BASE_URL"`.
- **Edge cases / guards:** `ALIASES` maps bare `qwen → alibaba` at the identity layer while the plugin registry maps `qwen → qwen-oauth`; the two namespaces are separate.
- **Rebuild notes:** Message normaliser + one cache breakpoint + two request fields.

### Ramp Router (router.com)  `id: providers.router`
- **Surface:** Provider
- **Where:** `model.provider: router` (display "Ramp Router"); plugin `plugins/model-providers/router/` (395 lines — the largest profile).
- **What it does:** Ramp's LLM gateway: one OpenAI-Responses-compatible endpoint that routes each request across upstream providers (OpenAI, Anthropic, xAI, Fireworks…) and handles fallbacks and spend controls server-side, picking the cheapest model that clears a quality bar.
- **How it works:** `RouterProfile` (`router/__init__.py:308-362`) plus a full capability-cache subsystem:
  - `fetch_models()` (`:311-339`) fetches the live, **key-scoped** catalog (BYOK accounts see extra entries) and seeds the reasoning-effort cache from the same document at no extra network cost. IDs are deduped with `dict.fromkeys` but **not sorted** — Router's listing order is deliberate presentation (featured/current first), so the picker keeps it.
  - `supported_reasoning_efforts(model)` (`:341-362`) is cache-only: memory → disk mirror → `None` + background warm. Router 400s with `invalid-argument` on an effort outside a model's published set (e.g. `max` on `grok-4.6`) and with `unsupported_parameter` when a non-reasoning model (gpt-4.1 family, gpt-4o) receives any reasoning field.
  - `_parse_efforts()` (`:111-168`) reads `item["router"]["capabilities"]["reasoning"]`: `supported: false` → `[]` (definitive negative — omit reasoning entirely); otherwise the `efforts[].value` list, filtered against `EFFORT_LADDER` with an INFO log `"router: model %s publishes unrecognized reasoning effort level(s) %s; ignoring them (update agent/reasoning_effort EFFORT_LADDER to adopt new vendor tiers)"`; `supported: true` with no recognised vocabulary leaves the model out (unknown).
  - Disk mirror at `$HERMES_HOME/cache/router_catalog.json` (`_disk_path`, `:171-177`) written atomically via a `.tmp` + `replace` (`_save_disk`, `:180-193`), carrying `{"ts": <epoch>, "efforts": {...}}`. `_DISK_TTL_SECONDS = 24*60*60` (`:76`) — a past-TTL mirror is still served while a background refresh runs.
  - `_warm_efforts_async()` (`:279-305`) starts at most one daemon thread named `router-caps-warm` per process, skips entirely under `PYTEST_CURRENT_TEST`, and does nothing without a key (an unauthenticated fetch would 401).
  - `_resolve_api_key()` (`:84-108`) prefers `hermes_cli.config.get_env_value_prefer_dotenv` over the raw environment, trying `RAMP_ROUTER_API_KEY` then `ROUTER_API_KEY`.
  - `_base_url()` (`:79-81`): `RAMP_ROUTER_BASE_URL` overrides `ROUTER_DEFAULT_BASE_URL = "https://api.router.com/v1"`.
- **Inputs / options:** aliases `ramp-router`, `ramp`, `router.com`; `api_mode="codex_responses"`; `display_name="Ramp Router"`; `description="Ramp Router (router.com) — routes each request to the cheapest model that clears your quality bar"`; `signup_url="https://app.router.com/keys"`; `auth_type="api_key"`; `default_headers={"User-Agent": "Hermes-Agent/<version>"}` (Router attributes coding-agent clients by UA prefix and its WAF rejects blank/default client UAs); `supports_vision=True`; `default_aux_model="gpt-5.4-mini"`; `fallback_models=()` deliberately empty (account-scoped catalog; Router's docs say to read the catalog at runtime).
- **Outputs / side effects:** Writes/reads `$HERMES_HOME/cache/router_catalog.json`; one background thread per process.
- **Config / env:** `RAMP_ROUTER_API_KEY`, `ROUTER_API_KEY`, `RAMP_ROUTER_BASE_URL`.
- **Edge cases / guards:** `host_mandated_api_mode` pins `api.router.com` to `codex_responses` — `/v1/chat/completions` is only a minimal compatibility shim added Aug 2026. `store: false`, `prompt_cache_key`, `include: ["reasoning.encrypted_content"]` and `reasoning.summary` are accepted on all models; encrypted reasoning replay round-trips on OpenAI-served models.
- **Rebuild notes:** Catalog fetch that doubles as a capability seeder + a TTL'd disk mirror + a one-shot background warmer + tri-state `supported_reasoning_efforts`. This is the reference design for catalog-driven effort validation; a better version would generalise it so every provider with a capability-publishing catalog reuses the same cache.

### StepFun Step Plan  `id: providers.stepfun`
- **Surface:** Provider
- **Where:** `model.provider: stepfun` (label "StepFun Step Plan"); plugin `plugins/model-providers/stepfun/`.
- **What it does:** StepFun's Step Plan endpoint.
- **How it works:** Bare profile.
- **Inputs / options:** aliases `step`, `stepfun-coding-plan`; `base_url="https://api.stepfun.ai/step_plan/v1"`; `default_aux_model="step-3.5-flash"`.
- **Outputs / side effects:** n/a.
- **Config / env:** `STEPFUN_API_KEY`; overlay `stepfun` adds `STEPFUN_API_KEY`, `base_url_override="https://api.stepfun.ai/step_plan/v1"`, `base_url_env_var="STEPFUN_BASE_URL"`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Bare profile.

### Upstage Solar  `id: providers.upstage`
- **Surface:** Provider
- **Where:** `model.provider: upstage` (label "Upstage Solar"); plugin `plugins/model-providers/upstage/`.
- **What it does:** Upstage's Solar API, with reasoning defaulted **ON** for agentic use even though Solar's own server default is off.
- **How it works:** `_NON_REASONING_MODEL_MARKERS = ("solar-mini", "syn-pro")` (`upstage/__init__.py:14`) is a **deny-list** by design — newly released Solar models are assumed reasoning-capable; substring (not prefix) matching so dated variants like `solar-mini-250127` are covered. `_DEFAULT_REASONING_EFFORT = "medium"` (`:23`) matches what Hermes's `/reasoning` panel shows for an unset config, so displayed default and wire value agree. `UpstageProfile.build_api_kwargs_extras()` (`:59-99`): deny-listed model → send nothing; `reasoning_config` absent → `{"reasoning_effort": "medium"}`; `enabled is False` (`/reasoning none`) → send nothing so Solar applies its own `minimal` default; empty effort → `"medium"`; effort `"minimal"` → send nothing (Solar's `minimal` means off); otherwise `clamp_effort(effort, SOLAR_EFFORTS)`, and a bespoke level outside the ladder collapses to `"high"` rather than silently downgrading (#62650 precedent).
- **Inputs / options:** alias `solar`; `display_name="Upstage Solar"`; `description="Upstage (Solar API)"`; `signup_url="https://console.upstage.ai/api-keys"`; `base_url="https://api.upstage.ai/v1"`; `auth_type="api_key"`; `default_aux_model` left empty → auxiliary side tasks use the main model; `fallback_models=("solar-pro3",)` — entry [0] is the setup default.
- **Outputs / side effects:** Top-level `reasoning_effort` (`low`|`medium`|`high`).
- **Config / env:** `UPSTAGE_API_KEY`, `UPSTAGE_BASE_URL`; overlay `upstage` adds `UPSTAGE_API_KEY`, `base_url_override="https://api.upstage.ai/v1"`, `base_url_env_var="UPSTAGE_BASE_URL"`.
- **Edge cases / guards:** Unlike DeepSeek/Kimi, Solar does NOT require echoing `reasoning_content` back on later turns, so only the request field needs wiring. `plugin.yaml` author: `Upstage AI`.
- **Rebuild notes:** Deny-list + default-on effort. A better version would ask Solar's catalog which models accept the field.

### Google Vertex AI  `id: providers.vertex`
- **Surface:** Provider
- **Where:** `model.provider: vertex` (label "Google Vertex AI"); plugin `plugins/model-providers/vertex/`; token minting in `agent/vertex_adapter.py`.
- **What it does:** Gemini models through Google Cloud's OpenAI-compatible Vertex endpoint, authenticated with short-lived OAuth2 access tokens from a service-account JSON or Application Default Credentials — never a static API key.
- **How it works:** `auth_type="vertex"` marks it as an OAuth-token provider (resolved specially, like Bedrock's `aws_sdk`) so a credentials-file path is never mistaken for a key. `runtime_provider.py` calls `agent/vertex_adapter.py` for a fresh `(token, base_url)` pair and hands the token to the standard OpenAI client as `api_key`. `VertexProfile.build_extra_body()` (`vertex/__init__.py:29-50`) reuses Gemini's translation, always emitting the OpenAI-compat shape `{"extra_body": {"google": {"thinking_config": <snake_cased>}}}`. `fetch_models()` (`:52-62`) returns `None` — Vertex's OpenAI-compat endpoint has no `/models` listing route; the setup wizard ships a curated list.
- **Inputs / options:** aliases `google-vertex`, `vertex-ai`, `gcp-vertex`; `api_mode="chat_completions"`; `env_vars=()`; `base_url="https://aiplatform.googleapis.com"` (the real base URL is computed at runtime from project + region); `default_aux_model="google/gemini-3.6-flash"`.
- **Outputs / side effects:** Mints and refreshes OAuth2 access tokens.
- **Config / env:** `vertex.project_id` (default `""`), `vertex.region` (default `"global"`); standard Google env (`GOOGLE_APPLICATION_CREDENTIALS`) via ADC. Overlay `vertex`: `transport="openai_chat"`, `auth_type="vertex"` — the overlay entry exists specifically so `get_provider("vertex")` does not return `None`, which would make `_preserve_provider_with_base_url()` in `agent/auxiliary_client.py` treat a Vertex MoA slot's `(base_url, api_key)` pair as an unknown custom endpoint and lose the identity `_refresh_provider_credentials()` needs to re-mint an expired token on a 401.
- **Edge cases / guards:** No message translation is needed — the wire is the OpenAI-compatible chat/completions surface.
- **Rebuild notes:** ADC/service-account token minting + Gemini thinking translation + curated model list. `plugin.yaml` author: `Steve Lawton (@slawt), Hermes Agent`.

### xAI (Grok)  `id: providers.xai`
- **Surface:** Provider
- **Where:** `model.provider: xai`; plugin `plugins/model-providers/xai/`.
- **What it does:** xAI Grok models over the Responses API with an API key.
- **How it works:** Bare `ProviderProfile` with `api_mode="codex_responses"`.
- **Inputs / options:** aliases `grok`, `x-ai`, `x.ai`; `auth_type="api_key"`; `base_url="https://api.x.ai/v1"`; `default_headers={"User-Agent": "Hermes-Agent/<hermes_cli.__version__>"}`.
- **Outputs / side effects:** n/a.
- **Config / env:** `XAI_API_KEY`; overlay `xai`: `transport="codex_responses"`, `base_url_override="https://api.x.ai/v1"`, `base_url_env_var="XAI_BASE_URL"`. Effort vocabulary: `XAI_GROK46_EFFORTS = (low, medium, high, xhigh)` for Grok 4.6+, `XAI_LEGACY_EFFORTS = (low, medium, high)` for older Grok. `x_search.model` default `grok-4.5`, `x_search.reasoning_effort` default `null`.
- **Edge cases / guards:** A separate identity `xai-oauth` (label "xAI Grok OAuth (SuperGrok / Premium+)") exists in `HERMES_OVERLAYS` with `auth_type="oauth_external"` and the same base URL; it is reachable via `hermes logout --provider xai-oauth` and the aliases `grok-oauth`, `x-ai-oauth`, `xai-grok-oauth`. It has no plugin-directory profile.
- **Rebuild notes:** Responses client + UA header.

### Xiaomi MiMo  `id: providers.xiaomi`
- **Surface:** Provider
- **Where:** `model.provider: xiaomi` (label "Xiaomi MiMo"); plugin `plugins/model-providers/xiaomi/`.
- **What it does:** Xiaomi's MiMo models over an OpenAI-compatible endpoint.
- **How it works:** Bare profile with two capability corrections.
- **Inputs / options:** aliases `mimo`, `xiaomi-mimo`; `base_url="https://api.xiaomimimo.com/v1"`; `supports_health_check=False` (its `/v1/models` returns 401 even with a valid key, so `hermes doctor` must skip the probe); `supports_vision=True` (mimo-v2-omni is vision-capable); `supports_vision_tool_messages=False` (rejects list-type tool content with HTTP 400 `"text is not set"`).
- **Outputs / side effects:** Doctor skips its health check.
- **Config / env:** `XIAOMI_API_KEY`; overlay `xiaomi` sets `base_url_env_var="XIAOMI_BASE_URL"`.
- **Edge cases / guards:** `mimo-v2.5-pro` on the OpenCode Go relay needs a 131072 `max_tokens` cap (see `providers.opencode-go`).
- **Rebuild notes:** Bare profile + two capability flags — the canonical example of why `supports_vision_tool_messages` exists.

### Z.AI (GLM)  `id: providers.zai`
- **Surface:** Provider
- **Where:** `model.provider: zai`; plugin `plugins/model-providers/zai/`.
- **What it does:** Zhipu AI's GLM models with correct thinking on/off and the GLM-5.2/5.3 `reasoning_effort` knob.
- **How it works:** `_model_supports_thinking(model)` (`zai/__init__.py:38-46`) parses `^glm-(\d+)(?:\.(\d+))?` and returns True for `(major, minor) >= (4, 5)`. `_is_glm_5_2(model)` (`:49-65`) matches any of `glm-5.2`, `glm-5-2`, `glm-5p2`, `glm-5.3`, `glm-5-3`, `glm-5p3` as a substring (covers relay spellings like Fireworks' `glm-5p2` and vendor prefixes like `z-ai/glm-5.2`). `_is_glm_5_3(model)` (`:68-78`) matches only the 5.3 spellings. `_glm_5_2_reasoning_effort()` (`:81-119`): returns `None` when disabled or no effort; picks `(GLM53_EFFORTS, GLM53_OVERRIDES, floor="low")` for 5.3 and `(GLM52_EFFORTS, GLM52_OVERRIDES, floor="high")` otherwise; clamps and falls back to the floor. `ZaiProfile.build_api_kwargs_extras()` (`:125-145`): bail when the model neither supports thinking nor is GLM-5.2/5.3; when a `reasoning_config` dict is present emit `extra_body["thinking"] = {"type": "enabled"|"disabled"}` (omitting it entirely when the user expressed no preference keeps the server default, which is thinking ON for GLM-4.5+); for GLM-5.2/5.3 additionally emit top-level `reasoning_effort`.
- **Inputs / options:** aliases `glm`, `z-ai`, `z.ai`, `zhipu`; `display_name="Z.AI (GLM)"`; `description="Z.AI / GLM — Zhipu AI models"`; `signup_url="https://z.ai/"`; `base_url="https://api.z.ai/api/paas/v4"`; `default_aux_model="glm-4.5-flash"`; `fallback_models=("glm-5.2", "glm-5", "glm-4-9b")`.
- **Outputs / side effects:** `{"extra_body": {"thinking": {"type": …}}}` plus optional top-level `reasoning_effort`.
- **Config / env:** `GLM_API_KEY`, `ZAI_API_KEY`, `Z_AI_API_KEY`; overlay `zai` adds all three plus `base_url_env_var="GLM_BASE_URL"`.
- **Edge cases / guards:** GLM models before 4.5 (e.g. `glm-4-9b`) do not accept `thinking` and are left untouched. GLM-5.2 has only two enabled effort levels (`high`/`max`) — it *cannot* think less than `high`; 5.3 widens to `low/medium/high/max` with monotonic reasoning-token scaling (verified live: low=4, medium=11, high=98, max=125 tokens on the probe prompt, issue #91789).
- **Rebuild notes:** Version-regex capability detection + per-version effort vocabularies. A better version would read Z.AI's own model metadata rather than parsing version numbers out of names.

### Providers reachable only through overlays / auth registry (no plugin directory)  `id: providers.overlay-only`
- **Surface:** Provider
- **Where:** `model.provider: <id>` for `openai-api`, `xai-oauth`, `lmstudio`, `local`, `tencent-tokenhub`, `tencent-tokenplan`, `moa`, `github-copilot`, `kimi-for-coding`, `vercel`, `opencode`, `kilo`.
- **What it does:** Provider identities that resolve through `HERMES_OVERLAYS` and/or the models.dev catalog without a bundled `plugins/model-providers/` directory.
- **How it works:** `get_provider()` returns a `ProviderDef` built from the overlay alone (`source="hermes"`) when models.dev has no entry.
- **Inputs / options:** `openai-api` — `transport="codex_responses"`, `base_url_override="https://api.openai.com/v1"`, `base_url_env_var="OPENAI_BASE_URL"`. `xai-oauth` — `transport="codex_responses"`, `auth_type="oauth_external"`, `base_url_override="https://api.x.ai/v1"`, `base_url_env_var="XAI_BASE_URL"`, label "xAI Grok OAuth (SuperGrok / Premium+)". `lmstudio` — `transport="openai_chat"`, `auth_type="api_key"`, `extra_env_vars=("LM_API_KEY",)`, `base_url_override="http://127.0.0.1:1234/v1"`, `base_url_env_var="LM_BASE_URL"`, label "LM Studio"; reasoning display handled by `agent/lmstudio_reasoning.py`. `local` — label "Local endpoint", the alias target for `vllm`/`llamacpp`/`llama.cpp`/`llama-cpp`. `tencent-tokenhub` — `transport="openai_chat"`, `base_url_env_var="TOKENHUB_BASE_URL"`, label "Tencent TokenHub", effort vocabulary `TOKENHUB_EFFORTS = (low, medium, high)`. `tencent-tokenplan` — `transport="anthropic_messages"`, `base_url_override="https://api.lkeap.cloud.tencent.com/plan/anthropic"`, `base_url_env_var="TOKENPLAN_BASE_URL"`, label "Tencent TokenPlan". `moa` — `transport="openai_chat"`, `auth_type="virtual"`, `base_url_override="moa://local"`, label "Mixture of Agents" (a *virtual* provider, see the MoA section).
- **Outputs / side effects:** Same `ProviderDef` shape as plugin-backed providers.
- **Config / env:** As listed above.
- **Edge cases / guards:** These have no `ProviderProfile`, so `prepare_messages` / `build_extra_body` / `build_api_kwargs_extras` hooks do not run for them — the transport uses its legacy flag path.
- **Rebuild notes:** Keep overlays for identities that need no request-shaping; promote any that grow quirks into a real plugin.

---

## 3. Wire adapters (per-protocol runtime)

### Anthropic Messages adapter  `id: providers.anthropic-adapter`
- **Surface:** Core
- **Where:** `agent/anthropic_adapter.py` (1217 lines) — used whenever `api_mode == "anthropic_messages"`.
- **What it does:** Translates Hermes's internal OpenAI-style messages into Anthropic's Messages API, builds the client (including auth-style selection), and issues the call.
- **How it works:** Lazy SDK import via `tools.lazy_deps.ensure("provider.anthropic", prompt=False)` (`:133-150`) so `anthropic` is only installed when needed. Key data:
  - `THINKING_BUDGET = {"xhigh": 32000, "high": 16000, "medium": 8000, "low": 4000}` (`:154`) — manual budget-based thinking for legacy models.
  - `ADAPTIVE_EFFORT_MAP = {"ultra": "max", "max": "max", "xhigh": "xhigh", "high": "high", "medium": "medium", "low": "low", "minimal": "low"}` (`:163-171`) — Hermes effort → Anthropic `output_config.effort`.
  - `_LEGACY_MANUAL_THINKING_CLAUDE_SUBSTRINGS` (`:194-202`): `claude-3`, `claude-opus-4-0`, `claude-opus-4.0`, `claude-opus-4-1`, `claude-opus-4.1`, `claude-sonnet-4-0`, `claude-sonnet-4.0`, `claude-opus-4-2025`, `claude-sonnet-4-2025`, `claude-opus-4-5`, `claude-opus-4.5`, `claude-sonnet-4-5`, `claude-sonnet-4.5`, `claude-haiku-4-5`, `claude-haiku-4.5`. Unknown Claude models DEFAULT to the modern adaptive contract (mirrors `_get_anthropic_max_output`'s "default to newest" design) so each new Claude release works without a code change.
  - `_NO_XHIGH_CLAUDE_SUBSTRINGS` (`:207-210`): `claude-opus-4-6`, `claude-opus-4.6`, `claude-sonnet-4-6`, `claude-sonnet-4.6`.
  - `_MANDATORY_THINKING_CLAUDE_SUBSTRINGS = ("claude-fable",)` (`:219-221`) — families that answer `thinking:{"type":"disabled"}` with HTTP 400. Failure is asymmetric (a missing entry 400s the turn; a spurious one only leaves thinking on), so "when in doubt, add the family".
  - `_FAST_MODE_SUPPORTED_SUBSTRINGS = ("opus-4-6", "opus-4.6")` (`:228`) — Anthropic Fast Mode (`speed: "fast"`, ~2.5× output throughput) is Opus 4.6 only; any other model 400s.
  - `_ANTHROPIC_OUTPUT_LIMITS` (`:234-267`), longest-substring match with dots normalised to hyphens: `claude-fable` 128000, `claude-sonnet-5` 128000, `claude-opus-4-8` 128000, `claude-opus-4-7` 128000, `claude-opus-4-6` 128000, `claude-sonnet-4-6` 64000, `claude-opus-4-5` 64000, `claude-sonnet-4-5` 64000, `claude-haiku-4-5` 64000, `claude-opus-4` 32000, `claude-sonnet-4` 64000, `claude-3-7-sonnet` 128000, `claude-3-5-sonnet` 8192, `claude-3-5-haiku` 8192, `claude-3-opus` 4096, `claude-3-sonnet` 4096, `claude-3-haiku` 4096, `minimax` 131072, `qwen3` 65536 (DashScope enforces `max_tokens ∈ [1, 65536]`). `_ANTHROPIC_DEFAULT_OUTPUT_LIMIT = 128_000` (`:271`).
  - Beta headers: `_COMMON_BETAS = ["interleaved-thinking-2025-05-14", "fine-grained-tool-streaming-2025-05-14"]` (`:459-462`); `_TOOL_STREAMING_BETA = "fine-grained-tool-streaming-2025-05-14"` (stripped for MiniMax, which fails tool-use requests when present); `_CONTEXT_1M_BETA = "context-1m-2025-08-07"` (deliberately NOT in `_COMMON_BETAS` — native Anthropic returns HTTP 400 "long context beta is not yet available for this subscription" for accounts without it; added only for Bedrock/Azure paths that need 1M context on Opus 4.6/4.7 and Sonnet 4.6); `_FAST_MODE_BETA = "fast-mode-2026-02-01"`; `_OAUTH_ONLY_BETAS = ["claude-code-20250219", "oauth-2025-04-20"]`.
  - Claude Code identity for OAuth traffic: `_CLAUDE_CODE_VERSION_FALLBACK = "2.1.74"` (`:487`), detected at runtime by running `claude --version` / `claude-code --version` with a 5 s timeout (`_detect_claude_code_version`, `:491-513`) and cached (`_get_claude_code_version`, `:520-525`). Anthropic rejects OAuth requests whose spoofed UA version is too far behind the real release. `_CLAUDE_CODE_SYSTEM_PREFIX = "You are Claude Code, Anthropic's official CLI for Claude."` and `_MCP_TOOL_PREFIX = "mcp__"` (`:516-517`).
  - Predicates: `_supports_adaptive_thinking` (Kimi family always True; non-Claude False; Claude True unless in the legacy list), `_supports_xhigh_effort`, `_accepts_thinking_disable` (Claude-only, adaptive, not in the mandatory list), `_forbids_sampling_params` (Opus 4.7+ 400s on any non-default temperature/top_p/top_k; 4.6 and legacy families still accept them), `_supports_fast_mode`.
  - `sanitize_anthropic_kwargs()` (`:1099`) strips `_RESPONSES_ONLY_KWARGS` (`:1094`). `_is_stream_unavailable_error()` (`:1131`) drives the non-stream fallback in `create_anthropic_message()` (`:1143`).
- **Inputs / options:** `build_anthropic_client()` (`:643`), `build_anthropic_bedrock_client(region)` (`:799`), `build_anthropic_kwargs()` (`:840`), `create_anthropic_message()` (`:1143`), `_build_anthropic_client_with_bearer_hook()` (`:563`), `_common_betas_for_base_url()` (`:531`).
- **Outputs / side effects:** HTTP calls to the Messages API; beta headers per endpoint family.
- **Config / env:** `ANTHROPIC_API_KEY`, `ANTHROPIC_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN`; `model.max_tokens`; `model.auth_mode`.
- **Edge cases / guards:** `_resolve_positive_anthropic_max_tokens()` (`:295`) floors `max_tokens` to a positive int — the API rejects 0, negative, non-integer or non-finite values with HTTP 400 (ported from openclaw#66664).
- **Rebuild notes:** A translation layer keyed on model family + endpoint family, with "default to the newest contract" for unknown model names. A better version would negotiate capabilities from Anthropic's `/v1/models` response instead of substring tables.

### Anthropic endpoint-family predicates  `id: providers.anthropic-endpoints`
- **Surface:** Core
- **Where:** `agent/anthropic_endpoints.py` (258 lines); re-exported from `agent/anthropic_adapter.py`.
- **What it does:** Pure functions over a base-URL string that decide auth style, accepted beta headers and request quirks for the dozen services speaking the Anthropic Messages API.
- **How it works:** No I/O, no SDK, no credentials — which is what lets both the adapter and the message converter import it without a cycle. Functions:
  - `_normalize_base_url_text(base_url)` (`:22-30`) — coerces `httpx.URL` or `str` to a stripped string.
  - `_is_third_party_anthropic_endpoint()` (`:33-46`) — False when empty (direct Anthropic) or when `"anthropic.com"` appears; True otherwise. OAuth detection is skipped for third-party proxies.
  - `_is_kimi_coding_endpoint()` (`:49-54`) — starts with `https://api.kimi.com/coding`.
  - `_is_opencode_endpoint()` (`:57-59`) — host matches `opencode.ai`.
  - `_KIMI_FAMILY_MODEL_PREFIXES = ("kimi-", "kimi_", "moonshot-", "moonshot_", "k1.", "k1-", "k2.", "k2-", "k25", "k2.5", "k3.", "k3-")` (`:69-76`); `_KIMI_FAMILY_EXACT_SLUGS = frozenset({"k3"})` (`:81`); `_model_name_is_kimi_family()` (`:84-95`) strips a vendor prefix then exact-matches or prefix-matches.
  - `_is_kimi_family_endpoint(base_url, model)` (`:98-123`) — the `/coding` URL, any `api.kimi.com` / `moonshot.ai` / `moonshot.cn` host, **or** a Kimi-family model name (so a private gateway fronting Kimi still gets Kimi's thinking semantics — hermes-agent#13848, #17057).
  - `_is_deepseek_anthropic_endpoint()` (`:126-150`) — host `api.deepseek.com` AND path contains `/anthropic`; DeepSeek's thinking blocks are unsigned and must round-trip or the API returns `The content[].thinking in the thinking mode must be passed back to the API` (#16748).
  - `_is_nous_portal_endpoint()` (`:153-182`) — host `inference-api.nousresearch.com` or an exact-host match against the operator's `NOUS_INFERENCE_BASE_URL` override; lookalikes like `inference-api.nousresearch.com.attacker.test` are rejected.
  - `_requires_bearer_auth()` (`:185-212`) — True for Nous Portal, `https://api.minimax.io/anthropic`, `https://api.minimaxi.com/anthropic`, any URL containing `azure.com`, host `palantirfoundry.com` (its LLM proxy rejects `x-api-key` with 401), and host `api.commandcode.ai`.
  - `_base_url_needs_context_1m_beta()` (`:215-220`) — True when the URL contains `azure.com`.
  - `_is_minimax_anthropic_endpoint()` (`:223-235`) — MiniMax rejects the fine-grained-tool-streaming and context-1m betas.
  - `_is_azure_anthropic_endpoint()` (`:238-258`) — host contains `.services.ai.azure.` (Foundry) or `.openai.azure.` (legacy Azure OpenAI) AND path contains `/anthropic`; deliberately avoids a finite TLD allow-list so sovereign/private Azure clouds work. Opts the host into `api-version` query-param plumbing.
- **Inputs / options:** base URL string (or `httpx.URL`), optional model name.
- **Outputs / side effects:** Booleans only.
- **Config / env:** `NOUS_INFERENCE_BASE_URL` (via `hermes_cli.auth._nous_inference_env_override`).
- **Edge cases / guards:** All host comparisons go through `utils.base_url_host_matches` (exact-or-dot-suffix, userinfo/port stripped, lowercased, trailing dot removed).
- **Rebuild notes:** A pure predicate module keyed on host + path. A better version would be table-driven (host pattern → capability record) rather than a function per vendor.

### Anthropic credential sources, OAuth & refresh  `id: providers.anthropic-credentials`
- **Surface:** Core
- **Where:** `agent/anthropic_credentials.py` (1124 lines); re-exported from `agent/anthropic_adapter.py`.
- **What it does:** Owns *where an Anthropic credential comes from* and *how a rotated one is committed*, including Hermes's own PKCE OAuth login against a Claude Pro/Max subscription.
- **How it works:** `resolve_anthropic_token()` (`:789-844`) priority: (1) `ANTHROPIC_TOKEN`; (2) `CLAUDE_CODE_OAUTH_TOKEN`; (3) `ANTHROPIC_API_KEY` (an explicit user key must not be shadowed by auto-discovered credentials); (4) Claude Code credentials (`~/.claude.json` or `~/.claude/.credentials.json`, plus the macOS Keychain reader `_read_claude_code_credentials_from_keychain`, `:265`) with automatic refresh when expired; (5) the Anthropic OAuth entry in the credential pool (`~/.hermes/auth.json`). For (1) and (2) `_prefer_refreshable_claude_code_token()` (`:707`) upgrades a static env token to a refreshable Claude Code credential when one exists. Sources 3 and 4 are *singletons*: `credential_pool._seed_from_singletons()` re-reads them on every `load_pool()` and writes what it finds over the pool row, so a failed write here is a failed refresh (`CredentialPersistError`, `:85`) rather than a best-effort cache miss.
  **Hermes PKCE OAuth** (`run_hermes_oauth_login_pure()`, `:933`): `_OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"`; authorize URL `https://claude.ai/oauth/authorize?` with params `code=true`, `client_id`, `response_type=code`, `redirect_uri=https://console.anthropic.com/oauth/code/callback`, `scope=org:create_api_key user:profile user:inference`, `code_challenge` (S256 of a 32-byte urlsafe verifier), `code_challenge_method=S256`, `state` (32-byte urlsafe). Token endpoints tried in order: `https://platform.claude.com/v1/oauth/token`, then `https://console.anthropic.com/v1/oauth/token` (console now 404s). The token-endpoint User-Agent is `axios/1.7.9` — Anthropic rate-limits (HTTP 429) any token-endpoint request whose UA starts with `claude-code/` (verified: `claude-code/2.1.200` and `Mozilla/5.0` → 429; `axios/*`, `node`, SDK-style UAs → 400, i.e. they reach code validation). The *inference* path still uses the `claude-code/` UA + `x-app: cli`, which is required there and is not throttled on the messages API. Credentials land in `~/.hermes/.anthropic_oauth.json` (`_get_hermes_oauth_file`, `:916`).
  **Spent-rotation sidecar** (`:130-263`): `_SPENT_ROTATION_SIDECAR_VERSION = 1`, `_SPENT_ROTATION_MAX_TRACKED = 64`, guarded by `_SPENT_ROTATION_LOCK`. `mark_rotation_consumed_uncommitted()` / `is_rotation_consumed_uncommitted()` record fingerprints of refresh tokens that were exchanged but whose new value could not be committed, so the same one-time refresh token is never replayed.
- **Inputs / options:** `read_claude_code_credentials()`, `is_claude_code_token_valid(creds)`, `refresh_anthropic_oauth_pure(refresh_token, *, use_json=False)`, `run_oauth_setup_token()` (runs `claude setup-token` interactively), `read_hermes_oauth_credentials()`, `_write_claude_code_credentials()`, `_write_hermes_oauth_credentials()`.
- **Outputs / side effects:** Writes `~/.hermes/.anthropic_oauth.json` and `~/.claude/.credentials.json` (mode-restricted via `stat`), plus the sidecar file next to whichever credential file is being rotated.
- **Config / env:** `ANTHROPIC_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY`.
- **Edge cases / guards:** `_is_oauth_token(key)` (`:56`) distinguishes `sk-ant-oat*` OAuth setup tokens (→ Bearer + beta header) from `sk-ant-api*` keys (→ `x-api-key`). Token reads go through `agent.secret_scope.get_secret` so scoped secrets apply.
- **Rebuild notes:** Ordered credential resolution + PKCE login + a replay-guard sidecar for one-time refresh tokens. A better version would put all five sources behind one pluggable `CredentialSource` interface with explicit precedence config.

### Anthropic message conversion  `id: providers.anthropic-message-convert`
- **Surface:** Core
- **Where:** `agent/anthropic_message_convert.py` (1225 lines); re-exported from `agent/anthropic_adapter.py`.
- **What it does:** Converts OpenAI-shaped messages and tool definitions into Anthropic Messages payloads and back, including thinking-block handling and cache breakpoints.
- **How it works:** Public entry points `convert_messages_to_anthropic()` and `convert_tools_to_anthropic()`. Internal helpers (all re-exported): `_EMPTY_TEXT_PLACEHOLDER`, `_apply_assistant_cache_control_to_last_cacheable_block`, `_content_parts_to_anthropic_blocks`, `_convert_assistant_message`, `_convert_content_part_to_anthropic`, `_convert_content_to_anthropic`, `_convert_tool_message_to_result`, `_convert_user_message`, `_ensure_leading_user_turn`, `_evict_old_screenshots`, `_extract_preserved_thinking_blocks`, `_fix_blank_text_blocks_in_list`, `_image_source_from_openai_url`, `_is_bedrock_model_id`, `_manage_thinking_signatures`, `_merge_consecutive_roles`, `_normalize_tool_input_schema`, `_safe_text`, `_sanitize_replay_block`, `_sanitize_tool_id`, `_scrub_blank_text_blocks`, `_strip_orphaned_tool_blocks`, `_to_plain_data`.
- **Inputs / options:** OpenAI-style `messages` list, tool definitions, endpoint-family flags from `anthropic_endpoints`.
- **Outputs / side effects:** Anthropic `messages` + `system` + `tools` payloads.
- **Config / env:** n/a.
- **Edge cases / guards:** Anthropic requires the first turn to be `user` (`_ensure_leading_user_turn`); blank text blocks are rejected (`_scrub_blank_text_blocks`, `_fix_blank_text_blocks_in_list`, `_EMPTY_TEXT_PLACEHOLDER`); consecutive same-role turns must be merged (`_merge_consecutive_roles`); tool_use blocks with no matching tool_result must be stripped (`_strip_orphaned_tool_blocks`); signed thinking blocks are stripped on third-party endpoints while unsigned ones are preserved for Kimi/DeepSeek (`_manage_thinking_signatures`, `_sanitize_replay_block`, `_extract_preserved_thinking_blocks`); old screenshots are evicted to bound payload size (`_evict_old_screenshots`).
- **Rebuild notes:** A per-role converter plus a set of well-named repair passes run in a fixed order. A better version would validate the produced payload against Anthropic's published request schema before sending.

### Codex identity headers  `id: providers.codex-headers`
- **Surface:** Core
- **Where:** `agent/codex_headers.py` (92 lines) — a deliberately dependency-free leaf module so long-lived processes can import a new client builder without resolving a new symbol from a stale cached `auxiliary_client`.
- **What it does:** Builds the identity and account headers OpenAI requires from third-party harnesses hitting `chatgpt.com/backend-api/codex`, and re-applies them after user/provider header overrides.
- **How it works:** `CODEX_AUX_BASE_URL = "https://chatgpt.com/backend-api/codex"` (`:16`). `is_official_codex_base_url()` (`:19-31`) requires scheme `https`, hostname exactly `chatgpt.com`, port in `(None, 443)`, and path exactly `/backend-api/codex` or a sub-path of it. `codex_cloudflare_headers(access_token, *, base_url)` (`:34-73`) starts from `{"User-Agent": "codex_cli_rs/0.0.0 (Hermes Agent)", "originator": "codex_cli_rs"}` (the compatibility identity kept for custom endpoints) and, on the official endpoint, replaces them with `{"User-Agent": "HermesAgent/<version>", "originator": "hermes-agent"}`. It then base64url-decodes the JWT payload (padding it to a multiple of 4) and, when `claims["https://api.openai.com/auth"]["chatgpt_account_id"]` is a non-empty string, adds `ChatGPT-Account-ID`. Malformed tokens are tolerated — the account-ID header is dropped rather than raising, so a bad token surfaces as a 401 instead of a crash at client construction. `apply_required_codex_headers(client_kwargs, *, access_token, base_url)` (`:76-92`) is a no-op off the official endpoint; on it, it removes any case-insensitively-matching existing header and merges the required set back on top.
- **Inputs / options:** `access_token`, `base_url`, `client_kwargs` dict.
- **Outputs / side effects:** Mutates `client_kwargs["default_headers"]`.
- **Config / env:** n/a.
- **Edge cases / guards:** Custom proxies keep the compatibility identity so they are not fingerprinted as Hermes.
- **Rebuild notes:** URL predicate + JWT claim extraction + header re-application. A better version would verify the JWT signature rather than decoding the payload blindly.

### Codex Responses adapter & runtime  `id: providers.codex-responses`
- **Surface:** Core
- **Where:** `agent/codex_responses_adapter.py` (1896 lines) and `agent/codex_runtime.py` (1858 lines); active for `api_mode == "codex_responses"` (OpenAI Codex, OpenAI API, xAI, Ramp Router, Meta AI, Actual).
- **What it does:** Speaks OpenAI's Responses API: request construction, SSE streaming, reasoning summaries, encrypted reasoning replay, prompt-cache keys, and the codex app-server projection path.
- **How it works:** The adapter builds `/v1/responses` payloads (`store`, `prompt_cache_key`, `include: ["reasoning.encrypted_content"]`, `reasoning.summary`, `parallel_tool_calls`, tools) and consumes the SSE event stream. `_cache_scope_from_session_id()` (imported by the Nous and OpenRouter profiles) derives the sticky cache scope from a session id. Effort clamping uses `agent.reasoning_effort.codex_supported_efforts(model)` unless the profile declares `supported_reasoning_efforts()` (Ramp Router). `agent/codex_runtime.py` owns the codex app-server path, whose already-executed tool work is folded back into Hermes's turn state by `agent/provider_projection.py`.
- **Inputs / options:** Request kwargs mirroring the Responses API; `_RESPONSES_ONLY_KWARGS` marks fields the Anthropic sanitizer must strip when a session switches wires.
- **Outputs / side effects:** Streams reasoning summaries and tool calls; may return `hermes_projected_messages` / `hermes_provider_tool_iterations`.
- **Config / env:** `compression.codex_gpt55_autoraise` (`true`), `compression.codex_gpt55_autoraise_notice` (`true`), `compression.codex_app_server_auto` (`"native"`), `compression.codex_responses_native` (`false`), `compression.codex_responses_compact_threshold` (`null`).
- **Edge cases / guards:** `minimal` is rejected by every Codex generation and clamps to `low`; `max` is `gpt-5.6`-only (gpt-5.5 answers `"Supported values are: 'none', 'low', 'medium', 'high', 'xhigh'"`).
- **Rebuild notes:** Responses-API client with SSE parsing and encrypted-reasoning round-tripping. A better version would expose the reasoning-summary stream as a first-class typed event rather than free text.

### Provider projection (agent-as-provider)  `id: providers.provider-projection`
- **Surface:** Core
- **Where:** `agent/provider_projection.py` (70 lines) — `splice_provider_projection(agent, response, messages)`.
- **What it does:** Folds an agent-shaped provider's own completed tool work back into Hermes's transcript and nudge counters, so Hermes never re-runs finished work but the self-improvement loop and skill-review nudge still see it.
- **How it works:** Some providers are *agents*, not models — an ACP CLI reached through a client shim, or the codex app-server — and by the time Hermes sees the response their read/edit/execute tools have already run inside their own session. Those calls must never come back as pending `tool_calls`. The provider client therefore hands back two attributes on the completion object: `hermes_projected_messages` (already-completed `assistant(tool_calls=[…])` + `tool(result)` history rows) and `hermes_provider_tool_iterations` (an int). `splice_provider_projection` appends every dict row via `agent.message_metadata.append_message` (so they carry a timestamp and persist like any live-transcript append), logs `"spliced %d provider-projected transcript row(s) from %s"` at DEBUG, and adds the iteration count to `agent._iters_since_skill`. It returns the number of rows spliced and tolerates absent/garbage attributes so a third-party OpenAI-compatible client cannot break the turn.
- **Inputs / options:** `agent`, `response`, `messages`.
- **Outputs / side effects:** Appends transcript rows; bumps `_iters_since_skill`.
- **Config / env:** n/a.
- **Edge cases / guards:** Non-list `hermes_projected_messages` yields zero rows; a non-integer iteration count is coerced to 0.
- **Rebuild notes:** Two optional response attributes + an append-only splice. A better version would type these as a formal `ProviderProjection` object rather than duck-typed attributes.

### AWS Bedrock adapter  `id: providers.bedrock-adapter`
- **Surface:** Core
- **Where:** `agent/bedrock_adapter.py` (1948 lines); active for `api_mode == "bedrock_converse"`.
- **What it does:** Runs the Converse / ConverseStream API through boto3, including model discovery, guardrails and cross-region inference profiles.
- **How it works:** Uses the AWS SDK credential chain (no API key). Model discovery is gated by `bedrock.discovery.*`; guardrails are applied per request from `bedrock.guardrail.*`.
- **Inputs / options:** `bedrock.region`, `bedrock.discovery.enabled`, `bedrock.discovery.provider_filter`, `bedrock.discovery.refresh_interval`, `bedrock.guardrail.guardrail_identifier`, `bedrock.guardrail.guardrail_version`, `bedrock.guardrail.stream_processing_mode`, `bedrock.guardrail.trace`.
- **Outputs / side effects:** AWS API calls; `build_anthropic_bedrock_client(region)` in `agent/anthropic_adapter.py:799` provides the Anthropic-SDK-on-Bedrock path for Claude models.
- **Config / env:** the eight `bedrock.*` keys above (defaults `""`, `true`, `[]`, `3600`, `""`, `""`, `"async"`, `"disabled"`), plus the standard AWS environment.
- **Edge cases / guards:** `_is_bedrock_model_id()` in the message converter recognises Bedrock's ARNs/inference-profile ids; the 1M-context beta must be added explicitly for Bedrock-served Claude 4.6/4.7.
- **Rebuild notes:** boto3 Converse client + discovery cache + guardrail plumbing.

### Vertex AI adapter  `id: providers.vertex-adapter`
- **Surface:** Core
- **Where:** `agent/vertex_adapter.py` (318 lines).
- **What it does:** Mints and caches short-lived OAuth2 access tokens for Vertex AI and builds the OpenAI-compatible base URL.
- **How it works:** Lazily installs `google-auth` via `tools.lazy_deps.ensure("provider.vertex", prompt=False)` (the `[vertex]` extra left `[all]` on 2026-05-12 under the lazy-install policy). `get_vertex_credentials(credentials_path)` (`:154`) resolves a service-account JSON or falls back to ADC; `_sa_snapshot()` / `_read_sa_file()` hash the SA file so `_creds_cache` invalidates when it changes. `build_vertex_base_url(project_id, region)` (`:257-267`): host is `aiplatform.googleapis.com` for `region == "global"` and `{region}-aiplatform.googleapis.com` otherwise; the URL is `https://{host}/v1beta1/projects/{project_id}/locations/{region}/endpoints/openapi` — Gemini 3.x preview models are only served via the global endpoint. `get_vertex_config()` (`:269`) returns `(access_token, base_url)` or `(None, None)`.
- **Inputs / options:** `credentials_path`, `region`.
- **Outputs / side effects:** Token cache in-process (`_creds_cache`).
- **Config / env:** `GOOGLE_APPLICATION_CREDENTIALS` (service-account JSON path, treated as a secret), `VERTEX_CREDENTIALS_PATH` (alias, takes precedence), `VERTEX_PROJECT_ID`, `VERTEX_REGION`; config.yaml `vertex.project_id` (`""`), `vertex.region` (`"global"`). Env wins over config.yaml. `DEFAULT_REGION = "global"` (`:47`).
- **Edge cases / guards:** `has_vertex_credentials()` (`:283`) is a no-network, no-import fast check (True when an SA path resolves or an explicit project id is configured, implying ADC); `has_explicit_vertex_config()` (`:298`) is stricter — True only when the user deliberately pointed Hermes at Vertex. Secret reads go through `agent.secret_scope` and respect `is_multiplex_active`.
- **Rebuild notes:** ADC/SA token minting with a file-hash-keyed cache + a region-aware URL builder.

### Microsoft Entra ID adapter (Azure Foundry keyless auth)  `id: providers.azure-identity-adapter`
- **Surface:** Core
- **Where:** `agent/azure_identity_adapter.py` (571 lines); engaged when `model.auth_mode = entra_id`.
- **What it does:** Keyless authentication for Microsoft Foundry using `azure-identity`'s `DefaultAzureCredential` chain, handing the OpenAI SDK a zero-arg token callable so refresh is transparent.
- **How it works:** Lazy import (`_AZURE_IDENTITY_FEATURE = "provider.azure_identity"`, `:57`) so users on `AZURE_FOUNDRY_API_KEY` never pay the cost. `SCOPE_AI_AZURE_DEFAULT = "https://ai.azure.com/.default"` (`:51`) — Microsoft's documented Foundry inference audience for ALL endpoint shapes (`*.openai.azure.com`, `*.services.ai.azure.com`, `*.ai.azure.com`); the older control-plane scope `https://cognitiveservices.azure.com/.default` is for ARM resource management and is rejected for inference by newer resources. `EntraIdentityConfig` (`:123-171`) is a frozen dataclass (hashable for `functools.lru_cache`, serialisable across multiprocessing boundaries so workers rebuild the credential in their own process) with fields `scope: str = SCOPE_AI_AZURE_DEFAULT` and `exclude_interactive_browser: bool = True` (an internal constructor knob so probes stay non-interactive; the setup wizard never writes it), plus `to_dict()` / `from_dict()`. `build_token_provider(scope, …)` (`:215`) returns the callable from `get_bearer_token_provider` — exactly the value Microsoft's sample plugs into `OpenAI(api_key=token_provider, base_url=…)`. Three purpose-split consumer helpers avoid accidental token-minting in logging paths or token leakage into cache keys / dashboard JSON: `describe_active_credential()` (`:315`, display), `has_azure_identity_credentials()` (`:261`, cache/probe), `materialize_bearer_for_http()` (`:449`, http-bearer). `is_token_provider(value)` (`:440`) and `build_bearer_http_client(token_provider, **httpx_kwargs)` (`:478`) complete the surface. `reset_credential_cache()` (`:104`) clears the memoised credential.
- **Inputs / options:** The DefaultAzureCredential chain order is env service principal → workload identity → managed identity → VS Code → Azure CLI → azd → PowerShell → broker.
- **Outputs / side effects:** No persisted JWT — `azure-identity` caches in-process and (where available) in the OS keychain or `~/.IdentityService`; Hermes does not duplicate that in `auth.json`.
- **Config / env:** `model.auth_mode = entra_id`; `model.entra.scope` overrides the audience for sovereign / non-standard tenants; identity selection stays in the standard Azure SDK env vars (`AZURE_CLIENT_ID`, tenant, authority, federated token file, service-principal secret…).
- **Edge cases / guards:** `_require_azure_identity()` (`:72`) raises a clear feature-unavailable error when the optional dependency is missing.
- **Rebuild notes:** SDK token-provider callable + a frozen config + three purpose-split accessors. Architecture deliberately mirrors `agent/bedrock_adapter.py`.

### Gemini native adapter  `id: providers.gemini-native-adapter`
- **Surface:** Core
- **Where:** `agent/gemini_native_adapter.py` (1274 lines), with `agent/gemini_schema.py` for tool-schema translation.
- **What it does:** A custom native Gemini client that bypasses the standard OpenAI transport, used by the `gemini` provider.
- **How it works:** Translates Hermes messages to Gemini `contents`/`parts`, tools to `functionDeclarations` (schema sanitised by `agent/gemini_schema.py`, which strips JSON-Schema constructs Gemini rejects), and reasoning to `thinking_config`. The profile-level translation shape is decided by `GeminiProfile.build_extra_body()` (see `providers.gemini`).
- **Inputs / options:** model, messages, tools, `thinking_config`.
- **Outputs / side effects:** HTTP calls to `generativelanguage.googleapis.com/v1beta`.
- **Config / env:** `GOOGLE_API_KEY`, `GEMINI_API_KEY`.
- **Edge cases / guards:** `_is_gemini_openai_compat_base_url()` distinguishes the native surface from the `/openai` compatibility subpath (which needs snake_cased `thinking_config` nested under `extra_body.google`).
- **Rebuild notes:** Native client + schema sanitiser + two thinking-config shapes.

### Copilot ACP client  `id: providers.copilot-acp-client`
- **Surface:** Core
- **Where:** `agent/copilot_acp_client.py` (678 lines); paired with `agent/acp_openai_bridge.py` and the `hermes acp` CLI.
- **What it does:** Drives an external Agent Client Protocol subprocess (GitHub Copilot CLI) and presents it to Hermes as an OpenAI-compatible client.
- **How it works:** Spawns the ACP process, speaks JSON-RPC over stdio, and returns completions carrying `hermes_projected_messages` / `hermes_provider_tool_iterations` so the already-executed tool work is spliced into the transcript by `agent/provider_projection.py`.
- **Inputs / options:** subprocess path/args; `COPILOT_ACP_BASE_URL` (overlay `base_url_env_var`).
- **Outputs / side effects:** Child process lifecycle; transcript projection.
- **Config / env:** `auth_type="external_process"` — credentials are managed by the subprocess.
- **Edge cases / guards:** `fetch_models()` returns `None`, so the picker cannot list ACP models.
- **Rebuild notes:** stdio JSON-RPC bridge + a projection contract. A better version would surface the subprocess's model list and per-tool approval prompts natively.

---

## 4. Model catalog, metadata and pricing

### Remote model catalog manifest  `id: providers.model-catalog-manifest`
- **Surface:** Docs / Config
- **Where:** Documented at `website/docs/reference/model-catalog.md`; implemented in `hermes_cli/model_catalog.py` (471 lines); source of truth `website/static/api/model-catalog.json`; live at `https://hermes-agent.nousresearch.com/docs/api/model-catalog.json`.
- **What it does:** Lets maintainers update the curated picker lists for **OpenRouter** and **Nous Portal** (and the silent default model) without shipping a new `hermes-agent` release.
- **How it works:** `get_catalog(*, force_refresh=False)` (`:268`) resolves in-process cache → disk cache at `~/.hermes/cache/model_catalog.json` → network fetch. `_fetch_manifest_with_fallback()` (`:152`) tries `DEFAULT_CATALOG_URL` then `DEFAULT_CATALOG_FALLBACK_URLS = ("https://raw.githubusercontent.com/NousResearch/hermes-agent/main/website/static/api/model-catalog.json",)` — the Docusaurus site is served through Vercel, which occasionally returns HTTP 403 + `x-vercel-mitigated: challenge` for non-browser clients (urllib, curl), and the raw GitHub URL is the same manifest and is not bot-gated. `_validate_manifest()` (`:177`) enforces `SUPPORTED_SCHEMA_VERSION = 1`; a manifest failing validation is treated as unreachable. `_write_disk_cache()` (`:220`) uses `utils.atomic_replace`. Stale-while-revalidate: `_spawn_catalog_swr_refresh(url)` (`:240-260`) starts one deduped daemon thread named `model-catalog-swr`. `seed_cache_from_checkout(project_root)` (`:436`) lets `hermes update` overwrite the disk cache straight from the freshly-pulled `website/static/api/model-catalog.json` with no network round-trip.
- **Inputs / options:** Manifest schema v1: top-level `version` (int), `updated_at` (ISO8601), `metadata` (free-form dict); `providers.<id>.metadata` (free-form); `providers.<id>.models[]` entries `{id, description, default, metadata}`. `description` is **OpenRouter-only** and drives the picker badge text (`"recommended"`, `"free"`, `"default"`, or empty); Nous Portal free-tier gating is determined live from the Portal's pricing endpoint. Exactly one entry per provider may carry `"default": true` — the **silent default**, i.e. what Hermes lands on when the user never selected a model (GUI onboarding confirm card, provider configured with no model, empty `model.default`); it is deliberately a capable low-cost model, never the priciest flagship. Pricing and context length are NOT in the manifest — those come from live provider APIs and models.dev at fetch time. Accessors: `get_curated_openrouter_models()` → `list[(id, description)]|None` (`:365`), `get_curated_nous_models()` → `list[str]|None` (`:384`), `get_default_model_from_cache(provider)` (`:412`, **cache-only, never network** — safe on hot resolution paths such as agent build and gateway session setup), `reset_cache()` (`:467`, used by tests and `hermes model --refresh`).
- **Outputs / side effects:** `~/.hermes/cache/model_catalog.json`; one background refresh thread.
- **Config / env:** `model_catalog.enabled` (default `true`; `false` disables remote fetch entirely and always uses the in-repo snapshot), `model_catalog.url` (default `https://hermes-agent.nousresearch.com/docs/api/model-catalog.json`), `model_catalog.ttl_hours` (default `1`), `model_catalog.providers` (per-provider override URLs — third parties can self-host a curation list using the same schema; the overriding manifest only needs the provider blocks it cares about), `model_catalog.excluded_providers` (list; hides providers from every `/model` picker surface — the gateway interactive/text pickers, the TUI picker and the interactive `hermes model` CLI picker — even when valid credentials exist; matched case-insensitively against the Hermes id, the models.dev id, the overlay pid, the resolved Hermes slug and the canonical slug, so a single entry like `copilot` hides the provider regardless of which section emits it; an empty list or omitting the key has no effect). Constants: `DEFAULT_TTL_HOURS = 1`, `DEFAULT_FETCH_TIMEOUT = 8.0`, UA `hermes-cli/<version>`.
- **Edge cases / guards:** Fetch behaviour table (from the doc, verbatim rows): `/model` or `hermes model` → fetches if disk cache is stale, else uses cache; disk cache fresh (< TTL) → no network hit; network failure with cache → silent fallback to cache, one log line; network failure, no cache → silent fallback to in-repo snapshot; manifest fails schema validation → treated as unreachable. When no cached manifest exists, `PREFERRED_SILENT_DEFAULT_MODEL` (the in-repo constant, which must match the labelled entry) is used.
- **Rebuild notes:** A versioned JSON manifest + TTL disk cache + SWR refresh + a raw-GitHub fallback URL. Maintainers regenerate with `python scripts/build_model_catalog.py` (keeps the manifest in sync after editing `OPENROUTER_MODELS` / `_PROVIDER_MODELS["nous"]` in `hermes_cli/models.py`) and PR the result. A better version would sign the manifest and let each provider plugin ship its own curation block.

### models.dev registry integration  `id: providers.models-dev`
- **Surface:** Core
- **Where:** `agent/models_dev.py` (1550 lines).
- **What it does:** The primary database for provider and model metadata — 4000+ models across 109+ providers fetched from `https://models.dev/api.json`.
- **How it works:** Resolution order: (1) in-memory cache (fresh, or stale served immediately while a single background daemon thread refreshes); (2) disk cache `~/.hermes/models_dev_cache.json` of **any** age (stale data is served rather than blocking callers on the network); (3) network fetch, only when no cache exists at all — failed refreshes back off for 5 minutes process-wide. `MODELS_DEV_URL = "https://models.dev/api.json"`, `_MODELS_DEV_CACHE_TTL = 4*3600`, `_MODELS_DEV_RETRY_DELAY = 300`. Network hardening: **ETag conditional GET** (`If-None-Match` from `_load_etag()`; a 304 re-confirms the cache without re-downloading ≈2 MB; the ETag is persisted atomically alongside the cache — `_save_etag`, `_clear_etag`, `_NotModified`, `_confirm_cache_not_modified`); a **no-network-on-hot-paths invariant** with `allow_network=False` threaded through every query function and passed explicitly by vision routing, image routing, the cost guard and context-length lookup; **corrupt-cache rejection** (`_validate_registry`, `_quarantine_corrupt_cache`) — a disk cache that fails to parse, is not a dict, or is empty is ignored with a warning rather than served as `{}`; and a **mirror URL override** so deployments can point at a self-hosted copy.
- **Inputs / options:** `ModelInfo` dataclass fields (`:74-148`): `id`, `name`, `family`, `provider_id`; capabilities `reasoning`, `tool_call`, `attachment`, `temperature`, `structured_output`, `open_weights`; modalities `input_modalities`, `output_modalities`; limits `context_window`, `max_output`, `max_input`; cost per million USD `cost_input`, `cost_output`, `cost_cache_read`, `cost_cache_write`; metadata `knowledge_cutoff`, `release_date`, `status` (`"alpha"`/`"beta"`/`"deprecated"`/`""`), `interleaved` (True or `{"field": "reasoning_content"}`). Methods `has_cost_data()`, `supports_vision()` (attachment OR `"image"` in input modalities), `supports_pdf()`, `supports_audio_input()`, `format_cost()` (`"$3.00/M in, $15.00/M out"` + optional `"cache read $X/M"`), `format_capabilities()` (joins any of `reasoning`, `tools`, `vision`, `PDF`, `audio`, `structured output`, `open weights`; `"basic"` when none). `ProviderInfo` (`:153-160`): `id`, `name`, `env` (tuple of env var names), `api` (base URL), `doc`, `model_count`.
- **Outputs / side effects:** `~/.hermes/models_dev_cache.json` + an ETag sidecar; one background refresh thread.
- **Config / env:** `models_dev.url` (default `""` → the canonical URL).
- **Edge cases / guards:** `PROVIDER_TO_MODELS_DEV` (`:172-212`) maps Hermes ids to models.dev ids: `openrouter→openrouter`, `novita→novita-ai`, `anthropic→anthropic`, `openai→openai`, `openai-codex→openai`, `zai→zai`, `kimi→kimi-for-coding`, `kimi-coding→kimi-for-coding`, `moonshot→kimi-for-coding`, `stepfun→stepfun`, `kimi-coding-cn→kimi-for-coding`, `minimax→minimax`, `minimax-oauth→minimax`, `minimax-cn→minimax-cn`, `deepseek→deepseek`, `alibaba→alibaba`, `qwen-oauth→alibaba`, `copilot→github-copilot`, `ai-gateway→vercel`, `opencode-zen→opencode`, `opencode-go→opencode-go`, `kilocode→kilo`, `fireworks→fireworks-ai`, `huggingface→huggingface`, `gemini→google`, `google→google`, `xai→xai`, `xai-oauth→xai`, `xiaomi→xiaomi`, `nvidia→nvidia`, `meta-ai→meta`, `meta→meta`, `groq→groq`, `mistral→mistral`, `togetherai→togetherai`, `perplexity→perplexity`, `cohere→cohere`, `ollama-cloud→ollama-cloud`. A lazily-built reverse map (`_models_dev_to_hermes_ids`) is many-to-one. User overrides for context/cost live in a YAML override file consumed by `_load_model_overrides()` / `_override_for()` / `_merge_catalog_entry_with_override()`.
- **Rebuild notes:** ETag-conditional registry mirror with stale-serve semantics and an explicit no-network flag on every query. A better version would let providers publish their own delta feed so a single retired model does not require re-downloading 2 MB.

### Model context-length resolution & static fallback table  `id: providers.model-context-resolution`
- **Surface:** Core
- **Where:** `agent/model_metadata.py` (4019 lines) — `get_model_context_length()` (`:2938`) is the entry point.
- **What it does:** Determines a model's usable context window (and max output) from every available source, with a thin static fallback table for the cases where no provider publishes it.
- **How it works:** Resolution consults, in order: an explicit `model.context_length` config override; the endpoint-scoped override table (`_endpoint_scoped_context_length`, `:815`); a persisted per-(model, base_url) cache (`save_context_length` / `get_cached_context_length` / `_invalidate_cached_context_length`, `:1584-1664`, keyed by `_context_cache_key`); live provider `/models` metadata (`fetch_model_metadata`, `:1284`; `fetch_endpoint_model_metadata`, `:1345`); models.dev; provider-specific probes — Anthropic (`_query_anthropic_context_length`, `:2456`), Codex OAuth (`_fetch_codex_oauth_context_lengths`, `:2772`, keyed by a token fingerprint `_codex_oauth_token_fingerprint` and the `chatgpt_account_id` claim), Nous (`_resolve_nous_context_length`, `:2859`), Ollama/LM Studio (`query_ollama_num_ctx`, `:1974`; `_query_ollama_api_show`, `:2090`; `_query_local_context_length`, `:2272`; `detect_local_server_type`, `:1010`); and finally `DEFAULT_CONTEXT_LENGTHS` by **longest-substring** match. Errors are mined too: `parse_context_limit_from_error()` (`:1674`), `get_context_length_from_provider_error()` (`:1711`), `parse_available_output_tokens_from_error()` (`:1731`), `is_output_cap_error()` (`:1889`), and `get_next_probe_tier()` (`:1666`) for step-down probing. Blackhole protection: `_note_endpoint_blackholed` / `_endpoint_blackholed` (`:207-239`) skip endpoints that connect-timeout. Local probes are memoised in-process for `_LOCAL_CTX_PROBE_TTL_SECONDS = 30.0` and on disk (`_local_probe_disk_get/put`).
- **Inputs / options:** `DEFAULT_CONTEXT_LENGTHS` (`:428-624`), matched longest-key-first — full table: `claude-fable-5` 1000000, `claude-fable` 1000000, `claude-opus-5` 1000000, `claude-sonnet-5` 1000000, `claude-opus-4-8` 1000000, `claude-opus-4.8` 1000000, `claude-opus-4-7` 1000000, `claude-opus-4.7` 1000000, `claude-opus-4-6` 1000000, `claude-sonnet-4-6` 1000000, `claude-opus-4.6` 1000000, `claude-sonnet-4.6` 1000000, `claude` 200000; `gpt-5.6-luna` 1050000, `gpt-5.6-terra` 1050000, `gpt-5.6-sol` 1050000, `gpt-5.5` 1050000, `gpt-5.4-nano` 400000, `gpt-5.4-mini` 400000, `gpt-5.4` 1050000, `gpt-5.3-codex-spark` 128000, `gpt-5.1-chat` 128000, `gpt-5` 400000, `gpt-4.1` 1047576, `gpt-4` 128000; `gemini` 1048576; `gemma-4` 256000, `gemma4` 256000, `gemma-4-31b` 256000, `gemma-3` 131072, `gemma` 8192; `deepseek-v4-pro` 1000000, `deepseek-v4-flash` 1000000, `deepseek-chat` 1000000, `deepseek-reasoner` 1000000, `deepseek` 128000; `llama` 131072; `inkling` 1048576; `qwen3.8-max` 1000000, `qwen3.8-flash` 1000000, `qwen3.6-plus` 1048576, `qwen3.7-plus` 1048576, `qwen3-coder-plus` 1000000, `qwen3-coder` 262144, `qwen3-max` 262144, `qwen` 131072; `minimax-m3` 1000000, `minimax` 204800; `glm-5.2` 1048576, `glm-5.2:free` 256000, `glm-5.3` 1048576, `glm` 202752; `grok-composer` 200000, `grok-build-latest` 500000, `grok-build` 256000, `grok-code-fast` 256000, `grok-2-vision` 8192, `grok-4-fast` 2000000, `grok-4.20` 2000000, `grok-4.6` 500000, `grok-4.5` 500000, `grok-4.3` 1000000, `grok-4` 256000, `grok-3` 131072, `grok-2` 131072, `grok` 131072; `kimi-k3` 1048576, `kimi` 262144; `solar-open2` 262144, `solar-pro3` 131072, `solar-pro2` 65536, `solar-mini` 32768; `hy4-preview` 1048576, `hy3-preview` 262144, `hy3` 262144; `x-preview-f` 1048576, `ox-alpha` 1048576; `nemotron-3.5-lightning` 1000000, `nemotron` 131072; `laguna-s-2.1` 262144, `laguna-xs-2.1` 262144; `trinity` 262144; `elephant` 262144; `Qwen/Qwen3.5-397B-A17B` 131072, `Qwen/Qwen3.5-35B-A3B` 131072, `deepseek-ai/DeepSeek-V3.2` 65536, `moonshotai/Kimi-K2.5` 262144, `moonshotai/Kimi-K2.6` 262144, `moonshotai/Kimi-K2-Thinking` 262144, `MiniMaxAI/MiniMax-M2.5` 204800, `XiaomiMiMo/MiMo-V2-Flash` 262144, `mimo-v2-pro` 1048576, `mimo-v2.5-pro` 1048576, `mimo-v2.5` 1048576, `mimo-v2-omni` 262144, `mimo-v2-flash` 262144, `zai-org/GLM-5` 202752.
- **Outputs / side effects:** Persisted context cache; one-shot warning `"Could not determine context length for model %r (base_url=%s) — falling back to %s tokens. Set model.context_length in config.yaml to override."` (`_warn_context_length_fallback`, `:395-408`).
- **Config / env:** `model_context_length` (schema label "Context window override (0 = auto-detect from model metadata)"); per-provider `ssl_verify` / `ssl_ca_cert` affect the `/models` probes via `_resolve_requests_verify()`.
- **Edge cases / guards:** `MINIMUM_CONTEXT_LENGTH = 64_000` (`:414`) — models below this cannot maintain enough working memory for tool-calling workflows, so sessions, model switches and cron jobs reject them. `_stale_pre_catalog_cache_entry()` (`:2226`) discards cache entries written before a `DEFAULT_CONTEXT_LENGTHS` key existed. Codex context variants: `is_codex_900k_base()` (`:2591`), `is_codex_context_variant()` (`:2612`), `strip_codex_context_variant_suffix()` (`:2624`), `has_codex_context_variant()` (`:2643`), `_verified_codex_ctx_for_slug()` (`:2652`). `requests` is imported lazily (≈27 ms off the `import cli` waterfall) via `_ensure_requests()` and a PEP-562 `__getattr__`.
- **Rebuild notes:** A layered resolver with per-source caching and error-message mining. A better version would make every provider publish `context_window`/`max_output` in its catalog and delete the static table.

### Grok reasoning-effort capability table  `id: providers.grok-effort-capability`
- **Surface:** Core
- **Where:** `agent/model_metadata.py:626-668` — `_GROK_EFFORT_CAPABLE_PREFIXES`, `grok_supports_reasoning_effort(model)`, `is_grok_46_family(model)`.
- **What it does:** Decides whether an xAI Grok model accepts the `reasoning.effort` parameter at all, so Hermes sends no `reasoning` key rather than a default `medium` that would 400.
- **How it works:** Verified live against `/v1/responses` 2026-05-10. **ACCEPTS effort:** `grok-3-mini`, `grok-3-mini-fast`, `grok-4.20-multi-agent-0309`, `grok-4.3`. **REJECTS effort:** `grok-3`, `grok-4`, `grok-4-0709`, `grok-4-fast-(non-)reasoning`, `grok-4-1-fast-(non-)reasoning`, `grok-4.20-0309-(non-)reasoning`, `grok-code-fast-1`. REJECTS-side models still reason natively — they just do not expose an effort dial — and sending one yields `"Model X does not support parameter reasoningEffort"`. `_GROK_EFFORT_CAPABLE_PREFIXES = ("grok-3-mini", "grok-4.20-multi-agent", "grok-4.3", "grok-4.5", "grok-4.6")`.
- **Inputs / options:** model id string.
- **Outputs / side effects:** Boolean gate on the reasoning field.
- **Config / env:** n/a.
- **Edge cases / guards:** `grok-4.5` accepts `low`/`medium`/`high` (default `high` when omitted) but **rejects** `"none"` (`"This model does not support `reasoning_effort` value `none`"`), unlike `grok-4.3`; models.dev agrees. `grok-4.6` is a drop-in successor with the same dial.
- **Rebuild notes:** A prefix allow-list validated by live probing. A better version would read xAI's own `/v1/models` capability field once it exists.

### Usage normalisation & cost estimation  `id: providers.usage-pricing`
- **Surface:** Core
- **Where:** `agent/usage_pricing.py` (1600 lines).
- **What it does:** Normalises every provider's usage payload into one canonical shape and turns it into a dollar cost, including "subscription-included" routes where no invoice exists.
- **How it works:** Dataclasses `CanonicalUsage` (`:74`), `BillingRoute` (`:112`), `PricingEntry` (`:120`), `CostResult` (`:143`). `resolve_billing_route()` (`:1078`) decides which provider/model actually bills for a call (handling aggregators and relays); `_normalize_bedrock_model_name()` (`:1128`) and `_normalize_anthropic_model_name()` (`:1169`) canonicalise ids; `_lookup_official_docs_pricing()` (`:1186`) and `_openrouter_pricing_entry()` (`:1210`) supply rates, with `_pricing_entry_from_metadata()` (`:1219`) falling back to the metadata cache; `get_pricing_entry()` (`:1263`), `normalize_usage()` (`:1293`) and `estimate_usage_cost()` (`:1448`) complete the pipeline. `has_known_pricing()` (`:1547`) gates cost display. Money is `Decimal`; `_ONE_MILLION` scales per-million rates.
- **Inputs / options:** Provider usage objects (dict or SDK object) — read defensively by `_usage_get()` / `_usage_count()` / `_to_decimal()` / `_to_int()`.
- **Outputs / side effects:** `CostResult` with a `status`; `status="included"` carries the note `"subscription-included; no provider invoice for usage"` so consumers can distinguish "free because subscription" from "free because $0 pricing". Display helpers: `format_cost_label(amount)` (`:30`) — zero → `"$0.00"`, sub-cent (< `_SUBCENT_THRESHOLD = Decimal("0.01")`) → 4 decimal places with a `~` prefix (e.g. `~$0.0046`) so the display is never a misleading `$0.00` (#79220); `format_duration_compact(seconds)` (`:1566`); `format_token_count_compact(value)` (`:1580`).
- **Config / env:** `DEFAULT_PRICING = {"input": 0.0, "output": 0.0}`; `_NOUS_DEFAULT_BASE_URL = "https://inference-api.nousresearch.com/v1"`.
- **Edge cases / guards:** Never re-parses provider-formatted USD strings to float.
- **Rebuild notes:** Canonical usage record + a route resolver + Decimal arithmetic. A better version would persist the resolved `PricingEntry` per (route, day) so historical reports are not re-priced with today's rates.

---

## 5. Credential pool, rotation, rate limits and credits

### Credential pool (multi-credential same-provider failover)  `id: providers.credential-pool`
- **Surface:** Core
- **Where:** `agent/credential_pool.py` (3566 lines); state in `~/.hermes/auth.json` under `credential_pool`; CLI surface is `hermes auth add|list|remove|reset|status|logout`.
- **What it does:** Holds several credentials per provider and rotates between them, benching a credential when it 401s / 429s / hits a billing wall, so a session survives a single key running out.
- **How it works:** `PooledCredential` dataclass (`:203-306`) fields: `provider`, `id` (6 hex chars), `label`, `auth_type`, `priority`, `source`, `access_token`, `refresh_token`, `last_status`, `last_status_at`, `last_error_code`, `last_error_reason`, `last_error_message`, `last_error_reset_at`, `base_url`, `expires_at`, `expires_at_ms`, `last_refresh`, `inference_base_url`, `agent_key`, `agent_key_expires_at`, `request_count`, `extra` (dict). `_EXTRA_KEYS` (`:177-189`, round-tripped through JSON but never used as logic attributes): `token_type`, `scope`, `client_id`, `portal_base_url`, `obtained_at`, `expires_in`, `agent_key_id`, `agent_key_expires_in`, `agent_key_reused`, `agent_key_obtained_at`, `tls`, `secret_source`, `secret_fingerprint`, `failure_reason` (the classified failure semantics from `agent/error_classifier.py`, persisted so a restart does not downgrade a billing bench back to a 60 s transient cooldown). `runtime_api_key` (`:283`) — for `nous` it prefers `agent_key` then `access_token`, each validated as a usable NAS invoke JWT by `auth._nous_invoke_jwt_is_usable`. Statuses: `STATUS_OK = "ok"`, `STATUS_EXHAUSTED = "exhausted"`, `STATUS_DEAD = "dead"` (terminal — excluded from rotation unconditionally, cleared only by an explicit write-side sync such as `_save_codex_tokens` after a fresh device-code login). `_TERMINAL_AUTH_REASONS` (`:82-95`): `token_invalidated` (OpenAI Codex "Your authentication token has been invalidated."), `token_revoked` (RFC 7009), `invalid_token` (RFC 6750), `invalid_grant` (RFC 6749 refresh rejected), `unauthorized_client` (RFC 6749), `refresh_token_reused`. Plus the locally-generated `CREDENTIAL_PERSIST_FAILED_REASON = "credential_persist_failed"` (a refresh POST rotated a single-use pair but the replacement never reached its store, so the on-disk token is already spent). `DEAD_MANUAL_PRUNE_TTL_SECONDS = 24*60*60` — DEAD `manual:*` entries are pruned after 24 h (the user can re-add), while singleton-seeded entries (`device_code`, `claude_code`) are never pruned because `_seed_from_singletons` would just re-create them.
- **Inputs / options:** Rotation strategies (`:118-133`): `fill_first` (`STRATEGY_FILL_FIRST`), `round_robin`, `random`, `least_used`; `get_pool_strategy(provider)` (`:544`) reads config. Cooldowns (`:135-146`): `EXHAUSTED_TTL_401_SECONDS = 5*60` (transient 401s cool down briefly so single-key setups recover), `EXHAUSTED_TTL_429_SECONDS = 60*60`, `EXHAUSTED_TTL_DEFAULT_SECONDS = 60*60`, `EXHAUSTED_TTL_SOLE_CREDENTIAL_SECONDS = 60` (when the offending key is the sole non-DEAD entry a 1-hour bench would mean an hour of hard failures with nothing to fall back to). A provider-supplied `reset_at` overrides all of these (`_parse_absolute_timestamp`, `_extract_retry_delay_seconds`, `_exhausted_ttl`, `_exhausted_until`). `FAILURE_REASON_BILLING = "billing"`; `FAILURE_REASON_BILLING_UNVERIFIED = "billing_unverified"` — Anthropic's "out of extra usage" 400 is returned both for genuine overage depletion and for a server-side content-filter rejection (#82154), so an unverified billing exhaustion gets the short transient cooldown instead of the one-hour bench. `DEFAULT_MAX_CONCURRENT_PER_CREDENTIAL = 1` (`:664`). `CUSTOM_POOL_PREFIX = "custom:"` — custom endpoints share `provider="custom"` and are keyed `custom:<normalized_name>` (`get_custom_provider_pool_key`, `:492`; `list_custom_pool_providers`, `:522`; `resolve_runtime_pool_key`, `:625`).
- **Outputs / side effects:** Reads/writes `~/.hermes/auth.json` under `_auth_store_lock`; `_write_through_provider_state_to_global_root()` (`:667`) keeps the legacy singleton block in sync. `_seed_from_singletons()` (`:2869`) and `_seed_from_env()` (`:3268`) re-populate the pool on every `load_pool()`; `_prune_stale_seeded_entries()` (`:3395`) removes rows whose source disappeared.
- **Config / env:** Pool strategy config key; `load_env()` / `get_env_prefer_dotenv(key)` (`:3249`) prefer `~/.hermes/.env` over the process environment.
- **Edge cases / guards:** `NO_AVAILABLE_ENTRIES_LOG_THROTTLE_SECONDS = 60.0` — credential selection runs on the hot path (every model call plus auxiliary tasks), and on Windows several Hermes processes share one rotating log guarded by concurrent-log-handler's cross-process lock; the un-throttled line stormed that lock (`RuntimeError: Cannot acquire lock after 20 attempts`), pegged a core and stalled the event loop long enough to fail the Desktop backend readiness handshake ("Timed out connecting to Hermes backend after 15000ms"). `_normalize_pool_auth_type()` (`:191`) infers `oauth` for an Anthropic token starting `sk-ant-oat`. `_load_config_safe()` uses `load_config_readonly()` because `load_config()`'s per-call deepcopy made credential-pool checks the dominant cost of `model.options` (the picker calls `load_pool()` once per provider row).
- **Rebuild notes:** A JSON-persisted list of credentials per provider with status, cooldown and priority, plus four selection strategies. A better version would keep secrets in the OS keychain and store only fingerprints in `auth.json`.

### Credential-source removal contract  `id: providers.credential-sources`
- **Surface:** Core
- **Where:** `agent/credential_sources.py` (451 lines); drives `hermes auth remove <provider> <target>`.
- **What it does:** Guarantees that removing a pooled credential makes it stay gone, no matter which of the nine sources originally seeded it.
- **How it works:** Sources Hermes seeds from: `env:<VAR>` (os.environ / `~/.hermes/.env`), `claude_code` (`~/.claude/.credentials.json`), `hermes_pkce` (`~/.hermes/.anthropic_oauth.json`), `device_code` (`auth.json providers.<provider>` — nous, openai-codex, …), `qwen-cli` (`~/.qwen/oauth_creds.json`), `gh_cli` (`gh auth token`), `config:<name>` (a `custom_providers` config entry), `model_config` (`model.api_key` when `model.provider == "custom"`), `manual` (`hermes auth add`). Before this module each source had an ad-hoc removal branch and several had none, so `auth remove` silently reverted on the next `load_pool()` for qwen-cli, nous device_code (partial), hermes_pkce, copilot gh_cli, and custom-config sources. Now each source registers a `RemovalStep` (`:79`) via `register()` (`:115`) that always does three things: (1) clean up the externally-readable state the source reads from (.env line, auth.json block, OAuth file); (2) suppress the `(provider, source_id)` pair in auth.json so the corresponding `_seed_from_*` branch skips the upsert on re-load; (3) return a `RemovalResult` (`:54`) describing what was cleaned plus diagnostic hints (shell-exported env vars, external credential files deliberately not deleted).
- **Inputs / options:** Registered steps (`_register_all_sources`, `:386`): `_remove_env_source` (`:143`), `_remove_claude_code` (`:202`), `_remove_hermes_pkce` (`:215`), `_remove_nous_device_code` (`:248`), `_remove_minimax_oauth` (`:263`), `_remove_xai_oauth_device_code` (`:276`), `_remove_codex_device_code` (`:296`), `_remove_qwen_cli` (`:330`), `_remove_copilot_gh` (`:343`), `_remove_custom_config` (`:372`). `find_removal_step(provider, source)` (`:120`) resolves the right one; `_clear_auth_store_provider(provider)` (`:230`) is the shared auth.json cleaner.
- **Outputs / side effects:** Edits `.env`, `auth.json`, OAuth JSON files; adds suppression records.
- **Config / env:** `~/.hermes/.env`; `~/.hermes/auth.json`.
- **Edge cases / guards:** Adding a new source requires wiring a reader branch in `_seed_from_*` **and** gating it behind `is_source_suppressed(provider, source_id)`.
- **Rebuild notes:** One registry of `(provider, source) → RemovalStep` with a suppression list. A better version would make seeding and removal two halves of one `CredentialSource` class so they cannot drift.

### Credential-pool disk-boundary sanitisation  `id: providers.credential-persistence`
- **Surface:** Core
- **Where:** `agent/credential_persistence.py` (183 lines).
- **What it does:** Strips raw secret values from credential-pool rows that merely *reference* a borrowed runtime secret before they are written to `auth.json`, leaving a non-reversible fingerprint behind.
- **How it works:** `_PERSISTABLE_PROVIDER_SOURCES` (`:20-26`) — the exact `(provider, source)` pairs Hermes owns and may persist: `("anthropic","hermes_pkce")`, `("minimax-oauth","oauth")`, `("nous","device_code")`, `("openai-codex","device_code")`, `("xai-oauth","device_code")`. `is_borrowed_credential_source(source, provider_id)` (`:103-111`) returns False for an empty source and for `manual` / `manual:*`, and True for anything else not in that set — future external secret providers therefore **fail closed** at the disk boundary. `sanitize_borrowed_credential_payload(payload, provider_id)` (`:160-183`) drops every key `_is_secret_payload_key()` matches and adds `secret_fingerprint` (`sha256:<first 16 hex chars>` from `fingerprint_secret_value`, `:133`) derived from the first of `agent_key`, `access_token`, `refresh_token`, `api_key`, `token`, `secret` that has a value, else any secret-ish key, else an existing `sha256:`-prefixed fingerprint.
- **Inputs / options:** `_SAFE_SECRETISH_METADATA_KEYS` (`:28-49`) — keys that LOOK secret-ish but are kept: `secret_fingerprint`, `secret_source`, `token_type`, `scope`, `client_id`, `agent_key_id`, `agent_key_expires_at`, `agent_key_expires_in`, `agent_key_reused`, `agent_key_obtained_at`, `expires_at`, `expires_at_ms`, `expires_in`, `last_refresh`, `last_status`, `last_status_at`, `last_error_code`, `last_error_reason`, `last_error_message`, `last_error_reset_at`. `_SECRET_VALUE_KEYS` (`:51-73`): `access_token`, `refresh_token`, `agent_key`, `api_key`, `apikey`, `api_token`, `auth_token`, `authorization`, `bearer_token`, `client_secret`, `credential`, `credentials`, `id_token`, `oauth_token`, `private_key`, `secret_key`, `session_token`, `password`, `secret`, `token`, `tokens`. `_SECRET_VALUE_SUFFIXES` (`:75-92`): `_api_key`, `_api_token`, `_access_token`, `_auth_token`, `_refresh_token`, `_bearer_token`, `_client_secret`, `_id_token`, `_oauth_token`, `_private_key`, `_session_token`, `_secret_key`, `_password`, `_secret`, `_token`, `_key`. Key normalisation (`_normalize_key`, `:97-100`) splits camelCase (`_CAMEL_CASE_BOUNDARY = r"(?<=[a-z0-9])(?=[A-Z])"`), lowercases, and maps `-`/`.` to `_`.
- **Outputs / side effects:** The dict that `PooledCredential.to_dict()` writes.
- **Config / env:** n/a.
- **Edge cases / guards:** No dependency on `hermes_cli.auth`, so the pool model and the auth-store write boundary share one policy without an import cycle.
- **Rebuild notes:** A key classifier + a SHA-256 fingerprint. A better version would encrypt owned secrets at rest instead of only sanitising borrowed ones.

### Rate-limit header tracking  `id: providers.rate-limit-tracker`
- **Surface:** Core
- **Where:** `agent/rate_limit_tracker.py` (246 lines); rendered by the `/usage` slash command.
- **What it does:** Captures `x-ratelimit-*` headers from provider responses and formats them as usage bars.
- **How it works:** `parse_rate_limit_headers()` (`:92`) reads all 12 headers into `RateLimitState` (`:57`) of `RateLimitBucket` (`:31`, fields `limit`, `remaining`, plus reset seconds). Header schema, verbatim: `x-ratelimit-limit-requests` (RPM cap), `x-ratelimit-limit-requests-1h` (RPH cap), `x-ratelimit-limit-tokens` (TPM cap), `x-ratelimit-limit-tokens-1h` (TPH cap), `x-ratelimit-remaining-requests`, `x-ratelimit-remaining-requests-1h`, `x-ratelimit-remaining-tokens`, `x-ratelimit-remaining-tokens-1h`, `x-ratelimit-reset-requests`, `x-ratelimit-reset-requests-1h`, `x-ratelimit-reset-tokens`, `x-ratelimit-reset-tokens-1h`. Rendering: `_bar(pct, width=20)` (`:159`), `_bucket_line(label, bucket, label_width=14)` (`:167`), `_fmt_count` (`:135`), `_fmt_seconds` (`:146`), `format_rate_limit_display(state)` (`:182`) and `format_rate_limit_compact(state)` (`:226`).
- **Inputs / options:** A response header mapping.
- **Outputs / side effects:** Text blocks for `/usage`.
- **Config / env:** n/a.
- **Edge cases / guards:** Currently supports the Nous Portal header format, which OpenRouter and other OpenAI-compatible APIs also follow.
- **Rebuild notes:** 12 headers → 4 buckets → 2 renderers.

### Nous cross-session rate-limit guard  `id: providers.nous-rate-guard`
- **Surface:** Core
- **Where:** `agent/nous_rate_guard.py` (325 lines); state file `~/.hermes/rate_limits/nous.json`.
- **What it does:** Records a Nous Portal 429 to a shared file so every session (CLI, gateway, cron, auxiliary) checks it before making a request, eliminating retry amplification when RPH is tapped.
- **How it works:** Each 429 from Nous triggers up to 9 API calls per conversation turn (3 SDK retries × 3 Hermes retries) and every one counts against RPH. `record_nous_rate_limit()` (`:71`) writes state atomically (`utils.atomic_replace`); `nous_rate_limit_remaining()` (`:139`) returns seconds left or `None`; `clear_nous_rate_limit()` (`:163`) resets it; `format_remaining(seconds)` (`:173`) renders it. `_parse_reset_seconds()` (`:39`) extracts the reset window from headers. `is_genuine_nous_rate_limit()` (`:192`) distinguishes a real bucket exhaustion from an unrelated 429 by parsing the buckets (`_parse_buckets_from_headers`, `:247`; `_has_exhausted_bucket`, `:286`; `_has_exhausted_bucket_in_object`, `:300`), gated by `_MIN_RESET_FOR_BREAKER_SECONDS = 60.0` (`:189`).
- **Inputs / options:** Response headers; a reset timestamp.
- **Outputs / side effects:** `<HERMES_HOME>/rate_limits/nous.json`.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** Falls back to `~/.hermes` when `hermes_constants` cannot be imported.
- **Rebuild notes:** One shared JSON breaker file with an expiry timestamp.

### Nous credits tracking & notices  `id: providers.credits-tracker`
- **Surface:** Core / CLI / TUI / Desktop
- **What it does:** Parses Nous's credit headers into a validated state, and turns that state into the escalating status-bar notices the user sees.
- **Where:** `agent/credits_tracker.py` (860 lines); notices surface through `AIAgent.notice_callback` / `notice_clear_callback` (the TUI renders them as a status-bar override, the CLI as a console line).
- **How it works:** `parse_credits_headers(headers, provider)` (`:452`) returns `None` (miss) when there is no `x-nous-credits-version` header or the version is not 1 (a version > 1 also emits a one-time `logger.warning`). Header schema, verbatim: `x-nous-credits-version`, `x-nous-credits-remaining-micros`, `x-nous-credits-remaining-usd`, `x-nous-credits-subscription-micros` (SIGNED; may be negative/debt), `x-nous-credits-subscription-usd`, `x-nous-credits-subscription-limit-micros` (PAIRED/optional), `x-nous-credits-subscription-limit-usd` (PAIRED/optional), `x-nous-credits-rollover-micros`, `x-nous-credits-purchased-micros`, `x-nous-credits-purchased-usd`, `x-nous-credits-denominator-kind` (`"subscription_cap"` | `"none"`), `x-nous-credits-paid-access` (the STRING `"true"`/`"false"`), `x-nous-credits-disabled-reason` (header omitted when null), `x-nous-credits-as-of-ms`. Tool-pool headers use a SEPARATE prefix: `x-nous-tool-pool-micros`, `x-nous-tool-pool-gated-off` (STRING). Money is micros ints only; `*_usd` values are preserved verbatim as the raw strings the server sent and never re-parsed to float (`_USD_RE = r"^-?\d+\.\d{2}$"` validates them). `CreditsState` (`:94-150`) also carries `captured_at`, `from_header`, and properties `has_data`, `age_seconds`, `depleted` (keyed off `paid_access == False` ONLY — never `remaining_micros == 0`, which would false-positive when a balance is zero but access is still live) and `used_fraction` (computable only when `subscription_limit_micros` is a truthy int; guarded on the LIMIT FIELD, not `denominator_kind`, which is only metadata).
- **Inputs / options:** `evaluate_credits_notices(state, latch, *, model_is_free=False)` (`:274-445`) is a pure function returning `(to_show, to_clear)`; the caller emits `to_clear` FIRST. `new_credits_latch()` (`:181`) is the required latch factory: `{"active": set(), "seen_below_90": False, "usage_band": None, "seen_grant_unspent": False}`. `CREDITS_USAGE_BANDS = ((0.50, "info", 50), (0.75, "warn", 75), (0.90, "warn", 90))` — a single escalating status line, not three stacked notices; crossing up replaces the line and recovering steps it back down. `CREDITS_USAGE_KEY = "credits.usage"`, `CREDITS_NOTICE_KIND = "sticky"`, `CREDITS_RESTORED_TTL_MS = 8000`, `GRANT_UNSPENT_MIN_MICROS = 10_000` (1¢ floor for the grant-spent crossing gate, because portal-seeded states derive micros from float dollars and can carry sub-cent residue). `AgentNotice` (`:199-217`): `text`, `level` (`info|warn|error|success`), `kind` (`sticky|ttl`), `ttl_ms`, `key`, `id`.
- **Outputs / side effects:** Exact notice strings — usage gauge: `"⚠ You've used $<used> of your $<cap> cap"` (glyph `⚠` at level `warn`, `•` at `info`; used = cap − remaining in micros, clamped to `[0, cap]`; cap renders as `?` when `subscription_limit_usd` is missing); grant spent: `"• Grant spent · $<purchased_usd> top-up left"` (level `info`, key `credits.grant_spent`); depleted: `"✕ Credit access paused · run /topup to top up"` (level `error`, key `credits.depleted`); restored: `"✓ Credit access restored"` (level `success`, kind `ttl`, `ttl_ms=8000`, key `credits.restored`).
- **Config / env:** `display.credits_notices` (default `true`).
- **Edge cases / guards:** Top-up suppression — when `purchased_micros > 0` the subscription-cap gauge is the wrong denominator ("90% used" at a user sitting on $50 of top-up is noise and used to stick permanently alongside `grant_spent` at ≥100%), so the band is suppressed entirely and the `grant_spent` info notice covers the cap-reached case. The `seen_below_90` crossing latch prevents a brand-new session opening mid-range from firing spuriously. The `seen_grant_unspent` gate is consumed by its show, so a header flicker cannot re-announce; only a renewal re-arms it, and seeds must NOT prime it. `model_is_free` suppresses `credits.depleted` (a depleted account on a free model can keep inferencing) and suppression deliberately does NOT emit the "restored" success notice. `is_free_tier_model(model, base_url)` (`:221`) uses two zero-network signals: the `:free` suffix (the canonical Nous free SKU marker — spend is forced to 0 for `:free` ids) and the `stealth/` prefix (stealth-preview SKUs are free-tier but carry no `:free` suffix). `seed_credits_at_session_start(agent)` (`:807`) hydrates state before the first header arrives; `dev_fixture_credits_state()` (`:708`) supplies a dev fixture.
- **Rebuild notes:** Header parser → validated state → a pure notice policy with an explicit latch. A better version would make the bands and glyphs user-configurable and expose the same policy over the API for the web dashboard.

### Billing recovery links  `id: providers.billing-links`
- **Surface:** Core
- **Where:** `agent/billing_links.py` (124 lines); the resulting `BillingBlock` rides the turn result and the gateway `message.complete` event.
- **What it does:** Maps a billing-classified failure onto a recovery link and label so every surface (CLI, TUI, desktop) renders one structured signal instead of re-parsing error text.
- **How it works:** *Detection* is not done here — that is `agent/error_classifier.py` (`FailoverReason.billing`), the single source of truth for "credit wall vs rate limit / auth / transport". `build_billing_block(*, provider, base_url, model, message="")` (`:104-124`): when `is_nous_inference_route()` (`:73-77`, provider `nous` or host `inference-api.nousresearch.com`) it returns `BillingBlock(provider, "Nous Portal", model, <nous billing url>, is_nous=True, message)`; otherwise `_resolve_provider_link(slug, base_url)` (`:90-101`) tries the exact slug, then a base-URL host match, then degrades to a readable title-cased label with **no invented URL**. `_nous_billing_url()` (`:80-87`) calls `hermes_cli.nous_account.nous_portal_billing_url(None)` and falls back to `https://portal.nousresearch.com/billing`.
- **Inputs / options:** `_PROVIDERS` table (`:53-68`) — label, curated "add credits / manage billing" URL, slugs, hosts: **OpenAI** `https://platform.openai.com/settings/organization/billing` (slug `openai`, host `api.openai.com`); **Anthropic** `https://console.anthropic.com/settings/billing` (`anthropic`, `api.anthropic.com`); **OpenRouter** `https://openrouter.ai/settings/credits` (`openrouter`, `openrouter.ai`); **xAI** `https://console.x.ai/team/default/billing` (`xai`, `xai-oauth`, `api.x.ai`); **DeepSeek** `https://platform.deepseek.com/top_up` (`deepseek`, `api.deepseek.com`); **Groq** `https://console.groq.com/settings/billing` (`groq`, `api.groq.com`); **Mistral** `https://console.mistral.ai/billing` (`mistral`, `api.mistral.ai`); **Together AI** `https://api.together.ai/settings/billing` (`together`, `api.together.ai`, `api.together.xyz`); **Fireworks AI** `https://fireworks.ai/account/billing` (`fireworks`, `fireworks.ai`); **Perplexity** `https://www.perplexity.ai/settings/api` (`perplexity`, `perplexity.ai`); **Google AI** `https://aistudio.google.com/app/billing` (`google`, `gemini`, `generativelanguage.googleapis.com`); **Cohere** `https://dashboard.cohere.com/billing` (`cohere`); **Moonshot AI** `https://platform.moonshot.ai/console/pay` (`moonshot`); **NVIDIA** `https://build.nvidia.com/settings/billing` (`nvidia`).
- **Outputs / side effects:** `BillingBlock(provider, provider_label, model, billing_url, is_nous, message)` with `to_dict()`.
- **Config / env:** n/a.
- **Edge cases / guards:** `is_nous` is the routing bit — Nous has a first-class in-app billing surface (desktop Settings → Billing, TUI/CLI `/topup`), so surfaces prefer that over `billing_url`; third-party providers have no in-app flow, so `billing_url` is the deep link the user actually needs.
- **Rebuild notes:** A slug/host → URL table plus a graceful unknown-provider degradation.

---

## 6. Billing, subscription and top-up

### Nous billing API client  `id: providers.nous-billing-client`
- **Surface:** API
- **Where:** `hermes_cli/nous_billing.py` (675 lines) — a thin, fail-loud client for the `/api/billing/*` endpoints the terminal uses.
- **What it does:** Talks to the Nous portal's billing API for balance, charges, auto-reload and subscription changes.
- **How it works:** `_resolve_token_and_base(*, use_cache=True)` (`:243`) resolves the portal token and base URL (`resolve_portal_base_url`, `:173`; `_absolutize_portal_url`, `:189`; `invalidate_cached_token`, `:217`). `_request(...)` (`:382`) issues the call and `_raise_for_error(...)` (`:310`) maps status/error codes onto the exception hierarchy. `BILLING_MANAGE_SCOPE = "billing:manage"` (`:44`, duplicated from `hermes_cli.auth.NOUS_BILLING_MANAGE_SCOPE` so this module has no import dependency).
- **Inputs / options:** Endpoints — `get_billing_state()` → `GET /api/billing/state` (role-tiered overview, **no scope required**); `patch_auto_top_up(...)` → `PATCH /api/billing/auto-top-up` (scope required); `post_charge(...)` → `POST /api/billing/charge` (scope required); `get_charge_status(id)` → `GET /api/billing/charge/{id}` (scope required); `get_subscription_state()` → `GET /api/billing/subscription` (no scope); `post_subscription_preview(...)` → `POST /api/billing/subscription/preview` (a chargeless effect quote); `put_subscription_pending_change(...)` → `PUT /api/billing/subscription/pending-change` (set the end-of-period intent); `delete_subscription_pending_change(...)` → `DELETE /api/billing/subscription/pending-change` (clear it — resume / undo); `post_subscription_upgrade(...)` → `POST /api/billing/subscription/upgrade` (immediate paid upgrade).
- **Outputs / side effects:** Raw JSON dicts parsed by `agent/billing_view.py` and `agent/subscription_view.py`.
- **Config / env:** portal base URL from the auth store / `dashboard.oauth.portal_url`.
- **Edge cases / guards:** Exception hierarchy (`:52-171`): `BillingError` (base, carries `code`/`payload`), `BillingScopeRequired`, `BillingAuthError`, `BillingRemoteSpendingRevoked`, `BillingSessionRevoked` (a subclass of `BillingAuthError` meaning "log in again", not just reconnect), `BillingTransient` (the one to catch — a contract property, not the old ad-hoc hierarchy), `BillingRateLimited`, `BillingStripeUnavailable`, `BillingUpgradeCapExceeded`. `_retry_after_seconds(headers)` (`:298`) reads the retry hint.
- **Rebuild notes:** Nine endpoints + a typed error hierarchy + a cached token. A better version would expose the same client over the local API so the web dashboard and desktop share it.

### Billing state model (`GET /api/billing/state`)  `id: providers.billing-view`
- **Surface:** Core
- **Where:** `agent/billing_view.py` (511 lines) — a surface-agnostic core consumed identically by `cli.py::_show_billing`, the TUI JSON-RPC methods in `tui_gateway/server.py`, and any other surface.
- **What it does:** Parses the billing payload into frozen dataclasses, keeping money as `Decimal` end to end.
- **How it works:** Money discipline — the server emits decimal STRINGS (`"142.5"`, not fixed 2 dp), so `parse_money()` (`:32`) keeps them as `Decimal` and `format_money()` (`:47`) formats only for display. **Fail open**: when not logged in or the portal is unreachable, `build_billing_state(*, timeout=15.0)` (`:341`) returns `BillingState(logged_in=False, …)` and the surface degrades rather than crashing. `billing_state_from_payload()` (`:297`) does the parse; `_fallback_portal_url(base)` (`:391`) supplies a link when the payload omits one; `_dev_fixture_billing_state()` (`:401`) supplies a dev fixture.
- **Inputs / options:** `BillingState` fields (`:150-205`): `logged_in`, `org_id`, `org_slug`, `org_name`, `role` (`"OWNER"|"ADMIN"|"FINANCE_ADMIN"|"SECURITY_ADMIN"|"MEMBER"`), `can_change_plan_raw`, `balance_usd`, `cli_billing_enabled`, `charge_presets` (tuple of Decimals), `min_usd`, `max_usd`, `card`, `payment_method`, `monthly_cap`, `auto_reload`, `portal_url`, `error`. Properties: `is_admin` (deprecated/display-only legacy OWNER/ADMIN check — **not** a capability check), `can_change_plan` (server capability when supplied, else the legacy role fallback), `can_charge` (`can_change_plan` AND the per-org `cli_billing_enabled` kill-switch — this lets the server grant charge capability to non-OWNER/ADMIN roles like FINANCE_ADMIN via `canChangePlan`; the server still enforces, this only greys out actions). `CardInfo` (`:79-107`): `brand`, `last4`, `resolved_via`; `masked` → `"<brand> ····<last4>"` or just the brand when `last4` is empty (a Link payment method has no card number); `provenance` maps `resolved_via` through `_CARD_PROVENANCE_LABELS = {"subPin": "the card on your subscription", "customerDefault": "your default card saved on the portal", "autoRefill": "your auto-reload card"}`; `display` → `"Visa ····4242 — the card on your subscription"` or the masked card alone. `PaymentMethodInfo` (`:111-124`): `kind` (`"card"|"link"|"unknown"` — anything else is normalised to `unknown` at parse time), `brand`, `last4`, `wallet`, `email`, `resolved_via`, `raw_kind`. `MonthlyCap` (`:127-131`): `limit_usd`, `spent_this_month_usd`, `is_default_ceiling`. `AutoReload` (`:142-148`): `enabled`, `threshold_usd`, `reload_to_usd`, `card`. `AutoReloadCard` (`:134-139`): `kind` (`"canonical"|"distinct"|"none"`), `payment_method_id`, `brand`, `last4`. `new_idempotency_key()` (`:467`) returns a UUID for charge idempotency. `validate_charge_amount(raw, *, min_usd, max_usd)` (`:490-511`) returns `AmountValidation(ok, amount, error)` and mirrors the server's accept/reject so the UI gives instant feedback: strips a leading `$`; `"Enter a dollar amount, e.g. 100"` when unparseable; `"Amount must be greater than $0"`; `"Amount can't be smaller than a cent"` when the value is not a multiple of 0.01; `"Minimum is <money>"` / `"Maximum is <money>"` against the bounds.
- **Outputs / side effects:** Pure parsing; the caller performs the HTTP.
- **Config / env:** n/a.
- **Edge cases / guards:** A 404 from a not-yet-shipped endpoint yields `logged_in=False` rather than an error.
- **Rebuild notes:** Frozen dataclasses + Decimal money + fail-open. A better version would carry the server's own capability list rather than re-deriving `can_charge` client-side.

### Subscription state model (`GET /api/billing/subscription`)  `id: providers.subscription-view`
- **Surface:** Core
- **Where:** `agent/subscription_view.py` (507 lines) — the surface-agnostic core for the `/subscription` screen.
- **What it does:** Parses the current plan, the available tiers and a change preview, and builds the portal deep link.
- **How it works:** Same fail-open philosophy as `billing_view`; money is decimal end-to-end via `parse_money`. The TUI `SubscriptionOverlay` drives plan changes in-terminal (V3): it previews the effect, then schedules a downgrade / cancellation / resume (chargeless) or applies an upgrade (charges the card on the subscription). The portal deep link — built locally from `portal_url` + `org_id` by `subscription_manage_url()` (`:303`) — remains the fallback for an upgrade that needs 3DS or was declined.
- **Inputs / options:** Dataclasses: `CurrentSubscription` (`:38`) — `None` (not this object) means "no plan"; `SubscriptionTier` (`:59`); `SubscriptionChangePreview` (`:78`); `SubscriptionState` (`:100`). Parsers `_parse_current` (`:141`), `_parse_tier` (`:175`), `_coalesce` (`:163`), `subscription_change_preview_from_payload` (`:193`), `subscription_state_from_payload` (`:214`), `build_subscription_state(*, timeout=15.0)` (`:253`). Helpers `_format_dollars_grouped` (`:353`), `selectable_tiers(state)` (`:368`), `format_tier_row(tier)` (`:385`), `is_upgrade(state, tier_id)` (`:400`). Dev fixtures `_dev_current` (`:422`), `_dev_tiers` (`:434`), `dev_fixture_subscription_state` (`:456`), with `_DEV_FIXTURE_PORTAL = "https://portal.nousresearch.com/billing"` (`:419`).
- **Outputs / side effects:** Pure parsing.
- **Config / env:** n/a.
- **Edge cases / guards:** `GET /api/billing/subscription` is a NAS endpoint (WS1 Phase A); until it ships the fail-open contract handles 404s by returning `logged_in=False`.
- **Rebuild notes:** Plan + tier list + preview + deep link, all fail-open.

### Dollar usage bars (`agent/billing_usage.py`)  `id: providers.billing-usage`
- **Surface:** Core
- **Where:** `agent/billing_usage.py` (323 lines) — the single source of truth behind the `/usage` and `/subscription` usage bars in TUI and CLI.
- **What it does:** Renders the monthly subscription allowance and separately-purchased top-up dollars as two distinct bars.
- **How it works:** Per user feedback (Jun 2026) the terminal surfaces show **dollars**, never "credits". Data comes from the NAS account-info fetch (`NousPortalAccountInfo`), whose `paid_service_access_info` carries three USD floats despite the legacy `*_credits` field names: `subscription_credits_remaining` → plan dollars left this month; `purchased_credits_remaining` → top-up dollars left (rolls over); `total_usable_credits` → total spendable. Plus `subscription.monthly_credits` (the plan's monthly $ allowance, the denominator for the "% used" plan bar) and `current_period_end` (renewal). Design decision: **two separate bars** rather than one crammed three-segment bar, because at terminal widths three same-glyph density segments are unreadable. The plan bar is "spent vs allowance this month" (carries % used); the top-up bar is "money you bought, doesn't expire". Each gets full resolution and a single fill glyph, so the bar is never ambiguous and never relies on colour.
- **Inputs / options:** `UsageBar` (`:89`), `UsageModel` (`:117`), `usage_model_from_account(account_info)` (`:143`), `build_usage_model(*, timeout=10.0)` (`:226`), `_dev_fixture_usage_model()` (`:264`), `format_renews(value)` (`:61`), `_fmt_usd(value)` (`:56`), `_finite(value)` (`:48`). `LOW_BALANCE_THRESHOLD_USD = 5.0` (`:45`).
- **Outputs / side effects:** Ready-to-print lines (filled = remaining) via `CLIBillingMixin._usage_bar_lines(usage, plan_name)`.
- **Config / env:** n/a.
- **Edge cases / guards:** Fail-open everywhere — any missing or non-finite field degrades to fewer bars or a magnitudes-only view; a logged-out or unreachable portal yields `available=False` and the surface shows nothing.
- **Rebuild notes:** Two independent bars driven by three dollar magnitudes plus an allowance denominator.

### `/topup` — CLI top-up flow  `id: providers.slash-topup`
- **Surface:** CLI
- **Where:** Slash command `/topup` (also reachable from the depleted-credits notice "✕ Credit access paused · run /topup to top up"); implemented in `hermes_cli/cli_billing_mixin.py::_show_billing(command="/topup")` (`:754`).
- **What it does:** Shows the org's balance, card, auto-reload and monthly cap, and lets an authorised user add funds from the terminal.
- **How it works:** `_show_billing` builds a `BillingState`; on failure it prints `"  💳 Could not load subscription: <error>"` or, when logged out, `"  💳 Not logged into Nous Portal."` + `"  Run \`hermes portal\` to log in, then /topup."`. `_billing_overview(state)` (`:795`) prints the header `"💳 Top up · balance <money>"`, an optional org line, a `─`×41 rule, the usage bars, the auto-reload line, the card line (`"Card: <CardInfo.display>"`) or `"No saved card on file — “Add funds” walks you through adding one."`, a second rule, then the action menu. Gating: `_billing_require_admin(state)` (`:956`) prints `"  💳 Billing actions require an org admin/owner."` or `"  💳 Remote spending is off for this org."`. In a non-interactive context (slash-worker / no live app) no modal is shown — `_billing_portal_hint(state)` prints `"  Manage on portal: <url>"` and the URL is the affordance.
- **Inputs / options:** Menu (`_prompt_text_input_modal(title="Top up your balance", detail="", choices=…)`), choices verbatim `(key, label, detail)`: `("buy", "Add funds", "a single charge, added to your balance today")`, `("auto", "Auto-reload", "refill automatically when your balance runs low")`, `("limit", "Monthly limit", "show the monthly spend cap (read-only)")`, `("portal", "Manage on portal", "open the billing page in your browser")`, `("cancel", "Cancel", "do nothing")`. Framing copy printed above the rule: `"Add funds now — a single charge, added to your balance today."` and either `"Refill when low — charges <reload_to> automatically when your balance falls below <threshold>."` or `"Refill when low — charges your card automatically when your balance falls below the amount you set."`. **Add-funds flow** `_billing_buy_flow` (`:1019`): when no card is on file it first runs `_billing_add_card_flow` (`:975`) — `"💳 Add a card first"`, `"No saved card on file."`, `"Add a card once on the portal billing page — after that you can top up right from the terminal."`, `"Add the card on the billing page, then pick “check again” here."`, `"✓ Card found: <card> — continuing."`, `"Still no card on file — finish adding it on the portal, then check again."`, `"Cancelled. No funds added."`. Then a preset modal titled `"Add funds"` with `detail = "Payment: <card.display>"` (or `"No saved card on file"`), one choice per `state.charge_presets` labelled with `format_money(p)` and detail `"one-time credit purchase"`, plus `("custom", "Custom amount…", "enter your own amount")` and `("cancel", "Cancel", "do nothing")`. `custom` prompts `"  Amount (USD): "` and validates with `validate_charge_amount`. **Confirm** `_billing_confirm_and_charge` (`:1092`): `"💳 Confirm purchase"`, rule, `"Total: <money>"`, `"Payment: <card.display>"` or `"Your card saved on the portal will be charged."`, rule, a consent line, then `POST /api/billing/charge` with an idempotency key. **Poll** `_billing_poll_charge` (`:1162`): `"Charge submitted — confirming settlement…"`, success `"✓ <amount> added to your balance."`, timeout `"🟡 Still processing after 5 minutes — this is a timeout, not a …"`, errors `"🔴 Could not check the charge: <exc>"`.
- **Outputs / side effects:** A real card charge against the org's portal-saved card (server-held via `POST /charge` — no card reference leaves the client) and an updated balance.
- **Config / env:** Requires a Nous Portal login and the `billing:manage` scope ("Remote Spending").
- **Edge cases / guards:** No card/scope preflight — the charge is allowed to fly and the flow reacts to whatever 403 the server returns, in the server's own gate order: scope first (`insufficient_scope` → in-flight re-auth via `_billing_handle_scope_required`, `:1267`), then card (`no_payment_method` → portal handoff). Error copy (`_billing_render_charge_error`, `:1220`, and `_billing_render_charge_failed`, `:1206`), verbatim: `"💳 No card on file — top up and manage billing on the portal."`; `"Remote spending is off for this account — a billing admin can turn it on from the portal's Hermes Agent page."`; `"Adding funds needs an org admin/owner. Ask an admin, or manage on the portal."`; `"🔴 That charge key was already used for a different amount. Start a fresh top-up."`; `"🔴 Monthly spend cap reached — $<remaining> headroom left."` / `"🔴 Monthly spend cap reached."`; `"🟡 Too many charges right now<mins>. This isn't a payment failure."`; `"🔴 Remote Spending needs approval — run /topup to allow it, then retry."`; `"🔴 Your bank requires verification (3DS). Complete it on the …"`; `"🔴 Your card has expired. Update it on the portal."`; `"🔴 Your card was declined. Try another card on the portal."`; `"🔴 The charge didn't go through (<reason or processing_error>)."`; `"🔴 <who> Reconnect to restore — run \`hermes portal\` to re-authorize."`. Scope flow copy: `"! One-time setup"`, `"To charge from this terminal, allow Remote Spending once. It opens your browser to authorize, then <amount> picks up right here."`, choices `("yes", "Allow Remote Spending", "open your browser to authorize")` / `("no", "Not now", "cancel")`, `"Opening your browser to allow Remote Spending…"`, `"Couldn't allow Remote Spending: <exc>"`, `"Couldn't allow Remote Spending — an org admin or owner has to approve it. Your card was not charged."`, `"Remote Spending is allowed for this terminal, but it's still off for this org. A billing admin can turn it on from the portal's Hermes Agent page, then run /topup again."`, `"✓ Remote Spending allowed — but there's no card on file yet."`, `"Top up and manage billing on the portal to continue."`, `"✓ Remote Spending allowed. Run /topup to continue."`, `"✓ Remote Spending allowed."`, resume choices `("resume", "Resume <money> top-up", "finish the held purchase")` / `("cancel", "Cancel", "do not charge")`, `"Resuming your top-up — confirming settlement…"`, `"No charge id returned; please check the portal."`.
- **Rebuild notes:** Overview → preset/custom amount → consent → idempotent charge → poll to settlement, with 403-driven remediation instead of preflight. A better version would show live settlement status via a webhook instead of polling.

### `/topup` → Auto-reload  `id: providers.topup-auto-reload`
- **Surface:** CLI
- **Where:** `/topup` menu item `"Auto-reload"`; `hermes_cli/cli_billing_mixin.py::_billing_auto_reload_flow` (`:1374`) and `_billing_auto_reload_disable` (`:1519`).
- **What it does:** Configures an automatic charge that refills the balance when it drops below a threshold.
- **How it works:** Prints `"💳 Auto-reload"`, a rule, `"Automatically add funds when your balance is low."`, then `"Card on file: <masked>"` or `"No saved card — manage billing on the portal."`. Non-interactive prints `"Run in the interactive CLI to configure auto-reload."`. When already enabled the top menu offers `("edit", "Edit thresholds", "change when / how much to reload")`, `("off", "Turn off", "disable auto-reload")`, `("cancel", "Cancel", "do nothing")`. Editing prompts for a threshold and a reload-to amount, both validated by `validate_charge_amount` (errors print as `"🔴 <error>"`), with the extra rule `"🔴 Reload-to amount must be greater than the threshold."`. Confirmation shows a consent line and the choices `("agree", "Agree and turn on", "enable auto-reload")` / `("cancel", "Cancel", "do nothing")`, then `PATCH /api/billing/auto-top-up`.
- **Inputs / options:** threshold USD, reload-to USD.
- **Outputs / side effects:** Success `"✅ Auto-reload on: below <threshold> → …"`; disable prints `"✅ Auto-reload turned off."`; cancels print `"🟡 Cancelled."`.
- **Config / env:** Requires `billing:manage`.
- **Edge cases / guards:** Reload-to must exceed the threshold; both amounts obey the server min/max and the 2 dp rule.
- **Rebuild notes:** Two validated amounts + a consent gate + one PATCH.

### `/topup` → Monthly limit  `id: providers.topup-monthly-limit`
- **Surface:** CLI
- **Where:** `/topup` menu item `"Monthly limit"`; `hermes_cli/cli_billing_mixin.py::_billing_limit_screen` (`:1544`).
- **What it does:** Shows the org's monthly spend cap and how much has been used — read-only in the terminal.
- **How it works:** Prints `"💳 Monthly spend limit"`, a rule, then either `"No monthly cap visible (managed on the portal)."` or `"<spent> of <limit> used this month<ceiling>"` followed by a dimmed explanatory note.
- **Inputs / options:** none (read-only).
- **Outputs / side effects:** Display only.
- **Config / env:** `MonthlyCap.limit_usd`, `spent_this_month_usd`, `is_default_ceiling` from `GET /api/billing/state`.
- **Edge cases / guards:** Managed on the portal — the terminal never writes it.
- **Rebuild notes:** One read-only screen.

### `/subscription` — plan overview and change  `id: providers.slash-subscription`
- **Surface:** CLI / TUI
- **Where:** Slash command `/subscription`; `hermes_cli/cli_billing_mixin.py::_show_subscription` (`:103`) and helpers; the TUI equivalent is `SubscriptionOverlay`.
- **What it does:** Shows the current plan, its usage bars and renewal date, and lets an authorised user upgrade immediately or schedule a downgrade / cancellation / resume.
- **How it works:** `_show_subscription` builds a `SubscriptionState`; failures print `"  💳 Could not load subscription: <error>"`, logged-out prints `"  💳 Not logged into Nous Portal."` + `"  Run \`hermes portal\` to log in, then /subscription."`. A team org renders `"⚕ Team subscription"`, a `─`×41 rule, `"This terminal is connected to <org>. Teams run on a shared"`, `"balance · use /topup to add funds."`, `"Personal subscriptions live on your personal account."`. `_subscription_overview` (`:147`) renders any scheduled change as `"⏳ Scheduled change"` + `"<from> ──▶ <to>  · <when>"` + `"You keep <from> (and its credits) until then."`, then `"⚕ <status>"`, a rule, the usage bars, `"Total spendable: $<n>"`, `"> Paid models need a subscription. Start one to reach them."` when free, a low-balance line, an org line, a second rule, and either `"Plan changes need an org admin/owner."` + `"Manage on portal: <url>"` or the change menu. `_subscription_free_catalog` (`:292`) renders `"⚕ Choose a plan"` + a numbered `format_tier_row(t)` list + `"Starting a subscription opens the portal to add your card."`.
- **Inputs / options:** `_subscription_change_menu` (`:387`), `_subscription_pick_tier` (`:421`) — `"No other plans are available to switch to right now."`; `_subscription_preview_and_confirm(state, tier_id, *, allow_stepup=True)` (`:449`) → `POST /api/billing/subscription/preview`, printing `"Checking the change…"`, `"You are already on <target> — nothing to change."`, `"🟡 <reason or 'This change cannot be confirmed here — manage it on the portal.'>"`, and for an upgrade `"Confirm plan change  · charged now"` + `"Upgrade to <target>. You will be charged <amount> now (prorated)."` (or `"…the prorated amount now."`) + a card line, or for a scheduled change `"Confirm plan change  · scheduled · not today"` + `"Change to <target> — takes effect <when>. No charge now; you keep your current plan until then."` + `"Monthly credits change: <delta>."`; `_subscription_confirm_cancel` (`:543`) — `"Confirm cancellation  · scheduled · not today"`, `"Cancel <plan> — it stays active until <end>, then won't renew."`, `"You keep your remaining credits for this period. You can resume before it ends."`; `_subscription_apply(state, action, idempotency_key=None, *, allow_stepup=True)` (`:565`) → `PUT`/`DELETE /api/billing/subscription/pending-change` or `POST /api/billing/subscription/upgrade`; `_subscription_open_portal(state, manage_url, *, verb="Manage your subscription")` (`:357`) — `"No manage URL available — is your portal configured?"`, `"Open this URL: <url>"`, `"Finish in your browser, then re-run /subscription."`, `"📋 Copied: <url>"`, `"Manage URL: <url>"`, `"🟡 Cancelled."`; `_open_url_in_browser(url)` (`:264`).
- **Outputs / side effects:** Result copy: `"✓ You are already on <name>."`; `"✓ Upgraded to <name>. Your new monthly credits land in a moment."`; `"🟡 This upgrade needs extra verification (3DS). Finish it on the portal."` + `"Portal: <url>"`; `"🔴 Your card was declined. Update your payment method on the portal and try again."` + `"Portal: <url>"`; `"✓ Scheduled — your plan doesn't change today. You keep it until the end of the billing period, then it switches."`; `"✓ Scheduled — your plan stays active until the end of the billing period, then it cancels. Nothing changes today."`; `"✓ Undone — you stay on your current plan."`; `"Re-run /subscription anytime to review it."`; `"🟡 Cancelled. No plan change."`; `"🟡 Closed. No plan change."`; `"🟡 Cancelled. Your plan is unchanged."`; `"🟡 Cancelled. No plan started."`; `"Opening the portal to start <label>…"`; `"Open this URL to start <label>: <url>"`; `"Finish in your browser, then re-run /subscription."`.
- **Config / env:** Requires a portal login; plan changes need `can_change_plan`.
- **Edge cases / guards:** `_subscription_handle_scope_required` (`:656`) runs the same in-flight Remote-Spending authorisation as `/topup`: `"! One-time setup"`, `"To change your plan from the terminal, allow Remote Spending once. It opens your browser to authorize, then your change picks up right here."`, `"Run \`hermes portal\` and allow Remote Spending, then re-run /subscription."`, `"No change made. Allow Remote Spending when you're ready."`, `"Opening your browser to allow Remote Spending…"`, `"Couldn't allow Remote Spending: <exc>"`, `"Couldn't allow Remote Spending — an org admin or owner has to approve it for this org."`, `"✓ Remote Spending allowed."`, and `"Remote Spending still isn't active for this terminal — the authorization didn't take. Retry, or make this change on the portal."`. `_subscription_render_error` (`:719`) prints `"🟡 Remote Spending isn't allowed yet. Allow it, then retry."` / `"🟡 <msg>"` / `"🔴 <msg>"` + `"Portal: <url>"`; `_subscription_render_upgrade_ambiguous` (`:736`) prints `"🟡 Couldn't confirm the upgrade — your card may or may not have been charged."` + `"Re-run /subscription to check your plan before trying again."` + `"Portal: <url>"`.
- **Rebuild notes:** Preview → confirm → apply, with scheduled (chargeless) and immediate (charged) paths kept visually distinct. A better version would show the exact proration line items from the preview.

### `/usage` — credits, rate limits and account usage  `id: providers.slash-usage`
- **Surface:** CLI / TUI / Gateway
- **Where:** Slash command `/usage`; `hermes_cli/cli_billing_mixin.py::_print_nous_credits_block` (`:23`) and `_print_usage_cta` (`:88`); data from `agent/account_usage.py`, `agent/billing_usage.py` and `agent/rate_limit_tracker.py`.
- **What it does:** Shows the plan name and renewal, the dollar usage bars, the total spendable balance, and the provider's live rate-limit windows.
- **How it works:** `_print_nous_credits_block()` prints `"  Plan: <plan><renews>"`, then the two usage bars (raw `print()` and `_cprint()` flush to different streams, so ordering is made deterministic deliberately), then `"  Total spendable: $<n>"`, then `"  > Free · free models only. Run /subscription to reach paid models."` on the free tier, then a low-balance line when applicable. `_print_usage_cta()` prints `"  Run /subscription to change plan · /topup to add to your balance"`. `agent/account_usage.py` supplies provider-specific windows: `AccountUsageWindow(label, used_percent, reset_at, detail)` and `AccountUsageSnapshot(provider, …)` rendered by `render_account_usage_lines(snapshot, *, markdown=False)` (`:95`), with `_format_reset(dt)` (`:75`) and `_fmt_usd(d)` (`:123`).
- **Inputs / options:** `fetch_account_usage(...)` (`:884`) dispatches per provider: `build_nous_credits_snapshot(account_info)` (`:137`) / `nous_credits_lines(*, markdown=False, timeout=10.0)` (`:233`) / `build_credits_view(*, markdown=False, timeout=10.0)` (`:358`, returning a `CreditsView`, `:342`); `_fetch_codex_account_usage(...)` (`:510`) using `_codex_backend_urls(base_url)` (`:428`), `_resolve_codex_usage_url(base_url)` (`:448`) and `_resolve_codex_usage_credentials(...)` (`:452`); `_fetch_anthropic_account_usage()` (`:751`); `_fetch_openrouter_account_usage(base_url, api_key)` (`:812`).
- **Outputs / side effects:** Text only. Rate-limit bars come from `format_rate_limit_display` / `format_rate_limit_compact`.
- **Config / env:** `display.credits_notices`.
- **Edge cases / guards:** `redeem_codex_reset_credit(...)` (`:587`) redeems a Codex window reset, returning `CodexResetRedeemResult` (`:567`); `_CODEX_WINDOW_EXHAUSTED_PERCENT = 100.0` (`:584`) marks an exhausted window.
- **Rebuild notes:** One snapshot dataclass per provider + a shared renderer.

### `hermes insights` — historical usage, cost and tool analytics  `id: providers.cli-insights`
- **Surface:** CLI
- **Where:** `hermes insights [--days DAYS] [--source SOURCE]`; implemented in `agent/insights.py` (1212 lines).
- **What it does:** Analyses session history to show token usage, costs, tool patterns and activity trends.
- **How it works:** Reads persisted session records and aggregates per day / model / tool, pricing them through `agent/usage_pricing.py`.
- **Inputs / options:** `--days DAYS` — number of days to analyse (default `30`); `--source SOURCE` — filter by platform (`cli`, `telegram`, `discord`, …). `-h/--help`.
- **Outputs / side effects:** A formatted terminal report.
- **Config / env:** n/a.
- **Edge cases / guards:** Models with no known pricing are reported without a cost rather than at $0.
- **Rebuild notes:** Session-log aggregation + the shared pricing table.

---

## 7. Fallback chain

### `hermes fallback` — fallback provider chain manager  `id: providers.cli-fallback`
- **Surface:** CLI
- **Where:** `hermes fallback [list|ls|add|remove|rm|clear]`; `hermes_cli/fallback_cmd.py` (377 lines), config helpers in `hermes_cli/fallback_config.py` (101 lines); docs `website/docs/user-guide/features/fallback-providers.md`.
- **What it does:** Manages the ordered list of backup provider:model pairs Hermes tries when the primary model fails with a rate-limit, overload, auth or connection error.
- **How it works:** `cmd_fallback(args)` (`:362`) dispatches: no subcommand / `list` / `ls` → `cmd_fallback_list`; `add` → `cmd_fallback_add`; `remove` / `rm` → `cmd_fallback_remove`; `clear` → `cmd_fallback_clear`; anything else prints `"Unknown fallback subcommand: <sub>"` + `"Use one of: list, add, remove, clear"` and exits 2. `get_fallback_chain(config)` (`fallback_config.py:80-101`) merges `fallback_providers` (primary source of truth, order preserved) with legacy `fallback_model` entries appended afterwards unless they target the same `(provider, model, base_url)` route — identity is lower-cased and the base URL is right-stripped of `/`. Entries missing `provider` or `model` are dropped. `resolve_entry_api_key(entry)` (`:14-40`) resolves an inline `api_key` first, else the env var named by `key_env` (alias `api_key_env`) **through `agent.secret_scope.get_secret`, not `os.getenv`** — in a multiplexed gateway a bare env read would ignore the active profile's scope and could return another profile's credential.
- **Inputs / options:** `hermes fallback list` prints `"  No fallback providers configured."` + `"  Add one with:  hermes fallback add"` when empty, else `"  Primary:   <primary>"`, `"  Fallback chain (<n> entry|entries):"`, a numbered list of `_format_entry(entry)`, `"  Tried in order when the primary fails (rate-limit, 5xx, connection errors)."` and `"  Docs: https://hermes-agent.nousresearch.com/docs/user-guide/features/fallback-providers"`. `hermes fallback add` prints `"  Adding a fallback provider.  The picker below is the same one used by"` / `"  \`hermes model\` — select the provider + model you want as a fallback."`, runs the `hermes model` picker, and refuses self-fallback with `"  Selected model matches the current primary (<entry>)."` + `"  A provider cannot be a fallback for itself — no change."`; a duplicate prints `"  <entry> is already in the fallback chain — skipped."`; success prints `"  Added fallback: <entry>"`, `"  Chain is now <n> entry|entries long."` and `"  Run \`hermes fallback list\` to view, or \`hermes fallback remove\` to delete."`. `hermes fallback remove` prints `"  No fallback providers configured — nothing to remove."` or, after a pick, `"  Removed fallback: <entry>"` + `"  Chain is now <n> …"` / `"  Fallback chain is now empty."`; cancelling prints `"  Cancelled — no change."`. `hermes fallback clear` lists the current chain, asks for confirmation, and prints `"  Fallback chain cleared."` or `"  Cancelled — no change."`. A curses-free environment falls back to `_numbered_pick(question, choices)` (`:337`) which prints the choices and prompts `"Choice [1-N]: "`, re-prompting with `"Please enter 1-N"` / `"Please enter a number"`.
- **Outputs / side effects:** Writes the top-level `fallback_providers:` list in `~/.hermes/config.yaml` (and migrates a legacy `fallback_model` on write). `_snapshot_auth_active_provider()` / `_restore_auth_active_provider()` (`:78-88`) and `_restore_model_cfg()` (`:250`) ensure running the picker for a fallback does not change the primary provider.
- **Config / env:** `fallback_providers` (list, default `[]`); legacy `fallback_model` (singular). **There are deliberately no environment variables for the primary fallback chain** — it is configured exclusively through `config.yaml` or `hermes fallback`, because fallback configuration is a deliberate choice, not something a stale shell export should override. Per-entry fields: `provider`, `model`, optional `base_url`, optional `api_key`, optional `key_env` / `api_key_env`.
- **Edge cases / guards:** When both `fallback_providers` and `fallback_model` are set, `fallback_providers` takes priority.
- **Rebuild notes:** An ordered list in config + the same picker as `hermes model` + identity-based dedup.

### Fallback chain semantics (runtime)  `id: providers.fallback-semantics`
- **Surface:** Core
- **Where:** Documented in `website/docs/user-guide/features/fallback-providers.md`; enforced in the agent loop and `hermes_cli/runtime_provider.py`.
- **What it does:** Switches provider:model mid-turn when the primary fails, preserving conversation history, tool calls and context.
- **How it works:** Three layers of resilience, tried in this order: (1) **credential pools** — rotate across multiple API keys for the *same* provider; (2) **primary model fallback** — switch to a *different* provider:model; (3) **auxiliary task fallback** — independent provider resolution for side tasks. Triggers, verbatim: rate limits (HTTP 429) after exhausting retry attempts; server errors (HTTP 500, 502, 503) after exhausting retry attempts; auth failures (HTTP 401, 403) immediately (no point retrying); not found (HTTP 404) immediately; invalid responses when the API returns malformed or empty responses repeatedly. On trigger Hermes (1) resolves credentials for the fallback provider, (2) builds a new API client, (3) swaps the model, provider and client in place, (4) resets the retry counter and continues.
- **Inputs / options:** `fallback_providers` entries; for `provider: custom` a `base_url` and optionally `key_env`.
- **Outputs / side effects:** A different model serves the rest of the turn.
- **Config / env:** Per the docs' provider table, the credential each supported fallback needs: `ai-gateway`→`AI_GATEWAY_API_KEY`; `openrouter`→`OPENROUTER_API_KEY`; `nous`→`hermes setup --portal` or `hermes auth add nous`; `openai-codex`→`hermes model` → **ChatGPT or Codex Subscription**; `copilot`→`COPILOT_GITHUB_TOKEN`/`GH_TOKEN`/`GITHUB_TOKEN`; `copilot-acp`→external process; `anthropic`→`ANTHROPIC_API_KEY` or Claude Code credentials; `zai`→`GLM_API_KEY`; `kimi-coding`→`KIMI_API_KEY`; `minimax`→`MINIMAX_API_KEY`; `minimax-cn`→`MINIMAX_CN_API_KEY`; `deepseek`→`DEEPSEEK_API_KEY`; `nvidia`→`NVIDIA_API_KEY` (optional `NVIDIA_BASE_URL`); `gmi`→`GMI_API_KEY` (optional `GMI_BASE_URL`); `upstage` (alias `solar`)→`UPSTAGE_API_KEY` (optional `UPSTAGE_BASE_URL`); `stepfun`→`STEPFUN_API_KEY` (optional `STEPFUN_BASE_URL`); `ollama-cloud`→`OLLAMA_API_KEY`; `gemini`→`GOOGLE_API_KEY` (alias `GEMINI_API_KEY`); `xai` (alias `grok`)→`XAI_API_KEY` (optional `XAI_BASE_URL`); `xai-oauth` (alias `grok-oauth`)→`hermes model` browser login (SuperGrok subscription); `bedrock`→standard boto3 auth (`AWS_REGION` + `AWS_PROFILE` or `AWS_ACCESS_KEY_ID`); `qwen-oauth`→`hermes model` (optional `HERMES_QWEN_BASE_URL`); `minimax-oauth`→`hermes model`; `opencode-zen`→`OPENCODE_ZEN_API_KEY`; `commandcode` (alias `commandcode-chat`; Claude via `commandcode-anthropic`)→`COMMANDCODE_API_KEY`; `opencode-go`→`OPENCODE_GO_API_KEY`; `opencode-free`→none (keyless); `kilocode`→`KILOCODE_API_KEY`; `router`→`RAMP_ROUTER_API_KEY`; `xiaomi`→`XIAOMI_API_KEY`; `arcee`→`ARCEEAI_API_KEY`; `nebius-token-factory`→`NEBIUS_API_KEY`; `alibaba`→`DASHSCOPE_API_KEY`; `alibaba-coding-plan`→`ALIBABA_CODING_PLAN_API_KEY` (falls back to `DASHSCOPE_API_KEY`); `kimi-coding-cn`→`KIMI_CN_API_KEY`; `tencent-tokenhub`→`TOKENHUB_API_KEY`; `tencent-tokenplan`→`TOKENPLAN_API_KEY`; `azure-foundry`→`AZURE_FOUNDRY_API_KEY` + `AZURE_FOUNDRY_BASE_URL`; `lmstudio`→`LM_API_KEY` (or none for local) + `LM_BASE_URL`; `huggingface`→`HF_TOKEN`; `custom`→`base_url` + `key_env`.
- **Edge cases / guards:** **Fallback resets the prompt cache** — caches are keyed to the model (and on most providers the account), so the first request after a switch re-reads the entire history at full input-token price instead of the ~75–90% discounted cached rate, and so does the first request back on the primary (unless its cache TTL has not expired). **Per-turn, not per-session** — each new user message starts with the primary restored; within one turn fallback activates at most once (if the fallback also fails, normal error handling takes over), which prevents cascading failover loops while giving the primary a fresh chance every turn. The per-turn retry is **reset-aware**: when the primary's credentials report a rate-limit reset time that has not elapsed (subscription windows such as Claude Pro/Max's 5-hour blocks or Codex weekly limits report hours or days), Hermes skips the doomed retry and stays on the fallback until the reset passes, avoiding two pointless provider switches (and two prompt-cache invalidations) per turn; transient 429s without a reset time keep the short-cooldown-then-retry-every-turn behaviour. Support matrix: CLI sessions ✔; messaging gateway (Telegram, Discord, …) ✔; subagent delegation ✔ (subagents inherit the parent chain); cron jobs ✔ (cron agents inherit configured fallback providers); auxiliary tasks on `provider: auto` ✔ (try per-task fallback, then the main fallback chain, before built-in aux discovery).
- **Rebuild notes:** Turn-scoped, single-shot, reset-aware failover with in-place client swap. A better version would pre-warm the fallback's prompt cache during the primary's cooldown.

---

## 8. Mixture of Agents (MoA)

### `/moa <prompt>` — one-shot Mixture-of-Agents turn  `id: providers.slash-moa`
- **Surface:** CLI / Gateway / TUI
- **Where:** Slash command `/moa <prompt>`; usage string (verbatim): `"Usage: /moa <prompt>  (runs one prompt through the default MoA preset, then restores your model; pick a preset from the model picker to switch for the session)"` (`hermes_cli/moa_config.py:508`).
- **What it does:** Runs one user turn through several "reference" advisor models in parallel, then hands their advice to an "aggregator" model that actually answers and drives the tool loop.
- **How it works:** The slash command is deliberately **not** a model tool — it marks one user turn as MoA-enabled while the normal Hermes agent loop still owns tool calling and turn termination; `agent/moa_loop.py` (2459 lines) gathers reference-model context before each model iteration. For frontends that can only send text, `encode_moa_turn(prompt, config, preset)` (`moa_config.py:478`) base64url-encodes `{"prompt": …, "config": <resolved preset>}` behind the marker `MOA_MARKER_PREFIX = "__HERMES_MOA_TURN_V1__"`, and `decode_moa_turn(message)` (`:490`) reverses it; `build_moa_turn_prompt()` (`:503`) is the TUI/gateway entry point. The virtual provider `moa` (`HERMES_OVERLAYS["moa"]`: `auth_type="virtual"`, `base_url="moa://local"`, label "Mixture of Agents") makes a preset selectable from the model picker for the whole session.
- **Inputs / options:** `<prompt>` (required). Preset fields (`_normalize_preset`, `:313-371`): `enabled` (bool, default `true`); `reference_models` (list of slots `{provider, model, enabled, …}`; accepts a JSON string or a single mapping from hand-edited YAML and degrades to defaults instead of crashing); `aggregator` (one slot); `reference_temperature` / `aggregator_temperature` (float or `None` — `None` means the parameter is omitted so the provider default applies, matching single-model behaviour); `reference_timeout` (`None` = inherit `auxiliary.moa_reference.timeout`, default 900 s; an explicit finite positive value is honoured as-is with no artificial cap, since long-thinking advisor models legitimately run far beyond five minutes); `degraded_reference_policy` (default `"loud"`); `max_tokens` (default `4096`); `reference_max_tokens` (`None` = uncapped; setting e.g. 600 makes advisors give concise advice — the dominant MoA latency is advisor generation, turn latency correlates ~0.88 with output tokens, and the aggregator only needs the gist, so capping roughly halves per-turn wall time; it does NOT cap the acting aggregator, whose output is the user-visible answer); `fanout` (cadence — `"user_turn"` (default, cheapest: advisors run ONCE per user turn, the original MoA shape, #67199), `"per_iteration"` (re-run whenever the advisory view changes, i.e. every tool iteration, multiplying advisor spend by tool-loop depth), or `"every_n:<N>"` with N ≥ 2 (advisors run on the first iteration of each user turn and every Nth tool iteration after it; in-between iterations reuse the cached guidance); the mapping form `{mode: every_n, n: N}` is accepted and normalised; `every_n:1` collapses to `per_iteration`; anything unparseable falls back to `user_turn`). Per-slot `reasoning_effort` is canonicalised by `_clean_reasoning_effort` (`:165`), where a disabled config becomes the string `"none"`.
- **Outputs / side effects:** Labelled reference blocks in the UI, a guidance block injected into the aggregator prompt, and optional trace files.
- **Config / env:** `moa.default_preset` (default `"default"`), `moa.active_preset` (default `""`), `moa.save_traces` (`false`), `moa.trace_dir` (`""`), `moa.privacy_filter` (`""`), `moa.presets.default.reference_models` (default `[{"provider": "openai-codex", "model": "gpt-5.5"}, {"provider": "openrouter", "model": "deepseek/deepseek-v4-pro"}]`), `moa.presets.default.aggregator.provider` (`"openrouter"`), `moa.presets.default.aggregator.model` (`"anthropic/claude-opus-4.8"`), `moa.presets.default.max_tokens` (`4096`), `moa.presets.default.enabled` (`true`); `auxiliary.moa_reference.{provider,model,base_url,api_key,timeout}` (timeout default `900`) and `auxiliary.moa_aggregator.{provider,model,base_url,api_key,timeout}` (timeout default `900`). Module constants: `DEFAULT_MOA_PRESET_NAME = "default"`, `DEFAULT_MOA_REFERENCE_MODELS = [{"provider": "openai-codex", "model": "gpt-5.5"}, {"provider": "openrouter", "model": "deepseek/deepseek-v4-pro"}]`, `DEFAULT_MOA_AGGREGATOR = {"provider": "openrouter", "model": "anthropic/claude-opus-4.8"}`, `DEFAULT_MOA_REFERENCE_TIMEOUT = None`.
- **Edge cases / guards:** `validate_moa_payload(raw)` (`:247`) returns a list of problems; `_slot_problem(slot)` (`:225`) explains a bad slot. `list_moa_presets(config)` (`:426`), `resolve_moa_preset(config, name)` (`:431`), `exact_moa_preset_name(config, text)` (`:446`), `set_active_moa_preset(config, name)` (`:469`).
- **Rebuild notes:** Parallel advisor fan-out + one aggregator + a cadence knob + an encoded one-shot marker. A better version would let advisors and the aggregator share a cache key so identical advisory views are not re-billed.

### MoA privacy filter  `id: providers.moa-privacy-filter`
- **Surface:** Config
- **Where:** `moa.privacy_filter`; `coerce_privacy_filter()` in `hermes_cli/moa_config.py:139-163`; redaction in `agent/moa_loop.py:26-60`.
- **What it does:** Redacts PII from advisor output before it reaches user-visible surfaces and, in the strongest mode, before it reaches the aggregator.
- **How it works:** Three values: `""` (empty string, the default — filter off; `false`/`None`/unknown values land here so a hand-edited config degrades to prior behaviour under the tolerant-read contract); `"display"` — redact user-visible surfaces only, i.e. the reference blocks shown in the UI and the saved MoA trace records, while the aggregator still sees raw advisor text so answer quality is unaffected; `"full"` — additionally redact the advisor text injected into the aggregator prompt (issue #59959's literal ask). A hand-edited boolean `true` maps to `"full"` because the issue framed the toggle as "redact before passing to the aggregator"; the strings `true`/`on`/`yes`/`1` also map to `"full"`. Secret and credential shapes (API-key prefixes, JWTs, private keys, DB connection strings, E.164 phone numbers) are handled by the repo's central redactor `agent.redact.redact_sensitive_text` — the MoA filter never re-implements those. Two extra patterns cover the PII classes the central redactor deliberately leaves alone for log/tool output: `_MOA_EMAIL_RE = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"` and `_MOA_PHONE_RE`, which requires clearly delimited formatting — a parenthesised area code and/or explicit `-`/`.` separators — so `(555) 123-4567`, `555-123-4567`, `555.123.4567` and `+1 555-123-4567` match while undelimited digit runs (`5551234567`), dates (`2026-07-12`), times (`12:34:56`), hex IDs, git SHAs, line numbers and dotted-quad IPs never do.
- **Inputs / options:** `""` | `"display"` | `"full"` (plus the tolerant aliases above).
- **Outputs / side effects:** Redacted advisor text in the chosen surfaces.
- **Config / env:** `moa.privacy_filter` (default `""`).
- **Edge cases / guards:** Advisory text is frequently code-review-shaped, which is why the phone pattern is deliberately conservative.
- **Rebuild notes:** Central redactor + two extra PII patterns + a three-state scope switch.

### MoA turn traces  `id: providers.moa-trace`
- **Surface:** Config
- **Where:** `agent/moa_trace.py` (182 lines); files at `<HERMES_HOME>/moa-traces/<session_id>.jsonl`.
- **What it does:** Appends one JSON line per MoA turn recording exactly what every model saw, what every model said, and what it cost — so a run can be audited end-to-end offline.
- **How it works:** Opt-in via `moa.save_traces`. When enabled, every MoA turn that actually runs the reference fan-out (a cache MISS in `MoAChatCompletions.create`) appends a record containing the exact `messages` array each reference model received (system prompt + advisory view, **not** the truncated display preview), each reference's full output, and the exact `messages` array the aggregator received (including the injected reference-context guidance block) plus its output when available. `_traces_enabled_and_dir()` (`:37-57`) reads config lazily per call (only on a cache-MISS turn, i.e. once per user turn, not per tool iteration) and honours `moa.trace_dir` with `expandvars`/`expanduser`. `_sanitize_session_id()` (`:60-64`) replaces every character that is not alphanumeric or one of `-_.` with `_`. `_slot_trace(acct, label)` (`:67`) renders one reference's accounting.
- **Inputs / options:** `moa.save_traces` (bool, default `false`), `moa.trace_dir` (string, default `""` → `<hermes_home>/moa-traces`).
- **Outputs / side effects:** JSONL files keyed by session id.
- **Config / env:** as above; `HERMES_HOME`.
- **Edge cases / guards:** This is a **side-channel** trace — it is NOT the conversation `messages` table and never enters message history or replay, because MoA references are advisory side-calls with their own system prompt and persisting them as message rows would corrupt role alternation and replay. Traces are safe to delete. Gated OFF by default; when off the only overhead is the cheap `_traces_enabled()` config read — no file I/O, no serialization.
- **Rebuild notes:** One JSONL append per fan-out with full inputs and outputs.

### `hermes moa` — MoA preset CLI  `id: providers.cli-moa`
- **Surface:** CLI
- **Where:** `hermes moa [list|ls|configure|config|delete|rm]`; `hermes_cli/moa_cmd.py` (152 lines).
- **What it does:** Lists, edits and deletes the named MoA presets used by `/moa`.
- **How it works:** `cmd_moa(args)` (`:94`) dispatches on `args`. `_print_config(config)` (`:78`) prints `"Mixture of Agents presets"`, `"Default: <default_preset>"`, `"Active in config: <active>"` (live: `"Active in config: (off)"` when none is active), then for each preset a marker (`*` for the default) + name, `"  Reference models:"` with a numbered `_format_slot(slot)` list rendered `provider:model`, and `"  Aggregator: <provider>:<model>"` — live example: `"* default"` / `"  Reference models:"` / `"    1. openai-codex:gpt-5.5"` / `"    2. openrouter:deepseek/deepseek-v4-pro"` / `"  Aggregator: openrouter:anthropic/claude-opus-4.8"`. `configure` prints `"Configure MoA preset: <name>"` and `"Pick at least one reference model; choose Done when finished."`, loops the picker built from `_model_options()` (`:29`) / `_pick_slot(current)` (`:52`) / `_prompt_choice(title, rows, default=0)` (`:12`), then `"Configure aggregator model."`, and finally `"Saved MoA preset: <name>"`. `delete` prints `"Deleted MoA preset: <name>"`.
- **Inputs / options:** `hermes moa list` (alias `ls`) — "Show current MoA model slots", no flags. `hermes moa configure [name]` (alias `config`) — positional `name` = "Preset name to create or update". `hermes moa delete <name>` (alias `rm`) — positional `name` = "Preset name to delete". All accept `-h/--help`.
- **Outputs / side effects:** Writes `moa.presets.<name>.*` in `config.yaml`.
- **Config / env:** `moa.presets.*`, `moa.default_preset`, `moa.active_preset`.
- **Edge cases / guards:** A preset with no valid reference slots falls back to `DEFAULT_MOA_REFERENCE_MODELS`.
- **Rebuild notes:** A small interactive editor over the preset schema.

---

## 9. Local OpenAI-compatible proxy

### `hermes proxy` — credential-attaching local proxy  `id: providers.cli-proxy`
- **Surface:** CLI
- **Where:** `hermes proxy [start|status|providers]`; `hermes_cli/proxy/cli.py` (140 lines), `hermes_cli/proxy/server.py` (298 lines), `hermes_cli/proxy/adapters/` (base + nous_portal + xai).
- **What it does:** Runs a local HTTP server that forwards OpenAI-compatible requests to an OAuth-authenticated provider (Nous Portal or xAI). External apps point at the proxy with **any** bearer token; the proxy attaches your real credentials.
- **How it works:** `run_server(adapter, host, port)` (`server.py:246`) mounts `GET /health` (`handle_health`, `:101`) and a catch-all `app.router.add_route("*", "/v1/{tail:.*}", handle_proxy)` (`:241`). `handle_proxy` (`:110`) extracts the path after `/v1`, rejects anything not in `adapter.allowed_paths` with a 404 whose body says `"Path /v1<rel_path> is not forwarded by this proxy. "` plus the allowed list, then forwards to `<upstream base_url><rel_path>` with the client's `Authorization` replaced by a freshly-resolved bearer. `_HOP_BY_HOP_HEADERS` (stripped): `host`, `content-length`, `connection`, `keep-alive`, `proxy-authenticate`, `proxy-authorization`, `te`, `trailers`, `transfer-encoding`, `upgrade`, and `authorization` (replaced). Everything else — content-type, accept, user-agent, `x-*` headers — passes through. Responses are streamed back unmodified, preserving SSE. The server is intentionally minimal: it does NOT mediate, log, transform or rewrite bodies. `_send_upstream` / `_open_upstream` (`:138`, `:170`) support a one-shot retry with `adapter.get_retry_credential(...)` after an auth failure.
- **Inputs / options:** `hermes proxy start [--provider PROVIDER] [--host HOST] [--port PORT]` — `--provider`: "Upstream provider: nous or xai (default: nous). See `hermes proxy providers`."; `--host`: "Bind address (default: 127.0.0.1). Use 0.0.0.0 to expose on LAN."; `--port`: "Bind port (default: 8645)". `hermes proxy status` — "Show which proxy upstreams are ready". `hermes proxy providers` (alias `list`) — "List available proxy upstream providers". All accept `-h/--help`.
- **Outputs / side effects:** `start` prints to stderr: `"Starting Hermes proxy for <display_name>"`, `"  Listening on:  http://<host>:<port>/v1"`, `"  Forwarding to: (resolved per-request from your subscription)"`, `"  Use any bearer token in the client — the proxy attaches your real credential."`, `"Press Ctrl+C to stop."`; on Ctrl+C `"proxy: stopped"`; on a bind failure `"proxy: failed to bind <host>:<port>: <exc>"` and exit 1. `status` prints `"Hermes proxy upstream adapters"` then one line per adapter, the name left-padded to 8 characters — `"  [nous    ] Nous Portal — not logged in"`, `"  [<name>    ] <display_name> — credentials need attention (<exc>)"`, or `"  [<name>    ] <display_name> — ready (bearer expires <ts>)"` — and finally `"Start the proxy with: hermes proxy start [--provider <name>]"`. `providers` prints `"Available proxy upstream providers:"` then `"  <name>  — <display_name>"` (live: `"  nous  — Nous Portal"` and `"  xai  — xAI Grok OAuth"`). With no subcommand it prints the short help block listing all three subcommands. A missing `aiohttp` prints `"hermes proxy requires aiohttp. Run \`hermes setup\` to install it."` to stderr and exits 1. An unknown provider prints `"Error: Unknown proxy upstream provider: <name>. Available: nous, xai"` and exits 2. Not being logged in prints `"Not logged into <display_name>. Run \`<auth_hint>\` first."` and exits 2.
- **Config / env:** `DEFAULT_HOST = "127.0.0.1"`, `DEFAULT_PORT = 8645`, `MAX_REQUEST_BYTES = 10_000_000` (mirrors the API server's cap; `client_max_size` bounds every read path including chunked bodies).
- **Edge cases / guards:** Path allow-lists per adapter keep stray clients from leaking weird requests upstream.
- **Rebuild notes:** An aiohttp reverse proxy with a per-provider credential adapter and a path allow-list. A better version would support more than one upstream at once, keyed by the client's bearer.

### Proxy upstream adapters  `id: providers.proxy-adapters`
- **Surface:** Core
- **Where:** `hermes_cli/proxy/adapters/__init__.py` (registry), `base.py` (contract), `nous_portal.py`, `xai.py`.
- **What it does:** Wraps one OAuth-authenticated provider so the proxy server stays provider-agnostic.
- **How it works:** `ADAPTERS = {"nous": NousPortalAdapter, "xai": XAIGrokAdapter}`; `get_adapter(name)` lower-cases and raises `ValueError("Unknown proxy upstream provider: <name>. Available: nous, xai")`. `UpstreamCredential` (frozen dataclass): `bearer` (token only, no `Bearer` prefix), `base_url` (e.g. `https://inference-api.nousresearch.com/v1`), `token_type` (currently always `"Bearer"`), `expires_at` (ISO-8601, informational). `UpstreamAdapter` (ABC) requires `name`, `display_name`, `allowed_paths`, `is_authenticated()`, `get_credential()`, `get_retry_credential(...)`.
- **Inputs / options:** **NousPortalAdapter** — `name="nous"`, `display_name="Nous Portal"`, allowed paths `{"/chat/completions", "/completions", "/embeddings", "/models"}`; serialises requests in-process with a `threading.Lock` while cross-process token refresh and persistence are handled by `resolve_nous_runtime_credentials()`; validates the inference URL with `_validate_nous_inference_url_from_network()` and honours `_nous_inference_env_override()`; can quarantine bad state via `_quarantine_nous_oauth_state` / `_quarantine_nous_pool_entries`. **XAIGrokAdapter** — `name="xai"`, `display_name="xAI Grok OAuth"`, `auth_hint="hermes auth add xai-oauth --type oauth"`, allowed paths `{"/responses", "/chat/completions", "/completions", "/embeddings", "/models"}`; reads the credential pool (`is_authenticated()` = `pool.has_available()`) and falls back to `DEFAULT_XAI_OAUTH_BASE_URL` when the entry carries no base URL.
- **Outputs / side effects:** Token refresh writes back to the auth store.
- **Config / env:** `NOUS_INFERENCE_BASE_URL`; the credential pool in `auth.json`.
- **Edge cases / guards:** Requests to a path outside the adapter's allow-list get a 404 with a helpful error body.
- **Rebuild notes:** One ABC + a name→class registry. A better version would let a provider plugin register its own proxy adapter.

---

## 10. The model picker

### `hermes model` — interactive provider + model picker  `id: providers.cli-model`
- **Surface:** CLI
- **Where:** `hermes model [--refresh] [--portal-url] [--inference-url] [--client-id] [--scope] [--no-browser] [--timeout] [--ca-bundle] [--insecure]`; `hermes_cli/main.py::cmd_model` (`:3789`) → `select_provider_and_model(args)` (`:3823`).
- **What it does:** "Interactively select your inference provider and default model" — a two-step picker (provider, then model) that also prompts for the credential the chosen provider needs and writes the result to config.
- **How it works:** `_require_tty("model")` gates it. `--refresh` calls `hermes_cli.models.clear_provider_models_cache()` and prints `"  Cleared model picker cache."`. The whole flow runs inside `run_setup_action_with_navigation("Model & Provider", …, cancelled_message="No change.")`. `select_provider_and_model` reads the effective provider exactly as the CLI does at startup — `config.yaml model.provider` → env `HERMES_INFERENCE_PROVIDER` → `"auto"` — then prints `"  Current model:    <model>"` and `"  Active provider:  <label>"`. Step 1 builds the provider rows from `CANONICAL_PROVIDERS`, folded by `group_providers()`, filtered by `model_catalog.excluded_providers` (a canonical provider is hidden if its slug **or any alias** appears in the list, case-insensitively). The active row is suffixed `"  ← currently active"` and pre-selected. Step 2 dispatches to a provider-specific credential flow; `_is_profile_api_key_provider(provider_id)` (`:3808`) is the catch-all, so **adding `plugins/model-providers/<name>/` is sufficient to expose a new provider** in the picker with no edits to `main.py`.
- **Inputs / options:** Flags (all from live `--help`): `--refresh` — "Wipe the model picker disk cache and re-fetch every provider's live /v1/models list."; `--portal-url PORTAL_URL` — "Portal base URL for Nous login (default: production portal)"; `--inference-url INFERENCE_URL` — "Inference API base URL for Nous login (default: production inference API)"; `--client-id CLIENT_ID` — "OAuth client id to use for Nous login (default: hermes-cli)"; `--scope SCOPE` — "OAuth scope to request for Nous login"; `--no-browser` — "Do not attempt to open the browser automatically during Nous login"; `--timeout TIMEOUT` — "HTTP request timeout in seconds for Nous login (default: 15)"; `--ca-bundle CA_BUNDLE` — "Path to CA bundle PEM file for Nous TLS verification"; `--insecure` — "Disable TLS verification for Nous login (testing only)"; `-h, --help`. Trailing action rows appended after the provider list, verbatim: `"Custom endpoint (enter URL manually)"` (key `custom`); `"Remove a saved custom provider"` (key `remove-custom`, only when `custom_providers` is a non-empty list); `"Configure auxiliary models..."` (key `aux-config`); `"Leave unchanged"` (key `cancel` → prints `"No change."`). Saved custom providers render as `"<name> (<host+path>) — <saved model>"`.
- **Outputs / side effects:** Writes `model.provider`, `model.default`, `model.base_url`, `model.api_mode` (and credentials via the auth store / `.env`) into `~/.hermes/config.yaml`.
- **Config / env:** `HERMES_INFERENCE_PROVIDER`; `model_catalog.excluded_providers`; `custom_providers`.
- **Edge cases / guards:** Non-TTY invocation is refused. Groups collapse to a single row when only one member is present ("no pointless one-item submenu").
- **Rebuild notes:** Canonical provider list + display grouping + per-auth-type credential flows + a live/curated model list. A better version would show price and context length inline for every model row.

### Canonical provider list (picker rows)  `id: providers.canonical-provider-list`
- **Surface:** CLI / Gateway / TUI
- **Where:** `hermes_cli/models.py:1306-1350` (`CANONICAL_PROVIDERS`), the single source of truth for provider identity used by `hermes model`, `/model` and `list_authenticated_providers`.
- **What it does:** Defines the ordered rows the picker shows, each with a slug, a short label and a long description.
- **How it works:** `ProviderEntry = NamedTuple(slug, label, tui_desc)`. `_PROVIDER_LABELS` is derived from it, plus the special case `_PROVIDER_LABELS["custom"] = "Custom endpoint"`. The list auto-extends from the plugin registry: every registered profile whose name is not already present and whose `auth_type` is **not** in `{oauth_device_code, oauth_external, external_process, aws_sdk, copilot, vertex}` (those need bespoke picker UX) is appended as `ProviderEntry(name, display_name or name, description or "<label> (direct API)")`.
- **Inputs / options:** The 40 declared entries, verbatim `slug` → `label` → `tui_desc`: `nous` → "Nous Portal" → "Nous Portal (Everything your agent needs, 300+ models with bundled tool use)"; `fireworks` → "Fireworks AI" → "Fireworks AI (OpenAI-compatible direct model API)"; `openrouter` → "OpenRouter" → "OpenRouter (Pay-per-use API aggregator)"; `moa` → "Mixture of Agents" → "Mixture of Agents (named presets; aggregator acts after reference models)"; `novita` → "NovitaAI" → "NovitaAI (Cloud: Model API, Agent Sandbox, GPU Cloud)"; `lmstudio` → "LM Studio" → "LM Studio (Local desktop app with built-in model server)"; `anthropic` → "Anthropic" → "Anthropic (Claude models via API key or Claude Code)"; `openai-codex` → "ChatGPT or Codex Subscription" → "ChatGPT or Codex Subscription (Sign in with your ChatGPT account, uses Codex models)"; `openai-api` → "OpenAI API" → "OpenAI API (api.openai.com, API key)"; `alibaba` → "Qwen Cloud" → "Qwen Cloud / DashScope (Qwen + multi-provider)"; `xai-oauth` → "xAI Grok OAuth (SuperGrok / Premium+)" → "xAI Grok OAuth (SuperGrok / Premium+ subscription)"; `xiaomi` → "Xiaomi MiMo" → "Xiaomi MiMo (MiMo-V2.5 and V2 models: pro, omni, flash)"; `tencent-tokenhub` → "Tencent TokenHub" → "Tencent TokenHub (Hy4 preview via tokenhub.tencentmaas.com)"; `tencent-tokenplan` → "Tencent TokenPlan" → "Tencent TokenPlan (Hy4 preview via api.lkeap.cloud.tencent.com, Anthropic Messages)"; `nvidia` → "NVIDIA NIM" → "NVIDIA NIM (Nemotron models via build.nvidia.com or local NIM)"; `copilot` → "GitHub Copilot" → "GitHub Copilot (Uses GITHUB_TOKEN or gh auth token)"; `copilot-acp` → "GitHub Copilot ACP" → "GitHub Copilot ACP (Spawns copilot --acp --stdio)"; `huggingface` → "Hugging Face" → "Hugging Face Inference Providers"; `gemini` → "Google AI Studio" → "Google AI Studio (Native Gemini API)"; `vertex` → "Google Vertex AI" → "Google Vertex AI (Gemini via GCP; OAuth2 service account or ADC, GCP billing/quotas)"; `deepseek` → "DeepSeek" → "DeepSeek (V3, R1, coder, direct API)"; `xai` → "xAI" → "xAI Grok (Direct API)"; `zai` → "Z.AI / GLM" → "Z.AI / GLM (Zhipu direct API)"; `kimi-coding` → "Kimi / Kimi Coding Plan" → "Kimi Coding Plan (api.kimi.com & Moonshot API)"; `kimi-coding-cn` → "Kimi / Moonshot (China)" → "Kimi / Moonshot China (Domestic direct API)"; `stepfun` → "StepFun Step Plan" → "StepFun Step Plan (Agent / coding models via Step Plan API)"; `minimax` → "MiniMax" → "MiniMax (Global direct API)"; `minimax-oauth` → "MiniMax (OAuth)" → "MiniMax via OAuth browser login (Coding Plan, minimax.io)"; `minimax-cn` → "MiniMax (China)" → "MiniMax China (Domestic direct API)"; `ollama-cloud` → "Ollama Cloud" → "Ollama Cloud (Cloud-hosted open models, ollama.com)"; `arcee` → "Arcee AI" → "Arcee AI (Trinity models, direct API)"; `gmi` → "GMI Cloud" → "GMI Cloud (Multi-model direct API)"; `kilocode` → "Kilo Code" → "Kilo Code (Kilo Gateway API)"; `opencode-zen` → "OpenCode Zen" → "OpenCode Zen (Curated models, pay-as-you-go)"; `opencode-go` → "OpenCode Go" → "OpenCode Go (Open models subscription)"; `bedrock` → "AWS Bedrock" → "AWS Bedrock (Claude, Nova, Llama, DeepSeek; IAM or API key)"; `azure-foundry` → "Azure Foundry" → "Azure Foundry (OpenAI-style or Anthropic-style endpoint, your Azure AI deployment)"; `ai-gateway` → "Vercel AI Gateway" → "Vercel AI Gateway (Multi-model aggregator)"; `qwen-oauth` → "Qwen OAuth (Portal)" → "Qwen OAuth (Reuses local Qwen CLI login)".
- **Outputs / side effects:** Drives every picker surface.
- **Config / env:** n/a.
- **Edge cases / guards:** Auto-injected plugin providers inherit their `display_name`/`description`; a profile with neither gets `"<name> (direct API)"`.
- **Rebuild notes:** A named-tuple list plus a registry auto-extend hook.

### Provider display groups  `id: providers.provider-groups`
- **Surface:** CLI / Gateway / TUI
- **Where:** `hermes_cli/models.py:1395-1406` (`PROVIDER_GROUPS`), `provider_group_for_slug()` (`:1413`), `group_providers()` (`:1418`).
- **What it does:** Folds vendors that expose several Hermes slugs (one per endpoint / auth method) under one top-level picker row so the list stays short.
- **How it works:** **DISPLAY ONLY** — grouping does not change `CANONICAL_PROVIDERS`, slug identity, the `--provider` flag, `/model <provider:model>`, or any typed path; every member slug remains individually addressable. `group_providers()` is the single fold used by all three picker surfaces (`hermes model`, the setup wizard, the Telegram `/model` keyboard) so they stay consistent. Rules: a group row appears at the position of its FIRST present member in the input order and subsequent members fold into it; member order inside a group follows the `PROVIDER_GROUPS` declaration restricted to members actually present; a group reduced to a single present member degrades to a `single` row; ungrouped slugs pass through in order; duplicate slugs are ignored after first sight. A group row's label is rendered `"<label> ▸ (<group_description>)"`, or `"<label> ▸"` when there is no description.
- **Inputs / options:** The nine groups, verbatim `group_id → (label, description, members)`: `kimi` → ("Kimi / Moonshot", "Coding Plan, Moonshot global & China endpoints", `["kimi-coding", "kimi-coding-cn"]`); `minimax` → ("MiniMax", "Global, OAuth Coding Plan & China endpoints", `["minimax", "minimax-oauth", "minimax-cn"]`); `xai` → ("xAI Grok", "Direct API or SuperGrok / Premium+ OAuth", `["xai", "xai-oauth"]`); `google` → ("Google Gemini", "Google AI Studio (API key)", `["gemini"]`); `openai` → ("OpenAI", "ChatGPT/Codex subscription or direct OpenAI API", `["openai-codex", "openai-api"]`); `qwen` → ("Qwen", "Qwen Cloud / DashScope, Coding Plan, Token Plan & Qwen CLI OAuth", `["alibaba", "alibaba-cn", "alibaba-coding-plan", "alibaba-coding-plan-cn", "alibaba-token-plan", "alibaba-token-plan-cn", "qwen-oauth"]`); `opencode` → ("OpenCode", "Zen pay-as-you-go, Go subscription, or free tier", `["opencode-zen", "opencode-go", "opencode-free"]`); `copilot` → ("GitHub Copilot", "GitHub token API or copilot --acp process", `["copilot", "copilot-acp"]`); `tencent` → ("Tencent Hy", "Hy4 / Hy3 via TokenHub & TokenPlan", `["tencent-tokenhub", "tencent-tokenplan"]`).
- **Outputs / side effects:** Picker rows of `{"kind": "single", "slug": …}` or `{"kind": "group", "group_id", "label", "description", "members"}`.
- **Config / env:** n/a.
- **Edge cases / guards:** `_SLUG_TO_GROUP` is built once at import.
- **Rebuild notes:** A declaration dict + one fold function shared by all pickers.

### `hermes setup model` — model section of the setup wizard  `id: providers.setup-model`
- **Surface:** CLI
- **Where:** `hermes setup model` (one of the sections `model|tts|terminal|gateway|tools|telemetry|agent`); `setup_model_provider` in `hermes_cli/setup.py` calls the same `select_provider_and_model()`.
- **What it does:** Runs only the provider+model part of the setup wizard.
- **How it works:** Shares the picker with `hermes model`, so the provider list, credential prompts and validation are identical.
- **Inputs / options:** `hermes setup [--non-interactive] [--reset] [--reconfigure] [--quick] [--portal] [{model,tts,terminal,gateway,tools,telemetry,agent}]`. `--non-interactive` — "Non-interactive mode (use defaults/env vars)"; `--reset` — "Reset configuration to defaults"; `--reconfigure` — "(Default on existing installs.) Re-run the full wizard, showing current values as defaults. Kept for backwards compatibility — a bare 'hermes setup' now does this."; `--quick` — "On existing installs: only prompt for items that are missing or unset, instead of running the full reconfigure wizard."; `--portal` — "One-shot Nous Portal setup: log in via OAuth, pick a Nous model, set Nous as the inference provider, and opt into the Tool Gateway. Skips the rest of the wizard."
- **Outputs / side effects:** Same config writes as `hermes model`.
- **Config / env:** Same.
- **Edge cases / guards:** `--portal` short-circuits the rest of the wizard and is identical to `hermes portal`.
- **Rebuild notes:** Reuse the one picker for both entry points.

---

## 11. OAuth logins and the Nous Portal

### Provider auth registry (`hermes_cli/auth.py`)  `id: providers.auth-registry`
- **Surface:** Core
- **Where:** `hermes_cli/auth.py` (9541 lines) — `PROVIDER_REGISTRY: Dict[str, ProviderConfig]` (`:247+`).
- **What it does:** Declares each provider's auth type, portal/inference URLs, OAuth client id and scope, and the env vars an API-key provider checks.
- **How it works:** `ProviderConfig` dataclass (`:233-246`): `id`, `name`, `auth_type` (`"oauth_device_code"` | `"oauth_external"` | `"oauth_minimax"` | `"api_key"`), `portal_base_url`, `inference_base_url`, `client_id`, `scope`, `extra` (dict), `api_key_env_vars` (tuple, priority order), `base_url_env_var`. `auth.py` extends this registry with every api-key `ProviderProfile` it sees, skipping `copilot`, `kimi-coding`, `kimi-coding-cn`, `zai`, `openrouter` and `custom` (those need bespoke token resolution).
- **Inputs / options:** Constants (`:112-193`), verbatim: `DEFAULT_NOUS_PORTAL_URL = "https://portal.nousresearch.com"`; `DEFAULT_NOUS_INFERENCE_URL = "https://inference-api.nousresearch.com/v1"`; `DEFAULT_NOUS_CLIENT_ID = "hermes-cli"`; `NOUS_INFERENCE_INVOKE_SCOPE = "inference:invoke"`; `NOUS_BILLING_MANAGE_SCOPE = "billing:manage"`; `DEFAULT_NOUS_SCOPE = NOUS_INFERENCE_INVOKE_SCOPE`; `NOUS_DEVICE_CODE_SOURCE = "device_code"`; `NOUS_AUTH_PATH_INVOKE_JWT = "invoke_jwt"`; `ACCESS_TOKEN_REFRESH_SKEW_SECONDS = 120`; `NOUS_INVOKE_JWT_MIN_TTL_SECONDS = 120`; `DEVICE_AUTH_POLL_INTERVAL_CAP_SECONDS = 1`; `AUTH_LOCK_TIMEOUT_SECONDS = 15.0`; `DEFAULT_CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"`; `CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"`; `CODEX_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"`; `CODEX_OAUTH_USER_AGENT = "hermes-cli/<version>"`; `CODEX_ACCESS_TOKEN_REFRESH_SKEW_SECONDS = 120`; `DEFAULT_XAI_OAUTH_BASE_URL = "https://api.x.ai/v1"`; `XAI_OAUTH_ISSUER = "https://auth.x.ai"`; `XAI_OAUTH_DISCOVERY_URL = "https://auth.x.ai/.well-known/openid-configuration"`; `XAI_OAUTH_CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"`; `XAI_OAUTH_SCOPE = "openid profile email offline_access grok-cli:access api:access"`; `XAI_OAUTH_DEVICE_CODE_URL = "https://auth.x.ai/oauth2/device/code"`; `XAI_ACCESS_TOKEN_REFRESH_SKEW_SECONDS = 3600` (xAI/Grok access tokens are ~6 h in current SuperGrok flows, and a two-minute window is too narrow for gateway/cron workloads that only touch the provider every 30 minutes, so Hermes refreshes up to an hour early); `MINIMAX_OAUTH_CLIENT_ID = "78257093-7e40-4613-99e0-527b14b39113"`; `MINIMAX_OAUTH_SCOPE = "group_id profile model.completion"`; `MINIMAX_OAUTH_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:user_code"`; `MINIMAX_OAUTH_GLOBAL_BASE = "https://api.minimax.io"`; `MINIMAX_OAUTH_CN_BASE = "https://api.minimaxi.com"`; `MINIMAX_OAUTH_GLOBAL_INFERENCE = "https://api.minimax.io/anthropic"`; `MINIMAX_OAUTH_CN_INFERENCE = "https://api.minimaxi.com/anthropic"`; `MINIMAX_OAUTH_REFRESH_SKEW_SECONDS = 60`; `QWEN_OAUTH_CLIENT_ID = "f0304373b74a44d2b584a3fb70ca9e56"`; `QWEN_OAUTH_TOKEN_URL = "https://chat.qwen.ai/api/v1/oauth2/token"`; `QWEN_ACCESS_TOKEN_REFRESH_SKEW_SECONDS = 120`; `DEFAULT_QWEN_BASE_URL = "https://portal.qwen.ai/v1"`; `DEFAULT_GITHUB_MODELS_BASE_URL = "https://api.githubcopilot.com"`; `DEFAULT_COPILOT_ACP_BASE_URL = "acp://copilot"`; `DEFAULT_OLLAMA_CLOUD_BASE_URL = "https://ollama.com/v1"`; `DEFAULT_ACTUAL_BASE_URL = "https://api.actual.inc/v1"`; `DEFAULT_ACTUAL_LOCAL_BASE_URL = "http://127.0.0.1:8080/v1"`; `STEPFUN_STEP_PLAN_INTL_BASE_URL = "https://api.stepfun.ai/step_plan/v1"`; `STEPFUN_STEP_PLAN_CN_BASE_URL = "https://api.stepfun.com/step_plan/v1"`; `KIMI_CODE_BASE_URL = "https://api.kimi.com/coding"`; `OAUTH_OVER_SSH_DOCS_URL = "https://hermes-agent.nousresearch.com/docs/guides/oauth-over-ssh"`; `LMSTUDIO_NOAUTH_PLACEHOLDER = "dummy-lm-api-key"` and `ACTUAL_LOCAL_NOAUTH_PLACEHOLDER = "dummy-actual-local-api-key"` (LM Studio's default no-auth mode still requires *some* non-empty bearer for the API-key code paths to treat the provider as configured; these sentinels are sent only to those local servers, never to a remote service). Registry entries observed: `nous` (Nous Portal, `oauth_device_code`), `openai-codex` (OpenAI Codex, `oauth_external`), `openai-api` (OpenAI API, `api_key`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`), `xai-oauth` (xAI Grok OAuth (SuperGrok / Premium+), `oauth_external`), `qwen-oauth` (Qwen OAuth, `oauth_external`), `lmstudio` (LM Studio, `api_key`, `LM_API_KEY`, `LM_BASE_URL`), `copilot` (GitHub Copilot, `api_key`, `COPILOT_GITHUB_TOKEN`/`GH_TOKEN`/`GITHUB_TOKEN`, `COPILOT_API_BASE_URL`), `minimax-oauth` (region-aware with `extra={"region": "global", "cn_portal_base_url": …, "cn_inference_base_url": …}`), `anthropic` (`api_key` with `ANTHROPIC_API_KEY`/`ANTHROPIC_TOKEN`/`CLAUDE_CODE_OAUTH_TOKEN` — note `CLAUDE_CODE_OAUTH_TOKEN` is NOT an API key despite `auth_type="api_key"`), `alibaba` (`DASHSCOPE_API_KEY`, `DASHSCOPE_BASE_URL`), `alibaba-coding-plan` (`ALIBABA_CODING_PLAN_API_KEY`, `DASHSCOPE_API_KEY`), and the auto-extended api-key profiles.
- **Outputs / side effects:** Reads/writes `~/.hermes/auth.json` under a file lock.
- **Config / env:** `NOUS_INFERENCE_BASE_URL` override via `_nous_inference_env_override()`.
- **Edge cases / guards:** `is_actual_local_base_url(base_url)` (`:195`) and `normalize_actual_base_url(base_url)` (`:205`) treat `localhost`/`127.0.0.1`/`::1`/`0.0.0.0` as Actual's loopback local API.
- **Rebuild notes:** One dataclass per provider + a registry + per-auth-type flows.

### `hermes auth` — credential management  `id: providers.cli-auth`
- **Surface:** CLI
- **Where:** `hermes auth {add,list,remove,reset,status,logout,spotify}`; `hermes_cli/auth_commands.py` (901 lines).
- **What it does:** Adds, lists, removes and inspects the pooled credentials for every provider, and clears exhaustion state.
- **How it works:** Each subcommand operates on the credential pool in `~/.hermes/auth.json`, routing removals through `agent/credential_sources.py`.
- **Inputs / options:** `hermes auth add <provider> [--type {oauth,api-key,api_key}] [--label LABEL] [--api-key API_KEY] [--portal-url PORTAL_URL] [--inference-url INFERENCE_URL] [--client-id CLIENT_ID] [--scope SCOPE] [--no-browser] [--timeout TIMEOUT] [--insecure] [--ca-bundle CA_BUNDLE]` — positional `provider`: "Provider id (for example: anthropic, openai-codex, openrouter)"; `--type`: "Credential type to add"; `--label`: "Optional display label"; `--api-key`: "API key value (otherwise prompted securely)"; `--portal-url`: "Nous portal base URL"; `--inference-url`: "Nous inference base URL"; `--client-id`: "OAuth client id"; `--scope`: "OAuth scope override"; `--no-browser`: "Do not auto-open a browser for OAuth login"; `--timeout`: "OAuth/network timeout in seconds"; `--insecure`: "Disable TLS verification for OAuth login"; `--ca-bundle`: "Custom CA bundle for OAuth login". `hermes auth list [provider]` — optional positional "Optional provider filter". `hermes auth remove <provider> <target>` — "Credential index, entry id, or exact label". `hermes auth reset <provider>` — "Clear exhaustion status for all credentials for a provider". `hermes auth status <provider>` — "Show auth status for a provider". `hermes auth logout <provider>` — "Log out a provider and clear stored auth state". `hermes auth spotify` — "Authenticate Hermes with Spotify via PKCE" (out of this shard's scope beyond the listing).
- **Outputs / side effects:** Writes `auth.json`, `.env`, and provider-specific OAuth files.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** `hermes auth add nous --type oauth` is the canonical form `hermes portal` aliases.
- **Rebuild notes:** Seven subcommands over one JSON store.

### `hermes login` (deprecated) and `hermes logout`  `id: providers.cli-login-logout`
- **Surface:** CLI
- **Where:** `hermes login [...]`, `hermes logout [--provider {nous,openai-codex,xai-oauth,spotify}]`.
- **What it does:** `login` is deprecated — its help says "Deprecated. Use `hermes auth` to manage credentials, `hermes model` to select a provider, or `hermes setup` for full setup."; `logout` removes stored credentials and resets provider config.
- **How it works:** `login` still accepts the Nous OAuth flags for back-compat; `logout` clears the named provider's state (defaulting to the active provider).
- **Inputs / options:** `hermes login [--provider PROVIDER] [--portal-url PORTAL_URL] [--inference-url INFERENCE_URL] [--client-id CLIENT_ID] [--scope SCOPE] [--no-browser] [--timeout TIMEOUT] [--ca-bundle CA_BUNDLE] [--insecure]` — `--provider`: "(deprecated) Provider name; ignored — see `hermes model`"; `--portal-url`: "Portal base URL (default: production portal)"; `--inference-url`: "Inference API base URL (default: production inference API)"; `--client-id`: "OAuth client id to use (default: hermes-cli)"; `--scope`: "OAuth scope to request"; `--no-browser`: "Do not attempt to open the browser automatically"; `--timeout`: "HTTP request timeout in seconds (default: 15)"; `--ca-bundle`: "Path to CA bundle PEM file for TLS verification"; `--insecure`: "Disable TLS verification (testing only)". `hermes logout [--provider {nous,openai-codex,xai-oauth,spotify}]` — "Provider to log out from (default: active provider)".
- **Outputs / side effects:** Deletes credential state.
- **Config / env:** n/a.
- **Edge cases / guards:** The `logout --provider` choice list is a fixed four-value enum.
- **Rebuild notes:** Thin wrappers over the auth store.

### `hermes portal` — Nous Portal onboarding & discovery  `id: providers.cli-portal`
- **Surface:** CLI
- **Where:** `hermes portal [login|info|status|open|tools]`; `hermes_cli/portal_cli.py` (246 lines).
- **What it does:** Logs into Nous Portal and sets it up in one shot — OAuth login, pick a Nous model, switch the inference provider to Nous, and offer the Tool Gateway — plus discovery subcommands for auth state and tool routing.
- **How it works:** `portal_command(args)` (`:191`) dispatches: none / `login` → `_cmd_login` (`:170`), which calls `hermes_cli.setup._run_portal_one_shot(config)` — the exact wiring behind `hermes setup --portal`, which in turn runs the same Nous flow as the first-time quick setup, so the commands stay in lockstep (device-code login, pick a Nous model, switch provider to Nous, offer the Tool Gateway opt-in); `info` or `status` (a back-compat alias for the prior default) → `_cmd_status` (`:34`); `open` → `_cmd_open` (`:107`); `tools` → `_cmd_tools` (`:122`); anything else prints `"Unknown portal subcommand: <sub>"` and `"Run \`hermes portal -h\` for usage."` to stderr and returns 1. `_cmd_status` uses `get_nous_auth_status_local()` — a **refresh-free** snapshot with no OAuth refresh, because it is a read-only status display.
- **Inputs / options:** Sub-parser help strings, verbatim: `login` — "Log in to Nous Portal + set it up (default; one-shot onboarding)"; `info` — "Show Portal auth + Tool Gateway routing summary"; `status` (hidden back-compat alias, no help); `open` — "Open the Portal subscription page in your default browser"; `tools` — "List Tool Gateway tools and which are routed via Nous". Top-level help: "Set up Nous Portal (login, model pick, Tool Gateway); see also `portal info`".
- **Outputs / side effects:** `info` prints the block `"  Nous Portal"` / `"  ───────────"` then `"  Auth:    ✓ logged in"` + `"  Portal:  <portal_base_url>"` + `"  API:     <inference_base_url>"`, or `"  Auth:    not logged in"` + `"  Sign up: https://portal.nousresearch.com/manage-subscription"` + `"  Login:   hermes portal"`; then `"  Model:   ✓ using Nous as inference provider"` or `"  Model:   currently <provider> (switch with \`hermes model\`)"`; then `"  Tool Gateway"` / `"  ────────────"` with one aligned row per feature whose state is `"via Nous Portal"` (green), the current provider name, `"active"`, or `"not configured"` (dim), or `"  (could not resolve subscription state)"`; when logged out it appends `"  Docs: https://hermes-agent.nousresearch.com/docs/user-guide/features/tool-gateway"`. `open` prints `"Opening <SUBSCRIPTION_URL>"` and, on failure, `"Could not launch a browser. Visit the URL above manually."` (exit 1). `tools` prints `"  Tool Gateway catalog"` / `"  ────────────────────"`, optionally `"  Not logged into Nous Portal — sign in with \`hermes portal\`."`, then one row per catalog entry formatted `"  <label>  partner: <partner> <state>"` where state is `"✓ via Nous Portal"`, the current provider, `"active"`, `"not configured"` or `"unknown"`; then `"  Manage your subscription: https://portal.nousresearch.com/manage-subscription"` and `"  Docs: <DOCS_URL>"`. On failure it prints `"Could not resolve Tool Gateway state."` to stderr and returns 1. `login` cancellation prints `"Portal setup cancelled."` and returns 1.
- **Config / env:** `DEFAULT_PORTAL_URL = "https://portal.nousresearch.com"`; `SUBSCRIPTION_URL = "https://portal.nousresearch.com/manage-subscription"`; `DOCS_URL = "https://hermes-agent.nousresearch.com/docs/user-guide/features/tool-gateway"`; `dashboard.oauth.portal_url`; `cron.chronos.portal_url` (`https://portal.nousresearch.com`).
- **Edge cases / guards:** The command is intentionally minimal and does not duplicate `hermes auth` or `hermes tools`.
- **Rebuild notes:** One onboarding entry point + three read-only discovery views.

### Nous Tool Gateway catalog  `id: providers.tool-gateway-catalog`
- **Surface:** CLI
- **Where:** `hermes portal tools`; the static catalog in `hermes_cli/portal_cli.py:134-140`; state from `hermes_cli/nous_subscription.get_nous_subscription_features(config)`.
- **What it does:** Lists the partner-backed capabilities a Nous Portal subscription can route on the user's behalf, and shows which are currently routed via Nous versus a directly-configured provider.
- **How it works:** The catalog is a static list of `(key, label, partner)` triples; the live state comes from the subscription feature resolver, which reports per feature `managed_by_nous`, `active` and `current_provider`.
- **Inputs / options:** The five catalog entries, verbatim: `("web", "Web search & extract", "Firecrawl")`; `("image_gen", "Image generation", "FAL")`; `("tts", "Text-to-speech", "OpenAI TTS")`; `("browser", "Browser automation", "Browser Use")`; `("modal", "Cloud terminal", "Modal")`.
- **Outputs / side effects:** Display only.
- **Config / env:** Requires a Nous Portal login (`features.nous_auth_present`).
- **Edge cases / guards:** A feature key missing from the resolver renders as `"unknown"`.
- **Rebuild notes:** A static catalog joined against a live feature resolver.

---

## 12. Model-name normalisation, selection guards and per-run overrides

### Per-provider model-name normalisation  `id: providers.model-normalize`
- **Surface:** Core
- **Where:** `hermes_cli/model_normalize.py` (586 lines) — `normalize_model_for_provider(model_input, target_provider)` (`:428`).
- **What it does:** Translates one user-typed model id into the exact shape the chosen provider's API expects, so `claude-sonnet-4.6` works whether you point it at OpenRouter, Anthropic native, Copilot or OpenCode.
- **How it works:** Per-provider policy sets. `_VENDOR_PREFIXES` (`:48-66`) maps the first hyphen-delimited token of a bare name to the aggregator vendor slug: `claude→anthropic`, `gpt→openai`, `o1→openai`, `o3→openai`, `o4→openai`, `gemini→google`, `gemma→google`, `deepseek→deepseek`, `glm→z-ai`, `kimi→moonshotai`, `minimax→minimax`, `grok→x-ai`, `qwen→qwen`, `mimo→xiaomi`, `trinity→arcee-ai`, `nemotron→nvidia`, `llama→meta-llama`, `step→stepfun`. `_AGGREGATOR_PROVIDERS = {openrouter, nous, ai-gateway, kilocode}` consume `vendor/model` slugs. `_DOT_TO_HYPHEN_PROVIDERS = {anthropic}` want bare names with dots replaced by hyphens (`claude-sonnet-4-6`). `_STRIP_VENDOR_ONLY_PROVIDERS = {copilot, copilot-acp, openai-codex}` want bare names with dots preserved (`claude-sonnet-4.6`). `_AUTHORITATIVE_NATIVE_PROVIDERS = {huggingface}` pass through unchanged. `_MATCHING_PREFIX_STRIP_PROVIDERS = {zai, kimi-coding, kimi-coding-cn, minimax, minimax-oauth, minimax-cn, alibaba, qwen-oauth, xiaomi, arcee, ollama-cloud, nebius-token-factory, custom, gemini, xai}` accept bare names but repair a matching `provider/` prefix when users copy the aggregator form into config.yaml. `_CATALOGUE_PREFIX_REPAIR_PROVIDERS = {nvidia}` serve `vendor/model` ids but can also front arbitrary self-hosted models, so a bare id is repaired only when the curated catalogue holds exactly one entry ending in `/<name>` — a lookup, not a guess (without it a bare `nemotron-3-ultra-550b-a55b` reaches build.nvidia.com and returns a bare `404 page not found` that never names the model, #78796). `_LOWERCASE_MODEL_PROVIDERS = {xiaomi}` additionally get `.lower()` because `api.xiaomimimo.com` rejects mixed-case names like `MiMo-V2.5-Pro` and only accepts `mimo-v2.5-pro`.
- **Inputs / options:** Helpers: `_strip_vendor_prefix` (`:218`), `_dots_to_hyphens` (`:235`), `_normalize_provider_alias` (`:244`), `_strip_matching_provider_prefix` (`:257`), `detect_vendor(model_name)` (`:291`), `_prepend_vendor` (`:341`), `_repair_prefix_from_catalogue` (`:367`), `suggest_prefixed_model_id(provider, model_name)` (`:404`).
- **Outputs / side effects:** The wire model id.
- **Config / env:** n/a.
- **Edge cases / guards:** DeepSeek special handling (`_normalize_for_deepseek`, `:172`): the direct API only accepts first-class V-series IDs after the 2026-07-24 15:59 UTC cut-off. `_DEEPSEEK_RETIRED_ALIASES = {deepseek-chat, deepseek-reasoner}` are remapped to `deepseek-v4-flash` (chat = non-thinking, reasoner = thinking; thinking mode itself is controlled by `extra_body.thinking` on the DeepSeek profile). `_DEEPSEEK_CANONICAL_MODELS = {deepseek-v4-pro, deepseek-v4-flash}`. `_DEEPSEEK_REASONER_KEYWORDS = {reasoner, r1, think, reasoning, cot}` steer fuzzy names. `_DEEPSEEK_V_SERIES_RE = r"^deepseek-v\d+([-.].+)?$"` recognises first-class ids including dated variants (`deepseek-v4-flash-20260423`) — verified empirically 2026-04-24 that these are NOT aliases of `deepseek-chat` and must not be folded into it (older Hermes revisions folded every non-reasoner input into `deepseek-chat`, which on aggregators routes to V3, silently downgrading a user who picked V4 Pro).
- **Rebuild notes:** Six provider policy sets + a vendor-prefix table + one vendor-specific remap. A better version would ask the provider's catalogue whether an id exists before rewriting it.

### Picker-only model search aliases  `id: providers.model-search-aliases`
- **Surface:** CLI / TUI / Web dashboard
- **Where:** `hermes_cli/model_search.py` (53 lines); kept in sync with `ui-tui/src/lib/model-search-text.ts` and `web/src/lib/model-search-text.ts`.
- **What it does:** Lets users find a model by its familiar public name even when the provider reports a short or brand-less wire id, and prevents the same model rendering as two picker rows.
- **How it works:** `_MODEL_SEARCH_ALIASES` maps a lowercased wire id to extra tokens appended to the **search haystack only** — wire ids are never changed: `"k3" → ("kimi-k3", "kimi")` (Kimi Coding's flagship is literally `k3`) and `"x-preview-f-free" → ("ox-alpha", "ox")` (OpenCode Zen serves the "Ox Alpha" stealth model under an opaque preview slug). `_MODEL_ALIAS_CANONICAL` is derived from the FIRST alias entry, which by convention is the full public slug, and is used by picker dedup so a live bare id and its curated public slug do not render twice.
- **Inputs / options:** `model_search_text(model)` (`:42`) returns `"<id> <aliases…>"` or the id unchanged; `model_alias_canonical(model)` (`:32`) returns the canonical public slug (identity for ids with no alias entry), lowercased so it can be used directly as a dedup key.
- **Outputs / side effects:** Search matching only.
- **Config / env:** n/a.
- **Edge cases / guards:** Three implementations (Python, TUI TS, web TS) must be kept in sync.
- **Rebuild notes:** A two-entry alias table used for search and dedup.

### Expensive-model confirmation guard  `id: providers.model-cost-guard`
- **Surface:** CLI / Web dashboard / Gateway / TUI
- **Where:** `hermes_cli/model_cost_guard.py` (185 lines) — `expensive_model_warning(model_name, *, provider, base_url, api_key, model_info)`.
- **What it does:** Blocks accidental selection of a very expensive model behind an explicit confirm step.
- **How it works:** Pricing is resolved in order: a trusted `ModelInfo` (only when the caller's provider maps to the model's `provider_id` via `PROVIDER_TO_MODELS_DEV`), then `agent.models_dev.get_model_info(provider, model)`, then `agent.usage_pricing.get_pricing_entry(...)` when `_can_trust_pricing_lookup()` allows it. The guard **only triggers when pricing is known**.
- **Inputs / options:** `INPUT_COST_WARNING_THRESHOLD = Decimal("20")`, `OUTPUT_COST_WARNING_THRESHOLD = Decimal("100")`, plus the special case `GPT55_PRO_OPENROUTER_ID = "openai/gpt-5.5-pro"` which always warns with `GPT55_SUGGESTION = "did you mean to select openai/gpt-5.5?"`.
- **Outputs / side effects:** `ExpensiveModelWarning(model, provider, input_cost_per_million, output_cost_per_million, source, message)` whose message is, verbatim: `"!!! EXPENSIVE MODEL WARNING !!!"`, blank line, `"<model> has known pricing above Hermes' safety threshold."`, `"Input tokens: $<n>/M"` (or `"unknown"`), `"Output tokens: $<n>/M"`, `"Threshold: more than $20/M input tokens or more than $100/M output tokens."`, optionally `"Pricing source: <source>."`, optionally the GPT-5.5-Pro suggestion, and `"Confirm only if you intend to use this model."`.
- **Config / env:** n/a.
- **Edge cases / guards:** Callers must run it AFTER model resolution so aliases and provider-specific ids have settled.
- **Rebuild notes:** Two thresholds + a layered pricing lookup + one vendor confusion case.

### Data-training-tier confirmation guard  `id: providers.model-data-policy-guard`
- **Surface:** CLI / Web dashboard
- **Where:** `hermes_cli/model_data_policy_guard.py` (108 lines) — `data_training_warning(model_name, *, provider=None, base_url=None)`.
- **What it does:** Warns when the selected tier is cheap *because* the vendor trains future models on your prompts and completions.
- **How it works:** A static rule table `(predicate, message)` evaluated in order, first match wins. It is deliberately NOT a `ProviderProfile` hook: the guard runs inside core selection code (`auth.py` / `web_server.py`), which never calls into the active profile for a selection-time warning; keeping the rules here also means it renders regardless of which provider plugin is loaded and stays testable without importing third-party plugin code into the selection path. The status is not machine-readable anywhere today — neither models.dev nor Meta's `/v1/models` payload exposes a training/retention flag (verified 2026-08-07) — so the rule keys on the vendor-documented model id, with the anomalously low pricing as a corroborating signal only. Currently one rule: `_is_meta_contributor(model_lower, provider_lower)` matches an id ending `-contributor` or containing `contributor` as a hyphen-delimited token, deliberately without requiring a specific provider id so it fires whether the model is selected via the meta-ai plugin, a gateway, or a custom endpoint serving the same id. A misbehaving predicate never breaks selection.
- **Inputs / options:** model name, provider, `base_url` (reserved for future host-scoped rules).
- **Outputs / side effects:** `DataTrainingWarning(model, provider, message)`. The Meta message, verbatim: `"!!! CONTRIBUTOR TIER — TRAINS ON YOUR DATA !!!"`, blank, `"muse-spark-1.2-contributor is Meta's contributor tier: heavily discounted"` / `"token pricing in exchange for permission to use your prompts and completions"` / `"to train future Meta models."`, blank, `"  Price per 1M tokens:  input $0.10  |  output $0.20  |  cached input $0.002"`, `"  (vs. standard muse-spark-1.2:  input $1.25  |  output $4.25  |  cached $0.15)"`, blank, `"It lowers the barrier to entry for prototyping, testing integrations, and"` / `"scaling experiments where training on your data is acceptable. Do NOT use it"` / `"for confidential, proprietary, personal, or otherwise sensitive data. For the"` / `"same model at standard pricing with no training on your data, select the"` / `"standard variant, muse-spark-1.2."`, blank, `"Source: https://dev.meta.ai/docs/pricing-rate-limits/"`, `"Confirm only if training on your prompts and completions is acceptable."`.
- **Config / env:** n/a.
- **Edge cases / guards:** Returns `None` for an empty model name and for the common no-match case.
- **Rebuild notes:** An extensible `(predicate, message)` table keyed on documented model ids.

### Unified selection-guard registry  `id: providers.model-selection-guards`
- **Surface:** Core
- **Where:** `hermes_cli/model_selection_guards.py` (181 lines) — `selection_warnings(...)`.
- **What it does:** Runs every registered selection-time guard once, so adding a guard makes it appear on every model-selection surface at the same time.
- **How it works:** Hermes has multiple selection surfaces (CLI picker, TUI, dashboard, gateway `/model`, Telegram/Discord pickers, TUI-gateway RPC). Each previously imported `model_cost_guard.expensive_model_warning` directly, so every new guard class had to be wired into every surface by hand — and inevitably missed some. This module is the single **evaluation** point; the **rendering** half stays per-surface (stdin prompt, modal, inline keyboard, `confirm_required` JSON). Guard modules keep their public APIs so existing tests and mock patch points remain valid; this module only aggregates them.
- **Inputs / options:** `_GUARDS` currently wraps `_cost_guard` (`model_cost_guard.expensive_model_warning`) and the data-policy guard; access to warning payloads is duck-typed on `.message` so future guards can supply minimal objects.
- **Outputs / side effects:** A list of `SelectionWarning(kind, title, model, provider, message)` where `kind` is `"cost"` | `"data_policy"` | future kinds.
- **Config / env:** n/a.
- **Edge cases / guards:** Guards run after model resolution.
- **Rebuild notes:** One registry + one evaluation function; rendering stays per-surface.

### `--usage-file PATH` — machine-readable spend report  `id: providers.flag-usage-file`
- **Surface:** CLI
- **Where:** Global flag `hermes --usage-file PATH` (one-shot mode only); implemented in `hermes_cli/oneshot.py::_write_usage_file` (`:158-198`).
- **What it does:** After a `-z/--oneshot` run, writes a JSON usage report (estimated cost, token counts, model, api_calls) to PATH — **even when the run fails**, so pipelines can always account for spend.
- **How it works:** Best-effort and never raises — a broken usage write must not mask the run's own outcome. The parent directory is created; the file is written with `indent=2` plus a trailing newline, UTF-8.
- **Inputs / options:** `--usage-file PATH`. Help text, verbatim: "One-shot mode only: after the run, write a JSON usage report (estimated cost, token counts, model, api_calls) to PATH. The report is written even when the run fails, so pipelines can always account for spend. No effect outside -z/--oneshot."
- **Outputs / side effects:** JSON object with the keys: `estimated_cost_usd`, `cost_status`, `cost_source`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `reasoning_tokens`, `total_tokens`, `api_calls`, `model`, `provider`, `session_id`, `completed`, `failed` (true when the run failed OR a failure was passed), `service_tier` (a billing-audit field: the service tier this run REQUESTED via `request_overrides.extra_body`, e.g. OpenAI `"flex"`; `None` when unset — it lets batch pipelines verify the tier they think they are paying for actually went out on the wire, after a July 2026 incident where a config-matching bug silently dropped flex and caused 2.3× billing), and `failure` (only present when a failure occurred).
- **Config / env:** n/a.
- **Edge cases / guards:** No effect outside `-z/--oneshot`.
- **Rebuild notes:** One JSON dump in a `finally` block.

### `-m/--model`, `--provider`, `--reasoning` per-run overrides  `id: providers.flags-model-overrides`
- **Surface:** CLI
- **Where:** Global flags on `hermes`.
- **What it does:** Override the model, provider and reasoning effort for a single invocation without touching config.
- **How it works:** All three apply to `-z/--oneshot` and `--tui`.
- **Inputs / options:** `-m MODEL, --model MODEL` — "Model override for this invocation (e.g. anthropic/claude-sonnet-4.6). Applies to -z/--oneshot and --tui. Also settable via HERMES_INFERENCE_MODEL env var."; `--provider PROVIDER` — "Provider override for this invocation (e.g. openrouter, anthropic). Applies to -z/--oneshot and --tui. The persistent provider lives in config.yaml under model.provider — use `hermes setup` or edit the file to change it."; `--reasoning LEVEL` — "Reasoning effort for this invocation: none, minimal, low, medium, high, xhigh, max, or ultra. Overrides agent.reasoning_effort in config.yaml for this run only; the persistent level lives there (or per-model under agent.reasoning_overrides)."
- **Outputs / side effects:** In-memory overrides only.
- **Config / env:** `HERMES_INFERENCE_MODEL`, `HERMES_INFERENCE_PROVIDER`; `model.provider`, `model.default`, `agent.reasoning_effort`, `agent.reasoning_overrides`.
- **Edge cases / guards:** The eight accepted reasoning levels are exactly `EFFORT_LADDER`.
- **Rebuild notes:** Three argparse flags feeding the runtime resolver.

---

## 13. Provider/model HTTP API (dashboard + desktop back end)

These are the local API routes that expose provider, model, credential and usage state. The dashboard
SPA pages that render them belong to the web-* shards; the routes and their payloads are documented here.

### `GET /api/model/options` — provider + model picker payload  `id: providers.api-model-options`
- **Surface:** API
- **Where:** `GET /api/model/options` (dashboard model picker; `hermes_cli/web_models.py`).
- **What it does:** Returns every selectable provider with its model list, capability flags and authentication state — the data behind the dashboard's model picker.
- **How it works:** Built by `build_models_payload`, which merges the canonical provider list, live `/v1/models` fetches, the curated catalog and credential state, then dedups against routing aggregators (`is_routing_aggregator`).
- **Inputs / options:** Header `X-Hermes-Session-Token`. Response `{providers: [...], model: "<current model>", provider: "<current provider>"}`; each provider row carries exactly these keys: `slug`, `name`, `is_current`, `is_user_defined`, `models` (list of ids), `total_models`, `source` (`"virtual"` | `"built-in"` | `"hermes"` | user-defined), `authenticated` (bool), `auth_type` (e.g. `"virtual"`), `warning` (e.g. the MoA row's `"Aggregator acts as the selected model; references provide analysis before each call."`), `capabilities` (map of model id → `{fast: bool, reasoning: bool}`), `featured_models`.
- **Outputs / side effects:** May trigger live catalog fetches.
- **Config / env:** `model_catalog.excluded_providers` hides rows.
- **Edge cases / guards:** Only providers with resolvable credentials report `authenticated: true`.
- **Rebuild notes:** One aggregate endpoint so the picker needs a single round trip.

### `GET /api/model/info` — active model resolution  `id: providers.api-model-info`
- **Surface:** API
- **Where:** `GET /api/model/info`.
- **What it does:** Reports the currently configured model/provider and the resolved context window.
- **How it works:** Reads config and the context-length resolver.
- **Inputs / options:** none.
- **Outputs / side effects:** `{model, provider, auto_context_length, config_context_length, effective_context_length, capabilities}`.
- **Config / env:** `model.provider`, `model.default`, `model_context_length`.
- **Edge cases / guards:** Empty strings and `0` when nothing is configured.
- **Rebuild notes:** One resolver read.

### `GET /api/model/recommended-default` — silent default  `id: providers.api-model-recommended-default`
- **Surface:** API
- **Where:** `GET /api/model/recommended-default`.
- **What it does:** Returns the catalog-labelled silent default model for onboarding.
- **How it works:** Reads the model catalog's `"default": true` entry (cache-only) via `get_default_model_from_cache`.
- **Inputs / options:** none.
- **Outputs / side effects:** `{provider, model, free_tier}`.
- **Config / env:** `model_catalog.*`.
- **Edge cases / guards:** Empty strings when no cached manifest exists (the caller falls back to `PREFERRED_SILENT_DEFAULT_MODEL`).
- **Rebuild notes:** Cache-only read; never network.

### `POST /api/model/set` — apply a model selection  `id: providers.api-model-set`
- **Surface:** API
- **Where:** `POST /api/model/set`.
- **What it does:** Persists a provider+model choice from the dashboard, running the same selection guards as the CLI.
- **How it works:** Resolves the provider, normalises the model name, evaluates `selection_warnings()` and returns `confirm_required` when a guard fires.
- **Inputs / options:** provider, model, optional base_url/api_key and a confirmation flag.
- **Outputs / side effects:** Writes `model.*` in config.yaml.
- **Config / env:** as above.
- **Edge cases / guards:** Cost and data-policy guards must be confirmed.
- **Rebuild notes:** Same guard registry as every other surface.

### `GET /api/model/auxiliary` — auxiliary task model routing  `id: providers.api-model-auxiliary`
- **Surface:** API
- **Where:** `GET /api/model/auxiliary`.
- **What it does:** Lists every auxiliary task and the provider/model/base_url it is pinned to (or `auto`).
- **How it works:** Reads the `auxiliary.<task>.*` config block.
- **Inputs / options:** none.
- **Outputs / side effects:** `{tasks: [{task, provider, model, base_url}, …], main: {provider, model}}`. The live task list, verbatim: `vision`, `compression`, `skills_hub`, `approval`, `mcp`, `title_generation`, `review`, `triage_specifier`, `kanban_decomposer`, `profile_describer`, `curator`.
- **Config / env:** `auxiliary.<task>.provider` (default `"auto"`), `.model`, `.base_url`, `.api_key`, `.timeout`, `.reasoning_effort`.
- **Edge cases / guards:** `"auto"` means the resolver picks (per-task fallback → main fallback chain → built-in aux discovery).
- **Rebuild notes:** A flat projection of the auxiliary config namespace.

### `GET /api/model/moa` and `PUT /api/model/moa` — MoA preset API  `id: providers.api-model-moa`
- **Surface:** API
- **Where:** `GET /api/model/moa`, `PUT /api/model/moa`.
- **What it does:** Reads and writes the MoA preset configuration from the dashboard.
- **How it works:** GET returns `normalize_moa_config()`'s output plus a flattened view of the active preset; PUT validates with `validate_moa_payload()` before saving.
- **Inputs / options:** GET: none. PUT: the preset object.
- **Outputs / side effects:** GET payload keys: `default_preset`, `active_preset`, `presets` (map name → `{enabled, reference_models[{provider, model, enabled}], aggregator{provider, model}, reference_temperature, aggregator_temperature, reference_timeout, degraded_reference_policy, max_tokens, reference_max_tokens, fanout}`), plus the same fields flattened at the top level for the active preset.
- **Config / env:** `moa.*`.
- **Edge cases / guards:** Invalid payloads are rejected with the problem list from `validate_moa_payload`.
- **Rebuild notes:** One normalise/validate pair shared with the CLI.

### `GET /api/providers/oauth` and the OAuth session routes  `id: providers.api-providers-oauth`
- **Surface:** API
- **Where:** `GET /api/providers/oauth`; `POST /api/providers/oauth/{provider_id}/start`; `POST /api/providers/oauth/{provider_id}/submit`; `GET /api/providers/oauth/{provider_id}/poll/{session_id}`; `DELETE /api/providers/oauth/{provider_id}`; `DELETE /api/providers/oauth/sessions/{session_id}`.
- **What it does:** Drives every browser/device-code OAuth login from the dashboard and reports which providers are connected.
- **How it works:** `start` opens a login session, `submit` posts a pasted code, `poll` waits for completion, the two DELETEs disconnect a provider or abandon a session.
- **Inputs / options:** `GET` returns `{providers: [...]}` where each entry is `{id, name, flow, cli_command, docs_url, disconnect_hint, disconnect_command, disconnectable, status{logged_in, source, source_label, token_preview, expires_at, has_refresh_token, last_refresh?}}`. The eight live entries, verbatim: `nous` / "Nous Portal" / flow `device_code` / `hermes auth add nous` / docs `https://portal.nousresearch.com` / disconnectable; `openai-codex` / "ChatGPT or Codex Subscription" / `device_code` / `hermes auth add openai-codex` / `https://platform.openai.com/docs` / disconnectable; `qwen-oauth` / "Qwen (via Qwen CLI)" / `external` / `hermes auth add qwen-oauth` / `https://github.com/QwenLM/qwen-code` / NOT disconnectable, hint `"Managed by that provider's CLI; remove it there."`; `minimax-oauth` / "MiniMax (OAuth)" / `device_code` / `hermes auth add minimax-oauth` / `https://www.minimax.io` / disconnectable; `xai-oauth` / "xAI Grok OAuth (SuperGrok / Premium+)" / `device_code` / `hermes auth add xai-oauth` / `https://hermes-agent.nousresearch.com/docs/guides/xai-grok-oauth` / disconnectable; `copilot-acp` / "GitHub Copilot (ACP)" / `external` / `copilot /login` / `https://docs.github.com/en/copilot` / NOT disconnectable, hint `"Managed by that provider's CLI; remove it there."`; `anthropic` / "Anthropic API Key" / `external` / `hermes auth add anthropic` / `https://docs.claude.com/en/api/getting-started` / disconnectable; `claude-code` / "Anthropic OAuth: Required Extra Usage Credits to Use Subscription" / `external` / `claude setup-token` / `https://docs.claude.com/en/docs/claude-code` / NOT disconnectable, hint `"Managed outside Hermes — run the disconnect command to remove it."`, disconnect command `rm -f ~/.claude/.credentials.json`.
- **Outputs / side effects:** Writes credentials into the auth store.
- **Config / env:** as per each provider's OAuth constants.
- **Edge cases / guards:** Providers managed by another CLI report `disconnectable: false` with a hint instead of a delete action.
- **Rebuild notes:** start/submit/poll/delete session state machine + a per-provider descriptor.

### `GET /api/credentials/pool` and `DELETE /api/credentials/pool/{provider}/{index}`  `id: providers.api-credentials-pool`
- **Surface:** API
- **Where:** `GET /api/credentials/pool`, `DELETE /api/credentials/pool/{provider}/{index}`.
- **What it does:** Shows the credential pool per provider and removes one entry by index.
- **How it works:** Projects `CredentialPool` rows (sanitised — no raw secrets) and routes removal through `agent/credential_sources.py`.
- **Inputs / options:** GET: none → `{providers: []}` when empty. DELETE: path `provider` and `index`.
- **Outputs / side effects:** Edits `auth.json` and the source the entry came from.
- **Config / env:** n/a.
- **Edge cases / guards:** Removal must also suppress re-seeding, or the entry reappears on the next `load_pool()`.
- **Rebuild notes:** Read + delete over the pool.

### `/api/providers/custom-endpoints` family  `id: providers.api-custom-endpoints`
- **Surface:** API
- **Where:** `GET /api/providers/custom-endpoints`; `POST /api/providers/custom-endpoints`; `POST /api/providers/custom-endpoints/{endpoint_id}/activate`; `DELETE /api/providers/custom-endpoints/{endpoint_id}`; `POST /api/providers/custom-endpoints/validate`; `POST /api/providers/validate`.
- **What it does:** Manages user-defined OpenAI-compatible endpoints from the dashboard — list, create, activate, delete and validate.
- **How it works:** Backed by the `custom_providers:` config list and `custom_provider_slug()` identities.
- **Inputs / options:** GET returns `{endpoints: [], current: {provider, model, base_url}}`. POST bodies carry name, base_url, key_env/api_key and an optional model.
- **Outputs / side effects:** Writes `custom_providers` in config.yaml; `activate` also writes `model.*`.
- **Config / env:** `custom_providers`, `providers`.
- **Edge cases / guards:** `validate` probes the endpoint before saving so a typo is caught in the form.
- **Rebuild notes:** CRUD over a config list plus a live probe.

### `GET /api/portal` — Portal + Tool Gateway state  `id: providers.api-portal`
- **Surface:** API
- **Where:** `GET /api/portal`.
- **What it does:** The dashboard's version of `hermes portal info` — login state, URLs, active provider and the Tool Gateway feature routing.
- **How it works:** Same resolver as the CLI (`get_nous_auth_status_local` + `get_nous_subscription_features`).
- **Inputs / options:** none.
- **Outputs / side effects:** `{logged_in, portal_url, inference_url, provider, subscription_url, features: [{label, state}, …]}`. Live feature labels, verbatim: `"Web tools"`, `"Image generation"`, `"Video generation"`, `"OpenAI TTS"`, `"Speech-to-text"`, `"Browser automation"`, `"Modal execution"`; live states seen include `"not configured"`, `"Edge TTS"`, `"Local browser"`, `"local"`. `subscription_url` is `"https://portal.nousresearch.com/manage-subscription"`.
- **Config / env:** `dashboard.oauth.portal_url`.
- **Edge cases / guards:** Refresh-free — never triggers an OAuth refresh.
- **Rebuild notes:** One read-only projection shared with the CLI.

### `GET /api/analytics/usage` and `GET /api/analytics/models`  `id: providers.api-analytics`
- **Surface:** API
- **Where:** `GET /api/analytics/usage`, `GET /api/analytics/models`.
- **What it does:** Historical token/cost analytics for the dashboard — the same data `hermes insights` renders in the terminal.
- **How it works:** Aggregates session records over a rolling window.
- **Inputs / options:** Optional period parameters; live default `period_days: 30`.
- **Outputs / side effects:** `/api/analytics/usage` → `{daily: [], by_model: [], by_task: [], totals: {total_input, total_output, total_cache_read, total_reasoning, total_estimated_cost, total_actual_cost, total_sessions, total_api_calls}, period_days, skills: {summary: {total_skill_loads, total_skill_edits, total_skill_actions, distinct_skills_used}, top_skills: []}, tools: []}`. `/api/analytics/models` → `{models: [], totals: {distinct_models, total_input, total_output, total_cache_read, total_reasoning, total_estimated_cost, total_actual_cost, total_sessions, total_api_calls}, period_days}`.
- **Config / env:** n/a.
- **Edge cases / guards:** `total_estimated_cost` vs `total_actual_cost` are tracked separately so an estimate is never presented as an invoice.
- **Rebuild notes:** Two aggregate endpoints over the session store.

---

## 14. Runtime provider resolution and remaining surfaces

### Runtime provider resolution  `id: providers.runtime-provider`
- **Surface:** Core
- **Where:** `hermes_cli/runtime_provider.py` (2560 lines) — `resolve_runtime_provider(*, requested=None, explicit_api_key=None, explicit_base_url=None, target_model=None)` (`:1882`).
- **What it does:** Turns "which provider should this call use" into a concrete `(api_key, base_url, api_mode, provider, capabilities…)` bundle for the CLI, gateway, cron and every helper.
- **How it works:** `resolve_requested_provider(requested)` (`:647`) normalises the request, then resolution walks the credential pool (`_resolve_runtime_from_pool_entry`, `:498`; `_try_resolve_from_custom_pool`, `:666`), the per-provider credential resolvers imported from `hermes_cli.auth` (`resolve_nous_runtime_credentials`, `resolve_codex_runtime_credentials`, `resolve_xai_oauth_runtime_credentials`, `resolve_qwen_runtime_credentials`, `resolve_api_key_provider_credentials`, `resolve_external_process_provider_credentials`) and the config/model block. `target_model` overrides `model_cfg["default"]` when computing the provider-specific `api_mode` — a mid-session model switch must derive the mode from the model it is switching TO, not the stale persisted default (this matters for OpenCode Zen/Go where different models route through different API surfaces). API-mode helpers: `_detect_api_mode_for_url` (`:128`), `_fallback_api_mode` (`:187`), `_resolve_plain_custom_api_mode` (`:212`), `_parse_api_mode` (`:444`), `_provider_supports_explicit_api_mode` (`:384`), `_copilot_runtime_api_mode` (`:401`, per-model routing for Copilot). Capability lift: `_filter_capabilities` (`:710`), `_lift_model_capabilities` (`:721`), `_lift_max_output_tokens` (`:734`). Local endpoints: `_loopback_hostname` (`:93`), `_config_base_url_trustworthy_for_bare_custom` (`:98`), `_host_derived_api_key` (`:235`), `_auto_detect_local_model` (`:329`), `_anthropic_base_url_override_ok` (`:292`). Codex app-server runtime: `_maybe_apply_codex_app_server_runtime` (`:472`).
- **Inputs / options:** `requested`, `explicit_api_key`, `explicit_base_url`, `target_model`.
- **Outputs / side effects:** A dict consumed by the transport/client builders.
- **Config / env:** `providers.<name>.enabled: false` is honoured for BOTH user-defined custom providers and the built-ins (openai / anthropic / openrouter / gemini / …); resolution fails fast with a typed error so the fallback chain can advance to the next provider instead of using a disabled one. `HERMES_INFERENCE_PROVIDER`, `NOUS_INFERENCE_BASE_URL`, plus each provider's key/base-URL env vars. `normalize_extra_headers(value)` (`:70`) sanitises user-supplied headers.
- **Edge cases / guards:** `ACTUAL_LOCAL_NOAUTH_PLACEHOLDER` / `LMSTUDIO_NOAUTH_PLACEHOLDER` satisfy the "has a key" checks for local servers that need no auth.
- **Rebuild notes:** One resolver with a documented precedence chain and a typed disabled-provider error.

### Codex model discovery  `id: providers.codex-models`
- **Surface:** Core
- **Where:** `hermes_cli/codex_models.py` (282 lines) — `get_codex_model_ids(access_token=None)` (`:253`).
- **What it does:** Lists the models a ChatGPT/Codex subscription can actually use, from the live backend, the local Codex CLI cache, or a curated fallback.
- **How it works:** Live discovery via `_fetch_models_from_api(access_token)` (`:154`) against `chatgpt.com/backend-api/codex/models`; `_read_cache_models(codex_home)` (`:216`) and `_read_default_model(codex_home)` (`:198`) read the Codex CLI's own state; `_finalize_codex_models()` (`:119`) applies two synthesis passes. `_add_forward_compat_models()` (`:68`) adds Clawdbot-style synthetic forward-compat slugs: when a newer Codex slug is not returned by live discovery it is surfaced anyway if an older compatible template model is present. `_add_context_variants()` (`:92`) inserts a `<slug>-900k` picker entry after each eligible base slug — the ChatGPT Codex backend advertises 272K for the gpt-5.4 / gpt-5.6 families but accepts ~911K (live-verified Aug 2026), so the base slug keeps the cheaper advertised 272K by default and the variant opts into the large window; the suffix is **Hermes-side only** and is stripped before the id hits the wire (`agent/transports/codex.py`, `agent/auxiliary_client.py`). `_extract_chatgpt_account_id(access_token)` (`:124`) reads the OAuth JWT claim.
- **Inputs / options:** `DEFAULT_CODEX_MODELS` (`:15-…`), the curated offline fallback, verbatim: `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, `gpt-5.5`, `gpt-5.4-mini`, `gpt-5.4`, `gpt-5.3-codex`, `gpt-5.3-codex-spark`.
- **Outputs / side effects:** The `/model` picker list for `openai-codex`.
- **Config / env:** `CODEX_HOME`-style discovery of the Codex CLI directory.
- **Edge cases / guards:** The public API exposes `-pro` variants but the ChatGPT Codex OAuth backend rejects them with HTTP 400, so they are kept out of the curated fallback. `gpt-5.3-codex-spark` is research-preview and exposed **only** via the Codex CLI/OAuth backend for ChatGPT Pro subscribers — it stays out of the public `openai` provider catalog; the backend reports `supported_in_api: false` for it, but that flag describes API availability, not Codex-backend availability, so the fetch/cache paths deliberately do NOT filter on it (PR #12994 removed the entry on the wrong assumption; it was restored). `gpt-5.2-codex`, `gpt-5.1-codex-max` and `gpt-5.1-codex-mini` were removed because the backend returns HTTP 400 `"The '<model>' model is not supported when using Codex with a ChatGPT account."` for all three on every ChatGPT Pro account tested (verified live 2026-05-27), and keeping them leaked dead slugs into `/model` whenever live discovery was unavailable.
- **Rebuild notes:** Live fetch → cache → curated fallback, plus forward-compat and context-variant synthesis.

### `/model` gateway slash command (model/provider switch)  `id: providers.gateway-slash-model`
- **Surface:** Gateway/Telegram
- **Where:** Slash command `/model`; strings in `locales/en.yaml` under `gateway.model.*`; switch logic in `hermes_cli/model_switch.py` (4233 lines).
- **What it does:** Shows the current model, lists selectable models, and switches model and/or provider mid-session (optionally persisting to config).
- **How it works:** The same canonical provider list and `group_providers()` fold as the CLI picker; selection guards run through `model_selection_guards.selection_warnings()`.
- **Inputs / options:** Usage strings, verbatim (`i18n: gateway.model.usage_switch_model`) `` "`/model <name>` — switch model" ``; (`i18n: gateway.model.usage_switch_provider`) `` "`/model <name> --provider <slug>` — switch provider" ``; (`i18n: gateway.model.usage_persist`) `` "`/model <name> --global` — persist" ``.
- **Outputs / side effects:** Reply strings, verbatim: `i18n: gateway.model.switched` = "Model switched to `{model}`"; `gateway.model.provider_label` = "Provider: {provider}"; `gateway.model.context_label` = "Context: {tokens} tokens"; `gateway.model.max_output_label` = "Max output: {tokens} tokens"; `gateway.model.cost_label` = "Cost: {cost}"; `gateway.model.capabilities_label` = "Capabilities: {capabilities}"; `gateway.model.prompt_caching_enabled` = "Prompt caching: enabled"; `gateway.model.warning_prefix` = "Warning: {warning}"; `gateway.model.error_prefix` = "Error: {error}"; `gateway.model.saved_global` = "Saved to config.yaml (`--global`)"; `gateway.model.session_only_hint` = "_(session only — add `--global` to persist)_"; `gateway.model.current_label` = "Current: `{model}` on {provider}"; `gateway.model.current_tag` = " (current)"; `gateway.model.more_models_suffix` = " (+{count} more)".
- **Config / env:** `model.*` when `--global` is passed; otherwise session-only.
- **Edge cases / guards:** A switch that trips a cost or data-policy guard surfaces `gateway.model.warning_prefix` and requires confirmation.
- **Rebuild notes:** Session-scoped override plus an optional persist flag, sharing the picker data with every other surface.

### `/usage` gateway output (cost and rate limits)  `id: providers.gateway-slash-usage`
- **Surface:** Gateway/Telegram
- **Where:** Slash command `/usage`; strings in `locales/en.yaml` under `gateway.usage.*` and `gateway.credits.*`.
- **What it does:** Reports the session's token usage, cost, context breakdown and the provider's rate-limit state.
- **How it works:** Reads the session's accumulated usage, prices it with `agent/usage_pricing.py`, and formats the rate-limit buckets with `agent/rate_limit_tracker.py`.
- **Inputs / options:** `/usage` and `/usage reset [--force]`.
- **Outputs / side effects:** Strings, verbatim: `gateway.usage.header_session` = "📊 **Session Token Usage**"; `gateway.usage.label_model` = "Model: `{model}`"; `gateway.usage.label_input_tokens` = "Input tokens: {count}"; `gateway.usage.label_cache_read` = "Cache read tokens: {count}"; `gateway.usage.label_cache_write` = "Cache write tokens: {count}"; `gateway.usage.label_output_tokens` = "Output tokens: {count}"; `gateway.usage.label_total` = "Total: {count}"; `gateway.usage.label_api_calls` = "API calls: {count}"; `gateway.usage.label_cost` = "Cost: {prefix}${amount}"; `gateway.usage.label_cost_included` = "Cost: included"; `gateway.usage.label_context` = "Context: {used} / {total} ({pct}%)"; `gateway.usage.label_compressions` = "Compressions: {count}"; `gateway.usage.rate_limits` = "⏱️ **Rate Limits:** {state}"; `gateway.usage.breakdown_header` = "🧩 **Context breakdown** _(estimated)_"; `gateway.usage.breakdown_line` = "• {label}: ~{count} ({pct}%)"; breakdown categories `gateway.usage.breakdown_cat_system_prompt` = "System prompt", `…_tool_definitions` = "Tool definitions", `…_rules` = "Rules", `…_skills` = "Skills", `…_mcp` = "MCP", `…_subagent_definitions` = "Subagent definitions", `…_memory` = "Memory", `…_conversation` = "Conversation"; `gateway.usage.header_session_info` = "📊 **Session Info**"; `gateway.usage.label_messages` = "Messages: {count}"; `gateway.usage.label_estimated_context` = "Estimated context: ~{count} tokens"; `gateway.usage.detailed_after_first` = "_(Detailed usage available after the first agent response)_"; `gateway.usage.no_data` = "No usage data available for this session."; `gateway.usage.unknown_subcommand` = "Unknown /usage subcommand: `{args}`. Try `/usage` or `/usage reset [--force]`."; `gateway.usage.reset_wrong_provider` = "Banked usage resets are only available on the openai-codex provider. Switch with `/model` first."; `gateway.credits.not_logged_in` = "Not logged into Nous Portal. Log in to see your credit balance and top up."; `gateway.status.model_provider` = "**Model:** `{model}` ({provider})".
- **Config / env:** `display.credits_notices`.
- **Edge cases / guards:** `"Cost: included"` is the subscription-included case from `agent/usage_pricing.py`, deliberately distinct from a $0.00 price.
- **Rebuild notes:** One usage record + a pricing lookup + a rate-limit renderer.

### Desktop model picker overlay  `id: providers.desktop-model-picker`
- **Surface:** Desktop app
- **Where:** Desktop model-picker overlay, opened from the status bar (`i18n: shell.statusbar.openModelPicker` = "Open model picker"); strings under `modelPicker.*` / `modelVisibility.*` in `apps/desktop/src/i18n`.
- **What it does:** Lets the desktop user switch provider+model, with price and tier badges.
- **How it works:** Backed by `GET /api/model/options` and `POST /api/model/set`.
- **Inputs / options:** Verbatim strings: `modelPicker.title` = "Switch model"; `modelPicker.current` = "current:"; `modelPicker.unknown` = "(unknown)"; `modelPicker.search` = "Filter providers and models..."; `modelPicker.noModels` = "No models found."; `modelPicker.addProvider` = "Add provider"; `modelPicker.loadFailed` = "Could not load models"; `modelPicker.noAuthenticatedProviders` = "No authenticated providers."; `modelPicker.pro` = "Pro"; `modelPicker.proNeedsSubscription` = "Pro models need a paid Nous subscription."; `modelPicker.free` = "Free"; `modelPicker.freeTier` = "Free tier"; `modelPicker.priceTitle` = "Input / Output price per million tokens"; `modelPicker.wasPrice` = "was"; `modelVisibility.noAuthenticatedProviders` = "No authenticated providers."; `modelVisibility.addProvider` = "Add provider…"; `assistant.thread.errorLayers.provider` = "Provider error"; `assistant.thread.errorSwitchProvider` = "Switch provider"; `desktop.providerCredentialRequired` = "Add a provider credential before sending your first message."; `settings.model.provider` = "Provider"; `settings.model.providerDefault` = "(provider default)".
- **Outputs / side effects:** Writes the model selection through the API.
- **Config / env:** `model.*`.
- **Edge cases / guards:** Pro-tier rows are gated by a paid Nous subscription.
- **Rebuild notes:** A searchable two-level list with price and tier badges.

### Desktop billing block (out-of-credits banner)  `id: providers.desktop-billing-block`
- **Surface:** Desktop app
- **Where:** The billing-wall banner rendered from a `BillingBlock`; strings under `billingBlock.*`; settings entry `settings.nav.billing` = "Billing".
- **What it does:** Surfaces a credit wall with a direct action to add credits, using the structured `BillingBlock` rather than parsed error text.
- **How it works:** `agent/billing_links.build_billing_block()` rides the gateway `message.complete` event; `is_nous` selects the in-app flow over `billing_url`.
- **Inputs / options:** Verbatim strings: `billingBlock.titleNous` = "Out of Nous credits"; `billingBlock.fallbackMessage` = "Your account is out of credits. Add credits to keep going."; `billingBlock.openBilling` = "Open billing"; `billingBlock.addCredits` = "Add credits"; `billingBlock.dismiss` = "Dismiss"; `assistant.thread.errorLayers.billing` = "Out of credits"; `notifications.native.creditsTitle` = "Credits"; `settings.notifications.kinds.credits.label` = "Credit alerts"; `settings.notifications.kinds.credits.description` = "Credit access is paused or restored."
- **Outputs / side effects:** Opens the in-app billing surface or the provider's billing URL.
- **Config / env:** n/a.
- **Edge cases / guards:** A third-party provider has no in-app flow, so the deep link is the only action.
- **Rebuild notes:** One structured signal rendered identically on every surface.

### Web dashboard OAuth provider panel  `id: providers.web-oauth-panel`
- **Surface:** Web dashboard
- **Where:** The "Provider Logins (OAuth)" panel; strings under `oauth.*` in `web/src/i18n`; backed by `/api/providers/oauth*`.
- **What it does:** Connects, disconnects and monitors every OAuth provider from the browser, including the paste-the-code flows.
- **How it works:** start → (browser or device code) → submit/poll → connected; external-CLI providers are shown read-only.
- **Inputs / options:** Verbatim strings: `oauth.title` / `oauth.providerLogins` = "Provider Logins (OAuth)"; `oauth.connected` = "Connected"; `oauth.expired` = "Expired"; `oauth.notConnected` = "Not connected. Use Login when available, or run {command} in a terminal."; `oauth.runInTerminal` = "in a terminal."; `oauth.noProviders` = "No OAuth-capable providers detected."; `oauth.login` = "Login"; `oauth.disconnect` = "Disconnect"; `oauth.managedExternally` = "Managed externally"; `oauth.copied` = "Copied ✓"; `oauth.copyCode` = "Copy code"; `oauth.copyFailed` = "Could not copy automatically. Select the code and copy it manually."; `oauth.cli` = "Copy"; `oauth.copyCliCommand` = "Copy CLI command (for external / fallback)"; `oauth.connect` = "Connect"; `oauth.sessionExpires` = "Session expires in {time}"; `oauth.initiatingLogin` = "Initiating login flow…"; `oauth.exchangingCode` = "Exchanging code for tokens…"; `oauth.connectedClosing` = "Connected! Closing…"; `oauth.loginFailed` = "Login failed."; `oauth.sessionExpired` = "Session expired. Click Retry to start a new login."; `oauth.reOpenAuth` = "Re-open auth page"; `oauth.reOpenVerification` = "Re-open verification page"; `oauth.submitCode` = "Submit code"; `oauth.pasteCode` = "Paste authorization code (with #state suffix is fine)"; `oauth.waitingAuth` = "Waiting for you to authorize in the browser…"; `oauth.enterCodePrompt` = "A new tab opened. Enter this code if prompted:"; `oauth.pkceStep1` = "A new tab opened to claude.ai. Sign in and click Authorize."; `oauth.pkceStep2` = "Copy the authorization code shown after authorizing."; `oauth.pkceStep3` = "Paste it below and submit."; `oauth.flowLabels.pkce` = "Browser login (PKCE)"; `oauth.flowLabels.device_code` = "Device code"; `oauth.flowLabels.external` = "External CLI"; `oauth.expiresIn` = "expires in {time}"; `env.llmProviders` = "LLM Providers"; `env.providersConfigured` = "{configured} of {total} providers configured".
- **Outputs / side effects:** Writes credentials via the API.
- **Config / env:** n/a.
- **Edge cases / guards:** The PKCE step copy is Anthropic-specific (claude.ai).
- **Rebuild notes:** Three flow labels driving three different UI paths over the same start/submit/poll API.

### Web dashboard model analytics strings  `id: providers.web-model-analytics`
- **Surface:** Web dashboard
- **Where:** The analytics/models views; strings under `models.*` and `analytics.*` in `web/src/i18n`; backed by `/api/analytics/models` and `/api/analytics/usage`.
- **What it does:** Renders per-model token spend, estimated cost and call counts.
- **How it works:** Reads the two analytics endpoints.
- **Inputs / options:** Verbatim strings: `models.modelsUsed` = "Models Used"; `models.estimatedCost` = "Est. Cost"; `models.tokens` = "tokens"; `models.sessions` = "sessions"; `models.avgPerSession` = "avg/session"; `models.apiCalls` = "API calls"; `models.toolCalls` = "tool calls"; `models.noModelsData` = "No model usage data for this period"; `models.startSession` = "Start a session to see model data here"; `analytics.dailyTokenUsage` = "Daily Token Usage"; `analytics.noUsageData` = "No usage data for this period".
- **Outputs / side effects:** Display only.
- **Config / env:** n/a.
- **Edge cases / guards:** Cost is labelled "Est." because it is an estimate, never an invoice.
- **Rebuild notes:** Two endpoints, one table and one chart.

---

## 15. Addenda

### Nous Portal request tags & ambient conversation context  `id: providers.portal-tags`
- **Surface:** Core
- **Where:** `agent/portal_tags.py` (144 lines) — `nous_portal_tags(session_id=None)`, `set_conversation_context()`, `reset_conversation_context()`, `get_conversation_context()`.
- **What it does:** Ensures every Hermes request that hits the Nous Portal — main agent loop, auxiliary client (compression / titles / vision / web_extract / session_search / …) and any future code path — carries the same product-attribution tags, and attributes them to the right conversation without threading a `session_id` through dozens of call sites.
- **How it works:** `nous_portal_tags()` (`:120-144`) always returns a **fresh list** so callers can mutate it freely (e.g. `merged_extra.setdefault("tags", []).extend(nous_portal_tags())`). Base tags: `"product=hermes-agent"` and `hermes_client_tag()` = `f"client=hermes-client-v{__version__}"` (`:98-103`). A high-cardinality `conversation=<id>` tag (`conversation_tag`, `:106-117`) is appended only when an id is available — resolved as **ambient context first**, explicit argument as fallback (`:141`). The ambient value is published by the agent loop at turn entry via `set_conversation_context(conversation_id)` (`:59-67`), which returns a ContextVar token for `reset_conversation_context(token)` (`:70-77`) on turn exit; a token from another Context (e.g. reset on a different thread) falls back to clearing rather than raising in a cleanup path. `_conversation_id` is a `ContextVar` (not a module global) so concurrent agents in one process — gateway sessions, `delegate_task` subagents, batch runners — never see each other's conversation id; worker threads spawned via `tools.thread_context.propagate_context_to_thread` (background review, MoA fan-out, tool executor) inherit it through the copied Context, and bare threads (the title generator) capture it explicitly at spawn time. `_hermes_version()` (`:85-95`) falls back to `"unknown"` if `hermes_cli` cannot be imported.
- **Inputs / options:** optional `session_id`.
- **Outputs / side effects:** The `extra_body["tags"]` list on every Portal request.
- **Config / env:** n/a — the version is sourced live from `hermes_cli.__version__` so it auto-aligns to the installed release (the release script `scripts/release.py` regex-bumps that single string and every Portal request picks up the new tag on the next process start).
- **Edge cases / guards:** Consumers must NOT pre-compute these as module-level constants — the version can change at runtime (editable installs, hot-reload tooling), and `hermes_cli.__version__` is the canonical source of truth. The helper exists because four call sites (main-loop profile, aux client, `run_agent` compression fallback, `web_tools` fallback) used to drift apart — PR #24194 only fixed the aux site, leaving the main loop sending a different tag set.
- **Rebuild notes:** Two static tags + one ambient contextvar. A better version would carry the tags as request metadata rather than an `extra_body` field.

### Nous auth keepalive  `id: providers.nous-auth-keepalive`
- **Surface:** Core
- **Where:** `hermes_cli/nous_auth_keepalive.py` (189 lines) — `start_nous_auth_keepalive()` / `stop_nous_auth_keepalive(timeout=5.0)` / `refresh_nous_auth_keepalive_once()`.
- **What it does:** Keeps a long-lived Nous Portal session's credentials warm in the background so a gateway or cron process does not wake to an expired token.
- **How it works:** A daemon thread with a stop `Event` under `_keepalive_lock`; `_keepalive_loop()` (`:126`) sleeps between refreshes and `_refresh_selected_pool_entry()` (`:47`) refreshes the currently selected pool entry through `resolve_nous_runtime_credentials`, guarded by `_agent_key_is_usable` / `_is_expiring` from `hermes_cli.auth`. `_entry_state(entry)` (`:39`) snapshots `agent_key`, `agent_key_expires_at` and `scope`.
- **Inputs / options:** `NOUS_AUTH_KEEPALIVE_INTERVAL_SECONDS = 6*60*60` (6 hours); `NOUS_AUTH_KEEPALIVE_INITIAL_DELAY_SECONDS = 60`.
- **Outputs / side effects:** Refreshed tokens written back to `auth.json`.
- **Config / env:** `HERMES_NOUS_TIMEOUT_SECONDS` (default `15`) via `_timeout_seconds()` (`:30`); `ACCESS_TOKEN_REFRESH_SKEW_SECONDS = 120`; `NOUS_INVOKE_JWT_MIN_TTL_SECONDS = 120`.
- **Edge cases / guards:** Only one thread per process; `AuthError` is caught so a failed refresh does not kill the loop.
- **Rebuild notes:** A 6-hour daemon refresher over the pool's selected entry.

### `hermes dashboard register` — register a self-hosted dashboard with Nous Portal  `id: providers.dashboard-register`
- **Surface:** CLI
- **Where:** `hermes dashboard register [--name NAME] [--redirect-uri REDIRECT_URI] [--portal-url PORTAL_URL]`; `hermes_cli/dashboard_register.py` (~350 lines).
- **What it does:** "Register this install as a self-hosted dashboard with your Nous Portal account. Creates an OAuth client, writes HERMES_DASHBOARD_OAUTH_CLIENT_ID into ~/.hermes/.env, and prints how to engage the login gate. Requires being logged in (hermes setup)." It automates what a user otherwise does by hand — open the Portal `/local-dashboards` page, click "register", copy the resulting `agent:{id}` OAuth client id, and paste it into `.env`.
- **How it works:** `cmd_dashboard_register(args)` (`:230`): (1) resolve a fresh Nous Portal access token from the existing login in `~/.hermes/auth.json` via `resolve_nous_access_token()`, refreshing if needed; (2) POST to `{portal}/api/oauth/self-hosted-client` with that bearer, which creates a `SELF_HOSTED` agent client owned by the caller's org and returns the fully-formed `agent:{id}` client_id — the `agent:` prefix is applied **server-side**, so this client never needs to know the namespace convention (`_register_self_hosted_client`, `:93`); (3) write `HERMES_DASHBOARD_OAUTH_CLIENT_ID` and, when absent, `HERMES_DASHBOARD_PORTAL_URL` into `~/.hermes/.env` idempotently; (4) print the post-register hint (`_print_post_register_hint`, `:179`). `_resolve_portal_base_url(override)` (`:65`) picks the portal. `_generate_dashboard_name()` (`:60`) builds a Docker-style `adjective_noun` label from `_NAME_ADJECTIVES` (45 entries: amber, bold, brave, bright, calm, clever, cosmic, crisp, dreamy, eager, electric, fancy, gentle, golden, happy, hidden, jolly, keen, lively, lucid, lunar, mellow, merry, mighty, nimble, noble, polished, quiet, quirky, rapid, serene, sharp, shiny, silent, snappy, solar, spry, stellar, sunny, swift, tidy, vivid, vibrant, witty, zesty) and `_NAME_NOUNS` (43 entries: albatross, antelope, badger, beacon, comet, condor, cypress, dolphin, ember, falcon, ferret, galaxy, glacier, harbor, heron, ibex, jaguar, kestrel, lantern, lynx, meadow, nebula, ocelot, orchid, otter, panther, petrel, quasar, raven, reef, sparrow, summit, tundra, vortex, walrus, willow, yarrow, plus the Docker-spirit scientist surnames kepler, tesla, curie, hopper, turing, lovelace) — there is NO uniqueness constraint on the portal side (the row id is the key), so collisions are harmless and it never retries.
- **Inputs / options:** `--name NAME` — "Human-readable label for the dashboard (default: an auto-generated name)"; `--redirect-uri REDIRECT_URI` — "Optional public HTTPS OAuth redirect URI for the dashboard, e.g. https://hermes.example.com/auth/callback. Omit for localhost-only use."; `--portal-url PORTAL_URL` — "Override the Nous Portal base URL for registration (default: the portal you logged into). The access token must be valid at this portal. Also settable via HERMES_DASHBOARD_PORTAL_URL. Mainly for testing against a staging/preview portal."; `-h, --help`.
- **Outputs / side effects:** Writes `~/.hermes/.env`. Console output, verbatim: `✓ Registered dashboard "<name>"` (or `✓ Updated dashboard "<name>"` when re-run), `  Wrote to <env_path>:`, `    HERMES_DASHBOARD_OAUTH_CLIENT_ID=<id>`, optionally `    HERMES_DASHBOARD_PORTAL_URL=<url>` and `    HERMES_DASHBOARD_PUBLIC_URL=<url>`, then `  Heads up — Nous login only *engages* on a non-loopback bind. A plain` / `  \`hermes dashboard\` (localhost) leaves the gate off and serves locally` / `  without auth, which is fine for your own machine.`, then either `  To require Nous login on your registered host, run the dashboard` / `  bound publicly (it must be reachable at https://<host>) and log in` / `  at its /login page.` (when a custom redirect URI was given) or `  To require Nous login (e.g. exposing on your LAN or a public host):` / `    hermes dashboard --host 0.0.0.0` / `  …then log in at the dashboard's /login page.`, then `  If the dashboard is already running, restart it to pick up the new env.` and `  Manage or revoke this dashboard at <portal>/local-dashboards`.
- **Config / env:** `HERMES_DASHBOARD_OAUTH_CLIENT_ID`, `HERMES_DASHBOARD_PORTAL_URL`, `HERMES_DASHBOARD_PUBLIC_URL`; `dashboard.oauth.portal_url` (default `""`).
- **Edge cases / guards:** Not logged in prints `✗ You're not logged into Nous Portal.` + `  Run \`hermes setup\` (or \`hermes auth add nous\`) first, then retry.`; a token-resolution failure prints `✗ Could not resolve a Nous Portal access token: <exc>`; a registration failure prints `✗ Registration failed: <exc>`; a `.env` write failure prints `✗ Failed to write HERMES_DASHBOARD_OAUTH_CLIENT_ID to .env: <exc>` + `  Set it manually:  HERMES_DASHBOARD_OAUTH_CLIENT_ID=<client_id>`. Managed (Docker/hosted) installs are refused with `✗ \`hermes dashboard register\` is not available in a managed/hosted install.` + `  The dashboard OAuth client is provisioned by the hosting platform.` and exit 1 — NAS stamps the client id in via `buildContainerEnvVars` and `save_env_value` refuses to write anyway. Re-running is idempotent.
- **Rebuild notes:** One authenticated POST + an idempotent `.env` write + a clear "the gate only engages off-loopback" explanation. A better version would offer to restart the dashboard for you.

---

## Handoffs

- `hermes doctor` provider health checks (`hermes_cli/doctor.py` adds a `/models` probe per `auth_type="api_key"` profile, skipping `supports_health_check=False`) — cli-* shard.
- The full desktop Settings → Providers / Accounts / API keys / Custom Endpoints pages (`settings.providers.*`, `settings.keys.*`, `settings.nav.provider*`) — desktop-settings shard.
- `hermes tools` and the Tool Gateway feature toggles behind `hermes_cli/nous_subscription.py` — tools / optional shards.
- Image-gen, TTS, STT, transcription, video-gen, web-search and browser provider registries (`agent/{image_gen,tts,transcription,video_gen,web_search,browser}_registry.py`) — these are separate provider subsystems, not model providers — optional / tools shards.
- `agent/auxiliary_client.py` task-by-task auxiliary routing and the `auxiliary.*` config namespace (115 keys) — config-a/config-b shards; this shard documents only `default_aux_model` / `resolve_aux_model` and the MoA slots.
- `agent/secret_scope.py` multiplexed secret scoping — security shard.
- `hermes secrets` / `hermes egress` and the Iron egress proxy (`agent/proxy_sources/iron_proxy.py`, config keys `proxy.enabled`, `proxy.tunnel_port`, `proxy.auto_install`, `proxy.credential_source`, `proxy.enforce_on_docker`, `proxy.allow_env_fallback`, `proxy.upstream_deny_cidrs`, `proxy.extra_allowed_hosts`) — this is the outbound egress firewall, a different subsystem from `hermes proxy` — web-shell / security shard.
- `hermes_cli/memory_oauth.py` and `/api/memory/providers/*` (memory backends) — memory shard.
- `hermes_cli/dingtalk_auth.py` and platform OAuth — platforms shards.
- `hermes cron` model pinning (`cron.model`, `cron.model_provider`, `cron.provider`, `cron.model_drift_guard`) — cli shard.
- `delegation.model` / `delegation.provider` / `delegation.reasoning_effort` subagent model routing — cli / core shard.
- `x_search.model` (`grok-4.5`) and `x_search.reasoning_effort` — tools shard.
- TUI billing/subscription overlays (`ui-tui` `SubscriptionOverlay`, credits status bar) — a TUI shard; this shard documents the shared cores (`agent/billing_view.py`, `agent/subscription_view.py`, `agent/billing_usage.py`) they render.
- `hermes_cli/web_models.py` dashboard model-payload builder internals beyond the endpoint contract — web-* shard.
