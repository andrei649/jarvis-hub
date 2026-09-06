"""Live rails behind flags — write-back / social / call clients + connector wiring.

Slice ``live-rails-behind-flags`` (T-0.66, H10.30, H12.21, H12.22, H12.25):

* ``JARVIS_WRITEBACK_LIVE`` / ``JARVIS_SOCIAL_LIVE`` / ``JARVIS_CALL_LIVE`` unset →
  every broker constructs its Null client (byte-identical to before); set → the
  HTTP client with an injectable transport, host allowlist enforced, and an
  honest refusal (``credential_not_configured`` / ``call_config_missing:*``)
  instead of an unauthenticated request.
* The 0.66 connector builders (``writeback_connectors``) are reachable through
  ``WriteBackBroker.request`` / ``.execute`` (kind ``writeback.<target>.<action>``),
  credentials via the SecretBroker at execute time.
* Approved ``create_task`` / ``task.create`` tasks (transcript watcher) are mapped
  onto a Todoist / Notion write; unapproved tasks never reach the transport.

All offline: fake transport, in-memory SecretBroker, tmp SQLite queue.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import social as social_mod  # noqa: E402
from agents.core import writeback as wb_mod  # noqa: E402
from agents.core import writeback_connectors as wbc  # noqa: E402
from agents.core.autonomy import call_broker as cb_mod  # noqa: E402
from agents.core.autonomy.call_broker import (  # noqa: E402
    CallBroker,
    HttpCallClient,
    NullCallClient,
)
from agents.core.plugins.degradation import is_degraded  # noqa: E402
from agents.core.security.secret_broker import SecretBroker  # noqa: E402
from agents.core.social import HttpSocialClient, NullSocialClient, SocialBroker  # noqa: E402
from agents.core.writeback import (  # noqa: E402
    TASK_CREATE_KINDS,
    WRITEBACK_DRAFT_CONTRACT,
    HttpWriteBackClient,
    NullWriteBackClient,
    WriteBackBroker,
    build_any_request,
    map_task_create,
)

WB_FLAG, SOCIAL_FLAG, CALL_FLAG = "JARVIS_WRITEBACK_LIVE", "JARVIS_SOCIAL_LIVE", "JARVIS_CALL_LIVE"


# ── fakes ────────────────────────────────────────────────────────────────────

class _Resp:
    status_code = 201

    def raise_for_status(self):
        pass

    def json(self):
        return {"id": "created-1"}


class _Transport:
    """Stands in for PluginHTTPClient: records every request, no network."""

    def __init__(self):
        self.calls: list[dict] = []

    async def request(self, method, url, headers=None, json=None, params=None,
                      data=None, auth=None):
        self.calls.append({"method": method, "url": url, "headers": headers,
                           "json": json, "params": params, "data": data, "auth": auth})
        return _Resp()


class _FakeQueue:
    def __init__(self):
        self.calls = []

    def enqueue(self, agent, kind, title, payload=None, risk_tier=3,
                autonomy_level="ask", origin="generated"):
        self.calls.append({"agent": agent, "kind": kind, "title": title,
                           "payload": payload, "risk_tier": risk_tier,
                           "autonomy_level": autonomy_level, "origin": origin})
        return len(self.calls)


def _task(kind, payload):
    return SimpleNamespace(kind=kind, payload=payload)


def _secrets(**values):
    sb = SecretBroker()
    for name, value in values.items():
        sb.put(name, value)
    return sb


@pytest.fixture(autouse=True)
def _flags_unset(monkeypatch):
    for flag in (WB_FLAG, SOCIAL_FLAG, CALL_FLAG):
        monkeypatch.delenv(flag, raising=False)


# ── flag off → Null clients (byte-identical default) ─────────────────────────

def test_flags_unset_construct_null_clients():
    assert isinstance(WriteBackBroker()._client, NullWriteBackClient)
    assert isinstance(SocialBroker()._client, NullSocialClient)
    assert isinstance(CallBroker()._client, NullCallClient)
    assert WriteBackBroker().live is False
    assert SocialBroker().live is False
    assert CallBroker().live is False


@pytest.mark.parametrize("value", ["0", "false", "off", "garbage", ""])
def test_unrecognized_or_falsy_flag_values_stay_off(monkeypatch, value):
    monkeypatch.setenv(WB_FLAG, value)
    monkeypatch.setenv(SOCIAL_FLAG, value)
    monkeypatch.setenv(CALL_FLAG, value)
    assert isinstance(WriteBackBroker()._client, NullWriteBackClient)
    assert isinstance(SocialBroker()._client, NullSocialClient)
    assert isinstance(CallBroker()._client, NullCallClient)


async def test_flag_off_connector_execute_stays_deferred_and_names_the_secret():
    broker = WriteBackBroker()
    out = await broker.execute(_task("writeback.todoist.create_task", {
        "system": "todoist", "action": "create_task", "fields": {"content": "buy milk"},
        "credential_ref": SecretBroker.reference("todoist_token")}))
    assert out["status"] == "ok" and out["writeback"]["status"] == "deferred"
    assert is_degraded(out["writeback"])
    assert out["writeback"]["_degraded"]["needs"] == ["secret:todoist_token"]
    assert isinstance(broker._client, NullWriteBackClient)


# ── flag on → HTTP clients over an injected transport ────────────────────────

def test_flags_set_construct_http_clients(monkeypatch):
    monkeypatch.setenv(WB_FLAG, "1")
    monkeypatch.setenv(SOCIAL_FLAG, "yes")
    monkeypatch.setenv(CALL_FLAG, "true")
    assert isinstance(WriteBackBroker()._client, HttpWriteBackClient)
    assert isinstance(SocialBroker()._client, HttpSocialClient)
    assert isinstance(CallBroker()._client, HttpCallClient)
    assert WriteBackBroker().live and SocialBroker().live and CallBroker().live


def test_injected_client_wins_over_the_flag(monkeypatch):
    monkeypatch.setenv(WB_FLAG, "1")
    null = NullWriteBackClient()
    broker = WriteBackBroker(client=null)
    assert broker._client is null and broker.live is False


async def test_writeback_live_sends_h10_30_request_with_resolved_token(monkeypatch):
    monkeypatch.setenv(WB_FLAG, "1")
    http = _Transport()
    broker = WriteBackBroker(secret_broker=_secrets(github_token="ghp_live"), http=http)
    out = await broker.execute(_task("writeback.github.create_issue", {
        "system": "github", "action": "create_issue",
        "fields": {"repo": "a/b", "title": "t"},
        "credential_ref": SecretBroker.reference("github_token")}))
    assert out["status"] == "ok" and out["writeback"]["http_status"] == 201
    assert len(http.calls) == 1
    assert http.calls[0]["url"] == "https://api.github.com/repos/a/b/issues"
    assert http.calls[0]["headers"]["Authorization"] == "Bearer ghp_live"


async def test_writeback_live_refuses_without_credential(monkeypatch):
    monkeypatch.setenv(WB_FLAG, "1")
    http = _Transport()
    broker = WriteBackBroker(http=http)   # no SecretBroker → no token
    out = await broker.execute(_task("writeback.github.create_issue", {
        "system": "github", "action": "create_issue",
        "fields": {"repo": "a/b", "title": "t"},
        "credential_ref": SecretBroker.reference("github_token")}))
    assert out == {"status": "failed", "reason": "credential_not_configured",
                   "target": "github", "action": "create_issue",
                   "needs": ["secret:github_token"]}
    assert http.calls == []   # never an unauthenticated request


async def test_writeback_live_host_allowlist_blocks_escaped_url(monkeypatch):
    monkeypatch.setenv(WB_FLAG, "1")
    http = _Transport()

    def _bad_builder(target, action, fields, credentials):
        return {"method": "POST", "url": "https://evil.example.com/repos/a/b/issues",
                "headers": {}, "json": {}}

    monkeypatch.setattr(wb_mod, "build_request", _bad_builder)
    broker = WriteBackBroker(secret_broker=_secrets(github_token="ghp"), http=http)
    out = await broker.execute(_task("writeback.github.create_issue", {
        "system": "github", "action": "create_issue",
        "fields": {"repo": "a/b", "title": "t"},
        "credential_ref": SecretBroker.reference("github_token")}))
    assert out["status"] == "failed" and out["reason"] == "client_error"
    assert http.calls == []


def test_build_any_request_enforces_connector_allowlist(monkeypatch):
    with pytest.raises(ValueError):
        build_any_request("dropbox", "upload", {}, {})
    monkeypatch.setattr(wbc, "build_connector_request",
                        lambda *a, **k: {"method": "POST", "url": "https://attacker.tld/x",
                                         "headers": {}, "json": {}})
    with pytest.raises(ValueError, match="not allowed"):
        build_any_request("todoist", "create_task", {"content": "x"}, {"token": "t"})


# ── connector suite wired through the write-back broker ──────────────────────

def test_broker_supports_connector_catalog_and_lists_it_separately():
    assert WriteBackBroker.supports("todoist", "create_task")
    assert WriteBackBroker.supports("Linear", "Create_Issue")
    assert not WriteBackBroker.supports("dropbox", "upload")
    assert len(WriteBackBroker().targets()) == 5            # H10.30 surface unchanged
    kinds = {t["kind"] for t in WriteBackBroker().connector_targets()}
    assert kinds == {f"writeback.{t}.{a}" for (t, a) in wbc.CATALOG}
    trello = next(t for t in WriteBackBroker().connector_targets() if t["target"] == "trello")
    assert trello["credential"] == "trello_token"


def test_connector_request_enqueues_ask_tier_task_with_secret_handles():
    q = _FakeQueue()
    out = WriteBackBroker(enqueue=q.enqueue).request(
        "trello", "create_card", {"list_id": "L1", "name": "Card", "desc": "d",
                                  "token": "raw-token-should-be-dropped"})
    assert out["ok"] and out["queued"] and out["kind"] == "writeback.trello.create_card"
    call = q.calls[0]
    assert call["autonomy_level"] == "ask" and call["risk_tier"] == 2
    p = call["payload"]
    assert p["system"] == "trello" and p["fields"] == {"list_id": "L1", "name": "Card",
                                                       "desc": "d"}
    assert p["credential_ref"] == "{{secret:trello_token}}"
    assert p["credential_refs"] == {"token": "{{secret:trello_token}}",
                                    "api_key": "{{secret:trello_api_key}}"}
    assert "raw-token" not in repr(p)


def test_connector_request_refuses_unknown_and_missing():
    b = WriteBackBroker(enqueue=_FakeQueue().enqueue)
    unknown = b.request("todoist", "delete_everything", {})
    assert unknown["ok"] is False and unknown["reason"] == "unknown_target_action"
    assert "todoist.create_task" in unknown["supported"]
    missing = b.request("todoist", "create_task", {"due_string": "tomorrow"})
    assert missing == {"ok": False, "reason": "missing_fields", "missing": ["content"],
                       "required": ["content"]}


def test_draft_contract_admits_connector_payloads_and_rejects_bad_handles():
    good = {"kind": "writeback.todoist.create_task", "system": "todoist",
            "action": "create_task", "fields": {"content": "x"},
            "credential_ref": "{{secret:todoist_token}}"}
    assert WRITEBACK_DRAFT_CONTRACT.evaluate(good, now=0.0).admissible
    bad = dict(good, credential_ref="{{secret:github_token}}")
    d = WRITEBACK_DRAFT_CONTRACT.evaluate(bad, now=0.0)
    assert not d.admissible and d.reason == "credential_ref_mismatch"
    empty = dict(good, fields={})
    assert WRITEBACK_DRAFT_CONTRACT.evaluate(empty, now=0.0).reason == "missing_fields"


def test_connector_credentials_resolve_only_through_secret_broker():
    assert wbc.credential_names("trello") == {"token": "trello_token",
                                             "api_key": "trello_api_key"}
    assert wbc.credential_names("dropbox") == {}
    assert wbc.draft_task_payload("linear", "create_issue",
                                  {"team_id": "T", "title": "x"})["credential_ref"] \
        == SecretBroker.reference("linear_token")
    creds = wbc.resolve_credentials("trello", _secrets(trello_token="tok"))
    assert creds == {"token": "tok", "api_key": ""}      # missing slot → "", never fabricated
    assert wbc.resolve_credentials("trello", None) == {"token": "", "api_key": ""}


async def test_connector_execute_live_sends_trello_with_both_slots(monkeypatch):
    monkeypatch.setenv(WB_FLAG, "on")
    http = _Transport()
    broker = WriteBackBroker(secret_broker=_secrets(trello_token="tok", trello_api_key="key"),
                             http=http)
    out = await broker.execute(_task("writeback.trello.create_card", {
        "system": "trello", "action": "create_card",
        "fields": {"list_id": "L1", "name": "Card"},
        "credential_ref": "{{secret:trello_token}}"}))
    assert out["status"] == "ok" and out["writeback"]["response"] == {"id": "created-1"}
    req = http.calls[0]
    assert req["url"] == "https://api.trello.com/1/cards"
    assert req["params"] == {"idList": "L1", "key": "key", "token": "tok"}


# ── approved create_task → connector write (H12.25 closure) ──────────────────

def test_map_task_create_todoist_and_notion():
    assert {"create_task", "task.create"} == TASK_CREATE_KINDS
    todo = map_task_create({"system": "todoist", "text": "  buy milk ", "assignee": "Ana"})
    assert todo["ok"] and todo["payload"]["system"] == "todoist"
    assert todo["payload"]["action"] == "create_task"
    assert todo["payload"]["fields"] == {"content": "buy milk"}
    assert todo["payload"]["credential_ref"] == "{{secret:todoist_token}}"
    notion = map_task_create({"system": "notion", "text": "write docs", "assignee": "Ana",
                              "source": "standup"})
    assert notion["payload"]["action"] == "create_page"
    assert notion["payload"]["fields"] == {"title": "write docs",
                                           "content": "Assignee: Ana\nSource: standup"}
    assert notion["payload"]["credential_ref"] == "{{secret:notion_api_key}}"
    assert map_task_create({"system": "trello", "text": "x"})["reason"] == "unknown_task_system"
    assert map_task_create({"system": "todoist", "text": "  "})["reason"] == "missing_fields"


@pytest.mark.parametrize("kind", ["create_task", "task.create"])
async def test_execute_maps_approved_create_task_onto_todoist(monkeypatch, kind):
    monkeypatch.setenv(WB_FLAG, "1")
    http = _Transport()
    broker = WriteBackBroker(secret_broker=_secrets(todoist_token="td_tok"), http=http)
    out = await broker.execute(_task(kind, {
        "system": "todoist", "text": "ship it", "assignee": "", "source": "standup",
        "action": "create_task", "injection_flags": [], "untrusted_source": True}))
    assert out["status"] == "ok" and out["mapped_from"] == "create_task"
    assert out["target"] == "todoist" and out["action"] == "create_task"
    assert http.calls[0]["url"] == "https://api.todoist.com/rest/v2/tasks"
    assert http.calls[0]["json"] == {"content": "ship it"}
    assert http.calls[0]["headers"]["Authorization"] == "Bearer td_tok"


async def test_execute_create_task_unknown_system_fails_closed(monkeypatch):
    monkeypatch.setenv(WB_FLAG, "1")
    http = _Transport()
    out = await WriteBackBroker(http=http).execute(_task("create_task", {
        "system": "jira", "text": "x", "action": "create_task"}))
    assert out["status"] == "failed" and out["reason"] == "unknown_task_system"
    assert http.calls == []


async def test_unapproved_create_task_never_reaches_the_transport(monkeypatch, tmp_path):
    """End to end: transcript → queue (proposed) → worker tick sends NOTHING until approved."""
    from agents.core.autonomy.executor import TaskExecutor
    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.autonomy.queue import TaskQueue, TaskStatus
    from agents.core.autonomy.transcript_watcher import TranscriptWatcher
    from agents.core.autonomy.worker import AutonomyWorker

    monkeypatch.setenv(WB_FLAG, "1")
    http = _Transport()
    q = TaskQueue(db_path=str(tmp_path / "autonomy.db")).initialize()
    try:
        broker = WriteBackBroker(enqueue=q.enqueue,
                                 secret_broker=_secrets(todoist_token="td"), http=http)
        ingested = TranscriptWatcher(enqueue=q.enqueue, target="todoist").ingest(
            "- [ ] call the vendor\n", source="weekly")
        tid = ingested["items"][0]["task_id"]
        assert q.get(tid).status == "proposed" and q.get(tid).kind == "create_task"

        executor = TaskExecutor()
        executor.register("create_task", broker.execute)
        executor.register("task.create", broker.execute)
        worker = AutonomyWorker(q, policy=AutonomyPolicy(), executor=executor.execute)
        await worker.tick()
        assert http.calls == []                       # unapproved → nothing sent
        assert q.get(tid).status != "done"

        q.transition(tid, TaskStatus.APPROVED, decided_by="andrei", decision="accept")
        summary = await worker.tick()
        assert summary["done"] == 1 and q.get(tid).status == "done"
        assert len(http.calls) == 1
        assert http.calls[0]["json"] == {"content": "call the vendor"}
    finally:
        q.close()


# ── social rail ──────────────────────────────────────────────────────────────

async def test_social_live_posts_with_resolved_token(monkeypatch):
    monkeypatch.setenv(SOCIAL_FLAG, "1")
    http = _Transport()
    broker = SocialBroker(secret_broker=_secrets(x_api_token="xt"), http=http)
    out = await broker.execute(_task("social.x.post", {
        "platform": "x", "action": "post", "fields": {"text": "hello"},
        "credential_ref": SecretBroker.reference("x_api_token")}))
    assert out["status"] == "ok" and out["social"]["http_status"] == 201
    assert http.calls[0]["url"] == "https://api.twitter.com/2/tweets"
    assert http.calls[0]["headers"]["Authorization"] == "Bearer xt"


async def test_social_live_refuses_without_credential(monkeypatch):
    monkeypatch.setenv(SOCIAL_FLAG, "1")
    http = _Transport()
    out = await SocialBroker(http=http).execute(_task("social.x.post", {
        "platform": "x", "action": "post", "fields": {"text": "hello"},
        "credential_ref": SecretBroker.reference("x_api_token")}))
    assert out["status"] == "failed" and out["reason"] == "credential_not_configured"
    assert out["needs"] == ["secret:x_api_token"] and http.calls == []


async def test_social_live_host_allowlist(monkeypatch):
    monkeypatch.setenv(SOCIAL_FLAG, "1")
    http = _Transport()
    monkeypatch.setattr(social_mod, "build_social_request",
                        lambda *a, **k: {"method": "POST", "url": "https://evil.tld/2/tweets",
                                         "headers": {}, "json": {}})
    out = await SocialBroker(secret_broker=_secrets(x_api_token="xt"), http=http).execute(
        _task("social.x.post", {"platform": "x", "action": "post", "fields": {"text": "hi"},
                                "credential_ref": SecretBroker.reference("x_api_token")}))
    assert out["status"] == "failed" and out["reason"] == "client_error"
    assert http.calls == []


# ── call rail ────────────────────────────────────────────────────────────────

def _call_task(provider="twilio"):
    return _task("call.outbound", {
        "provider": provider, "action": "call", "to": "+40700000000",
        "message": "hi", "credential_ref": SecretBroker.reference(
            cb_mod._CREDENTIAL[provider])})


async def test_call_live_refuses_without_credential_or_config(monkeypatch):
    monkeypatch.setenv(CALL_FLAG, "1")
    http = _Transport()
    out = await CallBroker(http=http).execute(_call_task())
    assert out["status"] == "failed" and out["reason"] == "credential_not_configured"
    assert out["needs"] == ["secret:twilio_auth_token"]

    broker = CallBroker(secret_broker=_secrets(twilio_auth_token="tw"), http=http)
    out = await broker.execute(_call_task())
    assert out["status"] == "failed"
    assert out["reason"] == "call_config_missing:account_sid,from"
    assert out["needs"] == ["JARVIS_CALL_CONFIG.twilio.account_sid",
                            "JARVIS_CALL_CONFIG.twilio.from"]
    assert http.calls == []


async def test_call_live_dials_when_configured(monkeypatch):
    monkeypatch.setenv(CALL_FLAG, "1")
    http = _Transport()
    broker = CallBroker(secret_broker=_secrets(twilio_auth_token="tw"), http=http,
                        config={"twilio": {"account_sid": "AC1", "from": "+1555"}})
    out = await broker.execute(_call_task())
    assert out["status"] == "ok" and out["call"]["http_status"] == 201
    req = http.calls[0]
    assert req["url"] == "https://api.twilio.com/2010-04-01/Accounts/AC1/Calls.json"
    assert req["auth"] == ("AC1", "tw") and req["data"]["To"] == "+40700000000"
    assert cb_mod.missing_config("telnyx", {"from": "+1"}) == ["connection_id"]
