"""Tests for the Dark Vessel Detection algorithm."""

from worldview_ingest.darkwatch.detector import DarkVesselDetector, Geofence

# A square geofence roughly over the Strait of Hormuz, 30-minute gap threshold.
HORMUZ = Geofence(
    id=1,
    name="Strait of Hormuz",
    dark_gap_seconds=1800,
    ring=[(55.0, 25.0), (55.0, 27.0), (57.5, 27.0), (57.5, 25.0)],
)


def test_no_event_while_transmitting():
    det = DarkVesselDetector([HORMUZ])
    assert det.process(mmsi=123, lon=56.2, lat=26.5, ts=1000.0, cog=90.0, sog=10.0) is None
    # Swept shortly after: still within the gap threshold -> no event.
    assert det.sweep(now=1100.0) == []


def test_goes_dark_inside_geofence():
    det = DarkVesselDetector([HORMUZ])
    det.process(mmsi=123, lon=56.0, lat=26.5, ts=1000.0, cog=90.0, sog=10.0)
    events = det.sweep(now=1000.0 + 2000.0)  # silent past the 1800s threshold
    assert len(events) == 1
    ev = events[0]
    assert ev.mmsi == 123
    assert ev.geofence_id == 1
    assert ev.status == "dark"
    assert ev.gap_seconds == 2000
    # Dead-reckoned east (cog 90) from the last position -> longitude increases.
    assert ev.extrapolated_lon > 56.0


def test_flag_emitted_once():
    det = DarkVesselDetector([HORMUZ])
    det.process(mmsi=123, lon=56.0, lat=26.5, ts=1000.0, cog=90.0, sog=10.0)
    assert len(det.sweep(now=3000.0)) == 1
    assert det.sweep(now=4000.0) == []  # already flagged, not re-emitted


def test_resumed_event_on_reappearance():
    det = DarkVesselDetector([HORMUZ])
    det.process(mmsi=123, lon=56.0, lat=26.5, ts=1000.0, cog=90.0, sog=10.0)
    det.sweep(now=3000.0)  # flags it dark
    resumed = det.process(mmsi=123, lon=56.4, lat=26.5, ts=5000.0, cog=90.0, sog=10.0)
    assert resumed is not None
    assert resumed.status == "resumed"


def test_outside_geofence_not_watched():
    det = DarkVesselDetector([HORMUZ])
    assert det.process(mmsi=999, lon=10.0, lat=10.0, ts=1000.0) is None
    assert det.sweep(now=9999.0) == []
