"""Synthetic ``TelemetryEnvelope`` generation for the load-test rig (ticket H19.1.6).

Pure and deterministic: given an entity count, a layer (domain), a tick time and a
seeded RNG, produce valid :class:`~worldview_ingest.envelope.TelemetryEnvelope`
objects whose identifiers and geometry are realistic for the layer and lie within a
bounding box. There is NO I/O and NO wall-clock read — the caller passes the tick
``ts`` and the RNG, so a fixed seed yields byte-identical output (the tests rely on
this).

Design choices
--------------
* **Stable entities.** A run simulates a fixed fleet of ``count`` entities. Each
  entity's *identity* (icao24 / mmsi / norad / sensor id) is derived from its index
  via a seeded permutation, so entity *i* keeps the same id across ticks (a track),
  which is what makes the as-of-T ``/history`` query meaningful.
* **Per-tick jitter.** Position drifts a little each tick (a seeded walk anchored on
  a per-entity home point) so successive ticks differ but stay inside the bbox.
* **Monotonic ts.** Every envelope's ``ts`` equals the tick time, so a sequence of
  ticks produces non-decreasing timestamps — the rig pumps a monotonic window the
  ``/history`` as-of-T probe then samples within.

The bbox is ``(lon_min, lat_min, lon_max, lat_max)`` (GeoJSON axis order, lon-first),
matching the backend ``/history?bbox=`` contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from random import Random

from worldview_ingest.envelope import Domain, TelemetryEnvelope

# A default AOI bbox around the Strait of Hormuz (lon_min, lat_min, lon_max, lat_max),
# matching the deployment's primary AOI used elsewhere in the package.
DEFAULT_BBOX: tuple[float, float, float, float] = (54.0, 24.0, 58.0, 28.0)

# Per-layer synthetic source label (kept distinct from the live source names).
_LAYER_SOURCE: dict[Domain, str] = {
    "adsb": "loadtest-adsb",
    "ais": "loadtest-ais",
    "tle": "loadtest-tle",
    "ew": "loadtest-ew",
    "context": "loadtest-context",
}

# How far (in bbox-fraction) an entity may wander from its home point per tick.
_JITTER_FRAC = 0.02


@dataclass(frozen=True)
class Bbox:
    """A lon/lat bounding box in GeoJSON axis order (lon-first)."""

    lon_min: float
    lat_min: float
    lon_max: float
    lat_max: float

    def __post_init__(self) -> None:
        if self.lon_min >= self.lon_max:
            raise ValueError(f"lon_min must be < lon_max, got {self.lon_min}, {self.lon_max}")
        if self.lat_min >= self.lat_max:
            raise ValueError(f"lat_min must be < lat_max, got {self.lat_min}, {self.lat_max}")

    @classmethod
    def from_tuple(cls, raw: tuple[float, float, float, float]) -> Bbox:
        return cls(raw[0], raw[1], raw[2], raw[3])

    def contains(self, lon: float, lat: float) -> bool:
        """Whether ``(lon, lat)`` lies within (inclusive) the box."""
        return self.lon_min <= lon <= self.lon_max and self.lat_min <= lat <= self.lat_max

    def clamp(self, lon: float, lat: float) -> tuple[float, float]:
        """Clamp a point back into the box (used after jitter)."""
        clon = min(max(lon, self.lon_min), self.lon_max)
        clat = min(max(lat, self.lat_min), self.lat_max)
        return clon, clat

    def as_query(self) -> str:
        """Render as the backend ``bbox=`` query value (lon_min,lat_min,lon_max,lat_max)."""
        return f"{self.lon_min},{self.lat_min},{self.lon_max},{self.lat_max}"


def _entity_id(layer: Domain, index: int) -> str:
    """A realistic, stable identifier for entity ``index`` in ``layer``.

    Deterministic from the index alone (no RNG) so an entity keeps its id across ticks
    and across runs — that stability is what makes a "track" queryable as-of-T.
    """
    if layer == "adsb":
        # ICAO24: 6 lowercase hex digits (24-bit address space).
        return f"{index & 0xFFFFFF:06x}"
    if layer == "ais":
        # MMSI: 9 digits; keep it in the valid 200_000_000–799_999_999 range.
        return str(200_000_000 + (index % 600_000_000))
    if layer == "tle":
        # NORAD catalog id: a 1–5 digit integer, offset into a plausible range.
        return str(10000 + (index % 89999))
    if layer == "ew":
        # EW grid / emitter id.
        return f"ew-{index:06d}"
    # context
    return f"ctx-{index:06d}"


def _home_point(rng: Random, bbox: Bbox) -> tuple[float, float]:
    """A uniformly random home point inside the bbox (drawn from the seeded RNG)."""
    lon = rng.uniform(bbox.lon_min, bbox.lon_max)
    lat = rng.uniform(bbox.lat_min, bbox.lat_max)
    return lon, lat


def generate_tick(
    *,
    count: int,
    layer: Domain,
    ts: float,
    rng: Random,
    bbox: Bbox | None = None,
    ingested_at: float | None = None,
) -> list[TelemetryEnvelope]:
    """Generate ``count`` synthetic envelopes for ``layer`` stamped at tick ``ts``.

    Deterministic for a fixed ``rng`` state: drawing from the injected RNG only, so a
    seeded ``Random`` reproduces the exact batch. Every envelope:

    * has ``domain == layer`` and a synthetic per-layer ``source``;
    * has a realistic, *stable* ``entity_id`` (icao24 / mmsi / norad / …) derived from
      its index, so entity *i* is the same track every tick;
    * has ``lon``/``lat`` inside ``bbox`` (jittered around a per-entity home point);
    * has ``ts`` exactly equal to the tick time (so a tick sequence is monotonic);
    * sets ``ingested_at`` to the supplied value (default: the tick ``ts``) so nothing
      reads the wall clock.

    ``count`` must be >= 0; 0 yields an empty list (a clean no-op tick).
    """
    if count < 0:
        raise ValueError(f"count must be >= 0, got {count}")
    box = bbox if bbox is not None else Bbox.from_tuple(DEFAULT_BBOX)
    stamp = ts if ingested_at is None else ingested_at
    source = _LAYER_SOURCE[layer]

    lon_span = box.lon_max - box.lon_min
    lat_span = box.lat_max - box.lat_min
    lon_jitter = lon_span * _JITTER_FRAC
    lat_jitter = lat_span * _JITTER_FRAC

    envelopes: list[TelemetryEnvelope] = []
    for index in range(count):
        home_lon, home_lat = _home_point(rng, box)
        lon = home_lon + rng.uniform(-lon_jitter, lon_jitter)
        lat = home_lat + rng.uniform(-lat_jitter, lat_jitter)
        lon, lat = box.clamp(lon, lat)

        alt_m: float | None
        if layer == "adsb":
            alt_m = rng.uniform(0.0, 12_000.0)
        elif layer == "tle":
            alt_m = rng.uniform(400_000.0, 800_000.0)
        else:
            alt_m = None

        envelopes.append(
            TelemetryEnvelope(
                domain=layer,
                source=source,
                entity_id=_entity_id(layer, index),
                ts=ts,
                ingested_at=stamp,
                lon=lon,
                lat=lat,
                alt_m=alt_m,
                payload={"synthetic": True, "idx": index},
            )
        )
    return envelopes
