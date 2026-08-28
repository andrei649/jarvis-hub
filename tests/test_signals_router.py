"""T-0.41 — the live sidecar signal feed wired through the routing layer.

`agents/core/signal_routing.py` (classify → per-domain → per-agent) was a pure,
fully-tested module with **no caller**: nothing fetched live signals and ran them
through it. This is the wiring — the Signal Layer plugin's live `signals()` feed
routed into per-domain and per-agent slices, plus the per-domain brief.

Honesty contract under test: with no sidecar configured the surface reports
`available: false` and empty slices — it never fabricates signals, and an
unclassifiable signal stays visible in `unrouted` rather than being force-labeled.
"""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

# Import via the `agents.` path — the SAME module object `agents/web.py` mounts.
# `core.routers.signals` resolves to a *distinct* module object (both paths are on
# sys.path), so patching that one would leave the mounted app untouched and the
# HTTP round-trip below would silently test the unpatched code.
from agents.core.routers import signals as signals_router  # noqa: E402

_SIGNALS = [
    {"title": "Missile strike near border", "summary": "artillery exchange", "severity": 4},
    {"title": "Ransomware breach at bank", "summary": "malware deployed", "severity": 5},
    {"title": "Something entirely unclassifiable", "summary": "no keywords here", "severity": 1},
]


def _orch(plugin=None):
    return SimpleNamespace(plugins={"signal-layer": plugin} if plugin else {})


def _live_plugin(payload=None):
    async def signals(**kwargs):
        return payload if payload is not None else {
            "status": "ok", "count": len(_SIGNALS), "signals": _SIGNALS,
            "freshness": {"age_s": 12}, "provider": "signal-layer",
        }
    return SimpleNamespace(signals=signals)


def test_routed_feed_classifies_live_signals_per_domain_and_agent(monkeypatch):
    monkeypatch.setattr(signals_router, "get_orch", lambda: _orch(_live_plugin()))
    body = json.loads(asyncio.run(signals_router.signals_routed()).body)

    assert body["available"] is True
    assert body["counts"] == {"signals": 3, "routed": 2, "unrouted": 1}
    # conflict + cyber matched; the third signal stays honestly unrouted
    assert set(body["by_domain"]) == {"conflict", "cyber"}
    assert body["unrouted"] == [2]
    # per-agent slices: ultron is cyber-only, argus sees everything routed
    assert body["by_agent"]["ultron"] == [1]
    assert body["by_agent"]["argus"] == [0, 1]
    assert body["freshness"] == {"age_s": 12}


def test_routed_feed_is_honest_when_no_sidecar_is_configured(monkeypatch):
    monkeypatch.setattr(signals_router, "get_orch", lambda: _orch())
    body = json.loads(asyncio.run(signals_router.signals_routed()).body)

    assert body["available"] is False
    assert body["reason"] == "signal_layer_plugin_unavailable"
    assert body["by_domain"] == {} and body["by_agent"] == {} and body["signals"] == []


def test_routed_feed_reports_an_unavailable_sidecar_without_inventing_signals(monkeypatch):
    plugin = _live_plugin({"status": "unavailable", "detail": "connection refused"})
    monkeypatch.setattr(signals_router, "get_orch", lambda: _orch(plugin))
    body = json.loads(asyncio.run(signals_router.signals_routed()).body)

    assert body["available"] is False
    assert body["reason"] == "unavailable"
    assert body["signals"] == []


def test_routed_feed_survives_a_raising_plugin(monkeypatch):
    async def boom(**kwargs):
        raise RuntimeError("sidecar exploded")
    monkeypatch.setattr(signals_router, "get_orch",
                        lambda: _orch(SimpleNamespace(signals=boom)))
    body = json.loads(asyncio.run(signals_router.signals_routed()).body)

    assert body["available"] is False
    assert body["reason"] == "fetch_failed"


def test_agent_slice_filters_to_one_agents_interests(monkeypatch):
    monkeypatch.setattr(signals_router, "get_orch", lambda: _orch(_live_plugin()))
    body = json.loads(asyncio.run(signals_router.signals_for_agent("ultron")).body)

    assert body["agent"] == "ultron"
    assert body["available"] is True
    assert len(body["signals"]) == 1
    assert "Ransomware" in body["signals"][0]["title"]


def test_agent_slice_rejects_an_unknown_agent_honestly(monkeypatch):
    monkeypatch.setattr(signals_router, "get_orch", lambda: _orch(_live_plugin()))
    body = json.loads(asyncio.run(signals_router.signals_for_agent("nobody")).body)

    assert body["agent"] == "nobody"
    assert body["known_agent"] is False
    assert body["signals"] == []


def test_domain_brief_ranks_by_severity(monkeypatch):
    # Explicit top/limit: calling the handler directly bypasses FastAPI's
    # dependency resolution, so the Query(...) defaults would arrive as Query
    # objects rather than ints. Production always gets real values (proven by
    # the HTTP round-trip below).
    monkeypatch.setattr(signals_router, "get_orch", lambda: _orch(_live_plugin()))
    body = json.loads(asyncio.run(
        signals_router.signals_domain_brief("cyber", top=5, limit=20)).body)

    assert body["domain"] == "cyber"
    assert body["known_domain"] is True
    assert body["count"] == 1
    assert "Ransomware" in body["top"][0]["title"]


def test_domain_brief_unknown_domain_is_explicit(monkeypatch):
    monkeypatch.setattr(signals_router, "get_orch", lambda: _orch(_live_plugin()))
    body = json.loads(asyncio.run(
        signals_router.signals_domain_brief("astrology", top=5, limit=20)).body)

    assert body["known_domain"] is False
    assert body["top"] == []


def test_routes_registered_and_user_guarded():
    paths = {r.path for r in signals_router.router.routes}
    assert paths == {
        "/api/signals/routed",
        "/api/signals/agent/{agent_id}",
        "/api/signals/brief/{domain}",
    }
    for route in signals_router.router.routes:
        names = {getattr(d.call, "__name__", "") for d in route.dependant.dependencies}
        assert "user_guard" in names, f"{route.path} must be user-guarded"


def test_http_roundtrip_degrades_honestly_without_a_plugin():
    from fastapi.testclient import TestClient

    from agents import web

    client = TestClient(web.app)
    r = client.get("/api/signals/routed")
    assert r.status_code == 200
    assert r.json()["available"] is False


def test_http_roundtrip_with_a_live_plugin_resolves_real_query_defaults(monkeypatch):
    """The real FastAPI path — proves the Query(...) defaults resolve to ints
    (the direct-call tests above pass them explicitly for exactly this reason)."""
    from fastapi.testclient import TestClient

    from agents import web

    monkeypatch.setattr(signals_router, "get_orch", lambda: _orch(_live_plugin()))
    client = TestClient(web.app)

    r = client.get("/api/signals/routed")
    assert r.status_code == 200 and r.json()["counts"]["routed"] == 2

    r = client.get("/api/signals/brief/cyber")
    assert r.status_code == 200
    assert r.json()["count"] == 1 and r.json()["available"] is True

    r = client.get("/api/signals/agent/ultron")
    assert r.status_code == 200 and r.json()["count"] == 1

    # bounds are enforced by FastAPI, not silently clamped
    assert client.get("/api/signals/routed?limit=0").status_code == 422
