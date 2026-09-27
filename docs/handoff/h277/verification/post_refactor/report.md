# H277 bounded post-refactor mutation verification

Executed 2026-09-27, local only, after the coordinator ended the full backend milestone and gave an explicit test-go signal. Original round2 evidence remains untouched in the parent directory.

**Results: 14 killed, 0 survived, 0 superseded/equivalent, 0 invalid.**

Scope: 10 existing mutations remapped to the shared runner/action adapter plus 4 shared-capacity mutations. Provider, role, prompt, verdict-parser and HUD mutations were not repeated. Source mutation ran only in a new non-Git disposable snapshot, one process at a time, restoring each file in finally.

## Source provenance

- Git HEAD: `bd2bb70ead1b493043a335e77713fc42c47d4013`.
- Prepared snapshot fingerprint: `6434719f47633fe78894e4d59ad81bdf9e0794b32dbc973cf8fd7a7bdbc0b9ea`.
- Initial execution fingerprint after four-file coordinator overlay: `bb5d80e859e08116e97b2c28f037c429ffc032f2cd691afe6408367d038a9d6b`.
- Final restored snapshot fingerprint: `ff4dc245ff787c8db15c3afac315c17b4b736a179859fb6ff6f1b2edb06e107a`.
- [source_manifest_pre_overlay.json](source_manifest_pre_overlay.json) preserves the prepared version; [overlay_manifest.json](overlay_manifest.json) records original/new hashes for approval_judge.py, model_roles.py, test_h277_approval_judge.py and test_h277_model_roles.py.
- [source_manifest.json](source_manifest.json) records hashes for every copied tracked file and required new untracked file, deleted paths, dirty overlay, and temporary snapshot path. The fingerprint hashes sorted JSON containing files/path-SHA256 pairs and deleted paths.
- Required new untracked files included: advisory_judgements.py, task_approval_judge.py, and test_h277_task_judge.py. Other untracked docs/generated frontend bundles are outside this bounded backend verification.

## Executed baseline and restoration

- **199 passed** in the action+task H277 baseline, with normal project pytest addopts, timeout and socket controls: [exact command/output](logs/baseline.log). Python is the existing repository .venv/bin/python3.12. No dependency installation, paid provider or live model call.
- [anchor_checks.json](anchor_checks.json) shows all 14 anchors match once and all modified Python files parse. Unmatched anchors, invalid syntax, collection/import/setup errors and tool failures are not counted as killed.
- Restoration passed for all **3716 copied file hashes** and **11 deleted paths**: [exact evidence](restoration.json).

## Cases

| Case | Source | Result | Exact evidence |
|---|---|---|---|
| queue_snapshot_is_stored_item | agents/core/autonomy/advisory_judgements.py | killed | [log](logs/queue_snapshot_is_stored_item.log) |
| queue_judge_inherits_caller_context | agents/core/autonomy/advisory_judgements.py | killed | [log](logs/queue_judge_inherits_caller_context.log) |
| queue_short_lived_loop_not_judged_on_hub | agents/core/autonomy/advisory_judgements.py | killed | [log](logs/queue_short_lived_loop_not_judged_on_hub.log) |
| N1_post_slot_status_stale | agents/core/autonomy/advisory_judgements.py | killed | [log](logs/N1_post_slot_status_stale.log) |
| N1_post_slot_wants_dropped | agents/core/autonomy/advisory_judgements.py | killed | [log](logs/N1_post_slot_wants_dropped.log) |
| N1_skip_revoked_counter_dropped | agents/core/autonomy/advisory_judgements.py | killed | [log](logs/N1_skip_revoked_counter_dropped.log) |
| N2_finish_pending_not_cleared | agents/core/autonomy/advisory_judgements.py | killed | [log](logs/N2_finish_pending_not_cleared.log) |
| N1_disk_pending_recheck_dropped | agents/core/autonomy/action_approvals.py | killed | [log](logs/N1_disk_pending_recheck_dropped.log) |
| N1_memory_pending_recheck_dropped | agents/core/autonomy/action_approvals.py | killed | [log](logs/N1_memory_pending_recheck_dropped.log) |
| N2_capacity_released_on_decide | agents/core/autonomy/action_approvals.py | killed | [log](logs/N2_capacity_released_on_decide.log) |
| shared_pending_limit_dropped | agents/core/autonomy/advisory_judgements.py | killed | [log](logs/shared_pending_limit_dropped.log) |
| shared_concurrency_limit_raised | agents/core/autonomy/advisory_judgements.py | killed | [log](logs/shared_concurrency_limit_raised.log) |
| shared_external_capacity_ignored | agents/core/autonomy/advisory_judgements.py | killed | [log](logs/shared_external_capacity_ignored.log) |
| shared_capacity_release_dropped | agents/core/autonomy/advisory_judgements.py | killed | [log](logs/recheck_shared_capacity_release_dropped.log) |

Initial bounded result: **13 killed / 1 survived**. The coordinator strengthened the task/action shared-capacity test to submit a new task and action after the original 32 judgments drained, require 34 total backend calls, and require both new opinions. Only tests/test_h277_task_judge.py was overlaid. The unchanged production release logic passes; removing release now fails this public reuse regression.
- Follow-up baseline: **199 passed**; [exact command/output](logs/capacity_reuse_baseline.log).

## Follow-up regression rechecks

The initial survivor evidence is retained in initial_results.json. Only coordinator-authorized test overlays were applied for the following baseline/mutant reruns; followup_overlay_manifest.json records their hashes and final source fingerprint.

- shared_capacity_release_dropped: killed; [log](logs/recheck_shared_capacity_release_dropped.log).

## Reproduction and limits

```sh
.venv/bin/python3.12 docs/handoff/h277/verification/post_refactor/run_bounded.py prepare
# Run only after the coordinator test-go milestone:
.venv/bin/python3.12 docs/handoff/h277/verification/post_refactor/run_bounded.py run
# After coordinator-authorized capacity-reuse test is ready:
.venv/bin/python3.12 docs/handoff/h277/verification/post_refactor/recheck_capacity.py
.venv/bin/python3.12 docs/handoff/h277/verification/post_refactor/build_report.py
```

prepare refuses to overwrite an existing prepared manifest. These exact results require the recorded snapshot and four-file overlay; a new current working-tree snapshot may differ. No production source/test edits, service changes, commits or pushes were made by the verifier.

This report covers selected shared scheduling/capacity/revocation behaviors. It does not verify every new task-adapter rule, all provider/role paths, the full backend suite, generated frontend bundles, separate frontend application, real network/provider behavior, or broader H277 completion. Original round2 results and this bounded pass must retain their distinct source fingerprints.
