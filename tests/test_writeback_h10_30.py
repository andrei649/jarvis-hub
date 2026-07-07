"""H10.30 — Governed write-back integrations (Notion/GitHub/Calendar).

Verifies the governance layer end-to-end, all offline:
  request → validated/sanitized → enqueued ask-tier task → (approval) → executor
  resolves credentials behind approval → injectable client (no real network).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import pytest

from agents.core.automation_contracts import ContractDecision
from agents.core.writeback import (
    WriteBackBroker, NullWriteBackClient, HttpWriteBackClient, build_request, _CATALOG,
)
from agents.core.security.secret_broker import SecretBroker


class _FakeQueue:
    """Captures enqueue calls without a real DB."""

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


# ── catalog ──────────────────────────────────────────────────────────────────

def test_targets_lists_catalog():
    t = WriteBackBroker().targets()
    assert len(t) == len(_CATALOG) == 5
    kinds = {x["kind"] for x in t}
    assert "writeback.github.create_issue" in kinds
    assert "writeback.notion.create_page" in kinds
    assert "writeback.google_calendar.create_event" in kinds
    gh = next(x for x in t if x["kind"] == "writeback.github.create_issue")
    assert gh["required"] == ["repo", "title"] and "labels" in gh["optional"]
    assert gh["credential"] == "github_token"


def test_supports():
    assert WriteBackBroker.supports("github", "create_issue")
    assert WriteBackBroker.supports("GitHub", "Create_Issue")  # case-insensitive
    assert not WriteBackBroker.supports("github", "delete_repo")
    assert not WriteBackBroker.supports("dropbox", "upload")


# ── request validation ───────────────────────────────────────────────────────

def test_request_unknown_target_action():
    out = WriteBackBroker().request("dropbox", "upload", {"x": 1})
    assert out["ok"] is False and out["reason"] == "unknown_target_action"
    assert "github.create_issue" in out["supported"]


def test_request_missing_required_fields():
    out = WriteBackBroker().request("github", "create_issue", {"repo": "a/b"})
    assert out["ok"] is False and out["reason"] == "missing_fields"
    assert out["missing"] == ["title"]


def test_request_preview_mode_when_no_queue():
    out = WriteBackBroker().request(
        "github", "create_issue", {"repo": "a/b", "title": "Bug"})
    assert out["ok"] is True and out["queued"] is False
    prev = out["preview"]
    assert prev["would_execute"] is False
    assert prev["requires_approval"] is True  # external tier always asks


def test_request_enqueues_governed_task():
    q = _FakeQueue()
    broker = WriteBackBroker(enqueue=q.enqueue)
    out = broker.request("github", "create_issue",
                         {"repo": "andrei/jarvis-hub", "title": "Track flaky test",
                          "body": "details", "labels": ["bug"]},
                         agent="hephaestus")
    assert out["ok"] is True and out["queued"] is True and out["task_id"] == 1
    call = q.calls[0]
    assert call["agent"] == "hephaestus"
    assert call["kind"] == "writeback.github.create_issue"
    assert call["autonomy_level"] == "ask"      # governed: never auto-runs
    assert call["risk_tier"] == 2               # external
    assert call["origin"] == "generated"
    p = call["payload"]
    assert p["system"] == "github" and p["action"] == "create_issue"
    assert p["credential_ref"] == "{{secret:github_token}}"  # handle, never a value
    assert p["fields"]["repo"] == "andrei/jarvis-hub"
    assert p["fields"]["labels"] == ["bug"]


def test_request_obeys_live_writeback_draft_contract(monkeypatch):
    import agents.core.writeback as writeback

    class _FakeWriteBackDraftContract:
        def __init__(self):
            self.calls = []

        def evaluate(self, payload=None, **kwargs):
            payload = payload or {}
            self.calls.append((payload, kwargs))
            return ContractDecision(
                kind="writeback_draft",
                admissible=False,
                requires_approval=True,
                reason="contract_denied",
                checked=("fake",),
            )

    q = _FakeQueue()
    contract = _FakeWriteBackDraftContract()
    monkeypatch.setattr(writeback, "WRITEBACK_DRAFT_CONTRACT", contract, raising=False)

    out = writeback.WriteBackBroker(enqueue=q.enqueue).request(
        "github",
        "create_issue",
        {"repo": "andrei/jarvis-hub", "title": "Hold for contract"},
        agent="hephaestus",
        source="night-shift",
    )

    assert out == {
        "ok": False,
        "reason": "contract_denied",
        "kind": "writeback.github.create_issue",
    }
    assert q.calls == []
    assert len(contract.calls) == 1
    payload, kwargs = contract.calls[0]
    assert payload["kind"] == "writeback.github.create_issue"
    assert payload["system"] == "github"
    assert payload["action"] == "create_issue"
    assert payload["agent"] == "hephaestus"
    assert payload["source"] == "night-shift"
    assert payload["fields"]["repo"] == "andrei/jarvis-hub"
    assert payload["fields"]["title"] == "Hold for contract"
    assert "now" in kwargs


def test_request_sanitizes_fields():
    q = _FakeQueue()
    broker = WriteBackBroker(enqueue=q.enqueue)
    broker.request("github", "create_issue",
                   {"repo": "a/b", "title": "x" * 5000, "evil": "drop me",
                    "labels": "single", "assignees": ["u1", "", "u2"]})
    p = q.calls[0]["payload"]["fields"]
    assert "evil" not in p                       # unknown key dropped
    assert len(p["title"]) == 2000               # capped
    assert p["labels"] == ["single"]             # str coerced to list
    assert p["assignees"] == ["u1", "u2"]        # blanks dropped


# ── build_request (pure HTTP mapping) ─────────────────────────────────────────

def test_build_request_github_create_issue():
    spec = build_request("github", "create_issue",
                         {"repo": "a/b", "title": "t", "body": "x", "labels": ["bug"]},
                         {"token": "ghp_x"})
    assert spec["method"] == "POST"
    assert spec["url"] == "https://api.github.com/repos/a/b/issues"
    assert spec["headers"]["Authorization"] == "Bearer ghp_x"
    assert spec["json"] == {"title": "t", "body": "x", "labels": ["bug"]}


def test_build_request_github_comment():
    spec = build_request("github", "comment_issue",
                         {"repo": "a/b", "issue": "42", "body": "hi"}, {"token": "t"})
    assert spec["url"] == "https://api.github.com/repos/a/b/issues/42/comments"
    assert spec["json"] == {"body": "hi"}


def test_build_request_notion_create_page():
    spec = build_request("notion", "create_page",
                         {"title": "Notes", "parent": "pg1", "content": "body"},
                         {"token": "ntn"})
    assert spec["url"] == "https://api.notion.com/v1/pages"
    assert spec["headers"]["Notion-Version"] == "2022-06-28"
    assert spec["json"]["parent"] == {"page_id": "pg1"}
    assert spec["json"]["properties"]["title"][0]["text"]["content"] == "Notes"
    assert "children" in spec["json"]


def test_build_request_notion_append_block():
    spec = build_request("notion", "append_block",
                         {"page_id": "pg9", "text": "more"}, {"token": "ntn"})
    assert spec["method"] == "PATCH"
    assert spec["url"] == "https://api.notion.com/v1/blocks/pg9/children"


def test_build_request_calendar_event():
    spec = build_request("google_calendar", "create_event",
                         {"summary": "Sync", "start": "2026-06-10T09:00:00Z",
                          "end": "2026-06-10T09:30:00Z", "attendees": ["a@x.com"]},
                         {"token": "ya29"})
    assert spec["url"].endswith("/calendars/primary/events")
    assert spec["json"]["start"]["dateTime"] == "2026-06-10T09:00:00Z"
    assert spec["json"]["attendees"] == [{"email": "a@x.com"}]


def test_build_request_unsupported_raises():
    with pytest.raises(ValueError):
        build_request("github", "delete_repo", {}, {})


# ── execute (deferred, behind approval) ───────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_null_client_no_network():
    null = NullWriteBackClient()
    broker = WriteBackBroker(client=null)
    task = _Task("writeback.github.create_issue",
                 {"system": "github", "action": "create_issue",
                  "fields": {"repo": "a/b", "title": "t"},
                  "credential_ref": "{{secret:github_token}}"})
    out = await broker.execute(task)
    assert out["status"] == "ok"
    assert out["writeback"]["status"] == "deferred"
    assert null.calls[0]["target"] == "github"
    assert null.calls[0]["has_credential"] is False   # no secret broker wired


@pytest.mark.asyncio
async def test_execute_resolves_credentials_behind_approval():
    sb = SecretBroker()
    sb.put("github_token", "ghp_secret")

    class _Rec:
        last = None
        async def write(self, target, action, fields, credentials):
            _Rec.last = {"target": target, "credentials": credentials}
            return {"status": "ok"}

    broker = WriteBackBroker(secret_broker=sb, client=_Rec())
    task = _Task("writeback.github.create_issue",
                 {"system": "github", "action": "create_issue",
                  "fields": {"repo": "a/b", "title": "t"},
                  "credential_ref": "{{secret:github_token}}"})
    out = await broker.execute(task)
    assert out["status"] == "ok"
    # The raw token is injected only at action time, only into the client call.
    assert _Rec.last["credentials"]["token"] == "ghp_secret"


@pytest.mark.asyncio
async def test_execute_rejects_unknown_payload():
    broker = WriteBackBroker(client=NullWriteBackClient())
    task = _Task("writeback.dropbox.upload",
                 {"system": "dropbox", "action": "upload", "fields": {}})
    out = await broker.execute(task)
    assert out["status"] == "failed" and out["reason"] == "unknown_target_action"


@pytest.mark.asyncio
async def test_http_client_sends_built_request():
    class _Resp:
        status_code = 201
        def raise_for_status(self): pass
        def json(self): return {"id": 7}

    class _Http:
        def __init__(self): self.calls = []
        async def request(self, method, url, headers=None, json=None):
            self.calls.append({"method": method, "url": url,
                               "headers": headers, "json": json})
            return _Resp()

    http = _Http()
    out = await HttpWriteBackClient(http=http).write(
        "github", "create_issue", {"repo": "a/b", "title": "t"}, {"token": "ghp"})
    assert out["status"] == "ok" and out["http_status"] == 201 and out["response"] == {"id": 7}
    assert http.calls[0]["url"].endswith("/repos/a/b/issues")
    assert http.calls[0]["headers"]["Authorization"] == "Bearer ghp"


# ── end-to-end through the real queue + worker ────────────────────────────────

@pytest.mark.asyncio
async def test_end_to_end_governed_execution(tmp_path):
    from agents.core.autonomy.queue import TaskQueue, TaskStatus
    from agents.core.autonomy.worker import AutonomyWorker
    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.autonomy.executor import TaskExecutor

    q = TaskQueue(db_path=str(tmp_path / "autonomy.db")).initialize()
    try:
        sb = SecretBroker()
        sb.put("github_token", "ghp_e2e")
        null = NullWriteBackClient()
        broker = WriteBackBroker(enqueue=q.enqueue, secret_broker=sb, client=null)

        # 1. Agent requests a write-back → governed task, held as `proposed`.
        out = broker.request("github", "create_issue",
                             {"repo": "a/b", "title": "Ship it", "body": "go"})
        tid = out["task_id"]
        assert q.get(tid).status == "proposed"   # NOT executed yet
        assert null.calls == []

        # 2. Human approves → APPROVED.
        q.transition(tid, TaskStatus.APPROVED, decided_by="andrei", decision="accept")

        # 3. Worker tick dispatches it to the writeback executor.
        executor = TaskExecutor()
        executor.register("writeback", broker.execute)
        worker = AutonomyWorker(q, policy=AutonomyPolicy(), executor=executor.execute)
        summary = await worker.tick()

        assert summary["done"] == 1
        assert q.get(tid).status == "done"
        # The client was called exactly once, with the credential resolved.
        assert len(null.calls) == 1
        assert null.calls[0]["target"] == "github"
        assert null.calls[0]["has_credential"] is True
    finally:
        q.close()
