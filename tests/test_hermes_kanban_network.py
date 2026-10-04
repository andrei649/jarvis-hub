"""Approved Kanban URL attachments use the signed worker and pinned HTTP path."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from agents.core.autonomy.executor import TaskExecutor
from agents.core.autonomy.queue import TaskStatus
from agents.core.commands import Principal
from agents.core.kanban.context import KanbanContext, kanban_scope
from agents.core.kanban.network import NetworkAttachmentAdapter
from agents.core.kanban.runtime import register_kanban_tools
from agents.core.kanban.upstream import kanban_db as kb
from agents.core.tool_rpc import ToolRPCServer
from tests.test_hermes_kanban_dispatcher import create, fixture_runtime


@pytest.fixture
def rig(tmp_path, monkeypatch):
    controller, orch, settings, _, _ = fixture_runtime(tmp_path, monkeypatch)
    settings["llm.kanban_network_attachments"] = True
    orch.secret_broker = SimpleNamespace(redact=lambda value: value)
    kernel = orch.autonomy._mediation_kernel
    orch.autonomy._mediation_kernel = lambda action, **kwargs: kernel(action)
    requests = []
    response = [lambda: httpx.Response(200, stream=httpx.ByteStream(b"\x00\xffraw bytes"))]

    def service(request):
        requests.append(request)
        return response[0]()

    adapter = NetworkAttachmentAdapter(
        orch,
        home=controller.home,
        resolver=lambda *a, **kw: (["93.184.216.34"], None),
        transport_factory=lambda target: httpx.MockTransport(service),
    )
    executor = TaskExecutor(execution_guard=adapter.guard)
    executor.register("plugin.egress", adapter.execute)
    orch.autonomy.executor = executor.execute
    yield controller, orch, settings, requests, response, adapter
    orch.autonomy_queue.close()


def propose(rig, url="https://example.com/file.bin", **args):
    controller, _, _, _, _, adapter = rig
    tid = create(controller)
    with kanban_scope(KanbanContext(controller.home, "jarvis", can_mutate=True)):
        answer = adapter.submit({"task_id": tid, "url": url, **args})
    return tid, answer


async def approve(rig, qid):
    orch = rig[1]
    await orch.autonomy.apply_decision(qid, "accept", decided_by="owner")
    await orch.autonomy.tick()
    return orch.autonomy_queue.get(qid)


@pytest.mark.asyncio
async def test_proposal_waits_for_exact_approval_then_stores_binary_bytes(rig):
    controller, orch, _, requests, _, _ = rig
    tid, answer = propose(rig)
    assert answer["ok"] and answer["status"] == "approval_required"
    qid = answer["queue_id"]
    assert orch.autonomy_queue.get(qid).status == "blocked"
    assert requests == []
    assert (await orch.autonomy.tick())["ran"] == 0
    assert (await approve(rig, qid)).status == "done"
    assert orch.autonomy_queue.get(qid).result["status"] == "ok", orch.autonomy_queue.get(qid).result
    assert len(requests) == 1
    assert requests[0].headers["accept-encoding"] == "identity"
    assert "cookie" not in requests[0].headers
    assert "authorization" not in requests[0].headers
    with (
        kanban_scope(KanbanContext(controller.home, "jarvis", can_mutate=True)),
        kb.connect_closing() as conn,
    ):
        attachments = kb.list_attachments(conn, tid)
        assert len(attachments) == 1
        assert attachments[0].filename == "file.bin"
        assert Path(attachments[0].stored_path).read_bytes() == b"\x00\xffraw bytes"


@pytest.mark.parametrize("url", [
    "https://user:pass@example.com/file", "https://example.com/?token=abc",
    "https://example.com/#fragment", "file:///etc/passwd", "https://example.com/secret-value",
])
def test_credentials_and_non_http_are_refused_before_queue(rig, url):
    rig[1].secret_broker.redact = lambda value: value.replace("secret-value", "[redacted]")
    _, answer = propose(rig, url)
    assert answer == {"ok": False, "reason": "kanban_url_refused"}
    assert rig[1].autonomy_queue.list() == [] and rig[3] == []


@pytest.mark.asyncio
async def test_direct_execution_and_replay_have_no_claim(rig):
    _, answer = propose(rig)
    qid = answer["queue_id"]
    queue = rig[1].autonomy_queue
    queue.transition(qid, TaskStatus.APPROVED, decided_by="owner", decision="approve")
    claimed = queue.claim_mediated(qid, execution_id="00000000-0000-4000-8000-000000000010")
    assert (await rig[5].execute(claimed))["status"] == "refused"
    assert rig[3] == []
    # An approved row alone cannot mint the worker's private permit.
    assert (await rig[5].execute(claimed))["status"] == "refused"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["feature", "board", "kernel", "private_dns"])
async def test_revoked_or_private_target_never_dials(rig, change, monkeypatch):
    controller, orch, settings, requests, _, adapter = rig
    tid, answer = propose(rig)
    if change == "feature":
        settings["llm.kanban_network_attachments"] = False
    elif change == "board":
        with kanban_scope(KanbanContext(controller.home, "jarvis", can_mutate=True)), kb.connect_closing() as conn, kb.write_txn(conn):
            conn.execute("DELETE FROM tasks WHERE id=?", (tid,))
    elif change == "kernel":
        from agents.core.kernel import Decision, Verdict
        orch.autonomy._mediation_kernel = lambda action, **kw: Decision(Verdict.DENY, reason="secret")
    else:
        adapter.resolver = lambda *a, **kw: (["127.0.0.1"], None)
    result = await approve(rig, answer["queue_id"])
    assert requests == []
    assert result.result is None or result.result.get("status") in {"refused", "failed"} or result.result.get("guard_reason") in {"configuration_changed", "board_run_changed"}


@pytest.mark.asyncio
async def test_oversize_identity_stream_is_not_published(rig):
    rig[4][0] = lambda: httpx.Response(200, stream=httpx.ByteStream(b"x" * (kb.KANBAN_ATTACHMENT_MAX_BYTES + 1)))
    controller, orch, _, requests, _, _ = rig
    tid, answer = propose(rig)
    task = await approve(rig, answer["queue_id"])
    assert len(requests) == 1 and task.result["status"] == "failed"
    with kanban_scope(KanbanContext(controller.home, "jarvis", can_mutate=True)), kb.connect_closing() as conn:
        assert kb.list_attachments(conn, tid) == []


@pytest.mark.asyncio
async def test_redirect_creates_separate_blocked_approval(rig):
    rig[4][0] = lambda: httpx.Response(302, headers={"location": "/next.bin"}, stream=httpx.ByteStream(b""))
    controller, orch, _, requests, _, _ = rig
    tid, answer = propose(rig)
    parent = await approve(rig, answer["queue_id"])
    assert parent.result["status"] == "approval_required"
    child_id = parent.result["queue_id"]
    child = orch.autonomy_queue.get(child_id)
    assert child.status == "blocked"
    assert child.payload["attachment"]["hop"] == 1
    assert child.payload["attachment"]["parent_queue_id"] == parent.id
    assert len(requests) == 1
    with kanban_scope(KanbanContext(controller.home, "jarvis", can_mutate=True)), kb.connect_closing() as conn:
        assert kb.list_attachments(conn, tid) == []
    rig[4][0] = lambda: httpx.Response(200, stream=httpx.ByteStream(b"next"))
    child = await approve(rig, child_id)
    assert child.result["status"] == "ok" and len(requests) == 2


@pytest.mark.asyncio
async def test_runtime_delegates_validated_owner_call_and_worker_cannot_switch_task(rig):
    controller, orch, _, requests, _, adapter = rig
    server = ToolRPCServer()
    register_kanban_tools(
        server, home=lambda: controller.home, enabled=lambda: True,
        principal=lambda: Principal(channel="web", admin=True),
        profiles=lambda: ("jarvis",), network=lambda: adapter,
    )
    own = create(controller)
    other = create(controller)
    result = await server.handle({"tool": "kanban_attach_url", "args": {
        "task_id": own, "url": "https://example.com/file.bin"}}, actor="jarvis")
    assert result["result"]["status"] == "approval_required"
    assert requests == []
    with kanban_scope(KanbanContext(controller.home, "jarvis", can_mutate=True)), kb.connect_closing() as conn:
        claimed = kb.claim_task(conn, own)
    with kanban_scope(KanbanContext(controller.home, "jarvis", task_id=own,
                                    run_id=claimed.current_run_id, can_mutate=True)):
        bad = await server.handle({"tool": "kanban_attach_url", "args": {
            "task_id": other, "url": "https://example.com/other"}}, actor="jarvis")
        assert bad["result"]["ok"] is False
        good = await server.handle({"tool": "kanban_attach_url", "args": {
            "url": "https://example.com/owned"}}, actor="jarvis")
        assert good["result"]["status"] == "approval_required"
    with kanban_scope(KanbanContext(controller.home, "jarvis", can_mutate=True)), kb.connect_closing() as conn:
        kb.complete_task(conn, own, result="done", expected_run_id=claimed.current_run_id)
    stale = await approve(rig, good["result"]["queue_id"])
    assert stale.result.get("guard_reason") == "board_run_changed"
    assert requests == []


@pytest.mark.asyncio
async def test_worker_run_changed_during_body_is_withheld(rig):
    controller, orch, _, requests, responses, adapter = rig
    tid = create(controller)
    with kanban_scope(KanbanContext(controller.home, "jarvis", can_mutate=True)), kb.connect_closing() as conn:
        claimed = kb.claim_task(conn, tid)
    with kanban_scope(KanbanContext(controller.home, "jarvis", task_id=tid,
                                    run_id=claimed.current_run_id, can_mutate=True)):
        answer = adapter.submit({"url": "https://example.com/owned.bin"})
    assert answer["status"] == "approval_required"

    class ChangedRun(httpx.AsyncByteStream):
        async def __aiter__(self):
            with kanban_scope(KanbanContext(controller.home, "jarvis", can_mutate=True)), kb.connect_closing() as conn:
                kb.complete_task(conn, tid, result="successor", expected_run_id=claimed.current_run_id)
            yield b"must not publish"

    responses[0] = lambda: httpx.Response(200, stream=ChangedRun())
    task = await approve(rig, answer["queue_id"])
    assert len(requests) == 1
    assert task.result == {"status": "failed", "reason": "withheld_after_fetch"}
    with kanban_scope(KanbanContext(controller.home, "jarvis", can_mutate=True)), kb.connect_closing() as conn:
        assert kb.list_attachments(conn, tid) == []


@pytest.mark.asyncio
async def test_cancelled_stream_does_not_publish(rig):
    controller, orch, _, requests, responses, _ = rig
    entered = asyncio.Event()

    class Hanging(httpx.AsyncByteStream):
        async def __aiter__(self):
            entered.set()
            await asyncio.Event().wait()
            yield b"never"

    responses[0] = lambda: httpx.Response(200, stream=Hanging())
    tid, answer = propose(rig)
    await orch.autonomy.apply_decision(answer["queue_id"], "accept", decided_by="owner")
    running = asyncio.create_task(orch.autonomy.tick())
    await asyncio.wait_for(entered.wait(), 2)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert len(requests) == 1
    with kanban_scope(KanbanContext(controller.home, "jarvis", can_mutate=True)), kb.connect_closing() as conn:
        assert kb.list_attachments(conn, tid) == []


@pytest.mark.asyncio
async def test_failed_http_response_never_leaks_body_or_headers(rig):
    responses = rig[4]
    responses[0] = lambda: httpx.Response(
        500, headers={"x-secret": "private-marker"},
        stream=httpx.ByteStream(b"private-marker"),
    )
    _, answer = propose(rig)
    task = await approve(rig, answer["queue_id"])
    assert task.result == {"status": "failed", "reason": "kanban_url_fetch_failed"}
    assert "private-marker" not in str(task.result)


@pytest.mark.asyncio
async def test_redirect_to_credential_url_cannot_enqueue_successor(rig):
    rig[4][0] = lambda: httpx.Response(
        302, headers={"location": "https://user:pass@example.com/next"},
        stream=httpx.ByteStream(b""),
    )
    _, answer = propose(rig)
    task = await approve(rig, answer["queue_id"])
    assert task.result["status"] == "failed"
    assert len(rig[1].autonomy_queue.list()) == 1
    assert "pass" not in str(task.result)


@pytest.mark.asyncio
async def test_maximum_five_redirect_hops_requires_six_approvals(rig):
    rig[4][0] = lambda: httpx.Response(302, headers={"location": "/next"},
                                      stream=httpx.ByteStream(b""))
    _, answer = propose(rig)
    qid = answer["queue_id"]
    for hop in range(5):
        task = await approve(rig, qid)
        assert task.result["status"] == "approval_required"
        qid = task.result["queue_id"]
        child = rig[1].autonomy_queue.get(qid)
        assert child.status == "blocked" and child.payload["attachment"]["hop"] == hop + 1
    sixth = await approve(rig, qid)
    assert sixth.result == {"status": "refused", "reason": "redirect_limit"} or sixth.result == {
        "status": "failed", "reason": "withheld_after_fetch"}
    assert len(rig[3]) == 6


@pytest.mark.asyncio
async def test_mixed_public_private_dns_answer_is_rejected(rig):
    rig[5].resolver = lambda *a, **kw: (["93.184.216.34", "127.0.0.1"], None)
    _, answer = propose(rig)
    task = await approve(rig, answer["queue_id"])
    assert task.result["status"] == "failed"
    assert rig[3] == []


@pytest.mark.asyncio
async def test_stream_deadline_cannot_publish_partial_body(rig, monkeypatch):
    from agents.core.kanban import network

    real_timeout = asyncio.timeout
    monkeypatch.setattr(network.asyncio, "timeout", lambda seconds: real_timeout(0.02))

    class Slow(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"partial"
            await asyncio.Event().wait()

    rig[4][0] = lambda: httpx.Response(200, stream=Slow())
    tid, answer = propose(rig)
    task = await approve(rig, answer["queue_id"])
    assert task.result == {"status": "failed", "reason": "kanban_url_fetch_failed"}
    with kanban_scope(KanbanContext(rig[0].home, "jarvis", can_mutate=True)), kb.connect_closing() as conn:
        assert kb.list_attachments(conn, tid) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("revocation", ["plugin", "halt", "flag"])
async def test_live_revocation_during_stream_withholds_blob(rig, monkeypatch, revocation):
    controller, orch, settings, requests, responses, _ = rig
    plugin = SimpleNamespace(enabled=True)
    orch.permission_gate = SimpleNamespace(plugins={"kanban-attachments": plugin})
    halted = [False]
    monkeypatch.setattr(orch.autonomy, "_halted", lambda scope=None: halted[0])

    class Revoke(httpx.AsyncByteStream):
        async def __aiter__(self):
            if revocation == "plugin":
                plugin.enabled = False
            elif revocation == "halt":
                halted[0] = True
            else:
                settings["llm.kanban_network_attachments"] = False
            yield b"unpublishable"

    responses[0] = lambda: httpx.Response(200, stream=Revoke())
    tid, answer = propose(rig)
    task = await approve(rig, answer["queue_id"])
    assert len(requests) == 1
    assert task.result == {"status": "failed", "reason": "withheld_after_fetch"}
    with kanban_scope(KanbanContext(controller.home, "jarvis", can_mutate=True)), kb.connect_closing() as conn:
        assert kb.list_attachments(conn, tid) == []


def test_disabled_plugin_or_mismatched_queue_refuses_proposal(rig):
    controller, orch, _, requests, _, adapter = rig
    orch.permission_gate = SimpleNamespace(plugins={
        "kanban-attachments": SimpleNamespace(enabled=False)})
    _, answer = propose(rig)
    assert answer == {"ok": False, "reason": "kanban_url_refused"}
    orch.permission_gate = SimpleNamespace(plugins={
        "kanban-attachments": SimpleNamespace(enabled=True)})
    queue = orch.autonomy_queue
    orch.autonomy_queue = object()
    with kanban_scope(KanbanContext(controller.home, "jarvis", can_mutate=True)):
        assert adapter.submit({"task_id": "example", "url": "https://example.com/"})["ok"] is False
    orch.autonomy_queue = queue
    assert requests == []
