"""The restart command only queues a card; the notice uses one signed recipient."""

from __future__ import annotations

import asyncio
import sys
import threading
from types import ModuleType, SimpleNamespace

import pytest

import agents.core as core
from agents.core.autonomy.restart_records import NoticeClaim, VerifiedRestart
from agents.core.commands import ADMIN, CommandContext, Principal, build_default_registry
from agents.core.restart_command import restart_command
from agents.core.restart_notice import NOTICE_TEXT, notify_completed_restart


def _helper(monkeypatch, *, request=None, recipient=None):
    module = ModuleType("agents.core.hub_restart_apply")
    module.request_restart = request or (lambda *_args, **_kwargs: {"refused": "no_request"})
    module.recipient_current = recipient or (lambda *_args: True)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(core, "hub_restart_apply", module, raising=False)
    return module


def _ctx(source=None, *, admin=True, args="", channel="telegram", scope="dm"):
    return CommandContext(SimpleNamespace(), Principal(channel=channel, sender="10", admin=admin,
                                                        chat="10", scope=scope), "restart", args,
                          source=source)


@pytest.mark.asyncio
async def test_restart_registered_admin_and_invalid_sources_never_request(monkeypatch):
    from agents.core import restart_command as module

    called = []

    async def request(*_args, **_kwargs):
        called.append(True)
        return {"pending": 3}

    _helper(monkeypatch, request=request)
    registry = build_default_registry()
    assert registry.get("restart").tier == ADMIN
    assert "owner's Telegram DM" in await restart_command(_ctx())
    assert "Usage" in await restart_command(_ctx(args="now"))
    assert "Usage" in await restart_command(_ctx(admin=False))
    assert "owner's Telegram DM" in await restart_command(_ctx(channel="web"))
    monkeypatch.setattr(module, "source_for_dispatch", lambda **_kwargs: None)
    assert "owner's Telegram DM" in await restart_command(_ctx(source=object()))
    assert called == []


@pytest.mark.asyncio
async def test_valid_sealed_source_only_queues_human_card(monkeypatch):
    from agents.core import restart_command as module
    from agents.core.command_source import InboundCommandSource, TelegramCommandCandidate

    source = InboundCommandSource(
        TelegramCommandCandidate(object(), "gen", 42, 7, 12, 10, 10, "/restart",
                                 asyncio.current_task()), "inbox", object())
    calls = []

    async def request(orch, *, principal, source):
        calls.append((orch, principal, source))
        return {"pending": 17}

    _helper(monkeypatch, request=request)
    monkeypatch.setattr(module, "source_for_dispatch", lambda **_kwargs: source)
    ctx = _ctx(source=source)
    reply = await restart_command(ctx)
    assert "card #17 queued" in reply and "did not restart" in reply
    assert calls == [(ctx.orch, ctx.principal, source)]


@pytest.mark.asyncio
async def test_restart_refusals_and_uncertain_results_are_fixed(monkeypatch):
    from agents.core import restart_command as module
    from agents.core.command_source import InboundCommandSource, TelegramCommandCandidate

    source = InboundCommandSource(
        TelegramCommandCandidate(object(), "gen", 42, 7, 12, 10, 10, "/restart",
                                 asyncio.current_task()), "inbox", object())
    monkeypatch.setattr(module, "source_for_dispatch", lambda **_kwargs: source)

    async def refused(*_args, **_kwargs):
        return {"refused": "request_replayed"}

    _helper(monkeypatch, request=refused)
    assert "already used" in await restart_command(_ctx(source=source))

    async def broken(*_args, **_kwargs):
        raise RuntimeError("secret error")

    _helper(monkeypatch, request=broken)
    assert "secret" not in await restart_command(_ctx(source=source))


BOOT = "newboot_123456789"
OLD_BOOT = "oldboot_123456789"


class Queue:
    def __init__(self, verified):
        self.verified = verified
        self.claims = []
        self.finished = []
        self.valid = True
        self.can_claim = True

    def list_restart_notices(self, boot_id, *, limit):
        assert boot_id == BOOT and limit == 32
        return (self.verified,)

    def validate_restart_completion(self, task_id, digest, *, for_notification):
        assert for_notification is True
        assert (task_id, digest) == (self.verified.task_id, self.verified.intent_digest)
        return self.verified if self.valid else None

    def get(self, task_id):
        assert task_id == self.verified.task_id
        return SimpleNamespace(id=task_id, kind="hub.restart", mediation_scope="restart-scope")

    def claim_restart_notice(self, task_id, digest, boot_id, *, live_check):
        assert (task_id, digest, boot_id) == (self.verified.task_id,
                                              self.verified.intent_digest, BOOT)
        if not self.can_claim or live_check(self.verified) is not True:
            return None
        claim = NoticeClaim("claim", self.verified, "hub.restart:17")
        self.claims.append(claim)
        return claim

    def finish_restart_notice(self, claim, outcome):
        self.finished.append((claim, outcome))
        return True


def _notice_rig(monkeypatch, *, send_result=True, recipient=True):
    verified = VerifiedRestart(17, "a" * 64, OLD_BOOT, "telegram:42:7", 42, 10, 10)
    queue = Queue(verified)
    sent = []

    async def send(*args, **kwargs):
        sent.append((args, kwargs))
        return send_result

    halted = set()
    policy = SimpleNamespace(mode="ask", effective_mode=lambda _agent: "ask")
    worker = SimpleNamespace(queue=queue, policy=policy,
                             _halted=lambda scope=None: scope in halted)
    queue.mediation_mode = "enforce"
    orch = SimpleNamespace(autonomy_queue=queue, autonomy=worker,
                           channel_manager=SimpleNamespace(send=send))
    orch._test_halted = halted
    _helper(monkeypatch, recipient=lambda *_args: recipient)
    return orch, queue, sent


@pytest.mark.asyncio
async def test_notifier_sends_only_fixed_keyed_owner_dm_after_claim(monkeypatch):
    orch, queue, sent = _notice_rig(monkeypatch)
    result = await notify_completed_restart(orch, boot_id=BOOT)
    assert result == {"status": "ok", "listed": 1, "sent": 1, "withheld": 0, "unknown": 0}
    assert len(queue.claims) == 1
    assert queue.finished == [(queue.claims[0], "sent")]
    assert sent == [(("telegram", NOTICE_TEXT), {
        "chat_id": 10, "plain": True, "voice": False, "delivery_key": "hub.restart:17"})]


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["same_boot", "recipient", "completion", "claim"])
async def test_notifier_withholds_without_current_authority(monkeypatch, reason):
    orch, queue, sent = _notice_rig(monkeypatch, recipient=reason != "recipient")
    if reason == "same_boot":
        queue.verified = VerifiedRestart(17, "a" * 64, BOOT, "telegram:42:7", 42, 10, 10)
    elif reason == "completion":
        queue.valid = False
    elif reason == "claim":
        queue.can_claim = False
    result = await notify_completed_restart(orch, boot_id=BOOT)
    assert result["sent"] == 0 and result["withheld"] == 1
    assert sent == [] and queue.finished == []


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["worker", "queue", "mediation", "global_off",
                                     "owner_off", "global_halt", "owner_halt", "scope_halt"])
async def test_notifier_requires_live_execution_floor_before_claim(monkeypatch, reason):
    orch, queue, sent = _notice_rig(monkeypatch)
    if reason == "worker":
        orch.autonomy = SimpleNamespace(queue=queue, policy=orch.autonomy.policy)
    elif reason == "queue":
        orch.autonomy.queue = object()
    elif reason == "mediation":
        queue.mediation_mode = "hold"
    elif reason == "global_off":
        orch.autonomy.policy.mode = False
    elif reason == "owner_off":
        orch.autonomy.policy.effective_mode = lambda _agent: "off"
    else:
        orch._test_halted.add({"global_halt": None, "owner_halt": "owner",
                               "scope_halt": "restart-scope"}[reason])
    result = await notify_completed_restart(orch, boot_id=BOOT)
    assert result["sent"] == 0
    assert queue.claims == [] and sent == []


@pytest.mark.asyncio
async def test_notifier_rechecks_halt_after_claim_before_send(monkeypatch):
    orch, queue, sent = _notice_rig(monkeypatch)
    original = queue.claim_restart_notice

    def claim_then_halt(*args, **kwargs):
        claim = original(*args, **kwargs)
        orch._test_halted.add("restart-scope")
        return claim

    queue.claim_restart_notice = claim_then_halt
    result = await notify_completed_restart(orch, boot_id=BOOT)
    assert result["sent"] == 0 and result["unknown"] == 1
    assert sent == [] and queue.finished == [(queue.claims[0], "unknown")]


@pytest.mark.asyncio
async def test_false_send_records_unknown_and_does_not_retry(monkeypatch):
    orch, queue, sent = _notice_rig(monkeypatch, send_result=False)
    result = await notify_completed_restart(orch, boot_id=BOOT)
    assert result["status"] == "partial" and result["unknown"] == 1
    assert len(sent) == 1 and queue.finished[0][1] == "unknown"


@pytest.mark.asyncio
async def test_cancelled_send_finishes_unknown_before_propagating(monkeypatch):
    orch, queue, _sent = _notice_rig(monkeypatch)
    entered = asyncio.Event()

    async def blocked(*_args, **_kwargs):
        entered.set()
        await asyncio.Event().wait()

    orch.channel_manager.send = blocked
    pending = asyncio.create_task(notify_completed_restart(orch, boot_id=BOOT))
    await entered.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert len(queue.claims) == 1
    assert queue.finished == [(queue.claims[0], "unknown")]


@pytest.mark.asyncio
async def test_cancel_during_claim_waits_for_commit_then_marks_unknown(monkeypatch):
    orch, queue, sent = _notice_rig(monkeypatch)
    entered = threading.Event()
    release = threading.Event()
    original = queue.claim_restart_notice

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return original(*args, **kwargs)

    queue.claim_restart_notice = blocked
    pending = asyncio.create_task(notify_completed_restart(orch, boot_id=BOOT))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        pending.cancel()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert len(queue.claims) == 1
    assert queue.finished == [(queue.claims[0], "unknown")]
    assert sent == []


@pytest.mark.asyncio
async def test_unreadable_notice_list_is_unavailable_and_sends_nothing(monkeypatch):
    from agents.core.autonomy.restart_records import RestartStateUnavailable

    orch, queue, sent = _notice_rig(monkeypatch)

    def unreadable(*_args, **_kwargs):
        raise RestartStateUnavailable("private store detail")

    queue.list_restart_notices = unreadable
    result = await notify_completed_restart(orch, boot_id=BOOT)
    assert result["status"] == "unavailable" and result["listed"] == 0
    assert sent == [] and queue.claims == []
