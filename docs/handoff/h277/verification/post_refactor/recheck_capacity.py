#!/usr/bin/env python3
"""Recheck the capacity-release mutant after the coordinator-owned task test overlay."""
import ast
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[4]


def write_json(name, data):
    (OUT / name).write_text(json.dumps(data, indent=2) + '\n')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    manifest = json.loads((OUT / 'source_manifest.json').read_text())
    snapshot = Path(manifest['snapshot'])
    results = json.loads((OUT / 'results.json').read_text())
    if (OUT / 'initial_results.json').exists():
        raise RuntimeError('Initial results already archived; do not overwrite evidence.')
    for name, expected in manifest['files'].items():
        if digest(snapshot / name) != expected:
            raise RuntimeError('Snapshot changed before overlay: ' + name)
    write_json('initial_results.json', results)
    write_json('source_manifest_pre_recheck.json', manifest)
    name = 'tests/test_h277_task_judge.py'
    before = manifest['files'][name]
    shutil.copy2(ROOT / name, snapshot / name)
    after = digest(snapshot / name)
    manifest['files'][name] = after
    prior = manifest['source_sha256']
    manifest['source_sha256'] = hashlib.sha256(json.dumps({'files': manifest['files'], 'deleted': manifest['deleted']}, sort_keys=True).encode()).hexdigest()
    overlay = {'before_source_sha256': prior, 'after_source_sha256': manifest['source_sha256'],
               'files': {name: {'before': before, 'after': after}}}
    write_json('followup_overlay_manifest.json', overlay)
    write_json('source_manifest.json', manifest)
    plan = json.loads((OUT / 'plan.json').read_text())
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(snapshot))

    def run(label):
        command = [str(ROOT / '.venv/bin/python3.12'), '-B', '-m', 'pytest', *plan['baseline_tests']]
        start = time.monotonic()
        proc = subprocess.run(command, cwd=snapshot, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=180, text=True)
        log = OUT / 'logs' / (label + '.log')
        log.write_text('COMMAND ' + json.dumps(command) + '\n' + proc.stdout)
        return {'returncode': proc.returncode, 'command': command, 'log': str(log.relative_to(ROOT)),
                'elapsed_seconds': round(time.monotonic() - start, 2)}, proc.stdout

    baseline, output = run('capacity_reuse_baseline')
    print('RECHECK BASELINE', baseline['returncode'], flush=True)
    if baseline['returncode']:
        raise RuntimeError('Follow-up baseline failed.')
    m = next(m for m in plan['mutations'] if m['label'] == 'shared_capacity_release_dropped')
    path = snapshot / m['file']
    original = path.read_text()
    if m['a'] not in original:
        raise RuntimeError('Follow-up mutation anchor mismatch.')
    try:
        modified = original.replace(m['a'], m['b'])
        ast.parse(modified, filename=m['file'])
        path.write_text(modified)
        evidence, output = run('recheck_shared_capacity_release_dropped')
        state = ('survived' if evidence['returncode'] == 0 else 'killed'
                 if evidence['returncode'] == 1 and 'FAILED ' in output and 'ERROR collecting' not in output else 'invalid')
        print('RECHECK shared_capacity_release_dropped', state, flush=True)
    finally:
        path.write_text(original)
    row = next(r for r in results['results'] if r['label'] == m['label'])
    row.update(initial_result=row['result'], initial_evidence={k: row[k] for k in ('returncode', 'log', 'elapsed_seconds')},
               result=state, source_sha256=manifest['source_sha256'], **evidence)
    results['rechecks'] = [{'label': m['label'], 'result': state, **evidence}]
    results['followup_baseline'] = baseline
    results['followup_overlay'] = overlay
    results['initial_source_sha256'] = results['source_sha256']
    results['source_sha256'] = manifest['source_sha256']
    results['counts'] = {s: sum(r['result'] == s for r in results['results']) for s in ('killed', 'survived', 'superseded', 'invalid')}
    write_json('results.json', results)
    for name, expected in manifest['files'].items():
        if digest(snapshot / name) != expected:
            raise RuntimeError('Restoration hash mismatch: ' + name)
    if any((snapshot / name).exists() for name in manifest['deleted']):
        raise RuntimeError('Deleted path unexpectedly exists.')
    write_json('restoration.json', {'result': 'passed', 'files_checked': len(manifest['files']),
                                   'deleted_paths_checked': len(manifest['deleted']), 'source_sha256': manifest['source_sha256']})
    write_json('state.json', {'status': 'executed_followup_recheck', 'source_sha256': manifest['source_sha256']})


if __name__ == '__main__':
    main()
