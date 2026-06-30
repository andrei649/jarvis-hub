"""0.39 — persistent curated market watchlist (WatchlistStore).

Covers agents/core/market/watchlist_store.py: add/upsert (one entry per symbol,
symbol normalized), band validation (low>high rejected), get/remove, list
(alphabetical), clear, stats, durable persistence across instances, corrupt-file
safety, and bounded pruning. Pure/offline — an injected ``now`` keeps it deterministic.
"""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.market.watchlist_store import WatchlistStore  # noqa: E402


def _store(tmp_path, **kw):
    return WatchlistStore(tmp_path / "watchlist.json", **kw)


def test_add_shape_and_symbol_normalized(tmp_path):
    s = _store(tmp_path)
    r = s.add(symbol=" aapl ", low=150.0, high=200.0, note="core", now=1000.0)
    assert r["symbol"] == "AAPL"            # stripped + uppercased
    assert r["low"] == 150.0 and r["high"] == 200.0
    assert r["note"] == "core" and r["added_at"] == 1000.0


def test_add_upserts_one_per_symbol(tmp_path):
    s = _store(tmp_path)
    s.add(symbol="btc", low=50000.0, now=1.0)
    s.add(symbol="BTC", high=80000.0, now=2.0)        # same symbol → replaces
    assert len(s.list()) == 1
    cur = s.get("btc")
    assert cur["high"] == 80000.0 and cur["low"] is None and cur["added_at"] == 2.0


def test_add_requires_symbol_and_rejects_inverted_band(tmp_path):
    s = _store(tmp_path)
    with pytest.raises(ValueError):
        s.add(symbol="  ", now=1.0)
    with pytest.raises(ValueError):
        s.add(symbol="X", low=100.0, high=50.0, now=1.0)   # low > high


def test_get_remove(tmp_path):
    s = _store(tmp_path)
    s.add(symbol="eth", now=1.0)
    assert s.get("ETH")["symbol"] == "ETH"
    assert s.get("missing") is None
    assert s.remove("eth") is True
    assert s.get("eth") is None
    assert s.remove("eth") is False        # already gone


def test_list_is_alphabetical(tmp_path):
    s = _store(tmp_path)
    for sym in ("tsla", "aapl", "nvda"):
        s.add(symbol=sym, now=1.0)
    assert [w["symbol"] for w in s.list()] == ["AAPL", "NVDA", "TSLA"]


def test_clear_and_stats(tmp_path):
    s = _store(tmp_path)
    s.add(symbol="a", low=1.0, now=1.0)
    s.add(symbol="b", high=2.0, now=2.0)
    s.add(symbol="c", low=3.0, high=4.0, now=3.0)
    assert s.stats() == {"total": 3, "with_low": 2, "with_high": 2}
    assert s.clear() == 3
    assert s.list() == [] and s.stats()["total"] == 0


def test_persists_across_instances(tmp_path):
    s = _store(tmp_path)
    s.add(symbol="spy", note="index", now=1.0)
    s2 = WatchlistStore(tmp_path / "watchlist.json")
    assert s2.get("spy")["note"] == "index"


def test_corrupt_file_degrades_to_empty(tmp_path):
    p = tmp_path / "watchlist.json"
    p.write_text("not json {{{")
    s = WatchlistStore(p)
    assert s.stats()["total"] == 0
    r = s.add(symbol="x", now=1.0)         # still writable (overwrites the garbage)
    assert s.get(r["symbol"]) is not None


def test_bounded_prunes_oldest_first(tmp_path):
    s = _store(tmp_path, max_keep=3)
    for i in range(5):
        s.add(symbol=f"S{i}", now=float(i))
    kept = {w["symbol"] for w in s.list()}
    assert "S0" not in kept and "S1" not in kept
    assert {"S2", "S3", "S4"} <= kept
