"""A chat turn must be able to name the approvals it queued.

``tool_rpc`` has always known the id of the task it pushed onto the approval
queue — it returns it beside ``reason="approval_required"`` — but the tool loop
answered with a fixed sentence and ``/chat`` carried only that prose, so the
owner was told "this needs approval" about something nobody could name. These
tests pin the id's whole way out: the enqueue site records it, the context copy
the tool loop runs its calls under does not lose it, ``/chat`` reports it, and —
the governance line — the task it names is still sitting unapproved in the queue.
"""
import asyncio
import contextvars
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import agents.web as web
from agents.core.autonomy.queue import TaskQueue
from agents.core.orchestrator import Orchestrator
from agents.core.tool_rpc import ToolRPCServer
from agents.core.turn_approvals import (
    current_turn_approvals,
    open_turn_approvals,
    record_pending_approval,
    reset_turn_approvals,
)


class _FakeQueue:
    """Stands in for the governed intake: hands back AUTOINCREMENT-shaped ids."""

    def __init__(self):
        self.calls = []

    def enqueue(self, agent, kind, title, payload=None, risk_tier=3,
                autonomy_level="ask", origin="generated"):
        self.calls.append({"agent": agent, "kind": kind, "payload": payload})
        return len(self.calls)


def _gated_server(enqueue):
    server = ToolRPCServer(enqueue=enqueue)

    async def send_mail(args):
        raise AssertionError("a gated tool must never run from the RPC surface")

    server.register_tool("send_mail", send_mail, gated=True)
    return server


@pytest.fixture
def sink():
    collected, token = open_turn_approvals()
    try:
        yield collected
    finally:
        reset_turn_approvals(token)


# ── the enqueue site records what it queued ──────────────────────────────────

@pytest.mark.asyncio
async def test_gated_call_records_the_id_it_queued(sink):
    queue = _FakeQueue()
    server = _gated_server(queue.enqueue)

    result = await server.handle({"tool": "send_mail", "args": {"to": "ana"}})

    assert result["reason"] == "approval_required"
    assert sink == [result["task_id"]] == [1]


@pytest.mark.asyncio
async def test_turn_that_queues_nothing_reports_nothing(sink):
    server = _gated_server(_FakeQueue().enqueue)

    async def read_clock(args):
        return {"now": 0}

    server.register_tool("read_clock", read_clock)
    result = await server.handle({"tool": "read_clock", "args": {}})

    assert result["ok"] is True
    assert sink == []


# ── the context copy the tool loop runs under ────────────────────────────────

@pytest.mark.asyncio
async def test_id_survives_the_tool_loop_context_copy(sink):
    """``agent_runtime`` runs every tool call under ``asyncio.create_task(...,
    context=...)``, which COPIES the context. A collector the child *re-sets*
    would die in that copy; only appending to the shared list reaches the turn
    that is waiting. This is that copy, reproduced."""
    queue = _FakeQueue()
    server = _gated_server(queue.enqueue)

    child = asyncio.create_task(
        server.handle({"tool": "send_mail", "args": {"to": "ana"}}),
        context=contextvars.copy_context(),
    )
    result = await child

    assert result["task_id"] == 1
    assert sink == [1], "the queued id did not survive the tool loop's context copy"


# ── governance: reporting an id must not move the task ───────────────────────

@pytest.mark.asyncio
async def test_reported_task_stays_pending_and_unexecuted(tmp_path, sink):
    """Naming an approval is not granting it (H002). The real queue row must
    still be `proposed` — unapproved, unexecuted — after the turn reports it."""
    queue = TaskQueue(db_path=str(tmp_path / "queue.db")).initialize()
    server = _gated_server(queue.enqueue)

    result = await server.handle({"tool": "send_mail", "args": {"to": "ana"}})

    assert sink == [result["task_id"]]
    task = queue.get(result["task_id"])
    assert task is not None
    assert task.status == "proposed"
    assert task.decision is None
    assert task.result is None


# ── the turn binds its own sink when nobody opened one ───────────────────────

@pytest.mark.parametrize("entry", ["handle_input", "handle_input_stream"])
@pytest.mark.asyncio
async def test_turn_without_a_caller_sink_collects_into_its_own(entry):
    """A voice or CLI turn has no caller holding a list, but it must still bind
    one: otherwise the ids would either vanish or land in whatever ambient
    context happened to be bound — a neighbouring turn's collector included."""
    orch = Orchestrator.__new__(Orchestrator)
    inner = {}

    async def _turn(*args, **kwargs):
        record_pending_approval(9)
        inner["seen"] = current_turn_approvals()
        return "ok"

    setattr(orch, f"_{entry}", _turn)
    reply = await getattr(Orchestrator, entry)(orch, "hi", channel="voice")

    assert reply == "ok"
    assert inner["seen"] == [9], "the turn bound no collector of its own"
    assert current_turn_approvals() == [], "the turn's ids escaped it"


# ── the wire: /chat carries the ids ──────────────────────────────────────────

def test_chat_reports_the_ids_the_turn_queued(monkeypatch):
    mock = MagicMock()

    async def _turn(message, channel="web", agent_override=None, **kw):
        record_pending_approval(41)
        record_pending_approval(42)
        return "I paused the tool loop because this action requires approval."

    mock.handle_input = _turn
    monkeypatch.setattr(web, "orch", mock)

    body = TestClient(web.app).post("/chat", json={"message": "mail ana"}).json()

    assert body["pending_approvals"] == [41, 42]


def test_chat_reports_an_empty_list_for_an_ordinary_turn(monkeypatch):
    mock = MagicMock()
    mock.handle_input = AsyncMock(return_value="Salut!")
    monkeypatch.setattr(web, "orch", mock)

    body = TestClient(web.app).post("/chat", json={"message": "hello"}).json()

    assert body["reply"] == "Salut!"
    assert body["pending_approvals"] == []


def test_chat_stream_end_event_carries_the_ids(monkeypatch):
    """Stream parity: the HUD's primary surface is /chat/stream, so an approval
    queued there must be nameable too — the runner task's context copy included."""
    mock = MagicMock()

    async def _stream(message, channel, on_token, agent_override=None, **kw):
        await on_token("one moment")
        await asyncio.to_thread(record_pending_approval, 7)  # a worker thread's copy
        return "I paused the tool loop because this action requires approval."

    mock.handle_input_stream = _stream
    monkeypatch.setattr(web, "orch", mock)

    body = TestClient(web.app).post("/chat/stream", json={"message": "mail ana"}).text
    end = [json.loads(c[len("data: "):]) for c in body.split("\n\n")
           if c.strip().startswith("data: ") and '"end"' in c][-1]

    assert end["pending_approvals"] == [7]


def test_chat_response_schema_declares_pending_approvals():
    """The HUD's generated types come from this schema — the field must be in it."""
    schema = web.app.openapi()["components"]["schemas"]["ChatResponse"]

    assert "pending_approvals" in schema["properties"]


def test_a_turn_that_queued_then_failed_still_names_what_it_queued(monkeypatch):
    """The failure branch is where a silent drop would hurt most.

    `/chat` answers a crashed turn with a constant "Internal error." — but whatever
    the turn pushed onto the approval queue before it raised is still sitting there,
    waiting for a decision. Reporting an empty list would tell the caller nothing is
    pending while a row it can neither see nor name is.
    """
    mock = MagicMock()

    async def _turn(message, channel="web", agent_override=None, **kw):
        record_pending_approval(55)
        raise RuntimeError("the turn fell over after queueing")

    mock.handle_input = _turn
    monkeypatch.setattr(web, "orch", mock)

    body = TestClient(web.app).post("/chat", json={"message": "mail ana"}).json()

    assert body["reply"] == "Internal error."
    assert body["pending_approvals"] == [55], (
        "a turn queued an approval and then crashed; the id was dropped, so the row "
        "is on the queue with nobody told about it"
    )


def test_a_stream_that_queued_then_failed_still_names_what_it_queued(monkeypatch):
    """Stream parity for the same case — the error end event carries the ids too."""
    mock = MagicMock()

    async def _stream(message, channel, on_token, agent_override=None, **kw):
        record_pending_approval(56)
        raise RuntimeError("the streamed turn fell over after queueing")

    mock.handle_input_stream = _stream
    monkeypatch.setattr(web, "orch", mock)

    body = TestClient(web.app).post("/chat/stream", json={"message": "mail ana"}).text
    end = [json.loads(c[len("data: "):]) for c in body.split("\n\n")
           if c.strip().startswith("data: ") and '"end"' in c][-1]

    assert end["text"] == "Eroare internă."
    assert end["pending_approvals"] == [56], (
        "the streamed failure branch dropped the id of a row still on the queue"
    )


# ── no turn bound: the recorder must get out of the way ──────────────────────
#
# Every test above runs with a collector bound. The gated enqueue sites are also
# reached with *none* — and that is the path where a mistake is invisible, so it
# is pinned at three levels: the function, the RPC surface, and the HTTP route
# whose docstring promises the behaviour.

def test_recording_outside_a_turn_is_a_no_op():
    assert current_turn_approvals() == [], "a collector leaked in from another test"
    record_pending_approval(7)
    assert current_turn_approvals() == []


@pytest.mark.asyncio
async def test_a_gated_call_with_no_turn_bound_still_answers_approval_required():
    """`ToolRPCServer.handle` is reached without a turn by the MCP server surface,
    the mesh and multimodal routers, `capability_actions`, both reality harnesses
    and the background autonomy ticks. The recorder runs *after* the row is
    queued, so raising there would strand a real queue row and hand the caller an
    exception instead of the id."""
    queue = _FakeQueue()
    server = _gated_server(queue.enqueue)

    result = await server.handle({"tool": "send_mail", "args": {"to": "ana"}})

    assert result == {"ok": False, "reason": "approval_required",
                      "tool": "send_mail", "task_id": 1}
    assert queue.calls, "the row must still be queued — reporting is the only thing skipped"


def test_the_governed_rpc_route_still_answers_a_gated_call(monkeypatch):
    """`POST /api/toolrpc/call` says in its own docstring that a gated tool
    returns `approval_required` + a task id. It runs no turn, so this is the
    user-visible shape of the bug: a 500 in place of a 422 carrying the id."""
    queue = _FakeQueue()
    mock = MagicMock()
    mock.tool_rpc = _gated_server(queue.enqueue)
    monkeypatch.setattr(web, "orch", mock)

    r = TestClient(web.app).post("/api/toolrpc/call",
                                 json={"tool": "send_mail", "args": {"to": "ana"}})

    assert r.status_code == 422
    assert r.json() == {"ok": False, "reason": "approval_required",
                        "tool": "send_mail", "task_id": 1}
