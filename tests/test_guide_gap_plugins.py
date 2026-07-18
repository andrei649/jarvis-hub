"""Guide-gap connector plugins: RevenueCat, Meta Ads, Postiz (all offline).

Every plugin takes an injectable client (the network seam), so these tests
drive the full request/format logic with a fake — no real network, keys, or
hosts. Covers: unconfigured honesty, request shape (URL/auth/params/body),
success formatting, HTTP-error honesty, Meta act_ normalization, and the
Postiz draft-first refusals.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.plugins.meta_ads import MetaAdsPlugin
from core.plugins.postiz import PostizPlugin
from core.plugins.revenuecat import RevenueCatPlugin


class FakeClient:
    """Injectable PluginHTTPClient stand-in that records calls."""

    def __init__(self, json_data=None, status_code=200):
        self.json_data = json_data or {}
        self.status_code = status_code
        self.calls = []

    def _resp(self):
        resp = MagicMock()
        resp.status_code = self.status_code
        resp.json.return_value = self.json_data
        if self.status_code >= 400:
            resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "err", request=MagicMock(), response=resp
            )
        else:
            resp.raise_for_status = MagicMock()
        return resp

    async def get(self, url, headers=None, params=None):
        self.calls.append({"method": "GET", "url": url, "headers": headers, "params": params})
        return self._resp()

    async def post(self, url, headers=None, json=None):
        self.calls.append({"method": "POST", "url": url, "headers": headers, "json": json})
        return self._resp()


# ---------------------------------------------------------------------------
# RevenueCat
# ---------------------------------------------------------------------------

async def test_revenuecat_unconfigured_is_honest(monkeypatch):
    monkeypatch.delenv("REVENUECAT_API_KEY", raising=False)
    monkeypatch.delenv("REVENUECAT_PROJECT_ID", raising=False)
    rc = RevenueCatPlugin(client=FakeClient())
    assert not rc.available()
    result = await rc.get_overview()
    assert result["ok"] is False and "not configured" in result["error"]
    assert "[revenue unavailable" in await rc.overview_text()


async def test_revenuecat_overview_request_and_text():
    fake = FakeClient(json_data={"metrics": [
        {"id": "active_subscriptions", "name": "Active Subscriptions", "value": 42, "unit": "#"},
        {"id": "mrr", "name": "MRR", "value": 199.5, "unit": "USD"},
    ]})
    rc = RevenueCatPlugin(api_key="sk_test", project_id="proj1", client=fake)
    result = await rc.get_overview()
    assert result["ok"] is True
    call = fake.calls[0]
    assert call["url"] == "https://api.revenuecat.com/v2/projects/proj1/metrics/overview"
    assert call["headers"]["Authorization"] == "Bearer sk_test"

    text = await rc.overview_text()
    assert "Active Subscriptions: 42" in text
    assert "MRR: 199.5 USD" in text


async def test_revenuecat_http_error_is_honest():
    rc = RevenueCatPlugin(api_key="sk", project_id="p", client=FakeClient(status_code=401))
    result = await rc.get_overview()
    assert result["ok"] is False and "401" in result["error"]


# ---------------------------------------------------------------------------
# Meta Ads
# ---------------------------------------------------------------------------

async def test_meta_ads_unconfigured_is_honest(monkeypatch):
    monkeypatch.delenv("META_ADS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("META_ADS_ACCOUNT_ID", raising=False)
    ma = MetaAdsPlugin(client=FakeClient())
    assert not ma.available()
    result = await ma.get_insights()
    assert result["ok"] is False and "not configured" in result["error"]


async def test_meta_ads_account_id_normalized():
    assert MetaAdsPlugin(access_token="t", account_id="12345", client=FakeClient()).account_id == "act_12345"
    assert MetaAdsPlugin(access_token="t", account_id="act_9", client=FakeClient()).account_id == "act_9"


async def test_meta_ads_insights_request_and_text():
    fake = FakeClient(json_data={"data": [
        {"spend": "120.50", "impressions": "9000", "clicks": "150", "ctr": "1.6"},
    ]})
    ma = MetaAdsPlugin(access_token="tok", account_id="777", client=fake)
    result = await ma.get_insights(date_preset="last_30d")
    assert result["ok"] is True
    call = fake.calls[0]
    assert call["url"] == "https://graph.facebook.com/v23.0/act_777/insights"
    assert call["params"]["access_token"] == "tok"
    assert call["params"]["date_preset"] == "last_30d"

    text = await ma.insights_text(date_preset="last_30d")
    assert "spend: 120.50" in text and "last_30d" in text


async def test_meta_ads_campaigns_request():
    fake = FakeClient(json_data={"data": [{"name": "Launch", "status": "ACTIVE"}]})
    ma = MetaAdsPlugin(access_token="tok", account_id="777", client=fake)
    result = await ma.get_campaigns(limit=5)
    assert result["ok"] is True
    call = fake.calls[0]
    assert call["url"].endswith("/act_777/campaigns")
    assert call["params"]["limit"] == 5


async def test_meta_ads_has_no_mutation_methods():
    """Read-only by design: no update/pause/budget mutators on the plugin."""
    forbidden = [m for m in dir(MetaAdsPlugin)
                 if any(v in m.lower() for v in ("update", "pause", "set_budget", "create"))]
    assert forbidden == []


# ---------------------------------------------------------------------------
# Postiz
# ---------------------------------------------------------------------------

async def test_postiz_unconfigured_is_honest(monkeypatch):
    monkeypatch.delenv("POSTIZ_URL", raising=False)
    monkeypatch.delenv("POSTIZ_API_KEY", raising=False)
    pz = PostizPlugin(client=FakeClient())
    assert not pz.available()
    result = await pz.list_posts()
    assert result["ok"] is False and "not configured" in result["error"]
    assert "[social queue unavailable" in await pz.queue_text()


async def test_postiz_list_and_queue_text():
    fake = FakeClient(json_data={"posts": [
        {"state": "QUEUE", "publishDate": "2026-07-20T09:00:00Z", "content": "Launch day!"},
    ]})
    pz = PostizPlugin(base_url="http://localhost:5000", api_key="pk", client=fake)
    result = await pz.list_posts()
    assert result["ok"] is True
    call = fake.calls[0]
    assert call["url"] == "http://localhost:5000/api/public/v1/posts"
    assert call["headers"]["Authorization"] == "pk"

    text = await pz.queue_text()
    assert "QUEUE @ 2026-07-20T09:00:00Z: Launch day!" in text


async def test_postiz_schedule_post_defaults_to_draft():
    fake = FakeClient(json_data={"id": "p1"})
    pz = PostizPlugin(base_url="http://localhost:5000", api_key="pk", client=fake)
    result = await pz.schedule_post("Hello", ["int-1", "int-2"], "2026-07-21T10:00:00Z")
    assert result["ok"] is True
    body = fake.calls[0]["json"]
    assert body["type"] == "draft"                      # draft-first, never implicit publish
    assert body["date"] == "2026-07-21T10:00:00Z"
    assert [p["integration"]["id"] for p in body["posts"]] == ["int-1", "int-2"]
    assert body["posts"][0]["value"][0]["content"] == "Hello"


async def test_postiz_schedule_post_refusals():
    pz = PostizPlugin(base_url="http://localhost:5000", api_key="pk", client=FakeClient())
    assert (await pz.schedule_post("x", ["i"], "d", kind="now"))["ok"] is False
    assert (await pz.schedule_post("", ["i"], "d"))["ok"] is False
    assert (await pz.schedule_post("x", [], "d"))["ok"] is False


async def test_postiz_registers_dynamic_domain(monkeypatch):
    seen = {}
    import core.plugin_gate as gate
    monkeypatch.setattr(gate, "register_dynamic_domain",
                        lambda pid, url: seen.update({pid: url}))
    PostizPlugin(base_url="http://social.local:5000", api_key="pk", client=FakeClient())
    assert seen == {"postiz": "http://social.local:5000"}


# ---------------------------------------------------------------------------
# Manifests exist + permission wiring
# ---------------------------------------------------------------------------

def test_manifests_registered():
    from core.plugin_gate import BUILTIN_PLUGINS, DataScope, NetworkAccess
    for pid in ("revenuecat", "meta-ads", "postiz"):
        m = BUILTIN_PLUGINS[pid]
        assert m.network_access == NetworkAccess.RESTRICTED
    assert BUILTIN_PLUGINS["revenuecat"].allowed_domains == ["api.revenuecat.com"]
    assert BUILTIN_PLUGINS["meta-ads"].allowed_domains == ["graph.facebook.com"]
    # Postiz transmits owner content outward and its host is config-driven.
    assert BUILTIN_PLUGINS["postiz"].data_scope == DataScope.TRANSMITTED
    assert BUILTIN_PLUGINS["postiz"].allowed_domains == []
