"""DRA-21 — the market router can fill missing quotes from the keyless feed.

`/api/market/watchlist` and `/api/market/brief` only ever analysed quotes the
caller pasted in, while `StockQuotesPlugin` (keyless Stooq, already allowlisted)
sat unused by any route. These tests pin the opt-in `live: true` path: caller
quotes always win, only unpriced symbols are fetched, and an unreachable or
disabled feed degrades to `no_quote` rather than inventing a price.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.plugins.degradation import degraded  # noqa: E402


class FakeQuotes:
    def __init__(self, payload=None, raises=False):
        self.calls: list[list[str]] = []
        self._payload = payload if payload is not None else {
            "quotes": {"AAPL": 190.0},
            "source": "stooq",
            "as_of": "2026-08-31 21:00",
            "missing": [],
            "mock": False,
        }
        self._raises = raises

    async def get_quotes(self, symbols):
        self.calls.append(list(symbols))
        if self._raises:
            raise RuntimeError("circuit open")
        return self._payload


def _orch(plugin, *, allowed=True):
    return SimpleNamespace(
        plugins={"stock-quotes": plugin} if plugin is not None else {},
        permission_gate=SimpleNamespace(check_call=lambda *a, **k: allowed),
    )


@pytest.fixture
def client():
    from agents.web import app
    with TestClient(app) as c:
        yield c


def _bind(monkeypatch, orch):
    from agents import web
    monkeypatch.setattr(web, "orch", orch, raising=False)


def test_live_flag_fills_missing_quote_from_the_plugin(client, monkeypatch):
    plugin = FakeQuotes()
    _bind(monkeypatch, _orch(plugin))

    body = client.post("/api/market/watchlist", json={
        "watches": [{"symbol": "AAPL", "low": 200}],
        "live": True,
    }).json()

    assert body["alerts"][0]["status"] == "below"
    assert body["alerts"][0]["price"] == 190.0
    assert body["quotes"]["live"] is True
    assert body["quotes"]["source"] == "stooq"
    assert body["quotes"]["as_of"] == "2026-08-31 21:00"
    # only the unpriced symbols are fetched
    assert plugin.calls == [["AAPL"]]


def test_caller_supplied_quotes_win_and_short_circuit_the_fetch(client, monkeypatch):
    plugin = FakeQuotes()
    _bind(monkeypatch, _orch(plugin))

    body = client.post("/api/market/watchlist", json={
        "watches": [{"symbol": "AAPL", "low": 200}],
        "quotes": {"AAPL": 150.0},
        "live": True,
    }).json()

    assert plugin.calls == []
    assert body["alerts"][0]["price"] == 150.0
    assert body["quotes"]["live"] is False
    assert body["quotes"]["source"] == "provided"


def test_default_stays_offline(client, monkeypatch):
    plugin = FakeQuotes()
    _bind(monkeypatch, _orch(plugin))

    body = client.post("/api/market/watchlist", json={
        "watches": [{"symbol": "AAPL", "low": 200}],
    }).json()

    assert plugin.calls == []
    assert body["alerts"][0]["status"] == "no_quote"
    assert body["alerts"][0]["price"] is None
    assert body["quotes"]["live"] is False


@pytest.mark.parametrize("case", ["denied", "raises", "degraded", "absent"])
def test_unavailable_feed_degrades_without_inventing_a_price(client, monkeypatch, case):
    if case == "denied":
        orch = _orch(FakeQuotes(), allowed=False)
    elif case == "raises":
        orch = _orch(FakeQuotes(raises=True))
    elif case == "degraded":
        orch = _orch(FakeQuotes(degraded({"quotes": {}, "missing": ["AAPL"]},
                                         reason="live quotes feed unavailable")))
    else:
        orch = _orch(None)
    _bind(monkeypatch, orch)

    resp = client.post("/api/market/watchlist", json={
        "watches": [{"symbol": "AAPL", "low": 200}],
        "live": True,
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["alerts"][0]["status"] == "no_quote"
    assert body["alerts"][0]["price"] is None
    assert body["quotes"]["live"] is False
    assert body["quotes"].get("degraded", {}).get("reason")


def test_brief_honours_live_and_keeps_the_disclaimer(client, monkeypatch):
    plugin = FakeQuotes()
    _bind(monkeypatch, _orch(plugin))

    body = client.post("/api/market/brief", json={
        "watches": [{"symbol": "AAPL", "low": 200}],
        "positions": [{"symbol": "AAPL", "qty": 2, "price": 190.0}],
        "live": True,
    }).json()

    assert body["breached"] == 1
    assert "1 breached" in body["headline"]
    assert body["disclaimer"]
    assert body["quotes"]["source"] == "stooq"
