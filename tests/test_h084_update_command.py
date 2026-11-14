"""H084 /update queues the existing irreversible card; it never applies one."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from agents.core import hub_update_apply
from agents.core.autonomy import irreversible
from agents.core.autonomy.queue import TaskQueue
from agents.core.channels import outbound_safety
from agents.core.commands import CommandContext, Principal
from agents.core.update_commands import update_command


def _ctx(channel="web", *, owner=True, args="", orch=None):
    if orch is None:
        queue = SimpleNamespace(pending_decisions=lambda **_kw: [])
        orch = SimpleNamespace(autonomy=SimpleNamespace(queue=queue))
    return CommandContext(orch, Principal(channel=channel, admin=owner),
                          "update", args)


@pytest.mark.parametrize("channel", ["web", "telegram", "discord", "slack", "matrix"])
async def test_owner_chat_surfaces_queue_the_default_request(channel, monkeypatch):
    calls = []

    def request(*args, **kwargs):
        calls.append((args, kwargs))
        return {"pending": 41, "plan": {"to": "not exposed"}}

    monkeypatch.setattr(hub_update_apply, "request_apply", request)
    ctx = _ctx(channel)
    reply = await update_command(ctx)
    assert len(calls) == 1
    assert calls[0][0] == (ctx.orch, None, "refuse")
    assert calls[0][1] == {"requested_by": "owner (chat /update)"}
    assert "41" in reply and "human" in reply.lower() and "not exposed" not in reply


async def test_guest_args_and_nonchat_surfaces_refuse_before_request(monkeypatch):
    monkeypatch.setattr(hub_update_apply, "request_apply",
                        lambda *_a, **_k: pytest.fail("request was reached"))
    assert "owner" in (await update_command(_ctx(owner=False))).lower()
    assert "Usage" in await update_command(_ctx(args="--stash"))
    for channel in ("api", "acp", "webhook", "unknown", "voice"):
        assert "chat" in (await update_command(_ctx(channel))).lower()


@pytest.mark.parametrize("code,expected", [
    ("no_trust_configured", "trust"), ("dirty_tree", "uncommitted"),
    ("not_a_git_checkout", "Git checkout"), ("container", "container"),
    ("restart_manual", "restart"), ("update_in_progress", "in progress"),
    ("up_to_date", "up to date"), ("target_unknown", "target"),
])
async def test_refusal_codes_use_fixed_notices_without_detail(code, expected, monkeypatch):
    def refused(*_args, **_kwargs):
        raise hub_update_apply.UpdateRefused(code, "secret/path-and-credential")

    monkeypatch.setattr(hub_update_apply, "request_apply", refused)
    reply = await update_command(_ctx())
    assert expected.lower() in reply.lower() and "secret/path" not in reply


def _admissible_plan():
    return {"can_apply": True, "from": "a" * 40, "to": "b" * 40,
            "target_ref": "@{u}", "tag": None, "dirty_policy": "refuse",
            "from_version": "1", "to_version": "2", "dependencies": {"changed": False, "command": None},
            "migrations": [], "migrations_uncertain": False, "frontend_changed": False,
            "dirty": False, "verdict": {"how": "pinned", "signer": None},
            "commit_count": 1, "commits": [], "file_count": 0}


async def test_real_request_apply_seam_queues_only_a_human_approval(monkeypatch):
    tasks = []

    def enqueue(**kwargs):
        tasks.append(kwargs)
        return 7

    queue = SimpleNamespace(pending_decisions=lambda **_kw: [])
    orch = SimpleNamespace(autonomy=SimpleNamespace(govern_enqueue=enqueue, queue=queue))
    monkeypatch.setattr(hub_update_apply, "plan",
                        lambda ref=None, dirty_policy="refuse": _admissible_plan())
    monkeypatch.setattr(hub_update_apply, "_remember_card", lambda *_a: None)
    monkeypatch.setattr(hub_update_apply, "_audit", lambda *_a: None)
    monkeypatch.setattr(hub_update_apply, "apply_approved",
                        lambda *_a: pytest.fail("the update pipeline ran"))
    reply = await update_command(_ctx(orch=orch))
    assert "7" in reply and len(tasks) == 1
    assert tasks[0]["kind"] == "hub.update"
    assert tasks[0]["risk_tier"] == irreversible.RISK_TIER
    assert tasks[0]["autonomy_level"] == "ask" and tasks[0]["origin"] == "manual"
    assert tasks[0]["payload"]["to"] == "b" * 40


async def test_govern_enqueue_refusal_is_reported_without_fallback(monkeypatch):
    def refused(**_kwargs):
        raise PermissionError("strict mediation refused")

    queue = SimpleNamespace(pending_decisions=lambda **_kw: [])
    orch = SimpleNamespace(autonomy=SimpleNamespace(govern_enqueue=refused, queue=queue))
    monkeypatch.setattr(hub_update_apply, "plan",
                        lambda ref=None, dirty_policy="refuse": _admissible_plan())
    monkeypatch.setattr(hub_update_apply, "apply_approved",
                        lambda *_a: pytest.fail("the update pipeline ran"))
    reply = await update_command(_ctx(orch=orch))
    assert "approval queue did not admit" in reply.lower()
    assert "strict mediation refused" not in reply


async def test_real_enforce_queue_refuses_unmediated_update_without_fallback(tmp_path, monkeypatch):
    queue = TaskQueue(str(tmp_path / "tasks.db"), mediation_mode="enforce").initialize()
    try:
        assert queue.classify_mediation("hub.update") is True
        orch = SimpleNamespace(autonomy=SimpleNamespace(queue=queue, govern_enqueue=queue.enqueue))
        monkeypatch.setattr(hub_update_apply, "plan",
                            lambda ref=None, dirty_policy="refuse": _admissible_plan())
        monkeypatch.setattr(hub_update_apply, "apply_approved",
                            lambda *_a: pytest.fail("the update pipeline ran"))
        reply = await update_command(_ctx(orch=orch))
        assert "approval queue did not admit" in reply.lower()
        assert queue.pending_decisions(kind="hub.update") == []
    finally:
        queue.close()


async def test_existing_pending_card_and_unavailable_pending_read_do_not_enqueue(monkeypatch):
    monkeypatch.setattr(hub_update_apply, "request_apply",
                        lambda *_a, **_k: pytest.fail("duplicate or unreadable queue was enqueued"))
    pending = _ctx()
    pending.orch.autonomy.queue.pending_decisions = lambda **_kw: [SimpleNamespace(kind="hub.update")]
    assert "already pending" in (await update_command(pending)).lower()
    missing = _ctx()
    missing.orch.autonomy.queue.pending_decisions = lambda **_kw: (_ for _ in ()).throw(OSError())
    assert "queue is unavailable" in (await update_command(missing)).lower()


async def test_redaction_failure_and_uncertain_worker_error_never_echo_raw(monkeypatch):
    monkeypatch.setattr(hub_update_apply, "request_apply",
                        lambda *_a, **_k: {"pending": 19, "plan": {}})
    monkeypatch.setattr(outbound_safety, "_known_redactor",
                        lambda _text: (_ for _ in ()).throw(RuntimeError("private")))
    assert "withheld" in (await update_command(_ctx())).lower()
    monkeypatch.setattr(outbound_safety, "_known_redactor", None)
    monkeypatch.setattr(hub_update_apply, "request_apply",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("private/path")))
    reply = await update_command(_ctx())
    assert "uncertain" in reply.lower() and "private/path" not in reply


async def test_cancellation_waits_for_request_worker_before_releasing_singleflight(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []

    def blocked(*_args, **_kwargs):
        calls.append(1)
        entered.set()
        release.wait(2)
        return {"pending": 51, "plan": {}}

    monkeypatch.setattr(hub_update_apply, "request_apply", blocked)
    task = asyncio.create_task(update_command(_ctx()))
    assert await asyncio.to_thread(entered.wait, 2)
    task.cancel()
    await asyncio.sleep(0)
    assert "already" in (await update_command(_ctx())).lower()
    assert len(calls) == 1
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert "51" in await update_command(_ctx())
