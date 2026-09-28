# H513 implementation plan

Implement the remaining frozen H513 gap: visible data-handling warnings and audited,
durable consent for unattended routed model work. Existing tool profiles/kernel
surface restrictions and pinned dependencies remain the capability/install controls.
H378 already declares `data_policy` and audits one-shot selection consent; that consent
does not grant unattended runtime permission.

## Contract

- Reuse `local`, `no-training`, `trains-on-inputs`, `unknown`. Resolve actual backend
  profiles, including clones, compatible substitutions and job scopes. A local profile
  pointed off-loopback is unknown. Cloud declarations are metadata, not evidence of
  the configured account's terms; unknown remains the conservative default.
- Preserve backend identity and `(backend, model, route)`. Selection/metadata probes
  produce no notices or usage counts. Immediately before routed generation, resolve
  fresh settings and enforce the current turn's existing tool-profile surface.
- Unknown/training routes warn through `turn_notices` and logs on actual use, including
  after acknowledgment. Internal/system work (including owner-started builder/workflow)
  refuses until acknowledged; no new cloud fallback is introduced.
- Store bounded provider-to-configuration fingerprints in route-only
  `security.data_training_ack`. Fingerprints bind endpoint, configured credential set
  and effective policy. Changes invalidate permission. Corrupt/unreadable state never
  grants permission. Generic settings/import/reset/undo cannot grant this permission.
- Admin POST `/api/security/data-handling/ack` takes strict `{provider, acknowledged,
  scope}`. `scope` is a 64-hex domain-separated HMAC of configuration using the
  existing protected persistent SecretStore key, never an offline credential verifier;
  mismatch is 409, unknown/unconfigured provider is 422, audit/storage failure 503.
  Audit must succeed before granting; revoke is also audited. Response is
  `{ok, provider, acknowledged, scope, warning}`.
- GET security posture adds `data_handling: {providers, settings_readable, coverage}`.
  Rows contain `{provider, policy, note, warning, acknowledged, last_used, scope,
  can_acknowledge, acknowledgment_unavailable}`. Unknown IDs, ambiguous providers,
  unreadable storage and unavailable scopes disable the acknowledgment action.
  No endpoint credentials or API keys appear. Coverage explicitly excludes direct
  backend paths not dispatched through routed agent work.

## Steps and ownership

1. Add failing focused tests for pure resolution, interactive versus internal use,
   no dispatch on refusal, scope invalidation, corrupt state, audited ack/revoke,
   route-only settings protection and prepared-route dispatch revocation.
2. Add `agents/core/llm/data_handling.py`: resolution, strict persistence validation,
   consent transactions, bounded observed-use metadata and notices.
3. Add HybridRouter resolver/dispatch/posture seams. Integrate at Agent generation
   and orchestrator routed dispatch without backend wrapping or tuple changes.
4. Add route-only setting and strict admin security route/posture projection. Reuse
   H378 audit event semantics without weakening one-shot selection guards.
5. Run the focused tests with normal timeout/socket options; verify nearby router,
   provider, H378, settings and route-compaction compatibility. No full suite.

The parent-authorized optional `before_model_call` hook in `agent_runtime.py` checks
each tool-loop request after tool awaits. Default `None` preserves existing callers.
The similarly optional `before_request` hook in `llm/gemini_cache.py` checks after the
session lock before every POST/PATCH and retry. Cleanup DELETE remains independent.

Parent owns frontend, generated API artifacts and FLAGS integration. No vendor term
research, paid requests, production provider calls, source-profile claims, commits,
pushes or subdelegation are part of this increment.

## Review focus

Credential/endpoint changes cannot retain consent; clones use actual declarations;
internal owner principals cannot masquerade as interactive; metadata probes do not
warn/count; revocation before dispatch works for a previously prepared route; audit
failure cannot grant; malformed imported storage fails closed; acknowledged routes
continue displaying warnings. Every routed tool-loop request is checked; independent
direct backend calls remain explicitly outside the coverage statement.

## Validation

RED observed for the missing policy module, missing admin route/dispatch gate,
revocation between tool rounds, missing cache hook, background-cache revocation,
unregistered provider/ambiguous account/endpoint scope cases, and the stream's
misleading backend-unavailable reply. GREEN: 35 H513 tests and 403 consolidated
focused backend tests, 0 failures/errors/skips, normal project timeout/socket flags
(`--junitxml=/tmp/h513-focused.xml`, 8.253s). Ruff and `git diff --check` pass.

The compatibility set covers H378 selection guards, HybridRouter, provider profiles,
settings transfer/reset, conversation/route compaction, tool profiles/runtime, and
Gemini cache/orchestrator caching. The synthetic runtime harness now declares its
loopback local provenance explicitly. No full suite or external provider call was
run; an existing router negative-network test remained socket-blocked by pytest.

Audit precedes the grant inside an SQLite write transaction. Configuration is
rechecked after audit; rollback/commit failure cannot grant permission. Audit is a
separate store, so an audited attempt may exist without a completed settings grant.
Unknown IDs and ambiguous provider accounts cannot be acknowledged. Local routes
continue operating if the protected scope key is unavailable; risky unattended
routes cannot acquire permission without a valid keyed scope and readable store.

Independent direct clients (for example separate title/summarizer or role clients)
are not universally mediated by this increment. Public posture states this limit.
The owner must still establish appropriate account/plan terms; existing profile
declarations are reused and no new vendor guarantees were added.

## Review correction: unattended inbound and physical retries

Two gaps require explicit regression fixes. An inbound origin without any principal
(webhook/workflow work) must not acquire interactive permission merely because
`classify_turn` labels it inbound. Bound web/voice/channel principals preserve their
existing interactive behavior; internal surfaces still require consent.

One logical generation can send several physical HTTP requests after a 401/429 or a
cache rejection. The routed generation/cache scope will carry a context-local request
guard through the shared `llm_async_client` request hook. Every physical send will
recheck fresh permission after awaits, including streaming/retries. Guard state is
per async context, never attached as mutable global state to a shared backend. A
recorded guard refusal must propagate from the outer scope even if a provider adapter
converts its exception to a degraded reply. Cleanup DELETE remains independent.

RED/GREEN tests: unbound inbound refusal versus bound interactive warning; revoke
during the first Gemini HTTP await followed by credential retry; revoked cache
fallback; concurrent scopes over a shared client; exceptional guard fail-closed.
Independent direct calls without a routed request scope remain explicitly excluded.

Correction validation: 42 focused H513 cases GREEN; consolidated 14-file subset
434 passed, 0 failures/errors/skips (normal timeout/socket options), JUnit
`/tmp/h513-reviewed-focused.xml`. An additional single-case rerun after import/style
cleanup passed; scoped Ruff and diff checks pass. RED reproduced unbound-inbound
bypass, Gemini retry/fallback leakage, absent physical scope and an independent tool
client incorrectly inheriting the initial overly broad generation scope.

The final scope encloses only a backend generation await (legacy text/stream,
synthesis, or one tool-loop model round), and resets before ToolRPC/tool execution.
Gemini cache writes have their separate explicit scope. Tests cover credential retry
inside real Gemini tool generation, cache-rejection text and stream fallback, shared
client concurrent turns, remembered adapter-swallowed denials and inherited delayed
requests after scope close. No mutable policy hook is installed on a shared backend.
Final explicit awaitable-guard regression added and passed: first asynchronous check
permits a physical request, consent changes during that request's await, and the
second asynchronous check is awaited and blocks retry. Final H513 file: 43 passing
cases (`/tmp/h513-final-focused.xml`); consolidated compatibility result above remains
434 passing plus this additional focused case. Production sources are frozen.

## Completed local integration milestone

The final complete backend suite passed 18,765 tests with 35 existing skips
(18,800 collected), with zero failures/errors. The full frontend passed 1,802
tests; legacy HUD passed 233 with 69.75% line coverage against the 60% gate.
TypeScript checking, production build, API/type/structural guards, Bandit and
the recorded source secret scan passed. Generated count verification matches the
actual backend/frontend reports. Initial failures and the interrupted first run
are retained, not hidden, in
[evidence/h487-h513-local-integration-2026-09-27.json](evidence/h487-h513-local-integration-2026-09-27.json).

This milestone is offline and local only. Both H487 and H513 remain partial for
the producer/consumer coverage gaps recorded in their assessments.
