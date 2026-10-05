"""Real resident Python protocol with synthetic H595 context and env permissions."""

import asyncio
import json
import sys
import venv

import pytest

from agents.core import code_tools
from agents.core.code_env import CodeEnvRegistry
from agents.core.skills.loader import Skill
from agents.core.skills.tools import register_skill_tools
from tests.test_code_tools import _run, _session_tool


def configure(tool, **values):
    old = tool._settings
    tool._settings = lambda key, default: values.get(key, old(key, default))


@pytest.mark.asyncio
async def test_project_context_imports_local_module_and_relative_data(tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    (project / 'my_project.py').write_text('VALUE = 42\n')
    (project / 'data.txt').write_text('synthetic project')
    (project / '.env').write_text('PRIVATE=hidden')
    (project / 'notes.txt').write_text('private-synthetic')
    _, tool = _session_tool(tmp_path / 'runtime')
    configure(tool, **{'llm.execute_code_project_root': str(project)})
    tool._project_redactor = lambda text: text.replace('private-synthetic', '[redacted]')
    try:
        result = await _run(tool, "import my_project, pathlib\nprint(my_project.VALUE, pathlib.Path('data.txt').read_text(), pathlib.Path('.env').exists())")
        assert result['ok'], result['stderr']
        assert result['stdout'].strip() == '42 synthetic project False'
        assert result['execution_context']['mode'] == 'project'
        assert (await _run(tool, "print(pathlib.Path('notes.txt').exists())"))['stdout'].strip() == 'False'
    finally:
        await tool._kernels.shutdown()


@pytest.mark.asyncio
async def test_strict_does_not_use_project_and_context_change_discards_namespace(tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    (project / 'data.txt').write_text('synthetic')
    _, tool = _session_tool(tmp_path / 'runtime')
    values = {'llm.execute_code_project_root': str(project)}
    old = tool._settings
    tool._settings = lambda key, default: values.get(key, old(key, default))
    try:
        assert (await _run(tool, 'saved = 1'))['ok']
        values['llm.execute_code_mode'] = 'strict'
        result = await _run(tool, "import pathlib\nprint('saved' in globals(), pathlib.Path('data.txt').exists())")
        assert result['stdout'].strip() == 'False False'
        assert result['execution_context']['mode'] == 'strict'
        assert result['state_lost'] is True
        assert len(tool._kernels.status()) == 1
    finally:
        await tool._kernels.shutdown()


@pytest.mark.asyncio
async def test_declared_environment_is_frozen_and_revocation_discards_kernel(tmp_path):
    _, tool = _session_tool(tmp_path)
    registry = CodeEnvRegistry()
    invocation = tool._invocation()
    scope = {'agent': invocation.agent, 'principal': invocation.principal, 'session_id': invocation.session_id}
    registry.declare(**scope, skill_id='synthetic', names=['CUSTOM_SERVICE_KEY'])
    tool._environment_registry = registry
    tool._environment_source = {'CUSTOM_SERVICE_KEY': 'synthetic-value', 'OPENAI_API_KEY': 'forbidden'}
    try:
        result = await _run(tool, "import os\nsaved = 1\nprint(os.environ.get('CUSTOM_SERVICE_KEY'), 'OPENAI_API_KEY' in os.environ)")
        assert result['stdout'].strip() == 'synthetic-value False'
        registry.revoke(**scope)
        result = await _run(tool, "import os\nprint('saved' in globals(), 'CUSTOM_SERVICE_KEY' in os.environ)")
        assert result['stdout'].strip() == 'False False'
        assert len(tool._kernels.status()) == 1
    finally:
        await tool._kernels.shutdown()


@pytest.mark.asyncio
async def test_revocation_while_waiting_refuses_stale_environment_cell(tmp_path):
    _, tool = _session_tool(tmp_path)
    registry = CodeEnvRegistry()
    invocation = tool._invocation()
    scope = {'agent': invocation.agent, 'principal': invocation.principal, 'session_id': invocation.session_id}
    registry.declare(**scope, skill_id='synthetic', names=['CUSTOM_SERVICE_KEY'])
    tool._environment_registry = registry
    tool._environment_source = {'CUSTOM_SERVICE_KEY': 'synthetic-value'}
    pending = record = None
    try:
        assert (await _run(tool, 'saved = 1'))['ok']
        record = next(iter(tool._kernels._records.values()))
        await record.lock.acquire()
        pending = asyncio.create_task(_run(tool, 'saved = 2'))
        await asyncio.sleep(.05)
        registry.revoke(**scope)
        record.lock.release()
        result = await pending
        assert not result['ok']
        assert result['reason'] == 'code_context_changed'
    finally:
        if record and record.lock.locked():
            record.lock.release()
        if pending:
            await asyncio.gather(pending, return_exceptions=True)
        await tool._kernels.shutdown()


@pytest.mark.asyncio
async def test_owner_vouched_skill_view_grants_only_same_actor_session(tmp_path):
    from types import SimpleNamespace

    server, tool = _session_tool(tmp_path)
    invocation = tool._invocation()
    skill = Skill('synthetic', tmp_path, {'description': 'synthetic example',
        'required_environment_variables': [{'name': 'CUSTOM_SERVICE_KEY'}]})
    skill.owner_vouched = True
    skill.view_files = {'SKILL.md': b'Use the synthetic service.'}
    loader = SimpleNamespace(skills={skill.name: skill}, catalog_gate=lambda skill, actor: '')
    registry = CodeEnvRegistry()
    tool._environment_registry = registry
    tool._environment_source = {'CUSTOM_SERVICE_KEY': 'synthetic-only'}
    register_skill_tools(server, loader=lambda: loader, environment_registry=registry,
        principal=lambda: 'owner', session_id=lambda: invocation.session_id)
    try:
        reply = await server.handle({'tool': 'skill_view', 'args': {'name': skill.name}},
                                    actor=invocation.agent)
        assert reply['result']['ok']
        result = await _run(tool, "import os\nprint(os.environ.get('CUSTOM_SERVICE_KEY'))")
        assert result['stdout'].strip() == 'synthetic-only'
        assert not registry.resolve_names(agent='another-agent', principal='owner',
                                          session_id=invocation.session_id)
        assert not registry.resolve_names(agent=invocation.agent, principal='owner',
                                          session_id='another-session')
        skill.owner_vouched = False
        result = await _run(tool, "import os\nprint('CUSTOM_SERVICE_KEY' in os.environ)")
        assert result['stdout'].strip() == 'False'
    finally:
        await tool._kernels.shutdown()


@pytest.mark.asyncio
async def test_backend_local_interpreter_selection_reexec_and_strict_default(tmp_path):
    environment = tmp_path / 'venv'
    venv.EnvBuilder(with_pip=False).create(environment)
    candidate = environment / 'bin' / 'python'
    _, tool = _session_tool(tmp_path / 'runtime')
    tool._environment_registry = CodeEnvRegistry()
    tool._environment_source = {'VIRTUAL_ENV': str(environment)}
    values = {'llm.execute_code_env_passthrough': ['VIRTUAL_ENV']}
    old = tool._settings
    tool._settings = lambda key, default: values.get(key, old(key, default))
    try:
        result = await _run(tool, 'import sys\nprint(sys.executable)')
        assert result['ok'], result['stderr']
        assert result['stdout'].strip() == str(candidate)
        assert result['execution_context']['python'] == str(candidate)
        values['llm.execute_code_mode'] = 'strict'
        result = await _run(tool, 'import sys\nprint(sys.executable)')
        assert result['stdout'].strip() == sys.executable
    finally:
        await tool._kernels.shutdown()


def test_container_context_values_use_stdin_and_project_has_separate_readonly_mount():
    from agents.core.session_kernels import (
        CHILD_RPC_ROOT,
        KernelKey,
        PipeKernelBackend,
        docker_kernel_argv,
    )

    backend = PipeKernelBackend(docker_kernel_argv('python:synthetic'), child_root=CHILD_RPC_ROOT)
    argv = backend._argv(KernelKey('agent', 'owner', 'session', '*'), 'synthetic-token', '/safe/rpc')
    context = {'mode': 'project', 'project_dir': '/safe/project',
               'env': {'CUSTOM_SERVICE_KEY': 'synthetic-never-in-argv'}}
    config = backend._startup_config('synthetic-token', context, '/safe/rpc', argv)
    assert '/safe/project:/nerva-project:ro' in argv
    assert '/safe/project' not in '/safe/rpc'
    assert 'synthetic-never-in-argv' not in repr(argv)
    assert config['execution_context']['env'] == context['env']
    assert config['execution_context']['cwd'] == '/nerva-project'


@pytest.mark.asyncio
async def test_revoke_during_worker_start_sends_no_stale_environment(tmp_path, monkeypatch):
    _, tool = _session_tool(tmp_path)
    registry = CodeEnvRegistry()
    invocation = tool._invocation()
    scope = {'agent': invocation.agent, 'principal': invocation.principal, 'session_id': invocation.session_id}
    registry.declare(**scope, skill_id='synthetic', names=['CUSTOM_SERVICE_KEY'])
    tool._environment_registry = registry
    tool._environment_source = {'CUSTOM_SERVICE_KEY': 'synthetic-value'}
    original = asyncio.create_subprocess_exec
    started, release = asyncio.Event(), asyncio.Event()
    workers = []
    sent = []

    async def delayed_start(*args, **kwargs):
        process = await original(*args, **kwargs)
        workers.append(process)
        write = process.stdin.write

        def capture(data):
            sent.append(data)
            return write(data)

        monkeypatch.setattr(process.stdin, 'write', capture)
        started.set()
        await release.wait()
        return process

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', delayed_start)
    pending = asyncio.create_task(_run(tool, "print('stale worker ran')"))
    try:
        await asyncio.wait_for(started.wait(), 2)
        registry.revoke(**scope)
        release.set()
        result = await asyncio.wait_for(pending, 3)
        assert not result['ok']
        assert result['reason'] == 'code_context_changed'
        assert workers[0].returncode is not None
        assert not tool._kernels.status()
        assert all(json.loads(packet).get('op') == 'close' for packet in sent), (
            'Revoked environment was sent to the waiting worker')
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)
        await tool._kernels.shutdown()
