#!/usr/bin/env python3
"""Render bounded shared-runner mutation evidence separately from round2 evidence."""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent


def main():
    d = json.loads((OUT / 'results.json').read_text())
    manifest = json.loads((OUT / 'source_manifest.json').read_text())
    overlay = json.loads((OUT / 'overlay_manifest.json').read_text())
    restoration = json.loads((OUT / 'restoration.json').read_text())
    counts = d['counts']
    lines = ['# H277 bounded post-refactor mutation verification', '',
             'Executed 2026-09-27, local only, after the coordinator ended the full backend milestone and gave an explicit test-go signal. Original round2 evidence remains untouched in the parent directory.', '',
             f"**Results: {counts['killed']} killed, {counts['survived']} survived, {counts['superseded']} superseded/equivalent, {counts['invalid']} invalid.**", '',
             'Scope: 10 existing mutations remapped to the shared runner/action adapter plus 4 shared-capacity mutations. Provider, role, prompt, verdict-parser and HUD mutations were not repeated. Source mutation ran only in a new non-Git disposable snapshot, one process at a time, restoring each file in finally.', '',
             '## Source provenance', '',
             f"- Git HEAD: `{manifest['head']}`.",
             f"- Prepared snapshot fingerprint: `{overlay['before_source_sha256']}`.",
             f"- Initial execution fingerprint after four-file coordinator overlay: `{overlay['after_source_sha256']}`.",
             f"- Final restored snapshot fingerprint: `{manifest['source_sha256']}`.",
             '- [source_manifest_pre_overlay.json](source_manifest_pre_overlay.json) preserves the prepared version; [overlay_manifest.json](overlay_manifest.json) records original/new hashes for approval_judge.py, model_roles.py, test_h277_approval_judge.py and test_h277_model_roles.py.',
             '- [source_manifest.json](source_manifest.json) records hashes for every copied tracked file and required new untracked file, deleted paths, dirty overlay, and temporary snapshot path. The fingerprint hashes sorted JSON containing files/path-SHA256 pairs and deleted paths.',
             '- Required new untracked files included: advisory_judgements.py, task_approval_judge.py, and test_h277_task_judge.py. Other untracked docs/generated frontend bundles are outside this bounded backend verification.', '',
             '## Executed baseline and restoration', '',
             '- **199 passed** in the action+task H277 baseline, with normal project pytest addopts, timeout and socket controls: [exact command/output](logs/baseline.log). Python is the existing repository .venv/bin/python3.12. No dependency installation, paid provider or live model call.',
             '- [anchor_checks.json](anchor_checks.json) shows all 14 anchors match once and all modified Python files parse. Unmatched anchors, invalid syntax, collection/import/setup errors and tool failures are not counted as killed.',
             f"- Restoration passed for all **{restoration['files_checked']} copied file hashes** and **{restoration['deleted_paths_checked']} deleted paths**: [exact evidence](restoration.json).", '',
             '## Cases', '', '| Case | Source | Result | Exact evidence |', '|---|---|---|---|']
    for r in d['results']:
        lines.append(f"| {r['label']} | {r['file']} | {r['result']} | [log](logs/{Path(r['log']).name}) |")
    if counts['survived']:
        lines += ['', '## Open survivor', '',
                  '`shared_capacity_release_dropped` replaces JudgementCapacity.release removal of (owner, key) with pass. The focused 199-test suite remains green; no error was called a kill. A leak leaves 32 completed reservations in the pool, so subsequent work cannot reserve capacity.',
                  'Regression suggestion, sent to the coordinator: after the existing test_task_and_action_adapters_share_one_capacity drains its first 32 calls, request one new action, drain it, and assert the backend call count becomes 33. This checks public capacity reuse without inspecting the private pool. The production release logic is already correct; this is a missing regression gate.', '']
    if 'rechecks' in d:
        lines += ['','Initial bounded result: **13 killed / 1 survived**. The coordinator strengthened the task/action shared-capacity test to submit a new task and action after the original 32 judgments drained, require 34 total backend calls, and require both new opinions. Only tests/test_h277_task_judge.py was overlaid. The unchanged production release logic passes; removing release now fails this public reuse regression.', '- Follow-up baseline: **199 passed**; [exact command/output](logs/capacity_reuse_baseline.log).']
        lines += ['', '## Follow-up regression rechecks', '',
                  'The initial survivor evidence is retained in initial_results.json. Only coordinator-authorized test overlays were applied for the following baseline/mutant reruns; followup_overlay_manifest.json records their hashes and final source fingerprint.', '']
        for r in d['rechecks']:
            lines.append(f"- {r['label']}: {r['result']}; [log](logs/{Path(r['log']).name}).")
    lines += ['', '## Reproduction and limits', '', '```sh',
              '.venv/bin/python3.12 docs/handoff/h277/verification/post_refactor/run_bounded.py prepare',
              '# Run only after the coordinator test-go milestone:',
              '.venv/bin/python3.12 docs/handoff/h277/verification/post_refactor/run_bounded.py run',
              '# After coordinator-authorized capacity-reuse test is ready:',
              '.venv/bin/python3.12 docs/handoff/h277/verification/post_refactor/recheck_capacity.py',
              '.venv/bin/python3.12 docs/handoff/h277/verification/post_refactor/build_report.py', '```', '',
              'prepare refuses to overwrite an existing prepared manifest. These exact results require the recorded snapshot and four-file overlay; a new current working-tree snapshot may differ. No production source/test edits, service changes, commits or pushes were made by the verifier.', '',
              'This report covers selected shared scheduling/capacity/revocation behaviors. It does not verify every new task-adapter rule, all provider/role paths, the full backend suite, generated frontend bundles, separate frontend application, real network/provider behavior, or broader H277 completion. Original round2 results and this bounded pass must retain their distinct source fingerprints.', '']
    (OUT / 'report.md').write_text('\n'.join(lines))


if __name__ == '__main__':
    main()
