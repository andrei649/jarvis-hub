#!/usr/bin/env python3
"""Render the exact local mutation evidence without promoting broader H277 completion."""
import json
import re
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]

def main():
    d = json.loads((OUT / 'results.json').read_text())
    initial = json.loads((OUT / 'initial_results.json').read_text())
    source = d['source']
    overlay = d['test_overlay']
    restore = json.loads((OUT / 'restoration.json').read_text())
    lines = ['# H277 round2 local mutation verification', '',
             'Executed 2026-09-27, local only. No production source mutations, commits, pushes, service changes, or global installs.', '',
             f"**Final: {d['counts']['killed']} killed, {d['counts']['survived']} survived, {d['counts']['superseded']} superseded/equivalent, {d['counts']['invalid']} invalid.**",
             'All 49 prepared handoff cases were executed against their current semantic anchors and killed. Of 25 additional N1–N7 cases, 24 were killed and one is observationally equivalent.', '',
             '## Scope and fingerprints', '',
             f"- Archived Git HEAD: `{source['head']}`.",
             '- Source snapshot: Git archive plus tracked dirty-file overlay taken before the concurrent kernel/mixin extraction. Untracked handoff files supply mutation metadata only. The snapshot has no .git directory.',
             f"- Original tracked-source fingerprint: `{source['tracked_source_sha256']}`.",
             f"- Same source with coordinator regression-test overlay: `{overlay['source_with_test_overlay_sha256']}`.",
             '- [source_manifest.json](source_manifest.json) records every tracked-file SHA256, the dirty overlay, and the disposable source path. Fingerprints hash sorted JSON of relative paths and SHA256 values.',
             '- [test_overlay_manifest.json](test_overlay_manifest.json) records the only subsequently copied files:', '']
    for name, digest in overlay['test_overlay_sha256'].items():
        lines.append(f'  - `{name}`: `{digest}`')
    lines += ['', 'The evidence applies to the settled round2 implementation plus these test overlays. It does not verify the subsequently edited shared kernel, new routes, Decision Inbox extension, full backend suite, or separate frontend application.', '',
              '## Baselines and execution', '',
              '- Initial targeted Python union: **433 passed**; [exact command/output](logs/baseline_py.log).',
              '- Initial legacy HUD tools file: **34 passed**; [exact command/output](logs/baseline_js.log).',
              '- Test-overlay H277 judge/roles baseline: **275 passed**; [exact command/output](logs/overlay_baseline_py.log).',
              '- Test-overlay legacy HUD tools baseline: **35 passed**; [exact command/output](logs/overlay_baseline_js.log).',
              '- Python uses the repository `.venv/bin/python3.12 -B -m pytest` with normal project pytest addopts, timeout and socket controls. No addopts override. JS uses the current PATH node and existing Vitest dependency tree. Snapshot dependencies are symlinked; source is copied.',
              '- Exactly one mutation process at a time. Each source file is restored in finally before proceeding. Python mutations parse before execution; collection/tool/import/setup errors are not counted as killed. No remaining invalid/unmatched cases.',
              f"- After the test overlay and final rechecks, all **{restore['tracked_files_checked']} tracked-file hashes** matched their expected original/overlaid values; [restoration evidence](restoration.json).", '',
              '## Survivors found and closed', '',
              f"The initial complete pass had {initial['counts']['killed']} killed and {initial['counts']['survived']} survivors. Five stale anchors were remapped and executed, never counted as kills while unmatched. [Original results](initial_results.json) retain every original survivor and log.", '',
              '| Initial survivor | Regression/equivalence | Final |', '|---|---|---|',
              '| queue_short_lived_loop_not_judged_on_hub | Capture asyncio.get_running_loop in the fake backend probe and assert it is the hub loop; instant fake completion had masked wrong-loop scheduling. | killed |',
              '| hud_repoll_never_stops | Capture a poll callback and invoke it after the hard deadline; an ordinary on-time fake timer had masked removal of the final deadline guard. | killed |',
              '| N1_memory_pending_recheck_dropped | Run waiting-policy revocation with both persisted and in-memory queues; disk checks had masked removal of the memory-status guard. | killed |',
              '| N4_remote_depth_refusal_dropped | Call remote score directly with a deep snapshot and assert no backend call; wants refusal had masked removal of the score defense. | killed |',
              '| N2_decide_pending_not_cleared | Public pending also checks terminal status; capacity uses _judging; status never returns to pending; task finally clears both sets. Removing eager discard changes transient private state only. The source keeps eager cleanup. | superseded/equivalent |', '',
              'Superseded here means observationally equivalent under the current public API, not unexecuted: the eager-discard mutant ran, returned zero, and is retained with observed_result=survived and a precise explanation. No kill ratio excludes this case silently.', '',
              '## Reproduction', '', '```sh',
              '.venv/bin/python3.12 docs/handoff/h277/verification/run_mutations.py',
              '# Resume invalid anchors only in that same snapshot:',
              'H277_MUTATION_RESUME=1 .venv/bin/python3.12 docs/handoff/h277/verification/run_mutations.py',
              '# Only after coordinator regression-test files are ready:',
              '.venv/bin/python3.12 docs/handoff/h277/verification/recheck_survivors.py',
              '.venv/bin/python3.12 docs/handoff/h277/verification/build_report.py', '```', '',
              'The initial evidence is tied to source_manifest.json; rerunning the initial script now snapshots the newer working tree and replaces that evidence. Archive this directory first if retaining these exact runs. The recheck script validates original snapshot hashes before copying tests and intentionally rejects a repeated overlay run.', '',
              '## Cases and exact logs', '',
              'Semantic anchor mappings are recorded in [effective_mutants.json](effective_mutants.json) and results.json. The obsolete test file tests/test_llm_model_config.py maps to existing tests/test_model_config.py. URL-default behavior moved to vlm.resolve_vlm_config; shallow taint and JSON-copy behavior moved to deep scanning and normalization; HUD poll-count caps moved to wall-clock deadlines.', '',
              '| Case | Generation | Result | Evidence |', '|---|---|---|---|']
    for r in d['results']:
        log = Path(r['log']).name
        lines.append(f"| {r['label']} | {r['generation']} | {r['result']} | [log](logs/{log}) |")
    lines += ['', '## Limits', '',
              '- This is targeted mutation verification, not exhaustive correctness, kernel verification, or completion of the broader H277 ledger. Mutants model specific behavioral regressions; unrelated bugs can remain.',
              '- Five initial test survivors led to four coordinator-owned regression improvements and one equivalence analysis. Live source/tests were never edited by this verification agent.',
              '- An already dispatched remote call cannot be retracted. Snapshot tests do not establish multi-process transactional persistence or real-provider network behavior.',
              '- Disposable source and existing dependency environments are reused; no paid provider or real remote model was invoked. Test execution remains governed by the project socket controls.', '']
    (OUT / 'report.md').write_text('\n'.join(lines))
    # Store failing test names as a compact machine-readable index, with exact logs authoritative.
    failures = {}
    for r in d['results']:
        output = (ROOT / r['log']).read_text()
        failures[r['label']] = re.findall(r'^FAILED (.+)$', output, re.MULTILINE)
    (OUT / 'failing_test_index.json').write_text(json.dumps(failures, indent=2) + '\n')

if __name__ == '__main__':
    main()
