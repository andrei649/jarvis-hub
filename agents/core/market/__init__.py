"""market — P3 Market Intel + Finance pack (ORIZONT 24 Track P).

Offline, deterministic market intelligence over *provided* quotes/positions, with a
mandatory not-advice disclaimer and a money-never-auto-moves governance rail. See
:mod:`.analyze`.
"""

from .analyze import (
    DISCLAIMER,
    daily_brief,
    evaluate_watchlist,
    portfolio_snapshot,
)

__all__ = ["DISCLAIMER", "evaluate_watchlist", "portfolio_snapshot", "daily_brief"]
