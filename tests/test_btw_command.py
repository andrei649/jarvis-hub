"""H414 — ``/btw <question>``: a side question ABOUT the conversation, beside it.

Hermes answers ``/btw`` without adding synthetic turns. Nerva's version reads a bounded,
redacted snapshot of the session (the same snapshot ``/refine`` reviews: newest turns
first, commands and their replies left out), asks the auxiliary rail once through
``run_oneshot`` — strict-local, job pins excluded, the auxiliary consent boundary — and
hands the answer back as a command result. The orchestrator dispatches it before the
turn is appended, so neither the question nor the answer becomes a user or assistant
turn, and the conversation the model sees next is exactly the one it saw before.

Hermetic: orchestrator doubles, a loopback backend double, no model.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.core import settings_db
from agents.core.commands import (
    CommandOutcome,
    CommandRegistry,
    Principal,
    build_default_registry,
    checkpoint_command_name,
    preappend_command_name,
    side_question_command_name,
)
from agents.core.llm import auxiliary_text
from agents.core.llm.providers import get_profile
from agents.core.orchestrator import Orchestrator, bind_turn_principal, reset_turn_principal

OWNER = Principal(channel="telegram", sender="42", admin=True)
GUEST = Principal(channel="telegram", sender="7", admin=False)
SECRET = "sk-" + "A1b2C3d4" * 6
TURNS = [
    {"role": "user", "content": "plan the trip to Cluj for the 14th", "channel": "web"},
    {"role": "assistant", "content": "Noted: Cluj on the 14th. Train or car?", "agent_id": "jarvis"},
    {"role": "user", "content": "/recap", "channel": "web"},
    {"role": "assistant", "content": "Previous conversation: ...", "agent_id": "commands"},
    {"role": "user", "content": f"use the key {SECRET} for the booking api", "channel": "web"},
    {"role": "assistant", "content": "I will not keep that key in the conversation.", "agent_id": "jarvis"},
]


@pytest.fixture
def rail(monkeypatch):
    """A loopback local backend double behind the real auxiliary policy."""
    monkeypatch.delenv("JARVIS_AUX_ONESHOT_MODEL", raising=False)
    monkeypatch.setattr(auxiliary_text, "_ONESHOT_USAGE", {})
    calls = []

    async def generate(**kwargs):
        calls.append(kwargs)
        return "You first asked to plan the trip to Cluj for the 14th."

    backend = SimpleNamespace(profile=get_profile("lm-studio"), base_url="http://127.0.0.1:1234",
                              generate=generate)
    router = SimpleNamespace(local_backend=backend, active_model="active-local",
                             _backend=backend, _local_model="active-local")
    return SimpleNamespace(router=router, backend=backend, calls=calls)


def _orch(rail, turns=TURNS, *, shared=False, session="s-1"):
    written = []

    class Memory:
        async def get_history(self, session_id, last_n=None):
            assert session_id == session
            return list(turns)

        async def add_turn(self, *args, **kwargs):
            written.append((args, kwargs))

    orch = SimpleNamespace(commands=build_default_registry(), llm_router=rail.router,
                           session_id=session, memory=Memory(), on_shared_session=lambda: shared,
                           written=written)
    return orch


# ── the command ───────────────────────────────────────────────────────────────────


async def test_btw_answers_from_a_bounded_redacted_snapshot_and_writes_no_turn(rail):
    orch = _orch(rail)
    outcome = await orch.commands.dispatch("/btw what did I ask first?", orch=orch, principal=OWNER)
    assert outcome.status == "answered"
    assert outcome.reply == "You first asked to plan the trip to Cluj for the 14th."
    assert orch.written == []
    (call,) = rail.calls
    prompt = call["prompt"]
    # The conversation goes in as role lines, the question after it; commands and the
    # hub's replies to them are not conversation.
    assert "user: plan the trip to Cluj for the 14th" in prompt
    assert "assistant: Noted: Cluj on the 14th. Train or car?" in prompt
    assert "/recap" not in prompt and "Previous conversation" not in prompt
    assert prompt.rstrip().endswith("what did I ask first?")
    # Redacted before it leaves the session: the key the owner pasted is not in the prompt.
    assert SECRET not in prompt and "booking api" in prompt
    assert "conversation" in call["system"].lower()
    assert call["max_tokens"] == auxiliary_text.BTW_MAX_TOKENS
    assert auxiliary_text.oneshot_usage()["btw"] == {
        "calls": 1, "answered": 1, "refused": 0, "max_tokens": auxiliary_text.BTW_MAX_TOKENS,
        "model": call["model"], "prompt_chars": len(call["system"]) + len(prompt),
        "last_at": auxiliary_text.oneshot_usage()["btw"]["last_at"],
    }


async def test_btw_without_a_question_explains_itself_and_calls_no_model(rail):
    orch = _orch(rail)
    outcome = await orch.commands.dispatch("/btw", orch=orch, principal=OWNER)
    assert outcome.status == "answered" and outcome.reply.startswith("Usage: /btw <question>")
    assert rail.calls == [] and orch.written == []


async def test_btw_bounds_the_question(rail):
    orch = _orch(rail)
    await orch.commands.dispatch("/btw " + "why " * 400, orch=orch, principal=OWNER)
    (call,) = rail.calls
    assert call["prompt"].rstrip().endswith("why")
    assert len(call["prompt"]) < auxiliary_text.BTW_SNAPSHOT_CHARS + auxiliary_text.BTW_QUESTION_CHARS + 200


async def test_btw_on_the_owners_shared_session_answers_only_the_owner(rail):
    orch = _orch(rail, shared=True)
    guest = await orch.commands.dispatch("/btw what did I ask?", orch=orch, principal=GUEST)
    assert guest.status == "answered" and "only for the owner" in guest.reply
    assert rail.calls == []
    owner = await orch.commands.dispatch("/btw what did I ask?", orch=orch, principal=OWNER)
    assert owner.reply.startswith("You first asked")
    # A turn on a session of its own: whoever the channel admitted may ask about it.
    own = _orch(rail, shared=False)
    assert (await own.commands.dispatch("/btw what did I ask?", orch=own, principal=GUEST)).reply.startswith("You first asked")


@pytest.mark.parametrize("turns", [[], [{"role": "user", "content": "/status"},
                                        {"role": "assistant", "content": "Nerva ...", "agent_id": "commands"}]])
async def test_btw_with_nothing_to_ask_about_says_so(rail, turns):
    orch = _orch(rail, turns)
    outcome = await orch.commands.dispatch("/btw what did I ask?", orch=orch, principal=OWNER)
    assert outcome.reply == "There is no conversation here to ask about yet."
    assert rail.calls == []


async def test_btw_without_a_conversation_or_a_router_says_so(rail):
    registry = build_default_registry()
    no_memory = await registry.dispatch("/btw why?", orch=SimpleNamespace(session_id=None), principal=OWNER)
    assert no_memory.reply == "There is no conversation here to ask about yet."
    orch = _orch(rail)
    orch.llm_router = None
    no_router = await registry.dispatch("/btw why?", orch=orch, principal=OWNER)
    assert "needs a local model" in no_router.reply and rail.calls == []


async def test_btw_without_a_local_backend_is_honest_and_never_reaches_a_cloud_route(rail):
    class Router:
        active_model = None

        @property
        def local_backend(self):
            raise RuntimeError("No local LLM backend available (strict-local path).")

    orch = _orch(rail)
    orch.llm_router = Router()
    outcome = await orch.commands.dispatch("/btw why?", orch=orch, principal=OWNER)
    assert outcome.status == "answered"
    assert "needs a local model" in outcome.reply and "never leave this machine" in outcome.reply
    assert rail.calls == [] and orch.written == []


async def test_btw_is_excluded_by_a_job_model_pin(rail):
    from agents.core.llm.job_selection import selection_scope

    orch = _orch(rail)
    with selection_scope({"model": "pinned-model"}):
        outcome = await orch.commands.dispatch("/btw why?", orch=orch, principal=OWNER)
    assert "job" in outcome.reply and "pin" in outcome.reply
    assert rail.calls == []


async def test_btw_inherits_the_auxiliary_consent_boundary(rail, tmp_path, monkeypatch):
    """The same refusal the fixed auxiliary tasks get on a warned, unacknowledged route."""
    from agents.core.llm import data_handling

    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.init_db(force=True)
    monkeypatch.setattr(data_handling, "_scope_key", lambda: b"btw-test-scope-key")
    rail.backend.api_key = "synthetic"
    rail.backend.base_url = "https://gateway.invalid"
    orch = _orch(rail)
    token = bind_turn_principal(OWNER)
    try:
        outcome = await orch.commands.dispatch("/btw why?", orch=orch, principal=OWNER)
    finally:
        reset_turn_principal(token)
    assert outcome.status == "answered" and "acknowledg" in outcome.reply
    assert rail.calls == [] and orch.written == []


async def test_btw_in_safe_mode_still_answers_strictly_locally(rail, monkeypatch):
    """Safe mode takes owner customizations away; a local read-only side question is
    not one, and the rail it runs on cannot reach a cloud backend in any mode."""
    monkeypatch.setenv("JARVIS_SAFE_MODE", "1")
    orch = _orch(rail)
    outcome = await orch.commands.dispatch("/btw what did I ask first?", orch=orch, principal=OWNER)
    assert outcome.reply.startswith("You first asked")
    assert len(rail.calls) == 1 and orch.written == []


async def test_btw_model_failures_are_reported_not_raised(rail):
    async def broken(**kwargs):
        raise ValueError("backend exploded")

    rail.backend.generate = broken
    orch = _orch(rail)
    outcome = await orch.commands.dispatch("/btw why?", orch=orch, principal=OWNER)
    assert outcome.status == "answered" and "could not be answered" in outcome.reply
    assert orch.written == []


async def test_btw_is_listed_with_its_siblings(rail):
    orch = _orch(rail)
    listed = await orch.commands.dispatch("/help", orch=orch, principal=GUEST)
    assert "/btw <question> — ask a side question about this conversation; nothing is added to it" in listed.reply
    assert "btw" in {c.name for c in build_default_registry().visible(GUEST)}


# ── the orchestrator keeps it out of the exchange ─────────────────────────────────


def test_the_side_question_is_recognised_as_a_pre_append_command():
    assert side_question_command_name("/btw what?") == "btw"
    assert side_question_command_name("/BTW@nerva_bot what?") == "btw"
    assert side_question_command_name("/btwx what?") is None
    assert side_question_command_name("hello /btw") is None
    assert side_question_command_name(None) is None
    assert preappend_command_name("/btw what?") == "btw"
    assert preappend_command_name("/rollback") == checkpoint_command_name("/rollback") == "rollback"
    assert preappend_command_name("/recap") is None


def _bare(rail, *, admin=True):
    orch = Orchestrator.__new__(Orchestrator)
    double = _orch(rail)
    orch.commands = double.commands
    orch.memory = double.memory
    orch.llm_router = rail.router
    orch.session_id = "s-1"
    orch._runtime_settings = {}
    orch._resolve_session = lambda session_id: "s-1"

    async def nothing(*args, **kwargs):
        return None

    orch._guard_foreign_turn = nothing
    orch._guard_media_history = nothing
    orch._direct_session_command = nothing
    orch.on_shared_session = lambda: False
    return orch, double.written


async def test_handle_input_answers_btw_before_the_turn_is_appended(rail):
    orch, written = _bare(rail)
    token = bind_turn_principal(OWNER)
    try:
        reply = await orch.handle_input("/btw what did I ask first?", channel="web")
    finally:
        reset_turn_principal(token)
    assert reply == "You first asked to plan the trip to Cluj for the 14th."
    assert written == []
    assert orch.last_cognition["trace"][0]["result"] == "/btw:answered"


async def test_handle_input_stream_answers_btw_before_the_turn_is_appended(rail):
    orch, written = _bare(rail)
    emitted = []

    async def on_token(text):
        emitted.append(text)

    token = bind_turn_principal(OWNER)
    try:
        reply = await orch.handle_input_stream("/btw what did I ask first?", channel="web", on_token=on_token)
    finally:
        reset_turn_principal(token)
    assert reply.startswith("You first asked") and emitted == [reply]
    assert written == []


async def test_a_refused_or_failed_side_question_still_adds_no_turn(rail):
    orch, written = _bare(rail)
    orch.on_shared_session = lambda: True
    token = bind_turn_principal(GUEST)
    try:
        reply = await orch.handle_input("/btw what did I ask first?", channel="web")
    finally:
        reset_turn_principal(token)
    assert "only for the owner" in reply and written == [] and rail.calls == []

    async def failing(text):
        return None

    orch._dispatch_command = failing
    token = bind_turn_principal(OWNER)
    try:
        reply = await orch.handle_input("/btw what did I ask first?", channel="web")
    finally:
        reset_turn_principal(token)
    assert reply == "/btw failed — check the hub log." and written == []


async def test_a_plain_message_still_takes_the_ordinary_path(rail):
    orch, written = _bare(rail)

    def stop(*args, **kwargs):
        raise RuntimeError("the ordinary turn path")

    orch._begin_chat_outcomes = stop
    token = bind_turn_principal(OWNER)
    try:
        with pytest.raises(RuntimeError, match="ordinary turn path"):
            await orch.handle_input("plan the next step", channel="web")
    finally:
        reset_turn_principal(token)
    assert written and written[0][0][1:3] == ("user", "plan the next step")


def test_dispatch_outcome_shape_is_unchanged():
    assert CommandOutcome("btw", "answered", "x").status == "answered"
    assert CommandRegistry.parse("/btw  why ") == ("btw", "why")
