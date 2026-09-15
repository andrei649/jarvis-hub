# Per-job model and provider pins implementation plan

Goal: make authored ask-job model/provider options effective without changing grants, SDKs, shared agent configuration or ordinary chat.

Architecture: a request-local immutable selection with a shared closed-lifetime gate wraps each model phase of a job. HybridRouter selects only configured, policy-permitted backends and validates approved models. Explicit unavailable/prohibited selections fail; they never silently fall back. Backend call wrappers recheck the scope gate so inherited tasks cannot start additional calls after job completion. Model-free jobs reject pins. Existing script/URL approvals, delivery, e-stop and durable dispatch identity stay intact.

- [x] RED scope lifecycle, validation and router-policy tests; implement scope and router integration. Cover local-only agents, availability, configured provider identities, approved models, ordinary routing, concurrent pins, cancellation and late inherited tasks.
- [x] RED real job option persistence/dispatch and model-phase propagation tests; bind scope in JobRunner._ask. Compression auxiliary model calls under pins must fail explicitly into existing deterministic fallback; no unrelated background attribution.
- [x] RED HUD/CLI authored payload tests; expose model/provider controls using the existing options API. Keep workdir/enabled_toolsets/skills rejected. Validate no_agent and non-ask combinations.
- [x] Run focused backend/frontend tests, mobile unaffected, both relevant frontend type checks and scoped lint/security checks. Record exact evidence and limitations; no global counts, assessment, built bundle, publication or live calls.

Provider names describe existing configured adapters, never URLs or credentials. Configuration changes and restarts revalidate at execution. Durable job options already participate in receipt identity and persisted script generation; tests must prove the new fields do too. Missing provider/model uses existing behavior only when no corresponding pin was requested. Model pins never become authority grants. Existing local-only and approved-model rules remain mandatory.

## Implemented contract

Providers are a constraint on existing cloud routing, not a new cloud-routing policy: a cloud pin must match the provider selected by existing per-agent, availability, spend and fallback rules for that request. Configured local adapters may be explicitly selected. A model-only pin changes the model on the policy-selected backend; use both fields when provider identity must remain fixed. Every selected model still passes the approved-model check. Unavailable or mismatched pins fail instead of falling back. Pins cannot create adapters, credentials, endpoints or grants.

The primary text/stream/tool-turn entrypoints share the closed scope wrapper. Existing one-shot job processing does not invoke the full chat synthesis/background-review path. Optional compression calls explicitly refuse under pins, preserving deterministic compression fallback; optional recall embedding likewise refuses into its existing logged empty-recall fallback because a completion-model identifier is not an embedding-model identifier. Ordinary chat's recall/taint and compression behavior remain unchanged. Tool execution keeps existing governance and is not reconfigured by model pins.

CLI authoring uses existing `jobs create/edit --options` JSON, now documented for model/provider. HUD custom jobs, blueprints and edit forms use the existing options editor. Non-ask actions and no-agent scripts reject pins. `workdir`, `enabled_toolsets` and `skills` remain unsupported, with no authority expansion or whole-row equivalence claim.


## Model-window follow-up and limitations

Preflight resolves backend/model/window before prompt history is assembled, freezes that identity for the model phase, and rejects changes on subsequent selection. History compaction uses that window and omits a previous unrelated turn's usage anchor. Automatic and configured tool transcript/output budgets cannot exceed the scoped bound. Completion is capped to one quarter of the resolved window (including the prior auto setting); a prompt estimated to exceed the remainder fails before generation rather than relying on silent provider truncation.

Changing a local model or local provider requires a loaded context bound from the adapter's existing synchronous context metadata. Ollama configured/cached `num_ctx` supplies it; no extra live probe or endpoint is introduced. LM Studio currently has no such accessor, so changes away from its policy-selected default model fail explicitly. Other changed models require a recognized existing model-window family. Pins retaining the policy-selected default retain its existing window estimate, which is not a new claim that loaded capacity was measured. No default-family window is claimed to be provider-reported usage or billing evidence.

Verification: RED scope/module, router pin failures, optional compression/recall calls, Howard provider identity, and window/budget regressions recorded in `/tmp/nerva-job-pins-*-red.log`. Final focused integration set passed 462 tests. Two additional capability regressions then passed in the complete 28-case pin module; production source was unchanged between those runs. UI passed 17 tests across jobs panel and entry coverage, including authored pin payload and visible memory limitation. Both frontend type checks, whole repository Ruff and Bandit 1.9.4 baseline scan passed; final logs are `/tmp/nerva-job-pins-final-backend.log`, `-final-ui.log`, `-tsc.log`, `-e2e-tsc.log`, `-whole-ruff.log`, and `-bandit.log`.

Test additions: 28 parameter-expanded backend cases in `test_job_model_pins.py`, one CLI payload case, and one HUD case. Existing guard tests also cover ordinary unpinned job/chat recall taint, compression, approved routing, script approvals, dispatch fingerprint/restart, and tool-loop budgets. No full backend suite, generated bundle, global evidence or status updates, native build, remote writes or live model calls.

## Review repair: preserve spill reads

Root review identified that applying a scoped per-result cap to `file_read` replaced its intentional infinite threshold, re-spilling the very file used to read a prior spill. The actual loop regression reproduced a new `file_read-*.json` file under a resolved 4,096-token pin (`/tmp/nerva-job-pins-respill-red.log`).

Preserve the existing pinned never-spill threshold. Other tool-result thresholds remain clamped. A large file read is folded into the existing honest in-memory compaction envelope before the next provider call; a read that cannot be folded within the transcript budget stops the loop before a second model call. The provider wrapper independently checks the resolved context bound. Thus no recursive spill is needed, and no unchecked oversized read reaches the model.

Three added regressions cover a fitting read preserved whole, an oversized read compacted with zero spill files, and an unfittable read stopping before a second model request. Pin/spill/compaction/guardrail suites: 60 passed (`/tmp/nerva-job-pins-respill-green.log`). Whole Ruff, Bandit baseline and diff whitespace checks passed. Total additions for this branch are now 32 backend cases and one HUD case; no dependency, global metadata, or frontend runtime changes in this repair.

## Root integration verification

Independent root review repeated 91 pin/store/tool-loop tests and found no further
issues after the no-respill correction. Integrated with the reviewed spill repair:
11,342 backend tests collected, 11,318 passed, 23 skipped and one expected failure
(255 seconds); all 1,314 frontend tests passed. All three frontend TypeScript
configurations, deterministic Vite build, whole Ruff and baseline Bandit passed.
Native source and dependencies remain unchanged (tracked suite: 140 tests).
No live model/provider calls, native-device proof or whole-row equivalence claim.
