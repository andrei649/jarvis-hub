"""H23.21 — design-partner feedback + NPS (store + endpoints).

First-party, local. NPS = %promoters(9-10) − %detractors(0-6) over scored nps rows.
"""

import pytest
from fastapi.testclient import TestClient

from agents.core import feedback_store


@pytest.fixture(autouse=True)
def _isolated_store():
    feedback_store.initialize(":memory:")
    yield
    feedback_store.close()


# ── store ─────────────────────────────────────────────────────────────────────
def test_record_and_summary_nps():
    for s in (10, 9, 7, 3):   # 2 promoters, 1 passive, 1 detractor → NPS = (2-1)/4 = 25
        feedback_store.record("nps", score=s)
    feedback_store.record("bug", message="it broke")
    summ = feedback_store.summary()
    assert summ["responses"] == 4
    assert summ["promoters"] == 2 and summ["detractors"] == 1
    assert summ["nps"] == 25
    assert summ["by_kind"]["bug"] == 1
    assert summ["recent"][0]["kind"] == "bug"   # newest-first


def test_nps_is_none_until_a_response():
    feedback_store.record("comment", message="hi")
    assert feedback_store.summary()["nps"] is None


def test_inputs_are_bounded():
    fid = feedback_store.record("weird-kind", score=99, message="x" * 9000)
    assert isinstance(fid, int)
    row = feedback_store.summary()["recent"][0]
    assert row["kind"] == "comment"          # unknown kind degrades
    assert len(row["message"]) <= 4000       # truncated


# ── endpoints ───────────────────────────────────────────────────────────────────
@pytest.fixture
def client():
    from agents import web
    from agents.core.routers._deps import admin_guard, user_guard
    web.app.dependency_overrides[user_guard] = lambda: None
    web.app.dependency_overrides[admin_guard] = lambda: None
    try:
        yield TestClient(web.app)
    finally:
        web.app.dependency_overrides.pop(user_guard, None)
        web.app.dependency_overrides.pop(admin_guard, None)


def test_submit_and_summary_endpoints(client):
    r = client.post("/api/feedback", json={"kind": "nps", "score": 10})
    assert r.status_code == 200 and r.json()["ok"] is True
    client.post("/api/feedback", json={"kind": "comment", "message": "love it"})
    summ = client.get("/api/feedback/summary").json()
    assert summ["nps"] == 100                # one promoter, no detractors
    assert summ["by_kind"].get("comment") == 1
    assert "no-store" in client.get("/api/feedback/summary").headers.get("cache-control", "")
