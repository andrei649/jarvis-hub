# Open-PR integration review — 2026-11-14

The owner explicitly requested review and merge into main. That authorizes this
integration pass and supersedes earlier draft-only restrictions. It does not
waive failing checks, data preservation or the previous platform-blocked review,
and does not authorize deployment or resumption of paused services.

Initial main: `1338833d5a344d277c43828a9d9314e10af792f1`.
Main after reviewed #1360 squash merge:
`a5dc55fbebe70c8359e50a63c5fe1ae7fc4af06d`.
This is a timestamped review snapshot; refresh GitHub before a further mutation.

## Disposition of all eleven original open PRs

| PR | Result of this pass | Remaining condition |
|---|---|---|
| #1359 | Closed as superseded by #1363; source branch retained | Its real-adapter literal `[SILENT]` regression is fixed in #1363. Not independently merged. |
| #1360 | **Merged into main**, squash `a5dc55f` | Review found no blocker; all mandatory checks passed before merge. |
| #1361 | Closed as superseded by #1363; source branch retained | Organization implementation/tests preserved in combined tree. Not independently merged. |
| #1362 | Closed as superseded by #1363; source branch retained | Transcript/UI/mobile implementation preserved; cancelled Windows checks are not treated as passes. |
| #1363 | Reviewed, main reconciled, marked ready; exact-head CI running | Every reported check, including Windows full tests, must pass before merge. |
| #1364 | Closed as superseded by #1365; source/history retained | Its head is an ancestor of #1365; no cumulative-source loss or merge claim. |
| #1365 | Draft; measured CI count corrected and published | Main conflicts and incomplete cumulative lifecycle/security review remain. |
| #1366 | Draft; concrete defects identified | Streaming callback compatibility, active-preset policy pin, and rollback journal. |
| #1367 | Draft; prior exact-source findings retained | Default sync persistence, stale-snapshot overwrite/data-loss semantics; failing CI and parent dependencies. |
| #1368 | Draft; prior exact-source findings retained | Callback/CLI/archive/inventory CI regressions; scanner failures; parent dependencies. |
| #1369 | Draft; specification package independently validated | Based on unmerged cumulative application code; do not retarget wholesale to main as though it were a main-based docs diff. |

Closing superseded PRs reduces duplicate integration paths. It does not claim their
features are already in main, and no source branch was deleted or force-pushed.
At this snapshot, one PR was merged, four were closed as superseded, and six remain
open. Five of the remaining six are still drafts.

## Combined gateway/bootstrap/session integration

Reviewed source #1363 `702845ae45765583f996fdb5b2b08de9db6664bc` contains the
earlier four feature PRs by reconciled content, not commit ancestry. Independent
review compared affected production/test files and ran **361 focused tests** on
the exact combined source. See [session integration](session-integration.md) and
[gateway/bootstrap review](gateway-bootstrap.md).

After #1360 merged, five generated-status conflicts were resolved by preserving
the already measured combined counts (35016/3009/396). The published merge commit
`024e1a58a745027186833b6b6e0a0dd57a42fe85` has parents `702845ae` and `a5dc55f`;
its entire tree is **byte-identical** to the previously reviewed source:
`9deba0f24220f9f0f89fee585f2a923e549cecc1`. No code or tests were removed to resolve
the conflicts. Canonical generated-status consistency passed.

The earlier Windows full-suite run was cancelled, not successful. It was retried,
then reconciliation triggered fresh full CI on the new head. Linux/Windows test
completion is pending in this snapshot. The PR is ready for the repository's
existing trusted green-check merge gate; no gate, workflow, label or schedule was
relaxed or activated. No GitHub auto-merge bypass or direct main push was used.

## Cumulative count correction and real blockers

#1365's authentic Ubuntu job records 36700 JUnit entries versus tracked36699. The
five status artifacts were regenerated from that measured result using canonical
APIs, reviewed and published as `b73a820a66e9b0897be8528bd0c537a9d072e959`. Only
the seven rendered occurrences of the backend count change. Application source
and checks are unchanged. See [count correction](count-correction.md) and
[provenance](count-evidence.json). Local collection reports36709 with an optional
Discord SDK installed; that environment-specific number was not substituted for
the actual CI result. The count includes skips and is not a pass total.

This does not clear #1365's seven main-merge conflicts or the documented incomplete
update/restart adversarial review. The prior platform-blocked reproduction was
not retried. Consequential lifecycle/kernel changes are still present; passing
functional CI alone is not evidence that this review boundary was completed.

For #1366, the [new bounded review](lot2.md) found:

- Cloud MoA aggregators receive an unsupported `on_activity` keyword and fail
  during streaming synthesis with the real Anthropic/Gemini adapter signatures.
- Partial libpython staging failure can lose the rollback journal and leave a
  live library missing or replaced. This finding comes from static control-flow
  inspection; no blocked fault-injection/update/restart operation was attempted.
- Editing an active MoA preset bypasses the model-selection pin used by activation
  and deletion. HTTP and offline CLI must agree at the mutation boundary.

For #1367 and #1368, the code heads are unchanged from the earlier
[published source review](../../../superpowers/plans/2026-11-14-small-model-backlog/evidence/REPORT.md).
Those findings and the 26 bounded task packets remain useful implementation
instructions. Do not equate zero recorded missing capabilities with completed
contracts, or fix failed checks with blanket allowlists/count fabrication.

## Next actions

1. Refresh #1363 head/base/checks. Merge only if the reviewed head still applies,
   GitHub reports a clean merge and all trusted mandatory/other checks pass.
2. Preserve the closed source branches until the combined paths are integrated.
3. Resolve #1365 conflicts without losing the bootstrap changes now in main; keep
   its security-review hold explicit and use only an authorized review route.
4. Fix and test the concrete #1366–#1368 defects before integrating their stack.
   Reconcile and retest combined output, not just each original PR independently.
5. Bring #1369's specifications with the reviewed application baseline. Its own
   eight planning-helper checks pass; inherited application CI is separate.

No deployment, release tag, dependency installation, network reconfiguration,
Windows checkout mutation or paused-service/scheduler activation occurred.
