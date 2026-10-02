# H277 Nous vision integration

Generated 2026-10-02. Goal: full local Nerva/Hermes parity; this increment connects
Nous accounts to actual image consumers, not merely provider metadata. Base/head
54e5bf1b on codex/h277-provider-discovery-20261002. Prior goal turn made concrete
progress: encrypted auth/CLI/API and 20,983 passing backend cases committed.
Pinned reference: 59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e. Local work only;
no push, merge, deployment, credential copying or live/paid requests.

## Design and scope

Keep explicit vision roles; Nous login alone enables nothing. Add Nous vision
profile and JARVIS_ROLE_VISION_PROVIDER=nous. JARVIS_ROLE_VISION_PROFILE selects
an owned account profile, default default. The account owns issuer and inference
endpoint; a role base must match its prepared inference endpoint, and a role key
cannot silently replace OAuth. JARVIS_NOUS_INFERENCE_BASE_URL remains the explicit
account endpoint override. Explicit role model wins on normal endpoints; welcome
host uses nous/welcome. JARVIS_NOUS_ANTHROPIC_WIRE mirrors pinned chat/native/auto:
chat default; native for anthropic/* uses Messages; auto remains chat because the
pinned upstream has not cleared native promotion. Invalid mode falls back to chat
as upstream does. No new dependency or unrelated refactor.

Composer GET status prepares usable credentials off-loop and discovers the model.
POST and role/policy readers never refresh OAuth or discover a replacement model.
Preparation persists a small encrypted selection under the account profile after
checking that credentials/configuration still match, so another hub worker can
resolve the selection. Logout, issuer/client/token/config drift and expiry make
old selection unavailable. Existing destination fingerprints and independent
remote/training/cost confirmations bind actual account/key/model/endpoint/wire.
Actual transport checks run after request hooks and immediately before the socket.
Local-only image consumers stay local, and inherited Nous video remains explicitly
unavailable until its own adapter contract is implemented.

Recommendations follow hermes_cli/models.py and nous_account.py: public GET
/api/nous/recommended-models (no bearer), 600-second profile/Portal cache plus
bounded persistent public last-good data; stale disk fallback on network failure.
Known free account uses freeRecommendedVisionModel only; paid/unknown uses paid
then free; missing recommendation falls back to google/gemini-3.6-flash. JWT
paid_access provides a local entitlement snapshot; explicit refresh may use
issuer-bound GET /api/oauth/account. Entitlement cache is 180 seconds and isolated
by profile/issuer/credential identity. No private account metadata is written in
the public cache. Welcome host skips metadata and returns nous/welcome. Requests
use bounded direct HTTP with no redirects, finite total deadline/bytes and final
configuration validation. Concurrent stale fetches cannot overwrite newer refresh.

Native Nous image inference implements both chat/completions and Messages payloads,
Bearer account auth (not Anthropic API-key substitution), model-correct response
normalization and bounded response/deadline. Existing image sizing, signed request
checks, empty recovery budget and selection policy remain enforced. The intended
wire is part of the reviewed identity, including method/path/headers/model/body.
Automatic main -> OpenRouter -> Nous -> DeepInfra selection remains the next shared
routing step; do not claim it from this explicit adapter. Auth pool/anonymous and
live acceptance remain separately open.

## Ownership and interfaces

Two Sol High implementers, no subdelegation. Root owns consumer/runtime integration,
shared VLMConfig/vision policy, roles/profile, HTTP/HUD, documentation and evidence.

A owns new agents/core/llm/nous_models.py and tests/test_h277_nous_models.py:
- frozen Recommendation(model: str, source: str).
- async recommend_vision(credentials: NousCredentials, *, force_refresh=False,
  validate=None, client_factory=None, cache_dir=None) -> Recommendation.
  validate is a synchronous callback raised on revoked/config-changed authority;
  check it at physical request and before cache publication/return. Cancellation
  and validation errors do not silently become a fallback selection.
- clear_cache() resets bounded process cache. Public persisted data is profile and
  Portal scoped, contains only normalized model recommendations plus timestamps.
- wire_mode(model, configured='chat') returns chat_completions or anthropic_messages.
Default transport uses a module _transport_factory seam for synthetic HTTP tests.

B owns new agents/core/llm/vision_nous.py, tests/test_h277_nous_vision_config.py,
and may extend nous_auth.py/test_h277_nous_auth.py with a pure peek_credentials
method sharing existing issuer/expiry checks. No other writer touches those files.
- resolve_config(env=None) -> VLMConfig; reads local owned state only.
- async prepare_config(env=None, *, force_refresh=False) -> VLMConfig; refreshes
  account before selection, calls A, atomically publishes matching selection.
- model_source(env=None) -> str; safe label only, no private values.
- Root adds VLMConfig.wire_mode default chat_completions; Nous resolver populates it.
No final transport implementation in B. Test stand-ins for A must be replaced by
real integration tests at root, not mistaken for recommendation proof.

## Verification and rollback

Red-first synthetic tests for recommendations/tier/cache/restart/concurrency,
profile logout/rotation and preparation races, default/native/auto payload paths,
actual composer send and late mutation refusals. Run focused tests at each step,
then combined routes/OpenAPI/HUD/documentation gates (all together), TypeScript,
full backend at clean frozen source, and truthful evidence. Run browser/UI checks
only for changed frontend runtime. Strict scan exact staged set before commits.
Rebuild/check Graft after final source edits; local cache remains uncommitted.
Rollback this increment's source and associated generated records as one unit;
retain independent Nous authentication delivered previously.
