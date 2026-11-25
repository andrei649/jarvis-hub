# H011 owner selection and approved effects

Generated 2026-10-04; base/head `38a14d46`. Prior turn made authoritative
progress in `6abf999f` and `38a14d46`; checkout is clean at task start. Goal remains
complete local parity across all 697 pinned Hermes capabilities. No publication.

Dependencies: immutable external selection package `24ca7abd` and durable
operation package `6991dc11`; root reviews and tests their exact bytes. Neither
IDs, previews nor journal claims confer authority.

1. Integrate readonly typed/ordinal checkpoint selection, bounded diff and force
   fingerprints. Expose `/checkpoints diff ID`, `/checkpoints restore ID` and
   `/rollback ID` through the existing preappend ADMIN command path; previews
   are the default. Add CLI diff/restore verbs using the same notice contract.
2. Persist exact restore/maintenance intent, stable ID, configured roots,
   indexed signature, force/current state and session identity/clock/tail before
   queuing an always-ask human task. Task binding must be unique and immutable.
3. Register exact `checkpoint.restore` / `checkpoint.maintenance` action kinds,
   manifest/rollback metadata and real kernel-halt tests. Restore is reversible
   only while pre-undo is preserved; instruction-sensitive paths and maintenance
   retain tier three. Do not relax global OFF/ASK, taint, budget or halt floors.
4. The actual worker/executor requires the exact signed current durable human
   decision. Recheck current worker/queue identity, action/payload, configured
   root and session before claiming once and before every physical effect.
   Maintenance's final check must use the pure predicate, not consume a second
   worker execution permit. A request ID or accepted task ID alone is insufficient.
5. Hold the original session turn lease during execution; reprepare and compare
   the exact accepted tail before restoring. Only complete filesystem success
   may commit the current-last-user rewind. Partial, uncertain, stale or failed
   persistence outcomes retain undo/audit and never claim a completed rollback.
6. Test real producer → signed queue → human decision → worker/executor → kernel
   → synthetic filesystem and conversation persistence. Verify late revocation,
   approval edits, stale preview/tail/root, restart replay and denied floors.
   Run affected/source/security gates; freeze before the costly full milestone.

Root owns commands/controller/coordinator/kernel/records and this checkout.
Independent agents may implement only explicitly assigned external files.
Rollback reverts integration code, preserving journals, snapshots and audit.
Shared generic blobs remain retained until checkpoint-owned cleanup is proven.
Owner previews/operations are not native-client or live-provider acceptance.

Execution record (2026-10-04T08:38:13Z): steps 1–5 are integrated through the
actual owner command, signed enforce-mode task, worker/executor and kernel.
The real CLI → web → preappend registry → queued human decision → worker →
synthetic filesystem/current-last-user rewind regression passes. The final
93-module affected run has 2,273 passed, 3 optional skips, no failures/errors.
Whole-repository Ruff and agents/scripts Bandit pass. Full frozen suites are next.

Rulings: store the full exact intent in the dedicated journal, but give the
bounded signed queue a shallow human preview; deeply nested group plans exceed
its existing canonical envelope. Exclude only the operation journal and its
SQLite sidecars from maintenance preview generations, because its own durable
prepare/claim must not expire the approved checkpoint inventory. The byte/status
inventory still includes those files. Physical session checks read existing SQL
identity/clock rows without clock seeding and bind the original memory manager;
rewiring revokes effects and cleanup discards the original unused ticket.

H011 remains partial: dedicated native/HUD controls, retention/size controls,
complete checkpoint-owned payload cleanup and Windows capture/restore remain
open. Generic shared records/blobs are preserved. No publication or live effects.
