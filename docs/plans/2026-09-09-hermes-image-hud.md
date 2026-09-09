# Governed image composer and result view

Generated: 2026-09-09. Goal: the instance owner can propose an image, approve it
in the existing Decision Inbox, follow its task and view/download authenticated
PNG bytes. Branch `codex/hermes-image-hud`; exact dependency/base/head before
changes: `1027a1971c04403c175e2474bb847f7ed426d1a2` (backend PR #1064, pending
integration). No lease. This branch must be rebased from that exact boundary
onto the eventual squash commit without replaying the backend implementation.
The integration record at the end supersedes the initial dependency instructions.

Non-goals: activation, ComfyUI/model installation, cloud, new approval semantics,
per-conversation privacy, catalog migration, automatic resubmission or backend
authority edits. No protected paths or mutations in the backend worktree.

Implementation: a small admin-only image-task projection in multimodal routes;
new frontend API adapter and panel; authenticated bounded PNG blob transport;
Console placement and image-specific readable Decision Inbox summary. Raw task
payload/results, host paths, backend URLs and internal approval fields are never
rendered by the new panel. Changes to other task editing are out of scope.

The panel uses the current owner authentication, observes one selected task,
aborts/ignores stale reads and revokes blob URLs on replacement/unmount. Config
alone means configured/unprobed. A done task requires validated nested success
and artifact ID before showing an image. A lost POST response is uncertain and
never triggers an automatic retry. No image/task history or prompt persistence
is added to browser storage; this is an instance-owner surface.

Tests: regression-first backend projection/auth/redaction and focused frontend
fetch/UI tests for exact requests, approval separation, response validation,
uncertainty, auth, byte bounds, cancellation, stale responses, blob cleanup,
image-only Inbox changes and accessibility. Run related frontend tests, type
check/build and Python route/OpenAPI/parity guards. Record actual outcomes below.

Rollback: revert this single UI + read-projection PR; the approved image backend
remains independently usable. Update BACKLOG, HUD/mobile parity, schema and
generated status in this delivery. Next action: failing regressions then code,
independent review and local commit handoff; no push or merge from this agent.

## Stable implementation handoff — 2026-09-09T16:02:00+03:00

The owner Images panel, existing Inbox integration and exact-task projection are
implemented. Reopening can resume a known task ID with a read only; no browser
prompt/task persistence was added. The new frontend transport uses header auth,
refuses redirects and URL control-character normalization, bounds JSON/PNG reads,
aborts unfinished response bodies and never retries a proposal. Preview URLs are
revoked on replacement/unmount and late reads cannot replace a newer selection.

Verification actually run: all **1,084 frontend tests passed** (43 new cases),
including **52** focused image/Inbox tests. **28** new Python projection cases
passed; the targeted projection/route/OpenAPI/auth/HUD/typegen/document packet
passed **59** tests. TypeScript typecheck, production bundle build, Ruff and
diff whitespace check passed. Local tools: Node 24.17.0, Vite 8.2.1, Vitest
4.1.10, TypeScript 7.0.2, React/ReactDOM 19.2.8; Python 3.11.15. The full Vitest
JSON report is outside tracked source and was handed to the integrating agent.
The first full frontend invocation used the repository root and hit existing
relative-path fixture failures; the correct frontend working directory passed.

Independent read-only review found two transport cleanup/origin issues; both
were fixed with six regressions and independently rechecked. Review closed with
no remaining actionable finding; reviewer independently ran 52 frontend and 28
Python cases. No live ComfyUI, new service, installation or cloud proof was run.

The wider pre-rebase Python packet still hit the known `media_generate` component
guard issue in dependency head 1027a197. Backend PR #1064 has since merged that
repair as `8db71a9dbc257b0997c9b2d46d29ce2dc8f7593c`; do not reintroduce the old
guard. Next action: integrate this clean single commit by rebasing **only the HUD
slice after 1027a197** onto current main, retain the backend repairs, remove
its now-called artifact route from `UNCALLED_BACKLOG`, recount the roadmap headline
(S1 subsequently adds one route), then regenerate status with the measured frontend count and rerun the
affected merge-boundary checks before a PR. Do not replay the backend commit.

Final real-browser visual review found the two new links inherited a 2.01:1
browser-blue contrast on the dark panel. The bounded style follow-up uses the
existing `--accent-light` theme token for those two links only. Eleven panel
tests and the rebuilt production bundle passed; independent Chromium recheck
measured **12.86:1** for both links and closed the finding. This visual recheck
used only synthetic GET fixtures, no generation POST, and its temporary preview
was closed. The unchanged full behavioral suite was not rerun for this color fix.

## Integration record — 2026-09-09T13:22:00Z

Goal and rollback remain the single image composer/result-view unit above. Base:
`652f6cf3a2f645be202f0ab7840ed69f4a498155` (S1 #1065 on top of image backend #1064).
Only the HUD commit is replayed; the S1 source tree and its squash tree were
verified identical. Head is recorded by the resulting PR, not guessed here.
Changed paths: image projection/router, frontend image transport/panel/Inbox,
generated production assets/API schema, regression tests, BACKLOG and delivery
documentation/parity/status. No protected control-plane paths.

Merge resolutions preserve the repaired component guard and authenticated
artifact route, include the new admin task-view route, and remove both genuinely
called media routes from the client punch list. S1's extension inspection remains
on that list: ten routes remain, six deliberate refusals and four open UI items.
The API manual and schema were regenerated. Actual backend collection is 9,617;
the saved full frontend result verifies 1,084 passes, with 137 mobile tests reused.
There are 479 routes. These inventory totals do not claim full local Python/mobile
execution. The same document pass corrects the stale P26 Ollama proof statement,
preserving the separate LM Studio/long-turn/memory/cloud proof gaps.

After combining both dependencies, the image backend/runtime/view and route,
guard, auth, OpenAPI, HUD, document-reference, API-manual and typegen test packet
passed. All 52 image/Inbox frontend tests passed again; TypeScript, Ruff, generated
status/count verification and whitespace checks passed. The projection's invalid
result exception now explicitly returns its uncertain state; 28 view regressions
and targeted Bandit passed. No baseline or scanner suppression was added.

Independent real Chromium 149.0.7827.55 used the built bundle and local synthetic
API fixtures: one proposal, a separate approval, authenticated PNG rendering and
download, then cache-disabled hard reload without repeating the proposal. JS/CSS
were refetched; no browser errors occurred. This is not live ComfyUI or PWA cache
proof. The final color-only build was separately inspected at 12.86:1 contrast.
Temporary previews were stopped. Next action: PR checks on the final head, trusted
policy classification, then squash merge only when every required/reporting gate
passes. Generation remains default-off pending an actual configured local service.

## Production composition follow-up — 2026-09-09T13:35:00Z

The first hosted run passed all 1,084 frontend tests, Python tests and security
scans, but rejected the committed bundle: the shared local dependency cache used
Vite 8.2.1 instead of the lockfile's 8.2.2. An isolated temporary runtime was
installed from the unchanged lockfile (Vite 8.2.2, Vitest 5.0.0); the shared
checkout's dependencies were preserved. Its rebuild matched the hosted asset.

A separate production-composition probe then found an image intake mismatch at
the real MediationKernelBridge: logical tool kind/title/args-key authorization
did not match the complete queued image proposal. Image backend integration is
being corrected independently on `codex/hermes-image-composition`; this HUD PR
must wait for that repair and its real bridge/worker regression packet.

The stable corrected durable contract is kind `tool.rpc`, with payload `tool`
and `target` both `image_generate`. This HUD accepts that exact identity and keeps
legacy image task reads. Ordinary canonical tools retain their existing Inbox
controls. The new canonical projection and Inbox regressions failed before the
fix; 33 projection tests, 54 focused frontend tests, and the complete 1,086-test
frontend suite then passed. TypeScript and E2E TypeScript passed. Final rebuilt
asset: `index-BmNGjE-_.js`, SHA256
`5dbe8fe82ce7276cc23953988bfa48be0c7e86c16368f5f5cc08ed204b03aace`.
The independent Chromium synthetic flow was repeated on that exact bundle and
canonical task shape: one proposal/approval, authenticated PNG, clean hard reload,
read-only resume, 12.86:1 links and no page errors. Previews were stopped.
This still does not establish real backend composition or live ComfyUI proof.
