"""Market Intel + Finance pack (P3, Track P) — offline, governed market intelligence.

`POST /api/market/watchlist` evaluates band rules against provided quotes (breaches →
alerts, each with a mandatory not-advice disclaimer). `POST /api/market/brief` is the
demoable daily brief: watchlist alerts + a portfolio snapshot (net worth + allocation
from provided positions) + an honest headline.

Honest by default: this *analyses* the quotes/positions you provide, and it never
proposes an executable trade. With `live: true` (DRA-21) it additionally fills the
symbols you did NOT price from the keyless `stock-quotes` plugin (delayed Stooq
closes) — caller-supplied quotes always win, and a symbol the feed cannot price
stays `no_quote` rather than getting an invented number; the response carries a
`quotes` provenance block (`live`/`source`/`as_of`, plus `degraded` when the feed
is unreachable or the plugin is disabled). Acting on a signal (a trade/transfer) is
a separate kernel action the Action Kernel classifies IRREVERSIBLE_OR_MONEY → QUEUE
(held for approval) — money never moves on its own. The bank/broker rail (the
`balance` plugin against ING/Libra, any executing broker API) remains owner-gated
credentials wiring (`docs/OWNER_TASKS.md`).
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from agents.core.app_state import get_orch
from agents.core.plugins.degradation import is_degraded
from agents.core.routers._deps import user_guard
from agents.core.web_helpers import logger, nocache_json

router = APIRouter(tags=["market"])


class Watch(BaseModel):
    symbol: str = Field(..., max_length=24)
    low: float | None = None
    high: float | None = None
    note: str = Field("", max_length=200)


class Position(BaseModel):
    symbol: str = Field(..., max_length=24)
    qty: float | None = None
    price: float | None = None
    kind: str = Field("other", max_length=24)         # crypto | etf | cash | stock | ...


class WatchlistBody(BaseModel):
    watches: list[Watch] = Field(default_factory=list, max_length=500)
    quotes: dict[str, float] = Field(default_factory=dict)   # {SYMBOL: price}
    # DRA-21 — opt in to filling the gaps from the keyless stock-quotes feed.
    # Default False keeps the pure-analyser contract for existing callers.
    live: bool = False


class BriefBody(WatchlistBody):
    positions: list[Position] = Field(default_factory=list, max_length=1000)


def _norm(symbol) -> str:
    return str(symbol or "").strip().upper().lstrip("$")


async def _resolve_quotes(body: WatchlistBody) -> tuple[dict[str, float], dict]:
    """Caller-supplied quotes win; `live=true` fills the gaps from the keyless
    stock-quotes plugin. Never invents a price — a symbol we cannot price stays
    absent, and evaluate_watchlist reports it as `no_quote`.

    Returns ``(quotes, provenance)``; the provenance block is what the response
    carries so a reader can tell a live delayed close from a value they pasted in.
    """
    quotes: dict[str, float] = {}
    for key, value in (body.quotes or {}).items():
        sym = _norm(key)
        if sym:
            quotes[sym] = float(value)

    missing: list[str] = []
    for watch in body.watches or []:
        sym = _norm(watch.symbol)
        if sym and sym not in quotes and sym not in missing:
            missing.append(sym)

    if not body.live or not missing:
        return quotes, {"live": False, "source": "provided"}

    orch = get_orch()
    plugin = orch.plugins.get("stock-quotes") if orch is not None else None
    allowed = False
    if plugin is not None and orch is not None:
        try:
            allowed = bool(orch.permission_gate.check_call("stock-quotes", "stark"))
        except Exception:
            allowed = False
    if plugin is None or not allowed:
        return quotes, {
            "live": False,
            "source": "provided",
            "missing": missing,
            "degraded": {
                "reason": "stock-quotes plugin unavailable or disabled",
                "needs": [],
            },
        }

    try:
        # get_quotes is wrapped in @resilient_call — a timeout or an open circuit
        # raises; treat that exactly as the plugin's own get_summary does.
        data = await plugin.get_quotes(missing)
    except Exception:
        logger.warning("live quote fetch failed — falling back to provided quotes",
                       exc_info=True)
        data = None
    if not isinstance(data, dict):
        data = None

    for sym, price in ((data or {}).get("quotes") or {}).items():
        try:
            quotes.setdefault(_norm(sym), float(price))
        except (TypeError, ValueError):
            continue

    live = bool(data is not None and not is_degraded(data))
    meta = {
        "live": live,
        "source": (data or {}).get("source", "provided") if live else "provided",
        "as_of": (data or {}).get("as_of", "") or "",
        "missing": (data or {}).get("missing", missing),
    }
    if data is None:
        meta["degraded"] = {"reason": "live quotes feed unavailable", "needs": []}
    elif isinstance(data.get("_degraded"), dict):
        meta["degraded"] = data["_degraded"]
    elif not live:
        meta["degraded"] = {"reason": "live quotes feed degraded", "needs": []}
    return quotes, meta


@router.post("/api/market/watchlist", dependencies=[Depends(user_guard)])
async def market_watchlist(body: WatchlistBody):
    """Evaluate the watchlist against provided (and, with `live`, fetched) quotes."""
    from agents.core.market import evaluate_watchlist
    quotes, meta = await _resolve_quotes(body)
    return nocache_json({
        "alerts": evaluate_watchlist([w.model_dump() for w in body.watches], quotes),
        "quotes": meta,
    })


@router.post("/api/market/brief", dependencies=[Depends(user_guard)])
async def market_brief(body: BriefBody):
    """The demoable daily brief: watchlist alerts + portfolio snapshot + headline."""
    from agents.core.market import daily_brief
    quotes, meta = await _resolve_quotes(body)
    return nocache_json({
        **daily_brief(
            [w.model_dump() for w in body.watches],
            quotes,
            [p.model_dump() for p in body.positions],
        ),
        "quotes": meta,
    })
