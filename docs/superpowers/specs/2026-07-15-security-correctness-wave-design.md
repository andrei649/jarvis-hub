# Fresh-Eyes Security Correctness Wave Design

## Goal

Close the verified critical and high correctness gaps from the 2026-07-15
fresh-eyes audit in one integration wave and one draft pull request. The wave
must restore the product's strict-local privacy promise, make cloud failures
secret-safe, make autonomy policy metadata server-owned, fail closed at
external identity boundaries, and make the advertised email transport usable.

The delivery shape is one branch, `codex/security-correctness-wave`, with
bounded commits per subsystem and one final GitHub CI cycle.

## Ground Truth

The design targets the current `main` baseline at
`57976b658d56c87873da66328fa941d0b77cfa10`.

Verified open defects:

- The hybrid router selects the correct backend for strict-local agents, but a
  boot-bound `GuardrailsEngine` later replaces it with the router's preferred
  global backend. With Claude configured, Frigga, Ultron, and Howard can send a
  prompt to Anthropic despite a local-only route decision. The same composition
  error exists in normal generation, streaming, and synthesis.
- Gemini authentication is placed in URLs and raw HTTP exceptions are returned
  to chat. A failed request can therefore copy the API key into conversation
  memory, run history, learning records, and logs. Context-cache and plugin
  call paths repeat the URL-secret pattern.
- The Gemini cached-content name is stored on the guardrails singleton instead
  of the selected Gemini backend. Shared mutable cache state is also unsafe for
  concurrent sessions.
- The default Claude model was retired on 2026-06-15. Existing settings rows
  keep the retired default because settings seeding is insert-only, and current
  Claude models are absent from the cost table.
- Autonomy intake lets proposal payloads shadow authoritative `kind` and
  `risk_tier` values. A destructive proposal can therefore be classified as a
  read-only action. External HTTP intake is admin-guarded and inbound taint adds
  another approval boundary, so this is a policy-integrity defect rather than
  a demonstrated unauthenticated execution path.
- HTTP rate limiting trusts `X-Forwarded-For` without the trusted-proxy posture
  used by authentication. Rotating the header evades the limiter, and reaching
  the IP cap clears every active bucket.
- Telegram starts from a bot token alone, with no sender allowlist and pairing
  disabled by default. Pairing errors fail open, and autonomy callbacks do not
  require both owner-chat and owner-user identity.
- Email startup passes keyword arguments that `EmailChannel` does not accept.
  Even after constructor repair, `ChannelManager` rejects email sends, so the
  live approved-reply path cannot succeed.

Two audit claims are excluded because they are stale on this baseline:

- the release/status-sync gate is currently green;
- `orch.tool_rpc` and `orch.writeback` are installed by the normal autonomy
  coordinator boot path.

Provider facts are grounded in the official
[Google Gemini API reference](https://ai.google.dev/api),
[Anthropic model deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations),
and [Anthropic migration/pricing guidance](https://platform.claude.com/docs/en/about-claude/models/migration-guide).

## Scope

### In scope

1. Route-preserving, request-bound guardrails for regular generation, tool
   turns, streaming, and synthesis, including output/tool-argument enforcement
   before protected data reaches a consumer.
2. Request-scoped Gemini cached-content selection with concurrency isolation,
   model/system/profile ownership, and invalid-cache recovery.
3. Secret-safe Gemini HTTP authentication and error handling across the main
   backend, context cache, and cloud-LLM plugin.
4. A single current Claude default, a conditional settings migration from the
   retired default, and a non-zero cost entry for the configured default.
5. Server-owned autonomy policy metadata at every worker intake and edit seam.
6. Trusted-proxy-peer-validated HTTP client identity and bounded rate-limit
   overflow behavior that preserves existing active buckets under churn.
7. Fail-closed Telegram startup, sender pairing, and autonomy approval identity.
8. Correct SMTP/IMAP construction and email dispatch through the real channel
   manager contract.
9. Regression tests, canonical configuration documentation, backlog truth, and
   the mobile parity ledger note required for changed user-facing behavior.

### Non-goals

- Do not redesign the router policy, add a second egress-control framework, or
  force cloud-capable agents onto local models.
- Do not change the autonomy HTTP schema or remove trusted explicit risk tiers
  from internal producers.
- Do not add new communication channels, an email compose UI, or a new pairing
  UI.
- Do not claim cryptographic email-sender identity or redesign cost-trace model
  attribution; this wave fixes transport and price-table correctness only.
- Do not turn the writeback or Tool-RPC residual degraded-startup behavior into
  this wave; healthy boot already wires both surfaces.
- Do not perform unrelated orphan-module cleanup, memory-pillar work, hardware
  validation, or broad refactors.
- Do not claim live Telegram, SMTP, IMAP, or cloud-provider validation without
  owner credentials. The automated acceptance layer remains hermetic and must
  be labeled as such.

## Delivery Architecture

Use one integration branch and one draft PR. Keep the branch bisectable through
the following logical commits:

1. route-preserving guardrails and request-scoped Gemini cache;
2. Gemini secret safety plus Claude default/migration/cost truth;
3. autonomy reserved-field integrity;
4. HTTP and Telegram external-identity hardening;
5. email startup and live channel-manager dispatch;
6. canonical docs, parity ledger, backlog, generated status artifacts, and any
   cross-cutting test adjustments.

Independent work may be prepared in isolated worktrees, but no intermediate PR
is created. Every worker must acquire the repository's component lock through
`lock.py` before editing and release it after its commit is handed back. At most
two workstreams run in parallel, so this remains one integration wave rather
than the three-or-more parallel-PR pattern that requires a dedicated conductor.
The lead agent integrates the commits, resolves shared-file changes in
`agents/web.py`, runs the combined gates, pushes once, and opens one draft PR.

## Component Design

### 1. Route-preserving guardrails

`HybridRouter.select_backend()` remains the sole source of the request's
backend and routed model. The orchestrator constructs the guardrails policy
prototype whenever guardrails are enabled, even when no LLM backend exists at
boot. `GuardrailsEngine` accepts an unbound prototype state and gains an
immutable binding method that creates a request wrapper around the selected
backend while copying the boot-loaded mode and input/output scanning
configuration. Calling generation on an unbound prototype is an error; it
never bypasses scanning.

Call sites must bind in this order:

1. select the backend and routed model;
2. configure request-only backend context, if any;
3. bind guardrails to that backend;
4. generate or run the tool turn;
5. release request-only context in a `finally`-safe scope.

No request may mutate `self.security._backend`. A mutable global replacement
would allow concurrent requests to route through each other's backends.
Normal `Agent.process`, `Agent.synthesize`, and the orchestrator streaming path
use one shared binding helper. Tool-runtime capability checks operate on the
bound wrapper, whose `supports_tools` property delegates to the selected
backend. A boot with no model followed by successful provider re-detection
must therefore produce a guarded first request rather than leaving guardrails
disabled.

Output enforcement is defined by mode:

- `WARN` preserves true token streaming and scans/logs the completed response;
- `REDACT` and `BLOCK` buffer provider output, scan it before invoking the
  caller's token callback, then emit only the redacted safe result or raise;
- tool-call argument strings and parsed string values are output, not trusted
  control metadata. `WARN` observes them, `BLOCK` refuses a turn with findings,
  and `REDACT` recursively redacts string values and regenerates matching JSON
  without changing tool name, call ID, or non-string values.

Malformed tool arguments remain non-executable under the existing parser. A
redaction that cannot preserve valid JSON fails closed instead of forwarding
the original arguments. Regenerated JSON is scanned again; a finding that
survives in a non-string value, such as a numeric identifier, also fails closed.

Strict-local failure stays fail-closed. Normal, tool, and streaming selection
failures return one deterministic privacy-safe local-unavailable message and
make zero cloud calls. If the selected synthesis backend is unavailable,
synthesis returns the already-produced constituent reports without an extra
LLM call. Guardrails must not create a cloud fallback or perform provider
selection in any path.

Cache creation is also an LLM egress. Before Gemini receives a system
instruction or history payload, the guardrails policy recursively scans every
string in that material. `BLOCK` performs zero cache network calls; `REDACT`
uploads only the redacted copy; `WARN` preserves the existing observe-only
behavior. The original in-memory history is never mutated.

### 2. Request-scoped Gemini cache

Remove the shared `_use_cache` mutation from the streaming orchestrator path.
The Gemini backend owns a structured request-local binding, implemented with
task-local context rather than instance strings. The binding carries an
immutable auth-profile lease (`profile_id` plus key for this attempt), optional
cache name/session identity, and an invalidation callback owned by
`ContextCache`. Payload and header construction read the same lease, so cache
selection and generation cannot observe different active profiles if another
task rotates the pool concurrently. Nested scopes restore their parent value,
and the value is reset after the request, including exceptions, cancellation,
and an uncached request that follows a cached request.

This keeps the generic LLM interface stable, avoids adding a Gemini-only
keyword to every backend and test double, and prevents one session's cache name
from leaking into another concurrent request. The guardrails wrapper delegates
inside the same task context, so cache selection survives wrapping without a
mutable proxy property.

`ContextCache.acquire_binding(session, model, system, history, policy, lease)`
performs the fingerprint and history-boundary lookup under the per-session
lock. Only a valid returned binding allows the orchestrator to omit the cached
history prefix from the prompt. The binding records the cached prefix turn
count and digest; every turn after that boundary is included exactly once as
an uncached tail. A changed/truncated prefix is a miss, keeps the complete
uncached prompt, and may schedule cache recreation.

`ContextCache` serializes create/extend decisions per session. Each persisted
entry records the existing cache name, cached-prefix count/digest, a hash of
system instruction/model, guardrail policy/scanner version, and a
non-reversible fingerprint of the active auth profile. A changed model, system
instruction, history prefix, active profile, guardrail mode/scan flags, or
scanner version invalidates the mapping and creates a new cache. Legacy entries
without these fields are misses. The raw key and raw history are never
persisted. A cache-specific 400/404 response
invokes the binding's session-aware invalidation callback; `GeminiBackend`
then clears cached content and retries that generate or stream call exactly
once, on the same auth lease. An auth failure reports that exact lease to the
pool and obtains a new lease for the next bounded attempt, without carrying the
old cache name. Cache rejection is represented internally by a typed,
secret-free `CachedContentRejected` signal containing only the status code;
the common generate/stream request helper catches it, awaits the binding's
compare-and-delete invalidation callback, and owns the single uncached retry.
Other provider errors follow normal degraded handling. Background cache
creation is tracked through shutdown so it cannot write through a closed
client.

### 3. Cloud secret safety and model truth

All Gemini HTTP clients use `x-goog-api-key` for the active key. The API key
must not appear in a URL, exception returned to the user, persisted response,
or log record. This applies to:

- `GeminiBackend.generate`;
- `GeminiBackend.generate_stream`;
- Gemini context-cache create/extend/delete operations (`POST`/`PATCH`/`DELETE`);
- the Gemini branch of the cloud-LLM plugin.

Provider failures return a stable degraded message that preserves the existing
`Gemini error` signal expected by callers without embedding `str(exception)`.
Operator logs may include provider name, exception class, and numeric HTTP
status, but not the request URL, authentication header, response body, prompt,
or key. `ContextCache` receives the shared auth-profile pool and explicit
immutable leases rather than freezing only `GEMINI_API_KEY` at boot, so
installations configured only through `GEMINI_API_KEYS` are supported.
Authentication-pool rotation continues to use status codes and the leased key
internally without placing either key or raw exception text in the result.
Context-cache POST/PATCH/DELETE operations call `report_success` or
`report_failure` for the exact lease and try each healthy profile at most once;
exhaustion returns a sanitized failure.

Sanitized cloud degraded replies use the shared `is_degraded_reply` contract.
Interaction recording marks them unsuccessful, bench/promotion metrics do not
count them as successful answers, and the background learning reviewer is not
spawned for them. The generic degraded message may remain in conversation
history for user continuity, but no provider diagnostic or secret does.

`DEFAULT_CLAUDE_MODEL` becomes `claude-sonnet-4-6` and remains the canonical
source for backend, plugin, provider-registry, and settings defaults. Settings
initialization performs a conditional value migration only when the stored
`llm.claude_model` equals the retired default. Empty/new installations receive
the current default, while every custom model value remains untouched. Public
SOUL metadata and agent-template entries that currently advertise the
non-runtime `claude-sonnet-4-7` hint are aligned to 4.6 as documentation truth;
personal `SOUL.local.md` files remain untouched. The cost estimator receives
the published Sonnet 4.6 input/output prices. This is price-table coverage, not
a claim that cognition traces already attribute every call to the routed model.
Unknown models retain their existing compatibility behavior; broader
trace-attribution redesign is outside this wave.

### 4. Server-owned autonomy metadata

Define one reserved-field set for proposal payloads, including `kind`,
`risk_tier`, `agent`, `origin`, `autonomy_level`, and `attention_mode`.
`AutonomyWorker.submit`, `govern_enqueue`, and edited-task reclassification
must construct a sanitized **policy view** and then apply authoritative method
arguments last. The execution payload remains byte-compatible: fields such as
House Brain's canonical, hash-verified `risk_tier` remain stored for executor
schema validation, but they carry no policy authority.

An ordinary payload field named `name` remains available to executors. It
cannot influence classification because the authoritative `kind` is always
present and applied last in the policy view.

`submit` gains a separate optional trusted risk-tier argument for internal
producers. Observer, watcher, and scheduler call sites move their intentional
tiers out of payload dictionaries and into this argument. The admin HTTP route
does not expose the trusted argument; a `risk_tier` embedded in its payload is
ignored for classification and for the authoritative task tier, even if it is
retained as inert executor data.

Policy evaluation is explicitly two-stage. First classify the sanitized action
without any proposal-supplied tier. Then compute
`effective_tier = max(classified_tier, trusted_tier_floor)` and calculate the
mode, money-cap, tier-outcome, earned-autonomy, and urgency result from that
effective tier. `govern_enqueue` then applies the stricter of that result, the
caller's requested autonomy level, and taint escalation. A tier-3 floor can
therefore never retain a tier-0 `ACT` decision, while a tier-0 floor can never
lower a destructive or money classification.

Trusted tier inputs accept `RiskTier` or a non-boolean integer in `0..3`.
Invalid, boolean, or out-of-range values fail closed to tier 3 and `ASK` rather
than being clamped downward or raising through the intake seam. An empty or
whitespace-only `kind` is an unknown action and also resolves to tier 3/`ASK`.
Top-level `agent`, `kind`, and `origin` method arguments define persisted task
identity; same-named payload values do not. Proposal fields may still raise
risk through existing amount, irreversibility, blast-radius, and signal-quality
rules.

Editing a blocked task may change ordinary execution payload, but reserved
fields cannot replace its stored identity or authoritative tier. The full
policy view is reclassified with the existing task tier as a floor. If it still
requires approval, it remains blocked and is re-presented to the owner.

### 5. HTTP client identity and rate-limit retention

Rate limiting reuses the same proxy-trust posture as authentication:

- without `JARVIS_TRUSTED_PROXY`, the canonicalized socket peer is authoritative
  and all forwarding headers are ignored;
- with `JARVIS_TRUSTED_PROXY`, the socket peer must also belong to a validated
  `JARVIS_TRUSTED_PROXY_CIDRS` network; otherwise forwarding headers are ignored
  and authentication fails closed behind that untrusted peer;
- for a trusted peer, parse only valid IP literals from `X-Forwarded-For`, walk
  right-to-left past configured trusted proxies, and select the first untrusted
  hop as the client. A valid `X-Real-IP` is the fallback when XFF is absent.
  The RFC `Forwarded` header is detected for fail-closed behavior but is not
  parsed in this wave;
- a missing socket identity falls into one shared unknown-client bucket rather
  than producing unbounded empty identities.

IPv4, IPv6, and IPv4-mapped IPv6 values are normalized with the standard IP
parser. Malformed or oversized header chains are ignored as a unit; they never
become attacker-chosen bucket keys.

When the 4,096-client bound is reached, prune expired buckets first. If no slot
opens, unseen clients share one overflow bucket reserved inside the 4,096-entry
cap; existing buckets are never evicted or cleared by identity churn. This
intentionally prefers possible over-throttling of new clients over resetting a
limited attacker's bucket. A deployment behind an unconfigured proxy may share
one proxy/unknown bucket and over-throttle; that is the intended safe failure
mode and is documented.

### 6. Telegram identity posture

Parse a canonical integer `TELEGRAM_ALLOWED_USER_IDS` owner/approver list at
startup. The value is a comma-separated list of positive Telegram user IDs;
whitespace is trimmed and duplicates are removed. A boolean, zero/negative ID,
oversized value, or malformed token invalidates the whole list and fails closed
instead of silently ignoring the bad entry. Telegram may start only in one of
these postures:

- static allowlist: at least one allowed Telegram user ID is configured;
- governed pairing: `JARVIS_CHANNEL_PAIRING=1` is enabled.

A bot token with neither posture does not register or start the Telegram
adapter and does not instantiate the HTTP client or call Telegram `getMe`. The
rest of Jarvis still starts, and a structured startup warning tells the operator
exactly which configuration is missing. This is an intentional secure-default
change for token-only installations.

An allowlisted owner is always admitted. A non-allowlisted user is sent to
`SenderPairing` only when pairing is enabled; otherwise the message is dropped.
This rule also covers the combined posture: the static owner list bypasses
pairing, while additional chat-only contacts can still be paired. An exception
in the shared pairing gate holds/drops the message and never routes it. This
fail-closed exception behavior intentionally applies to every sender-bearing
channel using the gateway, including email and webhook channels; cross-channel
tests pin that blast radius. Pairing-approved contacts may chat but do not
inherit autonomy approval authority.

Autonomy callbacks validate authorization at callback time, not only at boot,
and require both:

- callback `chat_id` equals the configured autonomy owner chat; and
- callback `user_id` belongs to the static Telegram allowlist.

If either identity is absent or mismatched, the callback is acknowledged as
denied with a generic response that reveals neither task existence nor task
state, without calling `apply_decision`. Changing the live
`autonomy.owner_chat_id` setting invalidates the old chat immediately. In
pairing-only posture, chat works but callbacks remain denied because no static
owner user exists. Telegram log messages must avoid raw HTTP exceptions because
Telegram embeds the bot token in request paths.

### 7. Email transport correctness

Startup constructs the dictionaries already required by `EmailChannel`:

- SMTP from `SMTP_HOST`, `SMTP_PORT` (default 587, valid range 1..65535),
  `SMTP_USER`, `SMTP_PASS`,
  `SMTP_TLS` (default true), `SMTP_FROM` (default `SMTP_USER`, then the current
  local fallback), and optional `SMTP_DEFAULT_RECIPIENT`;
- IMAP from `IMAP_HOST`, `IMAP_PORT` (default 993, valid range 1..65535),
  `IMAP_USER`, `IMAP_PASS`, and `IMAP_POLL_SECONDS` (default 60, bounded to
  5..3600 seconds).

Out-of-range or malformed numeric values fall back to the documented defaults.
`SMTP_TLS` uses the shared boolean parser; an unrecognized value falls back to
the secure default `true`.

The channel remains default-off and is registered only when both host settings
are present, preserving the existing enablement rule. `ChannelManager` adds
`email` to the supported send-channel contract but accepts email dispatch only
with the internal approved-reply authority supplied by
`ChannelReplyBroker.execute`. The automatic `Orchestrator.channel_handler`
reply path does not carry that authority and therefore cannot auto-email an
inbound sender. Approved email sends use the existing `to` and `subject`
metadata and do not bypass the channel-reply approval funnel.

Before MIME construction, reject CR/LF in `From`, `To`, or `Subject`; require a
non-empty parseable destination; bound addresses to 254 characters and subject
to 255 characters; and validate ports/poll intervals through the shared env
parsers. A missing destination never opens an SMTP connection. Logs may contain
a stable failure code and server host but never password, token, message body,
or secret-bearing raw exception.

At the adapter/manager boundary, missing destination, SMTP refusal, or contract
denial returns `False`. At the approved broker boundary, that becomes the
existing explicit `{"status": "failed", "reason": "send_failed"}` result. It
must not be reported as delivered or silently converted to `deferred`.

IMAP polling has a separate observable contract because it runs in a background
task. One `poll_once()` operation returns success/failure and updates a
secret-safe health snapshot (`disabled|healthy|degraded`, stable reason, last
success/error time). The poll loop calls that operation and continues after a
degraded result; it never represents IMAP failure as an outbound `send=False`
result.

Inbound email identity continues to be tainted and participates in the shared
pairing gate when `JARVIS_CHANNEL_PAIRING` is enabled. Static email allowlists,
SPF/DKIM verification, and cryptographic sender authentication are separate
features and are not claimed by this transport-correctness wave.

## External Behavior and Compatibility

- No HTTP request or response schema changes.
- Strict-local agents become more restrictive only in the defect configuration:
  cloud keys present plus guardrails enabled. Correct local routing is restored.
- Telegram token-only installations must add a static user allowlist or enable
  pairing. This breaking change is intentional and documented in `.env.example`
  and the architecture/configuration guide.
- Pairing-only Telegram users can chat but cannot approve autonomy decisions.
- Trusted forwarding headers require both the enable flag and a matching proxy
  CIDR; boolean-only proxy configurations fall back to the socket peer until
  `JARVIS_TRUSTED_PROXY_CIDRS` is configured.
- Guardrails `REDACT`/`BLOCK` modes trade token-by-token output for pre-emission
  enforcement; `WARN` keeps the current streaming latency.
- Existing custom Claude model settings are preserved. Only the retired default
  is migrated.
- Existing local-only installations without cloud keys remain behaviorally
  unchanged under the default `WARN` guardrail mode apart from stronger route
  assertions; enforcing modes gain the documented pre-emission buffering.
- Email installations move from boot failure/non-delivery to the already
  documented SMTP/IMAP behavior. Only approved broker replies may send email,
  and no new network call occurs when email is unconfigured.

## Error Handling

Every security boundary fails toward less authority:

- local backend unavailable: clean local degraded response, never cloud;
- guardrail binding failure: generation fails rather than bypassing scanning;
- enforcing output scan failure: no token or tool argument reaches the consumer;
- Gemini HTTP failure: sanitized provider error, no raw URL or secret;
- autonomy ambiguity or unknown kind: `ASK` at the highest conservative tier;
- malformed reserved payload field: ignored as untrusted metadata;
- untrusted proxy peer or malformed forwarding chain: socket peer/unknown bucket;
- full rate-limit table: unseen identities share overflow, existing limits stay;
- pairing exception or missing Telegram identity: hold/drop;
- unauthorized Telegram callback: acknowledge denial, no state transition;
- outbound email construction/SMTP failure: send false, never successful delivery;
- IMAP poll failure: degraded health with a stable reason, then bounded retry.

Startup should degrade only the affected optional channel. It must not make the
web/voice assistant unavailable because Telegram or email is incomplete.

## Test Design

Use red-green TDD per workstream. Existing tests that encode unsafe behavior
must be replaced, not merely supplemented. Gemini cache/settings tests use a
temporary settings database and may not mutate the repository's shared runtime
state.

### Route and cache tests

- Frigga, Ultron, and Howard select their local backends with cloud backends
  present and guardrails enabled; a cloud recorder remains at zero calls.
- Normal generation, tool turns, synthesis, and streaming preserve the selected
  backend.
- Cloud-capable control agents still use their selected cloud routes.
- Guardrail WARN/REDACT/BLOCK behavior and admin-loaded knobs remain effective.
- Boot without a model followed by provider re-detection still binds guardrails
  on the first successful request.
- `REDACT`/`BLOCK` streaming emits no unscanned token; tool-call string values
  are redacted or blocked before the runtime receives them, and a finding left
  in regenerated non-string JSON fails closed.
- Provider re-detection is followed by subsequent request bindings; no stale
  boot backend survives.
- Concurrent and nested Gemini sessions use distinct cached-content names;
  cancellation restores the parent scope and an uncached request inherits none.
- Same-session create/extend is serialized; model, system, or auth-profile
  changes recreate the mapping; an interleaved pool rotation cannot split the
  cache/generate lease; invalid cached content invokes the correct session
  callback and retries generate/stream uncached once.
- A multi-turn cache hit omits exactly the recorded cached prefix and includes
  every post-cache turn exactly once; a changed or truncated prefix is a miss
  and sends the complete history.
- A cache created under `WARN` is not reused after restart under `REDACT` or
  `BLOCK`; scanner-version changes and legacy entries without policy metadata
  are misses and recreate the mapping.
- A cache miss/fingerprint mismatch retains full history in the generation
  prompt. Cache creation in `BLOCK` makes zero network calls; `REDACT` uploads
  only a redacted copy without mutating local history.
- Local-unavailable normal, tool, and streaming paths return the same stable
  privacy-safe message with zero cloud calls; unavailable synthesis returns the
  constituent reports without a replacement backend call.

### Cloud/model tests

- Main Gemini, streaming, context-cache, and plugin requests contain
  `x-goog-api-key` and no `?key=` query.
- Distinct sentinel API key, URL, prompt, and response-body values are absent
  from returned text, DEBUG-level captured logs, conversation memory,
  learning/run history, and exception-derived diagnostics.
- Auth rotation still advances on rotatable HTTP statuses.
- Context cache works when only `GEMINI_API_KEYS` is configured, uses the active
  profile for POST/PATCH/DELETE, rotates once per healthy profile on rotatable
  status, recreates after an active-profile change, and never places a key in
  URL or persistence.
- Gemini source has a static ratchet forbidding `?key=` URL construction.
- Fresh settings use Claude Sonnet 4.6; exactly the retired default migrates;
  repeated/concurrent initialization is idempotent, `force=True` stays safe,
  custom values remain byte-identical, and public SOUL hints no longer claim
  4.7.
- `ClaudeBackend`, the cloud plugin, provider registry, and settings default all
  resolve through `DEFAULT_CLAUDE_MODEL`; the retired runtime ID is absent from
  executable source.
- The configured Claude default has a known non-zero price entry, alongside
  the already-priced configured Gemini defaults.
- Sanitized cloud failures are recorded as failures and do not trigger the
  background learning reviewer or count toward successful bench/promotion data.

### Autonomy tests

- Payload `risk_tier` cannot lower a destructive or money action.
- Payload `kind`/`name` cannot shadow the persisted or classified kind.
- Trusted internal monitor tiers still produce the intended read-only alerts.
- Tier 3 plus a policy `ACT` result is recalculated to `ASK`; tier 0 cannot lower
  delete/money. Invalid, boolean, out-of-range tiers and empty kinds fail closed.
- `govern_enqueue` chooses the strictest caller floor, policy, taint, and money
  result.
- House canonical payloads retain their hash-verified executor `risk_tier` while
  that payload field has no authority in the policy view.
- Edited payloads cannot replace reserved identity fields or auto-approve a
  task that still requires owner approval.
- The admin autonomy endpoint preserves its auth requirement and ignores
  reserved payload fields.

### Ingress and channel tests

- Untrusted XFF rotation from one socket reaches 429. Trusted headers work only
  when the socket peer matches configured IPv4/IPv6 CIDRs, with right-to-left
  chain resolution and canonical IPv4-mapped IPv6 behavior.
- Malformed/oversized forwarding chains fall back safely. Adding 4,097 or more
  identities cannot evict or reset an already-limited identity; unseen clients
  use the bounded overflow bucket.
- Telegram token-only startup disables Telegram with an actionable reason.
- Invalid/negative/boolean/oversized Telegram IDs disable startup without
  constructing the HTTP client; valid IDs are trimmed and deduplicated.
- Static allowlist and pairing modes each admit their intended messages.
- Pairing exceptions never invoke the handler for Telegram, email, or webhook
  sender paths.
- Pairing-approved but non-owner users cannot invoke autonomy callbacks.
- Owner callback requires matching live chat and user identity; changing the
  live owner setting invalidates the old chat, and denials leak no task state.
- Telegram send, card, callback-answer, and poll errors never log a bot-token
  sentinel.
- SMTP/IMAP environment configuration constructs the real `EmailChannel`.
- An approved email reply passes through the real `ChannelManager` and a
  stubbed SMTP transport; the automatic channel-handler path cannot send.
- Missing/invalid destinations, CR/LF headers, oversized subjects, and SMTP
  rejection return false without a network call or secret/body logging.
- Invalid/oversized ports and poll intervals fall back within bounds;
  unrecognized `SMTP_TLS` remains true.
- IMAP `poll_once()` records healthy/degraded state and stable timestamps/reasons
  without leaking credentials, sender body, or raw exceptions.

### Combined gates

After each logical commit, run its focused tests plus directly adjacent suites.
Before push, run once:

- the complete backend test suite;
- route and OpenAPI parity guards;
- lifespan/install smoke tests;
- status-sync check and regeneration required by the new test count;
- advisory code-health checks on touched files;
- the relevant mobile parity/document checks.

Report exact commands, collected/passed/skipped counts, warnings, and any
environment-only validation not performed. Do not substitute test doubles for
an owner-credential live claim.

## Documentation and Backlog Truth

The implementation PR must:

- add an engineering-tail backlog row for this single remediation wave and mark
  it complete only after every workstream and combined gate is complete;
- reconcile the residual text in `HF-7`, `H12.19`, and `B5` rather than leaving
  already-complete claims that contradict the live seams;
- update the canonical environment/configuration documentation for
  `TELEGRAM_ALLOWED_USER_IDS`, `JARVIS_TRUSTED_PROXY_CIDRS`, the token-only
  secure-default change, and the SMTP/IMAP optional values introduced above;
- update `mobile/PARITY.md` to record that autonomy approval behavior remains
  surface-parity while risk metadata and Telegram owner checks are enforced on
  the shared server API;
- update test counters and generated status artifacts through the repository's
  canonical status-sync tooling;
- avoid a separate backlog-only PR.

No HUD punch-list item is needed because no endpoint or control is added. The
existing autonomy and channel surfaces remain the UI entry points; their server
semantics become stricter.

## Rollout and Rollback

The PR is opened as draft. Targeted suites run before the first push, then the
full local suite runs once on the integrated branch. GitHub CI is allowed one
normal cycle unless it reveals platform-specific evidence that requires a fix.

Rollback remains component-granular because each workstream is a separate
commit. There is no destructive schema migration: the Claude value migration
updates only an exact retired-default match, and custom values are preserved.
The secure Telegram default can be rolled forward operationally by setting the
allowlist or enabling pairing; no stored sender state is deleted.

The wave is complete only when the draft PR contains all scoped fixes, the
combined verification is green, backlog/parity/status truth is synchronized,
and the handoff reports the branch/PR state explicitly.
