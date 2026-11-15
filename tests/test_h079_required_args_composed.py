"""Consented extension metadata reaches menus without changing dispatch authority."""
from types import SimpleNamespace

import pytest

from agents.core.commands import ADMIN, Principal, build_default_registry
from agents.web import _telegram_command_menus
from tests.test_extension_runtime import descriptor
from tests.test_extension_runtime import rig as rig


@pytest.mark.asyncio
async def test_real_activation_projects_required_arguments_out_of_menu_but_keeps_owner_dispatch(rig):
    registry = rig.runtime.commands = build_default_registry()
    rig.packages.write('''
def register():
    return {"tools": [], "commands": ["boat_report", "boat_ping"], "events": []}
def command(name, args):
    return name + ": " + args
''')
    manifest = descriptor(tools=[], commands=['boat_report', 'boat_ping'],
                          command_requires_args=['boat_report'])
    rig.consent.grant(manifest)
    await rig.runtime.activate(manifest)
    try:
        required, optional = registry.get('boat_report'), registry.get('boat_ping')
        assert required.tier == optional.tier == ADMIN
        assert required.requires_args is True and optional.requires_args is False
        assert '<arguments>' in required.summary
        orch = SimpleNamespace(commands=registry, get_setting=lambda key, default=None:
                               '4242' if key == 'autonomy.owner_chat_id' else default)
        everyone, owner = _telegram_command_menus(orch)
        assert owner[0] == 4242
        assert 'boat_ping' in {row['command'] for row in owner[1]}
        assert 'boat_report' not in {row['command'] for row in owner[1]}
        assert not {'boat_report', 'boat_ping'} & {row['command'] for row in everyone}
        count = len(rig.runner.calls)
        guest = await registry.dispatch('/boat_report today', orch=orch,
                                        principal=Principal(channel='telegram'))
        assert guest.status == 'refused' and len(rig.runner.calls) == count
        result = await registry.dispatch('/boat_report today', orch=orch,
                                         principal=Principal(admin=True))
        assert result.status == 'answered' and result.reply == 'boat_report: today'
        rig.consent.revoke('boats')
        denied = await registry.dispatch('/boat_report today', orch=orch,
                                         principal=Principal(admin=True))
        assert denied.status == 'failed'
    finally:
        await rig.runtime.deactivate('boats')


def test_cli_consent_preserves_required_argument_metadata(tmp_path):
    import io
    import json

    from agents.cli.nerva import Context, main
    from tests.test_extension_manifest import descriptor as raw_descriptor

    path = tmp_path / 'boats.json'
    path.write_text(json.dumps(raw_descriptor(command_requires_args=['boats_summary'])))
    posted = []

    def post(route, body):
        posted.append((route, body))
        return {'ok': True, 'revoked': False, 'consent': 'granted', 'declared_digest': 'a' * 64}

    context = Context(environ={}, out=io.StringIO(), err=io.StringIO(),
                      client_factory=lambda _: SimpleNamespace(post=post))
    assert main(['extensions', 'consent', str(path)], context=context) == 0
    assert posted[0][1]['manifest']['command_requires_args'] == ['boats_summary']


def test_offline_doctor_exposes_required_argument_declaration_without_activation(tmp_path):
    import json

    from agents.core.extensions.doctor import doctor_paths
    from tests.test_extension_manifest import descriptor as raw_descriptor

    path = tmp_path / 'boats.json'
    path.write_text(json.dumps(raw_descriptor(command_requires_args=['boats_summary'])))
    report = doctor_paths([path])
    row = report['extensions'][0]
    assert row['command_requires_args'] == ['boats_summary']
    assert row['execution_available'] is False and row['callable_commands'] == []
