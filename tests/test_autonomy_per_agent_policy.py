"""HUD-v3 backend pre-work — per-agent autonomy policy + the interrupt-budget surface.

Adds `GET/POST /autonomy/policy` (per-agent AUTO/ASK/OFF, enforced) and
`GET /autonomy/interrupts`. Per-agent overrides default to empty, so an agent
with no override behaves exactly as the global mode (zero behavior change).
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.autonomy.policy import ACT, ASK, AutonomyPolicy  # noqa: E402
from agents.core.kernel import Action, Verdict, authorize  # noqa: E402

HEADERS = {"X-Admin-Token": "test-secret"}


# ── policy: effective_mode + per-agent decide ─────────────────────────────────
def test_effective_mode_falls_back_to_global():
    p = AutonomyPolicy(mode="auto", agent_modes={"vision": "off"})
    assert p.effective_mode("vision") == "off"        # override wins
    assert p.effective_mode("jarvis") == "auto"       # no override → global
    assert p.effective_mode(None) == "auto"


def test_decide_honors_per_agent_override():
    p = AutonomyPolicy(mode="auto", agent_modes={"vision": "off"})
    # a reversible write: the un-overridden agent acts, the off agent waits
    base = {"kind": "kg.write", "risk_tier": 1}
    assert p.decide({**base, "agent": "jarvis"}).outcome == ACT
    assert p.decide({**base, "agent": "vision"}).outcome == ASK


def test_default_empty_overrides_is_pure_global():
    p = AutonomyPolicy(mode="ask")        # no per-agent overrides
    # ask makes a side-effecting write wait for everyone, regardless of agent
    assert p.decide({"kind": "kg.write", "risk_tier": 1, "agent": "x"}).outcome == ASK
    assert p.decide({"kind": "read", "risk_tier": 0, "agent": "x"}).outcome == ACT  # reads still act


# ── kernel threads the agent into the policy ──────────────────────────────────
def test_kernel_passes_agent_so_per_agent_off_escalates(tmp_path):
    from agents.core.security.capability import KillSwitch
    ks = KillSwitch(tmp_path / "kill.json")
    pol = AutonomyPolicy(mode="auto", agent_modes={"vision": "off"})
    act = Action(kind="kg.write", agent="vision", payload={"risk_tier": 1})
    other = Action(kind="kg.write", agent="jarvis", payload={"risk_tier": 1})
    assert authorize(act, kill_switch=ks, policy=pol).verdict is Verdict.QUEUE   # off → ASK → QUEUE
    assert authorize(other, kill_switch=ks, policy=pol).verdict is Verdict.GRANT  # global auto → GRANT


# ── endpoints ─────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def token_client():
    import agents.web as web
    old = web.ADMIN_TOKEN
    web.ADMIN_TOKEN = "test-secret"
    with TestClient(web.app) as c:
        yield c
    web.ADMIN_TOKEN = old


def test_interrupts_endpoint_reports_budget(token_client):
    r = token_client.get("/autonomy/interrupts", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"remaining", "per_day", "used"}
    if body["per_day"] is not None:
        assert body["used"] == body["per_day"] - body["remaining"]


def test_policy_get_post_roundtrip(token_client):
    base = token_client.get("/autonomy/policy", headers=HEADERS).json()
    assert "global" in base and "agents" in base

    # set vision → off, then read it back
    r = token_client.post("/autonomy/policy", json={"agent": "vision", "mode": "off"}, headers=HEADERS)
    assert r.status_code == 200 and r.json()["ok"] is True
    assert token_client.get("/autonomy/policy", headers=HEADERS).json()["agents"].get("vision") == "off"

    # clear it (mode=default) → falls back to global
    token_client.post("/autonomy/policy", json={"agent": "vision", "mode": "default"}, headers=HEADERS)
    assert "vision" not in token_client.get("/autonomy/policy", headers=HEADERS).json()["agents"]


def test_policy_rejects_bad_mode(token_client):
    r = token_client.post("/autonomy/policy", json={"agent": "x", "mode": "bogus"}, headers=HEADERS)
    assert r.status_code == 422
