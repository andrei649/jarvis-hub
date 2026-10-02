# H277 governed image empty-result recovery

Goal: advance the full pinned-Hermes parity objective with actual governed image
consumers, not an unwired helper. Base/head before implementation
`9313fe0c`; branch `codex/h277-image-empty-retry-20261002`. Generated 2026-10-02.
Reference: Hermes `59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`,
`tools/vision_tools.py:_call_vision_llm` retries the image auxiliary call once after
empty extraction. This increment implements bounded valid-empty recovery; broader
output normalization, adapters, discovery and SDK behavior remain part of the goal.

## Contract and approach

Use one strict owner setting `JARVIS_ROLE_VISION_EMPTY_RETRIES`: absent/ASCII-space
blank/0 means disabled, 1 means one additional send. Match the fixed video parser's
length/type/control/Unicode rejection. No request body accepts a retry budget.
Disabled preserves legacy identity bindings and public/result shapes. Enabled
policy enters the frozen VisionIdentity binding as a versioned marker, invalidating
old composer destination revisions and unattended role grants when changed. The
same captured policy drives public disclosure and dispatch; invalid configuration
refuses rather than enabling a fallback.

Add enabled-only `empty_retries: 1` and `retry_notice` to public vision metadata.
The fixed notice states: "May retry once with the same images and model after an
empty response (at most two model calls)." The composer displays it before the
existing remote acknowledgment; local describe/screen status/results also display
it. Unattended media/camera target notes disclose the budget for consent management.
The note is bounded to 500 characters, does not replace privacy warnings, and
contains no URL, credential or source data. No new UI consent checkbox is needed:
the existing remote acknowledgment is bound to the updated destination revision.
The terminal composer (`nerva chat --image`) also validates the paired enabled
metadata and prints the notice on stderr before checking remote acknowledgment or
sending. Both clients refuse incomplete fields, a count other than integer 1, or
blank/overlong/control-bearing notices. Legacy metadata omits both fields.

Establish recovery only inside the existing native vision policy scope, pinned to
the exact backend object/model and current authority check. Its active lifetime
must end even in inherited/cancelled child contexts. Every real governed checked
consumer is covered: composer, local describe, screen reflex through its legacy
wrapper, unattended media reader and camera descriptions. Unguarded screen-locator,
direct backend, ordinary text-only and injected fake adapters gain no retry.
Do not blanket-enable retry in the legacy wrapper or infer authority from a flag.

Build/encode messages once. For enabled, image-bearing calls use one 180-second
generation deadline across at most two physical sends; existing tighter caller
timeouts and cleanup checks remain authoritative. Each attempt has a fresh request
and body from the same prepared content, selected model, token cap and temperature,
using the existing owned native client. Close each response before the next send;
the existing caller still owns final client cleanup. Native request validation must
retain all existing destination, model, auth, transport, policy and selection checks,
add exact prepared-body validation and a per-attempt one-send latch, and never
replace the existing physical guard with a weaker nested scope. Configuration,
consent or authority changes during response/client cleanup suppress restart/output.
No new provider/credential, source fetch, backoff, parameter or transport retries.

Enabled responses are streamed with a 512,000-byte cap. A retry is permitted only
for successful 2xx JSON with exactly one explicit stop choice and blank/null content,
without error envelopes, refusal/tool/function/audio or meaningful reasoning output.
Extract the already-tested video empty predicate to a small shared pure module;
keep its exact behavior and existing video tests. Missing/malformed/truncated/blocked
responses, exceptions, cancellation, oversized output and thought-only content that
merely becomes blank after stripping are not retry signals. Two valid empty replies
fail through each consumer's existing sanitized failure path. Preserve nonempty
output normalization and public success/error shapes except the enabled metadata.

Alternatives rejected: an unconditional backend string-empty retry would widen
unguarded callers and confuse malformed output with success; a local-only helper
would leave the real remote composer requirement unaddressed. The scoped approach
reuses existing authority and consent bindings across all five governed consumers.

## Ownership, verification and delivery

One Sol High backend writer owns `agents/core/llm/vlm.py`, `vision_policy.py`, new
`vision_retry.py` and shared `native_response.py`, the pure-predicate extraction in
`agents/core/video_analysis.py`, and new `tests/test_h277_image_empty_retry.py`.
Avoid caller edits unless an actual seam requires them; flag exact paths first.
Second Sol High writer owns `frontend/src/composer-images.tsx`, relevant policy
message arrays in `frontend/src/gap.tsx`, and related component tests only.
Coordinator owns configuration/docs, generated assets/status/evidence and integration.
Coordinator also owns the narrow CLI disclosure in `agents/cli/nerva.py` and new
`tests/test_h277_image_retry_cli.py`, preserving stdout/JSON answer formats.

TDD through real native HTTPX consumers, including successful recovery for all five
surfaces, remote composer acknowledgment binding, stale settings/grants, independent
concurrent scopes, child-context lifetime, source encoding once, exact body and
single-send enforcement, malformed/safety/reasoning/error classification, total
deadline, cancellation and cleanup revocation. Preserve default-off identity and
ordinary/direct/text-only behavior. Frontend tests prove pre-send disclosure and
reset acknowledgment on refreshed binding, with malformed metadata refused.
Run focused backend/frontend, type/build/generated-asset checks, bounded independent
source review, relevant mutation probes and one full frozen backend/frontend
milestone. Refresh only previously-current evidence rows after whole-row review;
do not promote H277 or inherited stale rows on this partial increment.

Standing owner local autonomy authorizes this bounded implementation without new
approval ceremony. No push, merge, deployment or live provider calls. Rollback the
coherent feature diff; changed composer revisions/grants must be reacquired, never
silently reused. Preserve the previous branches and all verified artifacts.
