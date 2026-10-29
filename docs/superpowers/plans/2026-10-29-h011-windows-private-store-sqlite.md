# H011 Windows Unit 2 private store and SQLite implementation plan

**Goal:** Isolate and prove a private NTFS store lease, native `LockFileEx` and
ordinary SQLite parity without Windows H011 product wiring.

**Spec:** [private store and SQLite parity](../specs/2026-10-29-h011-windows-private-store-sqlite.md).
**Freshness (generated 2026-10-29T10:25:16Z):** base and drafting head
`b5134e9a3ce925699a3b3351caca85737f137744`; the plan was independently
approved before implementation. Unit 2 is now an isolated local candidate
awaiting source/security review and native Windows execution. Unit 1's
published zero-skip Windows job is GREEN:
job `123389933746`, 40 passed, zero failures/errors/skips on Windows 2025
Server build 10.0.26100, Python 3.12.10 x64, NTFS flags `65482495`.
**Rollback:** revert the isolated Unit 2 source/workflow/test commit; no owner
store, SQLite schema, history caller or production gate is changed.

## Files and interfaces

- Extend `agents/core/checkpoint_windows_fs.py` only for create-new
  handle-relative directory/file opens with an explicit protected owner DACL,
  current SID capture, and verified private handle return. Keep the existing
  read facade, Unicode, reparse, identity and ownership fences.
- Add `agents/core/checkpoint_windows_store.py` with an injectable native API
  and `WindowsPrivateStore.open_or_create(parent, name) -> StoreHandle`,
  `WindowsPrivateStore.locked(store) -> context-managed StoreLease`, and
  `StoreLease.verify_named_child(name, held, *, directory) -> WinStamp`.
  `StoreLease` owns the store and lock handles through entry/post-lock checks,
  thread-local reentry and `LockFileEx`/`UnlockFileEx`. The SQLite probe may use
  the lease but is not a production history connection adapter.
- Add `tests/test_h011_windows_store.py` for injected fake/error cases and
  disposable native NTFS/process/SQLite cases. Update
  `.github/workflows/h011-windows-native.yml` to Ruff-check both modules and
  tests, run both native files, and require all collected Windows cases with
  zero skips/errors/failures in JUnit. Preserve its permissions, pinned actions,
  Python 3.12 locks and bounded job timeout.
- Do not edit `file_checkpoint_history.py`, `checkpoint_inventory.py`,
  `checkpoint_maintenance.py`, `file_tools.py`, schema, `BACKLOG.md`, generic
  SnapshotStore, product gate or effect/GC code in this unit.

## Implementation order and acceptance

1. **Private creation.** Write failing fake tests for exclusive anchored
   creation, descriptor/owner propagation, wrong owner, inherited/Everyone ACE,
   reparse, wrong volume, same-name substitution and close failure. Implement
   a create-new native call relative to a held parent; pass the explicit security
   descriptor at creation, never after a broad create. Verify the returned
   handle's name, full ID, type, ACL and parent/mount before trusting it. Run
   native tests on fresh NTFS paths, including existing generic-store refusal.
2. **Lease and lock.** Write fake RED cases for post-lock store/lock identity,
   same-thread reentry and changed-ID refusal. Implement a one-byte exclusive
   `LockFileEx` lease with explicit handle and overlapped lifetime. Native
   two-process tests prove contention, ordinary release, killed-holder release,
   and store/lock substitution at entry and post-lock fences. Preserve
   unverified handle ownership on cleanup failure.
3. **SQLite spike.** Add bounded test-only synthetic tables and an outside
   sentinel. Under the lease, first-create the DB exclusively, recheck its
   regular identity and ACL, then use ordinary `sqlite3.connect(path)` for
   create/reopen/read-only URI, `synchronous=FULL`, claim commit, exact selected
   rows and `BEGIN IMMEDIATE` guard. Prove the `DELETE` rollback-journal mode,
   sidecar location and effective restricted inherited ACL; refuse unsafe
   reparses, hard links or broad access while admitting ordinary private hot
   journals for recovery. Probe clean reopen, rollback and crash/restart with
   a durable non-replayable `running` claim. Use deterministic barriers at
   precheck/connect/claim/guard for store/DB/sidecar swaps; assert outside
   sentinel bytes unchanged and classify each refusal or uncertainty. If an
   uncontained native result appears, stop and report its exact boundary for a
   separately reviewed stronger connection mechanism.
4. **Verify and publish for native proof.** Run focused fake/error tests and
   adjacent Unit 1/H011/CLI tests on local Python 3.12, Ruff, syntax, workflow
   parse and diff check. Record Mac native skips honestly. Root reviews the
   candidate before publication; the PR Windows job must execute both files
   with zero skips/errors/failures and log build, NTFS flags, identities, ACLs,
   journal mode, rows, crash barriers and sentinel outcomes. Do not start later
   Windows units or enable `HISTORY_SUPPORTED` from a local fake pass.

**POSIX fidelity:** `file_checkpoint_history._locked` holds a directory/lock
identity and `flock`; `_connection` uses pathname `sqlite3.connect` with FULL
synchronous. `checkpoint_maintenance.apply` commits `running` separately,
deletes exact selected rows under `BEGIN IMMEDIATE`, then holds another immediate
guard through owned asset effects and treats post-claim failure as uncertain.
`checkpoint_inventory._read_index` opens read-only by path after a no-follow
regular-file check. These are the comparison points, not a claim that POSIX
pins SQLite connection or sidecar IDs.
