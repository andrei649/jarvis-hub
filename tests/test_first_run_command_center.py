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
def _cloud_keys_accepted(monkeypatch):
    """H380: a selected cloud route asks its provider; here every provider accepts."""
    from agents.core.routers import onboarding

    async def accepted(llm_router, provider):
        return {"provider": provider, "verdict": "ok", "status_code": 200, "checked_at": 0.0, "cached": False}

    monkeypatch.setattr(onboarding, "_cloud_probe", accepted)


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
    def __init__(self, folders=None, router=None, plugins=None):
        self.agents = {"jarvis": object()}
        self.channels = {"web": object()}
        self.llm_router = router or _FakeRouter()
        self.plugins = plugins or {}
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
    assert {o["status"] for o in body["starter_outcomes"]} == {"needs_setup"}


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
    outcomes = {o["key"]: o for o in body["starter_outcomes"]}
    assert set(outcomes) == {
        "plan_my_day",
        "private_documents",
        "research_web",
    }
    assert outcomes["private_documents"]["status"] == "needs_setup"
    assert outcomes["private_documents"]["privacy"] == "local_only"
    assert outcomes["plan_my_day"]["changes"] == "none"


def test_starter_outcomes_use_live_plugin_honesty_not_manifest_presence(client, monkeypatch):
    from agents import web
    from agents.core.plugins.gmail_plugin import GmailPlugin
    from agents.core.plugins.google_calendar import GoogleCalendarPlugin
    from agents.core.plugins.websearch import WebSearchPlugin

    plugins = {
        "gmail": GmailPlugin(access_token="test-token"),
        "google-calendar": GoogleCalendarPlugin(access_token="test-token"),
        "websearch": WebSearchPlugin(tavily_api_key="test-token"),
    }
    monkeypatch.setattr(
        web,
        "orch",
        _FakeOrch(folders={"notes": "/tmp/notes"}, plugins=plugins),
        raising=False,
    )
    body = _get(client)
    outcomes = {o["key"]: o for o in body["starter_outcomes"]}
    assert {o["status"] for o in outcomes.values()} == {"live"}
    assert outcomes["plan_my_day"]["privacy"] == "third_party_account"
    assert outcomes["private_documents"]["privacy"] == "local_only"
    assert all(o["setup"] is None for o in outcomes.values())

    web.orch.plugins["gmail"] = GmailPlugin()
    held = _get(client)
    plan = next(o for o in held["starter_outcomes"] if o["key"] == "plan_my_day")
    assert plan["status"] == "needs_setup"
    assert plan["setup"] == "Connect Google in Settings."


def test_starter_outcomes_qualify_private_documents_on_cloud_route(client, monkeypatch):
    from agents import web

    cloud_router = _FakeRouter(route="cloud-flash", model="gemini-2.5-flash", backend_name="none")
    monkeypatch.setattr(
        web,
        "orch",
        _FakeOrch(folders={"notes": "/tmp/notes"}, router=cloud_router),
        raising=False,
    )
    body = _get(client)
    docs = next(o for o in body["starter_outcomes"] if o["key"] == "private_documents")
    assert docs["status"] == "live"
    assert docs["privacy"] == "local_storage_cloud_model"
    assert docs["changes"] == "none"


def test_starter_outcomes_qualify_connected_data_on_cloud_route(client, monkeypatch):
    from agents import web
    from agents.core.plugins.gmail_plugin import GmailPlugin
    from agents.core.plugins.google_calendar import GoogleCalendarPlugin

    cloud_router = _FakeRouter(route="cloud-flash", model="gemini-2.5-flash", backend_name="none")
    plugins = {
        "gmail": GmailPlugin(access_token="test-token"),
        "google-calendar": GoogleCalendarPlugin(access_token="test-token"),
    }
    monkeypatch.setattr(
        web,
        "orch",
        _FakeOrch(router=cloud_router, plugins=plugins),
        raising=False,
    )

    body = _get(client)
    plan = next(o for o in body["starter_outcomes"] if o["key"] == "plan_my_day")
    assert plan["status"] == "live"
    assert plan["privacy"] == "third_party_account_cloud_model"


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


def test_model_block_names_why_the_route_is_or_is_not_runnable(client, monkeypatch):
    """H242 (Hermes ``setup.runtime_check``): the strict verdict carries a named reason
    and the route's own provider/model, so a terminal check (``nerva doctor``'s
    ``runtime_resolves``, ``nerva status``'s ``runnable:``) can say *why* without
    re-deriving it. ``active_*`` stay None when not ready; ``selected_*`` name what the
    route asked for either way."""
    from agents import web
    from agents.core.routers import onboarding

    cold = _get(client)["model"]
    assert (cold["ready"], cold["reason"]) == (None, "router_unavailable")
    assert cold["selected_provider"] is None and cold["selected_model"] is None

    monkeypatch.setattr(web, "orch", _FakeOrch(), raising=False)
    warm = _get(client)["model"]
    assert (warm["ready"], warm["reason"]) == (True, "resident")
    assert (warm["selected_provider"], warm["selected_model"]) == ("lm-studio", "test-local-model")

    async def other_provider_resident(**kwargs):
        return {
            "backend": "lm-studio",
            "configured_model": "test-local-model",
            "resident_models": [{"provider": "ollama", "id": "test-other-model"}],
            "residency_state": "known",
            "providers": [
                {"name": "lm-studio", "online": True, "residency_state": "known"},
                {"name": "ollama", "online": True, "residency_state": "known"},
            ],
            "models": [],
        }

    monkeypatch.setattr(onboarding, "get_local_model_inventory", other_provider_resident)
    stuck = _get(client)["model"]
    assert (stuck["ready"], stuck["reason"]) == (False, "configured_not_resident")
    assert (stuck["selected_provider"], stuck["selected_model"]) == ("lm-studio", "test-local-model")
    assert stuck["active_provider"] is None and stuck["active_model"] is None

    async def provider_offline(**kwargs):
        snapshot = await other_provider_resident(**kwargs)
        snapshot["providers"][0] = {"name": "lm-studio", "online": False, "residency_state": "offline"}
        return snapshot

    monkeypatch.setattr(onboarding, "get_local_model_inventory", provider_offline)
    offline = _get(client)["model"]
    assert (offline["ready"], offline["reason"]) == (False, "provider_offline")

    async def residency_unknown(**kwargs):
        snapshot = await other_provider_resident(**kwargs)
        snapshot["providers"][0]["residency_state"] = "unknown"
        return snapshot

    monkeypatch.setattr(onboarding, "get_local_model_inventory", residency_unknown)
    unknown = _get(client)["model"]
    assert (unknown["ready"], unknown["reason"]) == (None, "residency_unknown")

    async def inventory_down(**kwargs):
        raise RuntimeError("probe failed")

    monkeypatch.setattr(onboarding, "get_local_model_inventory", inventory_down)
    unverified = _get(client)["model"]
    assert (unverified["ready"], unverified["reason"]) == (None, "inventory_unavailable")

    cloud_router = _FakeRouter(route="cloud-flash", model="test-cloud-model", backend_name="none")
    monkeypatch.setattr(web, "orch", _FakeOrch(router=cloud_router), raising=False)
    cloud = _get(client)["model"]
    assert (cloud["ready"], cloud["reason"]) == (True, "cloud_selected")
    assert (cloud["selected_provider"], cloud["selected_model"]) == ("gemini", "test-cloud-model")

    claude_only = _FakeRouter(model="test-cloud-model", backend_name="none", route_error=True)
    claude_only._claude_backend = object()
    monkeypatch.setattr(web, "orch", _FakeOrch(router=claude_only), raising=False)
    no_route = _get(client)["model"]
    assert (no_route["ready"], no_route["reason"]) == (False, "route_unselected")
    assert no_route["selected_model"] is None

    unsafe_route = _FakeRouter(route="not-cloud", model="test-pretender-model", backend_name="none")
    unsafe_route._gemini_backend = object()
    monkeypatch.setattr(web, "orch", _FakeOrch(router=unsafe_route), raising=False)
    mismatch = _get(client)["model"]
    assert (mismatch["ready"], mismatch["reason"]) == (False, "provider_unresolved")
    assert mismatch["selected_provider"] is None
    assert mismatch["selected_model"] == "test-pretender-model"

    # H380: a cloud route whose provider does not accept the key is not runnable.
    monkeypatch.setattr(web, "orch", _FakeOrch(router=cloud_router), raising=False)
    refused = []
    for verdict in ("auth_failed", "forbidden", "rate_limited", "error", "unreachable", "refused",
                    "not_configured"):
        async def said(llm_router, provider, verdict=verdict):
            return {"provider": "gemini", "verdict": verdict, "status_code": None,
                    "checked_at": 1.0, "cached": True, "models": 3}

        monkeypatch.setattr(onboarding, "_cloud_probe", said)
        block = _get(client)["model"]
        assert (block["ready"], block["reason"]) == (False, f"cloud_{verdict}")
        assert block["active_provider"] is None and block["selected_provider"] == "gemini"
        assert block["cloud_probe"] == {"provider": "gemini", "verdict": verdict, "status_code": None,
                                        "checked_at": 1.0, "cached": True}
        refused.append(block)
    for verdict in ("ok", "no_listing"):
        async def fine(llm_router, provider, verdict=verdict):
            return {"provider": "gemini", "verdict": verdict}

        monkeypatch.setattr(onboarding, "_cloud_probe", fine)
        assert (_get(client)["model"]["ready"], _get(client)["model"]["reason"]) == (True, "cloud_selected")

    async def no_profile(llm_router, provider):
        return None

    monkeypatch.setattr(onboarding, "_cloud_probe", no_profile)
    assert _get(client)["model"]["reason"] == "cloud_selected" and _get(client)["model"]["cloud_probe"] is None

    # Every reason the hub can name is exercised above — a new one needs a case here.
    verdicts = (cold, warm, stuck, offline, unknown, unverified, cloud, no_route, mismatch, *refused)
    assert {v["reason"] for v in verdicts} == onboarding.MODEL_READINESS_REASONS

    # The compatible-adapter route is trusted only when the router handed back the very
    # backend that route names — any other object is still an indirect fallback.
    impostor = _FakeRouter(route="cloud-compatible", model="test-cloud-model", backend_name="none")
    impostor._compatible_backend = object()
    monkeypatch.setattr(web, "orch", _FakeOrch(router=impostor), raising=False)
    not_it = _get(client)["model"]
    assert (not_it["ready"], not_it["reason"]) == (False, "provider_unresolved")
    assert not_it["selected_provider"] is None


def _real_router(monkeypatch, case):
    """A real ``HybridRouter`` in the state ``detect()`` leaves for each configuration a
    Jarvis turn can meet — no detection, no network, no generation. The strict verdict is
    only "the same resolution a chat uses" if it is pinned against this router, not a
    fake that speaks a smaller route vocabulary."""
    from agents.core.llm import hybrid_router
    from agents.core.llm.openrouter import OpenRouterBackend
    from agents.core.llm.providers import DEFAULT_REGISTRY

    router = hybrid_router.HybridRouter()
    local = case in {"local", "compatible-always"}
    router._local_available = local
    router._backend = object() if local else None
    router._backend_name = "lm-studio"
    router._local_model = "test-local-model"
    if case == "cloud-flash":
        router._gemini_backend = object()
        router._gemini_model = "test-cloud-model"
        router._cloud_available = True
    if case == "claude":
        # the owner's registry puts Jarvis on the Claude policy (agents.yaml llm_policy)
        monkeypatch.setattr(hybrid_router, "_registry_policies", lambda: {"jarvis": "claude"})
        router._claude_backend = object()
        router._claude_model = "test-cloud-model"
        router._claude_available = True
    if case.startswith("compatible"):
        # llm.compatible_provider=openrouter with its key set: what detect() builds
        router._compatible_backend = OpenRouterBackend(
            api_key="test-key", client=object(), profile=DEFAULT_REGISTRY.get("openrouter"))
        router._compatible_model = "test-cloud-model"
        router._cloud_available = True
        if case == "compatible-always":
            router.set_cloud_fallback_mode("always")
    return router


@pytest.mark.parametrize("case, route, provider, model, reason", [
    ("local", "local", "lm-studio", "test-local-model", "resident"),
    ("cloud-flash", "cloud-flash", "gemini", "test-cloud-model", "cloud_selected"),
    ("claude", "claude", "claude", "test-cloud-model", "cloud_selected"),
    # llm.cloud_fallback=always with a local runtime up: every cloud* route is rewritten
    ("compatible-always", "cloud-compatible", "openrouter", "test-cloud-model", "cloud_selected"),
    # on-demand with no local runtime: the spill goes to the compatible adapter too
    ("compatible-on-demand", "cloud-compatible", "openrouter", "test-cloud-model",
     "cloud_selected"),
])
def test_the_strict_verdict_runs_the_real_router_for_every_route_a_chat_can_take(
        client, monkeypatch, case, route, provider, model, reason):
    from agents import web

    router = _real_router(monkeypatch, case)
    backend, chat_model, chat_route = router.select_backend(
        "jarvis", "Hello Jarvis — first-run check.")
    assert (chat_route, chat_model) == (route, model)  # what a Jarvis turn runs on

    monkeypatch.setattr(web, "orch", _FakeOrch(router=router), raising=False)
    block = _get(client)["model"]
    assert (block["route"], block["ready"], block["reason"]) == (route, True, reason)
    assert (block["selected_provider"], block["selected_model"]) == (provider, model)
    assert (block["active_provider"], block["active_model"]) == (provider, model)
    assert block["cloud_configured"] is (case != "local")


class _AppResponse:
    """What urllib's opener returns, backed by the in-process app (context manager too,
    because agents/cli/client.py reads it with ``with``)."""

    def __init__(self, resp):
        self.status = resp.status_code
        self._body = resp.content

    def read(self):
        return self._body

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _app_opener(client, seen, canned=None):
    """A urlopen stand-in that forwards to the in-process app. ``canned`` answers other
    paths (``/status`` needs a full orchestrator, which this suite does not build)."""
    import json
    from types import SimpleNamespace
    from urllib.parse import urlsplit

    def open_(request, timeout=None):
        path = urlsplit(request.full_url).path
        seen.append((request.get_method(), path))
        assert request.get_method() == "GET" and request.data is None  # a read, nothing else
        if canned and path in canned:
            fake = SimpleNamespace(status_code=200, content=json.dumps(canned[path]).encode())
            return _AppResponse(fake)
        return _AppResponse(client.get(path, headers=dict(request.header_items())))

    return open_


def test_doctor_and_status_read_the_hubs_own_verdict_end_to_end(client, monkeypatch):
    """The terminal checks consume this route's real reply, not a hand-built payload:
    `nerva doctor` (runtime_resolves) and `nerva status` (runnable:) both report the
    verdict `_model_snapshot` reached, with its named reason."""
    import io

    from agents import web
    from agents.cli.client import HubClient
    from agents.cli.nerva import Context, main
    from agents.core.routers import onboarding
    from scripts import doctor

    monkeypatch.setattr(web, "orch", _FakeOrch(), raising=False)

    async def ollama_holds_another_model(**kwargs):
        return {
            "backend": "lm-studio",
            "configured_model": "test-local-model",
            "resident_models": [{"provider": "ollama", "id": "test-other-model"}],
            "residency_state": "known",
            "providers": [
                {"name": "lm-studio", "online": True, "residency_state": "known"},
                {"name": "ollama", "online": True, "residency_state": "known"},
            ],
            "models": [],
        }

    monkeypatch.setattr(onboarding, "get_local_model_inventory", ollama_holds_another_model)
    seen = []
    ready_hub = doctor.Check("readyz", doctor.OK, "ready")
    check = doctor.check_runtime_resolves(_app_opener(client, seen), readyz=ready_hub, env={})
    assert (check.status, check.reason) == (doctor.WARN, "configured_not_resident")
    assert check.detail == (
        "route=local provider=lm-studio model=test-local-model resident=ollama/test-other-model"
    )
    assert seen == [("GET", "/api/onboarding/command-center")]

    canned = {
        "/status": {"version": "1.0.0", "llm_backend": "lm-studio", "model_state": "ready",
                    "loaded_model": "test-other-model", "agents_total": 1, "channels": []},
        "/api/ops/estop": {"engaged": False, "state": None},
    }
    seen.clear()
    hub = HubClient(opener=_app_opener(client, seen, canned))
    out = io.StringIO()
    ctx = Context(environ={}, out=out, err=io.StringIO(), client_factory=lambda env: hub)
    assert main(["status"], context=ctx) == 0
    assert ("GET", "/api/onboarding/command-center") in seen
    text = out.getvalue()
    assert "test-other-model (resident)" in text
    assert "runnable:    no — configured_not_resident: route local → lm-studio/test-local-model" in text

    monkeypatch.setattr(onboarding, "get_local_model_inventory", _inventory_truth_resident)
    ok = doctor.check_runtime_resolves(_app_opener(client, seen), readyz=ready_hub, env={})
    assert (ok.status, ok.reason) == (doctor.OK, "resolves:lm-studio/test-local-model")


async def _inventory_truth_resident(**kwargs):
    return {
        "backend": "lm-studio",
        "configured_model": "test-local-model",
        "resident_models": [{"provider": "lm-studio", "id": "test-local-model"}],
        "residency_state": "known",
        "providers": [{"name": "lm-studio", "online": True, "residency_state": "known"}],
        "models": [],
    }


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
