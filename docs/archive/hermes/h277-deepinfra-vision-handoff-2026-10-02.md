# H277 DeepInfra vision: verified local checkpoint

Generated 2026-10-02. Goal: full local Nerva parity with pinned Hermes
`59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`; this increment does not complete H277.
Base: `0e617d63b51d3d8ddb6dd996b5cf5502d9f8d365`.
Runtime: `d78d47f166feb569df9333cf1fcfb511c3a9da74`.
Frozen full-suite head: `b9548379c679ff4b5b1ca5d9ab14da6bf6f11e56`.
Branch: `codex/h277-provider-discovery-20261002`. Local only: no push, merge,
deployment, credential migration or live/paid provider calls. This handoff and
its receipt are later documentation-only changes.

## Delivered behavior

Explicit DeepInfra vision now supports a pinned role model or catalog selection
before the user reviews the image destination. Catalog order, served metadata,
chat surface tags and the legacy ID filter match the pinned Hermes implementation.
Keys alone never enable this provider. A custom origin requires a dedicated role
key; ambient DeepInfra credentials are scoped to its canonical HTTPS origin.

Composer status can make an authenticated metadata GET, without prompts or images;
reachable remains null because no inference probe is performed. Pure role readers
and image POST never discover a replacement. The responsive HUD's existing Refresh
vision destination button forces a catalog refresh and clears confirmation. A failed
refresh revokes the old selection. The 32-entry cache isolates credentials and bases;
old concurrent responses cannot overwrite a refresh or repopulate after clear.
Pure reads while discovery is pending cannot cancel it. Metadata requests have a
five-second total deadline, a2 MiB cap, direct transport and no redirects.

Actual image inference retains independent remote and selection confirmations,
current model/credential/destination binding and final physical-request checks.
DeepInfra uses compatible image payloads, without OpenRouter-specific provider
fields. Both retry budgets reject duplicate JSON keys, and even retry0 has bounded
512,000-byte streaming responses and a180-second total deadline. Optional empty
recovery retains the same model/body and never fetches another catalog selection.
Local-only consumers remain local; inherited signed video explicitly refuses this
provider. Its registry entry advertises vision/catalog/cloud, not main-chat support.

## Verification

- Full backend: **20,903 passed,34 skipped,1 expected failure,64 warnings**;
  20,938 collected. All4,351 tracked regular files and HEAD stayed unchanged;
  checkout was clean before and after the frozen run.
- Final focused backend integration:455 passed, including61 new DeepInfra cases.
  Actual-consumer red-first:16 failures before wiring; review red-first:4 failures
  for duplicate model fields, unbounded default response and missing total deadline.
  Catalog race and pending pure-read regressions were also observed failing first.
- Frontend:1,859 passed. TypeScript, E2E TypeScript and production build passed;
  OpenAPI types and committed HUD assets were regenerated. Refresh regression
  failed before the UI change, then passed.
- Real Chrome:6 cases passed on desktop and emulated Pixel7 using an isolated
  loopback fixture. No native phone or live-provider acceptance is claimed.
- Documentation/status:92 passed after regenerating the Hermes report timestamp.
  Full Ruff and diff checks passed. Exact staged-index secret scan covered48
  cumulative changed paths with zero findings before the frozen full run.
- Two Sol High implementers worked in disjoint provider/catalog and role/profile
  paths. Root integrated runtime/UI. Independent bounded review found the response
  cap and duplicate-key issues; both were fixed, regression-tested and re-reviewed.
  Graft source graph was rebuilt and checked fresh; semantic context was not built.

Six previously current Hermes rows were re-reviewed. Four moved citations were
updated only when anchored text matched exactly. Existing inherited/stale rows
were left unchanged. The documented ledger remains **172 equivalent,254 partial,
64 missing,207 requiring review,zero excluded**. H277 remains partial; no newly
completed capability is claimed from this dependency.

The [verification receipt](evidence/h277-deepinfra-vision-verification-2026-10-02.json)
records the frozen source fingerprint and hashes of the local test artifacts.
This is regression evidence, not a new full mutation campaign or live-provider test.

## Next action

Implement Nous as a real provider prerequisite, including Nerva-owned profile
authentication/JWT refresh, tier-aware recommended vision models and native Messages
handling for Anthropic models. Do not copy rotating Hermes credentials or substitute
a bare compatible client for the full Nous contract. Pinned Hermes uses the public
`/api/nous/recommended-models` endpoint separately from inference authentication;
welcome-host routing selects its guest model, while ordinary Portal selection is
tier-aware with the pinned fallback.

Then integrate actual per-request main-provider context and the upstream main →
OpenRouter → Nous → DeepInfra selection order. Nerva's main backend is selected by
`HybridRouter.select_backend(agent_id, prompt)`, not a global backend attribute;
the current image composer has no agent context. Preserve explicit overrides and
avoid silently choosing a text-only default: Hermes permits unknown vision support
to attempt but skips known-false capability. SDK breadth, signed video adapters,
native mobile, live acceptance and all remaining697-row scope stay open.

Rollback: revert the DeepInfra runtime commit and its generated records/assets.
No deployment settings, saved credentials or database migrations changed.

## Changed paths

- `.env.example`
- `BACKLOG.md`
- `GO_LIVE_PLAN.md`
- `HERMES_STATUS.md`
- `NERVA.md`
- `README.md`
- `STATUS.md`
- `agents/core/llm/model_roles.py`
- `agents/core/llm/providers/__init__.py`
- `agents/core/llm/vision_deepinfra.py`
- `agents/core/llm/vision_policy.py`
- `agents/core/llm/vlm.py`
- `agents/core/routers/composer_vision.py`
- `agents/web/v2/assets/gap-C2VkMbW1.js`
- `agents/web/v2/assets/index-CUer-ESL.js`
- `agents/web/v2/assets/modes-DWhZHySS.js`
- `agents/web/v2/assets/modes2-CIdIZPeL.js`
- `agents/web/v2/assets/modes3-DJF9vW0Y.js`
- `agents/web/v2/assets/modes4-C_GsztC_.js`
- `agents/web/v2/assets/modes_world-xZS0jIzF.js`
- `agents/web/v2/index.html`
- `docs/FLAGS.md`
- `docs/HERMES_CAPABILITIES.md`
- `docs/design/HUD_V2_REMAINING.md`
- `docs/hermes/assessment.json`
- `docs/hermes/h277-deepinfra-vision-plan-2026-10-02.md`
- `frontend/src/api/schema.gen.ts`
- `frontend/src/composer-images.tsx`
- `frontend/src/test/composer-images.test.tsx`
- `mobile/PARITY.md`
- `project-status.json`
- `tests/test_h277_deepinfra_vision_catalog.py`
- `tests/test_h277_deepinfra_vision_consumer.py`
- `tests/test_h277_deepinfra_vision_roles.py`
