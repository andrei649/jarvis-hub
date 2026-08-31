"""H34.7 Live System Map — topology contract, reducers, parity, and routes.

Pins the plan's non-negotiables (docs/superpowers/plans/2026-08-31-live-system-map.md):

1. **Topology↔code parity** — every `health_source` the topology declares has an
   implemented reducer, and every `activity_source` a declared counter, so the
   map cannot silently claim a subsystem it does not read.
2. **Unknown never renders green** — a missing orchestrator or a raising reader
   reduces to `unknown`/`attention`, never `ok`.
3. **Honest states** — local LLM down is `attention`; unconfigured cloud is
   `off`; an actively-mock plugin is `degraded`; an egress violation, a failed
   task, a halted kill-switch each surface as `attention`.
4. **Payload-free** — the serialized feed never carries task payload/result
   content even when the fakes hold some.
"""

import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.observability.tracer import Tracer
from agents.core.routers import system_map as sm
from agents.core.system_map import (
    STATUSES,
    TopologyError,
    _validate,
    activity_sources,
    health_sources,
    load_topology,
)

# ── topology contract ─────────────────────────────────────────────────────────


def test_topology_loads_and_validates():
    topo = load_topology()
    assert topo["version"]
    ids = [n["id"] for n in topo["nodes"]]
    assert len(ids) == len(set(ids))
    for edge in topo["edges"]:
        assert edge["from"] in ids and edge["to"] in ids


def test_topology_rejects_malformed():
    with pytest.raises(TopologyError):
        _validate({"version": "x"})  # missing keys
    good = json.loads(json.dumps(load_topology()))
    good["edges"].append({"id": "bad", "from": "orch", "to": "nope"})
    with pytest.raises(TopologyError):
        _validate(good)
    dup = json.loads(json.dumps(load_topology()))
    dup["nodes"].append(dict(dup["nodes"][0]))
    with pytest.raises(TopologyError):
        _validate(dup)


def test_every_declared_source_has_an_implementation():
    """The parity gate: topology may only declare sources the code reads."""
    assert health_sources() <= set(sm.HEALTH_REDUCERS), (
        "topology declares a health_source with no reducer — the map would lie"
    )
    assert activity_sources() <= set(sm.ACTIVITY_SOURCES), (
        "topology declares an activity_source with no counter — the edge would lie"
    )


# ── fakes ─────────────────────────────────────────────────────────────────────


class _DegradedPlugin:
    configured = True

    def degradation_info(self):
        return {"reason": "mock fallback", "needs": ["SOME_KEY"]}


class _LivePlugin:
    configured = True


class _RaisingRouter:
    @property
    def _local_available(self):
        raise RuntimeError("boom")

    _cloud_available = False
    _claude_available = False


def _llm_router(local=True, cloud=False):
    return SimpleNamespace(
        _local_available=local, _cloud_available=cloud, _claude_available=False,
        _local_model="gemma-local", _backend_name="lmstudio",
        backend_type="auto", name="lmstudio",
    )


def _fake_orch(traces=(), **over):
    tracer = Tracer()
    for t in traces:
        tracer.record(t)
    orch = SimpleNamespace(
        tracer=tracer,
        agents={"jarvis": object(), "frigga": object()},
        channels={"web": object(), "telegram": object()},
        llm_router=_llm_router(),
        memory=SimpleNamespace(
            vectors=[0.0] * 7,
            graph=SimpleNamespace(entities={"andrei": {}, "nerva": {}}),
        ),
        plugins={"weather": _LivePlugin()},
        autonomy_queue=SimpleNamespace(
            stats=lambda: {"pending": 1, "failed": 0, "done": 5},
            pending_decisions=lambda: [SimpleNamespace(
                to_dict=lambda: {"payload": {"secret_detail": "admin-only"},
                                 "result": {"private": True}})],
        ),
        autonomy=SimpleNamespace(
            budget=SimpleNamespace(remaining=lambda: 3, per_day=4)),
        kill_switch=SimpleNamespace(is_halted=lambda: False),
        loop_detector=SimpleNamespace(status=lambda: {"tripped": False}),
        get_setting=lambda key, default=None: default,
    )
    for k, v in over.items():
        setattr(orch, k, v)
    return orch


def _trace(**over):
    base = {"ts": time.time(), "route": "jarvis", "channel": "web",
            "model": "gemma-local", "tokens_out": 10, "cost": 0.0,
            "total_ms": 50, "ok": True}
    base.update(over)
    return base


# ── reducers: honest states ───────────────────────────────────────────────────


def test_no_orchestrator_reduces_to_unknown_never_green():
    feed = sm.build_system_map(None)
    topo_ids = {n["id"] for n in load_topology()["nodes"]}
    assert set(feed["nodes"]) == topo_ids
    assert feed["initialized"] is False
    for info in feed["nodes"].values():
        assert info["status"] in STATUSES
    for nid in ("channels", "agents", "llm", "local", "cloud", "memory",
                "plugins", "autonomy"):
        assert feed["nodes"][nid]["status"] == "unknown", nid
    assert feed["nodes"]["orch"]["status"] == "attention"


def test_healthy_fake_orch_reduces_ok(monkeypatch):
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    feed = sm.build_system_map(_fake_orch(traces=[_trace()]))
    nodes = feed["nodes"]
    assert nodes["orch"]["status"] == "ok"
    assert nodes["agents"]["status"] == "ok"
    assert nodes["llm"]["status"] == "ok"
    assert nodes["local"]["status"] == "ok"
    assert nodes["local"]["stats"]["model"] == "gemma-local"
    assert nodes["cloud"]["status"] == "off"          # opt-in, unconfigured
    assert nodes["memory"]["stats"]["vectors"] == 7
    assert nodes["plugins"]["status"] == "ok"
    assert nodes["autonomy"]["status"] == "ok"
    assert nodes["kernel"]["status"] == "off"         # kernel rail is opt-in
    assert nodes["channels"]["stats"]["registered"] == 2


def test_local_llm_down_is_attention_and_cloud_configured_is_ok():
    orch = _fake_orch(llm_router=_llm_router(local=False, cloud=True))
    nodes = sm.build_system_map(orch)["nodes"]
    assert nodes["local"]["status"] == "attention"
    assert nodes["cloud"]["status"] == "ok"


def test_raising_reader_reduces_to_unknown():
    orch = _fake_orch(llm_router=_RaisingRouter())
    nodes = sm.build_system_map(orch)["nodes"]
    assert nodes["local"]["status"] == "unknown"


def test_failed_tasks_and_halt_surface_as_attention(monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    orch = _fake_orch(
        autonomy_queue=SimpleNamespace(stats=lambda: {"pending": 0, "failed": 2, "done": 1}),
        kill_switch=SimpleNamespace(is_halted=lambda: True),
    )
    nodes = sm.build_system_map(orch)["nodes"]
    assert nodes["autonomy"]["status"] == "attention"
    assert nodes["kernel"]["status"] == "attention"
    assert nodes["kernel"]["stats"]["kill_switch"] == "halted"


def test_mock_active_plugin_is_degraded_and_egress_violation_is_attention(monkeypatch):
    orch = _fake_orch(plugins={"tuya": _DegradedPlugin()})
    nodes = sm.build_system_map(orch)["nodes"]
    assert nodes["plugins"]["status"] == "degraded"
    assert nodes["plugins"]["stats"]["mock_active"] == 1

    monkeypatch.setattr(
        sm, "_build_context",
        lambda orch, now: {"turns_60s": 0, "inbound_turns_60s": 0,
                           "local_turns_60s": 0, "cloud_turns_60s": 0,
                           "active_agents_60s": 0,
                           "egress_violations": ["frigga_bridge"]},
    )
    nodes = sm.build_system_map(_fake_orch(plugins={"weather": _LivePlugin()}))["nodes"]
    assert nodes["plugins"]["status"] == "attention"


# ── edges: real counters, honest absence ─────────────────────────────────────


def test_edge_counters_split_local_cloud_and_inbound():
    now = time.time()
    orch = _fake_orch(traces=[
        _trace(ts=now, model="gemma-local", channel="web"),
        _trace(ts=now, model="gemini-2.5-flash", channel="telegram"),
        _trace(ts=now - 3600, model="gemma-local"),  # outside the 60s window
    ])
    edges = sm.build_system_map(orch)["edges"]
    assert edges["orch-to-agents"]["count"] == 2
    assert edges["llm-to-local"]["count"] == 1
    assert edges["llm-to-cloud"]["count"] == 1
    assert edges["channels-to-orch"]["count"] == 1
    assert edges["autonomy-to-channels"]["count"] == 1  # 4/day budget, 3 left


def test_absent_activity_is_omitted_not_fabricated():
    feed = sm.build_system_map(None)
    # no orch → no interrupt budget: the edge must be missing, not zeroed-fake
    assert "autonomy-to-channels" not in feed["edges"]
    # orch-to-plugins declares no activity_source at all → never present
    assert "orch-to-plugins" not in feed["edges"]


# ── payload discipline ────────────────────────────────────────────────────────


def test_feed_is_payload_free():
    feed = sm.build_system_map(_fake_orch(traces=[_trace()]))
    dumped = json.dumps(feed)
    assert "secret_detail" not in dumped
    assert "admin-only" not in dumped
    assert '"payload"' not in dumped and '"result"' not in dumped


# ── routes ────────────────────────────────────────────────────────────────────


def test_routes_serve_feed_and_page():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from agents.core.routers._deps import user_guard

    app = FastAPI()
    app.include_router(sm.router)
    app.dependency_overrides[user_guard] = lambda: None
    client = TestClient(app)

    r = client.get("/api/system-map")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == 1
    assert set(body["nodes"]) == {n["id"] for n in load_topology()["nodes"]}
    assert body["topology"]["version"] == body["topology_version"]
    assert "no-store" in (r.headers.get("cache-control") or "")

    r = client.get("/map")
    assert r.status_code == 200
    assert "LIVE SYSTEM MAP" in r.text
