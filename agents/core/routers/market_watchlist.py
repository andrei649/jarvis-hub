"""Persistent curated market watchlist (0.39) — the saved-watchlist CRUD surface.

`routers/market.py` evaluates band rules against quotes you *provide* each request;
this persists the watchlist itself so the owner curates it once. Kept in its own
module (not folded into `market.py`) so the two concerns stay separable.

Read-mostly + offline: it holds `{symbol, low, high, note}` entries only — no quotes
are fetched and no trade is ever proposed (acting on a signal stays a kernel-gated,
approval-held action; live quotes / bank data are owner-gated wiring).
"""

import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from agents.core.routers._deps import user_guard
from agents.core.web_helpers import error_json, nocache_json

router = APIRouter(tags=["market"])


class SaveWatchBody(BaseModel):
    symbol: str = Field(..., max_length=24)
    low: float | None = None
    high: float | None = None
    note: str = Field("", max_length=200)


@router.get("/api/market/watchlist/saved", dependencies=[Depends(user_guard)])
async def market_watchlist_saved():
    """The curated, persisted watchlist + stats (symbols/bands the owner saved once)."""
    from agents.core.market.watchlist_store import WatchlistStore
    s = WatchlistStore()
    return nocache_json({"watches": s.list(), "stats": s.stats()})


@router.post("/api/market/watchlist/saved", dependencies=[Depends(user_guard)])
async def market_watchlist_save(body: SaveWatchBody):
    """Add/upsert a symbol in the curated watchlist (one entry per symbol)."""
    from agents.core.market.watchlist_store import WatchlistStore
    try:
        item = WatchlistStore().add(symbol=body.symbol, low=body.low, high=body.high,
                                    note=body.note, now=time.time())
    except ValueError as e:
        # CWE-209: never echo the raw exception text back to the client. error_json
        # logs the full detail server-side and returns only this static message.
        return error_json(
            e, 422,
            "invalid watch: symbol is required and low must not exceed high",
            extra={"ok": False},
        )
    return nocache_json({"ok": True, "watch": item})


@router.delete("/api/market/watchlist/saved/{symbol}", dependencies=[Depends(user_guard)])
async def market_watchlist_remove(symbol: str):
    """Remove a symbol from the curated watchlist."""
    from agents.core.market.watchlist_store import WatchlistStore
    return nocache_json({"ok": True, "removed": WatchlistStore().remove(symbol)})
