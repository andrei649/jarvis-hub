#!/usr/bin/env python3
"""Isolated guardian observer boundary probes; no live source mutations."""
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
OBSERVER = 'agents/core/autonomy/smart_observers.py'
RUNNER = 'agents/core/autonomy/advisory_judgements.py'
JUDGE = 'agents/core/autonomy/approval_judge.py'
EVENTS = 'agents/core/extensions/events.py'
MANIFEST = 'agents/core/extensions/manifest.py'
DISPATCH_TEST = 'tests/test_h485_smart_observer_dispatch.py'
EVENT_TEST = 'tests/test_h485_smart_observer_events.py'
UTILITY = 'docs/hermes/evidence/h277-smart-terminal-mutations-2026-10-03.py'
TESTS = (DISPATCH_TEST, EVENT_TEST)
PUBLIC_CONFIG = 'agents/_system/agents.yaml'
SOURCES = (OBSERVER, RUNNER, JUDGE, EVENTS, MANIFEST)
HASHED = (*SOURCES, *TESTS, UTILITY, PUBLIC_CONFIG,
          'agents/core/security/scanner.py', 'agents/core/log_catalogue.py')
OUT = Path(__file__).with_suffix('.json')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cases():
    return [
        ('request_event_omitted', OBSERVER,
         'report = EXTENSION_EVENTS.emit("approval.smart.requested", **clean)',
         'report = None', (DISPATCH_TEST,)),
        ('committed_post_omitted', RUNNER,
         'decided_after_store(observation, self, snapshot, annotation, stored)',
         'pass', (DISPATCH_TEST,)),
        ('escalation_mislabeled_as_model_deny', OBSERVER,
         'or annotation.verdict not in {"approve", "deny"}',
         'or False', (DISPATCH_TEST + '::test_static_policy_deny_and_escalate_never_emit_decided',)),
        ('shape_scanner_bypassed', EVENTS,
         'redacted = scanner.redact(value)', 'redacted = value',
         (EVENT_TEST + '::test_forced_redaction_preserves_useful_text_with_log_masking_disabled',)),
        ('named_secret_catalogue_bypassed', EVENTS,
         'redacted = catalogue.redact(redacted)', 'redacted = redacted',
         (EVENT_TEST + '::test_named_short_credentials_are_forced_masked',)),
        ('source_truncated_before_scan', EVENTS,
         'redacted = scanner.redact(value)', 'redacted = scanner.redact(value[:200])',
         (EVENT_TEST + '::test_redaction_sees_whole_token_crossing_output_truncation',)),
        ('guardian_inherits_turn_context', EVENTS,
         'context=contextvars.Context()', 'context=None',
         (EVENT_TEST + '::test_guardian_delivery_does_not_inherit_request_or_turn_context',)),
        ('native_retry_emits_duplicate_request', OBSERVER,
         'if observation.requested or _identity(snapshot) != observation.identity:',
         'if _identity(snapshot) != observation.identity:',
         (DISPATCH_TEST + '::test_native_retry_emits_one_request_and_one_decision',)),
        ('failed_parent_reenabled_by_child', OBSERVER,
         'token = _CURRENT.set(observation if observation is not None else _DISABLED)',
         'token = _CURRENT.set(observation)',
         (DISPATCH_TEST + '::test_parent_preparation_failure_is_not_retried_in_wait_for_child',)),
    ]

def main():
    spec = importlib.util.spec_from_file_location('h277_mutation_helpers', REPO / UTILITY)
    utility = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(utility)
    utility.PYTHON = Path(sys.executable)
    root = Path(tempfile.mkdtemp(prefix='h485-observer-mutations-', dir='/tmp'))
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
