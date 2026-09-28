"""Closed generic ToolRPC provenance groups cards without granting authority."""
from contextlib import contextmanager

import pytest

from agents.core.approval_outcomes import (
    bind_approval_turn,
    close_approval_turn,
    open_approval_turn,
)
from agents.core.autonomy.queue import TaskQueue
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.commands import Principal
from agents.core.tool_rpc import ToolRPCServer


@pytest.fixture
def stack(tmp_path):
    queue=TaskQueue(str(tmp_path/'tasks.db')).initialize()
    worker=AutonomyWorker(queue)
    server=ToolRPCServer(enqueue=worker.govern_enqueue)
    server.register_tool('send_mail',lambda args:None,gated=True)
    yield queue,worker,server
    queue.close()


@contextmanager
def turn(*,session='s',instance='one',sender='owner',channel='web',live=True):
    context=open_approval_turn(session_id=session,session_instance=instance,
        principal=Principal(channel=channel,admin=True,sender=sender,chat='chat'),
        session_is_live=lambda *_:live)
    token=bind_approval_turn(context)
    try:
        yield context
    finally:
        close_approval_turn(context,token)


async def ask(server,args=None,actor='jarvis'):
    return await server.handle({'tool':'send_mail','args':{'to':'ana'} if args is None else args},actor=actor)


@pytest.mark.asyncio
async def test_real_generic_asks_group_two_independent_tasks(stack):
    queue,worker,server=stack
    with turn():
        a,b=await ask(server),await ask(server)
    assert a['reason']==b['reason']=='approval_required' and a['task_id']!=b['task_id']
    group,=queue.pending_groups()
    assert group['count']==2 and group['member_ids']==[a['task_id'],b['task_id']]
    assert len(queue.list(status='blocked'))==2


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['session','instance','sender','registration','args','actor'])
async def test_exact_producer_namespace_and_semantics_isolation(stack,change):
    queue,worker,server=stack
    with turn(channel='telegram'):
        await ask(server)
    kw={'channel':'telegram'}
    args=None
    actor='jarvis'
    if change in ('session','instance','sender'):
        kw[change]='other'
    elif change=='registration':
        server.register_tool('send_mail',lambda args:None,gated=True)
    elif change=='args':
        args={'to':'bea'}
    else:
        actor='other'
    with turn(**kw):
        await ask(server,args,actor)
    assert not queue.pending_groups()


@pytest.mark.asyncio
async def test_metadata_failure_preserves_successfully_persisted_ask(stack,monkeypatch):
    queue,worker,server=stack
    attempts=[]
    def failure(*args,**kwargs):
        attempts.append(True)
        raise RuntimeError('synthetic metadata failure')
    monkeypatch.setattr(queue,'register_pending_group',failure)
    with turn():
        result=await ask(server)
    assert result['reason']=='approval_required'
    assert queue.get(result['task_id']).status=='blocked'
    assert len(queue.list())==1 and attempts==[True]


@pytest.mark.asyncio
async def test_raw_fallback_and_direct_enqueue_cannot_borrow_provenance(stack):
    queue,worker,server=stack
    server._enqueue=queue.enqueue
    with turn():
        await ask(server)
        await ask(server)
        worker.govern_enqueue('jarvis','toolrpc.send_mail','Tool via RPC',payload={'tool':'send_mail','args':{'to':'ana'},'target':'send_mail'})
    assert not queue.pending_groups()


@pytest.mark.asyncio
@pytest.mark.parametrize('args',[{'to':'ana','session_id':'claimed'},{'to':'ana','authority':'owner'},{'to':'ana','nested':{'context':{}}}])
async def test_model_claims_opt_out_of_grouping(stack,args):
    queue,worker,server=stack
    with turn():
        await ask(server,args)
        await ask(server,args)
    assert not queue.pending_groups()


@pytest.mark.asyncio
async def test_closed_producer_and_child_task_cannot_borrow_scope(stack):
    import asyncio

    from agents.core.approval_outcomes import tool_approval_scope
    from agents.core.autonomy.approval_grouping import current_model_producer, model_request_scope
    with turn(),tool_approval_scope('send_mail'):
        with model_request_scope(actor='jarvis',tool='send_mail',args={'to':'ana'},epoch='a'*32,registration_is_live=lambda:True):
            assert current_model_producer() is not None
            async def copied():
                return current_model_producer()
            assert await asyncio.create_task(copied()) is None
        assert current_model_producer() is None


@pytest.mark.asyncio
async def test_finalized_argument_change_does_not_group(stack,monkeypatch):
    queue,worker,server=stack
    original=worker._mark_payload_for_origin
    def modified(payload,origin):
        changed,tainted=original(payload,origin)
        changed['args']={'to':'different'}
        return changed,tainted
    monkeypatch.setattr(worker,'_mark_payload_for_origin',modified)
    with turn():
        await ask(server)
        await ask(server)
    assert not queue.pending_groups()
    assert len(queue.list(status='blocked'))==2


@pytest.mark.asyncio
async def test_specialized_intake_never_mints_generic_marker(stack):
    queue,worker,server=stack
    server.register_tool('send_mail',lambda args:None,gated=True,trusted_execution=True,
        gated_intake=lambda actor,args:worker.govern_enqueue(actor,'toolrpc.send_mail','specialized',
            payload={'tool':'send_mail','args':args,'target':'send_mail'}))
    with turn():
        await ask(server)
        await ask(server)
    assert not queue.pending_groups()


@pytest.mark.asyncio
async def test_registration_callback_failure_is_metadata_only(stack,monkeypatch):
    from agents.core.approval_outcomes import tool_approval_scope
    from agents.core.autonomy.approval_grouping import current_model_producer, model_request_scope
    with turn(),tool_approval_scope('send_mail'):
        def broken():
            raise RuntimeError('synthetic registration unavailable')
        with model_request_scope(actor='jarvis',tool='send_mail',args={'to':'ana'},epoch='a'*32,registration_is_live=broken):
            assert current_model_producer() is None


@pytest.mark.asyncio
async def test_only_live_turn_is_eligible_and_epoch_not_public(stack):
    queue,worker,server=stack
    with turn(live=False):
        await ask(server)
        await ask(server)
    assert not queue.pending_groups()
    assert '_grouping_epoch' not in str(server.tools())
