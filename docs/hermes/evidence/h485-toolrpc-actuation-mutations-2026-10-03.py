#!/usr/bin/env python3
"""Isolated authority/feedback faults; live source is never modified."""
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
RPC = 'agents/core/tool_rpc.py'
QUEUE = 'agents/core/autonomy/queue.py'
WORKER = 'agents/core/autonomy/worker.py'
REVIEW = 'agents/core/autonomy/terminal_review.py'
RUNTIME = 'agents/core/agent_runtime.py'
OUTCOMES = 'agents/core/approval_outcomes.py'
INTEGRATION = 'tests/test_h485_toolrpc_actuation_integration.py'
NAMED = 'tests/test_h485_named_worker_execution.py'
PROOF = 'tests/test_h485_smart_execution_completion.py'
TESTS = (INTEGRATION, NAMED, PROOF, 'tests/test_h485_same_turn_queue_feedback.py',
         'tests/test_h485_toolrpc_review_seam.py')
SOURCES = (RPC, QUEUE, WORKER, REVIEW, RUNTIME, OUTCOMES,
           'agents/core/orchestrator.py', 'agents/core/autonomy_coordinator.py')
UTILITY = 'docs/hermes/evidence/h277-smart-terminal-mutations-2026-10-03.py'
PUBLIC_CONFIG = 'agents/_system/agents.yaml'
HASHED = (*SOURCES, *TESTS, UTILITY, PUBLIC_CONFIG,
          'tests/test_h277_smart_terminal_integration.py')
OUT = Path(__file__).with_suffix('.json')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cases():
    return [
        ('post_intake_review_skipped', RPC, 'review = spec.get("gated_review")', 'review = None',
         (INTEGRATION + '::test_two_native_approvals_execute_in_their_invocations_through_real_kernel',)),
        ('named_selection_ignored', QUEUE, 'clause += " AND id=?"\n            params.append(task_id)',
         'pass', (NAMED + '::test_named_tick_executes_only_selected_approved_task',)),
        ('registration_revocation_ignored', REVIEW, 'registration_is_live() is True and ', '',
         (INTEGRATION + '::test_replaced_terminal_registration_during_review_cannot_actuate',)),
        ('completion_proof_not_required', REVIEW, 'if not queue.verify_smart_terminal_result(task_id):',
         'if False:', (INTEGRATION + '::test_synthetic_done_without_worker_execution_cannot_report_success',)),
        ('completion_signature_not_checked', QUEUE,
         'return self._mediation_signer.verify(canonical_json(core), signature)', 'return True',
         (PROOF + '::test_tampered_persisted_bytes_or_receipt_fail_completion_proof',)),
        ('completion_result_digest_not_bound', QUEUE,
         'or proof["result_sha256"] != result_sha256', 'or False',
         (PROOF + '::test_tampered_persisted_bytes_or_receipt_fail_completion_proof',)),
        ('same_batch_breaker_disabled', RUNTIME,
         "if approval_state.get('guardian_stopped'):", 'if False:',
         (INTEGRATION + '::test_denial_breaker_blocks_fourth_gated_operation_in_one_provider_batch',)),
        ('model_tools_not_withdrawn', RUNTIME,
         'tools=[] if guardian_stopped else tools,', 'tools=tools,',
         (INTEGRATION + '::test_three_denials_warn_model_in_same_turn_and_stop_fourth_operation',)),
        ('unseen_truncated_feedback_acknowledged', OUTCOMES,
         "if item['revision'] in context._visible_invocation_revisions]", 'if True]',
         (INTEGRATION + '::test_truncated_denial_is_retained_for_next_turn_instead_of_acknowledged',)),
    ]


def main():
    spec = importlib.util.spec_from_file_location('h277_mutation_helpers', REPO / UTILITY)
    utility = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(utility)
    utility.PYTHON = Path(sys.executable)
    root = Path(tempfile.mkdtemp(prefix='h485-actuation-mutations-', dir='/tmp'))
    logs = root / 'logs'
    logs.mkdir()
    names = subprocess.check_output(['git', 'ls-files', '-z', '--', 'agents', 'tests'], cwd=REPO)
    paths = [os.fsdecode(p) for p in names.split(b'\0') if p and p.endswith(b'.py')]
    for name in dict.fromkeys([*paths, *SOURCES, *TESTS, PUBLIC_CONFIG, 'pytest.ini']):
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
        if data.count(old) != 1:
            raise RuntimeError(f'{name}: expected one exact anchor, found {data.count(old)}')
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
