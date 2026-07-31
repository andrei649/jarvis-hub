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


class TestAccountMasking:
    async def test_balances_mask_account_numbers(self, empty_plugin):
        data = await empty_plugin.get_balances()
        for acct in data["ing"]:
            assert acct["account"].startswith("…")
            assert "1234567890" not in acct["account"]
            assert "0987654321" not in acct["account"]
        # currency and balance survive the masking copy
        assert data["ing"][0]["currency"] == "RON"

    async def test_summary_does_not_leak_full_iban(self, empty_plugin):
        summary = await empty_plugin.get_summary()
        assert "RO12INGB1234567890" not in summary
        assert "RO12INGB0987654321" not in summary
        assert "…7890" in summary  # masked tail still identifies the account


# ── runway must never be computed from placeholder money ──────────────────────
#
# `_compute_burn_rate` gated the runway on `have_real_balances`, which only asked
# whether a balance source was CONFIGURED. So an ING/Libra source that was set up
# but failing at runtime still produced a runway: `_raw_balances()` swallowed the
# error, fell through to `degraded(MOCK_BALANCES)`, and `_total_balance()` summed
# the hardcoded 12450.32 + 350.00 + 3200.00 into a real-looking 16000.32 —
# ignoring the `_mock`/`_degraded` markers `degraded()` had just stamped on it.
# The owner was then told their runway in months, from money that does not exist,
# in a payload that said `"mock": False`.

import pytest

from agents.core.plugins.balance import MOCK_BALANCES, BalanceReaderPlugin


def _plugin(**kw):
    """A plugin with no HTTP client — every test here stubs the fetch it needs."""
    p = BalanceReaderPlugin.__new__(BalanceReaderPlugin)
    p.ing_client_id = kw.get("ing_client_id", "")
    p.ing_client_secret = kw.get("ing_client_secret", "")
    p.libra_token = kw.get("libra_token", "")
    p.csv_path = kw.get("csv_path", "")
    p.tx_csv_path = kw.get("tx_csv_path", "")
    p.client = None
    return p


@pytest.mark.asyncio
async def test_total_balance_is_unknown_when_a_configured_source_fails():
    """None, not 0.0 and not the mock sum.

    Zero would be its own lie — it asserts the owner has no money. None is the
    absence of a claim, and it is what stops a runway being computed downstream.
    """
    p = _plugin(ing_client_id="id", ing_client_secret="s")

    async def boom():
        raise RuntimeError("ING API down")
    p._fetch_ing = boom

    total = await p._total_balance()
    mock_sum = round(sum(
        a["balance"] for accounts in MOCK_BALANCES.values()
        if isinstance(accounts, list) for a in accounts
    ), 2)
    assert total is None
    assert total != mock_sum, "summed the placeholder balances"
    assert total != 0.0, "reported 'no money' for 'we could not read it'"


@pytest.mark.asyncio
async def test_total_balance_sums_a_real_read():
    p = _plugin(ing_client_id="id")

    async def ok():
        return {"ing": [{"account": "x", "balance": 100.5, "currency": "RON"},
                        {"account": "y", "balance": 200.0, "currency": "RON"}]}
    p._fetch_ing = ok
    assert await p._total_balance() == 300.5


@pytest.mark.asyncio
async def test_burn_rate_reports_no_runway_when_the_balance_read_failed(tmp_path):
    """The end-to-end regression: real transactions, dead balance API."""
    csv_file = tmp_path / "tx.csv"
    csv_file.write_text(
        "date,amount,category\n"
        "2026-07-01,-1000,food\n"
        "2026-07-10,-500,transport\n"
        "2026-07-15,3000,salary\n"
    )
    p = _plugin(ing_client_id="id", ing_client_secret="s", tx_csv_path=str(csv_file))

    async def boom():
        raise RuntimeError("ING API down")
    p._fetch_ing = boom

    out = await p.get_burn_rate(days=30)

    # The spend/income ARE real — they came from the CSV, which read fine.
    assert out["monthly_spend"] == 1500.0
    assert out["monthly_income"] == 3000.0
    assert out["mock"] is False
    # But the runway is not invented, and the gap is named.
    assert out["runway_months"] is None
    assert out["runway_unavailable"] == "balances unavailable"


@pytest.mark.asyncio
async def test_burn_rate_gives_a_runway_when_the_balances_are_real(tmp_path):
    """The honest happy path still works — this is not a blanket suppression."""
    csv_file = tmp_path / "tx.csv"
    csv_file.write_text("date,amount,category\n2026-07-01,-1000,food\n")
    p = _plugin(ing_client_id="id", tx_csv_path=str(csv_file))

    async def ok():
        return {"ing": [{"account": "x", "balance": 5000.0, "currency": "RON"}]}
    p._fetch_ing = ok

    out = await p.get_burn_rate(days=30)
    assert out["monthly_spend"] == 1000.0
    assert out["runway_months"] == 5.0
    assert "runway_unavailable" not in out


@pytest.mark.asyncio
async def test_burn_rate_names_the_gap_when_no_balance_source_is_configured(tmp_path):
    """Distinct from a failed read: nothing was ever set up. Both give no runway,
    but the owner needs to know which one it is to act on it."""
    csv_file = tmp_path / "tx.csv"
    csv_file.write_text("date,amount,category\n2026-07-01,-1000,food\n")
    p = _plugin(tx_csv_path=str(csv_file))

    out = await p.get_burn_rate(days=30)
    assert out["runway_months"] is None
    assert out["runway_unavailable"] == "no balance source configured"
