# Next local unit: child completion, separately governed parent resume, crash reconciliation

Goal remains all original 697 Hermes capabilities plus complete H277 handoff. This is a next implementation unit, not a reduced completion definition.

Authoritative workspace: /Users/andrei649/Projects/nerva-pr-worktrees/consent
HEAD: a7ffad6676cfb28e7ac374d495b4a5889e5f4646; preserve inherited dirty changes. No push, merge, deploy, paid calls or live model activation.

Full backend milestone is terminal (2026-10-04T22:31:00Z): 23,532 passed, 34 skipped, one existing xfail, zero failures/errors; all 4,200 inputs unchanged at that milestone. That proof predates this implementation. The preceding proof is archived in docs/hermes/evidence/2026-10-05-kanban-child-milestone/. The following observed contracts and proposed steps preserve the original pre-implementation plan; the current checkpoint is recorded below.

Observed contracts:
- ChildToolAdapter.execute independently consumes the child permit, opens a fresh scoped cwd, and durably settles child success/failure. The parent task remains blocked/needs_input.
- KanbanDispatcher._dispatch_locked currently considers ready/review tasks only. It already provides signed worker proposals, durable queue-birth recovery, capacity guards, and snapshot/CAS claim.
- dispatch_store.prepare records the full current task/parents/comments/attachments/workspace input snapshot and a bounded worker prompt. claim atomically validates that input and opens one run.
- kanban_db._claim_and_open_run accepts a source lane, but bypassing arbitrary needs_input blockers would be incorrect. A blocked-lane resume must be gated by a successful exact child and a newly approved worker proposal.
- Worker queue boot/tick uses its stuck-running reaper. An observation timeout, an age threshold alone or an old PID cannot establish that an effect did not happen.
- Existing child states prepared/queued/executing/succeeded/failed have no persisted resume reference, recorded result, orphan-abort API or reconciliation scan. prepared/queued/executing keep workspace cleanup blocked.

Proposed bounded implementation after freeze:
1. Add durable one-to-one resume binding in the Kanban module. Reuse existing kanban.worker classification and ask-policy; do not create approval, reuse a parent/child permit or broaden ordinary blocked-lane claiming.
2. Propose resume only when exact child success AND authenticated durable child queue completion agree; exact parent source run is latest and blocked for this child; source dispatch finished; profile/project/board/owner roots/cwd inode are unchanged. Preserve source review/ready phase and parent-dependency checks.
3. Prepare a fresh signed snapshot/worker prompt containing bounded child outcome with an explicit untrusted-result boundary. Decide session continuation explicitly: new governed run/session currently uses kanban::new_submission, so do not claim exact conversation restoration merely from board context.
4. A new independent worker approval plus consumed permit is required to atomically claim the parked parent. Link exact child/result/resume submission in the signed payload and validate again at claim. Never treat unrelated needs_input tasks as resumable. Use durable unique binding and recover queue birth before considering a new enqueue.
5. Reconciliation must distinguish prepared without queue, born-but-unbound queue, queued terminal denial/expiry, executing interrupted, succeeded-before-queue-DONE, and already-proposed resume. Abort confirmed nonexecuting orphan intent; retain blocked parent. Do not replay an ambiguous physical effect or infer success from absence of an error.
6. Test actual production coordinator + queue + worker + registered file/terminal consumers with synthetic boards and one harmless local process. Preserve legacy fixtures and no implicit feature activation.

Meaningful tests to write before implementation:
- Approved file write/delete/local terminal -> durable child success -> exactly one blocked fresh worker resume proposal -> no resumed model call before separate approval -> exactly one new run after approval.
- Repeat tick and process reopen recover same submission/queue without duplicate run or physical child replay.
- Queue-birth/bind crash, bind rollback, owner rejection, approval expiry, disabled kernel/runtime, parent run replacement, board/project/root/cwd/assignee drift and signed child-result mismatch refuse resume.
- A manually blocked task or a failed child never auto-unblocks; review resumes its correct phase and unsatisfied parents prevent claim.
- Child physical success followed by ambiguous queue finalization requires explicit reconciliation and never blind retry.
- Confirm orphan settlement frees only the active-child guard; it does not delete user-owned paths or remove a still-blocked workspace.
- Existing permit-floor, checkpoint-revocation, cleanup, owner CLI/project and H277 security tests remain green.

Rollback: revert only this unit's localized diff after inspection; retain all current dirty integration.
Next action: write failing actual-coordinator resume/recovery regressions, implement localized Kanban changes, run each scoped RED/GREEN step, then dependent gates and a new serial frozen full milestone. Keep original697 and H277 acceptance open.

H277 acceptance freshness audit (read-only during freeze): /tmp/nerva-h277-current-child-drift-20261005.json compares all 993 original49 manifest inputs; 21 changed/missing current inputs, including shared queue/coordinator/file/checkpoint/ToolRPC and rebuilt HUD assets. Preserve archived proof, explicitly date it, and rerun original49 after this next coherent integration unit. This audit does not indicate mutant survivors or a current defect by itself.

Generation time: 2026-10-04T22:32:07Z
Likely changed paths: agents/core/kanban/child_store.py, agents/core/kanban/child_tools.py, agents/core/kanban/dispatch_store.py, agents/core/kanban/dispatcher.py; coordinator only for exact recovery intake boundaries; new tests/test_hermes_kanban_child_resume.py and recovery tests, plus truthful docs/hermes records. No unrelated module rewrites.

## Implemented local checkpoint

- Added a durable unique child-to-resume submission binding in `child_resume.py`. A successful child, its authenticated DONE queue result, the exact latest parked source run and unchanged workspace are required. A new signed `kanban.worker` proposal waits for independent owner approval; claim revalidates the descriptor and opens one fresh run/session. This is not restoration of the previous conversation.
- Root RED initially had three missing resume proposals. Diagnostics traced the refusal to a physical child kernel decision left in the intake bridge. The dispatcher now authorizes the exact finalized typed worker action before enqueue, matching the existing coordinator producer pattern. The kernel mismatch guard remains unchanged. Dispatcher fixtures now use the production one-shot bridge binding.
- Added conservative `child_store.reconcile` and wired it into the trusted dispatcher scope. Exact queue-birth lookup uses a new submission identity marker. Rejected/expired/nonexecuting or terminal ambiguous children settle without unblocking the parent, deleting cwd, inferring physical success or replaying an effect. Legacy prepared rows without the marker remain held.
- Fresh scoped integration: **815 passed, zero failures/errors/skips**, `/tmp/nerva-child-resume-recovery-integration-20261005.xml`. This includes all `test_hermes_kanban*.py`, registered file coordinator intake, mediation evidence/head, H277 judge/smart suites and owner-once kernel tests. The focused child/dispatcher/store/recovery set is **60/60** and is contained in that larger run, not an additional total.
- Actual coordinator tests cover write/delete/harmless local terminal completion, a separate resume approval, process reopen/deduplication, no physical replay, rejected-child reconciliation, and refusal after board/cwd/assignee/dependency changes while approval waits. Ruff and scoped Bandit pass. Derived Hermes reports are regenerated without new equivalence credit: **124/697, 17.8%, exclusions zero**.

Remaining acceptance: expand remaining crash/rollback/source-result/phase edge cases; run a new coherent frozen full backend milestone and original H277 49-case mutation campaign serially. Previous full backend/HUD/mutation proofs remain dated historical evidence. No current-source full-suite or live-provider acceptance is claimed. Changes remain local and uncommitted.

## Boundary and mutation follow-up

Nine real-flow boundary cases now verify owner rejection/actual queue expiry without replacement approvals; roots, latest source run, stored child-result and runtime changes before claim; claim-transaction rollback of both the new run and resume mapping; born-but-unbound queue recovery; and preservation of source review phase. The combined final affected run passes **916 cases**, zero failures/errors/skips (`/tmp/nerva-kanban-resume-final-affected-20261005.xml`); this includes the prior overlapping scoped sets and status/document gates. Actual backend collection is **23,592**; frontend1,912/mobile185 counts remain their existing snapshots.

The [current original49 handoff rerun](../handoff/h277/prepared49-resume-current-2026-10-05/REPORT.md) is now terminal:43 assertion and6 behavior-exception detections,360 Python and40 HUD baseline/restored checks,997 inputs restored after every case,zero source/snapshot drift and strict default-rule secret scan clean. There are no new mutation survivors or setup failures. This satisfies the original49 mutation requirement for this local dirty source scope; it does not close full H277 functional parity.

Next action: a new frozen full backend milestone, independent verification of unchanged frontend/mobile evidence, and semantic review of the relevant partial records. Preserve all original697 scope and outstanding live/native/provider requirements; no publication.

## Terminal full milestone

The [new full evidence](evidence/2026-10-05-kanban-resume-full/README.md) verifies the current code/test snapshot: **23,592 backend cases;23,557 passed,34 ordinary skips,one existing xfail,zero failures/errors**, then serial full frontend **1,912/1,912 passed**. All **4,684** frozen regular source/test/metadata inputs match at backend terminal and again after frontend. Parameterized XML names are sanitized; exact raw local and derivative hashes are preserved. Strict default-rule scanning passes without documentation exemptions.

Mobile185 remains the previous tracked snapshot; its source is unchanged but no fresh mobile suite or native-device acceptance was run here. H075/H581/H277 remain partial. Original49 mutation verification and the backend/frontend full suites are now complete for this milestone; additional functional/provider/native requirements and all original697 remain open. Next implementation selection is H099 inbound ntfy parity, using the pinned reference and Nerva's existing gateway/pairing/reply boundaries.
