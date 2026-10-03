#!/usr/bin/env python3
"""Isolated behavioral probes for authenticated denial feedback, never live edits."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
QUEUE = 'agents/core/autonomy/queue.py'
RENDER = 'agents/core/approval_outcomes.py'
QUEUE_TEST = 'tests/test_h485_denial_feedback_queue.py'
CHAT_TEST = 'tests/test_h485_denial_feedback_integration.py'
UTILITY = 'docs/hermes/evidence/h277-smart-terminal-mutations-2026-10-03.py'
TESTS = (QUEUE_TEST, CHAT_TEST)
PUBLIC_CONFIG = 'agents/_system/agents.yaml'
HASHED = (QUEUE, RENDER, *TESTS, UTILITY, PUBLIC_CONFIG)
OUT = Path(__file__).with_suffix('.json')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cases():
    return [
        ('committed_denial_not_counted', QUEUE,
         'self._record_chat_guardian_denial_locked(task, snapshot_sha256)', 'pass',
         (QUEUE_TEST + '::test_third_exact_denial_warns_with_event_count_only', CHAT_TEST)),
        ('old_epoch_reactivated', QUEUE,
         "and tally['epoch'] == epoch", 'and True',
         (QUEUE_TEST + '::test_signed_approve_resets_without_reviving_old_warning',)),
        ('owner_approval_reset_omitted', QUEUE,
         'self._reset_chat_guardian_denials_locked(task)', 'pass',
         (QUEUE_TEST + '::test_recorded_human_approval_resets_but_reject_does_not',)),
        ('edited_snapshot_feedback_reused', QUEUE,
         'or self._approval_snapshot_digest_locked(task) != snapshot):', 'or False):',
         (QUEUE_TEST + '::test_changed_task_revision_hides_stale_event_then_counts_new_denial',)),
        ('consumer_capacity_unbounded', QUEUE,
         '(_GUARDIAN_CONSUMER_LIMIT,))', '(1_000_000,))',
         (QUEUE_TEST + '::test_tally_capacity_evicts_old_epoch_without_reviving_warning',)),
        ('active_breaker_hidden_by_backlog', QUEUE,
         'observations = [latest, *(item for item in observations if item is not latest)]',
         'observations = observations',
         (QUEUE_TEST + '::test_latest_active_breaker_preempts_waiting_backlog_with_exact_ack',)),
        ('warning_outside_byte_budget', RENDER,
         "if len(rendered.encode('utf-8')) > budget:", 'if False:',
         (CHAT_TEST + '::test_breaker_guidance_shares_fenced_output_budget',)),
    ]


def main():
    spec = importlib.util.spec_from_file_location('h277_mutation_helpers', REPO / UTILITY)
    utility = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(utility)
    utility.PYTHON = Path(sys.executable)
    root = Path(tempfile.mkdtemp(prefix='h485-feedback-mutations-', dir='/tmp'))
    logs = root / 'logs'
    logs.mkdir()
    names = subprocess.check_output(['git', 'ls-files', '-z', '--', 'agents', 'tests'], cwd=REPO)
    paths = [os.fsdecode(p) for p in names.split(b'\0') if p and p.endswith(b'.py')]
    paths = list(dict.fromkeys([*paths, *TESTS, PUBLIC_CONFIG, 'pytest.ini']))
    for name in paths:
        source, destination = REPO / name, root / name
        if not source.is_file() or source.is_symlink():
            raise RuntimeError(f'expected regular source: {name}')
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    originals = {name: (REPO / name).read_bytes() for name in HASHED}
    hashes = {name: digest(REPO / name) for name in HASHED}
    result = {'generated_utc': datetime.now(UTC).isoformat(), 'python': sys.executable,
              'source_and_test_sha256': hashes, 'temporary_root': str(root), 'mutants': []}
    baseline = result['baseline'] = utility.run(root, logs, 'baseline', TESTS)
    if baseline['returncode'] or baseline['failures'] or baseline['errors'] or not baseline['tests']:
        result['status'] = 'invalid_baseline'
        OUT.write_text(json.dumps(result, indent=2) + '\n')
        raise RuntimeError('isolated baseline failed; no mutants credited')
    for name, path, old, new, selectors in cases():
        data = originals[path].decode()
        # Reset calls have three trusted callers; deliberately remove all of them.
        expected = 3 if name == 'owner_approval_reset_omitted' else 1
        if data.count(old) != expected:
            raise RuntimeError(f'{name}: expected {expected} exact anchors, found {data.count(old)}')
        try:
            (root / path).write_text(data.replace(old, new))
            probe = utility.run(root, logs, name, selectors)
            valid = not probe['timed_out'] and probe['tests'] > 0 and not probe['errors']
            outcome = ('killed' if valid and probe['returncode'] and probe['failures'] else
                       'survived' if valid and probe['returncode'] == 0 else 'invalid')
            result['mutants'].append({'name': name, 'path': path, 'selectors': selectors,
                                      'outcome': outcome, **probe})
        finally:
            (root / path).write_bytes(originals[path])
    result['restored_baseline'] = utility.run(root, logs, 'restored_baseline', TESTS)
    result['live_source_unchanged'] = hashes == {name: digest(REPO / name) for name in HASHED}
    result['counts'] = {kind: sum(m['outcome'] == kind for m in result['mutants'])
                        for kind in ('killed', 'survived', 'invalid')}
    restored = result['restored_baseline']
    result['status'] = ('complete' if result['live_source_unchanged'] and not restored['returncode']
                        and restored['tests'] == baseline['tests'] and not restored['failures']
                        and not restored['errors'] else 'invalid_restoration_or_drift')
    OUT.write_text(json.dumps(result, indent=2) + '\n')
    if result['status'] != 'complete' or result['counts']['survived'] or result['counts']['invalid']:
        raise RuntimeError('mutation verification has unresolved gaps')
    print(result['counts'])


if __name__ == '__main__':
    main()
