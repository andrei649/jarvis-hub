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
from agents.core.autonomy.action_approvals import ActionApprovalQueue  # noqa: E402
from agents.core import browser_agent as browser_api  # noqa: E402
import agents.web as web  # noqa: E402


# ── egress allowlist ──────────────────────────────────────────────

def test_allowlist_suffix_match_and_fail_closed(monkeypatch):
    monkeypatch.setattr("core.security.ssrf.check_ssrf", lambda _url: None)
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


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/",
        "http://example.com/",
        "data:text/html,hello",
        "file:///C:/owner/private.txt",
        "javascript:alert(1)",
    ],
)
async def test_navigation_without_transport_refuses_before_url_parsing_or_driver_call(url):
    class NeverParsePolicy(BrowserPolicy):
        def domain_allowed(self, _url):
            pytest.fail("navigation must refuse before URL policy parsing")

    driver = NullBrowserDriver()
    browser = GovernedBrowser(driver=driver, policy=NeverParsePolicy(["example.com"]))

    result = await browser.run_step({"action": "navigate", "url": url})

    assert result == {
        "action": "navigate",
        "status": "blocked",
        "reason": "browser transport unavailable",
    }
    assert driver.calls == []


async def test_readonly_runs_without_approval():
    drv = NullBrowserDriver()
    gb = GovernedBrowser(driver=drv, policy=BrowserPolicy(["example.com"]))
    out = await gb.run([
        {"action": "navigate", "url": "https://example.com"},
        {"action": "extract", "selector": "h1"},
    ])
    assert out["ok"] is False
    assert out["trace"] == [{
        "action": "navigate",
        "status": "blocked",
        "reason": "browser transport unavailable",
    }]
    assert drv.calls == []


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

@pytest.fixture
def client():
    return TestClient(web.app)


def test_endpoint_check_and_preview(client):
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
    assert body == {
        "steps": [
            {
                "index": 0,
                "action": "navigate",
                "kind": "read",
                "decision": "run",
                "reason": "",
            },
            {
                "index": 1,
                "action": "click",
                "kind": "risky",
                "decision": "approve",
                "reason": "mutating action requires approval",
            },
        ]
    }


@pytest.mark.parametrize(
    "step",
    [
        {"action": "teleport"},
        {"action": "Navigate", "url": "https://example.com"},
        {"url": "https://example.com"},
        {"action": "navigate"},
        {"action": "extract"},
        {"action": "click"},
        {"action": "type", "selector": "#q"},
        {"action": "submit"},
        {"action": "wait"},
        {"action": "screenshot"},
        {"action": "click", "selector": "#x", "unexpected": "secret"},
        {"action": 1, "selector": "#x"},
        {"action": "navigate", "url": 1},
        {"action": "extract", "selector": 1},
        {"action": "type", "selector": "#q", "text": 1},
    ],
)
def test_preview_rejects_non_exact_step_shapes_before_governed_browser(
    client,
    monkeypatch,
    step,
):
    calls = []
    monkeypatch.setattr(
        browser_api.GovernedBrowser,
        "preview",
        lambda *_args, **_kwargs: calls.append(True),
    )

    response = client.post(
        "/api/browser/plan/preview",
        json={"allowlist": ["example.com"], "plan": [step]},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid_browser_request"}
    assert calls == []


@pytest.mark.parametrize(
    ("route", "accepted", "rejected"),
    [
        (
            "/api/browser/check",
            {"url": "https://example.com/" + "a" * 1980, "allowlist": []},
            {"url": "https://example.com/" + "a" * 1981, "allowlist": []},
        ),
        (
            "/api/browser/check",
            {"url": "https://example.com", "allowlist": ["a" * 253]},
            {"url": "https://example.com", "allowlist": ["a" * 254]},
        ),
        (
            "/api/browser/plan/preview",
            {"plan": [{"action": "extract", "selector": "a" * 512}]},
            {"plan": [{"action": "extract", "selector": "a" * 513}]},
        ),
        (
            "/api/browser/plan/preview",
            {"plan": [{"action": "type", "selector": "#q", "text": "a" * 4000}]},
            {"plan": [{"action": "type", "selector": "#q", "text": "a" * 4001}]},
        ),
        (
            "/api/browser/check",
            {
                "url": "https://example.com",
                "allowlist": [f"host{i}.invalid" for i in range(100)],
            },
            {
                "url": "https://example.com",
                "allowlist": [f"host{i}.invalid" for i in range(101)],
            },
        ),
        (
            "/api/browser/plan/preview",
            {"plan": [{"action": "extract", "selector": "h1"}] * 200},
            {"plan": [{"action": "extract", "selector": "h1"}] * 201},
        ),
    ],
)
def test_browser_request_limits_accept_exact_boundary_and_reject_one_past(
    client,
    route,
    accepted,
    rejected,
):
    accepted_response = client.post(route, json=accepted)
    rejected_response = client.post(route, json=rejected)

    assert accepted_response.status_code == 200
    assert rejected_response.status_code == 422
    assert rejected_response.json() == {"detail": "invalid_browser_request"}


def test_browser_422_is_bounded_and_never_echoes_rejected_input(client):
    secret = "owner-secret-" + "x" * 4001

    response = client.post(
        "/api/browser/plan/preview",
        json={"plan": [{"action": "type", "selector": "#q", "text": secret}]},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid_browser_request"}
    assert secret not in response.text
    assert len(response.content) <= 64


def test_browser_check_and_preview_project_only_bounded_public_evidence(
    client,
    monkeypatch,
):
    monkeypatch.setattr(
        browser_api.BrowserPolicy,
        "domain_allowed",
        lambda *_args, **_kwargs: (False, "r" * 1000),
    )
    check = client.post(
        "/api/browser/check",
        json={"url": "https://example.com", "allowlist": ["example.com"]},
    )

    seen = []

    def preview(_self, plan):
        seen.append(plan)
        return {
            "needs_approval": 1,
            "blocked": 0,
            "steps": [
                {
                    "i": 0,
                    "action": "type",
                    "kind": "risky",
                    "decision": "approve",
                    "reason": "p" * 1000,
                    "text": "must-not-leak",
                    "internal": {"raw": True},
                }
            ],
        }

    monkeypatch.setattr(browser_api.GovernedBrowser, "preview", preview)
    response = client.post(
        "/api/browser/plan/preview",
        json={"plan": [{"action": "type", "selector": "#q", "text": "typed secret"}]},
    )

    assert check.status_code == 200
    assert check.json() == {"allowed": False, "reason": "r" * 240}
    assert seen == [[{"action": "type", "selector": "#q", "text": "typed secret"}]]
    assert response.status_code == 200
    assert response.json() == {
        "steps": [
            {
                "index": 0,
                "action": "type",
                "kind": "risky",
                "decision": "approve",
                "reason": "p" * 240,
            }
        ]
    }
    assert "typed secret" not in response.text
    assert "must-not-leak" not in response.text
