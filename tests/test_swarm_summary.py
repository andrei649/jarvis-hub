"""Tests for Mission Control (agents/core/routers/swarm.py) — ORIZONT 34 / H34.1.

The swarm feed is a read-only aggregation over existing subsystems, so these
tests pin three contracts: (1) the summary shape survives any partially
initialized orchestrator, (2) the user-tier feed never leaks admin-tier task
payloads, and (3) the dev-lock reader parses lock.py's on-disk format without
ever writing.
"""

import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.observability.tracer import Tracer
from agents.core.routers import swarm

TOP_KEYS = (
    "generated_at", "initialized", "halted", "agents", "activity",
    "autonomy", "presence", "missions", "workflows", "subagents", "a2a", "dev_locks",
)


def _agent(name, model):
    return SimpleNamespace(name=name, config={"model": model})


def _task(i, **over):
    base = {
        "id": i, "agent": "steve", "kind": "writeback.github", "title": f"task {i}",
        "payload": {"secret_detail": "admin-only"}, "risk_tier": 2,
        "status": "blocked", "autonomy_level": "ask", "origin": "generated",
        "attempts": 0, "result": {"private": True}, "decided_by": None,
        "decision": None, "pushed": 0, "created_at": "2026-07-24T10:00:00",
        "updated_at": "2026-07-24T10:00:00",
    }
    base.update(over)
    return SimpleNamespace(to_dict=lambda b=base: dict(b))


def _fake_orch(traces=(), **over):
    tracer = Tracer()
    for t in traces:
        tracer.record(t)
    orch = SimpleNamespace(
        tracer=tracer,
        agents={
            "jarvis": _agent("Jarvis", "local-model"),
            "vision": _agent("Vision", "claude-sonnet-4-6"),
            "frigga": _agent("Frigga", "local-gemma"),
        },
    )
    for k, v in over.items():
        setattr(orch, k, v)
    return orch


def test_empty_orch_returns_full_shape(monkeypatch):
    monkeypatch.delenv("JARVIS_A2A_ENABLED", raising=False)
    s = swarm.build_swarm_summary(None)
    for key in TOP_KEYS:
        assert key in s
    assert s["initialized"] is False
    assert s["halted"] is None
    assert s["agents"] == [] and s["activity"] == []
    assert s["autonomy"]["pending_count"] == 0
    assert s["autonomy"]["pending_preview"] == []
    assert s["missions"] == [] and s["workflows"] == {"runs": []}
    assert s["subagents"] == {"spawns": 0, "stats": {}}
    assert s["a2a"] == {"enabled": False, "pending": 0}
    assert set(s["dev_locks"]) == {"known", "agents", "components", "available"}


def test_roster_seeded_and_activity_attributed():
    now = time.time()
    traces = [
        {"ts": now - 2, "route": "vision", "model": "claude-sonnet-4-6",
         "tokens_in": 10, "tokens_out": 200, "cost": 0.5,
         "timings": {"total_ms": 1200}, "channel": "web", "intent": "research"},
        {"ts": now, "route": "vision", "model": "claude-sonnet-4-6",
         "tokens_in": 5, "tokens_out": 80, "cost": 0.25,
         "timings": {"total_ms": 600}, "channel": "web", "intent": "research"},
    ]
    s = swarm.build_swarm_summary(_fake_orch(traces))
    ids = {r["id"] for r in s["agents"]}
    # Mission Control shows the whole cabinet, core included.
    assert {"jarvis", "vision", "frigga"} <= ids
    vision = next(r for r in s["agents"] if r["id"] == "vision")
    assert vision["events"] == 2
    assert vision["tokens_out"] == 280
    assert round(vision["cost_eur"], 2) == 0.75
    assert vision["last_ts"] > 1e12          # epoch ms
    # idle agents stay visible as zero nodes
    frigga = next(r for r in s["agents"] if r["id"] == "frigga")
    assert frigga["events"] == 0 and frigga["model"] == "local-gemma"
    # activity: newest-first, epoch ms, capped fields present
    assert len(s["activity"]) == 2
    top = s["activity"][0]
    assert top["ts"] >= s["activity"][1]["ts"]
    assert top["ts"] > 1e12
    assert top["agent"] == "vision"
    assert top["duration_ms"] == 600
    assert top["ok"] is True


def test_activity_capped_at_60():
    now = time.time()
    traces = [
        {"ts": now - i, "route": "vision", "model": "m", "tokens_out": 1,
         "cost": 0.0, "channel": "web"}
        for i in range(80)
    ]
    s = swarm.build_swarm_summary(_fake_orch(traces))
    assert len(s["activity"]) == 60
    vision = next(r for r in s["agents"] if r["id"] == "vision")
    assert vision["events"] == 80            # rollup still counts everything


def test_autonomy_block_uses_status_accessors_without_payload_leak():
    queue = SimpleNamespace(
        stats=lambda: {"proposed": 1, "blocked": 2},
        pending_decisions=lambda: [_task(1), _task(2), _task(3)],
    )
    autonomy = SimpleNamespace(
        policy=SimpleNamespace(mode="ask"),
        budget=SimpleNamespace(remaining=lambda: 3, per_day=4),
    )
    orch = _fake_orch(autonomy_queue=queue, autonomy=autonomy,
                      get_setting=lambda k, d=None: d)
    s = swarm.build_swarm_summary(orch)
    au = s["autonomy"]
    assert au["stats"] == {"proposed": 1, "blocked": 2}
    assert au["mode"] == "ask"
    assert au["budget"] == {"remaining": 3, "per_day": 4}
    assert au["pending_count"] == 3
    assert len(au["pending_preview"]) == 3
    for row in au["pending_preview"]:
        # Tier hygiene: the user-tier feed must not carry admin-tier fields.
        assert "payload" not in row and "result" not in row
        assert set(row) == set(swarm._PREVIEW_FIELDS)
    assert au["pending_preview"][0]["title"] == "task 1"


def test_partial_orch_never_raises():
    # Only tracer + agents — every other subsystem missing.
    s = swarm.build_swarm_summary(_fake_orch())
    assert s["initialized"] is True
    assert s["halted"] is None
    assert s["autonomy"]["stats"] == {}
    assert s["missions"] == []

    # A subsystem that *raises* degrades to defaults instead of failing.
    def _boom():
        raise RuntimeError("db locked")
    orch = _fake_orch(
        autonomy_queue=SimpleNamespace(stats=_boom, pending_decisions=_boom),
        missions=SimpleNamespace(list=_boom),
        workflow_engine=SimpleNamespace(recent=_boom),
        subagents=SimpleNamespace(list=_boom, stats=_boom),
        kill_switch=SimpleNamespace(is_halted=_boom),
    )
    s = swarm.build_swarm_summary(orch)
    assert s["autonomy"]["stats"] == {}
    assert s["autonomy"]["pending_count"] == 0
    assert s["missions"] == []
    assert s["workflows"] == {"runs": []}
    assert s["subagents"] == {"spawns": 0, "stats": {}}
    assert s["halted"] is None


def test_missions_workflows_subagents_halted_passthrough():
    # "active" is a real MissionStatus value (missions.py) — the page keys its
    # steering buttons on the real enum, so the fake must use it too.
    mission = SimpleNamespace(to_dict=lambda: {"id": 7, "title": "ship it", "status": "active"})
    orch = _fake_orch(
        missions=SimpleNamespace(list=lambda limit=10: [mission]),
        workflow_engine=SimpleNamespace(recent=lambda n: [{"id": "run-1", "ok": True}]),
        subagents=SimpleNamespace(list=lambda: [{"id": "s1"}, {"id": "s2"}],
                                  stats=lambda: {"active": 1}),
        kill_switch=SimpleNamespace(is_halted=lambda: True),
    )
    s = swarm.build_swarm_summary(orch)
    assert s["missions"] == [{"id": 7, "title": "ship it", "status": "active"}]
    assert s["workflows"]["runs"] == [{"id": "run-1", "ok": True}]
    assert s["subagents"] == {"spawns": 2, "stats": {"active": 1}}
    assert s["halted"] is True


def test_dev_locks_reader(tmp_path, monkeypatch):
    monkeypatch.setattr(swarm, "_LOCKS_DIR", tmp_path)
    now = time.time()
    (tmp_path / "claude.active").write_text(json.dumps(
        {"agent": "claude", "message": "building mission control",
         "time": "10:00:00", "ts": now - 60}), encoding="utf-8")
    (tmp_path / "opencode.active").write_text(json.dumps(
        {"agent": "opencode", "message": "old session",
         "time": "08:00:00", "ts": now - 7200}), encoding="utf-8")
    (tmp_path / "broken.active").write_text("{not json", encoding="utf-8")
    (tmp_path / "lock_state.json").write_text(json.dumps({
        "c:\\repo\\agents\\web.py": {"entity": "opencode", "task": "routes",
                                     "ts": now - 30, "time": "10:01:00"},
        "c:\\repo\\skills": {"entity": "claude", "task": "old lock",
                             "ts": now - 9000, "time": "07:00:00"},
    }), encoding="utf-8")

    d = swarm.read_dev_locks(now)
    assert d["available"] is True
    assert d["known"] == list(swarm._DEV_AGENTS)
    agents = {a["agent"]: a for a in d["agents"]}
    assert set(agents) == {"claude", "opencode"}     # corrupt file skipped
    assert agents["claude"]["stale"] is False
    assert agents["opencode"]["stale"] is True
    comps = {c["component"]: c for c in d["components"]}
    assert comps["web.py"]["entity"] == "opencode"
    assert comps["web.py"]["stale"] is False
    assert comps["skills"]["stale"] is True
    # fresh locks sort first
    assert d["components"][0]["component"] == "web.py"


def test_dev_locks_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(swarm, "_LOCKS_DIR", tmp_path / "nope")
    d = swarm.read_dev_locks()
    assert d == {"known": list(swarm._DEV_AGENTS), "agents": [],
                 "components": [], "available": False}


def test_dev_locks_corrupt_state_file(tmp_path, monkeypatch):
    monkeypatch.setattr(swarm, "_LOCKS_DIR", tmp_path)
    (tmp_path / "lock_state.json").write_text("][", encoding="utf-8")
    d = swarm.read_dev_locks()
    assert d["available"] is True
    assert d["components"] == []


def test_routes_registered():
    paths = {r.path for r in swarm.router.routes}
    assert "/mission-control" in paths
    assert "/api/swarm/summary" in paths


def test_routes_are_user_guarded():
    for route in swarm.router.routes:
        names = {getattr(d.call, "__name__", "") for d in route.dependant.dependencies}
        assert "user_guard" in names, f"{route.path} must be user-guarded"


def test_http_page_and_summary(monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web

    client = TestClient(web.app)

    monkeypatch.setattr(web, "orch", None)
    r = client.get("/api/swarm/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["initialized"] is False
    for key in TOP_KEYS:
        assert key in body

    monkeypatch.setattr(web, "orch", _fake_orch())
    r = client.get("/api/swarm/summary")
    assert r.status_code == 200
    assert {a["id"] for a in r.json()["agents"]} >= {"jarvis", "vision", "frigga"}

    r = client.get("/mission-control")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "MISSION CONTROL" in r.text


def test_html_selfcontained_and_wired():
    html = (repo_root / "agents" / "web" / "mission_control.html").read_text(encoding="utf-8")
    # CSP-safe: no external scripts/styles/fonts.
    assert 'src="http' not in html and "src='http" not in html
    assert 'href="http' not in html and "href='http" not in html
    # Wired to the feed + the existing governed steering endpoints.
    for ref in ("/api/swarm/summary", "/autonomy/approvals", "/autonomy/tasks/",
                "/api/missions/", "/api/a2a/inbox", "hud.admin_token"):
        assert ref in html, f"page must reference {ref}"
    # Mission steering buttons must key on the REAL MissionStatus values —
    # 'created'/'running' do not exist (caught in the H34.1 review).
    for status in ('planned:["start"', 'active:["pause"', 'paused:["resume"'):
        assert status in html.replace(" ", ""), f"MISSION_ACTIONS must key on real status: {status}"
    assert "created:[" not in html.replace(" ", "")
    assert "running:[" not in html.replace(" ", "")
