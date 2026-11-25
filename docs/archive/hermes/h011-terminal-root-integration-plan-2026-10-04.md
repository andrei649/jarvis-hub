# H011 terminal integration

Generated: 2026-10-04. Goal: connect bounded local terminal pre/post checkpoints
to the existing governed dispatch and exact queue provenance. Base/head before
integration: `57d00f50`; commands/orchestrator/web preappend work remains separate.

Owned paths: `agents/core/file_checkpoint_history.py`,
`agents/core/environments/{execution,local_transport}.py`,
`agents/core/autonomy_coordinator.py`, the three prototype group tests and a new
root boundary test. Dependencies: existing SnapshotStore, exact-birth queue
observer, terminal target/request/kernel/physical consent fences.

Derived metadata path: `agents/core/orchestrator_bindings.py`. The existing
binding-inventory gate failed after the coordinator insertion moved fourteen
unchanged writers by 21 lines. Refresh only verified callsite line numbers;
attribute identities, protocol and writer counts must remain identical.

1. Demonstrate a real governed synthetic spawn has no pre/post checkpoint on
   the baseline, without relying on a missing new import or constructor keyword.
2. Verify immutable package hashes and baseline source bytes; apply the original
   terminal group patch followed by its cancellation/private-storage/birth fix.
3. Connect the coordinator using an exact current queue task birth and canonical
   UUID origin. Reobserve after capture; no public request provenance or new grant.
4. Verify actual file changes, stale birth/origin zero-spawn, owner/consent CAS
   order, cancellation, restoration, shared retention and adjacent terminal paths.
5. Record root results and source freshness at a coherent frozen milestone.

Non-goals for this unit: public restore authority, Docker/SSH host snapshots,
arbitrary scripts or outside-cwd effects, live terminal/provider actions, remote
publication, and an H011 equivalent verdict. Owner UX and approved effect journal
remain required for full H011. Rollback removes only hooks/group methods and
provenance binding; retain inert recovery blobs and existing file history.

Ruling: use bounded ISO `Task.created_at` as birth, and normalize queue UUID hex
to dashed v4 only inside the trusted coordinator callback. The callback provides
group provenance; existing dispatch checks alone provide execution authority.

Root review finding: cancellation caught during child execution could still
wait indefinitely for the following postscan. A separate regression failed with
the corrected prototype. Observe postscan for the same bounded interval when
cancellation is already pending; preserve the background finalizer and original
cancellation. This is additional to cancellation arriving during a postscan.

Integration boundary: the actual producer/worker/coordinator test uses the
existing synthetic GRANT authorizer and synthetic process. Attempting the same
manual local task with the actual kernel currently returns `kernel_queued`;
the Docker manual receipt path is distinct. Preserve that refusal in this unit.
Extending the approved local/SSH manual kernel path requires its own authority
and physical dispatch review; this unit must not claim that live flow complete.
