"""The user roster describes web chat routing without exposing router internals."""

from types import SimpleNamespace

from fastapi.testclient import TestClient


def _roster(monkeypatch, policies, *, router=True, runtime=None):
    from agents import web

    agents = {
        aid: SimpleNamespace(name=aid.title(), has_heartbeat=False, config={}, soul={})
        for aid in policies
    }

    def policy(aid):
        value = policies[aid]
        if isinstance(value, Exception):
            raise value
        return value

    hub = SimpleNamespace(agents=agents)
    if router:
        hub.llm_router = runtime or SimpleNamespace(get_agent_policy=policy)
    monkeypatch.setattr(web, "orch", hub)
    monkeypatch.setattr(web, "_AGENT_SETTINGS", {})
    monkeypatch.setattr(web, "_user_credential_required", lambda: False)
    response = TestClient(web.app, base_url="http://localhost").get("/api/agents")
    assert response.status_code == 200, response.text
    return response.json()["agents"]


def test_chat_routing_projects_live_policy_and_cloud_only_floor(monkeypatch):
    from agents.core.llm import hybrid_router

    # Exercise the canonical policy reader without constructing or probing a backend.
    monkeypatch.setattr(hybrid_router, "_registry_policies", lambda: {
        "athena": "local", "gecko": "cloud", "frigga": "cloud", "vision": "claude",
    })
    rows = _roster(monkeypatch, {
        "jarvis": "auto",
        "athena": "cloud",
        "gecko": "cloud",  # Custom policy: cloud preference, not cloud-only.
        "vision": "claude",
        "frigga": "local",
        "friday": "auto",
    }, runtime=hybrid_router.HybridRouter.__new__(hybrid_router.HybridRouter))
    assert {row["id"]: row["chat_routing"] for row in rows} == {
        "jarvis": "orchestrated",
        "athena": "cloud_only",
        "gecko": "cloud_preferred",
        "vision": "claude_preferred",
        "frigga": "local",
        "friday": "auto",
    }
    assert all(set(row) == {
        "id", "name", "tier", "role", "status", "enabled", "has_heartbeat", "model", "chat_routing"
    } for row in rows)


def test_chat_routing_unknown_policy_or_read_error_keeps_entire_roster(monkeypatch):
    rows = _roster(monkeypatch, {
        "jarvis": "auto",
        "mystery": "secret-provider-and-token",
        "broken": RuntimeError("private backend detail"),
    })
    assert {row["id"]: row["chat_routing"] for row in rows} == {
        "jarvis": "orchestrated", "mystery": None, "broken": None,
    }
    assert "secret-provider" not in str(rows)


def test_chat_routing_missing_legacy_router_is_null(monkeypatch):
    rows = _roster(monkeypatch, {"jarvis": "auto", "friday": "auto"}, router=False)
    assert {row["id"]: row["chat_routing"] for row in rows} == {
        "jarvis": None, "friday": None,
    }
