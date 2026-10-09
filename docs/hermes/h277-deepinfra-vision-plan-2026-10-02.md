# H277 DeepInfra vision adapter and catalog discovery

Generated 2026-10-02. Goal: advance the complete Hermes provider-discovery contract
against pinned Hermes `59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`.
Base/head: `0e617d63b51d3d8ddb6dd996b5cf5502d9f8d365`, branch
`codex/h277-provider-discovery-20261002`. Previous goal turn delivered and verified
image selection confirmations. This next dependency stays local; no live provider
call, credential migration, paid usage, push, merge or deployment.

## Verified upstream contract

DeepInfra explicit vision accepts the specified model; absent a model, its plugin
selects the first served catalog entry passing the chat filter and carrying the
vision tag. Known surface tags take priority; entries with no surface tags use the
legacy ID exclusion regex from `hermes_cli/models.py`. Null metadata means an
unserved stub. No successful catalog selection means unavailable, never a guessed
model. The request is GET base/models?filter=true&sort_by=hermes with scoped bearer
credentials. Positive and negative catalog caches are scoped by base and key;
negative TTL is60 seconds. Catalog discovery is distinct from paid inference.

## Implementation contract

Explicit `JARVIS_ROLE_VISION_PROVIDER=deepinfra` enables this adapter only.
An explicit `JARVIS_ROLE_VISION_MODEL` bypasses discovery. Otherwise the real
composer status prepares the catalog-backed model before issuing its destination
revision. Normal role resolution and all physical-request rechecks remain pure:
they use that exact cached selection or refuse. POST never discovers a replacement
after the user has reviewed a destination. Status accepts optional
`refresh_catalog=true` for explicit refresh; other providers retain their behavior.
`reachable=null` still means no inference connectivity probe; document that
DeepInfra status can make a credential-bearing metadata request.

Canonical base is https://api.deepinfra.com/v1/openai. Role base wins over
DEEPINFRA_BASE_URL and the default. Dedicated ROLE_VISION_KEY wins; ambient
DEEPINFRA_API_KEY serves only canonical HTTPS origin/default443. Any custom origin
needs the dedicated role key. Ignore legacy VLM credentials/models and reject
malformed URLs, models or headers. No credential alone selects this provider.

New module `agents/core/llm/vision_deepinfra.py` owns `resolve_config(env=None)`
(pure, VLMConfig backend deepinfra), `prepare_config(env=None, *, force_refresh=False)`
(async metadata preparation), and `model_source(env=None)` (role env or catalog).
Use instrumented native HTTPX direct transport, no redirects/proxies/cookies,
bounded5-second metadata deadline and2 MiB response cap; sanitize failures.
Cache only validated model selection/catalog data, scoped by normalized base and
credential fingerprint, bounded to32 entries; positive results persist in process
until explicit refresh, matching upstream. Negative results expire after60 seconds.
Revalidate configuration and actual URL/auth at physical send and after response;
rotation or mutation must not publish a newly discovered model under old settings.

Register a truthful DeepInfra vision/catalog cloud profile with unknown data policy;
do not advertise an unwired main-chat adapter. Role provenance names catalog vs
explicit model. Extend native VLM identity/transport for DeepInfra, preserving
OpenRouter-specific body controls. Every DeepInfra inference needs the existing
remote/selection confirmation, exact model/destination binding, last HTTP hook,
bounded response and optional same-body recovery. Model/cache/config changes revoke
approval. Local-only consumers remain local; inherited signed video explicitly
refuses until its own supported adapter exists.

## Ownership and verification

Writer A: new vision_deepinfra module and its resolver/catalog tests only.
Writer B: providers/__init__.py, model_roles.py and focused role/profile tests only,
using the interface above. Coordinator: vlm.py, vision_policy.py, composer_vision.py,
real composer tests, any refresh UI adjustment, docs/evidence/integration.

Red-first tests: catalog order/tags/legacy fallback/null metadata; explicit model;
credential origin/rotation; positive/negative cache isolation/refresh; bounded and
malformed responses/redirects/late hooks; actual status→confirmation→composer POST;
no new discovery or fallback after preview; no inference without independent
consent; strict-local and video refusal. Run meaningful focused suites per step,
then one frozen milestone full suite and current evidence gates. Preserve H277
partial: Nous, actual-main integration, complete automatic provider order, native
SDK breadth and broader Hermes backlog remain accepted unfinished work.

Rollback: revert this adapter/catalog integration and generated records. No live
settings or credential stores are migrated. Next action: implement the two
independent provider seams, then connect them to actual composer preparation.
