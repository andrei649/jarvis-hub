"""Tests for H10.25 — Human Review Queue."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.observability.review_queue import ReviewQueue, RUBRIC_CRITERIA

TRACE = {"id": "t1", "text_preview": "a dubious answer", "quality": {"score": 0.3}}


# ── flagging ─────────────────────────────────────────────────────────────────

def test_flag_and_idempotent(tmp_path):
    q = ReviewQueue(path=tmp_path / "r.json")
    a = q.flag(TRACE, reason="manual")
    assert a["status"] == "pending" and a["trace_id"] == "t1"
    b = q.flag(TRACE)                                # same trace_id → no dup
    assert b["id"] == a["id"]
    assert len(q.list()) == 1


def test_auto_flag_threshold(tmp_path):
    q = ReviewQueue(path=tmp_path / "r.json")
    assert q.auto_flag(TRACE, score=0.9, threshold=0.6) is None   # above → skip
    item = q.auto_flag(TRACE, score=0.3, threshold=0.6)
    assert item is not None and "auto" in item["reason"]


# ── review ───────────────────────────────────────────────────────────────────

def test_review_records_verdict_and_rubric(tmp_path):
    q = ReviewQueue(path=tmp_path / "r.json")
    item = q.flag(TRACE)
    reviewed = q.review(item["id"], "down",
                        rubric={"accuracy": 0, "tone": 1, "bogus": 5}, notes="wrong facts")
    assert reviewed["status"] == "reviewed" and reviewed["verdict"] == "down"
    assert reviewed["rubric"] == {"accuracy": 0, "tone": 1}        # unknown criterion dropped
    assert reviewed["notes"] == "wrong facts"


def test_review_bad_verdict_and_missing(tmp_path):
    q = ReviewQueue(path=tmp_path / "r.json")
    item = q.flag(TRACE)
    with pytest.raises(ValueError):
        q.review(item["id"], "maybe")
    assert q.review("nope", "up") is None


def test_to_eval_case_and_stats(tmp_path):
    q = ReviewQueue(path=tmp_path / "r.json")
    item = q.flag(TRACE)
    q.review(item["id"], "up")
    case = q.to_eval_case(q.get(item["id"]))
    assert case["source"] == "human_review" and case["verdict"] == "up"
    q.mark_in_dataset(item["id"])
    s = q.stats()
    assert s["reviewed"] == 1 and s["thumbs_up"] == 1 and s["in_dataset"] == 1
    assert s["rubric_criteria"] == RUBRIC_CRITERIA


def test_list_filters_by_status(tmp_path):
    q = ReviewQueue(path=tmp_path / "r.json")
    i1 = q.flag({"id": "x", "text_preview": "p"})
    q.flag({"id": "y", "text_preview": "p"})
    q.review(i1["id"], "up")
    assert len(q.list("pending")) == 1 and len(q.list("reviewed")) == 1


# ── endpoints ────────────────────────────────────────────────────────────────

def test_review_endpoints():
    from agents import web
    with TestClient(web.app) as c:
        if getattr(web.orch, "review_queue", None) is None:
            return
        web.orch.review_queue.clear()
        assert c.post("/api/review/flag", json={}).status_code == 400
        flagged = c.post("/api/review/flag", json={"trace": TRACE, "reason": "manual"})
        assert flagged.status_code == 200
        item_id = flagged.json()["item"]["id"]
        assert len(c.get("/api/review/queue?status=pending").json()["items"]) == 1
        # bad verdict
        assert c.post(f"/api/review/{item_id}/vote", json={"verdict": "x"}).status_code == 400
        voted = c.post(f"/api/review/{item_id}/vote",
                       json={"verdict": "down", "rubric": {"accuracy": 0}})
        assert voted.status_code == 200 and voted.json()["item"]["verdict"] == "down"
        # promote to dataset
        ds = c.post(f"/api/review/{item_id}/dataset", json={"dataset": "review_test"})
        assert ds.status_code == 200 and ds.json()["case"]["source"] == "human_review"
        assert c.get("/api/review/stats").json()["stats"]["thumbs_down"] == 1
