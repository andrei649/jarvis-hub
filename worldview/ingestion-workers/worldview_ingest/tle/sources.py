"""TLE catalog source providers (Layer C).

`CelestrakSource` — fetch a GROUP catalog (one request), optionally filtered to a curated NORAD
set. `SpaceTrackSource` — authenticate (session login) and query the `gp` class by NORAD ids.
Both return parsed `TleRecord`s. Hosts must be reachable from the deployment (egress allowlist).
"""

from __future__ import annotations

import logging
from typing import Protocol

import httpx

from worldview_ingest.config import Settings
from worldview_ingest.tle.catalog import TleRecord, parse_tle_text

logger = logging.getLogger(__name__)

CELESTRAK_GP = "https://celestrak.org/NORAD/elements/gp.php"
SPACETRACK_LOGIN = "https://www.space-track.org/ajaxauth/login"
SPACETRACK_QUERY = "https://www.space-track.org/basicspacedata/query"


def parse_norad_ids(raw: str) -> set[int]:
    """Parse a comma-separated NORAD id list into a set (empty = no filter)."""
    return {int(p) for p in raw.split(",") if p.strip()}


class TleSource(Protocol):
    name: str

    async def fetch(self, client: httpx.AsyncClient) -> list[TleRecord]: ...


class CelestrakSource:
    name = "celestrak"

    def __init__(self, settings: Settings) -> None:
        self._group = settings.tle_group
        self._norad = parse_norad_ids(settings.tle_norad_ids)

    async def fetch(self, client: httpx.AsyncClient) -> list[TleRecord]:
        url = httpx.URL(CELESTRAK_GP, params={"GROUP": self._group, "FORMAT": "tle"})
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            records = list(parse_tle_text(resp.text))
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Celestrak fetch failed: %s", exc)
            return []
        if self._norad:
            records = [r for r in records if r.norad_id in self._norad]
        return records


class SpaceTrackSource:
    name = "spacetrack"

    def __init__(self, settings: Settings) -> None:
        self._user = settings.spacetrack_username
        self._password = settings.spacetrack_password
        self._norad = parse_norad_ids(settings.tle_norad_ids)

    def _query_url(self) -> str:
        # Latest elements for the curated NORAD set (or all, capped) in TLE format.
        selector = (
            f"/NORAD_CAT_ID/{','.join(str(n) for n in sorted(self._norad))}"
            if self._norad
            else ""
        )
        return f"{SPACETRACK_QUERY}/class/gp{selector}/format/tle"

    async def fetch(self, client: httpx.AsyncClient) -> list[TleRecord]:
        if not (self._user and self._password):
            logger.warning("Space-Track credentials missing")
            return []
        try:
            login = await client.post(
                SPACETRACK_LOGIN,
                data={"identity": self._user, "password": self._password},
            )
            login.raise_for_status()  # sets the session cookie on the client
            resp = await client.get(self._query_url())
            resp.raise_for_status()
            return list(parse_tle_text(resp.text))
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Space-Track fetch failed: %s", exc)
            return []


def build_source(settings: Settings) -> TleSource:
    """Construct the configured TLE source (`celestrak` default, `spacetrack` alternative)."""
    if settings.tle_source == "spacetrack":
        return SpaceTrackSource(settings)
    return CelestrakSource(settings)
