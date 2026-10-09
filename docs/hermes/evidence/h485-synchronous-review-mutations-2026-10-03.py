#!/usr/bin/env python3
"""Isolated exact-attempt waiting and notification faults; no live source edits."""
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
RUNNER = 'agents/core/autonomy/advisory_judgements.py'
ADAPTER = 'agents/core/autonomy/task_approval_judge.py'
WORKER = 'agents/core/autonomy/worker.py'
WAIT_TEST = 'tests/test_h485_judgement_waiting.py'
NATIVE_TEST = 'tests/test_h485_smart_review_waiting_integration.py'
NOTIFY_TEST = 'tests/test_h485_smart_review_notifications.py'
UTILITY = 'docs/hermes/evidence/h277-smart-terminal-mutations-2026-10-03.py'
TESTS = (WAIT_TEST, NATIVE_TEST, NOTIFY_TEST)
PUBLIC_CONFIG = 'agents/_system/agents.yaml'
SOURCES = (RUNNER, ADAPTER, WORKER)
HASHED = (*SOURCES, *TESTS, UTILITY, PUBLIC_CONFIG,
          'tests/test_h485_smart_observer_dispatch.py')
OUT = Path(__file__).with_suffix('.json')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cases():
    return [
        ('notification_wait_omitted', WORKER,
         'await self._await_smart_notification_review(task)', 'pass',
         (NOTIFY_TEST + '::test_governed_enqueue_holds_push_until_native_verdict',)),
        ('stale_intake_card_sent_after_wait', WORKER,
         'return await notifier(current)', 'return await notifier(task)',
         (NOTIFY_TEST + '::test_edited_task_release_uses_fresh_card_instead_of_pre_wait_bytes',)),
        ('expired_card_release_allowed', WORKER,
         'return current if valid and approval_is_pending(current) else None',
         'return current if valid else None',
         (NOTIFY_TEST + '::test_deadline_crossed_while_waiting_never_sends_unactionable_card',)),
        ('removed_notifier_consumes_retry', WORKER,
         'if not callable(notifier) or pending_leader() is None:',
         'if pending_leader() is None:',
         (NOTIFY_TEST + '::test_notifier_removed_during_review_does_not_consume_delivery_retry',)),
        ('waiter_timeout_does_not_invalidate', RUNNER,
         'except TimeoutError:\n            self._cancel_attempt(attempt)\n            return False',
         'except TimeoutError:\n            return False',
         (NATIVE_TEST + '::test_slot_wait_timeout_cannot_dispatch_later_after_capacity_returns',)),
        ('caller_cancellation_does_not_invalidate', RUNNER,
         'except asyncio.CancelledError:\n            self._cancel_attempt(attempt)\n            raise',
         'except asyncio.CancelledError:\n            raise',
         (WAIT_TEST + '::test_caller_cancellation_invalidates_exact_attempt',)),
        ('cancelled_work_releases_capacity_early', RUNNER,
         'if task is None and not attempt.capacity_released:',
         'if not attempt.capacity_released:',
         (WAIT_TEST + '::test_cancel_resistant_tasks_retain_capacity_until_their_actual_completion',)),
        ('old_callback_clears_replacement', RUNNER,
         'current = self._judge_attempts.get(attempt.key) is attempt',
         'current = True',
         (WAIT_TEST + '::test_old_cancelled_callback_cannot_clear_or_settle_replacement',)),
        ('deadline_timer_omitted', RUNNER,
         'attempt.timer = loop.call_later(\n                    max(0, attempt.deadline - time.monotonic()), self._cancel_attempt, attempt,\n                )',
         'attempt.timer = None',
         (WAIT_TEST + '::test_deadline_includes_slot_wait_even_without_a_waiter',)),
    ]

def main():
    spec = importlib.util.spec_from_file_location('h277_mutation_helpers', REPO / UTILITY)
    utility = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(utility)
    utility.PYTHON = Path(sys.executable)
    root = Path(tempfile.mkdtemp(prefix='h485-waiting-mutations-', dir='/tmp'))
    logs = root / 'logs'
    logs.mkdir()
    names = subprocess.check_output(['git', 'ls-files', '-z', '--', 'agents', 'tests'], cwd=REPO)
    paths = [os.fsdecode(p) for p in names.split(b'\0') if p and p.endswith(b'.py')]
    paths = list(dict.fromkeys([*paths, *SOURCES, *TESTS, PUBLIC_CONFIG, 'pytest.ini']))
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
        expected = 1
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
