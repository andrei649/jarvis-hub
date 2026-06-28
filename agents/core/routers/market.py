"""Market Intel + Finance pack (P3, Track P) — offline, governed market intelligence.

`POST /api/market/watchlist` evaluates band rules against provided quotes (breaches →
alerts, each with a mandatory not-advice disclaimer). `POST /api/market/brief` is the
demoable daily brief: watchlist alerts + a portfolio snapshot (net worth + allocation
from provided positions) + an honest headline.

Honest + offline: this *analyses* the quotes/positions you provide — it does not fetch,
and it never proposes an executable trade. Acting on a signal (a trade/transfer) is a
separate kernel action the Action Kernel classifies IRREVERSIBLE_OR_MONEY → QUEUE (held
for approval) — money never moves on its own. Live market/bank data (a quotes API, the
`balance` plugin against ING/Libra) is owner-gated wiring (`docs/OWNER_TASKS.md`).
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from agents.core.routers._deps import user_guard
from agents.core.web_helpers import nocache_json

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


class BriefBody(WatchlistBody):
    positions: list[Position] = Field(default_factory=list, max_length=1000)


@router.post("/api/market/watchlist", dependencies=[Depends(user_guard)])
async def market_watchlist(body: WatchlistBody):
    """Evaluate the watchlist against provided quotes → band-breach alerts (with disclaimer)."""
    from agents.core.market import evaluate_watchlist
    return nocache_json({"alerts": evaluate_watchlist([w.model_dump() for w in body.watches], body.quotes)})


@router.post("/api/market/brief", dependencies=[Depends(user_guard)])
async def market_brief(body: BriefBody):
    """The demoable daily brief: watchlist alerts + portfolio snapshot + headline (offline)."""
    from agents.core.market import daily_brief
    return nocache_json(daily_brief(
        [w.model_dump() for w in body.watches],
        body.quotes,
        [p.model_dump() for p in body.positions],
    ))
