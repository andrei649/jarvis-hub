"""H22 — first-party local analytics (privacy-first, offline, aggregate-on-read).

Covers the store (`core.analytics_store`), the public beacon route
(`POST /api/analytics/event`), and the plugin interface re-implemented over the
local table (`get_kpis` / `get_summary` shape-compat). Offline, no network.
"""
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import pytest
from fastapi.testclient import TestClient

from agents.core import analytics_store


@pytest.fixture
def store(tmp_path):
    """Isolated, file-backed analytics store (so WAL/aggregate paths are real)."""
    db = tmp_path / "analytics.db"
    analytics_store.initialize(str(db))
    yield analytics_store
    analytics_store.close()


# ── store: persistence ───────────────────────────────────────────────

class TestRecordEvent:
    def test_record_persists(self, store):
        eid = store.record_event("pageview", path="/pricing", session_id="s1")
        assert isinstance(eid, int) and eid > 0
        assert store.total_events() == 1

    def test_record_multiple(self, store):
        for i in range(5):
            store.record_event("pageview", path="/blog", session_id=f"s{i}")
        assert store.total_events() == 5

    def test_bad_props_does_not_raise(self, store):
        # A non-serializable prop bag must degrade, never 500 the ingest path.
        eid = store.record_event("pageview", path="/x", props={"o": object()})
        assert eid > 0
        assert store.total_events() == 1

    def test_explicit_ts_window(self, store):
        store.record_event("pageview", path="/old", ts="2000-01-01T00:00:00+00:00")
        store.record_event("pageview", path="/new")
        # 30-day window excludes the year-2000 event; all-time includes both.
        assert store.total_events(days=30) == 1
        assert store.total_events(days=0) == 2


# ── store: aggregate-on-read ─────────────────────────────────────────

class TestAggregates:
    def test_top_paths_ordering(self, store):
        for _ in range(3):
            store.record_event("pageview", path="/pricing")
        store.record_event("pageview", path="/blog")
        top = store.top_paths(limit=10)
        assert top[0] == {"path": "/pricing", "views": 3}
        assert {"path": "/blog", "views": 1} in top

    def test_top_paths_limit(self, store):
        for p in ("/a", "/b", "/c", "/d"):
            store.record_event("pageview", path=p)
        assert len(store.top_paths(limit=2)) == 2

    def test_event_counts_group_by_name(self, store):
        store.record_event("pageview", path="/a")
        store.record_event("pageview", path="/b")
        store.record_event("click", path="/a")
        counts = store.event_counts()
        assert counts == {"pageview": 2, "click": 1}

    def test_unique_sessions(self, store):
        store.record_event("pageview", session_id="s1")
        store.record_event("pageview", session_id="s1")
        store.record_event("pageview", session_id="s2")
        store.record_event("pageview")  # null session — not counted
        assert store.unique_sessions() == 2

    def test_timeseries_groups_by_day(self, store):
        store.record_event("pageview", ts="2026-06-10T01:00:00+00:00")
        store.record_event("pageview", ts="2026-06-10T05:00:00+00:00")
        store.record_event("pageview", ts="2026-06-11T05:00:00+00:00")
        ts = store.timeseries(days=0)
        assert {"day": "2026-06-10", "count": 2} in ts
        assert {"day": "2026-06-11", "count": 1} in ts

    def test_kpis_shape_and_values(self, store):
        store.record_event("pageview", path="/pricing", session_id="s1")
        store.record_event("pageview", path="/pricing", session_id="s2")
        store.record_event("conversion", session_id="s1")
        k = store.kpis(days=30)
        for key in ("daily_users", "page_views", "sessions",
                    "conversion_rate", "revenue", "top_pages"):
            assert key in k
        assert k["page_views"] == 2
        assert k["sessions"] == 2
        assert k["mock"] is False
        assert k["conversion_rate"] > 0  # 1 conversion / 3 events
        assert k["top_pages"][0]["path"] == "/pricing"

    def test_kpis_empty_is_zero_not_mock(self, store):
        k = store.kpis()
        assert k["page_views"] == 0
        assert k["sessions"] == 0
        assert k["mock"] is False


# ── route: POST /api/analytics/event ─────────────────────────────────

class TestIngestRoute:
    @pytest.fixture
    def client(self, tmp_path):
        analytics_store.initialize(str(tmp_path / "route.db"))
        from agents import web
        c = TestClient(web.app)
        yield c
        analytics_store.close()

    def test_ingest_valid_body(self, client):
        r = client.post("/api/analytics/event", json={
            "name": "pageview", "path": "/features",
            "referrer": "https://example.com", "session_id": "abc",
            "props": {"plan": "pro"},
        })
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert isinstance(body["id"], int)

    def test_ingest_minimal_body(self, client):
        r = client.post("/api/analytics/event", json={"name": "click"})
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_rejects_missing_name(self, client):
        r = client.post("/api/analytics/event", json={"path": "/x"})
        assert r.status_code == 422

    def test_rejects_empty_name(self, client):
        r = client.post("/api/analytics/event", json={"name": ""})
        assert r.status_code == 422

    def test_rejects_unknown_keys(self, client):
        # extra='forbid' → junk fields rejected (no smuggling sensitive data).
        r = client.post("/api/analytics/event", json={
            "name": "pageview", "evil": "drop table"})
        assert r.status_code == 422

    def test_rejects_oversized_name(self, client):
        r = client.post("/api/analytics/event", json={"name": "x" * 5000})
        assert r.status_code == 422

    def test_ingest_then_aggregate(self, client):
        for _ in range(3):
            client.post("/api/analytics/event",
                        json={"name": "pageview", "path": "/p", "session_id": "s1"})
        assert analytics_store.top_paths()[0] == {"path": "/p", "views": 3}


# ── plugin: shape-compatible interface over local data ───────────────

class TestPluginInterface:
    @pytest.fixture
    def plugin(self, tmp_path):
        analytics_store.initialize(str(tmp_path / "plugin.db"))
        from agents.core.plugins.analytics import AnalyticsPlugin
        p = AnalyticsPlugin()
        yield p
        analytics_store.close()

    async def test_get_kpis_local(self, plugin):
        analytics_store.record_event("pageview", path="/a", session_id="s1")
        k = await plugin.get_kpis()
        assert k["mock"] is False
        assert k["page_views"] == 1
        for key in ("daily_users", "page_views", "sessions",
                    "conversion_rate", "revenue", "top_pages"):
            assert key in k

    async def test_get_summary_shape(self, plugin):
        analytics_store.record_event("pageview", path="/a", session_id="s1")
        summary = await plugin.get_summary()
        assert "Daily Active Users" in summary
        assert "Page Views" in summary
        assert "%" in summary
        assert "$" in summary

    async def test_ga4_off_by_default(self, plugin):
        # Local-first: the remote GA4 path is not "available" unless opted in.
        assert plugin.available() is False
        await plugin.close()

    async def test_ga4_opt_in_available(self, tmp_path):
        analytics_store.initialize(str(tmp_path / "ga4.db"))
        from agents.core.plugins.analytics import AnalyticsPlugin
        p = AnalyticsPlugin(
            ga4_service_account='{"client_email":"t@t.com","private_key":"k"}',
            ga4_property_id="123",
            ga4_enabled=True,
        )
        assert p.available() is True
        await p.close()
        analytics_store.close()

    async def test_campaigns_not_mock(self, plugin):
        camps = await plugin.get_campaign_performance()
        assert camps["mock"] is False
        assert "campaigns" in camps and "total_roas" in camps
