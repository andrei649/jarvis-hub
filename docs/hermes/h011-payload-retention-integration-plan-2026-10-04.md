# H011 owned payloads and maintenance parity

Generated 2026-10-04; base/source `da88a139`. Previous goal turn made progress:
five local commits, prepared49 mutation closure, verified complete backend
23,086 passed /34 ordinary skips /one existing xfail and all serial clients.
The checkout is clean at start. Goal remains all697 pinned Hermes capabilities.
No push, merge, deployment, real user-file operation or live provider activation.

Pinned requirements: Hermes checkpoint status/project sizes, project-wide
retention (default seven days), exact approved orphan selection, oldest-history
size trimming (default500 MiB, keep a latest usable point per remaining project),
physical GC, clear and identified legacy cleanup. Namespace/accounting must land
before claiming physical reclamation; index-only deletion is not full clear.

Ruling: use a distinct `checkpoint_payloads-v1` child of the existing private
SnapshotStore. Keep index, operation journals and lock outside payload clear.
Ordinary FileTools preimages and returned generic undo refs remain unchanged.
After authorization, `apply_mutation` imports the verified preimage into the
owned namespace under the history lock. New terminal-group captures, postimages
and restore undo records use owned payloads. Existing history reads retain a
bounded legacy fallback only when the owned record/blob is absent, never when
it is present but invalid. Generic payloads are never reclaimed by this lane.

1. Implement owner-private no-follow bounded owned capture/load/blob storage,
   with an identified format and atomic/fsynced writes; prove symlink/hardlink,
   tampering, missing versus corrupt fallback, and concurrent-lock behavior.
2. Integrate owned writes and compatible reads in FileCheckpointHistory.
   Preserve all generic FileTools undo behavior and legacy history fixtures.
3. Build a bounded complete ownership/reachability view from every surviving
   file/group/pre/undo/post reference, including incomplete history. Approved
   maintenance refuses uncertain reachability; it never guesses that an
   unindexed capture is orphaned. Group capture has a durable capturing row;
   file preimage import occurs only inside the indexed effect transaction.
4. Add project-last-touch, deduplicated physical accounting and a pure policy
   planner. Stale projects may lose their whole history; size-only pruning
   retains a latest usable point per remaining root. Predict over actual
   uniquely reclaimable owned assets, preserve shared assets and expose a cap
   that cannot be met. Generic/shared legacy bytes are separately reported.
5. Bind policy inputs, complete ordered index candidates and exact payload GC
   plan into durable approval intent/generation. Preserve always-human tier3
   maintenance, worker/task/kernel/session/config guards and at-most-once journal.
   Commit index removal before GC with a durable intermediate state; recheck
   current reachability, namespace identity and literal live authority before
   each unlink. Interrupted or partial reclaim never auto-replays as success.
6. Wire retention/size/keep-orphans CLI and reserved chat options through the
   existing preappend path. Complete status/prune/clear acceptance uses actual
   owner→signed queue→worker/kernel→synthetic files and measured space reduction.
   Defaults/changed plans must refuse stale outstanding approvals.
7. Run meaningful RED/GREEN at each implementation step, then affected integration
   and static/record gates. Freeze a larger finished batch before costly full
   suites. Keep H011 partial until its remaining client/Windows/native scope
   and other accepted requirements are proved; continue all697 thereafter.

Likely paths: agents/core/checkpoint_payloads.py (new), file_checkpoint_history.py,
checkpoint_inventory.py, checkpoint_maintenance.py, checkpoint_controller.py,
checkpoint_commands.py, agents/cli/nerva.py, their focused tests and Hermes records.
Root is the only authoritative writer. At most two Sol High implementers may
prepare separately owned external prototypes; they cannot modify this checkout
or delegate. Namespace primitive and pure policy planner are independent.

Rollback reverses source integration, retaining existing/new payloads and journals.
The previous reader cannot use new owned-only history after rollback: disclose
that limitation and retain a compatible reader or export before downgrade.
Absent a recognized legacy archive format, clear-legacy must stay an explicit
no-op; arbitrary old generic snapshots must not be relabeled as disposable.

## Progress and owner steering

2026-10-04: steps1–2 now pass604 cases across31 affected modules, with Ruff
and production Bandit passing. No physical GC is enabled; steps3–6 remain.
The prepared pure retention patch remains external, not a product feature.
The owner explicitly requests copying/adapting Hermes to avoid unnecessary
reimplementation. H388 has a separately prepared upstream-based adapter; root
will wire actual runtime facts and tests before claiming delivery. Rechecked
the original H011 row: it asks for CLI status/list/prune/clear/clear-legacy,
per-project sizes/orphan GC and rollback. Dedicated native HUD/mobile controls
and reversal of arbitrary network/process effects are not added closure criteria.
Windows support and actual durable cleanup still remain genuine gaps.
