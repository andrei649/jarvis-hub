# H18.32 — native task mediation status

- Generated: 2026-10-09 UTC.
- Goal: read-only native parity for the owner HUD's task mediation evidence.
- Base / HEAD before changes: `d8374382ffdcef4d27d0cf20a58e1ad8c558b4bc`.
- Branch/worktree: `codex/native-mediation-status-20261009`,
  `/workspace/jarvis-hub-native-mediation-status`.
- Delivery: local; this unit is not included in draft PR #1247.
- Changed source: `mobile/src/api/client.ts`, new
  `mobile/src/components/TaskMediationCard.tsx`, and a bounded insertion in
  `mobile/src/screens/StatusScreen.tsx`. New tests are
  `mobile/src/api/__tests__/taskMediation.test.ts` and
  `frontend/native-tests/task-mediation-status.test.tsx`.
- Plan: [scope, ownership and rollback](../../docs/plans/2026-10-09-native-mediation-status.md).

## Behavior and limits

Status now shows Task mediation immediately after Trust. The card reads the
existing admin-only `GET /autonomy/mediation`, using the shared transport with a
15-second deadline and no retries. It refuses a blank admin token before network
dispatch. Modes are restricted to `off`, `hold` and `enforce`; valid evidence
requires all four counters to be nonnegative safe integers. Invalid evidence
requires null stats. Extra fields are discarded, and malformed responses are
rejected rather than converted to zero.

Effective mode and evidence validity are shown separately. Counts cover verified
recorded events, not all tasks or program acceptance. Refresh, malformed responses
and failures remove the previous projection. Missing connection/admin settings
link to Settings; other failures use a neutral unavailable message with no raw
error details or misleading user-token diagnosis. The card introduces no task
mutation, mode control, approval action or raw signed-event view.

Connection epochs and the parent pull-refresh key remount the card with empty
state before effects run. Request sequencing and unmount cleanup suppress older
same-scope results. The actual Status pull-to-refresh callback refreshes this card
independently of failures in the existing larger Status request batch. The
pre-existing general Status loader is unchanged; this unit makes no stale-read
claim for its other fields.

## Verification

Both writers demonstrated failures before implementation, then passed their
21 new API and 21 new mounted React regressions. The mounted suite uses the real
ServerProvider and StatusScreen with native host/service mocks. A file-local
ScrollView adapter exposes the actual RefreshControl callback; it does not alter
the shared native test shim. Coverage includes hydration, no-admin refusal,
headers, all modes, invalid/error states, immediate count removal, same-scope
ordering, hub/admin changes, unmount and global pull refresh.

- Complete mobile Jest: **305/305 passed**, 53 suites, no skips/failures.
- Native TypeScript: `npx tsc --noEmit` passed.
- Offline Expo exports for Android and iOS both passed, using `CI=1`,
  `EXPO_OFFLINE=1`, `EXPO_NO_TELEMETRY=1` and two Metro workers. The existing React
  Native private feature-flags export warning remains; no package or bundler
  workaround was introduced.
- Complete default frontend suite, one worker and no concurrent Metro export:
  **1,999/1,999 passed**, 224 files, no skips/todo/failures. This includes
  **158 native cases in 18 files** and **1,841 HUD cases in 206 files**; both
  previously failing browser cases pass in this complete final run.

The first frontend integration run overrode the repository's one-worker default
with four workers while Metro exports were running. It reported **1,997 passed,
two failed** out of 1,999 cases in 224 files. Only these unchanged browser cases
failed:

1. `desktop.test.tsx` — `floating app renders existing chat without normal shell or world control`:
   the expected conversation did not appear before the query timeout; the DOM
   still showed the lazy page loading state.
2. `pointer.test.tsx` — `the pointer does not re-render for a DOM change that leaves its target where it was`:
   three profiler commits were observed instead of two in a timer/animation-frame
   sensitive assertion.

Both entire modules subsequently passed **26/26** with one worker. No source,
test or timeout was changed. Browser source and built assets are byte-identical
to the base. Scheduling contention is a possible explanation, not a demonstrated
root cause; the first failed run remains recorded separately.

Reports in `/workspace/scratch/`: `native-mediation-mobile-final.json`,
`native-mediation-tsc.log`, `native-mediation-export-{android,ios}.log`,
`native-mediation-frontend-final.json`, `native-mediation-browser-repro.json`, and
`native-mediation-frontend-serial-final.json`.

Project/Hermes freshness and the executed frontend/mobile count checks pass.
The metadata regression union passes **86/86**, no skips/errors/failures
(`native-mediation-metadata-final.xml`). Current tracked inventory is backend
21,129, frontend 1,999, mobile 305, and 555 routes.

Two gpt-6-sol/high implementation agents cross-reviewed the API and UI; the final
pull-refresh regression was reviewed separately. No Critical/Important finding
remained. A gpt-6-luna/medium investigator reviewed collateral evidence. Only the
two previously current H526/H135 pins were refreshed after source comparison:
existing TTS behavior and Status theme styles are unchanged; the H526 TTS citation
moves by the inserted 58 lines. Assessment verdicts and remaining-work claims are
preserved.

No backend source, route, OpenAPI contract, browser bundle, dependency or persisted
state changed. The backend inventory is reused at 21,129 and routes at 555; no
complete backend run is claimed for this native-only unit. Physical-device and
live-hub acceptance remain open. DRA-59 retains its broader task-kind, scheduled
producer and program-acceptance work, with B7 still default-off.

Next action: inspect the card on Android/iOS against a configured hub, exercise
all effective modes, refresh/failure/recovery and connection changes, then record
device/live evidence without inferring it from host mocks or offline exports.
