# H277 image-turn selection confirmations: verified checkpoint

Generated 2026-10-02. Goal: complete local Nerva parity with pinned Hermes
`59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`; this is a completed dependency,
not completion of H277 or the whole backlog. Base: `68e68b311e2487821eab8d9d010bad8edee40c30`.
Runtime: `e2d32f39`. Frozen tested head: `b5a8b78474a6e63df0fd122ed681927d66eb1e63`.
Branch: `codex/h277-provider-discovery-20261002`. No push, merge or deployment.
This report and its receipt are subsequent documentation-only changes.

## Delivered behavior

Image turns in the responsive HUD and CLI now offer separate training and cost
confirmations when the server requires them. Status exposes bounded explanatory
text; complete guard findings, including prices and threshold, enter the existing
destination revision. The two new POST flags are strict booleans, false by default.
Remote acknowledgment remains separate. Missing flags refuse before dispatch.

Required training consent must be audited before any client is constructed; cost
confirmation preserves the existing best-effort audit. One call receives immutable
cleared findings, which are rechecked at physical send, retries and cleanup.
Changed findings or destination revoke the old preview, including generic
compatible routes without empty retry. No reusable role/provider grant is created.

HUD requires separate unchecked controls and resets them on image changes, clear
and refresh. Malformed, duplicated or unknown requirements disable send. CLI uses
explicit --acknowledge-training / --confirm-expensive, prints the requirements,
and never applies these flags silently to ordinary text chat. Legacy unchallenged
request shapes remain unchanged. The previous absence of these controls is resolved.

## Verification and scope

- Full backend: 20,842 passed, 34 skipped, one expected failure, 64 warnings; 20,877
  collected. HEAD and all4, 344 tracked regular files stayed unchanged.
- Final focused API/CLI/native HTTP set: 229 passed; earlier integration union: 236.
  CLI red-first run: 18 failed before implementation; backend initial red: 6 failed;
  HUD red: 11 failed. These are bounded regressions, not a new mutation campaign.
- Frontend full suite: 1,858 passed; TypeScript, E2E TypeScript and build passed.
  OpenAPI types were regenerated from the actual app schema using pinned cached
  openapi-typescript 7.13.0. Production HUD assets were regenerated from source.
- Real Chrome browser: 6 cases passed across desktop and emulated mobile, including
  all three independent confirmations, submitted flags, reset, stale destination,
  cancellation, image paste/drop, provenance and ordinary text dispatch.
  The browser backend is isolated; no physical mobile or live provider proof.
- Documentation/status guards: 92 passed. Full Ruff, diff check and strict staged
  secret scan passed (40 cumulative changed paths, zero findings before full run).
- Two Sol High agents independently implemented backend and HUD under disjoint
  file ownership; coordinator implemented CLI, reviewed integration, corrected the
  old cost-drift assertion and added CLI/browser integration coverage. No agent
  delegated further. Graft was rebuilt and checked without committing its cache.

Twenty previously current/relevant Hermes rows were reviewed; 26 moved citations
were corrected only where the tool proved identical anchored source text. Other
stale rows were left untouched. Status remains 172 equivalent, 254 partial, 64
missing, 207 requiring review, zero excluded. H277 remains partial. Counts are code
assessment, not proof of live service acceptance.

The [verification receipt](evidence/h277-vision-selection-consent-verification-2026-10-02.json)
contains the frozen source fingerprint, commands and artifact hashes. Temporary
logs/XML/browser reports remain local evidence locations. Frontend/mobile counts
were not obtained by repeating suites: the new frontend count was imported from
its successful JSON result, mobile retained its unchanged tracked count.

## Next action and fidelity notes

Continue the full provider discovery integration, including actual selected main
context and the pinned OpenRouter → Nous → DeepInfra fallback order. This checkpoint
removes the composer confirmation blocker; it does not implement discovery.
Nous needs its own profile authentication/JWT refresh and tier-aware/native
adapters; do not borrow rotating Hermes credentials. DeepInfra needs live catalog
selection and credential-scoped caching, without enabling a paid route implicitly.

Fresh pinned-source inspection refines the earlier provider research:
`hermes_cli/models.py` DeepInfra chat filtering accepts explicit chat tags, but
also has a legacy model-ID exclusion fallback when no surface tag exists. Vision
still requires the vision tag and a served model (non-null metadata). Requiring
both literal chat and vision tags for every entry would incorrectly narrow Hermes.
`agent/auxiliary_client.py` allows unknown main-model vision capability to attempt;
only known false skips. Nous selects the welcome-host guest model or tier-specific
recommended Vision slot; its public recommendations endpoint is separate from
inference authentication. Preserve these contracts in the next implementation.

Rollback is the consent source commit plus its generated records/assets. No live
settings, credentials or database migrations were changed. The broader goal stays
active, including signed video, SDK recovery and all remaining accepted Hermes rows.

## Changed paths

- `BACKLOG.md`
- `GO_LIVE_PLAN.md`
- `HERMES_STATUS.md`
- `NERVA.md`
- `README.md`
- `STATUS.md`
- `agents/cli/nerva.py`
- `agents/core/llm/vision_policy.py`
- `agents/core/routers/composer_vision.py`
- `agents/web/v2/assets/gap-Dsmt6AaX.js`
- `agents/web/v2/assets/index-CJ097X2i.js`
- `agents/web/v2/assets/modes-DIgUDrto.js`
- `agents/web/v2/assets/modes2-s_rhYpLd.js`
- `agents/web/v2/assets/modes3-DUOe3J0T.js`
- `agents/web/v2/assets/modes4-8w8aLs-7.js`
- `agents/web/v2/assets/modes_world-Drl5w43M.js`
- `agents/web/v2/index.html`
- `docs/FLAGS.md`
- `docs/HERMES_CAPABILITIES.md`
- `docs/design/HUD_V2_REMAINING.md`
- `docs/hermes/assessment.json`
- `docs/hermes/h277-vision-selection-consent-plan-2026-10-02.md`
- `frontend/e2e/composer-images.spec.ts`
- `frontend/src/api/schema.gen.ts`
- `frontend/src/composer-images.tsx`
- `frontend/src/test/composer-images.test.tsx`
- `mobile/PARITY.md`
- `project-status.json`
- `tests/test_composer_vision.py`
- `tests/test_h277_vision_selection_cli.py`
- `tests/test_h277_vision_selection_consent.py`
