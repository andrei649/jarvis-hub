#!/usr/bin/env python3
"""Overlay coordinator-owned regressions only, then baseline and serially recheck survivors."""
import ast
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
PYTHON = ROOT / '.venv/bin/python3.12'

def main():
    manifest = json.loads((OUT / 'source_manifest.json').read_text())
    snapshot = Path(manifest['snapshot'])
    initial = json.loads((OUT / 'results.json').read_text())
    for name, digest in manifest['files'].items():
        p = snapshot / name
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != digest:
            raise RuntimeError('Snapshot changed before test overlay: ' + name)
    (OUT / 'initial_results.json').write_text(json.dumps(initial, indent=2) + '\n')
    overlays = {}
    for name in ('tests/test_h277_approval_judge.py', 'tests/frontend/tools.test.js'):
        shutil.copy2(ROOT / name, snapshot / name)
        overlays[name] = hashlib.sha256((snapshot / name).read_bytes()).hexdigest()
    updated = dict(manifest['files'], **overlays)
    overlay_manifest = {'base_tracked_source_sha256': manifest['tracked_source_sha256'],
                        'test_overlay_sha256': overlays,
                        'source_with_test_overlay_sha256': hashlib.sha256(json.dumps(updated, sort_keys=True).encode()).hexdigest()}
    (OUT / 'test_overlay_manifest.json').write_text(json.dumps(overlay_manifest, indent=2) + '\n')
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(snapshot))
    def run(label, kind, tests):
        command = ([str(PYTHON), '-B', '-m', 'pytest', *tests] if kind == 'py'
                   else [shutil.which('node'), 'node_modules/vitest/vitest.mjs', 'run', *tests])
        start = time.monotonic()
        p = subprocess.run(command, cwd=snapshot, env=env, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=180, text=True)
        log = OUT / 'logs' / (label + '.log')
        log.write_text('COMMAND ' + json.dumps(command) + '\n' + p.stdout)
        return {'returncode': p.returncode, 'elapsed_seconds': round(time.monotonic()-start, 2),
                'log': str(log.relative_to(ROOT)), 'command': command}, p.stdout
    baseline = []
    for kind, tests in [('py', ['tests/test_h277_approval_judge.py', 'tests/test_h277_model_roles.py']), ('js', ['tests/frontend/tools.test.js'])]:
        row, output = run('overlay_baseline_' + kind, kind, tests)
        baseline.append(row)
        print('OVERLAY BASELINE', kind, row['returncode'], flush=True)
        if row['returncode']:
            raise RuntimeError('Overlay baseline failed; see log')
    cases = {m['label']: m for m in json.loads((OUT / 'effective_mutants.json').read_text())}
    followup = []
    for row in initial['results']:
        if row['result'] != 'survived':
            continue
        if row['label'] == 'N2_decide_pending_not_cleared':
            row.update(result='superseded', observed_result='survived', reason='Observationally equivalent: public pending additionally checks terminal status, capacity uses _judging, statuses never return to pending, and task finally clears both runtime sets. Only transient private set cleanup changes.')
            continue
        m = cases[row['label']]
        path = snapshot / m['file']
        original = path.read_text()
        if m['a'] not in original:
            raise RuntimeError('Recheck anchor mismatch: ' + m['label'])
        try:
            modified = original.replace(m['a'], m['b'])
            if m['run'] == 'py':
                ast.parse(modified)
            path.write_text(modified)
            evidence, output = run('recheck_' + m['label'], m['run'], m['tests'])
            result = ('survived' if evidence['returncode'] == 0 else 'killed'
                      if evidence['returncode'] == 1 and ('FAILED ' in output or ('AssertionError' in output and 'FAIL ' in output)) and 'ERROR collecting' not in output else 'invalid')
            followup.append(dict(label=m['label'], result=result, **evidence))
            row.update(initial_result='survived', initial_evidence={k:row[k] for k in ('returncode', 'log', 'elapsed_seconds')}, result=result, **evidence)
            print('RECHECK', m['label'], result, flush=True)
        finally:
            path.write_text(original)
    initial.update(test_overlay=overlay_manifest, overlay_baseline=baseline, rechecks=followup)
    initial['counts'] = {s:sum(r['result']==s for r in initial['results']) for s in ('killed', 'survived', 'superseded', 'invalid')}
    (OUT / 'results.json').write_text(json.dumps(initial, indent=2) + '\n')
    for name, digest in updated.items():
        p = snapshot / name
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != digest:
            raise RuntimeError('Snapshot restoration failed: ' + name)
    (OUT / 'restoration.json').write_text(json.dumps({'tracked_files_checked': len(updated), 'restoration': 'passed', **overlay_manifest}, indent=2) + '\n')

if __name__ == '__main__':
    main()
