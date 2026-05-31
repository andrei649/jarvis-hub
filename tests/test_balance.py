"""Tests for Gecko BalanceReaderPlugin."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import pytest
from agents.core.plugins.balance import BalanceReaderPlugin, MOCK_BALANCES, MOCK_BURN_RATE


@pytest.fixture
def empty_plugin():
    return BalanceReaderPlugin()


@pytest.fixture
def configured_plugin():
    return BalanceReaderPlugin(ing_client_id="test-id", ing_client_secret="test-secret")


class TestInit:
    def test_init_unconfigured(self, empty_plugin):
        assert empty_plugin.available() is False

    def test_init_configured(self, configured_plugin):
        assert configured_plugin.available() is True

    async def test_close(self, empty_plugin):
        await empty_plugin.close()


class TestGetBalances:
    async def test_get_balances_mock(self, empty_plugin):
        data = await empty_plugin.get_balances()
        assert data.get("mock") is True
        assert "ing" in data
        assert "libra" in data
        assert len(data["ing"]) > 0
        assert data["ing"][0]["currency"] == "RON"

    async def test_get_balances_with_ing_configured(self):
        plugin = BalanceReaderPlugin(ing_client_id="id", ing_client_secret="secret")
        data = await plugin.get_balances()
        assert "ing" in data or "mock" in data

    async def test_get_balances_network_error(self):
        plugin = BalanceReaderPlugin(libra_token="bad-token")
        data = await plugin.get_balances()
        assert data.get("mock") is True


class TestGetSummary:
    async def test_get_summary_mock(self, empty_plugin):
        summary = await empty_plugin.get_summary()
        assert "mock" in summary.lower() or "ING" in summary or "LIBRA" in summary


class TestBurnRate:
    async def test_get_burn_rate_mock(self, empty_plugin):
        br = await empty_plugin.get_burn_rate()
        assert br.get("mock") is True
        assert "monthly_spend" in br
        assert "runway_months" in br
        assert isinstance(br["runway_months"], (int, float))

    async def test_burn_rate_has_categories(self, empty_plugin):
        br = await empty_plugin.get_burn_rate()
        cats = br.get("top_categories", {})
        assert len(cats) > 0
        assert isinstance(cats, dict)


class TestCsvImport:
    async def test_parse_csv_missing_file(self):
        plugin = BalanceReaderPlugin(csv_path="nonexistent.csv")
        data = await plugin.get_balances()
        assert data.get("mock") is True
