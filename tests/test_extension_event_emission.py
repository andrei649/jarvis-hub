"""The three places a lifecycle event is actually raised, and what they refuse to say.

An event bus nothing calls is an interface, not a feature, so this file pins the
call sites rather than the bus. Each one carries a decision about *what a watching
extension is allowed to learn*, and each of those decisions is the kind that is easy
to reverse by accident later:

* a command's **name and status** go out; its **reply never does**;
* an **unknown** command is not observed at all, because its "name" is whatever the
  sender typed — a message body wearing a safe label;
* a session boundary emits **ids only**, ended before started;
* a tool call emits the **name and status** the observability store had already cut,
  never its arguments and never its result.

The bus itself is replaced with a recorder here. What is being tested is that the
production code reaches it, with the right event, carrying nothing else.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from agents.core import commands as commands_module
from agents.core.extensions import events as events_module


class _Recorder:
    def __init__(self):
        self.emitted: list[tuple[str, dict]] = []

    def emit(self, event, **fields):
        # The real holder validates the name before anything else; keep that here so
        # a call site inventing an event name still fails loudly in these tests.
        if event not in events_module.FIELDS:
            raise ValueError("unknown_event")
        self.emitted.append((event, dict(fields)))
        return {"event": event, "observers": [], "delivered": [], "dropped": 0}


@pytest.fixture()
def recorder(monkeypatch):
    made = _Recorder()
    monkeypatch.setattr(events_module, "EXTENSION_EVENTS", made)
    return made


# ── command.completed ────────────────────────────────────────────────────────

def _registry():
    registry = commands_module.CommandRegistry()
    registry.register(commands_module.SlashCommand("ping", "answers", lambda _ctx: "pong"))
    registry.register(commands_module.SlashCommand(
        "danger", "owner only", lambda _ctx: "done", tier=commands_module.ADMIN))
    registry.register(commands_module.SlashCommand(
        "boom", "raises", lambda _ctx: (_ for _ in ()).throw(RuntimeError("x"))))
    return registry


@pytest.mark.asyncio
async def test_an_answered_command_is_observed_by_name_and_status_only(recorder):
    outcome = await _registry().dispatch("/ping", orch=None, principal=commands_module.Principal(admin=True))
    assert outcome.reply == "pong"
    assert recorder.emitted == [("command.completed", {"command": "ping", "status": "answered"})]


@pytest.mark.asyncio
async def test_the_commands_reply_never_leaves_with_the_event(recorder):
    """A handler can say anything. That is exactly why the reply is not carried."""
    registry = commands_module.CommandRegistry()
    registry.register(commands_module.SlashCommand(
        "secrets", "leaks", lambda _ctx: "the owner's private answer"))
    await registry.dispatch("/secrets", orch=None, principal=commands_module.Principal(admin=True))
    _, fields = recorder.emitted[0]
    assert "the owner's private answer" not in str(fields)
    assert set(fields) == {"command", "status"}


@pytest.mark.asyncio
async def test_a_refused_command_is_observed_because_its_name_came_from_the_registry(recorder):
    outcome = await _registry().dispatch("/danger", orch=None, principal=commands_module.Principal(admin=False))
    assert outcome.status == "refused"
    assert recorder.emitted == [("command.completed", {"command": "danger", "status": "refused"})]


@pytest.mark.asyncio
async def test_a_failing_command_is_observed_as_failed_without_its_traceback(recorder):
    outcome = await _registry().dispatch("/boom", orch=None, principal=commands_module.Principal(admin=True))
    assert outcome.status == "failed"
    assert recorder.emitted == [("command.completed", {"command": "boom", "status": "failed"})]


@pytest.mark.asyncio
async def test_an_unknown_command_is_deliberately_not_observed(recorder):
    """`name` here is whatever the sender typed. Emitting it would push arbitrary
    message text through a field that promises to carry command names."""
    outcome = await _registry().dispatch(
        "/my_bank_password_is_hunter2", orch=None, principal=commands_module.Principal(admin=True))
    assert outcome.status == "unknown"
    assert recorder.emitted == []


@pytest.mark.asyncio
async def test_text_that_is_not_a_command_emits_nothing(recorder):
    assert await _registry().dispatch("just talking", orch=None,
                                      principal=commands_module.Principal(admin=True)) is None
    assert recorder.emitted == []


# ── session.started / session.ended ──────────────────────────────────────────

class _Orchestrator:
    """The one real boundary, isolated from the rest of the orchestrator."""

    def __init__(self, session_id=None):
        self.session_id = session_id
        self.memory = SimpleNamespace(new_session=self._new)
        self.flushed = 0

    async def _new(self):
        return "session_new"

    async def _flush_checkpoint(self):
        self.flushed += 1

    new_session = None  # bound below


@pytest.fixture()
def orchestrator_new_session():
    from agents.core.orchestrator import Orchestrator

    return Orchestrator.new_session


@pytest.mark.asyncio
async def test_a_session_boundary_emits_ended_then_started_with_ids_only(recorder, orchestrator_new_session):
    orch = _Orchestrator(session_id="session_old")
    assert await orchestrator_new_session(orch) == "session_new"
    assert orch.session_id == "session_new"
    assert recorder.emitted == [
        ("session.ended", {"session_id": "session_old"}),
        ("session.started", {"session_id": "session_new"}),
    ]


@pytest.mark.asyncio
async def test_the_first_session_has_nothing_to_end(recorder, orchestrator_new_session):
    orch = _Orchestrator(session_id=None)
    await orchestrator_new_session(orch)
    assert recorder.emitted == [("session.started", {"session_id": "session_new"})]


@pytest.mark.asyncio
async def test_the_checkpoint_is_flushed_before_anyone_is_told(recorder, orchestrator_new_session):
    """Announcing a boundary before the outgoing session is safely on disk would
    invite an observer to read state that is about to be rewritten."""
    orch = _Orchestrator(session_id="session_old")
    order = []
    original = orch._flush_checkpoint

    async def flush():
        order.append("flush")
        await original()

    orch._flush_checkpoint = flush
    recorder.emit = lambda event, **fields: order.append(event)
    await orchestrator_new_session(orch)
    assert order == ["flush", "session.ended", "session.started"]


# ── tool.completed ───────────────────────────────────────────────────────────

def _store():
    from agents.core.observability.tool_events import ToolEventLog

    return ToolEventLog()


def test_a_finished_tool_call_is_observed_by_name_and_status(recorder):
    _store().record({"event": "tool_result", "tool": "file_read", "status": "ok",
                     "agent_id": "jarvis", "call_id": "c1"})
    assert recorder.emitted == [("tool.completed", {"tool": "file_read", "status": "ok"})]


def test_a_failed_tool_call_is_observed_too(recorder):
    _store().record({"event": "tool_failed", "tool": "web_search", "status": "timeout"})
    assert recorder.emitted == [("tool.completed", {"tool": "web_search", "status": "timeout"})]


@pytest.mark.parametrize("event", [
    "tool_requested", "tool_started", "tool_profile", "tool_loop_repeated",
    "tool_cap_reached", "tool_result_untrusted", "tool_result_deduplicated",
])
def test_only_the_terminal_pair_is_forwarded(recorder, event):
    """The store carries the whole trail; an extension is told about completions."""
    _store().record({"event": event, "tool": "file_read", "status": "ok"})
    assert recorder.emitted == []


def test_a_tool_events_argument_cannot_ride_along_because_it_never_arrives(recorder):
    """The store bounds every field before this fan-out sees it, so a caller that
    put an argument in the event still cannot put one in the extension's payload."""
    _store().record({"event": "tool_result", "tool": "file_read", "status": "ok",
                     "args": {"path": "/home/owner/.ssh/id_rsa"}})
    _, fields = recorder.emitted[0]
    assert set(fields) == {"tool", "status"}
    assert "id_rsa" not in str(fields)


def test_the_store_still_records_when_the_extension_fan_out_raises(recorder):
    """Observability must never break the turn it observes."""
    def explode(event, **fields):
        raise RuntimeError("bus unavailable")

    recorder.emit = explode
    store = _store()
    store.record({"event": "tool_result", "tool": "file_read", "status": "ok"})
    assert store.counts()["tool_result"] == 1


def test_recording_from_a_worker_thread_reaches_the_fan_out(recorder):
    async def run():
        await asyncio.to_thread(_store().record,
                                {"event": "tool_result", "tool": "file_read", "status": "ok"})

    asyncio.run(run())
    assert recorder.emitted == [("tool.completed", {"tool": "file_read", "status": "ok"})]
