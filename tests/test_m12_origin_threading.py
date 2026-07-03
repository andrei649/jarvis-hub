"""M1.2 / Action.origin threading for inbound channels."""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.action_origin import (  # noqa: E402
    bind_action_origin,
    current_action_origin,
    reset_action_origin,
)
from agents.core.autonomy.policy import AutonomyPolicy  # noqa: E402
from agents.core.channels.gateway import Gateway  # noqa: E402
from agents.core.kernel import Decision, Verdict  # noqa: E402
from agents.core.kernel.binding import make_action_kernel  # noqa: E402
from agents.core.orchestrator import Orchestrator  # noqa: E402
from agents.core.social import SocialBroker  # noqa: E402


class _FakeQueue:
    def __init__(self):
        self.calls = []

    def enqueue(self, agent, kind, title, payload=None, risk_tier=3,
                autonomy_level="ask", origin="generated"):
        self.calls.append({
            "agent": agent,
            "kind": kind,
            "title": title,
            "payload": payload,
            "risk_tier": risk_tier,
            "autonomy_level": autonomy_level,
            "origin": origin,
        })
        return len(self.calls)


def _orch_stub(policy=None):
    return SimpleNamespace(
        autonomy_policy=policy or AutonomyPolicy(),
        kill_switch=None,
        capabilities=None,
        intent_log=None,
    )


def test_gateway_threads_origin_from_channel():
    seen = []

    async def handler(text, channel="web", **kwargs):
        seen.append((text, channel, kwargs.get("origin")))
        return "ok"

    gateway = Gateway(handler=handler)

    assert asyncio.run(gateway.route("from tg", channel="telegram")) == "ok"
    assert asyncio.run(gateway.route("from hud", channel="web")) == "ok"

    assert seen == [
        ("from tg", "telegram", "inbound"),
        ("from hud", "web", "generated"),
    ]


def test_channel_handler_origin_context_is_request_local():
    orch = Orchestrator.__new__(Orchestrator)
    orch._channel_sessions = {}
    orch.get_setting = lambda *_args, **_kwargs: False
    sent = []

    async def send(channel, response, **kwargs):
        sent.append((channel, response, kwargs))

    orch.channel_manager = SimpleNamespace(send=send)
    seen = {}

    async def handle_input(text, channel):
        seen[(text, "before")] = current_action_origin()
        await asyncio.sleep(0)
        seen[(text, "after")] = current_action_origin()
        return current_action_origin()

    orch.handle_input = handle_input

    async def run():
        return await asyncio.gather(
            Orchestrator.channel_handler(orch, "tg", channel="telegram"),
            Orchestrator.channel_handler(orch, "hud", channel="web"),
        )

    assert asyncio.run(run()) == ["inbound", "generated"]
    assert seen == {
        ("tg", "before"): "inbound",
        ("tg", "after"): "inbound",
        ("hud", "before"): "generated",
        ("hud", "after"): "generated",
    }
    assert current_action_origin() == "generated"
    assert [item[2] for item in sent] == [{}, {}]


def test_broker_action_carries_current_origin(monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    seen = []

    def kernel(action):
        seen.append(action)
        return Decision(Verdict.GRANT, reason="ok", tier=2)

    token = bind_action_origin("inbound")
    try:
        out = SocialBroker(enqueue=_FakeQueue().enqueue, kernel=kernel).request(
            "x", "post", {"text": "hello"})
    finally:
        reset_action_origin(token)

    assert out["ok"] is True
    assert seen and seen[0].origin == "inbound"


def test_inbound_origin_escalates_real_policy_grant_to_queue(monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    kernel = make_action_kernel(_orch_stub())
    q = _FakeQueue()

    token = bind_action_origin("inbound")
    try:
        out = SocialBroker(enqueue=q.enqueue, kernel=kernel).request(
            "x", "post", {"text": "notify-worthy external action"})
    finally:
        reset_action_origin(token)

    assert out["ok"] is True
    assert q.calls[0]["autonomy_level"] == "ask"

    q = _FakeQueue()
    out = SocialBroker(enqueue=q.enqueue, kernel=kernel).request(
        "x", "post", {"text": "same action from HUD"})
    assert out["ok"] is True
    assert q.calls[0]["autonomy_level"] == "act"


def test_kernel_off_keeps_broker_default_path(monkeypatch):
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    seen = []

    def kernel(action):
        seen.append(action)
        return Decision(Verdict.GRANT, reason="ok", tier=2)

    q = _FakeQueue()
    token = bind_action_origin("inbound")
    try:
        out = SocialBroker(enqueue=q.enqueue, kernel=kernel).request(
            "x", "post", {"text": "kernel disabled"})
    finally:
        reset_action_origin(token)

    assert out["ok"] is True
    assert seen == []
    assert q.calls[0]["autonomy_level"] == "ask"
    assert q.calls[0]["origin"] == "generated"
