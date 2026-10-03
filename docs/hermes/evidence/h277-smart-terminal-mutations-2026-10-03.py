#!/usr/bin/env python3
"""Isolated, exact-source mutation probes for H277 smart terminal authority."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PYTHON = Path('/tmp/nerva-pr-python-20261001/bin/python')
OUT = Path(__file__).with_suffix('.json')
QUEUE = 'agents/core/autonomy/queue.py'
JUDGE = 'agents/core/autonomy/approval_judge.py'
POLICY = 'agents/core/autonomy/smart_approvals.py'  # untracked at this checkpoint
COORDINATOR = 'agents/core/autonomy_coordinator.py'
WORKER = 'agents/core/autonomy/worker.py'
RUNNER = 'agents/core/environments/execution.py'
KERNEL = 'agents/core/kernel/__init__.py'
BINDING = 'agents/core/kernel/binding.py'
QUEUE_TEST = 'tests/test_h277_smart_terminal_queue.py'
JUDGE_TEST = 'tests/test_h277_smart_judge.py'
POLICY_TEST = 'tests/test_h277_smart_approval_policy.py'
INTEGRATION_TEST = 'tests/test_h277_smart_terminal_integration.py'
ACTUATION_TEST = 'tests/test_h277_smart_terminal_actuation.py'
KERNEL_TEST = 'tests/test_h277_smart_kernel.py'
TEST_FILES = (QUEUE_TEST, JUDGE_TEST, POLICY_TEST, INTEGRATION_TEST, ACTUATION_TEST,
              KERNEL_TEST)
HASHED = (QUEUE, JUDGE, POLICY, COORDINATOR, WORKER, RUNNER, KERNEL, BINDING,
          *TEST_FILES)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_result(junit: Path) -> dict:
    if not junit.is_file():
        return {'tests': 0, 'failures': 0, 'errors': 0, 'failed_tests': []}
    cases = list(ET.parse(junit).getroot().iter('testcase'))
    failed = [f"{case.get('classname')}::{case.get('name')}" for case in cases
              if any(child.tag == 'failure' for child in case)]
    return {'tests': len(cases), 'failures': len(failed),
            'errors': sum(child.tag == 'error' for case in cases for child in case),
            'failed_tests': failed}


def run(root: Path, logs: Path, name: str, selectors: tuple[str, ...]) -> dict:
    log, junit = logs / f'{name}.log', logs / f'{name}.xml'
    command = [str(PYTHON), '-m', 'pytest', *selectors, '-p', 'no:cacheprovider',
               '--tb=short', f'--junitxml={junit}']
    env = os.environ.copy()
    env.update({'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': str(root),
                'JARVIS_TESTING': '1', 'JARVIS_RATE_LIMIT': '0',
                'JARVIS_STRICT_EGRESS': '0'})
    started = time.monotonic()
    with log.open('w', encoding='utf-8') as stream:
        try:
            process = subprocess.run(command, cwd=root, env=env, stdout=stream,
                                     stderr=subprocess.STDOUT, timeout=90, check=False)
            code, timed_out = process.returncode, False
        except subprocess.TimeoutExpired:
            code, timed_out = None, True
    return {'returncode': code, 'timed_out': timed_out,
            'seconds': round(time.monotonic() - started, 3), 'log': str(log),
            **test_result(junit)}


def copy_source(root: Path) -> list[str]:
    tracked = subprocess.check_output(['git', 'ls-files', '-z', '--', 'agents'], cwd=REPO)
    paths = [os.fsdecode(item) for item in tracked.split(b'\0') if item]
    paths = [item for item in paths if item.endswith('.py')]
    # Include the new untracked helper and tests explicitly; git ls-files omits them.
    paths += [POLICY, *TEST_FILES, 'tests/conftest.py',
              'tests/support/pytest_root_cleanup.py', 'pytest.ini']
    paths = list(dict.fromkeys(paths))
    for name in paths:
        src, dest = REPO / name, root / name
        if not src.is_file() or src.is_symlink():
            raise RuntimeError(f'expected regular source file: {name}')
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
    return paths


def mutate(root: Path, relative: str, old: str, new: str, original: bytes) -> str:
    text = original.decode('utf-8')
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f'mutation anchor count {count}, expected 1: {relative}')
    mutant = text.replace(old, new, 1).encode('utf-8')
    if mutant == original:
        raise RuntimeError(f'mutation left source unchanged: {relative}')
    (root / relative).write_bytes(mutant)
    return sha256(mutant)


def cases() -> list[tuple[str, str, str, str, tuple[str, ...]]]:
    return [
        ('signed_receipt_validation_removed', QUEUE,
         'if not self._mediation_signer.verify(receipt_bytes, stored["signature"]):\n'
         '                    return False',
         'if False:\n                    return False',
         (QUEUE_TEST + '::test_receipt_signature_and_authority_fields_cannot_be_forged',)),
        ('config_revocation_ignored', JUDGE,
         'and self.smart_binding_current(result.policy_revision, result.judge_revision)',
         'and True',
         (INTEGRATION_TEST + '::test_revoked_smart_mode_after_approval_cannot_execute',
          JUDGE_TEST + '::test_smart_policy_revocation_during_physical_request_drops_result')),
        ('exact_snapshot_digest_ignored', QUEUE,
         'or self._approval_snapshot_digest_locked(task) != snapshot_sha256',
         'or False',
         (QUEUE_TEST + '::test_stale_snapshot_and_duplicate_or_wrong_kind_cannot_approve',)),
        ('real_agent_replaced_by_jarvis', COORDINATOR,
         "agent=getattr(approved, 'agent', ''),", "agent='jarvis',",
         (INTEGRATION_TEST + '::test_smart_execution_keeps_the_reviewed_agent_at_the_target_and_kernel',)),
        ('unsigned_human_downgrade_allowed', COORDINATOR,
         "return (task.decision in {'accept', 'edit'}\n"
         "                    and str(task.decided_by).lower() not in {'policy', 'smart_approval'}\n"
         "                    and isinstance(metadata, dict) and metadata.get('action') == task.decision\n"
         "                    and metadata.get('by') == task.decided_by)",
         "return task.decision in {'accept', 'edit'}",
         (INTEGRATION_TEST + '::test_machine_approval_cannot_be_downgraded_to_unsigned_human_accept',)),
        ('docker_kernel_grant_ignored', RUNNER,
         'kernel_refusal = await self._kernel_grant(decision.agent, payload, request=request)\n'
         '                if kernel_refusal is not None:\n'
         '                    return {"ok": False, **kernel_refusal, **base}',
         'kernel_refusal = await self._kernel_grant(decision.agent, payload, request=request)\n'
         '                if False:\n'
         '                    return {"ok": False, **kernel_refusal, **base}',
         (ACTUATION_TEST + '::test_smart_docker_requires_kernel_grant',)),
        ('post_await_request_guard_omitted', RUNNER,
         'if not self._request_current(approved_task_id, request):\n'
         '                return {"ok": False, "reason": "terminal_request_changed", **base}\n'
         '            active = self._sandbox.active_backend()',
         'if False:\n'
         '                return {"ok": False, "reason": "terminal_request_changed", **base}\n'
         '            active = self._sandbox.active_backend()',
         (ACTUATION_TEST + '::test_async_kernel_grant_cannot_outlive_approval_revocation',)),
        ('kernel_receipt_callback_forged', KERNEL,
         'trusted_receipt = approval_check(action) is True',
         'trusted_receipt = True',
         (KERNEL_TEST + '::test_receipt_callback_must_match_actual_action',)),
        ('kernel_auto_mode_guard_omitted', KERNEL,
         'if policy.effective_mode(action.agent) == "auto":',
         'if True:',
         (KERNEL_TEST + '::test_receipt_cannot_override_non_auto_global_mode',
          KERNEL_TEST + '::test_receipt_cannot_override_per_agent_mode')),
        ('kernel_taint_escalation_omitted', KERNEL,
         'is_tainted(action.payload) or is_untrusted_source(action.origin)',
         'False',
         (KERNEL_TEST + '::test_taint_escalates_even_a_trusted_receipt',
          INTEGRATION_TEST + '::test_real_kernel_does_not_let_local_guardian_launder_untrusted_task_origin')),
        ('real_worker_callback_forwarding_removed', WORKER,
         'decision = kernel(finalized_action, capability=capability, budget=budget,\n'
         '                              approval_check=approval_check)',
         'decision = kernel(finalized_action, capability=capability, budget=budget)',
         (INTEGRATION_TEST + '::test_real_kernel_satisfies_exact_sealed_terminal_approval_in_auto_mode',)),
    ]


def main() -> None:
    if not PYTHON.is_file():
        raise RuntimeError(f'missing pinned Python: {PYTHON}')
    root = Path(tempfile.mkdtemp(prefix='h277-smart-terminal-mutations-', dir='/tmp'))
    logs = root / 'logs'
    logs.mkdir()
    copied = copy_source(root)
    originals = {name: (root / name).read_bytes() for name in HASHED}
    hashes = {name: sha256(data) for name, data in originals.items()}
    live_before = {name: sha256((REPO / name).read_bytes()) for name in HASHED}
    summary = {'timestamp_utc': datetime.now(UTC).isoformat(), 'python': str(PYTHON),
               'temporary_root': str(root), 'source_and_test_sha256': hashes,
               'copied_python_files': len(copied), 'mutants': []}
    if live_before != hashes:
        summary['status'] = 'source_changed_during_copy'
        OUT.write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n')
        raise RuntimeError('source changed during copy; no mutation run')

    summary['baseline'] = run(root, logs, 'baseline', TEST_FILES)
    baseline = summary['baseline']
    if baseline['returncode'] != 0 or baseline['tests'] == 0 or baseline['failures'] or baseline['errors']:
        summary['status'] = 'invalid_baseline'
        OUT.write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n')
        raise RuntimeError('isolated baseline failed; no mutant counted')

    for name, relative, old, new, selectors in cases():
        item = {'name': name, 'path': relative, 'selectors': list(selectors)}
        try:
            item['mutant_sha256'] = mutate(root, relative, old, new, originals[relative])
            result = run(root, logs, name, selectors)
            item.update(result)
            if result['timed_out'] or result['tests'] == 0 or result['errors']:
                item['outcome'] = 'invalid'
            elif result['returncode'] == 0:
                item['outcome'] = 'survived'
            elif result['failures']:
                item['outcome'] = 'killed'
            else:
                item['outcome'] = 'invalid'
        except Exception as exc:
            item.update({'outcome': 'invalid', 'setup_error': str(exc)})
        finally:
            (root / relative).write_bytes(originals[relative])
        summary['mutants'].append(item)

    summary['restoration_sha256_match'] = all(
        sha256((root / name).read_bytes()) == digest for name, digest in hashes.items())
    summary['restored_baseline'] = run(root, logs, 'restored_baseline', TEST_FILES)
    summary['live_source_sha256_after'] = {name: sha256((REPO / name).read_bytes()) for name in HASHED}
    summary['live_source_unchanged'] = summary['live_source_sha256_after'] == hashes
    summary['counts'] = {kind: sum(item['outcome'] == kind for item in summary['mutants'])
                         for kind in ('killed', 'survived', 'invalid')}
    summary['survivor_gaps'] = [item['name'] for item in summary['mutants']
                                if item['outcome'] == 'survived']
    restored = summary['restored_baseline']
    summary['status'] = ('complete' if summary['restoration_sha256_match']
                         and summary['live_source_unchanged']
                         and restored['returncode'] == 0 and restored['tests'] == baseline['tests']
                         and not restored['failures'] and not restored['errors'] else 'invalid_restoration_or_drift')
    OUT.write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
