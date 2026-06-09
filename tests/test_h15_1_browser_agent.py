"""H15.1: governed local browser-use.

Three composing gates: an egress allowlist (off-allowlist navigation is hard
blocked, not approvable), an approval queue for mutating steps, and an injectable
driver so the governance layer is fully offline-testable.
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.browser_agent import (  # noqa: E402
    BrowserPolicy, GovernedBrowser, NullBrowserDriver, classify_step,
)
from core.autonomy.action_approvals import ActionApprovalQueue  # noqa: E402
import agents.web as web  # noqa: E402


# ── egress allowlist ──────────────────────────────────────────────

def test_allowlist_suffix_match_and_fail_closed():
    pol = BrowserPolicy(["example.com"])
    assert pol.domain_allowed("https://example.com/x")[0] is True
    assert pol.domain_allowed("https://docs.example.com/x")[0] is True   # subdomain
    assert pol.domain_allowed("https://evil.com")[0] is False
    assert BrowserPolicy([]).domain_allowed("https://example.com")[0] is False  # empty = closed


def test_allowlist_blocks_private_ip(monkeypatch):
    # an allowlisted host that resolves to a private IP is still blocked (SSRF)
    pol = BrowserPolicy(["internal.test"])
    monkeypatch.setattr("core.security.ssrf.check_ssrf", lambda url: "private IP")
    ok, reason = pol.domain_allowed("https://internal.test/x")
    assert ok is False and "private" in reason.lower()


def test_no_hostname_blocked():
    assert BrowserPolicy(["x.com"]).domain_allowed("not a url")[0] is False


# ── step classification ───────────────────────────────────────────

def test_classify_step():
    assert classify_step("navigate") == "read"
    assert classify_step("extract") == "read"
    assert classify_step("click") == "risky"
    assert classify_step("execute_js") == "risky"
    assert classify_step("teleport") == "unknown"


# ── preview (governance dry-run) ──────────────────────────────────

def test_preview_classifies_each_step():
    gb = GovernedBrowser(policy=BrowserPolicy(["example.com"]))
    plan = [
        {"action": "navigate", "url": "https://example.com"},
        {"action": "navigate", "url": "https://evil.com"},
        {"action": "extract", "selector": "h1"},
        {"action": "click", "selector": "#buy"},
        {"action": "teleport"},
    ]
    out = gb.preview(plan)
    decisions = [s["decision"] for s in out["steps"]]
    assert decisions == ["run", "block", "run", "approve", "block"]
    assert out["needs_approval"] == 1 and out["blocked"] == 2


# ── run: gating behavior ──────────────────────────────────────────

async def test_offlist_navigation_hard_blocked():
    drv = NullBrowserDriver()
    gb = GovernedBrowser(driver=drv, policy=BrowserPolicy(["example.com"]))
    out = await gb.run([{"action": "navigate", "url": "https://evil.com"}])
    assert out["trace"][0]["status"] == "blocked"
    assert drv.calls == []                       # driver never touched


async def test_readonly_runs_without_approval():
    drv = NullBrowserDriver()
    gb = GovernedBrowser(driver=drv, policy=BrowserPolicy(["example.com"]))
    out = await gb.run([
        {"action": "navigate", "url": "https://example.com"},
        {"action": "extract", "selector": "h1"},
    ])
    assert out["ok"] is True
    assert [c[0] for c in drv.calls] == ["navigate", "extract"]


async def test_risky_step_denied_without_queue():
    drv = NullBrowserDriver()
    gb = GovernedBrowser(driver=drv, policy=BrowserPolicy(["example.com"]))
    out = await gb.run([{"action": "click", "selector": "#buy"}])
    assert out["trace"][0]["status"] == "denied"
    assert drv.calls == []


async def test_risky_step_runs_after_approval(tmp_path):
    import asyncio
    q = ActionApprovalQueue(path=str(tmp_path / "a.json"))
    drv = NullBrowserDriver()
    gb = GovernedBrowser(driver=drv, policy=BrowserPolicy(["example.com"]),
                         approvals=q, approval_timeout=2.0)

    async def approve_soon():
        for _ in range(50):
            pend = q.list(status="pending")
            if pend:
                q.decide(pend[0]["id"], True)
                return
            await asyncio.sleep(0.01)

    res, _ = await asyncio.gather(
        gb.run_step({"action": "click", "selector": "#buy"}), approve_soon())
    assert res["status"] == "done"
    assert drv.calls == [("click", {"selector": "#buy"})]


async def test_risky_step_rejected(tmp_path):
    import asyncio
    q = ActionApprovalQueue(path=str(tmp_path / "a.json"))
    drv = NullBrowserDriver()
    gb = GovernedBrowser(driver=drv, policy=BrowserPolicy(["example.com"]), approvals=q)

    async def reject_soon():
        for _ in range(50):
            pend = q.list(status="pending")
            if pend:
                q.decide(pend[0]["id"], False)
                return
            await asyncio.sleep(0.01)

    res, _ = await asyncio.gather(
        gb.run_step({"action": "type", "selector": "#q", "text": "hi"}), reject_soon())
    assert res["status"] == "denied" and res["reason"] == "rejected"
    assert drv.calls == []


async def test_run_stops_on_block():
    gb = GovernedBrowser(policy=BrowserPolicy(["example.com"]))
    out = await gb.run([
        {"action": "navigate", "url": "https://evil.com"},   # blocked → stop
        {"action": "extract", "selector": "h1"},
    ])
    assert out["steps"] == 1


# ── endpoints (offline) ───────────────────────────────────────────

def test_endpoint_check_and_preview():
    client = TestClient(web.app)
    chk = client.post("/api/browser/check",
                      json={"url": "https://example.com/x", "allowlist": ["example.com"]})
    assert chk.status_code == 200 and chk.json()["allowed"] is True
    off = client.post("/api/browser/check",
                      json={"url": "https://evil.com", "allowlist": ["example.com"]})
    assert off.json()["allowed"] is False

    prev = client.post("/api/browser/plan/preview", json={
        "allowlist": ["example.com"],
        "plan": [{"action": "navigate", "url": "https://example.com"},
                 {"action": "click", "selector": "#x"}]})
    body = prev.json()
    assert body["needs_approval"] == 1 and body["steps"][1]["decision"] == "approve"
