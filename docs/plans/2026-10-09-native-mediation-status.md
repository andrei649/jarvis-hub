# Native task mediation evidence status

- Generated: 2026-10-09 UTC.
- Goal: H18.32 read-only parity with the owner HUD mediation status, inside the
  existing native Status screen next to Trust.
- Base/head before edits: `d8374382ffdcef4d27d0cf20a58e1ad8c558b4bc`.
- Branch: `codex/native-mediation-status-20261009`.
- Dependency: admin `GET /autonomy/mediation` already implemented and covered by
  signed-queue HTTP tests; no backend change is required for this unit.

## Contract and presentation

Add `fetchTaskMediationStatus(config)` and `TaskMediationStatus` to the native API
client. Reuse the existing admin GET transport,15-second deadline and no retries.
Validate the entire response: mode `off | hold | enforce`; boolean `valid`; when
true, all four named counters must be nonnegative safe integers; when false,
`stats` must be null. Copy only the named fields. Reject unknown/malformed shapes
instead of coercing values or inventing zeros. Send no body and no business write.

Mount a separate `TaskMediationCard` immediately after Trust in `StatusScreen`.
Its independent lifecycle avoids coupling evidence to the screen's larger status
batch. Reuse native theme/text/button patterns, with no new navigation or package.
Only load after settings hydration, a configured hub and a nonblank admin token.
Missing admin credentials explain the known requirement and link to Settings;
other failures display a neutral unavailable state without raw error bodies,
credentials or the shared transport's misleading user-token diagnosis on401.

Show effective mode and evidence validity separately. `valid:false` means
unavailable or invalid evidence, never a proven corrupt chain. Show four counts
only after a complete valid response. Clear counts while loading/reloading and on
failure. The card has explicit refresh/retry and Settings access, with no enable,
decision, raw-event or approval control. Counts cover recorded verified events,
not all-task coverage or operational acceptance.

Scope state to `connectionEpoch` so a hub/credential save synchronously removes
the previous projection. Suppress delayed results after newer reads, scope changes
or unmount using request sequencing and cleanup. The shared transport still owns
its normal timeout; this unit does not expand generic cancellation behavior.

## Ownership, checks and rollback

- API writer: `mobile/src/api/client.ts` and new
  `mobile/src/api/__tests__/taskMediation.test.ts`.
- UI writer: new `mobile/src/components/TaskMediationCard.tsx`, minimal insertion
  into `mobile/src/screens/StatusScreen.tsx`, and new mounted React regressions
  `frontend/native-tests/task-mediation-status.test.tsx`.
- Coordinator: independent integration, documentation/parity/counts/evidence/git.
  Two implementation agents use gpt-6-sol/high; optional read-only collateral
  inventory uses gpt-6-luna/medium. No nested delegation or shared-file writers.
- Red/green API checks: admin-only and combined credentials, exact GET/no body,
  three modes, valid zeros, invalid evidence, missing/wrong/negative/fractional/
  unsafe counter values, denied/unavailable/network responses and no retry.
- Mounted behavior checks: actual Status placement and fetch, missing-admin
  no-request/Settings, counts and mode, hidden stale counts on refresh, malformed/
  invalid/error states, delayed responses after credential changes/unmount and
  overlapping read ordering. Use the existing native React host harness.
- Integration: relevant native API/component regressions, native TypeScript,
  complete mobile Jest and native React suites, offline Android/iOS bundle exports,
  exact inventory and project/Hermes freshness. No live device/hub/provider claim.
- Rollback: revert API helper, card/insertion, tests and delivery metadata as one
  local unit. No persisted data, permission, backend or dependency change.
- Next action: device/live-hub acceptance; continue other local backlog work from
  the saved checkpoint.

## Implementation outcome

The two API/UI writers completed the fixed contract. The parent Status pull
refresh also remounts the card immediately; its mounted regression invokes the
actual RefreshControl callback and keeps the mediation read independent of the
pre-existing Status batch. No shared native mock or dependency changed. The
separate older Status loader still has its own same-scope ordering gap; this unit
claims stale-response suppression only for the new card.

Both new test groups demonstrated RED before implementation, then GREEN (21 API
cases and 21 mounted cases). Full mobile Jest is 305/305 in 53 suites; native
TypeScript and offline Android/iOS exports pass. Initial four-worker frontend
integration reported 1,997 passes and 2 failures in unchanged browser timing tests
while exports were active. Both whole modules pass 26/26 alone with one worker;
no test/source/timeout was altered. The complete suite then passed **1,999/1,999** in 224 files with its
configured one-worker default, including both originally failing browser cases. See [integration evidence](../../mobile/docs/h1832-task-mediation-status.md)
for the final result, exact limits and report paths.

Cross-review by the two gpt-6-sol/high agents, including the final pull-refresh
test, found no Critical/Important issue. The gpt-6-luna/medium collateral review
identified just two formerly fresh evidence pins. H135 keeps its theme claim;
H526 keeps its byte-identical TTS behavior and moves its client citation by 58
lines. Their statuses and remaining-work claims are preserved.
