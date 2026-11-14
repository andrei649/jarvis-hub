"""Unknown persisted update state must never look like an idle hub to restart."""
from pathlib import Path

import pytest

from agents.core import hub_restart_apply as restart


@pytest.fixture
def state(tmp_path, monkeypatch):
    directory = tmp_path / 'update'
    monkeypatch.setattr(restart.hub_update_apply, 'state_dir', lambda: directory)
    monkeypatch.setattr(restart.hub_restart, 'available', lambda: True)
    monkeypatch.setattr(restart.backup, 'boot_restore_due', lambda: False)
    monkeypatch.setattr(restart.backup, 'restore_in_progress', lambda: False)
    restart.hub_update.reset_for_tests()
    yield directory
    restart.hub_update.reset_for_tests()


@pytest.mark.parametrize('contents', ['', '{broken', '[]', 'null', ' ' * (1024 * 1024)])
def test_any_current_state_blocks_without_decoding(state, contents, monkeypatch):
    state.mkdir()
    (state / 'current.json').write_text(contents)
    reads = []

    def unreadable(path, *args, **kwargs):
        reads.append(path)
        raise OSError('unreadable update state')

    monkeypatch.setattr(Path, 'read_text', unreadable)
    assert restart._conflict() is not None
    assert reads == []


def test_absent_directory_and_absent_file_are_allowed(state):
    assert restart._conflict() is None
    state.mkdir()
    assert restart._conflict() is None


@pytest.mark.parametrize('entry_kind', ['directory', 'dangling_symlink'])
def test_nonregular_current_state_blocks(state, entry_kind):
    state.mkdir()
    path = state / 'current.json'
    if entry_kind == 'directory':
        path.mkdir()
    else:
        path.symlink_to(state / 'missing')
    assert restart._conflict() is not None


def test_symlink_state_directory_is_unknown(state):
    target = state.with_name('other')
    target.mkdir()
    state.symlink_to(target, target_is_directory=True)
    assert restart._conflict() == 'state_unavailable'


def test_permission_error_does_not_mean_absent(state, monkeypatch):
    state.mkdir()
    original = Path.lstat

    def denied(path, *args, **kwargs):
        if path == state / 'current.json':
            raise PermissionError('state access denied')
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'lstat', denied)
    assert restart._conflict() == 'state_unavailable'


def test_directory_swap_cannot_prove_absence(state, monkeypatch):
    state.mkdir()
    original = Path.lstat

    def swapped(path, *args, **kwargs):
        if path == state / 'current.json':
            state.rename(state.with_name('old-update'))
            state.mkdir()
            raise FileNotFoundError('old directory no longer selected')
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'lstat', swapped)
    assert restart._conflict() == 'state_unavailable'
