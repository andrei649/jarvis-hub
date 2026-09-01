"""DRA-08 Phase 5 — channel_handler is wired to the channel-session primitives.

Until this phase, `Orchestrator.channel_handler` hand-rolled `f"tg:{chat_id}"`
for telegram only, dropped every other channel onto the single shared
`session_id`, and delivered unconditionally. This module pins the wired
behaviour: session identity comes from `build_session_key(SessionSource(...))`
and delivery goes through `DeliveryRouter.resolve()`.

`tests/test_cross_channel_sessions.py` stays the untouched fence for the
behaviour that must NOT change (telegram isolation default, the cross-channel
flag, web staying shared).
"""

import sys
from pathlib import Path
from types import SimpleNamespace

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.channels.session import SessionSource, build_session_key  # noqa: E402
from agents.core.orchestrator import Orchestrator  # noqa: E402


def _bare_orchestrator(response="ok", resumable=()):
    """An Orchestrator with only what channel_handler touches wired up.

    Mirrors tests/test_cross_channel_sessions.py so the two files agree on the
    harness; the extra capture here is *which* session id was requested from
    memory and *what* was handed to channel_manager.send.
    """
    orch = Orchestrator.__new__(Orchestrator)
    orch._channel_sessions = {}
    orch._runtime_settings = {}
    orch.session_id = "web_shared"

    captured = {"new_session_ids": [], "resumed_ids": [], "sent": [], "sessions": []}

    async def fake_handle_input(text, channel="voice", agent_override=None):
        captured["session"] = orch.session_id
        captured["sessions"].append(orch.session_id)
        return response

    orch.handle_input = fake_handle_input

    class FakeMem:
        # `resumable` models what is already on disk. The handler must RESUME an
        # existing transcript and only CREATE when there is none — see
        # test_a_restart_resumes_the_transcript_instead_of_erasing_it below.
        def __init__(self, resumable=()):
            self.resumable = set(resumable)

        async def new_session(self, session_id=None):
            captured["new_session_ids"].append(session_id)
            return f"mem:{session_id}"

        async def resume_session(self, session_id):
            captured["resumed_ids"].append(session_id)
            return session_id in self.resumable

    orch.memory = FakeMem(resumable=resumable)

    async def fake_send(channel, message, **kwargs):
        captured["sent"].append((channel, message, kwargs))
        return True

    orch.channel_manager = SimpleNamespace(send=fake_send)
    return orch, captured


async def test_telegram_session_key_is_derived_not_hand_rolled():
    """The `tg:{chat_id}` string is gone; the key is build_session_key()'s."""
    orch, cap = _bare_orchestrator()

    await orch.channel_handler("salut", channel="telegram", chat_id="123", sender="42")

    expected = build_session_key(
        SessionSource(channel="telegram", sender="42", thread_id="123")
    )
    assert cap["new_session_ids"] == [expected]
    assert cap["session"] == f"mem:{expected}"
    assert set(orch._channel_sessions) == {expected}
    assert "tg:123" not in orch._channel_sessions
    # Deterministic across boots: the same chat re-enters the same session.
    await orch.channel_handler("iar", channel="telegram", chat_id="123", sender="42")
    assert cap["new_session_ids"] == [expected]  # not re-created
    assert cap["session"] == f"mem:{expected}"


async def test_two_email_senders_get_two_sessions():
    """Today every email lands on the shared session; each sender gets its own."""
    orch, cap = _bare_orchestrator()

    await orch.channel_handler(
        "a", channel="email", sender="a@x.test", from_addr="a@x.test", subject="s"
    )
    first = cap["session"]
    await orch.channel_handler(
        "b", channel="email", sender="b@x.test", from_addr="b@x.test", subject="s"
    )
    second = cap["session"]

    assert first != second
    assert first != "web_shared" and second != "web_shared"
    assert len(orch._channel_sessions) == 2
    assert cap["new_session_ids"] == [
        build_session_key(SessionSource(channel="email", sender="a@x.test")),
        build_session_key(SessionSource(channel="email", sender="b@x.test")),
    ]


async def test_identityless_source_stays_on_the_shared_session():
    """Voice carries no sender/thread/client — it must not fork a session."""
    orch, cap = _bare_orchestrator()

    await orch.channel_handler("salut", channel="voice")

    assert cap["session"] == "web_shared"
    assert cap["new_session_ids"] == []
    assert orch._channel_sessions == {}


async def test_cross_channel_flag_still_shares_the_session():
    orch, cap = _bare_orchestrator()
    orch._runtime_settings = {"memory.cross_channel_sessions": True}

    await orch.channel_handler("salut", channel="telegram", chat_id="123", sender="42")

    assert cap["session"] == "web_shared"
    assert cap["new_session_ids"] == []
    assert orch._channel_sessions == {}


async def test_empty_response_is_not_delivered():
    """DeliveryRouter.resolve() returns send=False for an empty reply."""
    orch, cap = _bare_orchestrator(response="")

    await orch.channel_handler("salut", channel="telegram", chat_id="123", sender="42")

    assert cap["sent"] == []


async def test_none_response_is_not_delivered():
    orch, cap = _bare_orchestrator(response=None)

    await orch.channel_handler("salut", channel="telegram", chat_id="123", sender="42")

    assert cap["sent"] == []


async def test_non_empty_response_is_delivered_on_its_home_channel():
    orch, cap = _bare_orchestrator()

    await orch.channel_handler("salut", channel="telegram", chat_id="123", sender="42")

    assert cap["sent"] == [("telegram", "ok", {"chat_id": "123", "sender": "42"})]


async def test_a_restart_resumes_the_transcript_instead_of_erasing_it():
    """The deterministic key must not become a data-loss bug.

    `_channel_sessions` is per-process, so the create branch is taken on the FIRST
    turn after every restart. `MemoryManager.new_session(key)` seeds an EMPTY turn
    list and never touches disk (memory/conversation.py:81-88 — only
    `resume_session` calls `load_memory`). Pairing a now-deterministic key with
    `new_session` therefore reopens the SAME session id with no history and
    overwrites the persisted transcript on the next save: the stable key turning
    into silent data loss, strictly worse than the per-boot random id it replaced.

    Two adversarial reviewers found this independently on the first implementation.
    This test is the fence: resume first, create only when there is nothing to resume.
    """
    expected = build_session_key(
        SessionSource(channel="telegram", sender="42", thread_id="123")
    )

    # A restart where the transcript IS on disk: resume it, never re-create.
    orch, cap = _bare_orchestrator(resumable={expected})
    await orch.channel_handler("salut", channel="telegram", chat_id="123", sender="42")
    assert cap["resumed_ids"] == [expected], "the handler must try to resume first"
    assert cap["new_session_ids"] == [], "resuming must not also create — that erases it"
    assert orch._channel_sessions[expected] == expected

    # A genuinely new conversation: nothing to resume, so create.
    orch2, cap2 = _bare_orchestrator()
    await orch2.channel_handler("salut", channel="telegram", chat_id="123", sender="42")
    assert cap2["resumed_ids"] == [expected]
    assert cap2["new_session_ids"] == [expected]
