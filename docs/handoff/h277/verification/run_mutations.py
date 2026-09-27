#!/usr/bin/env python3
"""Serial H277 mutation audit in a non-Git, disposable tracked-source snapshot."""
import ast
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
PYTHON = ROOT / '.venv/bin/python3.12'
MAP_TESTS = {'tests/test_llm_model_config.py': 'tests/test_model_config.py'}

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)

def main():
    resume = os.environ.get('H277_MUTATION_RESUME') == '1'
    snapshot = Path(json.loads((OUT / 'source_manifest.json').read_text())['snapshot']) if resume else Path(tempfile.mkdtemp(prefix='h277-mutation-'))
    if resume:
        manifest = json.loads((OUT / 'source_manifest.json').read_text())
    else:
        archive = snapshot.parent / (snapshot.name + '.tar')
        archive.write_bytes(git('archive', 'HEAD'))
        with tarfile.open(archive) as tar:
            tar.extractall(snapshot, filter='data')
        archive.unlink()
        dirty = git('diff', 'HEAD', '--name-only', '-z').decode().split('\0')
        for name in filter(None, dirty):
            src, dst = ROOT / name, snapshot / name
            if src.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            elif dst.exists():
                dst.unlink()
        for name in ('.venv', 'node_modules'):
            if (ROOT / name).exists():
                (snapshot / name).symlink_to(ROOT / name, target_is_directory=True)
        tracked = git('ls-files', '-z').decode().split('\0')
        hashes = {name: hashlib.sha256((snapshot / name).read_bytes()).hexdigest()
                  for name in sorted(filter(None, tracked)) if (snapshot / name).is_file()}
        fingerprint = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
        manifest = {'head': git('rev-parse', 'HEAD').decode().strip(), 'tracked_source_sha256': fingerprint,
                    'dirty_overlay': list(filter(None, dirty)), 'snapshot': str(snapshot), 'files': hashes}
        (OUT / 'source_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    mutations = json.loads((ROOT / 'docs/handoff/h277/mutants.json').read_text())
    for m in mutations:
        m['generation'] = 'prepared'
        m['tests'] = [MAP_TESTS.get(t, t) for t in m['tests']]
    maps = {
        'roles_pick_legacy_wins_over_role_name': ('    if new:\n', '    if new and not legacy:\n', 'Comment was added before return; mutate the current precedence condition.'),
        'roles_pick_shadowed_legacy_not_reported': ('([legacy_name] if legacy and legacy != new else [])', '[]', 'Round2 now compares case-sensitive values; drop the equivalent ignored-legacy report.'),
        'roles_vision_view_legacy_url_wins': ('url = role_url or legacy_url', 'url = legacy_url or role_url', 'Round2 extracts URL variables; invert the equivalent precedence.'),
        'roles_vision_lmstudio_default_url_dropped': ('base = url or LMSTUDIO_VLM_BASE', 'base = url', 'Default URL now belongs to resolve_vlm_config in vlm.py; remove that default at the current consumer.'),
        'judge_wants_tainted_sent_remote': ('            if taint.is_tainted(dict(snapshot)) or _deep_tainted(snapshot.get("args")):', '            if False:', 'Round2 replaced shallow args taint with deep args taint; remove current equivalent gate.'),
        'queue_snapshot_is_stored_item': ('snapshot = normalise_snapshot(item)', 'snapshot = item', 'Round2 replaced JSON round-trip with normalization; retain alias-to-live-item mutant.'),
        'hud_repoll_never_stops': ('if (polls.current[id] > Date.now();', '', ''),
    }
    maps['hud_opinion_advisory_label_dropped'] = ("'” · advisory only, it decides nothing'", "'”'", 'HUD now uses typographic closing quote; remove the same advisory label.')
    for m in mutations:
        if m['label'] in maps and m['label'] != 'hud_repoll_never_stops':
            m['a'], m['b'], m['mapping'] = maps[m['label']]
        if m['label'] == 'roles_vision_lmstudio_default_url_dropped':
            m['file'] = 'agents/core/llm/vlm.py'
        if m['label'] == 'hud_repoll_never_stops':
            m['a'] = 'return polls.current[id] > Date.now();'
            m['b'] = 'return true;'
            m['mapping'] = 'Round2 replaced poll-count cap with wall-clock deadlines; bypass final timer deadline guard.'
    def add(label, file, a, b, generation, run='py'):
        mutations.append({'label': label, 'file': file, 'a': a, 'b': b, 'generation': generation, 'run': run,
                          'tests': ['tests/frontend/tools.test.js'] if run == 'js' else ['tests/test_h277_approval_judge.py']})
    queue = 'agents/core/autonomy/action_approvals.py'
    judge = 'agents/core/autonomy/approval_judge.py'
    hud = 'agents/web/static/tools.js'
    add('N1_post_slot_status_stale', queue, 'current = judge.status() if judge is not None else None', 'current = status', 'N1')
    add('N1_post_slot_wants_dropped', queue, 'or not judge.wants(live, current) or not judge.wants(snapshot, current)', 'or False', 'N1')
    add('N1_disk_pending_recheck_dropped', queue, 'persisted.get("status") != "pending"', 'False', 'N1')
    add('N1_memory_pending_recheck_dropped', queue, 'if not item or item.get("status") != "pending" or "judge" in item:', 'if not item or "judge" in item:', 'N1')
    add('N1_skip_revoked_counter_dropped', queue, 'self._skipped_revoked += 1', 'self._skipped_revoked += 0', 'N1')
    add('N2_public_pending_hidden', queue, 'out["judge_pending"] = True', 'out["judge_pending"] = False', 'N2')
    add('N2_finish_pending_not_cleared', queue, '            self._judge_pending.discard(action_id)\n', '            pass\n', 'N2')
    add('N2_decide_pending_not_cleared', queue, '        self._clear_judge_pending(action_id)\n', '', 'N2')
    add('N2_hud_early_timeout', hud, '(17 * (timeout > 0 && Number.isFinite(timeout) ? timeout : 20) + 5)', '((timeout > 0 && Number.isFinite(timeout) ? timeout : 20) + 5)', 'N2', 'js')
    add('N2_hud_deadline_refreshes', hud, 'if (!Object.prototype.hasOwnProperty.call(next, a.id)) next[a.id] = now + budget;', 'next[a.id] = now + budget;', 'N2', 'js')
    add('N2_capacity_released_on_decide', queue, '        self._clear_judge_pending(action_id)\n', '        self._clear_judge_pending(action_id)\n        self._judging.discard(action_id)\n', 'N2')
    add('N3_within_budget_values_cut', judge, '    if len(encoded) <= ARGS_CAP:\n        return encoded, False', '    if len(encoded) <= 1500:\n        return encoded, False', 'N3')
    add('N3_small_values_inflated', judge, 'if len(_encoded(shortened)) < sizes[(kind, key)]:', 'if len(text) > cap:', 'N3')
    add('N3_args_cap_raised', judge, 'ARGS_CAP = 4000', 'ARGS_CAP = 8000', 'N3')
    add('N4_deep_truncated_flag_dropped', judge, 'return fenced, names, truncated or too_deep', 'return fenced, names, truncated', 'N4')
    add('N4_deep_flag_dropped', judge, 'names = sorted(set(names) | {"nesting_too_deep"})', 'names = sorted(set(names))', 'N4')
    add('N4_remote_depth_refusal_dropped', judge, 'if not status.local and "nesting_too_deep" in flags:', 'if False:', 'N4')
    add('N4_normalised_marker_not_tainted', judge, 'if depth > _TAINT_DEPTH or (isinstance(obj, str) and obj == _NESTING_MARKER):', 'if depth > _TAINT_DEPTH:', 'N4')
    add('N5_nfkc_dropped', judge, 'unicodedata.normalize("NFKC", text)', 'text', 'N5')
    add('N5_unicode_quote_categories_dropped', judge, 'or unicodedata.category(ch) in {"Pi", "Pf"}', 'or False', 'N5')
    add('N5_dot_separator_kept', judge, 'out = _SEPARATOR_RE.sub("-", out)', 'out = out', 'N5')
    add('N6_bytes_repr_instead_of_decode', judge, 'return obj.decode("utf-8", errors="replace")', 'return str(obj)', 'N6')
    add('N6_set_repr_instead_of_list', judge, 'if isinstance(obj, (list, tuple, set, frozenset)):', 'if isinstance(obj, (list, tuple)):', 'N6')
    add('N7_import_guard_wrong_exception', queue, '        except ImportError:\n', '        except KeyError:\n', 'N7')
    add('N7_unconfigured_judge_taints_item', queue, 'if self._judge is not None and self._judge.status().configured:', 'if True:', 'N7')
    (OUT / 'effective_mutants.json').write_text(json.dumps(mutations, indent=2) + '\n')
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(snapshot))
    logs = OUT / 'logs'
    logs.mkdir(exist_ok=True)
    def run(label, run_kind, tests):
        command = ([str(PYTHON), '-B', '-m', 'pytest', *tests] if run_kind == 'py'
                   else [shutil.which('node'), 'node_modules/vitest/vitest.mjs', 'run', *tests])
        start = time.monotonic()
        try:
            p = subprocess.run(command, cwd=snapshot, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, timeout=180, text=True)
            rc, output = p.returncode, p.stdout
        except subprocess.TimeoutExpired as exc:
            rc, output = 124, str(exc.stdout)
        log = logs / (label + '.log')
        log.write_text('COMMAND ' + json.dumps(command) + '\n' + output)
        return {'returncode': rc, 'elapsed_seconds': round(time.monotonic() - start, 2),
                'log': str(log.relative_to(ROOT)), 'command': command}, output
    prior = json.loads((OUT / 'results.json').read_text()) if resume else {}
    results = [r for r in prior.get('results', []) if r['result'] != 'invalid']
    baseline = prior.get('baseline', [])
    if resume:
        finished = {r['label'] for r in results}
        mutations = [m for m in mutations if m['label'] not in finished]
    for kind in (() if resume else ('py', 'js')):
        tests = sorted({t for m in mutations if m['run'] == kind for t in m['tests']})
        missing = [t for t in tests if not (snapshot / t).exists()]
        if missing:
            raise RuntimeError('Missing baseline tests: ' + repr(missing))
        evidence, output = run('baseline_' + kind, kind, tests)
        baseline.append(evidence)
        print('BASELINE', kind, evidence['returncode'], evidence['elapsed_seconds'], flush=True)
        if evidence['returncode']:
            (OUT / 'results.json').write_text(json.dumps({'manifest': manifest, 'baseline': baseline}, indent=2))
            raise RuntimeError('Baseline failed; see log')
    def save():
        counts = {state: sum(r['result'] == state for r in results) for state in ('killed', 'survived', 'superseded', 'invalid')}
        (OUT / 'results.json').write_text(json.dumps({'source': {k:v for k,v in manifest.items() if k != 'files'}, 'baseline': baseline, 'counts': counts, 'results': results}, indent=2) + '\n')
    for index, m in enumerate(mutations, 1):
        path = snapshot / m['file']
        original = path.read_text()
        row = {k:v for k,v in m.items() if k not in ('a', 'b')}
        if m['a'] not in original:
            row.update(result='invalid', reason='Anchor not matched; no mutation executed.')
        else:
            modified = original.replace(m['a'], m['b'])
            try:
                if m['run'] == 'py':
                    ast.parse(modified, filename=m['file'])
                path.write_text(modified)
                evidence, output = run(m['label'], m['run'], m['tests'])
                row.update(evidence)
                if evidence['returncode'] == 0:
                    row['result'] = 'survived'
                elif evidence['returncode'] == 1 and ('FAILED ' in output or ('AssertionError' in output and 'FAIL ' in output)) and 'ERROR collecting' not in output:
                    row['result'] = 'killed'
                else:
                    row.update(result='invalid', reason='Nonassertion/collection/timeout/tool failure; inspect log.')
            except SyntaxError as exc:
                row.update(result='invalid', reason=str(exc))
            finally:
                path.write_text(original)
        results.append(row)
        save()
        print(index, len(mutations), m['label'], row['result'], row.get('elapsed_seconds', ''), flush=True)
    print('DONE', str(OUT / 'results.json'), flush=True)

if __name__ == '__main__':
    main()
