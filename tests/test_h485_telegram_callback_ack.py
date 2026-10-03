"""Decision callback acknowledgments must reflect the durable owner decision."""

import json
from types import SimpleNamespace

import httpx

from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.autonomy_coordinator import AutonomyCoordinator
from agents.core.channels.telegram import TelegramChannel


async def _inbox(tmp_path):
    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    worker = AutonomyWorker(queue)
    channel = TelegramChannel(token="test-token", allowed_user_ids=[])
    answers = []

    def telegram_api(request):
        assert request.url.path.endswith("/answerCallbackQuery")
        answers.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": True})

    await channel.client.aclose()
    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(telegram_api))
    orch = SimpleNamespace(
        autonomy=worker,
        channels={"telegram": channel},
        get_setting=lambda key, default=None: {
            "autonomy.owner_chat_id": "-500",
            "autonomy.owner_user_ids": [42],
        }.get(key, default),
    )
    channel.on_callback = AutonomyCoordinator(orch)._on_callback
    task_id = queue.enqueue("jarvis", "delete_file", "Delete test file", attention_mode="none")
    queue.transition(task_id, TaskStatus.BLOCKED, decided_by="policy", decision="needs-approval")
    return queue, channel, task_id, answers


def _tap(task_id, sender, callback_id="tap"):
    return {
        "id": callback_id,
        "from": {"id": sender},
        "message": {"chat": {"id": -500, "type": "supergroup"}},
        "data": f"aut:{task_id}:accept",
    }


async def test_guest_tap_does_not_claim_success_or_decide_task(tmp_path):
    queue, channel, task_id, answers = await _inbox(tmp_path)
    try:
        await channel._handle_callback(_tap(task_id, 7, "guest"))
        assert queue.get(task_id).status == "blocked"
        assert queue.get(task_id).human_decision is None
        assert len(answers) == 1
        assert answers[0]["callback_query_id"] == "guest"
        assert not answers[0]["text"].startswith("OK")
    finally:
        await channel.client.aclose()
        queue.close()


async def test_owner_tap_commits_then_acknowledges_success(tmp_path):
    queue, channel, task_id, answers = await _inbox(tmp_path)
    try:
        await channel._handle_callback(_tap(task_id, 42, "owner"))
        task = queue.get(task_id)
        assert task.status == "approved"
        assert task.human_decision["action"] == "accept"
        assert task.human_decision["by"] == "telegram"
        assert len(answers) == 1
        assert answers[0]["callback_query_id"] == "owner"
        assert answers[0]["text"] == "OK: accept"
    finally:
        await channel.client.aclose()
        queue.close()


async def test_noop_or_raising_hook_never_claims_success(tmp_path):
    queue, channel, task_id, answers = await _inbox(tmp_path)
    try:
        async def no_op(*_args, **_kwargs):
            return None

        async def broken(*_args, **_kwargs):
            raise RuntimeError("decision unavailable")

        channel.on_callback = no_op
        await channel._handle_callback(_tap(task_id, 42, "noop"))
        channel.on_callback = broken
        await channel._handle_callback(_tap(task_id, 42, "broken"))
        assert queue.get(task_id).status == "blocked"
        assert [answer["callback_query_id"] for answer in answers] == ["noop", "broken"]
        assert all(not answer["text"].startswith("OK") for answer in answers)
    finally:
        await channel.client.aclose()
        queue.close()
