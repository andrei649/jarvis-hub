# H513 independent interactive local vision

Generated 2026-09-27. Base/head:
`bd2bb70ead1b493043a335e77713fc42c47d4013` plus local sprint changes.
Goal: apply actual-dispatch policy to the independent image-description and
screen-reflex HTTP surfaces, preserving their existing strict-loopback boundary.
The preceding transport snapshot passed 19,088 backend tests with 35 skips.
Next action: implement the two owned slices below, then integrate and verify.

## Verified problem and decisions

`routers/multimodal.py` constructs native VLM clients directly for both routes;
these calls lack the scoped composer policy/transport guard. Describe uses the
legacy error-sentinel API and can report ok:true after failed inference. Screen
reflex already distinguishes no answer, but currently has no fresh configuration
or physical-route policy checks. Its pure injected-generator core is not a
configuration/authorization owner and should remain unchanged.

The legacy VlmDescribePanel still offers a remote acknowledgment and claims that
its route allows remote upload. The backend already refuses non-loopback VLMs.
Remove this misleading control and align both panels with the actual route.

These are explicit authenticated web requests. Reuse the existing interactive
local-vision policy semantics: known LM Studio policy is local, custom endpoint
policy remains unknown with a visible warning, and no remote endpoint becomes
eligible. Do not borrow primary-provider or judge grants, invent provider terms,
or authorize unattended camera/Telegram consumers through this user-request seam.
No new persistent consent mechanism or mandatory request field is needed here.

## Backend contract (writer A)

Own `agents/core/llm/vision_policy.py`, the VLM portions of
`agents/core/routers/multimodal.py`, a new
`tests/test_h513_interactive_local_vision.py`, and narrowly affected existing VLM
route/screen-reflex route fixtures. Coordinate exact additional fixture paths
before editing them. Preserve unrelated desktop/media handlers and route guards.

Add a strict-local interactive wrapper around the existing frozen identity and
physical request checks; preserve the composer API and its remote-ack behavior.
Use native scoped-auth construction with environment proxies disabled, bind the
actual selected model/URL/auth/policy before constructing the client, re-resolve
configuration at entry/physical dispatch and after awaited cleanup. A body model
override remains supported, guarded and frozen; the live resolver must preserve
that explicit effective model while still checking destination/key/provider drift.
Close owned clients on refusals too. Do not convert an inference sentinel or empty
answer into success. Preserve ordinary screen-reflex invalid-input and grounding
semantics; remembered physical refusals must escape swallowed adapter errors.

Status and successful responses add optional top-level `data_policy`,
`data_policy_note`, `warning` using the existing bounded public metadata format.
Status remains a pure configuration report, reachable:null and no client/probe.
The existing `base_url` display field must expose only a sanitized origin
(scheme/host/port), never credentials, query, fragment or private endpoint path.
The UI does not use it for routing. Invalid policy/identity is bounded unavailable;
changed configuration/selection is a bounded conflict; inference failure is a
bounded failure, never raw exception text. Screen failures keep ok:false and
generated:false. Existing non-loopback refusals stay 503 and precede dispatch.

Tests: native offline HTTPX transports for both actual route calls; local/custom
warnings; strict remote refusal before construction; explicit model selection;
key/endpoint/model-policy change before physical send and during cleanup; proxy
or selector substitution; empty/sentinel/inference error; no secret in status or
errors; owned close; existing route auth and composer regression coverage.

## HUD contract (writer B)

Own only `frontend/src/gap.tsx` VlmDescribePanel/ScreenReflexPanel sections,
`frontend/src/test/vlm-describe-panel.test.tsx` and
`frontend/src/test/screen-reflex-panel.test.tsx`.

Both panels display optional policy note/warning from status before submission
and retain returned warnings after success. Missing optional fields preserve
legacy compatibility. Align the describe panel with strict local routing: no
remote acknowledgment control, no remote POST, and clear refusal/disabled state.
Keep file limits, upload/capture behavior, screenshot cleanup and grounding UI.
Handle false-success payloads as refusal rather than rendering a fake answer.
Do not modify unrelated panels or regenerate bundles/schema as a worker.

RED then GREEN tests for local warning before/after success, missing metadata,
non-loopback zero POST/no acknowledgment, and failed inference rendering. Run
focused frontend tests and typecheck. Coordinator owns full build/typegen if
needed, mobile/manual/Hermes records and cross-surface verification.

## Scope, integration and rollback

At most two Sol High implementers, single writer per file, no subdelegation,
no live providers, paid services, publication or global defaults. Run focused
tests after each implementation step, then appropriate serial full milestones.
Reassess only reviewed shared evidence; H513 remains partial. Native mobile stays
an explicit gap. Camera/media reader/screen-locator and stored-vector migration
remain separate, as does proving backend-server internals never forward inputs.
Rollback only these localized route/policy/panel changes and their tests; preserve
prior expiry and transport work. The frozen shared response fields above permit
parallel implementation. Coordinator GO: this plan is released for execution.
