#!/usr/bin/env python3
"""Prepare a fresh source snapshot, then run a bounded serial mutation audit separately."""
import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
PYTHON = Path(sys.executable)
SOURCE_REF = '9d5b3add85bd8c172bfe38ed1506a2852e2d6e5a'


def write_json(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2) + '\n')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def prepare():
    if (OUT / 'source_manifest.json').exists():
        raise RuntimeError('Prepared snapshot already exists; preserve evidence before preparing again.')
    plan = json.loads((OUT / 'plan.json').read_text())
    snapshot = Path(tempfile.mkdtemp(prefix='h277-shared-mutation-'))
    archive = snapshot.parent / (snapshot.name + '.tar')
    archive.write_bytes(git('archive', SOURCE_REF))
    with tarfile.open(archive) as tar:
        tar.extractall(snapshot, filter='data')
    archive.unlink()
    # Only the pinned committed source enters this campaign. Concurrent edits
    # and old evidence files are never overlaid or rewritten.
    dirty = []
    paths = sorted(filter(None, git('ls-tree', '-r', '--name-only', '-z', SOURCE_REF).decode().split('\0')))
    hashes = {name: digest(snapshot / name) for name in paths if (snapshot / name).is_file()}
    deleted = [name for name in paths if not (snapshot / name).exists()]
    fingerprint = hashlib.sha256(json.dumps({'files': hashes, 'deleted': deleted}, sort_keys=True).encode()).hexdigest()
    manifest = {'head': git('rev-parse', SOURCE_REF).decode().strip(), 'source_sha256': fingerprint,
                'snapshot': str(snapshot), 'dirty_overlay': dirty, 'included_untracked': plan['required_untracked'],
                'files': hashes, 'deleted': deleted, 'plan_sha256': digest(OUT / 'plan.json'), 'prepared_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    write_json('source_manifest.json', manifest)
    checks = []
    for m in plan['mutations']:
        source = (snapshot / m['file']).read_text()
        check = {'label': m['label'], 'anchor_count': source.count(m['a'])}
        if check['anchor_count'] != 1:
            check['error'] = 'Anchor mismatch; no mutation executed.'
        else:
            try:
                ast.parse(source.replace(m['a'], m['b']), filename=m['file'])
            except SyntaxError as exc:
                check['error'] = str(exc)
        checks.append(check)
    write_json('anchor_checks.json', checks)
    state = {'status': 'snapshot_ready', 'mutations': len(checks),
             'invalid_anchors': sum('error' in c for c in checks), 'source_sha256': fingerprint}
    write_json('state.json', state)
    print(json.dumps(state), flush=True)


def run():
    manifest = json.loads((OUT / 'source_manifest.json').read_text())
    snapshot = Path(manifest['snapshot'])
    plan = json.loads((OUT / 'plan.json').read_text())
    if digest(OUT / 'plan.json') != manifest['plan_sha256']:
        raise RuntimeError('Mutation plan changed after preparation.')
    results = []
    baseline = []
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(snapshot))
    logs = OUT / 'logs'
    logs.mkdir(exist_ok=True)

    def invoke(label, tests):
        command = [str(PYTHON), '-B', '-m', 'pytest', *tests]
        start = time.monotonic()
        try:
            p = subprocess.run(command, cwd=snapshot, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, timeout=180, text=True)
            rc, output = p.returncode, p.stdout
        except subprocess.TimeoutExpired as exc:
            rc, output = 124, str(exc.stdout)
        log = logs / (label + '.log')
        raw_log = 'COMMAND ' + json.dumps(command) + '\n' + output
        log.write_text('\n'.join(line.rstrip() for line in raw_log.splitlines()) + '\n')
        return {'returncode': rc, 'elapsed_seconds': round(time.monotonic() - start, 2),
                'command': command, 'log': str(log.relative_to(ROOT)),
                'raw_log_sha256': hashlib.sha256(raw_log.encode()).hexdigest()}, output

    def save():
        counts = {s: sum(r['result'] == s for r in results) for s in ('killed', 'survived', 'superseded', 'invalid')}
        write_json('results.json', {'source_sha256': manifest['source_sha256'], 'baseline': baseline,
                                    'counts': counts, 'results': results})

    for name, expected in manifest['files'].items():
        if digest(snapshot / name) != expected:
            raise RuntimeError('Snapshot changed before baseline: ' + name)
    evidence, output = invoke('baseline', plan['baseline_tests'])
    baseline.append(evidence)
    save()
    print('BASELINE', evidence['returncode'], evidence['elapsed_seconds'], flush=True)
    if evidence['returncode']:
        raise RuntimeError('Baseline failed; do not run mutations.')
    for i, m in enumerate(plan['mutations'], 1):
        path = snapshot / m['file']
        original = path.read_text()
        row = {k: v for k, v in m.items() if k not in ('a', 'b')}
        if original.count(m['a']) != 1:
            row.update(result='invalid', reason='Unmatched anchor; no mutation executed.')
        else:
            try:
                changed = original.replace(m['a'], m['b'])
                ast.parse(changed, filename=m['file'])
                path.write_text(changed)
                evidence, output = invoke(m['label'], m['tests'])
                result = ('survived' if evidence['returncode'] == 0 else 'killed'
                          if evidence['returncode'] == 1 and 'FAILED ' in output and 'ERROR collecting' not in output else 'invalid')
                row.update(result=result, **evidence)
            except SyntaxError as exc:
                row.update(result='invalid', reason=str(exc))
            finally:
                path.write_text(original)
        results.append(row)
        save()
        print(i, len(plan['mutations']), m['label'], row['result'], flush=True)
    for name, expected in manifest['files'].items():
        if digest(snapshot / name) != expected:
            raise RuntimeError('Restoration mismatch: ' + name)
    if any((snapshot / name).exists() for name in manifest['deleted']):
        raise RuntimeError('Deleted file unexpectedly restored.')
    write_json('restoration.json', {'result': 'passed', 'files_checked': len(manifest['files']),
                                    'deleted_paths_checked': len(manifest['deleted']), 'source_sha256': manifest['source_sha256']})
    write_json('state.json', {'status': 'executed', 'source_sha256': manifest['source_sha256']})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['prepare', 'run'])
    args = parser.parse_args()
    prepare() if args.mode == 'prepare' else run()
