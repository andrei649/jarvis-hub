"""Actual ntfy stream, governed output and typed model answers, offline."""

import asyncio

import httpx
import pytest

from agents.core.channels.gateway import Gateway
from agents.core.channels.manager import ChannelManager
from agents.core.channels.ntfy import NtfyChannel
from agents.core.channels.pairing import SenderPairing
from agents.core.channels.session import SessionSource, build_session_key
from tests.test_h011_rollback_conversation import context  # noqa: F401
from tests.test_ntfy_inbound import Frames, event, line, setup_channel, until
from tests.test_pending_input_completion_h067 import approve_prompt
from tests.test_pending_input_runtime import runtime_host
from tests.test_pending_input_workspace_broker import prompt_broker  # noqa: F401
from tests.test_session_command_kernel import governed  # noqa: F401
from tests.test_session_command_runtime import command_host


async def ntfy_host(tmp_path, prompt_broker, *, choices=None, answer="2"):
    broker, queue, worker, _sent, _state, _inbound, _calls, manager = prompt_broker
    orch, captured, gateway, server, _ready, _pairing, answers = runtime_host(tmp_path)
    channel, _, inbox, _seen, requests, stream = setup_channel(tmp_path / "ntfy")
    broker._inbox = inbox
    manager = ChannelManager()
    manager.register(channel)
    broker._channel_manager = manager
    orch.channel_manager, orch.channel_replies = manager, broker
    orch.autonomy, orch.autonomy_queue = worker, queue
    orch._begin_channel_draft = lambda *_args: None
    gateway.inbox_store, gateway.pairing = inbox, channel.pairing
    gateway.pending_handler = orch.channel_pending_handler
    channel.handler, channel.pending_reply_handler = gateway.route, gateway.route_pending
    release = asyncio.Event()

    async def frames():
        yield line(event(text="ask"))
        await release.wait()
        yield line(event("answer", text=answer))
        await asyncio.Event().wait()

    stream.__class__ = type("PendingFrames", (type(stream),), {"__aiter__": lambda _self: frames()})
    if choices is not None:
        original = server.handle

        async def handle(request, *args, **kwargs):
            return await original({**request, "args": {**request["args"], "choices": choices}}, *args, **kwargs)

        server.handle = handle
    return orch, captured, gateway, answers, channel, requests, release, broker, queue, worker


async def queued_prompt(queue, orch):
    await until(lambda: any("native_prompt" in t.payload for t in queue.list()) or
                not orch._pending_input_service().inputs._active)
    prompts = [t for t in queue.list() if "native_prompt" in t.payload]
    assert prompts, "The actual ntfy model did not queue its pending question"
    return prompts[-1]


async def cleanup_host(orch, channel):
    orch._pending_input_service().close()
    orch.channel_replies.close_pending_prompts()
    await channel.stop()


@pytest.mark.asyncio
async def test_pairing_alone_cannot_authorize_ntfy_history_changes(tmp_path, prompt_broker):
    orch, _cap, gateway, _answers, channel, _requests, _release, _broker, queue, _worker = await ntfy_host(
        tmp_path, prompt_broker)
    try:
        await channel.start()
        await until(lambda: queue.list())
        before = dict(orch._channel_sessions)
        reply = await gateway.route("/new", channel="ntfy", sender="home", chat_id="home",
                                    ntfy_topic="home", ntfy_context=channel._context())
        assert str(reply).startswith("Only the current owner")
        assert orch._channel_sessions == before
        assert not orch._channel_principal("ntfy", "home", "home").admin
        orch._runtime_settings["channels.owner_senders"] = {"ntfy": ["home"]}
        assert orch._channel_principal("ntfy", "home", "home").admin
        channel.pairing.unpair("ntfy", "home")
        assert not orch._channel_principal("ntfy", "home", "home").admin
    finally:
        await cleanup_host(orch, channel)


@pytest.mark.asyncio
@pytest.mark.parametrize("large", [False, True])
async def test_real_stream_reads_answer_while_model_waits_for_signed_prompt(tmp_path, prompt_broker, large, monkeypatch):
    from types import SimpleNamespace

    import agents.core.native_human_wait as human_wait

    clock = {"now": 1000.0}
    monkeypatch.setattr(human_wait, "time", SimpleNamespace(monotonic=lambda: clock["now"]))
    labels = ["Local " + "🧪" * 11000, "Remote " + "🧪" * 11000] if large else None
    orch, cap, _gateway, answers, channel, requests, release, broker, queue, worker = await ntfy_host(
        tmp_path, prompt_broker, choices=labels)
    try:
        await channel.start()
        await until(lambda: queue.list())
        queued = await queued_prompt(queue, orch)
        assert queued.status == "blocked" and queued.mediation_receipt
        assert queued.payload["native_prompt"]["mode"] == "text"
        assert not [r for r in requests if r.method == "POST"]
        assert cap["credit"].seconds() == 0
        assert broker.review_prompt(queued)["available"]
        await worker.apply_decision(queued.id, "accept", decided_by="owner")
        assert (await worker.tick(task_id=queued.id))["done"] == 1
        await until(lambda: orch._pending_input_service()._delivered)
        posts = [r for r in requests if r.method == "POST"]
        assert posts and all(len(p.content) <= 4096 for p in posts)
        if large:
            assert "content_sha256" in queued.payload["native_prompt"]
            assert labels[1] in b"".join(p.content for p in posts).decode()
        clock["now"] += 5
        # The runtime budget samples while the exact delivered wait is live.
        assert cap["credit"].seconds() == 5
        release.set()
        await until(lambda: answers)
        assert answers[0][0]["result"]["user_response"] == (labels[1] if large else "Remote")
        assert answers[0][1] == 5
        assert len(cap["sessions"]) == 1
    finally:
        await cleanup_host(orch, channel)


@pytest.mark.asyncio
async def test_ntfy_text_fallback_accepts_own_answer_with_choices(tmp_path, prompt_broker):
    own_answer = "Use the synthetic workspace instead"
    orch, cap, _gateway, answers, channel, requests, release, _broker, queue, worker = await ntfy_host(
        tmp_path, prompt_broker, answer=own_answer)
    try:
        await channel.start()
        await until(lambda: queue.list())
        queued = await queued_prompt(queue, orch)
        await worker.apply_decision(queued.id, "accept", decided_by="owner")
        await worker.tick(task_id=queued.id)
        await until(lambda: orch._pending_input_service()._delivered)
        count = len([r for r in requests if r.method == "POST"])
        release.set()
        await until(lambda: answers)
        assert answers[0][0]["result"]["user_response"] == own_answer
        assert len([r for r in requests if r.method == "POST"]) == count
        assert len(cap["sessions"]) == 1
    finally:
        await cleanup_host(orch, channel)


@pytest.mark.asyncio
async def test_ntfy_free_form_prompt_accepts_typed_prose(tmp_path, prompt_broker):
    orch, cap, _gateway, answers, channel, _requests, release, _broker, queue, worker = await ntfy_host(
        tmp_path, prompt_broker, choices=[], answer="Use the local synthetic workspace")
    try:
        await channel.start()
        await until(lambda: queue.list())
        queued = await queued_prompt(queue, orch)
        await worker.apply_decision(queued.id, "accept", decided_by="owner")
        await worker.tick(task_id=queued.id)
        await until(lambda: orch._pending_input_service()._delivered)
        release.set()
        await until(lambda: answers)
        assert answers[0][0]["result"]["user_response"] == "Use the local synthetic workspace"
        assert len(cap["sessions"]) == 1
    finally:
        await cleanup_host(orch, channel)


@pytest.mark.asyncio
async def test_full_serial_queue_does_not_block_pending_answer_and_stop_drains_tasks(tmp_path, prompt_broker):
    orch, _cap, _gateway, answers, channel, _requests, _release, _broker, queue, worker = await ntfy_host(
        tmp_path, prompt_broker)
    try:
        await channel.start()
        await until(lambda: queue.list())
        queued = await queued_prompt(queue, orch)
        for index in range(129):
            await channel._on_message(event(f"burst{index}", text="ordinary"))
        assert channel._events.qsize() == 128
        await worker.apply_decision(queued.id, "accept", decided_by="owner")
        await worker.tick(task_id=queued.id)
        await until(lambda: orch._pending_input_service()._delivered)
        await channel._on_message(event("valid", text="2"))
        await until(lambda: answers)
        assert answers[0][0]["result"]["user_response"] == "Remote"
    finally:
        dispatcher, subscription = channel._dispatch_task, channel._stream_task
        await cleanup_host(orch, channel)
        assert dispatcher.done() and subscription.done()
        assert channel._events is None


@pytest.mark.asyncio
async def test_live_prompt_revoked_during_dns_wait_never_reaches_http(tmp_path, monkeypatch):
    from agents.core.http_client import PluginHTTPClient

    pairing = SenderPairing(tmp_path / "pairing.json")
    pairing.approve("ntfy", "home")
    channel = NtfyChannel("https://ntfy.example", "home", inbound=True,
                          handler=lambda *_args, **_kwargs: None, pairing=pairing)
    entered, release = asyncio.Event(), asyncio.Event()
    active = {"value": True}
    requests = []
    original = PluginHTTPClient._prepare_target

    async def prepare(client, method, url):
        target = await original(client, method, url)
        if method == "POST":
            entered.set()
            await release.wait()
        return target

    monkeypatch.setattr(PluginHTTPClient, "_prepare_target", prepare)
    channel.client._resolver = lambda *_args, **_kwargs: (["9.9.9.9"], None)

    def transport(request):
        requests.append(request)
        return httpx.Response(200, stream=Frames([], hold=True)) if request.method == "GET" else httpx.Response(200)

    channel.client._transport_factory = lambda _target: httpx.MockTransport(transport)
    pending = None
    try:
        await channel.start()
        await until(lambda: requests)
        pending = asyncio.create_task(channel.send_reply("question", ntfy_topic="home",
                                      ntfy_context=channel._context(), current=lambda: active["value"]))
        await entered.wait()
        active["value"] = False
        release.set()
        assert await pending is False
        assert not [r for r in requests if r.method == "POST"]
    finally:
        release.set()
        if pending is not None:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await channel.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["/new", "/undo"])
@pytest.mark.parametrize("choice", ["!cancel", "Approve Once", "!always", "changed"])
async def test_ntfy_owner_commands_preserve_history_and_govern_permanence(
    tmp_path, context, prompt_broker, command, choice,
):
    orch, cap, _gateway, _ready, _pairing, _base = command_host(tmp_path, context)
    broker, queue, worker, _sent, _state, _inbound, _calls, manager = prompt_broker
    channel, _, inbox, _seen, _requests, _stream = setup_channel(tmp_path / "ntfy-command")
    manager.register(channel)
    broker._inbox, broker._channel_manager = inbox, manager
    orch.channel_manager, orch.channel_replies = manager, broker
    orch.autonomy, orch.autonomy_queue = worker, queue
    orch.permission_ledger = worker.executor.__self__.resolve("permission.grant").__self__
    orch._runtime_settings["channels.owner_senders"] = {"ntfy": ["home"]}
    gateway = Gateway(orch.channel_handler, pairing=channel.pairing, inbox_store=inbox,
                      pending_handler=orch.channel_pending_handler)
    channel.handler, channel.pending_reply_handler = gateway.route, gateway.route_pending
    await channel.start()
    delivery = {"channel": "ntfy", "sender": "home", "chat_id": "home", "ntfy_topic": "home",
                "ntfy_context": channel._context()}
    base = build_session_key(SessionSource(channel="ntfy", sender="home", thread_id="home"))
    turn = None
    try:
        await gateway.route("keep", **delivery)
        await gateway.route("remove", **delivery)
        sid = orch._channel_sessions[base]
        history = await orch.memory.get_history(sid)
        turn = asyncio.create_task(gateway.route(command, **delivery))
        await approve_prompt(orch, queue, worker, turn)
        assert await orch.memory.get_history(sid) == history
        assert await gateway.route("Approve Once" if choice == "changed" else choice, **delivery) == ""
        if choice == "changed":
            channel.publish_topic = "changed"
        response = await asyncio.wait_for(turn, 1)
        assert cap["model_texts"] == ["keep", "remove"]
        if choice in {"!cancel", "changed"}:
            assert orch._channel_sessions[base] == sid
            assert await orch.memory.get_history(sid) == history
        elif command == "/new":
            assert orch._channel_sessions[base] != sid
            assert await orch.memory.get_history(sid) == history
        else:
            assert len(await orch.memory.get_history(sid)) == len(history) - 2
        grants = [t for t in queue.list() if t.kind == "permission.grant"]
        assert bool(grants) == (choice == "!always"), response
        if grants:
            assert orch.permission_ledger.list_grants() == []
            await worker.apply_decision(grants[-1].id, "accept", decided_by="owner")
            assert (await worker.tick(task_id=grants[-1].id))["done"] == 1
            assert len(orch.permission_ledger.list_grants()) == 1
            from agents.core.channels.session_command_runtime import SessionCommandRuntime

            runtime = SessionCommandRuntime(orch._pending_input_service())
            source = SessionSource(channel="ntfy", sender="home", thread_id="home")
            key = runtime._consent_key(source)
            channel._epoch = "restarted-transport"
            channel._token = "synthetic-rotated-credential"
            assert runtime._consent_key(source) == key
            assert runtime._consent().check(key, command) == "allow"
            # A different ntfy server is a different consent authority even
            # when it uses the same short topic and session route.
            prior = len([t for t in queue.list() if "native_prompt" in t.payload])
            channel.url = "https://another-ntfy.example"
            fresh_delivery = {**delivery, "ntfy_context": channel._context()}
            turn = asyncio.create_task(gateway.route(command, **fresh_delivery))
            await until(lambda: turn.done() or len([t for t in queue.list() if "native_prompt" in t.payload]) > prior)
            assert not turn.done(), "Standing consent from another ntfy server bypassed confirmation"
    finally:
        if turn is not None:
            turn.cancel()
            await asyncio.gather(turn, return_exceptions=True)
        await cleanup_host(orch, channel)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["pairing", "config", "reject", "stop"])
async def test_pending_ntfy_lost_authority_never_publishes(tmp_path, prompt_broker, change):
    orch, _cap, _gateway, _answers, channel, requests, _release, _broker, queue, worker = await ntfy_host(
        tmp_path, prompt_broker)
    try:
        await channel.start()
        await until(lambda: queue.list())
        queued = await queued_prompt(queue, orch)
        if change == "pairing":
            channel.pairing.unpair("ntfy", "home")
        elif change == "config":
            channel.publish_topic = "changed"
        elif change == "stop":
            await channel.stop()
        await worker.apply_decision(queued.id, "reject" if change == "reject" else "accept", decided_by="owner")
        await worker.tick(task_id=queued.id)
        assert not [r for r in requests if r.method == "POST"]
    finally:
        await cleanup_host(orch, channel)
