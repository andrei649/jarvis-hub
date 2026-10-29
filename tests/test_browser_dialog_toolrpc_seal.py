"""A sensitive gated proposal is sanitized before ToolRPC's durable intake."""
from __future__ import annotations

import pytest

from agents.core.tool_rpc import ToolRPCServer, ToolRPCValidationError


def _registered_seal(_actor, _args):
    raise ToolRPCValidationError('dialog_stale')


def _changed_seal(_actor, _args):
    raise ToolRPCValidationError('dialog_changed')


def _registered_intake(_actor, _args):
    return 7


def _registered_handler(_args):
    return {'ok': False, 'reason': 'private_dispatch_required'}


def test_sensitive_sealer_is_part_of_exact_registration_identity():
    from agents.core.autonomy.consent_registration import trusted_registration_key

    server = ToolRPCServer()
    server.register_tool(
        'browser_dialog', _registered_handler, gated=True, trusted_execution=True,
        gated_seal=_registered_seal, gated_intake=_registered_intake,
        consent_revision='nerva.browser_dialog.v1',
    )
    spec = server._tools['browser_dialog']
    assert spec['_consent_registration_key'] is not None
    assert spec['_consent_registration_key'] == trusted_registration_key('browser_dialog', spec)
    changed = dict(spec, gated_seal=_changed_seal)
    assert trusted_registration_key('browser_dialog', changed) != spec['_consent_registration_key']
    assert trusted_registration_key('browser_dialog', dict(spec, mystery_callback=_changed_seal)) is None


@pytest.mark.asyncio
async def test_sealed_gated_intake_only_sees_reference_and_releases_after_binding():
    seen = []

    class Lease:
        args = {'opener_task_id': 9, 'prompt_ref': 'private-ref'}

        def __init__(self):
            self.bound = None
            self.released = False

        def bind(self, task_id):
            self.bound = task_id

        def release(self):
            self.released = True

    lease = Lease()
    server = ToolRPCServer()
    server.register_tool(
        'browser_dialog', lambda _args: None, gated=True, trusted_execution=True,
        input_schema={'type': 'object', 'properties': {'prompt_text': {'type': 'string'}}},
        gated_seal=lambda _actor, _args: lease,
        gated_intake=lambda _actor, args: seen.append(args) or 7,
    )
    result = await server.handle({'tool': 'browser_dialog',
                                  'args': {'opener_task_id': 9, 'prompt_text': 'secret-marker'}})
    assert result == {'ok': False, 'reason': 'approval_required',
                      'tool': 'browser_dialog', 'task_id': 7}
    assert seen == [{'opener_task_id': 9, 'prompt_ref': 'private-ref'}]
    assert lease.bound == 7
    assert lease.released is True


@pytest.mark.asyncio
async def test_sealed_gated_intake_wipes_on_preflight_refusal():
    class Lease:
        args = {'prompt_ref': 'private-ref'}

        def __init__(self):
            self.released = False

        def bind(self, _task_id):
            raise AssertionError('no row was created')

        def release(self):
            self.released = True

    lease = Lease()

    def deny(_args):
        raise ToolRPCValidationError('dialog_stale')

    server = ToolRPCServer()
    server.register_tool(
        'browser_dialog', lambda _args: None, gated=True, trusted_execution=True,
        gated_seal=lambda _actor, _args: lease,
        preflight=deny,
        gated_intake=lambda _actor, _args: 7,
    )
    result = await server.handle({'tool': 'browser_dialog',
                                  'args': {'prompt_text': 'secret-marker'}})
    assert result == {'ok': False, 'reason': 'dialog_stale', 'tool': 'browser_dialog'}
    assert lease.released is True
