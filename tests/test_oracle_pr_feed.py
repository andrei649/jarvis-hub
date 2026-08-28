"""Tests for OracleBridgePlugin's dev-swarm PR/CI feed (H34.3).

Read-only: lists open PRs + their check-run summary next to the dev-lock
panel. Gated on an explicit `github_token` (an unauthenticated GitHub API
call is capped at 60/hr, far below what this feed needs every refresh) and
refreshed on a bounded cadence, never per-request.
"""

import asyncio
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.plugins.oracle_bridge import OracleBridgePlugin


class _FakeResp:
    def __init__(self, status_code=200, json_body=None, headers=None):
        self.status_code = status_code
        self._json = {} if json_body is None else json_body
        self.headers = headers or {}

    def json(self):
        return self._json


def test_pr_feed_disabled_without_token():
    bridge = OracleBridgePlugin(github_token="")
    result = asyncio.run(bridge._refresh_pr_feed())
    assert result["available"] is False
    assert result["error"] == "no_github_token"
    assert result["prs"] == []


def test_pr_feed_fetches_open_prs_and_check_summaries(monkeypatch):
    bridge = OracleBridgePlugin(github_token="ghp_test")

    pulls = [
        {
            "number": 42,
            "title": "fix(kernel): example",
            "user": {"login": "someone"},
            "html_url": "https://github.com/andrei649/jarvis-hub/pull/42",
            "draft": False,
            "head": {"sha": "abc123", "ref": "fix/example"},
            "updated_at": "2026-08-28T00:00:00Z",
        },
    ]
    check_runs = {
        "check_runs": [
            {"status": "completed", "conclusion": "success"},
            {"status": "completed", "conclusion": "failure"},
            {"status": "in_progress", "conclusion": None},
        ]
    }
    calls = []

    async def fake_get(url, headers=None, params=None):
        calls.append(url)
        if url.endswith("/pulls"):
            return _FakeResp(200, pulls, headers={"Link": ""})
        if "check-runs" in url:
            assert "abc123" in url
            return _FakeResp(200, check_runs)
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(bridge._client, "get", fake_get)

    result = asyncio.run(bridge._refresh_pr_feed(force=True))

    assert result["available"] is True
    assert result["error"] is None
    assert len(result["prs"]) == 1
    pr = result["prs"][0]
    assert pr["number"] == 42
    assert pr["author"] == "someone"
    assert pr["branch"] == "fix/example"
    assert pr["checks"] == {
        "total": 3, "passed": 1, "failed": 1, "pending": 1, "state": "failure",
    }
    assert len(calls) == 2  # one PR list + one check-runs call


def test_pr_feed_all_green_state(monkeypatch):
    bridge = OracleBridgePlugin(github_token="ghp_test")
    pulls = [{"number": 1, "title": "t", "user": {"login": "a"}, "html_url": "",
              "draft": False, "head": {"sha": "s1", "ref": "b"}, "updated_at": ""}]
    check_runs = {"check_runs": [{"status": "completed", "conclusion": "success"}]}

    async def fake_get(url, headers=None, params=None):
        if url.endswith("/pulls"):
            return _FakeResp(200, pulls, headers={})
        return _FakeResp(200, check_runs)

    monkeypatch.setattr(bridge._client, "get", fake_get)
    result = asyncio.run(bridge._refresh_pr_feed(force=True))
    assert result["prs"][0]["checks"]["state"] == "success"


def test_pr_feed_no_checks_state_none(monkeypatch):
    bridge = OracleBridgePlugin(github_token="ghp_test")
    pulls = [{"number": 1, "title": "t", "user": {"login": "a"}, "html_url": "",
              "draft": True, "head": {"sha": "s1", "ref": "b"}, "updated_at": ""}]

    async def fake_get(url, headers=None, params=None):
        if url.endswith("/pulls"):
            return _FakeResp(200, pulls, headers={})
        return _FakeResp(200, {"check_runs": []})

    monkeypatch.setattr(bridge._client, "get", fake_get)
    result = asyncio.run(bridge._refresh_pr_feed(force=True))
    assert result["prs"][0]["checks"]["state"] == "none"
    assert result["prs"][0]["draft"] is True


def test_pr_feed_respects_cadence_without_force(monkeypatch):
    bridge = OracleBridgePlugin(github_token="ghp_test")
    calls = []

    async def fake_get(url, headers=None, params=None):
        calls.append(url)
        return _FakeResp(200, [])

    monkeypatch.setattr(bridge._client, "get", fake_get)

    asyncio.run(bridge._refresh_pr_feed(force=True))
    asyncio.run(bridge._refresh_pr_feed())  # too soon since the forced call — no re-fetch
    assert len(calls) == 1


def test_pr_feed_degrades_honestly_on_api_error(monkeypatch):
    bridge = OracleBridgePlugin(github_token="ghp_test")

    async def fake_get(url, headers=None, params=None):
        return _FakeResp(403, {"message": "rate limited"})

    monkeypatch.setattr(bridge._client, "get", fake_get)
    result = asyncio.run(bridge._refresh_pr_feed(force=True))
    assert result["available"] is False
    assert result["error"] == "github_api_403"
    assert result["prs"] == []


def test_pr_feed_degrades_honestly_on_network_exception(monkeypatch):
    bridge = OracleBridgePlugin(github_token="ghp_test")

    async def fake_get(url, headers=None, params=None):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(bridge._client, "get", fake_get)
    result = asyncio.run(bridge._refresh_pr_feed(force=True))
    assert result["available"] is False
    assert result["error"] == "connection refused"


def test_status_includes_an_honest_default_pr_feed():
    bridge = OracleBridgePlugin(github_token="")
    st = bridge.status()
    assert "pr_feed" in st
    assert st["pr_feed"]["available"] is False
    assert st["pr_feed"]["checked_at"] == 0.0


def test_sync_now_also_force_refreshes_the_pr_feed(monkeypatch):
    bridge = OracleBridgePlugin(github_token="ghp_test")

    async def fake_check_github():
        return {"ok": True, "new": False}

    calls = []

    async def fake_refresh(*, force=False):
        calls.append(force)
        return bridge.pr_feed

    monkeypatch.setattr(bridge, "_check_github", fake_check_github)
    monkeypatch.setattr(bridge, "_refresh_pr_feed", fake_refresh)

    asyncio.run(bridge.sync_now())

    assert calls == [True]
