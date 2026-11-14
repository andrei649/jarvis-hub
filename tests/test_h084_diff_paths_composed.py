"""Literal path selection reaches the real session checkpoint comparator."""
from __future__ import annotations

import pytest

from agents.core import file_tools
from agents.core.file_checkpoint_history import FileCheckpointHistory
from agents.core.file_tools import FileScope, SnapshotStore
from tests.test_h084_diff_session_command import _dispatch, _scope


@pytest.mark.asyncio
async def test_session_selected_directory_excludes_sibling_and_preserves_deleted_paths(tmp_path, monkeypatch):
    root = tmp_path / 'project'
    root.mkdir()
    _scope(monkeypatch, root)
    directory = tmp_path / 'private' / 'snapshots'
    original = file_tools.data_path
    monkeypatch.setattr(file_tools, 'data_path',
                        lambda *parts: directory if parts == ('file_tools', 'snapshots')
                        else original(*parts))
    (root / 'src').mkdir()
    (root / 'src-old').mkdir()
    (root / 'src' / 'Keep Case.txt').write_text('before selected\n')
    (root / 'src' / 'deleted.txt').write_text('removed selected\n')
    (root / 'src-old' / 'private.txt').write_text('before unrelated\n')
    history = FileCheckpointHistory(SnapshotStore(), FileScope([root]))
    scope = history.begin_scope(root, source_kind='terminal_turn', source_key='filter-start')
    history.finish_scope(scope['id'], reaped=True, run_id=scope['run_id'])
    (root / 'src' / 'Keep Case.txt').write_text('after selected\n')
    (root / 'src' / 'deleted.txt').unlink()
    (root / 'src' / 'added.txt').write_text('new selected\n')
    (root / 'src-old' / 'private.txt').write_text('unrelated-private-body\n')
    reply = (await _dispatch(root, '-- src')).reply
    assert 'approximate' in reply.lower()
    assert '-before selected' in reply and '+after selected' in reply
    assert '-removed selected' in reply and '+new selected' in reply
    assert 'src-old' not in reply and 'unrelated-private-body' not in reply
    stat = (await _dispatch(root, '--stat -- src')).reply
    assert 'added 1' in stat and 'modified 1' in stat and 'deleted 1' in stat
    assert 'selected paths' in stat.lower()
    exact = (await _dispatch(root, '-- "src/Keep Case.txt"')).reply
    assert '+after selected' in exact
    assert 'removed selected' not in exact and 'new selected' not in exact


@pytest.mark.asyncio
async def test_session_invalid_path_never_reads_checkpoint(tmp_path, monkeypatch):
    root = tmp_path / 'project'
    root.mkdir()
    _scope(monkeypatch, root)
    monkeypatch.setattr(FileCheckpointHistory, 'session_diff',
                        lambda *a, **kw: pytest.fail('invalid filter reached checkpoint'))
    for path in ('../secret', '/tmp/secret', 'src/../secret', ':(glob)**'):
        assert 'Usage' in (await _dispatch(root, '-- ' + path)).reply
