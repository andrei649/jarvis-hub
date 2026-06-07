"""Dark Vessel Detection (design doc §9.1).

A "dark vessel" stops transmitting AIS while inside a watched geofence (e.g. the Strait of
Hormuz) — the classic sanctions-evasion signature. This module is pure and stateful in
memory: feed it AIS positions, then `sweep(now)` to emit events for vessels gone silent
past their geofence's gap threshold, with a dead-reckoned extrapolated position.
"""

from __future__ import annotations

from dataclasses import dataclass

from worldview_ingest.geo import KNOTS_TO_KMH, destination_point, point_in_polygon


@dataclass(frozen=True)
class Geofence:
    id: int
    name: str
    dark_gap_seconds: int
    ring: list[tuple[float, float]]  # (lon, lat) vertices


@dataclass(frozen=True)
class DarkVesselEvent:
    mmsi: int
    geofence_id: int
    last_seen_ts: float
    last_lon: float
    last_lat: float
    gap_seconds: int
    extrapolated_lon: float
    extrapolated_lat: float
    status: str  # 'dark' | 'resumed'


@dataclass
class _Track:
    ts: float
    lon: float
    lat: float
    cog: float
    sog: float
    geofence_id: int
    flagged: bool = False


class DarkVesselDetector:
    def __init__(self, geofences: list[Geofence]) -> None:
        self._geofences = geofences
        self._by_id = {g.id: g for g in geofences}
        self._tracks: dict[int, _Track] = {}

    def _containing(self, lon: float, lat: float) -> Geofence | None:
        for g in self._geofences:
            if point_in_polygon(lon, lat, g.ring):
                return g
        return None

    def process(
        self, mmsi: int, lon: float, lat: float, ts: float, cog: float = 0.0, sog: float = 0.0
    ) -> DarkVesselEvent | None:
        """Record a position. Returns a 'resumed' event if a flagged vessel reappears."""
        prev = self._tracks.get(mmsi)
        resumed: DarkVesselEvent | None = None
        if prev is not None and prev.flagged:
            resumed = DarkVesselEvent(
                mmsi=mmsi,
                geofence_id=prev.geofence_id,
                last_seen_ts=prev.ts,
                last_lon=prev.lon,
                last_lat=prev.lat,
                gap_seconds=int(ts - prev.ts),
                extrapolated_lon=lon,
                extrapolated_lat=lat,
                status="resumed",
            )

        geofence = self._containing(lon, lat)
        if geofence is not None:
            self._tracks[mmsi] = _Track(ts, lon, lat, cog, sog, geofence.id)
        else:
            # Left every geofence; stop watching.
            self._tracks.pop(mmsi, None)
        return resumed

    def sweep(self, now: float) -> list[DarkVesselEvent]:
        """Emit a 'dark' event for each watched vessel silent past its gap threshold."""
        events: list[DarkVesselEvent] = []
        for mmsi, track in self._tracks.items():
            if track.flagged:
                continue
            geofence = self._by_id.get(track.geofence_id)
            if geofence is None:
                continue
            gap = now - track.ts
            if gap >= geofence.dark_gap_seconds:
                elon, elat = self._extrapolate(track, gap)
                events.append(
                    DarkVesselEvent(
                        mmsi=mmsi,
                        geofence_id=track.geofence_id,
                        last_seen_ts=track.ts,
                        last_lon=track.lon,
                        last_lat=track.lat,
                        gap_seconds=int(gap),
                        extrapolated_lon=elon,
                        extrapolated_lat=elat,
                        status="dark",
                    )
                )
                track.flagged = True
        return events

    @staticmethod
    def _extrapolate(track: _Track, gap_seconds: float) -> tuple[float, float]:
        """Dead-reckon the vessel's position from last course/speed over the silent gap."""
        distance_km = track.sog * KNOTS_TO_KMH * (gap_seconds / 3600.0)
        if distance_km <= 0.0:
            return track.lon, track.lat
        lat2, lon2 = destination_point(track.lat, track.lon, track.cog, distance_km)
        return lon2, lat2
