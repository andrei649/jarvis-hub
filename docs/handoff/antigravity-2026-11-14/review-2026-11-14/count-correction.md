# PR #1365 generated-count correction and integration review

Goal: repair generated backend-count drift from authentic CI evidence, preserving application source and prior work. Base/head: detached `e39d9b659cb740a5ec14a50ff607803c6927b102`. Integration comparison: main `a5dc55f` after #1360. Freshness: 2026-11-14 UTC. Scope: five generated status files plus this report/evidence; no publication, commit, merge, deployment, dependency install, or live service operation.

## Count correction prepared

Authentic connector-fetched [CI job 132452588220](https://github.com/andrei649/jarvis-hub/actions/runs/43596686135/job/132452588220) records checkout merge `5a8d563beb4bd2b47c480701eff3661e1583ead5`, combining exact head `e39d9b659cb740a5ec14a50ff607803c6927b102` with base `1338833d5a344d277c43828a9d9314e10af792f1`. At `2026-11-14T13:18:44.6357252Z`, the canonical verifier emitted `backend test count: 36700 (tracked 36699)`. All 23 Hermes area suites passed. 36,700 is the reported JUnit aggregate, including skipped entries; it is not a claim that all 36,700 tests passed.

The correction parses the actual count from that authentic verifier stdout, then uses unmodified `scripts.status_sync` APIs `build_project_status`, `_expected_docs`, `generated_drift`, and `_write_generated_status`. No synthetic JUnit, test filtering, fabricated result, or manual counter increment was used. Original verified-main stamp `1338833d...` is preserved, matching the observed CI base. Frontend 3,188/mobile 420 are explicitly reused tracked counts, not fresh suite claims.

Final diff: `project-status.json`, `README.md`, `NERVA.md`, `GO_LIVE_PLAN.md`, `STATUS.md`: only 36,699 → 36,700, seven lines replaced. `generated-status.patch` contains those five files only. `review-1365-count-evidence.json` preserves source and output hashes.

## Verification and environment difference

Executed with actual project Python `/workspace/jarvis-hub/.venv/bin/python`:

- `scripts/status_sync.py --reuse-js-counts --json`: successful fresh local backend collection, **36,709**. This initial local result was retained as evidence, then replaced with authentic CI-derived generation. It must not be represented as the CI count.
- `scripts/status_sync.py --check --reuse-test-counts --json`: **in_sync** after final measured-CI generation; backend36,700/frontend3,188/mobile420.
- `-m pytest tests/test_status_sync.py -q`: passed. No full application execution suite rerun.
- `-m pytest tests/test_h070_discord_media.py --collect-only -q -p no:xdist -o addopts=`: exactly10 tests collected locally.
- `git diff --check`: passed.

Likely explanation for the nine-entry local/CI difference: Discord SDK exists in the local environment, but is absent from both CI lockfiles. `tests/test_h070_discord_media.py:12` uses module-level `pytest.importorskip("discord")` and has10 tests: a missing optional module can contribute one JUnit collection-skip instead of10 runnable tests. This is a source-backed inference, not a newly reproduced CI environment. Default live-collection generation can therefore differ from the executed-run JUnit aggregate. No test guards, environments, dependencies, or generator source were changed to force a desired number.

Evidence files are adjacent in `/workspace/scratch/pr-consolidation-20261114/`: `fix-1365-ci-count-excerpt.log`, `fix-1365-generation.log` (fresh local collection), `fix-1365-ci-generation.log` (actual-CI-source generation), `fix-1365-consistency.log`, `fix-1365-status-tests.log`, `fix-1365-merge-preview.log`.

## Remaining integration holds

1. **Current main has unresolved conflicts.** Read-only `git merge-tree --write-tree a5dc55f HEAD` reports seven conflicts: `GO_LIVE_PLAN.md`, `NERVA.md`, `README.md`, `STATUS.md`, `project-status.json`, `docs/INSTALL.md`, `tests/test_bootstrap_script.py`. The application bootstrap script itself auto-merges in that preview. These are an uncommitted merge simulation, not resolved integration. No application, test, or installation-document conflict was edited.
2. **Cumulative update/restart security boundary remains unreviewed.** The branch changes consequential lifecycle/authority source: `hub_update_apply.py` (+306/-30), `hub_restart_apply.py` (+318), `restart_runtime.py` (+205), `restart_command.py` (+59), `update_commands.py` (+218), plus kernel/autonomy integration paths. Existing `docs/handoff/antigravity-2026-11-14/INVENTORY-REVIEW.md` and `HANDOVER-VERIFICATION.md` explicitly identify the prior platform-blocked adversarial review as incomplete. This is a real unresolved review boundary for merging this cumulative application work, rather than a harmless archived note. No blocked review or reproduction was retried or circumvented; no new exploit or vulnerability is claimed. Green functional CI and the count correction do not certify that boundary.
3. This pass inventoried cumulative changed paths and reviewed relevant evidence/conflicts; it is not a complete independent application/security audit of the cumulative branch. The #1359 literal-script-output issue is addressed in this branch's adapter source via its private literal-job marker; that does not clear unrelated holds.

Recommendation: the five-file count patch is ready for coordinator review; **hold cumulative #1365 integration** until its conflicts and unresolved security-review boundary are addressed through an authorized safe path. Next action: coordinator reviews the patch/provenance and chooses disposition of the cumulative branch. Rollback for this correction is reversal of the five-file patch; application bytes were preserved.
