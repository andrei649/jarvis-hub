"""Ntfy ingress reaches a signed approval before any synthetic HTTP publish."""

from types import SimpleNamespace

import pytest

from agents.core.autonomy_coordinator import AutonomyCoordinator
from agents.core.channels.gateway import Gateway
from agents.core.channels.manager import ChannelManager
from agents.core.kernel import Decision, Verdict
from tests.test_channel_handler_session_wiring import _bare_orchestrator
from tests.test_hermes_kanban_dispatcher import fixture_runtime
from tests.test_ntfy_inbound import event, line, setup_channel, until
from tests.test_web_tools_wiring import _coordinator


def _runtime(tmp_path, monkeypatch, *, messages=None):
    """Real coordinator, worker, signed queue and channel, with no live network."""
    _, signed, _, _, _ = fixture_runtime(tmp_path, monkeypatch)
    orch, captured = _bare_orchestrator(response="approved answer")
    for name, value in vars(_coordinator({})._orch).items():
        orch.__dict__.setdefault(name, value)
    orch.autonomy = signed.autonomy
    orch.autonomy_queue = signed.autonomy_queue
    orch.agents = {"veronica": SimpleNamespace()}
    orch.intent_log = SimpleNamespace(
        sign_detached=signed.autonomy._mediation_signer.sign,
        record=lambda *_args, **_kwargs: None,
    )
    channel, gateway, inbox, _, requests, _ = setup_channel(
        tmp_path / "ntfy", [line(message) for message in (messages or [event()])]
    )
    manager = ChannelManager()
    manager.register(channel)
    orch.channel_manager = manager
    orch.channel_inbox = inbox
    gateway.handler = orch.channel_handler
    channel.handler = gateway.route
    coordinator = AutonomyCoordinator(orch)
    executor = coordinator.build_executor()
    orch.autonomy.executor = executor.execute
    return SimpleNamespace(
        orch=orch, worker=orch.autonomy, queue=orch.autonomy_queue,
        channel=channel, gateway=gateway, inbox=inbox,
        requests=requests, captured=captured, executor=executor,
    )


def _posts(runtime):
    return [request for request in runtime.requests if request.method == "POST"]


async def _one_inbound(runtime):
    await runtime.channel.start()
    await until(lambda: len(runtime.queue.list()) == 1)
    [task] = runtime.queue.list()
    assert task.kind == "channel.reply"
    assert task.status == "blocked"
    assert task.mediation_enqueue_id
    assert task.payload["channel"] == "ntfy"
    assert task.payload["text"] == "approved answer"
    assert runtime.inbox.get_message(task.payload["message_id"])["text"] == "hello"
    assert not _posts(runtime)
    assert runtime.captured["sent"] == []
    return task


@pytest.mark.asyncio
async def test_inbound_approval_is_signed_and_dispatches_once(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    try:
        task = await _one_inbound(runtime)
        assert len(runtime.queue.pending_decisions()) == 1
        assert (await runtime.worker.tick())["ran"] == 0
        assert not _posts(runtime)

        await runtime.worker.apply_decision(task.id, "accept", "owner")
        result = await runtime.worker.tick()
        assert result["done"] == 1, result
        [post] = _posts(runtime)
        assert post.url.path == "/home"
        assert post.content == b"approved answer"
        assert post.headers["x-tags"] == "nerva-agent"
        messages = runtime.inbox.messages(task.payload["thread_id"])
        assert [message["direction"] for message in messages] == ["in", "out"]
        assert messages[-1]["reply_to"] == task.payload["message_id"]
        assert (await runtime.worker.tick())["ran"] == 0
        assert len(_posts(runtime)) == 1
    finally:
        await runtime.channel.stop()


@pytest.mark.asyncio
async def test_rejected_reply_never_publishes(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    try:
        task = await _one_inbound(runtime)
        await runtime.worker.apply_decision(task.id, "reject", "owner")
        assert (await runtime.worker.tick())["ran"] == 0
        assert not _posts(runtime)
        assert len(runtime.inbox.messages(task.payload["thread_id"])) == 1
    finally:
        await runtime.channel.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    "revoked", "url", "topic", "token", "stopped", "missing_inbound", "reply_binding",
])
async def test_accepted_reply_rechecks_live_destination_and_inbox(tmp_path, monkeypatch, change):
    runtime = _runtime(tmp_path, monkeypatch)
    try:
        task = await _one_inbound(runtime)
        await runtime.worker.apply_decision(task.id, "accept", "owner")
        if change == "revoked":
            runtime.channel.pairing.block("ntfy", "home")
        elif change == "url":
            runtime.channel.url = "https://different.example"
        elif change == "topic":
            runtime.channel.topic = "different"
        elif change == "token":
            runtime.channel._token = "different"
        elif change == "stopped":
            await runtime.channel.stop()
        elif change == "missing_inbound":
            runtime.inbox._messages.clear()
            runtime.inbox._save()
        elif change == "reply_binding":
            runtime.inbox._messages[0]["reply"]["ntfy_topic"] = "forged"
            runtime.inbox._save()
        result = await runtime.worker.tick()
        assert result["ran"] == 1, result
        assert runtime.queue.get(task.id).result["status"] != "ok"
        assert not _posts(runtime)
    finally:
        await runtime.channel.stop()


@pytest.mark.asyncio
async def test_unconsumed_executor_permit_cannot_publish(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    try:
        task = await _one_inbound(runtime)
        await runtime.worker.apply_decision(task.id, "accept", "owner")
        outcome = await runtime.executor.execute(runtime.queue.get(task.id))
        assert outcome["status"] == "refused", outcome
        assert not _posts(runtime)
    finally:
        await runtime.channel.stop()


@pytest.mark.asyncio
async def test_kernel_denial_refuses_before_queue_or_publish(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch, messages=[])
    signer = runtime.worker._mediation_signer
    runtime.worker.bind_mediation(
        lambda _action, **_kwargs: Decision(Verdict.DENY, reason="synthetic-denial"), signer
    )
    try:
        await runtime.channel.start()
        await runtime.channel._on_message(event())
        assert runtime.queue.list() == []
        assert not _posts(runtime)
        assert len(runtime.inbox.threads()) == 1
    finally:
        await runtime.channel.stop()
