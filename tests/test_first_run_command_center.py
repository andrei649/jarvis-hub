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


@pytest.fixture(autouse=True)
def _inventory_truth(monkeypatch):
    from agents.core.routers import onboarding

    async def inventory(*, router=None, controller=None, force_refresh=False):
        if router is None:
            return {
                "configured_model": None,
                "resident_models": [],
                "residency_state": "offline",
                "providers": [],
                "models": [],
            }
        return {
            "backend": "lm-studio",
            "configured_model": "test-local-model",
            "resident_models": [{"provider": "lm-studio", "id": "test-local-model"}],
            "residency_state": "known",
            "providers": [],
            "models": [],
        }

    monkeypatch.setattr(onboarding, "get_local_model_inventory", inventory, raising=False)


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
    def __init__(
        self,
        *,
        route="local",
        model="test-local-model",
        backend_name="lm-studio",
        route_error=False,
    ):
        self.name = backend_name
        self.active_model = model
        self._local_model = model
        self._backend_name = backend_name
        self._local_available = route.startswith("local")
        self._backend = object() if self._local_available else None
        self._claude_backend = None
        self._gemini_backend = object() if route.startswith("cloud") else None
        self._route = route
        self._route_error = route_error

    def select_backend(self, agent_id, prompt):
        assert agent_id == "jarvis"
        assert prompt
        if self._route_error:
            raise RuntimeError("no route")
        if self._route.startswith("cloud"):
            return self._gemini_backend, self.active_model, self._route
        return self._backend, self.active_model, self._route


class _FakeOrch:
    def __init__(self, folders=None, router=None):
        self.agents = {"jarvis": object()}
        self.channels = {"web": object()}
        self.llm_router = router or _FakeRouter()
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
        assert a["ready"] is False  # nothing is pretended ready cold
        assert a.get("reason")  # and each says why


def test_warm_install_reports_model_and_ready_actions(client, monkeypatch):
    from agents import web

    monkeypatch.setattr(web, "orch", _FakeOrch(), raising=False)
    body = _get(client)
    assert body["install"]["ready"] is True
    assert body["install"]["checks"]["agents_loaded"] == 1
    assert body["model"]["backend"] == "lm-studio"
    assert body["model"]["active_provider"] == "lm-studio"
    assert body["model"]["route"] == "local"
    assert body["model"]["active_model"] == "test-local-model"
    assert body["model"]["configured_model"] == "test-local-model"
    assert body["model"]["resident_models"] == [{"provider": "lm-studio", "id": "test-local-model"}]
    assert body["model"]["ready"] is True
    actions = {a["key"]: a for a in body["first_actions"]}
    assert actions["say_hello"]["ready"] is True
    assert actions["say_hello"]["kind"] == "chat"
    assert actions["morning_brief"]["ready"] is True
    # docs stay honestly not-ready until the owner configures a folder
    assert actions["index_docs"]["ready"] is False
    assert "folder" in actions["index_docs"]["reason"].lower()


def test_command_center_requires_the_selected_route_to_be_runnable(client, monkeypatch):
    from agents import web
    from agents.core.routers import onboarding

    monkeypatch.setattr(web, "orch", _FakeOrch(), raising=False)

    async def ollama_resident(**kwargs):
        return {
            "backend": "lm-studio",
            "configured_model": "text-embedding-nomic-embed-text-v1.5",
            "resident_models": [{"provider": "ollama", "id": "qwen3.5:0.8b"}],
            "residency_state": "known",
            "providers": [
                {"name": "lm-studio", "online": True, "residency_state": "known"},
                {"name": "ollama", "online": True, "residency_state": "known"},
            ],
            "models": [],
        }

    monkeypatch.setattr(onboarding, "get_local_model_inventory", ollama_resident)
    body = _get(client)
    assert body["model"]["active_model"] is None
    assert body["model"]["configured_model"] == "text-embedding-nomic-embed-text-v1.5"
    assert body["model"]["ready"] is False
    assert next(a for a in body["first_actions"] if a["key"] == "say_hello")["ready"] is False

    async def selected_lm_studio_resident(**kwargs):
        snapshot = await ollama_resident(**kwargs)
        snapshot["resident_models"] = [
            {"provider": "lm-studio", "id": "test-local-model"},
            {"provider": "ollama", "id": "qwen3.5:0.8b"},
        ]
        snapshot["configured_model"] = "test-local-model"
        return snapshot

    monkeypatch.setattr(onboarding, "get_local_model_inventory", selected_lm_studio_resident)
    runnable = _get(client)
    assert runnable["model"]["active_model"] == "test-local-model"
    assert runnable["model"]["active_provider"] == "lm-studio"
    assert runnable["model"]["ready"] is True

    async def configured_only(**kwargs):
        return {
            "backend": "lm-studio",
            "configured_model": "minimax/minimax-m2.7",
            "resident_models": [],
            "residency_state": "known",
            "providers": [{"name": "lm-studio", "online": True, "residency_state": "known"}],
            "models": [],
        }

    monkeypatch.setattr(onboarding, "get_local_model_inventory", configured_only)
    held = _get(client)
    assert held["model"]["active_model"] is None
    assert held["model"]["configured_model"] == "minimax/minimax-m2.7"
    assert held["model"]["ready"] is False
    hello = next(a for a in held["first_actions"] if a["key"] == "say_hello")
    assert hello["ready"] is False
    assert "model" in hello["reason"]

    async def residency_unknown(**kwargs):
        snapshot = await configured_only(**kwargs)
        snapshot["residency_state"] = "unknown"
        snapshot["providers"][0]["residency_state"] = "unknown"
        return snapshot

    monkeypatch.setattr(onboarding, "get_local_model_inventory", residency_unknown)
    unknown = _get(client)
    assert unknown["model"]["active_model"] is None
    assert unknown["model"]["ready"] is None
    assert unknown["model"]["residency_state"] == "unknown"
    assert next(a for a in unknown["first_actions"] if a["key"] == "say_hello")["ready"] is False

    cloud_router = _FakeRouter(route="cloud-flash", model="gemini-2.5-flash", backend_name="none")
    monkeypatch.setattr(web, "orch", _FakeOrch(router=cloud_router), raising=False)
    cloud = _get(client)
    assert cloud["model"]["backend"] == "gemini"
    assert cloud["model"]["active_provider"] == "gemini"
    assert cloud["model"]["active_model"] == "gemini-2.5-flash"
    assert cloud["model"]["route"] == "cloud-flash"
    assert cloud["model"]["ready"] is True

    claude_only = _FakeRouter(model="claude-sonnet", backend_name="none", route_error=True)
    claude_only._claude_backend = object()
    monkeypatch.setattr(web, "orch", _FakeOrch(router=claude_only), raising=False)
    no_jarvis_route = _get(client)
    assert no_jarvis_route["model"]["active_model"] is None
    assert no_jarvis_route["model"]["active_provider"] is None
    assert no_jarvis_route["model"]["ready"] is False

    unsafe_route = _FakeRouter(route="not-cloud", model="gemini-pretender", backend_name="none")
    unsafe_route._gemini_backend = object()
    monkeypatch.setattr(web, "orch", _FakeOrch(router=unsafe_route), raising=False)
    rejected_route = _get(client)
    assert rejected_route["model"]["active_model"] is None
    assert rejected_route["model"]["active_provider"] is None
    assert rejected_route["model"]["ready"] is False

    sentinel_model = _FakeRouter(route="cloud", model="none", backend_name="none")
    monkeypatch.setattr(web, "orch", _FakeOrch(router=sentinel_model), raising=False)
    rejected_sentinel = _get(client)
    assert rejected_sentinel["model"]["active_model"] is None
    assert rejected_sentinel["model"]["active_provider"] is None
    assert rejected_sentinel["model"]["ready"] is False


def test_docs_action_becomes_ready_with_configured_folder(client, monkeypatch):
    from agents import web

    monkeypatch.setattr(web, "orch", _FakeOrch(folders={"notes": "/tmp/notes"}), raising=False)
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
