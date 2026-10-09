"""Contextual execution through the actual skill and model tool registrars."""

from types import SimpleNamespace

import pytest

from agents.core import code_tools
from agents.core.code_env import CodeEnvRegistry
from agents.core.kernel import Decision, Verdict
from agents.core.skills.loader import Skill
from agents.core.skills.tools import register_skill_tools
from tests.test_code_tools import OWNER, _session_tool, _tool


@pytest.mark.asyncio
@pytest.mark.parametrize(('resident', 'fallback'), [(False, False), (True, False), (True, True)])
async def test_registered_model_project_skill_environment_and_imported_rpc(tmp_path, resident, fallback):
    project = tmp_path / 'project'
    project.mkdir()
    (project / 'project_module.py').write_text('VALUE = 42\n')
    (project / 'data.txt').write_text('synthetic project')
    factory = _session_tool if resident else _tool
    server, host = factory(tmp_path / 'runtime')
    # Existing fixture simulates isolation; this opt-in is only a test transport.
    host._sandbox()._allow_host_context_for_tests = True
    if fallback:
        host._kernels._backend._available = lambda: False

    grants = []

    def authorize(action):
        grants.append(action)
        return Decision(Verdict.GRANT)

    authorize.revalidate = lambda action: Decision(Verdict.GRANT)
    def settings(key, default):
        return {
            code_tools.SETTING: True, code_tools.SESSION_SETTING: resident,
            'llm.execute_code_project_root': str(project),
        }.get(key, default)
    registry = CodeEnvRegistry()
    skill = Skill('synthetic', tmp_path, {'description': 'synthetic service',
        'required_environment_variables': [{'name': 'CUSTOM_SERVICE_KEY'}]})
    skill.owner_vouched = True
    skill.view_files = {'SKILL.md': b'Read the synthetic service.'}
    loader = SimpleNamespace(skills={skill.name: skill}, catalog_gate=lambda skill, actor: '')
    register_skill_tools(server, loader=lambda: loader, environment_registry=registry,
        principal=lambda: 'owner', session_id=host._session_id)
    code_tools.register_code_tools(server, sandbox=host._sandbox, settings=settings,
        principal=lambda: OWNER, session_id=host._session_id, kernels=host._kernels,
        authorizer=authorize, environment_registry=registry,
        environment_source={'CUSTOM_SERVICE_KEY': 'synthetic-only', 'OPENAI_API_KEY': 'forbidden'})
    try:
        viewed = await server.handle({'tool': 'skill_view', 'args': {'name': skill.name}}, actor='friday')
        assert viewed['result']['ok']
        reply = await server.handle({'tool': 'execute_code', 'args': {'code':
            "import project_module, pathlib, os\nfrom jarvis_tools import echo\n"
            "print(project_module.VALUE, pathlib.Path('data.txt').read_text(), "
            "os.environ.get('CUSTOM_SERVICE_KEY'), 'OPENAI_API_KEY' in os.environ, "
            "echo('rpc')['result']['echo'])"}}, actor='friday')
        assert reply['ok'], reply
        result = reply['result']
        assert result['ok'], result
        assert result['stdout'].strip() == '42 synthetic project synthetic-only False rpc'
        assert result['execution_context']['mode'] == 'project'
        assert result['tool_calls'] == 1
        assert len(grants) == 1
        if fallback:
            assert result['session'] is False
    finally:
        if host._kernels:
            await host._kernels.shutdown()


@pytest.mark.asyncio
async def test_contextual_oneshot_requires_grant_before_reading_environment(tmp_path):
    server, host = _tool(tmp_path)
    reads = []

    def values(name):
        reads.append(name)
        return 'synthetic-only'

    code_tools.register_code_tools(server, sandbox=host._sandbox, settings=host._settings,
        principal=lambda: OWNER, session_id=host._session_id,
        environment_registry=CodeEnvRegistry(), environment_source=values)
    result = (await server.handle({'tool': 'execute_code', 'args': {'code': "print('unapproved')"}},
                                  actor='friday'))['result']
    assert not result['ok']
    assert result['reason'] == code_tools.SESSION_DENIED
    assert reads == []
