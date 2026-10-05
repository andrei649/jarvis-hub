"""Reachable board project/workspace metadata, not helper-only linkage."""

import subprocess

import pytest

from agents.core.kanban.context import KanbanContext, kanban_scope
from agents.core.kanban.upstream import kanban_db as kb
from agents.core.kanban.upstream import projects_db as pdb
from tests.test_hermes_kanban_dashboard import _client


@pytest.fixture
def board_projects(tmp_path, monkeypatch):
    root = tmp_path / 'repos'
    root.mkdir()
    repo = root / 'repo'
    repo.mkdir()
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    folder = root / 'folder'
    folder.mkdir()
    home = tmp_path / 'home'
    monkeypatch.setenv('JARVIS_FILE_ROOTS', str(root))
    with kanban_scope(KanbanContext(home=home, profile='owner', can_mutate=True)), pdb.connect_closing() as conn:
        project = pdb.create_project(conn, name='Repo', primary_path=str(repo))
        archived = pdb.create_project(conn, name='Archived')
        pdb.archive_project(conn, archived)
    return _client(home), home, root, repo, folder, project, archived


def test_project_linked_board_recommends_actual_workspace_and_creates_task(board_projects):
    client, home, _, repo, _, project, _ = board_projects
    response = client.post('/api/kanban/boards', json={'slug': 'linked', 'project_id': project})
    assert response.status_code == 200, response.text
    meta = response.json()['board']
    assert (meta['project_id'], meta['project_name'], meta['default_workspace_kind']) == (project, 'Repo', 'worktree')
    assert meta['default_workdir'] == str(repo)
    listed = next(x for x in client.get('/api/kanban/boards').json()['boards'] if x['slug'] == 'linked')
    assert listed['default_workspace_kind'] == 'worktree' and listed['project_name'] == 'Repo'
    made = client.post('/api/kanban/tasks?board=linked', json={
        'title': 'Actual inherited project', 'triage': True,
        'workspace_kind': listed['default_workspace_kind'],
    })
    assert made.status_code == 200, made.text
    assert made.json()['task']['project_id'] == project
    assert made.json()['task']['workspace_kind'] == 'worktree'
    assert not (home / 'kanban' / 'boards' / 'linked' / 'workspaces').exists()


def test_plain_workdir_and_clear_project_preserve_custom_path(board_projects):
    client, _, _, _, folder, project, _ = board_projects
    created = client.post('/api/kanban/boards', json={
        'slug': 'directory', 'project_id': project, 'default_workdir': str(folder),
    })
    assert created.status_code == 200, created.text
    assert created.json()['board']['default_workspace_kind'] == 'dir'
    cleared = client.patch('/api/kanban/boards/directory', json={'project_id': None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()['board']['project_id'] is None
    assert cleared.json()['board']['default_workdir'] == str(folder)
    made = client.post('/api/kanban/tasks?board=directory', json={
        'title': 'Directory task', 'triage': True, 'workspace_kind': 'dir',
    })
    assert made.status_code == 200, made.text
    assert made.json()['task']['workspace_path'] == str(folder)


def test_omitted_link_is_unchanged_and_explicit_clear_retires_inherited_path(board_projects):
    client, _, _, repo, _, project, _ = board_projects
    assert client.post('/api/kanban/boards', json={'slug': 'linked', 'project_id': project}).status_code == 200
    renamed = client.patch('/api/kanban/boards/linked', json={'name': 'Renamed'})
    assert renamed.json()['board']['project_id'] == project
    assert renamed.json()['board']['default_workdir'] == str(repo)
    cleared = client.patch('/api/kanban/boards/linked', json={'project_id': ''})
    assert cleared.json()['board']['project_id'] is None
    assert cleared.json()['board']['default_workdir'] is None
    assert cleared.json()['board']['default_workspace_kind'] == 'scratch'


@pytest.mark.parametrize('bad', ['unknown', 'archived'])
def test_invalid_project_is_refused_before_board_creation(board_projects, bad):
    client, home, _, _, _, _, archived = board_projects
    value = archived if bad == 'archived' else 'missing-project'
    result = client.post('/api/kanban/boards', json={'slug': 'refused', 'project_id': value})
    assert result.status_code == 400, result.text
    assert not (home / 'kanban' / 'boards' / 'refused').exists()


def test_invalid_workdir_and_revoked_roots_do_not_write_metadata(board_projects, monkeypatch, tmp_path):
    client, home, root, _, folder, _, _ = board_projects
    assert client.post('/api/kanban/boards', json={'slug': 'safe'}).status_code == 200
    with kanban_scope(KanbanContext(home=home, profile='owner', can_mutate=True)):
        path = kb.board_metadata_path('safe')
    before = path.read_bytes()
    outside = tmp_path / 'outside'
    outside.mkdir()
    link = root / 'escape'
    link.symlink_to(outside, target_is_directory=True)
    for workdir in [str(outside), str(link)]:
        refused = client.patch('/api/kanban/boards/safe', json={'default_workdir': workdir, 'name': 'Forged'})
        assert refused.status_code == 403, refused.text
        assert path.read_bytes() == before
    assert client.patch('/api/kanban/boards/safe', json={'default_workdir': str(folder)}).status_code == 200
    before = path.read_bytes()
    monkeypatch.setenv('JARVIS_FILE_ROOTS', str(outside))
    assert client.get('/api/kanban/boards').status_code == 403
    assert client.patch('/api/kanban/boards/safe', json={'name': 'Revoked'}).status_code == 403
    assert path.read_bytes() == before


def test_board_metadata_write_requires_owner_mutation_scope(board_projects):
    _, home, _, _, _, project, _ = board_projects
    denied = _client(home, mutate=False).post('/api/kanban/boards', json={'slug': 'denied', 'project_id': project})
    assert denied.status_code == 403
    assert not (home / 'kanban' / 'boards' / 'denied').exists()
