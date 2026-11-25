# H277 smart-promotion audit identity

Generated 2026-10-04. Goal: complete local parity with all 697 pinned Hermes
capabilities. Base/head before this unit: `6b9422ed`. This record preserves the
coordinator's earlier delegated specification; it does not imply that the plan
was first agreed after implementation.

## Requirement and boundary

The original H277 build contract requires the actual judge identity in the
action audit. Once the explicit Smart mode allows a judge to approve one exact
terminal operation, its promotion event must identify the committed provider,
model and local/cloud flag. An `active` alias must resolve to the model used for
that judgement, even if the loaded model changes before auditing.

Keep the existing signed execution receipt, queue CAS, policy and physical
dispatch verification unchanged. Invalid or mismatched receipts cannot justify
inventing a model identity. Preserve the existing generic audit event in that
case. No providers, services or real terminal effects are activated.

## Implementation and checks

1. Add real queue/worker/IntentLog regression coverage in
   `tests/test_h277_smart_promotion_audit.py`: configured and active-model
   identities, a loaded-model change after commit, invalid signature and
   mismatched observation. The implementer reported two initial assertion
   failures for missing judge metadata before the adapter fix.
2. Change only `agents/core/autonomy/task_approval_judge.py`: attribute the
   promotion through `verify_smart_terminal_approval` and exact matching of the
   committed snapshot, judgement revision, policy revision, time and identity.
   Add that identity to the existing signed audit sink. Preserve generic fallback.
3. Coordinator verification: the two new modules and existing task-judge,
   smart-queue and smart-terminal integration modules pass 121 cases, including
   all four new audit cases. Record the actual XML and current source hashes in
   the accompanying evidence. Broader H277/H485/H487 and frozen full backend
   verification are subsequent gates, not implied by the focused result.

Single writer for implementation: `native_wait_runtime`, Sol High, no child
delegation. The coordinator owns integration and records. Independent read-only
review used Luna Medium; no reproducible substantive flaw was found in the
specified integrated diff. This is narrow source review, not all-H277 acceptance.

## Delivery and rollback

Keep the adapter, its test and this unit's evidence independently revertible
from H487 inline outcomes. The full H277 row remains partial: provider/video
routing and wider accepted auxiliary/provider dependencies are still open.
Integrated verification passed 2,989 cases across 134 modules; the frozen
backend run completed with 22,360 passes, 34 ordinary skips, one existing xfail
and zero failures/errors. All 2,994 selected input hashes remained unchanged.
Three separate audit mutations produced assertion failures, with successful
before/after baselines and complete restoration. Next action: verify final
records and selected-index scan, then commit this unit locally. No push, merge,
deployment or paid-provider use.
