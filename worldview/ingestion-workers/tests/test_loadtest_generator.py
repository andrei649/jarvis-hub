"""Tests for the synthetic envelope generator (ticket H19.1.6).

Pure/deterministic: a seeded ``Random`` + an injected tick ``ts`` reproduce the batch
exactly. Covers determinism, valid envelopes per layer, stable entity ids across ticks,
monotonic ts across a tick sequence, and that positions stay inside the bbox.
"""

from __future__ import annotations

from random import Random

import pytest

from worldview_ingest.loadtest.generator import (
    DEFAULT_BBOX,
    Bbox,
    generate_tick,
)

T0 = 1_700_000_000.0
LAYERS = ("adsb", "ais", "tle", "ew", "context")


def _box() -> Bbox:
    return Bbox.from_tuple(DEFAULT_BBOX)


def test_count_and_domain_and_source() -> None:
    """generate_tick yields exactly `count` envelopes of the requested layer."""
    for layer in LAYERS:
        envs = generate_tick(count=7, layer=layer, ts=T0, rng=Random(1), bbox=_box())
        assert len(envs) == 7
        assert all(e.domain == layer for e in envs)
        assert all(e.source == f"loadtest-{layer}" for e in envs)


def test_zero_count_is_empty() -> None:
    """count=0 yields a clean empty tick."""
    assert generate_tick(count=0, layer="adsb", ts=T0, rng=Random(1)) == []


def test_negative_count_raises() -> None:
    with pytest.raises(ValueError, match="count must be >= 0"):
        generate_tick(count=-1, layer="adsb", ts=T0, rng=Random(1))


def test_deterministic_with_seed() -> None:
    """Same seed + same ts -> byte-identical envelopes (model_dump equality)."""
    a = generate_tick(count=20, layer="adsb", ts=T0, rng=Random(42), bbox=_box())
    b = generate_tick(count=20, layer="adsb", ts=T0, rng=Random(42), bbox=_box())
    assert [e.model_dump() for e in a] == [e.model_dump() for e in b]


def test_different_seed_differs() -> None:
    """Different seeds produce different positions (not a constant)."""
    a = generate_tick(count=20, layer="adsb", ts=T0, rng=Random(1), bbox=_box())
    b = generate_tick(count=20, layer="adsb", ts=T0, rng=Random(2), bbox=_box())
    assert [(e.lon, e.lat) for e in a] != [(e.lon, e.lat) for e in b]


def test_ts_equals_tick_and_ingested_at_default() -> None:
    """Every envelope's ts equals the tick; ingested_at defaults to the tick ts."""
    envs = generate_tick(count=5, layer="ais", ts=T0, rng=Random(1), bbox=_box())
    assert all(e.ts == T0 for e in envs)
    assert all(e.ingested_at == T0 for e in envs)


def test_ingested_at_override() -> None:
    envs = generate_tick(
        count=3, layer="ais", ts=T0, rng=Random(1), bbox=_box(), ingested_at=T0 + 5.0
    )
    assert all(e.ts == T0 for e in envs)
    assert all(e.ingested_at == T0 + 5.0 for e in envs)


def test_monotonic_ts_across_ticks() -> None:
    """A sequence of ticks at increasing ts gives non-decreasing envelope ts."""
    rng = Random(7)
    all_ts: list[float] = []
    for k in range(5):
        ts = T0 + k * 1.0
        envs = generate_tick(count=4, layer="adsb", ts=ts, rng=rng, bbox=_box())
        all_ts.extend(e.ts for e in envs)
    assert all_ts == sorted(all_ts)


def test_positions_within_bbox() -> None:
    """All generated positions lie inside the bbox, for every layer."""
    box = Bbox(lon_min=10.0, lat_min=-5.0, lon_max=20.0, lat_max=5.0)
    rng = Random(3)
    for layer in LAYERS:
        envs = generate_tick(count=200, layer=layer, ts=T0, rng=rng, bbox=box)
        for e in envs:
            assert e.lon is not None and e.lat is not None
            assert box.contains(e.lon, e.lat), (e.lon, e.lat)


def test_stable_entity_ids_across_ticks() -> None:
    """Entity i keeps the same id every tick (a track), independent of the RNG."""
    a = generate_tick(count=10, layer="adsb", ts=T0, rng=Random(1), bbox=_box())
    b = generate_tick(count=10, layer="adsb", ts=T0 + 100.0, rng=Random(999), bbox=_box())
    assert [e.entity_id for e in a] == [e.entity_id for e in b]


def test_entity_id_formats_per_layer() -> None:
    """ids look right: icao24 hex, 9-digit mmsi, norad int, ew-/ctx- prefixes."""
    icao = generate_tick(count=1, layer="adsb", ts=T0, rng=Random(1))[0].entity_id
    assert len(icao) == 6 and all(c in "0123456789abcdef" for c in icao)

    mmsi = generate_tick(count=1, layer="ais", ts=T0, rng=Random(1))[0].entity_id
    assert mmsi.isdigit() and len(mmsi) == 9 and 200_000_000 <= int(mmsi) <= 799_999_999

    norad = generate_tick(count=1, layer="tle", ts=T0, rng=Random(1))[0].entity_id
    assert norad.isdigit() and int(norad) >= 10000

    ew = generate_tick(count=1, layer="ew", ts=T0, rng=Random(1))[0].entity_id
    assert ew.startswith("ew-")

    ctx = generate_tick(count=1, layer="context", ts=T0, rng=Random(1))[0].entity_id
    assert ctx.startswith("ctx-")


def test_alt_present_only_for_adsb_and_tle() -> None:
    """adsb/tle carry an altitude; ais/ew/context do not."""
    assert generate_tick(count=1, layer="adsb", ts=T0, rng=Random(1))[0].alt_m is not None
    assert generate_tick(count=1, layer="tle", ts=T0, rng=Random(1))[0].alt_m is not None
    assert generate_tick(count=1, layer="ais", ts=T0, rng=Random(1))[0].alt_m is None
    assert generate_tick(count=1, layer="ew", ts=T0, rng=Random(1))[0].alt_m is None
    assert generate_tick(count=1, layer="context", ts=T0, rng=Random(1))[0].alt_m is None


def test_bbox_validation_and_helpers() -> None:
    """Bbox rejects degenerate boxes; clamp/contains/as_query behave."""
    with pytest.raises(ValueError, match="lon_min must be < lon_max"):
        Bbox(lon_min=5.0, lat_min=0.0, lon_max=5.0, lat_max=1.0)
    with pytest.raises(ValueError, match="lat_min must be < lat_max"):
        Bbox(lon_min=0.0, lat_min=1.0, lon_max=1.0, lat_max=1.0)

    box = Bbox(lon_min=0.0, lat_min=0.0, lon_max=10.0, lat_max=10.0)
    assert box.clamp(-5.0, 15.0) == (0.0, 10.0)
    assert box.contains(5.0, 5.0)
    assert not box.contains(11.0, 5.0)
    assert box.as_query() == "0.0,0.0,10.0,10.0"


def test_default_bbox_used_when_none() -> None:
    """Passing no bbox falls back to DEFAULT_BBOX (Strait of Hormuz)."""
    box = Bbox.from_tuple(DEFAULT_BBOX)
    envs = generate_tick(count=50, layer="adsb", ts=T0, rng=Random(1))
    for e in envs:
        assert box.contains(e.lon, e.lat)


def test_synthetic_payload_marker() -> None:
    """Envelopes are marked synthetic so a consumer can distinguish load traffic."""
    envs = generate_tick(count=3, layer="adsb", ts=T0, rng=Random(1))
    for i, e in enumerate(envs):
        assert e.payload["synthetic"] is True
        assert e.payload["idx"] == i
