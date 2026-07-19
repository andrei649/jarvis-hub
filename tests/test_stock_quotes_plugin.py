"""
tests/test_stock_quotes_plugin.py — keyless Stooq stock-quotes plugin.

The third keyless LIVE plugin alongside weather + news: it turns the Market pack's
"does not fetch" into a real quote feed. Offline — the HTTP call is mocked; parsing,
symbol handling, honest degradation, and the egress manifest are all asserted.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

from unittest.mock import AsyncMock

import httpx

from agents.core.plugin_gate import NetworkAccess, PermissionGate
from agents.core.plugins.degradation import is_degraded
from agents.core.plugins.stock_quotes import (
    StockQuotesPlugin,
    _parse_stooq_csv,
    display_symbol,
    extract_symbols,
    normalize_symbol,
)

_CSV = (
    "Symbol,Date,Time,Open,High,Low,Close,Volume\n"
    "AAPL.US,2026-07-18,22:00:04,210.5,212.0,209.8,211.20,50000000\n"
    "MSFT.US,2026-07-18,22:00:04,404,406,403,405.10,20000000\n"
    "ZZZZ.US,2026-07-18,22:00:04,N/D,N/D,N/D,N/D,0\n"
)


def _resp(text: str, status: int = 200) -> httpx.Response:
    # raise_for_status() needs an associated request instance.
    return httpx.Response(status_code=status, content=text.encode(),
                          request=httpx.Request("GET", "https://stooq.com/q/l/"))


# ── pure helpers ────────────────────────────────────────────────────────────

class TestSymbolHelpers:
    def test_normalize_defaults_to_us(self):
        assert normalize_symbol("AAPL") == "aapl.us"
        assert normalize_symbol("$msft") == "msft.us"

    def test_normalize_keeps_qualified(self):
        assert normalize_symbol("^spx") == "^spx"
        assert normalize_symbol("BTC.V") == "btc.v"
        assert normalize_symbol("  ") == ""

    def test_display_strips_us(self):
        assert display_symbol("AAPL.US") == "AAPL"
        assert display_symbol("^SPX") == "^SPX"

    def test_extract_prefers_cashtags_and_skips_stopwords(self):
        syms = extract_symbols("should I buy $AAPL or MSFT? the USA CEO said the ETF is fine")
        assert syms[0] == "AAPL"          # cashtag first
        assert "MSFT" in syms
        assert "USA" not in syms and "CEO" not in syms and "ETF" not in syms

    def test_extract_dedupes_and_limits(self):
        assert extract_symbols("AAPL AAPL AAPL") == ["AAPL"]
        many = "ABC DEF GHI JKL MNO PQR STU VWX"   # 8 valid 3-letter tickers
        assert len(extract_symbols(many, limit=5)) == 5


class TestParse:
    def test_parse_skips_nd_rows(self):
        quotes, as_of = _parse_stooq_csv(_CSV)
        assert quotes == {"AAPL": 211.20, "MSFT": 405.10}   # ZZZZ (N/D) dropped
        assert as_of == "2026-07-18 22:00:04"

    def test_parse_empty(self):
        quotes, as_of = _parse_stooq_csv("Symbol,Date,Time,Open,High,Low,Close,Volume\n")
        assert quotes == {} and as_of == ""


# ── get_quotes / get_summary (mocked HTTP) ──────────────────────────────────

class TestGetQuotes:
    async def test_live_quotes(self):
        p = StockQuotesPlugin()
        p.client.get = AsyncMock(return_value=_resp(_CSV))
        out = await p.get_quotes("AAPL, MSFT, ZZZZ")
        assert out["mock"] is False and out["source"] == "stooq"
        assert out["quotes"] == {"AAPL": 211.20, "MSFT": 405.10}
        assert out["missing"] == ["ZZZZ"]                    # N/D → reported missing
        assert out["as_of"] == "2026-07-18 22:00:04"
        await p.close()

    async def test_accepts_list(self):
        p = StockQuotesPlugin()
        p.client.get = AsyncMock(return_value=_resp(_CSV))
        out = await p.get_quotes(["aapl", "$msft"])
        assert set(out["quotes"]) == {"AAPL", "MSFT"}
        await p.close()

    async def test_no_symbols_degrades(self):
        p = StockQuotesPlugin()
        out = await p.get_quotes("")
        assert is_degraded(out) is True and out["quotes"] == {}
        assert out["_degraded"]["reason"]
        await p.close()

    async def test_fetch_failure_degrades(self):
        p = StockQuotesPlugin()
        p.client.get = AsyncMock(side_effect=httpx.ConnectError("boom"))
        out = await p.get_quotes("AAPL")
        assert is_degraded(out) is True and out["quotes"] == {}
        assert out["missing"] == ["AAPL"]
        await p.close()

    async def test_no_data_degrades(self):
        p = StockQuotesPlugin()
        p.client.get = AsyncMock(return_value=_resp(
            "Symbol,Date,Time,Open,High,Low,Close,Volume\nAAPL.US,2026-07-18,22:00,N/D,N/D,N/D,N/D,0\n"))
        out = await p.get_quotes("AAPL")
        assert is_degraded(out) is True
        await p.close()

    async def test_summary_live_and_degraded(self):
        p = StockQuotesPlugin()
        p.client.get = AsyncMock(return_value=_resp(_CSV))
        s = await p.get_summary("AAPL MSFT")
        assert "AAPL 211.20" in s and "not advice" in s.lower()

        p.client.get = AsyncMock(side_effect=httpx.ConnectError("boom"))
        s2 = await p.get_summary("AAPL")
        assert "unavailable" in s2.lower()
        await p.close()


# ── governance: registered + egress-restricted ──────────────────────────────

class TestManifest:
    def test_registered_with_restricted_egress(self):
        gate = PermissionGate()
        assert "stock-quotes" in gate.plugins
        m = gate.plugins["stock-quotes"]
        assert m.network_access == NetworkAccess.RESTRICTED
        assert "stooq.com" in m.allowed_domains
        # keyless → served to any agent (like weather/news)
        assert gate.check_call("stock-quotes", "stark") is True
