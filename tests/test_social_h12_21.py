"""H12.21 — Governed social actions (X/Twitter post/reply/DM).

Verifies the governance layer end-to-end, all offline: request → validated →
ask-tier task → (approval) → credentials resolved behind approval → injectable
client (no real network).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import pytest

from agents.core.automation_contracts import ContractDecision
from agents.core.social import (
    SocialBroker, NullSocialClient, HttpSocialClient, build_social_request, _CATALOG,
)
from agents.core.security.secret_broker import SecretBroker


class _FakeQueue:
    def __init__(self):
        self.calls = []

    def enqueue(self, agent, kind, title, payload=None, risk_tier=3,
                autonomy_level="ask", origin="generated"):
        self.calls.append(dict(agent=agent, kind=kind, title=title, payload=payload,
                               risk_tier=risk_tier, autonomy_level=autonomy_level,
                               origin=origin))
        return len(self.calls)


class _Task:
    def __init__(self, kind, payload):
        self.kind = kind
        self.payload = payload


def test_targets_lists_catalog():
    t = SocialBroker().targets()
    assert len(t) == len(_CATALOG) == 3
    kinds = {x["kind"] for x in t}
    assert kinds == {"social.x.post", "social.x.reply", "social.x.dm"}
    post = next(x for x in t if x["kind"] == "social.x.post")
    assert post["required"] == ["text"] and post["credential"] == "x_api_token"


def test_supports():
    assert SocialBroker.supports("x", "post")
    assert SocialBroker.supports("X", "DM")
    assert not SocialBroker.supports("x", "delete")
    assert not SocialBroker.supports("mastodon", "post")


def test_request_unknown_platform_action():
    out = SocialBroker().request("mastodon", "toot", {"text": "hi"})
    assert out["ok"] is False and out["reason"] == "unknown_platform_action"
    assert "x.post" in out["supported"]


def test_request_missing_required_fields():
    out = SocialBroker().request("x", "reply", {"text": "hi"})  # missing reply_to
    assert out["ok"] is False and out["missing"] == ["reply_to"]


def test_request_preview_mode():
    out = SocialBroker().request("x", "post", {"text": "hello world"})
    assert out["ok"] is True and out["queued"] is False
    assert out["preview"]["would_execute"] is False
    assert out["preview"]["requires_approval"] is True


def test_request_enqueues_governed_task():
    q = _FakeQueue()
    out = SocialBroker(enqueue=q.enqueue).request(
        "x", "post", {"text": "shipping H12.21"}, agent="pepper")
    assert out["ok"] is True and out["queued"] is True
    call = q.calls[0]
    assert call["kind"] == "social.x.post"
    assert call["autonomy_level"] == "ask" and call["risk_tier"] == 2
    p = call["payload"]
    assert p["platform"] == "x" and p["action"] == "post"
    assert p["credential_ref"] == "{{secret:x_api_token}}"
    assert p["fields"]["text"] == "shipping H12.21"


def test_request_obeys_live_social_draft_contract(monkeypatch):
    import agents.core.social as social

    class _FakeSocialDraftContract:
        def __init__(self):
            self.calls = []

        def evaluate(self, payload=None, **kwargs):
            payload = payload or {}
            self.calls.append((payload, kwargs))
            return ContractDecision(
                kind="social_draft",
                admissible=False,
                requires_approval=True,
                reason="contract_denied",
                checked=("fake",),
            )

    q = _FakeQueue()
    contract = _FakeSocialDraftContract()
    monkeypatch.setattr(social, "SOCIAL_DRAFT_CONTRACT", contract, raising=False)

    out = social.SocialBroker(enqueue=q.enqueue).request(
        "x",
        "post",
        {"text": "ship through the contract"},
        agent="pepper",
        source="safe-comms",
    )

    assert out == {"ok": False, "reason": "contract_denied", "kind": "social.x.post"}
    assert q.calls == []
    assert len(contract.calls) == 1
    payload, kwargs = contract.calls[0]
    assert payload["kind"] == "social.x.post"
    assert payload["platform"] == "x"
    assert payload["action"] == "post"
    assert payload["agent"] == "pepper"
    assert payload["source"] == "safe-comms"
    assert payload["fields"]["text"] == "ship through the contract"
    assert "now" in kwargs


def test_request_caps_text_length():
    q = _FakeQueue()
    SocialBroker(enqueue=q.enqueue).request("x", "post", {"text": "z" * 9000})
    assert len(q.calls[0]["payload"]["fields"]["text"]) == 4000


def test_build_request_post():
    spec = build_social_request("x", "post", {"text": "hi"}, {"token": "t"})
    assert spec["method"] == "POST"
    assert spec["url"] == "https://api.twitter.com/2/tweets"
    assert spec["headers"]["Authorization"] == "Bearer t"
    assert spec["json"] == {"text": "hi"}


def test_build_request_reply():
    spec = build_social_request("x", "reply", {"text": "hi", "reply_to": "123"}, {"token": "t"})
    assert spec["json"]["reply"]["in_reply_to_tweet_id"] == "123"


def test_build_request_dm():
    spec = build_social_request("x", "dm", {"text": "yo", "recipient": "u99"}, {"token": "t"})
    assert spec["url"].endswith("/dm_conversations/with/u99/messages")
    assert spec["json"] == {"text": "yo"}


def test_build_request_unsupported_raises():
    with pytest.raises(ValueError):
        build_social_request("x", "delete", {}, {})


@pytest.mark.asyncio
async def test_execute_null_client_no_network():
    null = NullSocialClient()
    broker = SocialBroker(client=null)
    task = _Task("social.x.post",
                 {"platform": "x", "action": "post", "fields": {"text": "hi"},
                  "credential_ref": "{{secret:x_api_token}}"})
    out = await broker.execute(task)
    assert out["status"] == "ok" and out["social"]["status"] == "deferred"
    assert null.calls[0]["platform"] == "x" and null.calls[0]["has_credential"] is False


@pytest.mark.asyncio
async def test_execute_resolves_credentials_behind_approval():
    sb = SecretBroker()
    sb.put("x_api_token", "bearer_secret")

    class _Rec:
        last = None
        async def send(self, platform, action, fields, credentials):
            _Rec.last = credentials
            return {"status": "ok"}

    broker = SocialBroker(secret_broker=sb, client=_Rec())
    task = _Task("social.x.post",
                 {"platform": "x", "action": "post", "fields": {"text": "hi"},
                  "credential_ref": "{{secret:x_api_token}}"})
    await broker.execute(task)
    assert _Rec.last["token"] == "bearer_secret"


@pytest.mark.asyncio
async def test_http_client_sends_built_request():
    class _Resp:
        status_code = 201
        def raise_for_status(self): pass
        def json(self): return {"data": {"id": "9"}}

    class _Http:
        def __init__(self): self.calls = []
        async def request(self, method, url, headers=None, json=None):
            self.calls.append({"url": url, "json": json})
            return _Resp()

    http = _Http()
    out = await HttpSocialClient(http=http).send(
        "x", "post", {"text": "hi"}, {"token": "t"})
    assert out["status"] == "ok" and out["http_status"] == 201
    assert http.calls[0]["url"] == "https://api.twitter.com/2/tweets"


@pytest.mark.asyncio
async def test_end_to_end_governed_execution(tmp_path):
    from agents.core.autonomy.queue import TaskQueue, TaskStatus
    from agents.core.autonomy.worker import AutonomyWorker
    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.autonomy.executor import TaskExecutor

    q = TaskQueue(db_path=str(tmp_path / "autonomy.db")).initialize()
    try:
        sb = SecretBroker()
        sb.put("x_api_token", "bearer_e2e")
        null = NullSocialClient()
        broker = SocialBroker(enqueue=q.enqueue, secret_broker=sb, client=null)

        out = broker.request("x", "post", {"text": "announce H12.21"})
        tid = out["task_id"]
        assert q.get(tid).status == "proposed"
        assert null.calls == []

        q.transition(tid, TaskStatus.APPROVED, decided_by="andrei", decision="accept")

        executor = TaskExecutor()
        executor.register("social", broker.execute)
        worker = AutonomyWorker(q, policy=AutonomyPolicy(), executor=executor.execute)
        summary = await worker.tick()

        assert summary["done"] == 1 and q.get(tid).status == "done"
        assert len(null.calls) == 1 and null.calls[0]["has_credential"] is True
    finally:
        q.close()
