# H517 local provider milestone review

Generated 2026-09-27; base/head bd2bb70ead1b493043a335e77713fc42c47d4013
plus preserved local work. Goal: a configured third-party local image service
through the actual approved image workflow. Result: this slice implemented and
verified; H517 remains partial. Next action: extend shared provider contracts and
settle the video validation/provider design before implementing H516.

## Delivered behavior

Bounded, data-only configuration registers an `openai_images` service without
editing core. Existing ComfyUI configuration remains supported. The native
transport accepts only literal HTTP loopback, sends one approved request, refuses
unsupported options and validates bounded base64 PNG bytes against the requested
canvas. Core owns the opaque artifact path and atomic publication. Configuration,
implementation and approval are rechecked at physical dispatch and publication.
Status never probes a service. HUD models and edit/upscale controls follow the
selected backend; switching clears incompatible state.

The coordinator chose this finite protocol slice instead of loading installed
Python plugins into the host. That decision avoids a second code-trust system but
does not close arbitrary adapters or the shared registry across all media kinds.

## Review and corrections

Two Sol High writers owned backend/runtime and independent production integration
tests. The coordinator owned HUD changes and integration; a bounded Luna Medium
review examined authority and transport, then re-reviewed its one durability
finding after correction. No agents delegated further.

The gallery initially inherited the ComfyUI callback name; a failing integration
case exposed it, and the callback now identifies the selected backend. The first
full suite found a raw environment read outside the standard helper and an
import-time catalog path captured before the integration fixture changed home.
The environment inventory cap was retained. A focused catalog-before-integration
run reproduced the second failure; only fixture bootstrap isolation changed.

The independent review found that file fsync alone did not persist the attempt's
directory entry. Exclusive proposal/attempt writes now require file synchronization
followed by directory synchronization through the ancestor chain. Failures retain
the marker and prevent POST/replay. Real descriptor-order and injected open/sync
failure tests pass; the scoped re-review found the issue addressed and no new
helper defect. Unsupported platforms/filesystems fail closed. Native Windows
durability remains follow-up work, and OS fsync tests do not certify physical
hardware power-loss behavior.

## Verification

- Final backend: **19,363 passed, 35 skipped, zero failures/errors** (19,398 total),
  249.993 seconds. The preceding 19,394-test run had the two failures above;
  both snapshots are preserved in the evidence.
- Final source focus: **221 passed**; independent catalog/integration focus:
  **43 passed**. The actual signed queue/kernel/worker path is exercised with only
  provider HTTP replaced. Restart, concurrent ticks, revocation, wrong canvas,
  malformed response, no retry, gallery and authenticated bytes are covered.
- Frontend: **1,829 passed**; focused Images/API tests: **78 passed**, following
  four meaningful RED regressions. Typecheck/build passed; existing large-chunk
  build warning remains.
- Ruff, scoped diff checks, Bandit against the repository baseline, scoped Gitleaks
  and scoped Graft freshness checks passed. No live service, GPU, paid provider,
  native-device acceptance or coverage percentage is claimed.

Commands, result hashes and source fingerprints are in
[the evidence](evidence/h517-local-providers-2026-09-27.json).

## H518 and H523 current-source reassessment

H518's stale `gap.tsx`/`multimodal.py` changes concern vision, decision inbox and
model posture; retained-gallery pagination/search/selection/authenticated previews
and export remain intact. `media_library.py`, `media_catalog.py` and the artifact
router match their recorded evidence. Existing 200-ID/128-MiB export bounds, missing
file manifests and cursor binding remain. The new local producer reaches this
same catalog/readback path. H518 is equivalent against its frozen retained-gallery
contract, with no deleted-history or universal producer guarantee added.

H523's generated-PNG route retains user authentication, opaque IDs, shared byte
validation, no-store and nosniff. Changed Telegram code concerns decision reasons;
the existing bounded, acknowledged no-retry `send_media` path remains. Protected
settings additions do not alter the scheduled-media 1–300-second deadline.
`jobs_media.py` matches its recorded evidence and retains recipient/content checks
and durable uncertain/partial states. H523 is equivalent against its frozen
authenticated delivery and scheduled-media contract. Non-PNG validation remains
signature-level; this is not native codec or live Telegram proof.

These are explicit contract reassessments, not a blanket hash refresh. H312 and
other unrelated stale reviews were left unchanged. H517 provider breadth remains
partial, and H516 rendered video remains missing.

## Changed paths and rationale

| Paths | Purpose |
|---|---|
| `agents/core/media_backends/registry.py` | Pure bounded provider configuration, selection and capabilities |
| `agents/core/media_backends/local_openai_image.py` | Bounded local image protocol and fresh transport/publication guards |
| `agents/core/media_backends/comfyui.py` | Shared validated artifact writer and implementation fingerprint |
| `agents/core/image_generation_runtime.py` | Approved protocol dispatch, correct catalog provenance, durable attempt records |
| `tests/test_h517_local_provider.py`, `tests/test_h517_provider_integration.py` | Protocol/authority edges and actual signed production composition |
| `frontend/src/api/images.ts`, `frontend/src/panels/images.tsx` | Provider-specific model parsing and usable controls |
| `frontend/src/test/images-api.test.ts`, `frontend/src/test/images-panel.test.tsx` | Selection, default model and incompatible-state regressions |
| `agents/web/v2/index.html`, `agents/web/v2/assets/` | Regenerated committed HUD bundle |
| `docs/hermes/h517-local-provider-plan.md`, `docs/hermes/h517-provider-registration-design.md`, `docs/hermes/local-image-providers.md` | Chosen contract, superseded design and operator guide |
| `docs/hermes/h517-local-provider-review.md`, `docs/hermes/evidence/h517-local-providers-2026-09-27.json` | Review, failures/corrections and measured evidence |
| `docs/hermes/h516-video-design-checkpoint.md` | Explicit next-step protocol/validation uncertainties; no completion credit |
| `docs/hermes/assessment.json`, `HERMES_STATUS.md`, `docs/HERMES_SPRINT.md`, `BACKLOG.md`, `docs/handoff/h277/README.md` | Truthful scope, current evidence and continuation handoff |
| `mobile/PARITY.md`, `docs/design/HUD_V2_REMAINING.md` | HUD delivery and native gap |
| `project-status.json` and generated status documents | Verified backend/frontend counts |

No commit, push, merge, deployment or personal configuration mutation.
