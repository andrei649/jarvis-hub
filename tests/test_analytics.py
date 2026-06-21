"""Tests for the AnalyticsPlugin (H22: local-first, GA4 mirror opt-in).

The plugin no longer fabricates mock KPIs — it aggregates the local first-party
event table on read. See test_analytics_local.py for the full store + route
coverage; this file pins the plugin's public interface and the GA4 opt-in flag.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import pytest
from agents.core import analytics_store
from agents.core.plugins.analytics import AnalyticsPlugin


@pytest.fixture
def empty_plugin(tmp_path):
    analytics_store.initialize(str(tmp_path / "analytics.db"))
    yield AnalyticsPlugin()
    analytics_store.close()


class TestInit:
    def test_init_local_first_ga4_off(self, empty_plugin):
        # GA4 remote path is OFF by default; local analytics still works.
        assert empty_plugin.available() is False

    async def test_close(self, empty_plugin):
        await empty_plugin.close()


class TestGetKpis:
    async def test_get_kpis_local_not_mock(self, empty_plugin):
        kpis = await empty_plugin.get_kpis()
        assert kpis.get("mock") is False
        assert "daily_users" in kpis
        assert "page_views" in kpis
        assert "sessions" in kpis
        assert "conversion_rate" in kpis

    async def test_get_kpis_reflects_events(self, empty_plugin):
        analytics_store.record_event("pageview", path="/a", session_id="s1")
        analytics_store.record_event("pageview", path="/a", session_id="s2")
        kpis = await empty_plugin.get_kpis()
        assert kpis["page_views"] == 2
        assert kpis["sessions"] == 2


class TestGetSummary:
    async def test_get_summary_shape(self, empty_plugin):
        summary = await empty_plugin.get_summary()
        assert "Daily Active Users" in summary

    async def test_get_summary_contains_numbers(self, empty_plugin):
        summary = await empty_plugin.get_summary()
        assert "%" in summary
        assert "$" in summary or "RON" in summary


class TestCampaigns:
    async def test_get_campaigns_not_mock(self, empty_plugin):
        camps = await empty_plugin.get_campaign_performance()
        assert camps.get("mock") is False
        assert "campaigns" in camps
        assert "total_roas" in camps


class TestAvailable:
    async def test_available_with_ga4_opt_in(self, tmp_path):
        analytics_store.initialize(str(tmp_path / "ga4.db"))
        plugin = AnalyticsPlugin(
            ga4_service_account='{"client_email":"test@test.com","private_key":"abc"}',
            ga4_property_id="123456789",
            ga4_enabled=True,
        )
        assert plugin.available() is True
        analytics_store.close()

    async def test_unavailable_when_ga4_disabled(self, tmp_path):
        analytics_store.initialize(str(tmp_path / "ga4.db"))
        # Configured but not enabled → still local-only.
        plugin = AnalyticsPlugin(
            ga4_service_account='{"client_email":"test@test.com","private_key":"abc"}',
            ga4_property_id="123456789",
            ga4_enabled=False,
        )
        assert plugin.available() is False
        analytics_store.close()

    async def test_available_invalid_json(self, tmp_path):
        analytics_store.initialize(str(tmp_path / "ga4.db"))
        plugin = AnalyticsPlugin(ga4_service_account="not-json", ga4_property_id="123",
                                 ga4_enabled=True)
        assert plugin.available() is False
        analytics_store.close()
