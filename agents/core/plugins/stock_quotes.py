"""
stock_quotes.py — Stark keyless stock/ETF/index quote reader.

Live end-to-end with no API key, the same posture as the weather and news plugins:
it fetches delayed quotes from Stooq's public CSV endpoint. Previously the Market
pack could only *score quotes the caller supplied* ("does not fetch"); this makes a
real quote feed available so an agent can answer "what's AAPL at?" for real. When
the feed is unreachable it degrades honestly (no fabricated prices) via the shared
``degradation`` helper.

Not advice: quotes are delayed and informational; acting on a signal stays a
governed Action-Kernel step. No key, no account, no PII leaves the machine — only
the ticker symbols are sent.
"""
import csv
import io
import logging
import re

from ..http_client import PluginHTTPClient
from ..resilience import resilient_call
from .degradation import degraded

logger = logging.getLogger("jarvis.plugins.stock_quotes")

# Stooq public CSV quote endpoint (keyless). f=sd2t2ohlcv → symbol,date,time,OHLC,volume.
_STOOQ_URL = "https://stooq.com/q/l/?s={symbols}&f=sd2t2ohlcv&h&e=csv"

# Uppercase words that look like tickers but almost never are, to cut false hits
# when extracting symbols from free text.
_NOT_TICKERS = {
    "A", "I", "AN", "AS", "AT", "BE", "BY", "DO", "GO", "IF", "IN", "IS", "IT", "ME",
    "MY", "NO", "OF", "ON", "OR", "SO", "TO", "UP", "US", "WE", "OK", "USA", "CEO",
    "CFO", "GDP", "AI", "ETF", "IPO", "PM", "AM", "EU", "UK", "THE", "AND", "FOR",
}


def normalize_symbol(symbol: str) -> str:
    """Map a display ticker to Stooq's symbol form (US stocks get a ``.us`` suffix)."""
    s = symbol.strip().lower().lstrip("$")
    if not s:
        return ""
    # Already market-qualified (aapl.us, ^spx, btc.v) or an index — leave it.
    if "." in s or s.startswith("^"):
        return s
    return f"{s}.us"


def display_symbol(stooq_symbol: str) -> str:
    """Inverse of :func:`normalize_symbol` for presenting results (AAPL.US → AAPL)."""
    s = stooq_symbol.strip().upper()
    return s[:-3] if s.endswith(".US") else s


def extract_symbols(text: str, limit: int = 8) -> list[str]:
    """Pull candidate tickers from free text: ``$AAPL`` cashtags first, then bare
    uppercase 1–5 letter tokens (minus obvious non-tickers). Order-preserving, deduped."""
    out: list[str] = []
    seen: set[str] = set()
    # $CASHTAGS (with optional market suffix) are unambiguous — take them first.
    for m in re.findall(r"\$([A-Za-z]{1,5}(?:\.[A-Za-z]{1,3})?)", text):
        u = m.upper()
        if u not in seen:
            seen.add(u)
            out.append(u)
    # Bare uppercase tokens as a fallback.
    for m in re.findall(r"\b[A-Z]{1,5}\b", text):
        if m in _NOT_TICKERS or m in seen:
            continue
        seen.add(m)
        out.append(m)
    return out[:limit]


def _parse_stooq_csv(text: str) -> tuple[dict[str, float], str]:
    """Parse a Stooq CSV response → ({DISPLAY_SYMBOL: close_price}, as_of).

    Rows whose close is ``N/D`` (unknown symbol / no data) are skipped. Returns an
    empty dict when nothing parseable is present.
    """
    quotes: dict[str, float] = {}
    as_of = ""
    reader = csv.DictReader(io.StringIO(text.strip()))
    for row in reader:
        close = (row.get("Close") or "").strip()
        sym = (row.get("Symbol") or "").strip()
        if not sym or close.upper() in ("", "N/D"):
            continue
        try:
            quotes[display_symbol(sym)] = float(close)
        except ValueError:
            continue
        date = (row.get("Date") or "").strip()
        time = (row.get("Time") or "").strip()
        if date and not as_of:
            as_of = f"{date} {time}".strip()
    return quotes, as_of


class StockQuotesPlugin:
    def __init__(self):
        self.client = PluginHTTPClient.for_plugin("stock-quotes")

    @resilient_call(
        max_retries=2,
        timeout=10.0,
        backoff_base=0.5,
        backoff_max=2.0,
        circuit_breaker_key="plugin:stock-quotes",
        circuit_breaker_threshold=3,
        metrics_agent_id="stark",
        metrics_backend="stooq.com",
    )
    async def get_quotes(self, symbols) -> dict:
        """Live delayed quotes for ``symbols`` (list or comma/space string).

        Returns ``{"quotes": {SYM: price}, "source": "stooq", "as_of": str,
        "missing": [...], "mock": False}``; degrades honestly (no prices invented)
        when the feed is unreachable or returns nothing.
        """
        if isinstance(symbols, str):
            requested = [s for s in re.split(r"[,\s]+", symbols) if s]
        else:
            requested = [str(s) for s in (symbols or []) if str(s).strip()]
        requested = [s.upper().lstrip("$") for s in requested]
        if not requested:
            return degraded({"quotes": {}, "missing": []},
                            reason="no ticker symbols supplied", needs=[])

        normalized = ",".join(normalize_symbol(s) for s in requested)
        url = _STOOQ_URL.format(symbols=normalized)
        try:
            resp = await self.client.get(url)
            resp.raise_for_status()
            quotes, as_of = _parse_stooq_csv(resp.text)
        except Exception as e:
            logger.warning("Stooq quote fetch failed: %s", e)
            return degraded({"quotes": {}, "missing": requested},
                            reason="live quotes feed unavailable", needs=[])

        if not quotes:
            return degraded({"quotes": {}, "missing": requested},
                            reason="no quotes returned for the requested symbols", needs=[])
        missing = [s for s in requested if display_symbol(normalize_symbol(s)) not in quotes]
        return {"quotes": quotes, "source": "stooq", "as_of": as_of,
                "missing": missing, "mock": False}

    async def get_summary(self, symbols) -> str:
        """One-line, human-readable quote line for agent replies (never advice)."""
        try:
            data = await self.get_quotes(symbols)
        except Exception:  # decorator timeout / circuit-breaker open → honest fallback
            return "Live quotes are unavailable right now."
        quotes = data.get("quotes") or {}
        if not quotes:
            return "Live quotes are unavailable right now."
        parts = ", ".join(f"{sym} {price:,.2f}" for sym, price in quotes.items())
        stamp = f" (stooq, {data['as_of']})" if data.get("as_of") else " (stooq)"
        return f"{parts}{stamp} — delayed, not advice."

    async def close(self):
        await self.client.close()
