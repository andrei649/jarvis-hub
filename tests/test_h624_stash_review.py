"""Real Git repo under pytest tmp; no hooks/network/native mutations."""
import subprocess

import pytest

from agents.core import hub_update_apply as update


def git(root, *args):
    return subprocess.run(['git', '-c', 'user.name=Review', '-c', 'user.email=review@localhost',
                           '-c', 'core.hooksPath=/dev/null', *args], cwd=root, check=True,
                          capture_output=True, text=True).stdout.strip()


def test_stash_does_not_apply_cleanly_to_a_different_baseline(tmp_path, monkeypatch):
    git(tmp_path, 'init')
    (tmp_path / 'owner.txt').write_text('baseline\n')
    git(tmp_path, 'add', 'owner.txt')
    git(tmp_path, 'commit', '-m', 'baseline')
    baseline = git(tmp_path, 'rev-parse', 'HEAD')
    (tmp_path / 'owner.txt').write_text('private edit\n')
    git(tmp_path, 'stash', 'push', '-m', 'owner state')
    stash = git(tmp_path, 'rev-parse', 'stash@{0}')
    (tmp_path / 'other.txt').write_text('external commit\n')
    git(tmp_path, 'add', 'other.txt')
    git(tmp_path, 'commit', '-m', 'external concurrent change')
    assert git(tmp_path, 'rev-parse', 'HEAD') != baseline
    monkeypatch.setattr(update.hub_update, 'repo_root', lambda: tmp_path)
    receipt = {'stash': stash, 'stash_parent': baseline, 'from': baseline}
    assert update._restore_stash(receipt, lambda _: None) is False
    assert receipt['stash_restored'] is False
    assert receipt['action_needed']
    assert (tmp_path / 'owner.txt').read_text() == 'baseline\n'
    assert git(tmp_path, 'rev-parse', 'stash@{0}') == stash


@pytest.mark.parametrize('stash', [7, 0, False, [], ''])
def test_invalid_stash_is_named_refusal_not_exception(stash):
    receipt = {'stash': stash, 'stash_parent': 'a'*40, 'from': 'a'*40}
    assert update._restore_stash(receipt, lambda _: None) is False
    assert receipt['stash_restored'] is False


@pytest.mark.parametrize('mode', ['success', 'unreadable', 'partial', 'wrong_parent', 'untracked'])
def test_exact_baseline_outcomes_preserve_stash(tmp_path, monkeypatch, mode):
    git(tmp_path, 'init')
    (tmp_path / 'owner.txt').write_text('baseline\n')
    git(tmp_path, 'add', 'owner.txt')
    git(tmp_path, 'commit', '-m', 'baseline')
    baseline = git(tmp_path, 'rev-parse', 'HEAD')
    (tmp_path / 'owner.txt').write_text('private edit\n')
    git(tmp_path, 'stash', 'push', '-m', 'owner state')
    stash = git(tmp_path, 'rev-parse', 'stash@{0}')
    receipt = {'stash': stash, 'stash_parent': baseline, 'from': baseline}
    monkeypatch.setattr(update.hub_update, 'repo_root', lambda: tmp_path)
    original_git = update._git
    calls = []
    def checked(*args, **kwargs):
        calls.append(args)
        if mode == 'unreadable' and args[0] == 'status':
            return 128, '', 'unreadable'
        if mode == 'partial' and args[:2] == ('stash', 'apply'):
            (tmp_path / 'owner.txt').write_text('partial conflict\n')
            return 1, '', 'partial apply fixture'
        if mode == 'wrong_parent' and args[0] == 'rev-parse' and any(str(a).endswith('^1^{commit}') for a in args):
            return 0, 'd'*40, ''
        return original_git(*args, **kwargs)
    monkeypatch.setattr(update, '_git', checked)
    if mode == 'untracked':
        (tmp_path / 'external.txt').write_text('new owner state')
    restored = update._restore_stash(receipt, lambda _: None)
    assert restored is (mode == 'success')
    assert receipt['stash_restored'] is restored
    assert git(tmp_path, 'rev-parse', 'stash@{0}') == stash
    expected = 'private edit\n' if mode == 'success' else 'partial conflict\n' if mode == 'partial' else 'baseline\n'
    assert (tmp_path / 'owner.txt').read_text() == expected
    assert not any(args[0] in ('reset', 'clean') or args[:2] in [('stash', 'drop'), ('stash', 'pop')] for args in calls)
    if not restored:
        assert receipt['action_needed']
        receipt.update(kind='update', migrations=False)
        assert update._rollback_result(receipt, baseline) == ('rollback_incomplete', 'owner_stash_not_restored')
