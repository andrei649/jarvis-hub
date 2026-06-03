"""Tests for H10.23 — Live Quality Monitor."""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.observability.quality import (
    evaluate_heuristics, score_trace, QualityMonitor,
)

GOOD = {"id": "t1", "text_preview": "Here is a helpful answer.", "ok": True,
        "timings": {"total_ms": 1200}}
BAD = {"id": "t2", "text_preview": "[error: boom]", "ok": False,
       "timings": {"total_ms": 30000}}


# ── heuristics / scoring ─────────────────────────────────────────────────────

def test_heuristics_good_vs_bad():
    g = evaluate_heuristics(GOOD)
    assert g["ok"] == 1.0 and g["non_empty"] == 1.0 and g["no_error"] == 1.0 and g["latency"] == 1.0
    b = evaluate_heuristics(BAD)
    assert b["ok"] == 0.0 and b["no_error"] == 0.0 and b["latency"] < 1.0


def test_score_trace_range():
    assert score_trace(GOOD)["score"] == 1.0
    assert score_trace(BAD)["score"] < 0.5


def test_score_blends_judge():
    r = score_trace(GOOD, judge=lambda t: 0.0)     # heuristic 1.0 blended with judge 0.0
    assert r["judge"] == 0.0 and r["score"] == 0.5


def test_score_tolerates_bad_judge():
    r = score_trace(GOOD, judge=lambda t: 1 / 0)   # raises → judge ignored
    assert r["judge"] is None and r["score"] == 1.0


# ── monitor: rolling avg + alert ─────────────────────────────────────────────

def test_monitor_rolling_avg_and_alert():
    m = QualityMonitor(window=10, threshold=0.6)
    assert m.check_alert()["alerting"] is False     # empty → no alert
    m.record(GOOD); m.record(GOOD)
    assert m.rolling_avg() == 1.0
    assert m.check_alert()["alerting"] is False
    for _ in range(5):
        m.record(BAD)
    alert = m.check_alert()
    assert alert["avg_score"] < 0.6 and alert["alerting"] is True


def test_monitor_window_caps():
    m = QualityMonitor(window=3)
    for i in range(5):
        m.record({"id": str(i), "text_preview": "ok", "ok": True, "timings": {"total_ms": 100}})
    assert m.stats()["n"] == 3
    assert len(m.recent(100)) == 3


def test_set_threshold_clamped():
    m = QualityMonitor()
    m.set_threshold(2.0)
    assert m.threshold == 1.0


# ── endpoints ────────────────────────────────────────────────────────────────

def test_quality_endpoints():
    from agents import web
    old = web.ADMIN_TOKEN
    web.ADMIN_TOKEN = "test-secret"
    try:
        with TestClient(web.app) as c:
            assert c.get("/api/quality").status_code == 200
            assert "stats" in c.get("/api/quality").json()
            assert c.get("/api/quality/scores").status_code == 200
            # threshold set requires admin
            assert c.post("/api/quality/threshold", json={"threshold": 0.7}).status_code == 401
            ok = c.post("/api/quality/threshold", json={"threshold": 0.7},
                        headers={"X-Admin-Token": "test-secret"})
            if getattr(web.orch, "quality", None) is not None:
                assert ok.status_code == 200 and ok.json()["threshold"] == 0.7
    finally:
        web.ADMIN_TOKEN = old
