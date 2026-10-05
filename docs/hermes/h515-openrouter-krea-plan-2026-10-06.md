# H515 OpenRouter and Krea implementation plan

**Goal:** Extend the existing approved image workflow with the pinned Hermes OpenRouter and Krea adapters, without replaying a paid submission.

**Architecture:** Reuse `CloudImageRuntime`, the mediated worker, local generated artifacts and existing HUD. Provider modules normalize inputs and parse bounded responses; the runtime owns credentials, approval checks, transport, durable records and publication. Krea polling uses only GET after one POST.

**Spec:** The immutable H515 inventory, pinned Hermes `59b2aeef`, and [current OpenRouter Images API](https://openrouter.ai/docs/guides/overview/multimodal/image-generation).

## Constraints

- Work only in this existing local checkout; preserve dirty changes and an empty Git index. No live calls, provider activation, dependencies or publication.
- Two implementation agents maximum, separate files. Root owns shared Python integration and verification.
- Admit fixed API origins only. Result URLs need the live PermissionGate and public DNS; download requests carry no provider credential. No fixture-derived CDN allowlist.
- OpenRouter makes one POST to the selected model, without a second model after ambiguous failure. Dedicated endpoint is `/api/v1/images`; chat endpoint is `/api/v1/chat/completions`.
- Krea stores the returned job ID before polling. No automatic Enhance POST, generic image editing, or paid replay. Polling recovery after process loss is a separately documented remaining gap until an authorized continuation is implemented.
- H515 remains partial; adapter existence and simulated HTTP tests do not establish live provider acceptance.

## Steps and verification

- [x] Adapt donor catalogs, payloads, response contracts and focused tests in new `media_backends/openrouter_image.py` and `media_backends/krea_image.py`.
- [x] Add signed runtime identities, default-off manifests, independent credentials and provider discovery. Bind generated artifact bytes for OpenRouter references. Bind canonical serialized Krea style references to stay inside queue nesting limits.
- [x] Add bounded Krea GET polling in `media_backends/krea_jobs.py`; write the job record before the first poll. Test retryable GET failures, terminal state, deadline, job mismatch and approval withdrawal.
- [x] Extend registered `image_generate` and the existing generation route; reject provider-only options on local calls rather than discard them.
- [x] Extend `frontend/src/api/images.ts`, `panels/images.tsx` and only the image approval-card fragment of `gap.tsx`. Expose explicit provider/model selection, OpenRouter artifact references and Krea style URLs. Never switch providers after catalog loss.
- [x] Prove route and registered-tool intake through the composed worker to a local artifact, with injected HTTP. Cover disabled/rotated providers, altered references, one POST after timeout, forbidden/private/redirected downloads and durable Krea job creation.
- [x] Run the affected test union, frontend tests/typecheck/build, narrow Ruff/Bandit/strict secret scan and source graph freshness. Preserve failed and successful receipts, source hashes and reviewed assessment preimages. Update only inspected H515 evidence and records.

## Review focus

Nested Krea reference objects must retain exact owner-visible meaning after serialization. Poll callbacks must recheck live approval and never retry a POST. Failed polling retains a job ID without asserting local success. Credential-free result downloads must still pass the live plugin allowlist. Generated artifact dimensions are measured from validated pixels, not inferred from nominal aspect selectors.
