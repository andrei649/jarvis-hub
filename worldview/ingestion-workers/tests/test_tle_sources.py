"""Tests for the TLE catalog sources (Celestrak + Space-Track) and the sensor registry."""

import asyncio

import httpx

from worldview_ingest.config import Settings
from worldview_ingest.tle.sensors import DEFAULT_SENSOR, sensor_for
from worldview_ingest.tle.sources import (
    CelestrakSource,
    SpaceTrackSource,
    build_source,
    parse_norad_ids,
)

# Two real TLEs: ISS (25544) + a second object (for filter tests).
TLE_TEXT = (
    "ISS (ZARYA)\n"
    "1 25544U 98067A   24001.50000000  .00016717  00000-0  10270-3 0  9007\n"
    "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.49514477 30000\n"
    "WORLDVIEW-3\n"
    "1 40115U 14048A   24001.50000000  .00000100  00000-0  00000-0 0  9990\n"
    "2 40115  97.8920 100.0000 0001000  90.0000 270.0000 14.84300000 40000\n"
)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_parse_norad_ids():
    assert parse_norad_ids("25544, 40115") == {25544, 40115}
    assert parse_norad_ids("") == set()


def test_sensor_registry_lookup():
    assert sensor_for(40115)[0] == "optical"  # WorldView-3, a real anchor
    assert sensor_for(99999) == DEFAULT_SENSOR  # unknown → default optical


def test_celestrak_group_url_and_parse():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, text=TLE_TEXT)

    src = CelestrakSource(Settings(tle_group="active"))

    async def go():
        async with _client(handler) as client:
            return await src.fetch(client)

    records = asyncio.run(go())
    assert "GROUP=active" in captured["url"] and "FORMAT=tle" in captured["url"]
    assert {r.norad_id for r in records} == {25544, 40115}


def test_celestrak_norad_filter():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=TLE_TEXT)

    src = CelestrakSource(Settings(tle_norad_ids="40115"))

    async def go():
        async with _client(handler) as client:
            return await src.fetch(client)

    records = asyncio.run(go())
    assert [r.norad_id for r in records] == [40115]  # filtered to the curated set


def test_spacetrack_login_then_query():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url)))
        if "ajaxauth/login" in str(request.url):
            return httpx.Response(200, text="", headers={"set-cookie": "chocolatechip=abc"})
        return httpx.Response(200, text=TLE_TEXT)

    src = SpaceTrackSource(
        Settings(tle_source="spacetrack", spacetrack_username="u", spacetrack_password="p",
                 tle_norad_ids="25544,40115")
    )

    async def go():
        async with _client(handler) as client:
            return await src.fetch(client)

    records = asyncio.run(go())
    assert calls[0][0] == "POST" and "ajaxauth/login" in calls[0][1]  # login first
    assert "/class/gp/NORAD_CAT_ID/25544,40115/format/tle" in calls[1][1]
    assert {r.norad_id for r in records} == {25544, 40115}


def test_spacetrack_without_creds_returns_empty():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not hit the network without credentials")

    src = SpaceTrackSource(Settings(tle_source="spacetrack"))

    async def go():
        async with _client(handler) as client:
            return await src.fetch(client)

    assert asyncio.run(go()) == []


def test_build_source_selects_by_config():
    assert build_source(Settings(tle_source="spacetrack")).name == "spacetrack"
    assert build_source(Settings(tle_source="celestrak")).name == "celestrak"
    assert build_source(Settings()).name == "celestrak"
