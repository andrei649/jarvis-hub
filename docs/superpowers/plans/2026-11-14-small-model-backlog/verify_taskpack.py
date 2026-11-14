"""Offline checks of planning-helper safeguards; no application tests or state changes."""

import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import taskpack


class PlanningChecks(unittest.TestCase):
    def cli(self, *args):
        output = io.StringIO()
        with patch.object(sys, 'argv', ['taskpack.py', *args]), contextlib.redirect_stdout(output):
            result = taskpack.main()
        return result, output.getvalue()

    def test_exact_coverage_and_source_fingerprints(self):
        result = taskpack.validate(check_source=True)
        self.assertTrue(result['ok'], result['errors'])
        self.assertEqual(result['contracts'], 697)
        self.assertEqual(result['backlog_records'], 93)

    def test_unknown_dependency_rejected(self):
        tasks = copy.deepcopy(taskpack.packets())
        tasks[0]['depends_on'].append('SM-UNKNOWN')
        with patch.object(taskpack, 'packets', return_value=tasks):
            self.assertIn('unknown dependency', ' '.join(taskpack.validate()['errors']))

    def test_dependency_cycle_rejected(self):
        tasks = copy.deepcopy(taskpack.packets())
        tasks[0]['depends_on'] = [tasks[0]['id']]
        with patch.object(taskpack, 'packets', return_value=tasks):
            self.assertIn('dependency cycle', ' '.join(taskpack.validate()['errors']))

    def test_missing_contract_rejected(self):
        with patch.object(taskpack, 'contracts', return_value=taskpack.contracts()[:-1]):
            self.assertFalse(taskpack.validate()['ok'])

    def test_production_drift_rejected(self):
        original_read = taskpack.read
        with tempfile.TemporaryDirectory() as root:
            Path(root, 'production.py').write_text('changed\n')

            def read(name):
                if name == 'catalog/source-fingerprints.json':
                    return {'production.py': hashlib.sha256(b'original\n').hexdigest()}
                value = original_read(name)
                if name == 'catalog/coverage.json':
                    value['input_sha256'] = {}
                return value

            with patch.object(taskpack, 'ROOT', Path(root)), patch.object(taskpack, 'read', side_effect=read):
                result, output = self.cli('next')
            self.assertEqual(result, 1)
            self.assertIn('production.py', output)

    def test_selection_respects_dependencies_and_file_ownership(self):
        tasks = {t['id']: t for t in taskpack.packets()}
        result, output = self.cli('next', '--done', 'SM-008', '--active', 'SM-009', '--limit', '8')
        self.assertEqual(result, 0)
        selected = json.loads(output)['assignments']
        self.assertTrue(selected)
        accepted = {ident for ident, task in tasks.items() if task['spec_state'] == 'implemented'}
        locked = set(tasks['SM-009']['owned_files'])
        for item in selected:
            task = tasks[item['id']]
            self.assertEqual(task['spec_state'], 'ready')
            self.assertTrue(set(task['depends_on']) <= ({'SM-008'} | accepted))
            self.assertFalse(locked & set(task['owned_files']))
            locked.update(task['owned_files'])

    def test_reviewed_implementations_are_not_reassigned_and_satisfy_dependencies(self):
        tasks = copy.deepcopy(taskpack.packets())
        restored = next(task for task in tasks if task['id'] == 'SM-008')
        restored['spec_state'] = 'implemented'
        restored['implementation_evidence'] = 'Reviewed local regression evidence; full CI pending.'
        with patch.object(taskpack, 'packets', return_value=tasks):
            result, output = self.cli('next', '--done', 'SM-001', 'SM-002', 'SM-003',
                                      'SM-004', 'SM-005', 'SM-006', 'SM-007', '--limit', '8')
        self.assertEqual(result, 0, output)
        selected = {row['id'] for row in json.loads(output)['assignments']}
        self.assertNotIn('SM-008', selected)
        self.assertIn('SM-009', selected)

    def test_implemented_state_requires_review_evidence(self):
        tasks = copy.deepcopy(taskpack.packets())
        tasks[0]['spec_state'] = 'implemented'
        tasks[0].pop('implementation_evidence', None)
        with patch.object(taskpack, 'packets', return_value=tasks):
            self.assertIn('implemented state requires reviewer evidence',
                          ' '.join(taskpack.validate()['errors']))

    def test_pagination_preserves_complete_packet(self):
        packet = taskpack.packets()[0]
        expected = json.dumps(packet, ensure_ascii=False, indent=2)
        chunks = []
        for part in range(1, (len(expected) + 499) // 500 + 1):
            result, output = self.cli('show', packet['id'], '--chars', '500', '--part', str(part))
            self.assertEqual(result, 0)
            chunks.append(output.split('\n', 1)[1][:-1])
        self.assertEqual(''.join(chunks), expected)

    def test_unknown_id_and_conflicting_assignment_rejected(self):
        for args in [('show', 'SM-UNKNOWN'), ('next', '--done', 'SM-008', '--active', 'SM-008')]:
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    self.cli(*args)
                self.assertEqual(raised.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
