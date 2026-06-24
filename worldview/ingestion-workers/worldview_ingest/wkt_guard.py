"""AUD-12 (F12): bounds + sanity guards for untrusted geo coordinates.

WKT is built by string-formatting coordinates straight into the envelope's
``geom_wkt`` (``wkt.py``), from data that originates in external OSINT feeds
(GeoJSON events, NOTAMs, GPS-jamming cells). Without validation a hostile or
malformed coordinate could inject text into the WKT (and the downstream SQL that
consumes it), emit a non-finite value, or blow memory with a giant ring.

These guards coerce every coordinate to a finite WGS84-bounded float and cap the
vertex count *before* anything is formatted. They are pure and dependency-free.
"""

from __future__ import annotations

import math

# WGS84 valid ranges.
LON_MIN, LON_MAX = -180.0, 180.0
LAT_MIN, LAT_MAX = -90.0, 90.0

# A single ingested geometry should never carry more than this many vertices —
# the operational feeds (events / NOTAMs / jamming cells) are simple polygons.
# A larger ring is almost certainly malformed or hostile (multi-MB WKT → DoS).
MAX_VERTICES = 10_000


class WktBoundsError(ValueError):
    """An untrusted coordinate failed float-coercion or a bounds / size check."""


def coerce_coord(lon: object, lat: object) -> tuple[float, float]:
    """Coerce ``(lon, lat)`` to finite floats inside WGS84 bounds.

    Raises :class:`WktBoundsError` for a non-numeric, non-finite (NaN/inf), or
    out-of-range coordinate — so a hostile value can never reach the WKT string.
    """
    try:
        flon = float(lon)
        flat = float(lat)
    except (TypeError, ValueError) as exc:
        raise WktBoundsError(f"non-numeric coordinate: {lon!r}, {lat!r}") from exc
    if not (math.isfinite(flon) and math.isfinite(flat)):
        raise WktBoundsError(f"non-finite coordinate: {flon!r}, {flat!r}")
    if not (LON_MIN <= flon <= LON_MAX and LAT_MIN <= flat <= LAT_MAX):
        raise WktBoundsError(f"coordinate out of WGS84 range: lon={flon}, lat={flat}")
    return flon, flat


def check_vertex_count(n: int) -> None:
    """Raise :class:`WktBoundsError` if a ring / geometry exceeds ``MAX_VERTICES``."""
    if n > MAX_VERTICES:
        raise WktBoundsError(f"too many vertices: {n} > {MAX_VERTICES}")


def format_coord(value: float) -> str:
    """Render a validated coordinate: an integral value without a trailing ``.0``
    (so ``55.0`` → ``"55"``), other values via ``repr`` (full precision, no
    scientific notation at coordinate magnitudes)."""
    return str(int(value)) if value.is_integer() else repr(value)
