"""H12.25: meeting transcript → action items → governed approval queue.

Extraction is high-precision (checkboxes, explicit prefixes, "<Name> will/to …"
assignments) and every item lands as an ask-tier autonomy task — nothing is
created in Notion/Todoist without approval.
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.autonomy.transcript_watcher import extract_action_items, TranscriptWatcher  # noqa: E402
import agents.web as web  # noqa: E402


# ── extraction ────────────────────────────────────────────────────

def test_extracts_checkbox_and_prefix_lines():
    items = extract_action_items(
        "Notes from sync\n"
        "- [ ] Ship the pairing PR\n"
        "Action item: write the changelog\n"
        "TODO: book the room\n"
        "next step - update the roadmap\n"
        "Just some discussion that is not a task.\n"
    )
    texts = [i["text"] for i in items]
    assert "Ship the pairing PR" in texts
    assert "write the changelog" in texts
    assert "book the room" in texts
    assert "update the roadmap" in texts
    assert all("discussion" not in t for t in texts)   # no false positives


def test_extracts_assignee():
    items = extract_action_items("Alice will send the report\n@Bob to review the design\n")
    by_who = {i["assignee"]: i["text"] for i in items}
    assert by_who["Alice"] == "send the report"
    assert by_who["Bob"] == "review the design"


def test_prefix_plus_assignee_combined():
    items = extract_action_items("Action item: Carol to deploy the build")
    assert items == [{"text": "deploy the build", "assignee": "Carol"}]


def test_dedup_and_min_length():
    items = extract_action_items("TODO: ship it\nTODO: ship it\n- [ ] ok\n- [ ] x\n")
    texts = [i["text"] for i in items]
    assert texts.count("ship it") == 1
    assert "x" not in texts            # under min length, dropped


def test_ignores_plain_prose():
    assert extract_action_items("We talked about the weather and then went home.") == []


# ── watcher: governed enqueue ─────────────────────────────────────

class _FakeQueue:
    def __init__(self):
        self.calls = []

    def enqueue(self, agent, kind, title, payload=None, risk_tier=3,
                autonomy_level="ask", origin="generated"):
        self.calls.append(dict(agent=agent, kind=kind, title=title, payload=payload,
                               risk_tier=risk_tier, autonomy_level=autonomy_level, origin=origin))
        return len(self.calls)


def test_ingest_enqueues_each_as_ask_tier_task():
    q = _FakeQueue()
    w = TranscriptWatcher(enqueue=q.enqueue, target="notion")
    out = w.ingest("- [ ] do X\nAction item: do Y\n", source="standup")
    assert out["count"] == 2 and out["target"] == "notion"
    assert [c["kind"] for c in q.calls] == ["create_task", "create_task"]
    # governance: every queued item is ask-tier and carries the target system
    assert all(c["autonomy_level"] == "ask" for c in q.calls)
    assert all(c["payload"]["system"] == "notion" for c in q.calls)
    assert out["items"][0]["queued"] is True and "task_id" in out["items"][0]


def test_ingest_without_queue_is_preview_only():
    w = TranscriptWatcher(enqueue=None)
    out = w.ingest("TODO: ship it")
    assert out["count"] == 1 and out["items"][0]["queued"] is False


def test_invalid_target_falls_back_to_todoist():
    q = _FakeQueue()
    out = TranscriptWatcher(enqueue=q.enqueue).ingest("TODO: a thing", target="trello")
    assert out["target"] == "todoist"


# ── endpoint ──────────────────────────────────────────────────────

def _client(monkeypatch, tmp_path):
    from core.autonomy.queue import TaskQueue
    q = TaskQueue(str(tmp_path / "q.db")).initialize()
    monkeypatch.setattr(web, "orch", type("O", (), {"autonomy_queue": q})())
    monkeypatch.setattr(web, "USER_TOKEN", "usr")
    return TestClient(web.app), {"X-User-Token": "usr"}, q


def test_endpoint_ingests_into_queue(monkeypatch, tmp_path):
    client, hdr, q = _client(monkeypatch, tmp_path)
    body = {"transcript": "- [ ] ship it\nAction item: write docs\n", "source": "weekly"}
    r = client.post("/api/transcripts/ingest", json=body, headers=hdr)
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 2 and all(i["queued"] for i in data["items"])
    # the tasks really landed in the queue as ask-tier
    assert len(q.list(status="proposed")) == 2


def test_endpoint_preview_without_queue(monkeypatch):
    monkeypatch.setattr(web, "orch", None)
    monkeypatch.setattr(web, "USER_TOKEN", "usr")
    client = TestClient(web.app)
    r = client.post("/api/transcripts/ingest", json={"transcript": "TODO: ship it"},
                    headers={"X-User-Token": "usr"})
    assert r.status_code == 200 and r.json()["items"][0]["queued"] is False
