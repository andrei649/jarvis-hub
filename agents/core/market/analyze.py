"""market/analyze.py — P3 Market Intel + Finance pack: offline, governed market intel.

ORIZONT 24 Track P (P3 — Market Intel + Finance). The concrete daily-utility surface:
evaluate a **watchlist** against provided quotes (band breaches → alerts), roll up a
**portfolio** from provided positions (net worth + allocation), and assemble a demoable
**daily brief**. Two non-negotiables make this honest:

* **Mandatory not-advice disclaimer.** Every alert and brief carries :data:`DISCLAIMER`.
  These are informational signals, never a recommendation to act.
* **Money never auto-moves.** This module only *reads/computes* — it proposes nothing
  executable. Acting on a signal (a trade/transfer) is a separate kernel action that the
  Action Kernel classifies ``IRREVERSIBLE_OR_MONEY`` → **QUEUE** (held for approval). The
  P3 reality case proves that rail end-to-end against the real policy + kernel.

Offline by design: it analyses the quotes/positions the caller hands it. *Live* market
data (a broker/quotes API, the `balance` plugin against ING/Libra) is owner-gated wiring —
this engine is the deterministic, hermetically-verifiable core.
"""

from __future__ import annotations

DISCLAIMER = (
    "Informational only — not financial advice. Figures derive from the data you provided; "
    "verify independently. Any trade or transfer requires your explicit approval."
)


def _num(x) -> float | None:
    """Best-effort float, or None (an absent/garbage quote must never become a fake price)."""
    try:
        if x is None or isinstance(x, bool):
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def _quote_map(quotes) -> dict[str, float]:
    """Normalise quotes — accept ``{SYM: price}`` or ``[{symbol, price}]`` — to upper-sym → price."""
    out: dict[str, float] = {}
    if isinstance(quotes, dict):
        items = quotes.items()
    elif isinstance(quotes, list):
        items = ((q.get("symbol"), q.get("price")) for q in quotes if isinstance(q, dict))
    else:
        items = ()
    for sym, price in items:
        s = str(sym or "").strip().upper()
        p = _num(price)
        if s and p is not None:
            out[s] = p
    return out


def evaluate_watchlist(watches, quotes) -> list[dict]:
    """Evaluate band rules against quotes → one alert per watch.

    A watch is ``{symbol, low?, high?, note?}``. Status is ``below`` / ``above`` /
    ``in_band`` against the provided quote, or ``no_quote`` when none was supplied (honest
    — never a fabricated price). Every alert carries the not-advice disclaimer.
    """
    qmap = _quote_map(quotes)
    alerts: list[dict] = []
    for w in watches or []:
        if not isinstance(w, dict):
            continue
        sym = str(w.get("symbol") or "").strip().upper()
        if not sym:
            continue
        low, high = _num(w.get("low")), _num(w.get("high"))
        price = qmap.get(sym)
        if price is None:
            status, msg = "no_quote", f"{sym}: no quote supplied"
        elif low is not None and price < low:
            status, msg = "below", f"{sym} {price:g} below {low:g}"
        elif high is not None and price > high:
            status, msg = "above", f"{sym} {price:g} above {high:g}"
        else:
            status, msg = "in_band", f"{sym} {price:g} within band"
        alerts.append({
            "symbol": sym, "price": price, "low": low, "high": high,
            "status": status, "breached": status in ("below", "above"),
            "message": msg, "note": str(w.get("note") or ""),
            "disclaimer": DISCLAIMER,
        })
    # breaches first, then by symbol — deterministic ordering
    alerts.sort(key=lambda a: (not a["breached"], a["symbol"]))
    return alerts


def portfolio_snapshot(positions) -> dict:
    """Roll up provided positions ``[{symbol, qty, price, kind?}]`` into a net-worth snapshot.

    Each position's value is ``qty * price`` (positions missing a numeric qty+price are
    dropped, not guessed). Returns net worth, per-position value + weight (share of net
    worth), and a by-kind allocation. Empty/zero → an honest empty snapshot.
    """
    rows: list[dict] = []
    for p in positions or []:
        if not isinstance(p, dict):
            continue
        sym = str(p.get("symbol") or "").strip().upper()
        qty, price = _num(p.get("qty")), _num(p.get("price"))
        if not sym or qty is None or price is None:
            continue
        rows.append({"symbol": sym, "kind": str(p.get("kind") or "other").lower(),
                     "qty": qty, "price": price, "value": round(qty * price, 2)})

    net_worth = round(sum(r["value"] for r in rows), 2)
    for r in rows:
        r["weight"] = round(r["value"] / net_worth, 4) if net_worth else 0.0
    by_kind: dict[str, float] = {}
    for r in rows:
        by_kind[r["kind"]] = round(by_kind.get(r["kind"], 0.0) + r["value"], 2)
    rows.sort(key=lambda r: (-r["value"], r["symbol"]))
    return {
        "net_worth": net_worth,
        "positions": rows,
        "by_kind": by_kind,
        "count": len(rows),
        "disclaimer": DISCLAIMER,
    }


def daily_brief(watches=None, quotes=None, positions=None) -> dict:
    """The demoable daily brief: watchlist alerts + portfolio snapshot + an honest headline.

    The headline a digest/agent can read aloud — how many alerts breached and the current
    net worth — always carrying the not-advice disclaimer. No input → "no market data".
    """
    alerts = evaluate_watchlist(watches or [], quotes or {})
    snap = portfolio_snapshot(positions or [])
    breached = sum(1 for a in alerts if a["breached"])
    if not alerts and not snap["count"]:
        headline = "no market data"
    else:
        headline = (
            f"{len(alerts)} watch(es) · {breached} breached · "
            f"net worth {snap['net_worth']:g}"
        )
    return {
        "headline": headline,
        "alerts": alerts,
        "snapshot": snap,
        "breached": breached,
        "disclaimer": DISCLAIMER,
    }
