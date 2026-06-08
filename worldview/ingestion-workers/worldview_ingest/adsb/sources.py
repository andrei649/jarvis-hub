"""ADS-B source providers (Layer A).

`OpenSkySource` — OpenSky `/states/all` with OAuth2 client-credentials (the 2025+ auth model),
falling back to anonymous; optional viewport bbox to cut API credits; rate-limit aware.
`AdsbFiSource` — the free ADSB.fi opendata feed, centered on an AOI.

Both fetch a snapshot and return normalized envelopes. The source hosts must be reachable from
the deployment (egress allowlist) — see worldview/DEPLOY.md.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from worldview_ingest.adsb.normalize import (
    normalize_adsbfi_aircraft,
    normalize_opensky_state,
)
from worldview_ingest.config import Settings
from worldview_ingest.envelope import TelemetryEnvelope

OPENSKY_STATES_URL = "https://opensky-network.org/api/states/all"
OPENSKY_TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network/"
    "protocol/openid-connect/token"
)
ADSBFI_BASE = "https://opendata.adsb.fi/api/v2"


class RateLimited(Exception):
    """Raised when a source returns HTTP 429; carries an optional Retry-After (seconds)."""

    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__("rate limited")
        self.retry_after = retry_after


@dataclass
class FetchResult:
    src_time: float
    envelopes: list[TelemetryEnvelope] = field(default_factory=list)
    credits_remaining: int | None = None


class AdsbSource(Protocol):
    name: str

    async def fetch(self, client: httpx.AsyncClient) -> FetchResult: ...


class OpenSkyTokenManager:
    """OAuth2 client-credentials bearer token with in-memory caching + early (30s) refresh."""

    def __init__(self, client_id: str, client_secret: str) -> None:
        self._id = client_id
        self._secret = client_secret
        self._token: str | None = None
        self._expires_at: float = 0.0

    @property
    def anonymous(self) -> bool:
        return not (self._id and self._secret)

    async def bearer(self, client: httpx.AsyncClient) -> str | None:
        if self.anonymous:
            return None
        if self._token and time.time() < self._expires_at - 30:
            return self._token
        resp = await client.post(
            OPENSKY_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self._id,
                "client_secret": self._secret,
            },
        )
        resp.raise_for_status()
        body = resp.json()
        self._token = str(body["access_token"])
        self._expires_at = time.time() + float(body.get("expires_in", 1800))
        return self._token


class OpenSkySource:
    name = "opensky"

    def __init__(self, settings: Settings) -> None:
        self._bbox = _parse_bbox(settings.adsb_bbox)
        self._tokens = OpenSkyTokenManager(
            settings.opensky_client_id, settings.opensky_client_secret
        )

    def _url(self) -> httpx.URL:
        params: dict[str, float] = {}
        if self._bbox is not None:
            lamin, lomin, lamax, lomax = self._bbox
            params = {"lamin": lamin, "lomin": lomin, "lamax": lamax, "lomax": lomax}
        return httpx.URL(OPENSKY_STATES_URL, params=params)

    async def fetch(self, client: httpx.AsyncClient) -> FetchResult:
        headers: dict[str, str] = {}
        token = await self._tokens.bearer(client)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        resp = await client.get(self._url(), headers=headers)
        if resp.status_code == 429:
            raise RateLimited(_retry_after(resp))
        resp.raise_for_status()
        data = resp.json()
        src_time = float(data.get("time") or time.time())
        envelopes = [
            env
            for state in (data.get("states") or [])
            if (env := normalize_opensky_state(state, src_time)) is not None
        ]
        return FetchResult(src_time, envelopes, _int_header(resp, "x-rate-limit-remaining"))


class AdsbFiSource:
    name = "adsbfi"

    def __init__(self, settings: Settings) -> None:
        lat, lon = _parse_center(settings.adsb_center)
        self._url = f"{ADSBFI_BASE}/lat/{lat}/lon/{lon}/dist/{settings.adsb_radius_nm}"

    async def fetch(self, client: httpx.AsyncClient) -> FetchResult:
        resp = await client.get(self._url)
        if resp.status_code == 429:
            raise RateLimited(_retry_after(resp))
        resp.raise_for_status()
        data = resp.json()
        # ADSB.fi `now` is epoch milliseconds; per-aircraft `seen_pos` is seconds-ago.
        src_time = float(data.get("now") or time.time() * 1000.0) / 1000.0
        aircraft = data.get("ac") or data.get("aircraft") or []
        envelopes = [
            env
            for ac in aircraft
            if (env := normalize_adsbfi_aircraft(ac, src_time)) is not None
        ]
        return FetchResult(src_time, envelopes)


def build_source(settings: Settings) -> AdsbSource:
    """Construct the configured ADS-B source (`opensky` default, `adsbfi` alternative)."""
    if settings.adsb_source == "adsbfi":
        return AdsbFiSource(settings)
    return OpenSkySource(settings)


def _parse_bbox(raw: str) -> tuple[float, float, float, float] | None:
    if not raw.strip():
        return None
    parts = [float(p) for p in raw.split(",")]
    if len(parts) != 4:
        raise ValueError(f"ADSB_BBOX must be 'lamin,lomin,lamax,lomax', got {raw!r}")
    return parts[0], parts[1], parts[2], parts[3]


def _parse_center(raw: str) -> tuple[float, float]:
    parts = [float(p) for p in raw.split(",")]
    if len(parts) != 2:
        raise ValueError(f"ADSB_CENTER must be 'lat,lon', got {raw!r}")
    return parts[0], parts[1]


def _retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("retry-after")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _int_header(resp: httpx.Response, name: str) -> int | None:
    value = resp.headers.get(name)
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None
