# H277 native video transient retry design

Generated 2026-10-02. Base `414978c1`; pinned Hermes
`59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`. Previous goal turn made progress:
native Gemini video passed the full backend on `c4231b64` with unchanged source.
This increment supplies a missing recovery behavior; H277 remains partial.
Local only: no push, merge, deployment, live model call or credential import.

## Evidence and chosen behavior

The [investigation](h277-retry-investigation-2026-10-02.md) separates synchronous
auxiliary retries from the asynchronous video path. Further source review confirms
that `agent/auxiliary_client.py:_async_call_llm_impl` retries the primary once.
`_should_skip_same_provider_retry` explicitly includes `vision`: ordinary timeouts
skip directly to fallback. A tagged first-token no-progress timeout is an upstream
exception, but Nerva has no equivalent typed native progress event yet.
`_call_fallback_candidate_async` has parameter/auth recovery, not this transient
primary retry. Therefore the previous draft's retry-per-lane and general timeout
retry would expand or misrepresent the reference behavior; do not implement them.

Selected implementation: a strict video retry setting plus a bounded primary retry
inside the existing native runtime. Retain provider-specific payload builders,
current consent, signed task mediation and the separate fallback classifier.
Do not introduce an SDK or refactor all auxiliary consumers in this batch.

## Contract

- `JARVIS_ROLE_VIDEO_TRANSIENT_RETRIES`: unset/blank/`0` means zero; `1` permits one
  additional primary attempt. All other values refuse intake and execution.
  A surrounding space may be normalized; invalid types, long values, controls and
  non-ASCII spellings must not silently enable recovery. Parsing reads only this
  fixed name, supports an injected mapping for tests and produces sanitized errors.
- Zero preserves exact existing single-send approval class, consent scope, notice
  and result shape. With one, bind a versioned internal retry-policy field into
  the task's HMAC material. Do not add a caller-controlled ToolRPC argument.
  Setting changes invalidate pending execution at existing authority checkpoints.
  The existing destination/model/key consent scope is unchanged; the extra send
  budget is authorized by the individual task approval, not by a new global grant.
- Only `role:video_analysis` can retry, at most once. Every fallback stays at one
  native attempt. The retry uses the same frozen identity and prepared media, a
  fresh mutable body and a fresh owned client. Close the first client and recheck
  the complete current chain, task, kernel, consent and retry policy before the
  second client/send. No additional source URL fetch.
- Eligible first-attempt failures: owned typed HTTPX network/remote-protocol
  failures classified as `connection`, or a bounded HTTP 408/5xx response classified
  as `transient_http`. Ordinary native/client/attempt timeouts do not retry; they
  retain the existing independently approved fallback behavior. No exception-name
  or arbitrary provider-text matching is introduced.
- Auth/payment/rate/model incompatibility uses existing fallback without transient
  retry. After exhausted connection retries, existing connection fallback may run.
  Generic HTTP 408/5xx exhaustion refuses; it does not authorize another provider.
  Generic HTTP 408/5xx also refuses on a fallback candidate or when retry is off.
- No retry on source/factory/hook/policy/consent/kernel failures, cancellation,
  cleanup failure, oversized response, malformed/blocked/empty success or deadline
  exhaustion. The per-attempt physical marker still permits one send, including
  auth-flow/redirect attempts; a second unauthorized send is never a retry event.
- The existing 180-second total includes source, both primary attempts, fallbacks
  and cleanup. Each model attempt retains its 65-second ceiling/60-second client
  timeout and source retains its 35-second sub-limit. No sleeps/backoff added:
  pinned asynchronous primary retry is immediate; synchronous backoff is separate.
- Retry-enabled approval notices clearly say the primary may retry once, retain
  candidate identity labels and fit 200 characters, including five long lanes.
  The zero-retry legacy formatter remains unchanged. New retry-enabled results
  expose fixed failure categories with a one-based `attempt` per route, plus
  existing chosen-route/provider/model and `chosen_attempt` on success. Single-route
  enabled calls expose that provenance too; disabled calls remain byte-compatible.
  Provider bodies, destination paths, credentials and exception text stay private.
- Actual-use accounting happens once per physical attempt. Reuse the existing
  request guards for compatible and Gemini protocols, including Gemini size checks
  before any lane and at the wire. No route, schema, dependency or HUD change is
  required; existing task notices/results present the new bounded behavior.

## Verification and rollback

Use real ToolRPC/queue/worker/kernel harnesses with offline native HTTPX transports
and real audited model-data acknowledgment. Red-first cases cover parser rejection,
same-primary recovery, policy drift, HTTP 408/5xx retry then refusal, immediate
timeout fallback, no retry on fallback candidates, unchanged default HMAC/result,
new provenance, once-only source retrieval, fresh clients/bodies and authority
revocation during cleanup. Check both Gemini and compatible wire shapes and limits.
Host guards, cancellation and total deadline tests must prove bounded physical sends.
Run the full video/role/consent/media selection after implementation and one full
backend at a coherent frozen milestone. Unchanged frontend keeps its source-matched
1,838-test proof. Pin records only after reviewing changed evidence.
Because this increment adds an approved physical-send budget, verify targeted
mutations of its retry limit, primary-only restriction, approval binding and
failure categories in a disposable exact-commit archive. Baseline, unique anchors,
syntax validity, test outcomes and restored hashes must be recorded separately;
the earlier campaigns do not prove these new branches. This is bounded mutation
evidence for the retry increment, not full mutation coverage of all H277 paths.

Rollback this increment to restore the existing one-send runtime; changing the retry
setting or removing support makes retry-enabled pending task classes stale. Keep
all default-zero legacy grants/tasks and unrelated work intact.

## Decisions and remaining scope

Standing owner autonomy supplies implementation approval; use one Sol High writer
and one bounded read-only review, with parent integration. The cost is possible
design rework, mitigated by the written contract and regression evidence.
Default zero preserves existing signed authority; enabling the new capability is
explicit configuration rather than silently adding model sends to old approvals.

This does not close empty-output retry, typed first-token no-progress handling,
SDK parameter/credential recovery, shared auxiliary routing/discovery, broader
adapters, larger video upload lifecycle or live/provider acceptance. Those remain
in the full project goal, together with native mobile and inbound media work.
