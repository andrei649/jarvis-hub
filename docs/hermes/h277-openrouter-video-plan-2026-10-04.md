# Coordinator integration: H277 OpenRouter native video

Generated 2026-10-04. Goal remains all697 pinned Hermes capabilities. Current
integration base/head:`4f265c6c`; prototype base:`6b9422ed`. Single writer for
real checkout:coordinator. The prototype below preserves its pre-code plan.

Integration steps: re-read the six-path patch and native-wire guard code; apply
the new test module alone and observe meaningful RED in this checkout; apply
the four source changes and necessary obsolete assertion update; run the597-case
affected module set, with current approvals/audit and role consumers. Re-read
only affected current Hermes reviews before any restamp, preserve already-stale
claims, update generated counts and scoped delivery docs. Rebuild/check Graft,
run lint/security/record gates, then freeze a new full backend milestone serially.
No live/provider acceptance, credentials, services, push, merge or deployment.
Rollback: reverse the six-path source/test patch and regenerate counts/records.
Next action: apply the new tests before production changes.

Independent Luna Medium read-only review found no reproducible substantive flaw
in the six-path proposal. Root verification follows; external597-pass results do
not establish integrated acceptance. H277 stays partial; DeepInfra/Nous and
remaining native/provider/auxiliary requirements are still open.

# H277 OpenRouter Native Video Implementation Plan

> **For agentic workers:** Use test-driven development and native execution in this disposable snapshot. The parent task explicitly forbids delegation and real-checkout edits.

**Goal:** Add one owner-approved OpenRouter native-video route to the existing `video_analyze` ToolRPC, preserving the full-video `video_url` data URL and every existing guard.

**Architecture:** Extend the existing model-role resolver, fallback parser, and video identity to recognize OpenRouter. Resolve an inherited vision route only through its guarded effective configuration, and copy its key only for the same provider and exact physical URL. Freeze the existing live OpenRouter provider-routing block in the identity and emit it on the physical chat/completions body; the existing equality, ToolRPC class, and request-scope checks then revoke changed configuration before egress.

**Tech Stack:** Python 3.12, httpx, pytest, Ruff.

**Spec:** Parent task handoff dated 2026-10-04; source baseline `6b9422ed56bd45c0823e818db123266b854496ec`, `/tmp/nerva-h487-h277-batch-full-20261004-frozen.json`.

## Global Constraints

- Change only `agents/core/llm/{model_roles.py,video_policy.py,video_routes.py}`, `agents/core/video_analysis.py`, new `tests/test_h277_openrouter_video.py`, and narrowly required existing test assertions.
- Do not change the real repository, index, credentials, docs, or providers; do not install, call a provider, publish, or delegate.
- Preserve local-only, safe/strict mode, cloud fallback, cost and per-role acknowledgment gates; require signed ToolRPC approval and current source bytes.
- OpenRouter support is model dependent. Keep sanitized provider rejection without automatic fallback for unsupported media.
- Existing providers' identity binding bytes and native body shape remain stable.

## Review Focus

- An explicitly selected custom OpenRouter base cannot inherit an ambient OpenRouter or vision key; the dedicated video key is required.
- An inherited vision route can reuse only the exact guarded provider/physical URL and key, including a model override that leaves that URL unchanged.
- A fallback OpenRouter route uses only its fixed slot key, with no role-key borrowing.
- Changing OpenRouter privacy/provider preference, URL, model, key, or remote grant after approval revokes the pending task before dispatch.
- Unsupported-media response is reported as a provider refusal without silent sampling, retry, or fallback.

---

### Task 1: Route selection and credentials

**Files:** `model_roles.py`, `video_routes.py`, `video_policy.py`, new `tests/test_h277_openrouter_video.py`; narrowly revise outdated refusal assertions if present.

**Interfaces:** `resolve_video_route(env) -> ResolvedVideoRoute`; `resolve_video_fallbacks(env) -> tuple[VideoFallbackRoute,...]`; `describe_video_route_set() -> tuple[VideoIdentity,...]`.

- [ ] Add RED tests for explicit primary, inherited vision route and model override, fallback slot selection, and invalid or mismatched credentials.
- [ ] Run new tests with `JARVIS_TESTING=1 /tmp/nerva-pr-python-20261001/bin/python -m pytest --timeout=90 ...` and record expected failures.
- [ ] Add OpenRouter to the bounded native providers. Reuse guarded vision config for inherited OpenRouter; exact URL/provider equality gates key reuse. Explicit route uses its own key unless it exactly matches the effective vision route. Fallback uses only its slot key.
- [ ] Run focused resolver tests and old model-role/fallback tests green.

### Task 2: Frozen routing policy and physical body

**Files:** `video_policy.py`, `video_analysis.py`, new `tests/test_h277_openrouter_video.py`.

**Interfaces:** `VideoIdentity.provider_block` is an immutable serialized OpenRouter block only; `native_video_request_scope` continues exact JSON/URL/Authorization validation.

- [ ] Add RED signed ToolRPC tests with `httpx.MockTransport` for the full MIME data URL, exact emitted OpenRouter provider block, scoped Authorization, and absence of dispatch before owner approval.
- [ ] Add RED revocation tests for privacy preferences and route/key/remote-grant changes, local-only actor, and unsupported-media response.
- [ ] Bind canonical block serialization to the identity; emit `provider` only on OpenRouter chat/completions bodies, preserving `data_collection`, `only`, `order`, and `require_parameters`.
- [ ] Run new signed tests and affected video policy/provider-chain suites green.

### Task 3: Verification and handoff

- [ ] Run affected focused modules with XML and Ruff. Do not run the concurrent full suite.
- [ ] Compare modified paths to the baseline manifest, generate exact unified `implementation.patch`, and record RED/GREEN logs, supplemental tracked inputs, limitations, and rollback (discard snapshot or reverse patch).

**Generation time:** 2026-10-04. **Next action:** write the first RED test before production code.


## Coordinator integration evidence

The root checkout reproduced21 meaningful missing-feature failures in22 new
cases before the source patch. After integration597 affected cases passed; the
136-module common regression passed3,012 cases, zero failures/errors/skips.
Ruff and baseline Bandit passed; Graft's explicit rebuild/check found no graph
drift (optional deep context remains absent). Backend count was collected as
22,418. Documentation records existing UI/mobile gaps and preserves already-stale
H275/H277/H513 reviews rather than hash-refreshing them. New provider mutation
checks and the frozen full backend milestone remain subsequent gates. See
[evidence](evidence/h277-openrouter-video-progress-2026-10-04.json).


The separate five-fault mutation run detected omitted physical privacy fields,
omitted approval preference binding, cross-URL credential borrowing, wrong
fallback-slot credentials and missing-key acceptance. Outcomes are recorded
separately:two AssertionErrors,two expected-refusal failures and one test-body
KeyError; no setup/import/timeouts. Baseline and final22 cases passed; all2,066
snapshot inputs were restored, and root rehashed current inputs independently.
The new frozen full backend milestone is the remaining local delivery gate.


## Terminal full-backend milestone

The frozen 22,418-case backend run completed with exit0:22,383 passed,34
ordinary skips and one existing expected failure; zero failures or errors. All
3,008 frozen inputs matched before documentation was updated. See the separate
[full receipt](evidence/h277-openrouter-video-full-2026-10-04.json). This covers
the integrated video increment and late-annotation regression; H277 stays partial.
H441,H586,H670 now require fresh evidence review, so the generated headline is
178/697 (25.5%); no loss of functionality is inferred from stale hashes.

H275 was subsequently re-read and its existing equivalent safe-mode verdict
restored from current semantic evidence, bringing the final report to179/697
(25.7%). This restores prior credit; it is not a new H277 completion.
