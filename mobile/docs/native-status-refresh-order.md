# Native Status refresh ordering

- Generated: 2026-10-09 UTC.
- Goal: the latest initiated Status refresh owns subsequent data/error/loading
  updates, even when previous network reads finish later.
- Base / HEAD before edits: `573cb12bc2a065a99c3d9e5c47b4a30bcd332af7`.
- Branch/worktree: `codex/native-status-refresh-order-20261009`,
  `/workspace/jarvis-hub-native-status-refresh`.
- Changed code: `mobile/src/screens/StatusScreen.tsx` and new
  `frontend/native-tests/status-refresh-order.test.tsx`; related plan, backlog,
  parity, H135 evidence pin and generated inventory.
- Delivery: local; not included in draft PR #1247.
- Plan: [scope and rollback](../../docs/plans/2026-10-09-native-status-refresh-order.md).

## Fix

Pull-to-refresh could previously start a second Status read while the first was
still running. An older response could replace a newer model, Trust snapshot or
brief. An older failure could clear visible data and show an outdated error; its
finally could also dismiss a newer refresh's loading indicator.

The screen now gives each configured load a generation and invalidates it when
its effect cleans up. Success paths check the generation after each awaited
phase; stale loads do not start later phases. Catch/finally update state only
for the current generation. Current-request fallback/error behavior and the
existing presentation remain unchanged. H18.32's separate mediation card keeps
its own independent lifecycle and refresh key.

This is read ordering and cleanup, not request cancellation. Already-started
requests still settle through the existing transport/deadline. No endpoint,
credential, business-write, voice or persisted-state behavior changes. App
navigation currently unmounts Status before Settings; this fix does not claim a
new credential-switch architecture or atomic snapshot across all feeds.

## Evidence

Five mounted native React regressions failed before the source fix and passed
after it. They exercise the actual RefreshControl callback through a file-local
ScrollView adapter and deterministic deferred fetch results:

1. A stale first-batch model cannot replace the newer model or launch downstream
   Trust requests.
2. A stale Trust batch cannot replace the newer snapshot or launch its brief.
3. A stale brief cannot replace the newer brief.
4. An older HTTP400 failure leaves existing data and the newer loading indicator
   intact, with no stale error; the current refresh then completes normally.
5. Resolving the first batch after unmount starts no downstream reads.

Native TypeScript passes. The complete default frontend suite passes
**2,004/2,004**, 225 files, no skips/todo/failures: **163 native cases in 19 files**
plus **1,841 HUD cases in 206 files**. The unchanged browser tests are included. Tests run with real React source and host/service mocks; no
physical-device or live-hub acceptance is inferred. No native bundler/dependency
changed; Android/iOS exports already passed at the immediately preceding
H18.32 checkpoint and were not repeated for this ref-only screen fix. Mobile API
and backend implementations are unchanged; their complete suites were not rerun.

Reports in `/workspace/scratch/`: `native-status-refresh-red.log`,
`native-status-refresh-green.log`, `native-status-refresh-tsc.log`, and
`native-status-refresh-frontend-final.json`.

The executed frontend inventory check and generated project/Hermes freshness
gates pass. Metadata regressions pass **86/86**, with no skips/errors/failures
(`native-status-refresh-metadata-final.xml`). Inventory is backend 21,129 and
mobile 305 (reused), frontend 2,004 (executed), and 555 unchanged routes.

A gpt-6-sol/high writer implemented the regression and fix; a separate
gpt-6-sol/high review found no Critical/Important issue. The coordinator verified
the source diff and owns integration. Only the previously current H135 Status
pin is refreshed: the JSX, theme/style definitions and shared appearance behavior
are unchanged, and assessment claims/verdicts remain identical. The complete
native suite includes the mounted Status appearance-consumer regression.

Next action: validate refresh behavior on a device with the configured hub when
performing the broader native acceptance pass; continue other local backlog work
without treating offline host tests as that acceptance.
