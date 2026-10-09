# H277 Nous authentication prerequisite

Generated 2026-10-02. Goal: full local Hermes parity, continuing provider discovery.
Base/head: `7a73bf03` on `codex/h277-provider-discovery-20261002`.
Pinned Hermes: `59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`.
Previous goal turn made concrete progress: DeepInfra integration, full suites and
truthful records committed. This increment remains local, with synthetic credentials
and mocked provider HTTP only. No push, merge, deployment or live provider request.

## Evidence and design

Pinned auth_nous.py uses scoped inference JWTs, refresh POST at `/api/oauth/token`
with `x-nous-refresh-token` and form grant_type/client_id, serializes refresh under
the auth-store lock, adopts an already rotated peer token, and distinguishes
terminal OAuth rejection from network/rate/edge failure. auth_device_flow.py uses
`/api/oauth/device/code`, device-code grant polling, pending/slow_down/expiry states.
Do not reuse Hermes auth files, shared stores, client credentials or rotating tokens.
Nerva has encrypted SecretStore primitives but no Nous account lifecycle.

Build a Nerva-owned profile store and usable synchronous auth service. Owner API
handlers run blocking service work in a thread. CLI login prints the provider
verification URI/user code and polls the owner API; credentials never leave the hub.
All routes require existing admin_guard. Status is read-only/no network; logout
clears only local account state and pending login. Login alone enables no inference.
A registered public OAuth client ID must be set in JARVIS_NOUS_CLIENT_ID; do not
invent a Nerva client ID or silently identify this application as hermes-cli.
This configuration requirement and untested provider acceptance remain explicit.

## Fixed interfaces and ownership

Writer A owns new agents/core/llm/nous_credentials.py and its test module.
`NousAuthStore(path=None, *, cipher=None)` defaults to a dedicated SQLite file under
Nerva data_root/security. `read(profile='default') -> dict` creates nothing if absent.
`transaction(profile='default')` yields a mutable dict and atomically encrypts and
commits changes with existing SecretStore.encrypt_value/decrypt_value. BEGIN IMMEDIATE
and bounded busy timeout serialize concurrent threads/processes, including refresh;
exceptions roll back. Profile names are validated `[A-Za-z0-9][A-Za-z0-9_-]{0,63}`.
No caches of decrypted state. Empty state deletes only that profile. Bound state size.
`usable_inference_token(state, *, now=None, min_ttl=120) -> str | None` prefers usable
agent_key then access_token; checks JWT shape/finite expiry and inference:invoke scope
from declared/JWT scope/scp. Decoding is usability metadata, not signature verification.
Opaque, malformed, near-expired tokens cannot become inference credentials.

Writer B owns new agents/core/llm/nous_auth.py and its test module. It consumes A's
interfaces. `NousAuthService(store=None, *, env=None, client_factory=None, clock=None)`
provides synchronous start_login(profile='default'), poll_login(profile, login_id),
status(profile='default'), logout(profile='default'), and
prepare_credentials(profile='default', *, force_refresh=False, stale_access_token=None).
prepare returns frozen NousCredentials(profile, api_key repr=False, base_url,
portal_base_url, expires_at), with no model selection yet. Named NousAuthError.reason
is bounded/sanitized for routes. All other methods return secret-free public dicts.
start returns login_id/user_code/verification_uri/verification_uri_complete/expires_in/
interval; poll returns state pending/complete/expired and retry_after where needed.
Store pending device_code encrypted, bind poll to random login_id, enforce interval
and expiry before HTTP, persist slow_down. Preserve previous credentials until a
successful login; logout invalidates pending flows. Serialize refresh; adopt a usable
peer token if stale_access_token differs. Terminal invalid_grant/token_reused/denied
clears dead tokens with a safe reason, transient errors retain them. Persist the
terminal quarantine before raising (not rollback). Fresh JWT scope/expiry is validated.

Service configuration: JARVIS_NOUS_PORTAL_URL defaults to
https://portal.nousresearch.com; JARVIS_NOUS_CLIENT_ID must be explicitly configured
for login. JARVIS_NOUS_INFERENCE_BASE_URL is an explicit operator endpoint override.
Default inference is https://inference-api.nousresearch.com/v1; network-provided
bases permit only HTTPS/default443 on inference-api or welcome-api.nousresearch.com,
or the exact configured override. Invalid network endpoints fall back to canonical.
Reject URL credentials/query/fragment/control chars and remote plain HTTP. Only
loopback dev overrides can use HTTP. Never use network-returned client_id/portal to
choose a credential destination. Verification links must remain on the chosen Portal.
Instrument native llm_client('nous-auth'), no environment proxies/cookies/redirects;
bound response size and deadline, validate outgoing URL/form/auth at physical transport
and current configuration after response. Never include provider diagnostics/tokens
in exceptions/status/logs. Test fixtures never contact live services.

Coordinator owns owner API routes (existing oauth router), CLI helper/parser wiring,
actual API/CLI tests, generated schema/docs and integration. No shared-file writes.
Max two Sol High implementers, no subdelegation. Root reviews security interfaces.

## Verification and continuation

Red-first tests cover persistence encryption/restart/profile isolation/concurrency,
JWT scope/expiry, device flow, polling cadence, refresh header/body, peer rotation,
terminal quarantine vs transient retention, hostile URLs and credential-safe outputs.
Actual owner routes and CLI must exercise the service; unprivileged requests refuse.
Run focused checks per step, one frozen full-suite milestone and truthful records.
H277 remains partial. Next: connect this auth service to tier-aware Nous vision
recommendations, welcome model and native Anthropic Messages handling; then actual
main context → OpenRouter → Nous → DeepInfra automatic selection. Credential-pool
breadth, anonymous identity lifecycle, SDK recovery and broader Hermes scope stay open.
Rollback is the new auth modules, API/CLI wiring and associated generated records;
no existing credential store is migrated or rewritten.
