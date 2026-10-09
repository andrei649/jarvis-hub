# Preserve the latest native Status refresh

- Generated: 2026-10-09 UTC.
- Goal: delayed older reads must not replace the latest Status refresh, erase its
  data/error state, or dismiss its loading indicator.
- Base / HEAD before edits: `573cb12bc2a065a99c3d9e5c47b4a30bcd332af7`.
- Branch/worktree: `codex/native-status-refresh-order-20261009`,
  `/workspace/jarvis-hub-native-status-refresh`.
- Dependency: existing native React harness and H18.32's independent mediation
  card. No endpoint or shared transport change is required.
- Next action: device/live-hub acceptance during the broader native pass; continue
  other local backlog work from this checkpoint.

## Evidence and scope

The original Status loader has two concurrent read batches followed by a brief
read. It commits each completed invocation without checking if a newer refresh
has started. Pull-to-refresh remains available while loading, so an older request
can overwrite a newer model/Trust result. An older catch clears newer state and
its finally can dismiss a newer loading indicator. This is a read-order bug, not
an authority escalation. The H18.32 mediation card independently fences its state.

Use a monotonically increasing request generation. Invalidate on every load and
on effect cleanup. Guard success after each awaited phase, catch and finally;
avoid launching later read phases for a stale invocation. Preserve the existing
transport, fallback values and presentation for the currently active load.

The real App unmounts Status when opening Settings, so a cross-credential display
race is not currently reachable through that navigation. Do not broaden this fix
into a new screen architecture, general credential cache, read cancellation,
voice lifecycle, business controls, or shared test-shim changes.

## Ownership, validation and rollback

- One gpt-6-sol/high writer owns only `mobile/src/screens/StatusScreen.tsx` and
  new `frontend/native-tests/status-refresh-order.test.tsx`.
- Coordinator owns documentation, generated counts, the previously current H135
  evidence pin after claim review, integration and git. Another gpt-6-sol/high
  agent may independently review; no nested delegation.
- RED then GREEN mounted regressions cover stale first-batch success, stale
  Trust/brief success, stale failure, stale finally while the current load is
  pending, and unmount/disposal. Exercise the actual refresh callback using the
  existing native host harness and deterministic deferred results.
- Run the complete native React suite and native TypeScript, then the complete
  frontend suite serially for the new test inventory. Mobile API/backend suites
  need no repeat because their implementation is unchanged. Android/iOS exports
  are repeated only if Metro-specific changes or unresolved bundling concerns
  arise; the preceding H18.32 checkpoint exported both platforms.
- Reconcile Status theme evidence and generated project/Hermes metadata; run the
  status/Hermes regressions and whitespace checks. No device/live-hub claim.
- Rollback: revert this screen-only generation fence, its regressions and local
  delivery metadata. There is no persisted state migration or authority change.

## Outcome

The frozen source adds a generation ref, guards after all three awaited phases
and in catch/finally, and effect-cleanup invalidation. It changes no JSX, styling,
voice handler or shared transport. All five deterministic mounted regressions
failed before the source fix and passed afterward. Native TypeScript passes.

The complete default frontend suite, which includes the complete native React
suite, passes **2,004/2,004** in 225 files: **163 native cases /19 files** plus
**1,841 HUD cases /206 files**, no skips/todo/failures. It ran serially with the
repository's one-worker default; no native suite was redundantly rerun.

Independent gpt-6-sol/high review found no Critical/Important issue. Only the
previously current H135 Status pin was refreshed after confirming the entire
presentation/theme/voice section remained byte-identical. Assessment claims and
verdicts are unchanged. See [full evidence](../../mobile/docs/native-status-refresh-order.md)
for report paths, metadata verification and unrun device/backend/build limits.
