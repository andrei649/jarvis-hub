# Image provider response failure evidence

- Generated: 2026-10-09 UTC.
- Goal: distinguish a narrowly proven provider-response failure from an uncertain
  image-task result, without claiming no remote work, no charge or safe retry.
- Base / HEAD before edits: `d48f6f4dfa07070ae2518075224a889f261a8dbc`.
- Branch/worktree: `codex/image-provider-failure-state-20261009`,
  `/workspace/jarvis-hub-image-failure-state`.
- Delivery: local; draft PR #1247 remains a separate previously published unit.
- Plan: [fixed contract, ownership and rollback](plans/2026-10-09-image-provider-failure-state.md).

## Behavior and boundary

The admin-only generation-task projection now exposes `state: failed` with null
artifact only for a normally completed cloud-image task whose exact fixed
provider-response envelope reports one of three outcomes: an unacceptable HTTP/encoding response,
an oversize response, or an invalid image response. Kind/plugin/POST/fixed endpoint
identity and the exact two-key result shape must match. The fetched row's ID is
checked as a positive non-boolean integer equal to the requested ID before both
cloud and local branches. Raw reasons, details, prompts, paths and provider bodies
are not returned.

The existing cloud runtime still verifies durable completion and bytes before
returning `ready`; that recovery outranks even a contrary stored failure envelope.
A cloud row carrying a local-shaped success envelope cannot bypass recovery.
Generic queue FAILED, reaper/crash/retry exhaustion, unknown delivery,
withheld-after-generation, machinery failures, malformed envelopes and all
current local generator failure reasons remain uncertain. In particular the
current ComfyUI `generation_failed` reason is not reliable terminal evidence.

Web and native readers accept the new finite null-artifact state and state its
limited meaning: no usable image was verified; inspect the task before another
proposal. Their existing refresh lifecycle clears old previews. The state does
not trigger a PNG fetch, automatic proposal or polling for an active task.
Native cloud proposal controls are not added. Worker execution, providers,
approvals, transport, authority and persisted schemas are unchanged. The result
is evidence within the queue-controlled domain, not a separately signed negative
attestation and not protection against a writer forging the entire database row.

## Regression and client checks

Backend tests first failed on the new projection and row-ID checks (12 failures)
and a separate forged local-success-on-cloud exclusion (one failure). The final
four-file backend union passed **159/159**, no skips/failures, using real queue,
worker and cloud-runtime fixtures with mocked network responses where relevant.
Existing producer cases now check the public projection; an actual completion
and restarted runtime prove that verified recovery still wins.

Client RED runs had five failing frontend cases and one failing mobile API case.
Focused GREEN runs passed **92/92 frontend/native cases** in three files and
**10/10 mobile API cases**. New cases cover the finite state, null artifact,
distinct uncertainty, no business or artifact request and cleared previous
preview. The complete mobile Jest suite passes **306/306**, 53 suites, no skips or
failures. Native TypeScript, browser app TypeScript and E2E TypeScript pass.

The complete default frontend/native suite passes **2,009/2,009**, 225 files,
no skips/todo/failures: **1,844 HUD cases /206 files** and **165 native cases
/19 files**. Full backend collection succeeds at **21,154 cases** (+25) in 1,023
files. The full backend execution milestone is pending below. No physical
device or live provider was used.

## Browser and generated contract

The committed production bundle builds. Two Chromium checks pass at 1280px and
390px: hard reload retains the failed state, manual refresh distinguishes
uncertainty, the admin header is present, no PNG/business request occurs, and
terminal failures do not retain the active-task polling timer. Screenshots were
inspected and the panel stays within each viewport. API bodies are fixtures;
backend regressions separately establish which producer results justify them.

The first browser attempt could not launch because the expected Chromium binary
was absent. Installing the matching Playwright headless runtime in the execution
environment resolved this prerequisite; no application/package source changed.
The subsequent browser run passed **2/2** in 8.7 seconds.

OpenAPI was exported directly from `web.app.openapi()` without starting the app
lifespan. Pinned openapi-typescript 7.13.0 regenerated exactly one schema change:
`ImageTaskView.state` gains `failed`. Route count, paths, operations and guards
are unchanged; all three route snapshots stay byte-identical. The generated
production assets are included with the source changes.

## Review and freshness

Two gpt-6-sol/high writers implemented separate backend and client files and
cross-reviewed the final changes. No Critical/Important issue remained. A
read-only gpt-6-luna/medium inventory and named claim reviews were checked against
the base. Root's final all-changed-path inventory includes test pins omitted from
the initial source-only inventory: **22 previously current pins** are refreshed;
**four already-stale changed-path pins** are preserved. Unchanged snapshot pins
need no refresh. All assessment summaries, statuses and remaining-work text stay
identical. H312's stale router pin remains stale while its current view pin is
reviewed and refreshed independently.

The router comparison finds only `media_generation_task` changed; its other
23 top-level symbols are structurally unchanged. Image proposal controls, VLM/
role/privacy behavior, gallery/export and binary delivery retain their existing
claims. The generated TypeScript role/vision types are unchanged. No affected
inline file/line citation needed repair.

Reports in `/workspace/scratch/`: `image-provider-failure-backend-focused.xml`,
`image-failure-clients-{red,green}-{frontend,mobile}.log`,
`image-failure-mobile-final.json`, `image-failure-mobile-tsc-final.log`,
`image-failure-build-final.log`, `image-failure-browser-final.log` (missing runtime),
`image-failure-browser-install.log`, `image-failure-browser-verified.log`,
`image-failure-frontend-final.json`, and `image-failure-backend-collection.log`.

H18.27 remains partial for local terminal-failure evidence and physical-device/
live-generator acceptance. This increment adds no activation or remote publication.
