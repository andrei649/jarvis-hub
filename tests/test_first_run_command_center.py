"""0.19 First-Run Command Center (Lane B2, handoff 2026-07-07).

One read (`GET /api/onboarding/command-center`, user-guarded) unifying the three
things a fresh install needs on a single screen: install health (the /readyz
checks + version), model status (backend / active model / cloud configured),
and honest FIRST ACTIONS — each carrying a real `ready` flag derived from live
state (a chat action is not "ready" without a model; the docs action is not
"ready" without configured folders). Honesty contract: nothing is presented as
available unless its prerequisite actually holds; `reason` says why not.

Offline: TestClient without lifespan (orch=None → the cold-start shape) plus a
monkeypatched fake orch for the warm shape. Guarding is pinned by the
route-auth matrix snapshot, not re-asserted here (same note as the wizard suite).
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from agents.core import analytics_store  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_analytics():
    analytics_store.initialize(":memory:")
    yield
    analytics_store.close()


@pytest.fixture
def client():
    from agents import web
    from agents.core.routers._deps import user_guard
    web.app.dependency_overrides[user_guard] = lambda: None
    try:
        yield TestClient(web.app)
    finally:
        web.app.dependency_overrides.pop(user_guard, None)


class _FakeRouter:
    name = "lmstudio"
    active_model = "test-local-model"
    _local_available = True
    _claude_backend = None
    _gemini_backend = None


class _FakeOrch:
    def __init__(self, folders=None):
        self.agents = {"jarvis": object()}
        self.channels = {"web": object()}
        self.llm_router = _FakeRouter()
        self._folders = folders or {}
        self._runtime_settings = {}

    def get_setting(self, key, default=None):
        if key == "local_docs.folders":
            return self._folders
        return default


def _get(client):
    resp = client.get("/api/onboarding/command-center")
    assert resp.status_code == 200
    return resp.json()


def test_cold_start_shape_is_honest(client):
    """No orchestrator (pre-boot): install not ready, model unknown, actions held."""
    body = _get(client)
    assert body["install"]["ready"] is False
    assert "version" in body["install"]
    assert body["model"]["backend"] == "none"
    assert body["model"]["ready"] in (None, False)
    # wizard state rides along so the screen is one fetch
    assert [s["key"] for s in body["wizard"]["steps"]][0] == "intro"
    actions = {a["key"]: a for a in body["first_actions"]}
    assert set(actions) == {"say_hello", "morning_brief", "index_docs"}
    for a in actions.values():
        assert a["ready"] is False          # nothing is pretended ready cold
        assert a.get("reason")              # and each says why


def test_warm_install_reports_model_and_ready_actions(client, monkeypatch):
    from agents import web
    monkeypatch.setattr(web, "orch", _FakeOrch(), raising=False)
    body = _get(client)
    assert body["install"]["ready"] is True
    assert body["install"]["checks"]["agents_loaded"] == 1
    assert body["model"]["backend"] == "lmstudio"
    assert body["model"]["active_model"] == "test-local-model"
    assert body["model"]["ready"] is True
    actions = {a["key"]: a for a in body["first_actions"]}
    assert actions["say_hello"]["ready"] is True
    assert actions["say_hello"]["kind"] == "chat"
    assert actions["morning_brief"]["ready"] is True
    # docs stay honestly not-ready until the owner configures a folder
    assert actions["index_docs"]["ready"] is False
    assert "folder" in actions["index_docs"]["reason"].lower()


def test_docs_action_becomes_ready_with_configured_folder(client, monkeypatch):
    from agents import web
    monkeypatch.setattr(web, "orch", _FakeOrch(folders={"notes": "/tmp/notes"}),
                        raising=False)
    body = _get(client)
    actions = {a["key"]: a for a in body["first_actions"]}
    assert actions["index_docs"]["ready"] is True
    assert actions["index_docs"]["folders"] == ["notes"]


def test_wizard_completion_rides_along(client, monkeypatch):
    from agents import web
    monkeypatch.setattr(web, "orch", _FakeOrch(), raising=False)
    client.post("/api/onboarding/funnel", json={"step": "intro"})
    body = _get(client)
    assert "intro" in body["wizard"]["completed"]
    assert body["wizard"]["complete"] is False
