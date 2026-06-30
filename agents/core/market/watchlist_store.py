"""watchlist_store.py — 0.39: a persistent, curated market watchlist.

``routers/market.py`` already *evaluates* band rules against quotes you pass in each
request (``evaluate_watchlist`` / ``daily_brief``), but the watchlist itself was
stateless — the caller had to resend every symbol + band each time. This stores it:
a small list of ``{symbol, low, high, note}`` watches the owner curates once, that
the brief/alerts can then run against.

Design mirrors the 0.34/0.37/0.46 stores: a single **bounded, atomically-written,
corrupt/missing-file-safe** JSON array. One entry per symbol (upsert, symbol upper-
cased). Pure storage — it holds no quotes and proposes no trades; acting on a signal
stays a kernel-gated, approval-held action (see ``routers/market.py``). Live quotes /
bank data remain owner-gated wiring.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path

from agents.core.paths import data_path

_DEFAULT_FILE = data_path("market") / "watchlist.json"
_DEFAULT_MAX_KEEP = 500


def _norm_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


class WatchlistStore:
    """Bounded, atomically-written JSON store of curated watchlist entries."""

    def __init__(self, path: Path | str | None = None, *, max_keep: int = _DEFAULT_MAX_KEEP) -> None:
        self._path = Path(path) if path is not None else _DEFAULT_FILE
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._max_keep = max(1, int(max_keep))

    # ── persistence (mirrors the 0.34/0.37/0.46 stores) ───────────────────────
    def _read(self) -> list[dict]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError, OSError):
            return []
        return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []

    def _write_atomic(self, items: list[dict]) -> None:
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(items, fh, ensure_ascii=False)
            os.replace(tmp, self._path)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    # ── api ────────────────────────────────────────────────────────────────────
    def add(
        self,
        *,
        symbol: str,
        now: float,
        low: float | None = None,
        high: float | None = None,
        note: str = "",
    ) -> dict:
        """Upsert one watch (one entry per symbol). ``now`` is the caller's clock
        (injectable for tests). Raises ``ValueError`` for an empty symbol; raises
        ``ValueError`` if ``low``/``high`` are both set and inverted (low > high)."""
        sym = _norm_symbol(symbol)
        if not sym:
            raise ValueError("symbol is required")
        lo = float(low) if low is not None else None
        hi = float(high) if high is not None else None
        if lo is not None and hi is not None and lo > hi:
            raise ValueError(f"low ({lo}) must not exceed high ({hi})")
        item = {
            "symbol": sym,
            "low": lo,
            "high": hi,
            "note": str(note),
            "added_at": float(now),
        }
        items = [r for r in self._read() if _norm_symbol(r.get("symbol", "")) != sym]
        items.append(item)
        # bound the watchlist: keep the most recently added.
        if len(items) > self._max_keep:
            items.sort(key=lambda r: float(r.get("added_at", 0)))
            items = items[-self._max_keep:]
        self._write_atomic(items)
        return dict(item)

    def remove(self, symbol: str) -> bool:
        """Drop a symbol from the watchlist. True if it existed."""
        sym = _norm_symbol(symbol)
        items = self._read()
        kept = [r for r in items if _norm_symbol(r.get("symbol", "")) != sym]
        if len(kept) == len(items):
            return False
        self._write_atomic(kept)
        return True

    def get(self, symbol: str) -> dict | None:
        sym = _norm_symbol(symbol)
        for r in self._read():
            if _norm_symbol(r.get("symbol", "")) == sym:
                return dict(r)
        return None

    def list(self) -> list[dict]:
        """Every watch, alphabetical by symbol (a stable, predictable order)."""
        items = [dict(r) for r in self._read()]
        items.sort(key=lambda r: _norm_symbol(r.get("symbol", "")))
        return items

    def clear(self) -> int:
        """Drop every watch. Returns how many were removed."""
        n = len(self._read())
        if n:
            self._write_atomic([])
        return n

    def stats(self) -> dict:
        """Total + how many carry a low / high band (for an at-a-glance view)."""
        items = self._read()
        return {
            "total": len(items),
            "with_low": sum(1 for r in items if r.get("low") is not None),
            "with_high": sum(1 for r in items if r.get("high") is not None),
        }
