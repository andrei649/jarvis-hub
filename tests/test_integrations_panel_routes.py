"""The HUD Integrations panel: keys set in the HUD, never echoed, in effect without a restart.

Owner side: a key set through the route is stored encrypted, takes effect for the next
read (an adopted search backend's ``configured()``, an adopted model provider's
``auth_key``), is shown as "set" plus at most its last four characters, and can be
removed. A choice that needs acknowledgements goes through the same selection guards
and records the same audited consent. Attacker side: a user token is refused on every
route, a malformed body never echoes the key, ``.env`` keeps winning, and the secret
broker never lists or injects an integration key.
"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agents")]

from agents import web  # noqa: E402
from agents.core import integration_keys, integrations_catalog, settings_db  # noqa: E402

ADMIN = {"X-Admin-Token": "integrations-owner-only"}
USER_TOKEN = "integrations-user-only"
KEY = "exa-synthetic-key-0123456789-WXYZ"
MODEL_KEY = "ds-synthetic-key-abcdefghijk-7788"
BASE = "/api/admin/integrations"
MANAGED = ("EXA_API_KEY", "BRAVE_SEARCH_API_KEY", "PARALLEL_API_KEY", "TAVILY_API_KEY", "DEEPSEEK_API_KEY",
           "JARVIS_WEB_BACKEND", "NERVA_WEB_BACKEND", "GEMINI_API_KEY", "ANTHROPIC_API_KEY")


class FakeAudit:
    def __init__(self):
        self.rows = []

    def log(self, event):
        self.rows.append((event.action_taken, event.content_preview))


class FakeRouter:
    def __init__(self):
        self.detects = 0
        self.gemini_api_key = ""
        self.anthropic_api_key = ""

    async def detect(self):
        self.detects += 1


@pytest.fixture
def hub(tmp_path, monkeypatch):
    from agents.core.routers import admin, integrations_setup

    for name in MANAGED:
        monkeypatch.delenv(name, raising=False)
    integration_keys._PLACED.clear()
    integrations_catalog.LAST_TEST.clear()
    store = tmp_path / "security" / "secrets.enc"
    monkeypatch.setattr(integration_keys, "_store_path", lambda: store)
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    monkeypatch.setattr(web.app, "dependency_overrides", {})
    monkeypatch.setattr(web, "_admin_configured", lambda: True)
    monkeypatch.setattr(web, "_admin_credential_ok", lambda token: token == ADMIN["X-Admin-Token"])
    monkeypatch.setattr(web, "USER_TOKEN", USER_TOKEN)
    monkeypatch.setenv("JARVIS_USER_TOKEN", USER_TOKEN)
    orch = SimpleNamespace(audit=FakeAudit(), llm_router=FakeRouter(), plugins={})
    monkeypatch.setattr(integrations_setup, "get_orch", lambda: orch)
    monkeypatch.setattr(admin, "get_orch", lambda: orch)
    yield SimpleNamespace(client=TestClient(web.app), orch=orch, store=store)
    integration_keys.reset_for_tests()
    for name in MANAGED:
        os.environ.pop(name, None)


def _row(client, eid):
    rows = client.get(BASE, headers=ADMIN).json()["integrations"]
    return next(r for r in rows if r["id"] == eid)


def test_one_list_covers_search_models_and_the_skills_catalog(hub):
    body = hub.client.get(BASE, headers=ADMIN).json()
    rows = body["integrations"]
    ids = {r["id"] for r in rows}
    assert {"search.exa", "search.brave-free", "search.parallel", "search.tavily"} <= ids
    from agents.core.llm.hermes_provider_table import ADOPTED_MODEL_PROVIDER_IDS
    adopted = {r["name"] for r in rows if r["kind"] == "model" and r["origin"] == "hermes"}
    assert adopted == set(ADOPTED_MODEL_PROVIDER_IDS) and len(adopted) == 24
    assert {"model.anthropic", "model.gemini", "model.openrouter"} <= ids
    deepseek = next(r for r in rows if r["id"] == "model.deepseek")
    assert deepseek["status"] == "not_set_up"
    assert deepseek["facts"]["host"] == "api.deepseek.com"
    assert deepseek["facts"]["data_policy"] == "unknown"
    assert deepseek["facts"]["price_known"] == "no"
    assert next(r for r in rows if r["id"] == "model.kimi-coding-cn")["facts"]["host_country"] == "China (mainland)"
    assert body["skills"]["kind"] == "skills" and body["skills"]["where"] == "skills-import"
    assert body["precedence"] == "env"


def test_a_user_token_is_refused_on_every_route(hub):
    user = {"X-User-Token": USER_TOKEN}
    calls = [("get", BASE, None), ("put", f"{BASE}/search.exa/key", {"value": KEY}),
             ("delete", f"{BASE}/search.exa/key", None), ("post", f"{BASE}/search.exa/test", None),
             ("post", f"{BASE}/search.exa/use", {}), ("delete", f"{BASE}/search-choice", None)]
    for method, path, body in calls:
        kwargs = {"headers": user}
        if body is not None:
            kwargs["json"] = body
        response = hub.client.request(method.upper(), path, **kwargs)
        assert response.status_code in (401, 403), (method, path)
    assert "EXA_API_KEY" not in os.environ
    assert not hub.store.exists()


def test_set_key_takes_effect_now_is_never_echoed_and_is_removable(hub):
    from agents.core.plugins import web_providers

    exa = web_providers.get_search_provider("exa")
    assert exa is not None and not exa.configured(SimpleNamespace())
    saved = hub.client.put(f"{BASE}/search.exa/key", json={"value": KEY}, headers=ADMIN)
    assert saved.status_code == 200, saved.text
    assert KEY not in saved.text and KEY[:-4] not in saved.text
    state = saved.json()["integration"]["key"]
    assert state == {**state, "set": True, "source": "hub", "hint": "…WXYZ"}
    assert saved.json()["integration"]["status"] in ("key_set", "active")
    # The reader picks the key up on its next call: no restart.
    assert exa.configured(SimpleNamespace())
    assert KEY not in hub.client.get(BASE, headers=ADMIN).text
    # Encrypted at rest: the store holds no plaintext.
    assert hub.store.exists() and KEY not in hub.store.read_text(encoding="utf-8")
    assert any(action == "integration_key_set" and KEY not in preview for action, preview in hub.orch.audit.rows)
    removed = hub.client.delete(f"{BASE}/search.exa/key", headers=ADMIN)
    assert removed.status_code == 200 and removed.json()["integration"]["key"]["set"] is False
    assert "EXA_API_KEY" not in os.environ
    assert not exa.configured(SimpleNamespace())


def test_an_adopted_model_provider_reads_a_new_key_without_restart(hub):
    from agents.core.llm.providers import get_profile

    profile = get_profile("deepseek")
    assert profile.auth_key() == ""
    saved = hub.client.put(f"{BASE}/model.deepseek/key", json={"value": MODEL_KEY}, headers=ADMIN)
    assert saved.status_code == 200 and MODEL_KEY not in saved.text
    assert profile.auth_key() == MODEL_KEY
    assert saved.json()["integration"]["key"]["hint"] == "…7788"


def test_selected_provider_key_change_rebuilds_the_router(hub):
    settings_db.put_category("llm", {"compatible_provider": "deepseek", "compatible_model": "deepseek-v4-pro"})
    before = hub.orch.llm_router.detects
    assert hub.client.put(f"{BASE}/model.deepseek/key", json={"value": MODEL_KEY}, headers=ADMIN).json()[
        "applied"] == "now"
    assert hub.orch.llm_router.detects == before + 1
    hub.client.put(f"{BASE}/model.gemini/key", json={"value": "gemini-synthetic-key-123456"}, headers=ADMIN)
    assert hub.orch.llm_router.gemini_api_key == "gemini-synthetic-key-123456"


def test_a_malformed_request_never_echoes_the_key(hub):
    bad = hub.client.put(f"{BASE}/search.exa/key", json={"value": KEY, "extra": KEY}, headers=ADMIN)
    assert bad.status_code == 422 and KEY not in bad.text
    wrong_type = hub.client.put(f"{BASE}/search.exa/key", json={"value": 12345}, headers=ADMIN)
    assert wrong_type.status_code == 422
    unknown = hub.client.put(f"{BASE}/model.not-a-provider/key", json={"value": KEY}, headers=ADMIN)
    assert unknown.status_code == 404 and KEY not in unknown.text
    assert "EXA_API_KEY" not in os.environ


def test_env_wins_and_is_never_overwritten_or_removed(hub, monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "from-dotenv-0000000000")
    row = _row(hub.client, "search.exa")
    assert row["key"]["source"] == "env" and row["key"]["editable"] is False
    put = hub.client.put(f"{BASE}/search.exa/key", json={"value": KEY}, headers=ADMIN)
    assert put.status_code == 409 and put.json()["error"] == "env_managed"
    assert hub.client.delete(f"{BASE}/search.exa/key", headers=ADMIN).status_code == 409
    assert os.environ["EXA_API_KEY"] == "from-dotenv-0000000000"
    assert not hub.store.exists()


def test_stored_keys_are_applied_at_start_only_where_env_left_a_gap(hub, monkeypatch):
    integration_keys.set_key("EXA_API_KEY", KEY)
    integration_keys.set_key("PARALLEL_API_KEY", "parallel-synthetic-key-0001")
    # A restart: the process environment is fresh, .env sets PARALLEL_API_KEY itself.
    integration_keys._PLACED.clear()
    os.environ.pop("EXA_API_KEY")
    os.environ.pop("PARALLEL_API_KEY")
    monkeypatch.setenv("PARALLEL_API_KEY", "dotenv-parallel-key-9999")
    applied = integration_keys.apply_stored()
    assert applied == ["EXA_API_KEY"]
    assert os.environ["EXA_API_KEY"] == KEY
    assert os.environ["PARALLEL_API_KEY"] == "dotenv-parallel-key-9999"


def test_choosing_an_adopted_model_provider_collects_the_audited_consent(hub):
    hub.client.put(f"{BASE}/model.deepseek/key", json={"value": MODEL_KEY}, headers=ADMIN)
    refused = hub.client.post(f"{BASE}/model.deepseek/use", json={"model": "deepseek-v4-pro"}, headers=ADMIN)
    assert refused.status_code == 409
    body = refused.json()
    assert body["error"] == "selection_guard"
    assert set(body["needs"]) == {"acknowledge_training", "confirm_expensive"}
    assert settings_db.get_value("llm", "compatible_provider", "") != "deepseek"
    half = hub.client.post(f"{BASE}/model.deepseek/use", headers=ADMIN,
                           json={"model": "deepseek-v4-pro", "acknowledge_training": True})
    assert half.status_code == 409 and half.json()["needs"] == ["confirm_expensive"]
    before = hub.orch.llm_router.detects
    ok = hub.client.post(f"{BASE}/model.deepseek/use", headers=ADMIN, json={
        "model": "deepseek-v4-pro", "acknowledge_training": True, "confirm_expensive": True})
    assert ok.status_code == 200, ok.text
    assert settings_db.get_value("llm", "compatible_provider", "") == "deepseek"
    assert settings_db.get_value("llm", "compatible_model", "") == "deepseek-v4-pro"
    actions = [a for a, _ in hub.orch.audit.rows]
    assert "model_training_consent" in actions and "model_cost_confirmed" in actions
    assert hub.orch.llm_router.detects == before + 1
    assert ok.json()["integration"]["status"] == "active"


def test_a_consent_that_cannot_be_recorded_changes_nothing(hub):
    hub.orch.audit = None
    refused = hub.client.post(f"{BASE}/search.exa/use", headers=ADMIN,
                              json={"acknowledge_training": True, "confirm_expensive": True})
    assert refused.status_code == 503 and refused.json()["error"] == "consent_not_recorded"
    assert "JARVIS_WEB_BACKEND" not in os.environ


def test_choosing_an_adopted_search_backend_needs_the_same_acknowledgements(hub):
    from agents.core.plugins import web_providers

    refused = hub.client.post(f"{BASE}/search.exa/use", json={}, headers=ADMIN)
    assert refused.status_code == 409
    body = refused.json()
    assert body["error"] == "selection_guard"
    assert set(body["needs"]) == {"acknowledge_training", "confirm_expensive"}
    assert any("api.exa.ai" in g["message"] for g in body["guards"])
    assert web_providers.configured_backend() == "auto"
    ok = hub.client.post(f"{BASE}/search.exa/use", headers=ADMIN,
                         json={"acknowledge_training": True, "confirm_expensive": True})
    assert ok.status_code == 200
    assert web_providers.configured_backend() == "exa"
    assert any(a == "search_backend_consent" for a, _ in hub.orch.audit.rows)
    assert _row(hub.client, "search.exa")["selected"] is True
    back = hub.client.delete(f"{BASE}/search-choice", headers=ADMIN)
    assert back.status_code == 200 and web_providers.configured_backend() == "auto"


def test_search_choice_set_in_env_is_not_overwritten(hub, monkeypatch):
    monkeypatch.setenv("NERVA_WEB_BACKEND", "tavily")
    response = hub.client.post(f"{BASE}/search.tavily/use", json={}, headers=ADMIN)
    assert response.status_code == 409 and response.json()["error"] == "env_managed"


def test_model_test_probes_only_that_provider(hub, monkeypatch):
    from agents.core.llm import provider_probe

    seen = []

    async def probe(provider_id, **kwargs):
        seen.append((provider_id, kwargs))
        return {"provider": provider_id, "verdict": "auth_failed", "working": False, "status_code": 401}

    async def probe_all(**_kwargs):
        raise AssertionError("probe_all must not run for one provider's test")

    monkeypatch.setattr(provider_probe, "probe", probe)
    monkeypatch.setattr(provider_probe, "probe_all", probe_all)
    response = hub.client.post(f"{BASE}/model.deepseek/test", headers=ADMIN)
    assert response.status_code == 200
    test = response.json()["test"]
    assert seen == [("deepseek", {"force": True})]
    assert test["ok"] is False and "rejected the key" in test["message"]
    hub.client.put(f"{BASE}/model.deepseek/key", json={"value": MODEL_KEY}, headers=ADMIN)
    response = hub.client.post(f"{BASE}/model.deepseek/test", headers=ADMIN)
    assert response.json()["integration"]["status"] == "error"


def test_search_test_runs_that_backend_through_the_egress_client(hub, monkeypatch):
    from agents.core.plugins.websearch import WebSearchPlugin

    asked = []

    async def ask(self, provider, query, max_results):
        asked.append((provider.name, self._egress(provider.plugin_id) is self._client, max_results))
        return [{"title": "t", "url": "https://example.org", "snippet": ""}]

    monkeypatch.setattr(WebSearchPlugin, "_ask", ask)
    not_set = hub.client.post(f"{BASE}/search.exa/test", headers=ADMIN).json()["test"]
    assert not_set["verdict"] == "not_configured" and asked == []
    hub.client.put(f"{BASE}/search.exa/key", json={"value": KEY}, headers=ADMIN)
    result = hub.client.post(f"{BASE}/search.exa/test", headers=ADMIN)
    assert result.status_code == 200 and KEY not in result.text
    assert result.json()["test"]["ok"] is True
    assert asked == [("exa", True, 1)]


def test_the_secret_broker_never_lists_or_injects_an_integration_key(tmp_path):
    from agents.core.secrets import SecretStore
    from agents.core.security.secret_broker import SecretBroker

    store = SecretStore(path=tmp_path / "secrets.enc")
    store.set(integration_keys.KEY_PREFIX + "EXA_API_KEY", KEY)
    broker = SecretBroker(store)
    assert broker.names() == []
    out = broker.inject("{{secret:integration.key.EXA_API_KEY}}", approved=True)
    assert KEY not in out["text"]
    assert broker.delete(integration_keys.KEY_PREFIX + "EXA_API_KEY") is False
    assert KEY not in broker.redact(f"leaked {KEY} here")
