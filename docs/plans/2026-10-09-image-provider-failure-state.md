# Project confirmed image provider response failures

- Generated: 2026-10-09 UTC.
- Goal: show a known provider-response failure separately from an uncertain
  execution result, without claiming remote work or charges did not occur.
- Base / HEAD before edits: `d48f6f4dfa07070ae2518075224a889f261a8dbc`.
- Branch/worktree: `codex/image-provider-failure-state-20261009`,
  `/workspace/jarvis-hub-image-failure-state`.
- Next action: run the complete backend milestone against the saved source
  checkpoint. Development and commits remain local.

## Fixed contract

Add `failed` to the existing finite ImageTaskView state contract. It means only
that a normally completed cloud image attempt received a provider response but
returned no accepted image artifact. It does not prove that remote generation
never happened, that no charge occurred, or that a retry is safe.

Project this state only if all conditions hold:

- The fetched row has a positive, non-boolean integer ID matching the route's
  selected task ID. Check this before the cloud branch as well as local reads.
- Task kind is exactly `plugin.egress`; payload is a plain dict with plugin
  `cloud-image`, method `POST` and URL equal to the fixed OpenAI image endpoint.
- Queue state is exactly `done`; the plain result dict has exactly keys `status`
  and `reason`, status `failed`, and one fixed reason:
  `cloud_image_provider_error`, `cloud_image_response_too_large`, or
  `cloud_image_invalid_response`.
- The existing cloud completion recovery keeps precedence: verified durable
  artifact recovery still returns `ready`. Failure projection exposes only
  `{task_id, state: failed, artifact: null}`, never raw reason/detail/body/prompt.

Every unmatched or malformed envelope remains `uncertain`, subject to the route's
existing non-image/availability handling. Generic queue FAILED, crash/reaper,
retry metadata, submission/delivery unknown, withheld-after-generation,
preflight/recheck/mediation machinery failures, and all current local image
failures are excluded. ComfyUI `generation_failed` currently includes malformed
or nonterminal history; it must not be treated as proven terminal failure.

This is evidence within the queue-controlled task/result domain, not an
independently signed failure attestation. No new worker, provider, publication,
retry, approval, authority or persisted-state behavior is added.

## Clients

Extend the backend, browser and native finite schemas atomically. Both clients
show the narrowly worded provider-response failure and retain manual task
inspection/refresh. Suggested copy: “Provider response failed; no usable image
was verified. Check this task before proposing another.” No automatic proposal,
retry or PNG preview/download may be caused by this state. Existing uncertain
copy remains distinct. A previously shown preview is cleared on a failed read
using the existing lifecycle. No new native cloud proposal surface is implied.

## Ownership and checks

- Backend writer (gpt-6-sol/high): `agents/core/image_generation_view.py`, bounded
  task-ID check in `agents/core/routers/multimodal.py`,
  `tests/test_image_generation_view.py`, and relevant producer/project regressions
  in `tests/test_cloud_image.py` only if needed to prove recovery/producer mapping.
- Client writer (gpt-6-sol/high): `frontend/src/api/images.ts`,
  `frontend/src/panels/images.tsx`, their existing API/panel tests;
  `mobile/src/api/generatedImages.ts`, `mobile/src/screens/GeneratedImages.tsx`,
  their existing API tests and `frontend/native-tests/generated-images.test.tsx`.
- Root owns coordination, independent review, any browser smoke, generated
  OpenAPI/TS/bundle/status artifacts, collateral pins, docs and git. A narrowly
  scoped read-only gpt-6-luna/medium investigator may inventory collateral.
  No nested delegation and no shared-file writers.
- RED then GREEN: all three exact reasons; task identity/ID/auth/no-cache;
  excluded queues, local envelopes, unknown/withheld/malformed/extra-key results;
  real producer failure → public state, and valid completion recovery wins.
- Client regressions: strict new finite state, malformed/unknown still rejected,
  distinct failure/uncertain text, no artifact read or business mutation, old
  preview cleared on refresh. Preserve local and cloud proposal semantics.
- Integration: focused backend cloud/projection/route gates, native Jest and
  TypeScript; complete frontend/native suite; browser app/E2E type checks and
  committed production bundle, production-browser hard reload at desktop/phone
  widths. Full suites run serially. Backend collection/results drive inventory;
  a full backend milestone is warranted if route/generated/collateral scope grows
  beyond the focused contract. No provider calls or device acceptance implied.
- Reconcile route/OpenAPI response schema and generated TS without changing route
  count. Refresh only formerly current collateral after named claim review;
  preserve already stale pins and all unrelated assessment claims/verdicts.
- Update H18.27/image parity and HUD remaining evidence without closing the still
  uncertain local-failure or physical-device/live-generator acceptance work.
- Rollback: revert projection/identity guard, both finite clients, tests and
  generated/docs artifacts as one local unit; there is no data migration.

## Implementation and pre-milestone evidence

The backend adds the exact failed projection and validates row ID before both
route branches. A separate regression exposed that an unmatched cloud row could
borrow the old local-success parser; cloud rows now require verified recovery for
ready. No runtime/provider/worker source changed. Initial RED had 12 failures; the
forged-success regression was separately RED. The final focused union passed
159/159, followed by 3/3 existing route cases with an added no-store assertion.

Client RED had 5 frontend and 1 mobile failures, then focused GREEN 92/92 and 10/10.
Full mobile Jest 306/306 and native TypeScript pass. Browser app/E2E types and
production build pass. A fresh headless Chromium runtime resolved an initial
pre-launch missing-browser failure; the actual production-shell smoke then passed
2/2 at 1280/390px, including hard reload, distinct uncertain copy, admin credentials,
no PNG/business requests and no retained active-task poll. Screenshots were
inspected. No live provider, native device or new cloud proposal UI was used.

Independent cross-review found no Critical/Important issue. Named collateral
review plus an all-changed-path inventory covers 22 formerly current pins,
including additive test changes; 4 already-stale changed-path pins are untouched.
All assessment claims/verdicts remain identical. Schema generation changes only
the ImageTaskView state literal; route/auth/operation-ID snapshots are unchanged.
Final complete frontend and backend milestone results are recorded in
[the integration evidence](../project-image-provider-failure-20261009.md).
