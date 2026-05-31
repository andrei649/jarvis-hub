"""Tests for Stark AnalyticsPlugin."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import pytest
from agents.core.plugins.analytics import AnalyticsPlugin, MOCK_KPIS, MOCK_CAMPAIGNS


@pytest.fixture
def empty_plugin():
    return AnalyticsPlugin()


class TestInit:
    def test_init_unconfigured(self, empty_plugin):
        assert empty_plugin.available() is False

    async def test_close(self, empty_plugin):
        await empty_plugin.close()


class TestGetKpis:
    async def test_get_kpis_mock(self, empty_plugin):
        kpis = await empty_plugin.get_kpis()
        assert kpis.get("mock") is True
        assert "daily_users" in kpis
        assert "page_views" in kpis
        assert "sessions" in kpis
        assert "conversion_rate" in kpis

    async def test_get_kpis_values(self, empty_plugin):
        kpis = await empty_plugin.get_kpis()
        assert kpis["daily_users"] > 0
        assert kpis["page_views"] > 0
        assert kpis["conversion_rate"] > 0


class TestGetSummary:
    async def test_get_summary_mock(self, empty_plugin):
        summary = await empty_plugin.get_summary()
        assert "Daily Active Users" in summary
        assert "mock" in summary.lower()

    async def test_get_summary_contains_numbers(self, empty_plugin):
        summary = await empty_plugin.get_summary()
        assert "%" in summary
        assert "$" in summary or "RON" in summary


class TestCampaigns:
    async def test_get_campaigns_mock(self, empty_plugin):
        camps = await empty_plugin.get_campaign_performance()
        assert camps.get("mock") is True
        assert "campaigns" in camps
        assert "total_roas" in camps

    async def test_campaigns_have_metrics(self, empty_plugin):
        camps = await empty_plugin.get_campaign_performance()
        for c in camps["campaigns"]:
            assert "impressions" in c
            assert "clicks" in c
            assert "spend" in c


class TestAvailable:
    async def test_available_with_ga4_config(self):
        plugin = AnalyticsPlugin(
            ga4_service_account='{"client_email":"test@test.com","private_key":"abc"}',
            ga4_property_id="123456789",
        )
        assert plugin.available() is True

    async def test_available_invalid_json(self):
        plugin = AnalyticsPlugin(ga4_service_account="not-json", ga4_property_id="123")
        assert plugin.available() is False
