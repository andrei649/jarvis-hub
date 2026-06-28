"""P3 — Market Intel + Finance pack: offline intel + a money-never-auto-moves rail.

The engine evaluates a watchlist against provided quotes (band breaches → alerts, each
carrying a mandatory not-advice disclaimer), rolls up a portfolio, and builds a demoable
daily brief — deterministic, no live fetch. The governance test proves the finance-safety
property with real primitives: a money action (trade/transfer) is QUEUED by the real
kernel while read-only market monitoring is GRANTed — money never moves without approval.
"""

import os
import shutil
import tempfile

from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.kernel import Action, Verdict, authorize
from agents.core.market import DISCLAIMER, daily_brief, evaluate_watchlist, portfolio_snapshot
from agents.core.observability import capability_registry as cr
from agents.core.observability.reality_harness import CASES, run_reality
from agents.core.security.capability import KillSwitch


# ── watchlist ──────────────────────────────────────────────────────────────────
def test_band_breach_classification_and_ordering():
    alerts = evaluate_watchlist(
        [{"symbol": "btc", "low": 60000, "high": 70000},
         {"symbol": "eth", "high": 4000},
         {"symbol": "vwce", "low": 100}],            # in-band
        {"BTC": 58000, "ETH": 4500, "VWCE": 110},
    )
    by = {a["symbol"]: a for a in alerts}
    assert by["BTC"]["status"] == "below" and by["BTC"]["breached"] is True
    assert by["ETH"]["status"] == "above" and by["ETH"]["breached"] is True
    assert by["VWCE"]["status"] == "in_band" and by["VWCE"]["breached"] is False
    # breaches sort ahead of non-breaches
    assert alerts[0]["breached"] and alerts[-1]["symbol"] == "VWCE"


def test_missing_quote_is_honest_not_fabricated():
    alerts = evaluate_watchlist([{"symbol": "xau", "low": 2000}], {})  # no quote
    assert alerts[0]["status"] == "no_quote" and alerts[0]["price"] is None
    assert alerts[0]["breached"] is False


def test_quotes_accepts_list_or_map():
    a_map = evaluate_watchlist([{"symbol": "btc", "low": 1}], {"BTC": 100})
    a_list = evaluate_watchlist([{"symbol": "btc", "low": 1}], [{"symbol": "BTC", "price": 100}])
    assert a_map[0]["price"] == 100 and a_list[0]["price"] == 100


def test_every_alert_and_brief_carries_the_disclaimer():
    alerts = evaluate_watchlist([{"symbol": "btc", "low": 1}], {"BTC": 2})
    assert all("not financial advice" in a["disclaimer"] for a in alerts)
    brief = daily_brief([{"symbol": "btc", "low": 1}], {"BTC": 2}, [])
    assert brief["disclaimer"] == DISCLAIMER and brief["snapshot"]["disclaimer"] == DISCLAIMER


# ── portfolio ──────────────────────────────────────────────────────────────────
def test_portfolio_net_worth_weights_and_allocation():
    snap = portfolio_snapshot([
        {"symbol": "btc", "qty": 0.5, "price": 58000, "kind": "crypto"},
        {"symbol": "vwce", "qty": 10, "price": 110, "kind": "etf"},
    ])
    assert snap["net_worth"] == 30100.0
    assert snap["by_kind"] == {"crypto": 29000.0, "etf": 1100.0}
    top = snap["positions"][0]
    assert top["symbol"] == "BTC" and 0.96 < top["weight"] < 0.97   # value-weighted, sorted desc


def test_portfolio_drops_unpriced_positions_never_guesses():
    snap = portfolio_snapshot([
        {"symbol": "btc", "qty": 1, "price": 100},
        {"symbol": "ghost", "qty": 5},                  # no price → dropped
        {"symbol": "", "qty": 1, "price": 1},           # no symbol → dropped
        "junk",
    ])
    assert snap["count"] == 1 and snap["net_worth"] == 100.0


def test_empty_brief_is_honest():
    b = daily_brief()
    assert b["headline"] == "no market data" and b["breached"] == 0


def test_brief_headline_counts_breaches():
    b = daily_brief(
        [{"symbol": "btc", "low": 60000}, {"symbol": "eth", "high": 4000}],
        {"BTC": 58000, "ETH": 4500},
        [{"symbol": "btc", "qty": 1, "price": 58000}],
    )
    assert b["breached"] == 2 and "2 breached" in b["headline"] and "net worth 58000" in b["headline"]


# ── governance rail: money never auto-moves (real policy + kernel, hermetic) ────
def _authorize(action):
    d = tempfile.mkdtemp(prefix="market-gov-")
    try:
        ks = KillSwitch(path=os.path.join(d, "kill.json"))  # isolated, not halted
        return authorize(action, kill_switch=ks, policy=AutonomyPolicy())
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_money_action_queued_readonly_monitoring_granted():
    scan = _authorize(Action(kind="market.monitor", title="monitor watchlist", scope="global"))
    trade = _authorize(Action(kind="trade.buy", title="buy BTC at market", scope="global"))
    transfer = _authorize(Action(kind="transfer.funds", title="transfer to broker", scope="global"))
    assert scan.verdict is Verdict.GRANT                # reading the market is free
    assert trade.verdict is Verdict.QUEUE               # moving money is held for approval
    assert transfer.verdict is Verdict.QUEUE
    assert "IRREVERSIBLE_OR_MONEY" in (trade.reason or "")


# ── the reality case promotes the finance capability to VERIFIED ───────────────
def teardown_function():
    cr.clear_verifications()
    cr._OVERRIDES.clear()


async def test_market_reality_case_present_and_passes():
    case = next((c for c in CASES if c.name == "market-money-action-queued"), None)
    assert case is not None, "the P3 money-governance reality case must be registered"
    assert case.capability_id == "plugin:balance" and case.live is False
    out = await run_reality([case], now="2026-06-28T00:00:00+00:00")
    assert out["passed"] == 1 and out["total"] == 1 and "plugin:balance" in out["promoted"]
