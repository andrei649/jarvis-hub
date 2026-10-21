"""H441: owner selection is strict, full-store, and never mutates active state."""
import io
import json

import pytest

from agents.cli.nerva import EXIT_FAILED, EXIT_OK, Context, build_parser, main
from agents.core import session_selectors
from agents.core.checkpoint import CheckpointManager


@pytest.fixture
def store(tmp_path):
    manager = CheckpointManager(str(tmp_path / 'checkpoints.db'))
    manager.initialize()
    yield manager
    manager.close()


def put(manager, sid, started, *, ended=None, title='', archived=False):
    meta = {'title': title}
    if archived:
        meta['archived_at'] = started
    with manager._lock, manager._conn:
        manager._conn.execute('INSERT INTO sessions(id,started_at,ended_at,metadata) VALUES(?,?,?,?)',
                              (sid, started, ended, json.dumps(meta)))


def test_exact_id_precedes_reserved_latest_and_full_table(store):
    for index in range(26):
        put(store, f'older_{index}', f'2026-01-{index + 1:02d}T00:00:00+00:00')
    put(store, 'latest', '2026-01-01T00:00:00+00:00')
    assert session_selectors.resolve(store, 'latest') == 'latest'
    assert session_selectors.resolve(store, 'latest', latest_mode=True) == 'older_25'
    assert session_selectors.resolve(store, 'older_0') == 'older_0'


def test_unique_prefix_title_and_ambiguity_do_not_select(store):
    put(store, 'alpha_111', '2026-01-01T00:00:00+00:00', title='  Project  Atlas ')
    put(store, 'alpha_222', '2026-01-02T00:00:00+00:00', title='project atlas')
    put(store, 'beta_333', '2026-01-03T00:00:00+00:00', title='Other')
    assert session_selectors.resolve(store, 'beta_') == 'beta_333'
    for selector in ('alpha_', 'PROJECT ATLAS'):
        with pytest.raises(session_selectors.SessionSelectionError) as caught:
            session_selectors.resolve(store, selector)
        assert caught.value.status == 409
        assert {row['id'] for row in caught.value.candidates} == {'alpha_111', 'alpha_222'}
    with pytest.raises(session_selectors.SessionSelectionError) as caught:
        session_selectors.resolve(store, 'missing')
    assert caught.value.status == 404


def test_latest_excludes_archived_but_exact_can_select_it(store):
    put(store, 'active', '2026-01-01T00:00:00+00:00', ended='2026-01-02T00:00:00+00:00')
    put(store, 'archived', '2026-01-03T00:00:00+00:00', archived=True)
    assert session_selectors.resolve(store, 'anything', latest_mode=True) == 'active'
    assert session_selectors.resolve(store, 'archived') == 'archived'


def test_unreadable_store_does_not_look_empty(store):
    store._conn.execute('DROP TABLE sessions')
    with pytest.raises(session_selectors.SessionSelectionError) as caught:
        session_selectors.resolve(store, 'latest')
    assert caught.value.status == 503


class _Hub:
    def __init__(self, *, refuse=False):
        self.calls = []
        self.refuse = refuse

    def post(self, path, body):
        self.calls.append((path, body))
        if path == '/sessions/resolve':
            from agents.cli.client import HubError
            if self.refuse:
                raise HubError(409, 'ambiguous')
            return {'session_id': 'chosen', 'recap': {'text': 'previous text'}}
        if path == '/chat':
            return {'reply': 'answer', 'session_id': body.get('session_id')}
        raise AssertionError(path)


def test_cli_resume_latest_recap_and_failure_never_chat():
    assert build_parser().parse_args(['chat', '-c', 'hello']).continue_latest
    for flags, latest in [(['-c'], True), (['-r', 'my title'], False)]:
        hub = _Hub()
        out, err = io.StringIO(), io.StringIO()
        ctx = Context(environ={}, out=out, err=err, inp=io.StringIO(), client_factory=lambda _, hub=hub: hub)
        assert main(['chat', '-z', *flags, 'hello'], context=ctx) == EXIT_OK
        assert out.getvalue() == 'answer\n'
        assert 'previous text' in err.getvalue()
        assert hub.calls[0] == ('/sessions/resolve', {'selector': 'latest' if latest else 'my title',
                                                        'latest_mode': latest})
        assert hub.calls[1][1]['session_id'] == 'chosen'
    hub = _Hub(refuse=True)
    ctx = Context(environ={}, out=io.StringIO(), err=io.StringIO(), inp=io.StringIO(),
                  client_factory=lambda _: hub)
    assert main(['chat', '-z', '-r', 'duplicate', 'hello'], context=ctx) == EXIT_FAILED
    assert [call[0] for call in hub.calls] == ['/sessions/resolve']
