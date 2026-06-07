"""Tests for the ADS-B source providers (OpenSky + ADSB.fi) using mocked HTTP.

Real-shaped payloads exercise the full fetch -> normalize -> envelope path without live network;
the only unvalidated hop here is the actual call to the (egress-allowlisted) source host.
"""

import asyncio

import httpx
import pytest

from worldview_ingest.adsb.normalize import normalize_adsbfi_aircraft
from worldview_ingest.adsb.sources import (
    AdsbFiSource,
    OpenSkySource,
    RateLimited,
    build_source,
)
from worldview_ingest.config import Settings

# A real-shaped OpenSky /states/all response: a flying aircraft + one with no position (skip).
OPENSKY_PAYLOAD = {
    "time": 1717760000,
    "states": [
        ["4ca7b3", "RYR1234 ", "Ireland", 1717759998, 1717759999, -0.45, 51.47,
         11277.6, False, 231.5, 118.2, 0.0, None, 11582.4, "1000", False, 0],
        ["407a3e", None, "United Kingdom", 1717759990, 1717759995, None, None,
         None, True, 0, 0, 0, None, None, "7000", False, 0],
    ],
}

# A real-shaped ADSB.fi response: airborne civil + on-ground military + a positionless entry.
ADSBFI_PAYLOAD = {
    "now": 1717760000000,
    "ac": [
        {"hex": "4CA7B3", "flight": "RYR1234 ", "lat": 51.47, "lon": -0.45,
         "alt_baro": 37000, "gs": 231.5, "track": 118.2, "baro_rate": 0,
         "squawk": "1000", "seen_pos": 0.4, "dbFlags": 0},
        {"hex": "43c6db", "flight": "RRR2671 ", "lat": 51.5, "lon": -0.5,
         "alt_baro": "ground", "gs": 0, "track": 0, "squawk": "7000",
         "seen_pos": 1.2, "dbFlags": 1},
        {"hex": "", "lat": None, "lon": None},
    ],
}


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_normalize_adsbfi_civil_and_military():
    civ = normalize_adsbfi_aircraft(ADSBFI_PAYLOAD["ac"][0], src_time=1717760000.0)
    assert civ is not None
    assert civ.entity_id == "4ca7b3"  # lowercased
    assert abs(civ.ts - (1717760000.0 - 0.4)) < 1e-6  # now - seen_pos
    assert abs(civ.alt_m - 37000 * 0.3048) < 1e-3  # feet -> meters
    assert civ.payload["callsign"] == "RYR1234"
    assert civ.payload["is_military"] is False

    mil = normalize_adsbfi_aircraft(ADSBFI_PAYLOAD["ac"][1], src_time=1717760000.0)
    assert mil is not None
    assert mil.payload["on_ground"] is True
    assert mil.alt_m == 0.0
    assert mil.payload["is_military"] is True  # dbFlags bit 0

    assert normalize_adsbfi_aircraft(ADSBFI_PAYLOAD["ac"][2], src_time=1.0) is None


def test_opensky_source_anonymous_fetch():
    seen_headers = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        assert "states/all" in str(request.url)
        return httpx.Response(200, json=OPENSKY_PAYLOAD)

    src = OpenSkySource(Settings())  # no creds -> anonymous

    async def go():
        async with _client(handler) as client:
            return await src.fetch(client)

    result = asyncio.run(go())
    assert len(result.envelopes) == 1  # the positionless state is skipped
    assert result.envelopes[0].entity_id == "4ca7b3"
    assert result.envelopes[0].payload["callsign"] == "RYR1234"
    assert "authorization" not in {k.lower() for k in seen_headers}  # anonymous: no bearer


def test_opensky_oauth_token_fetched_cached_and_sent():
    token_calls = {"n": 0}
    auth_seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "openid-connect/token" in url:
            token_calls["n"] += 1
            return httpx.Response(200, json={"access_token": "tok123", "expires_in": 1800})
        auth_seen.append(request.headers.get("authorization"))
        return httpx.Response(200, json=OPENSKY_PAYLOAD)

    src = OpenSkySource(Settings(opensky_client_id="id", opensky_client_secret="sec"))

    async def go():
        async with _client(handler) as client:
            await src.fetch(client)
            await src.fetch(client)  # second call should reuse the cached token

    asyncio.run(go())
    assert token_calls["n"] == 1  # token cached across fetches
    assert auth_seen == ["Bearer tok123", "Bearer tok123"]


def test_opensky_bbox_in_url():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"time": 1, "states": []})

    src = OpenSkySource(Settings(adsb_bbox="45,0,52,12"))

    async def go():
        async with _client(handler) as client:
            await src.fetch(client)

    asyncio.run(go())
    assert "lamin=45" in captured["url"] and "lomax=12" in captured["url"]


def test_rate_limited_raises_with_retry_after():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"retry-after": "42"}, json={})

    src = OpenSkySource(Settings())

    async def go():
        async with _client(handler) as client:
            await src.fetch(client)

    with pytest.raises(RateLimited) as ei:
        asyncio.run(go())
    assert ei.value.retry_after == 42.0


def test_adsbfi_source_fetch():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "opendata.adsb.fi" in str(request.url)
        return httpx.Response(200, json=ADSBFI_PAYLOAD)

    src = AdsbFiSource(Settings(adsb_source="adsbfi", adsb_center="51.47,-0.45"))

    async def go():
        async with _client(handler) as client:
            return await src.fetch(client)

    result = asyncio.run(go())
    assert len(result.envelopes) == 2  # 2 positioned, 1 skipped
    assert {e.entity_id for e in result.envelopes} == {"4ca7b3", "43c6db"}


def test_build_source_selects_by_config():
    assert build_source(Settings(adsb_source="adsbfi")).name == "adsbfi"
    assert build_source(Settings(adsb_source="opensky")).name == "opensky"
    assert build_source(Settings()).name == "opensky"  # default
