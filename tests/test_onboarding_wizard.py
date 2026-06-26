"""H23.20 — first-run onboarding wizard + activation funnel.

The wizard derives completion from recorded funnel events (no extra store), so onboarding
resumes across reloads. Funnel events are first-party + local (analytics_store).
"""

import pytest
from fastapi.testclient import TestClient

from agents.core import analytics_store


@pytest.fixture(autouse=True)
def _isolated_analytics():
    analytics_store.initialize(":memory:")   # in-process store shared with the route handlers
    yield
    analytics_store.close()


@pytest.fixture
def client():
    from agents import web
    from agents.core.routers._deps import user_guard
    web.app.dependency_overrides[user_guard] = lambda: None   # localhost-onboarding stand-in
    try:
        yield TestClient(web.app)
    finally:
        web.app.dependency_overrides.pop(user_guard, None)


def test_wizard_starts_incomplete(client):
    body = client.get("/api/onboarding/wizard").json()
    assert [s["key"] for s in body["steps"]] == ["intro", "model", "test_chat", "autonomy"]
    assert body["completed"] == []
    assert body["complete"] is False
    assert "model_ready" in body          # bool or None (best-effort)


def test_funnel_event_marks_step_complete(client):
    assert client.post("/api/onboarding/funnel", json={"step": "intro"}).json()["recorded"] == "funnel.intro.complete"
    body = client.get("/api/onboarding/wizard").json()
    assert "intro" in body["completed"]
    assert body["complete"] is False      # other steps still pending


def test_all_steps_complete(client):
    for step in ("intro", "model", "test_chat", "autonomy"):
        client.post("/api/onboarding/funnel", json={"step": step})
    body = client.get("/api/onboarding/wizard").json()
    assert set(body["completed"]) == {"intro", "model", "test_chat", "autonomy"}
    assert body["complete"] is True


def test_unknown_step_rejected(client):
    resp = client.post("/api/onboarding/funnel", json={"step": "definitely_not_a_step"})
    assert resp.status_code == 400
    assert "steps" in resp.json()
    # NB: the funnel/wizard routes carry user_guard; that they're guarded is pinned by the
    # route-auth matrix snapshot (env-independent), not asserted at runtime here.
