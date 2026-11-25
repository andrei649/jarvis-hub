# H277 video empty-result recovery

Goal: implement the missing pinned-Hermes video consumer retry, preserving the
full parity goal. Base/head before implementation:
afcc652dcc0f5e0caa6ea8b826fb748848abac41. Branch:
codex/h277-video-empty-retry-20261002. Generated2026-10-02.
Reference59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e:
tools/vision_tools.py:_call_vision_llm (721-731), video caller (1040), and
agent/auxiliary_client.py:_async_call_llm_impl (8170-8222).

## Selected behavior

Hermes calls the entire async auxiliary helper once more if the first successful
analysis has no extracted text. This is separate from transient primary retries.
Nerva will restart its already-approved frozen provider chain from the primary,
at most once, after a structurally valid empty successful answer. Merely retrying
the last fallback would not match that consumer contract. Generic exception retry
would confuse malformed or blocked results with a successful empty answer.

JARVIS_ROLE_VIDEO_EMPTY_RETRIES accepts only unset/blank/0 or1, using the existing
strict fixed-budget parsing rules; no ToolRPC argument can set it. Default0 keeps
legacy signed class, notices and result shapes exactly. At1, a versioned internal
consumer-retry marker enters the task's HMAC material and the bounded approval
notice explicitly describes the extra full-chain call. Enabling/disabling or
invalidating this setting after approval makes the pending task stale. Class material and approval notice must use the same captured
retry-policy values, with fresh resolution at each later authority checkpoint. Existing
independent route consents and credential/destination bindings remain unchanged.

Reuse the one prepared video source and question across both calls, retaining the
existing180-second total deadline, per-attempt budget, response limits and cleanup.
Each call uses the same ordered frozen identities; each physical attempt builds a
fresh body and owned client. The first client must close and current authority must
pass before starting another. All existing preflight/physical/cleanup checks apply.
The existing primary transient-retry budget applies independently inside each
consumer call, and each fallback still gets one attempt per call. Thus at most
2*(number_of_routes + transient_primary_budget) native sends, never a third call.
A source URL is downloaded once. No backoff, new credentials or new destinations.

An empty response in a fallback restarts the full chain, rather than progressing
to another fallback in that call. The second valid empty response ends refused.
Ordinary fallback failures keep existing behavior inside each call; exhausting a
chain without an empty successful response does not authorize another call.
Source/factory/guard/consent/kernel failures, cancellation, malformed or oversized
responses and deadlines do not become empty-retry signals. Revocation during
client cleanup wins over the response and prevents restart/publication.

## Response classification and provenance

Compatible protocol: retain existing nonempty-answer behavior. Classify empty only
from a successful2xx object with exactly one choice, explicit finish_reason=stop,
a message object with present string/null content and no refusal/tool/function
call or meaningful reasoning-only output. Whitespace counts as empty. Missing or
unknown finish reasons, length/content_filter/tool_calls, missing content, invalid
shapes, error envelopes and nontext content do not qualify. Do not inspect error
strings to infer emptiness. This establishes a known empty boundary rather than
retrying an arbitrary malformed provider response.

Gemini: keep exactly-one candidate, STOP finish and prompt/candidate safety checks.
A separate typed empty subtype of VideoNativeRefused can identify a structurally
valid response without visible text after validating all parts; blocked, truncated,
tool/inline-data, missing, malformed or error-bearing empty responses cannot restart.
Existing nonempty acceptance is unchanged, including ignoring malformed thought
parts when another part provides visible text. Tightening that inherited behavior
is separate output-normalization work, not a claim of this increment.
Thought parts do not become published analysis. Pure codec tests must distinguish
empty from refusal; caller-level tests must prove the actual second physical send.

With empty retry enabled, all recorded model failures include fixed category,
route target, consumer_call and per-route attempt; a valid empty uses category
empty_output. Success includes chosen_call as well as chosen route/provider/model
and chosen_attempt. Never expose provider body, credential, source URL or exception
text. Enabled first-call success also has provenance. Empty retry disabled retains
all existing transient-only/multi-route and plain result shapes. The notice stays
within200 characters even for five long routes, and describes both budgets when
both are enabled; do not silently truncate away the extra authority.

## Ownership, verification, rollback

One Sol High writer owns agents/core/video_analysis.py, agents/core/llm/video_retry.py,
agents/core/llm/video_native.py and new tests/test_h277_video_empty_retry.py.
Coordinator owns configuration docs, evidence and integration. No unrelated rewrites
or dependency changes. Standing owner local autonomy authorizes this design; no
new owner gate is inferred. Local only, no push/merge/deploy or live/provider calls.

Red-first real ToolRPC-to-worker native-HTTPX cases cover both protocols, ordinary
valid-empty recovery, twice-empty refusal, fallback-empty restarting primary,
primary transient retry in both calls, maximum sends, once-only source fetch,
fresh clients/bodies, settings drift, consent/kernel/cleanup revocation, cancelled
and deadline cases, physical reuse denial, malformed/blocked/truncated exclusion,
legacy class/notice/result identity and longest approval notice. Run existing
video/role/consent suites, then independent source review, bounded exact-snapshot
mutations of the call cap, signed marker, chain restart and empty classification,
and one full frozen backend at the milestone. Keep prior failed/passing receipts.

Rollback the local feature diff: empty-enabled queued approvals must become stale;
default-zero legacy behavior remains. This delivers bounded recovery of structurally valid empty video results;
image/other-adapter empty recovery, broader output normalization, SDK credentials/parameters, provider discovery, route cache,
progress recovery, larger videos and live/native-client acceptance remain open.
