"""Tests for the Dark Vessel Detection algorithm."""

from __future__ import annotations

import asyncio
from unittest import mock

from worldview_ingest.darkwatch import worker as dark_worker
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


class _FakeMsg:
    """Minimal stand-in for an aiokafka ConsumerRecord (only `.value` is used)."""

    def __init__(self, value: object) -> None:
        self.value = value


class _FakeConsumer:
    """Yields a fixed list of messages, then stops the `async for` loop."""

    def __init__(self, messages: list[_FakeMsg]) -> None:
        self._messages = messages
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    def __aiter__(self):
        async def _gen():
            for msg in self._messages:
                yield msg

        return _gen()


def _ais_envelope(mmsi: int, lon: float, lat: float, ts: float) -> dict:
    return {
        "entity_id": mmsi,
        "lon": lon,
        "lat": lat,
        "ts": ts,
        "payload": {"cog_deg": 90.0, "sog_kt": 10.0},
    }


def test_run_skips_malformed_envelope_and_continues():
    """A poison AIS envelope must be logged + skipped, not kill the consumer loop.

    Feed one malformed envelope (missing lon/lat) followed by a valid one; the
    worker must process the valid one (so the malformed message did not raise out
    of the `async for`) and leave it tracked in the detector.
    """
    malformed = _FakeMsg({"entity_id": "x", "ts": 1000.0})  # no lon/lat, bad mmsi
    valid = _FakeMsg(_ais_envelope(mmsi=123, lon=56.2, lat=26.5, ts=1000.0))
    consumer = _FakeConsumer([malformed, valid])

    producer = mock.AsyncMock()
    geofences = [HORMUZ]

    def _skip_sweeper(coro):
        # Don't run the periodic sweeper in this test; close the coroutine so it
        # isn't reported as "never awaited", and return a cancel()-able stand-in.
        coro.close()
        return mock.Mock()

    with (
        mock.patch.object(dark_worker, "AIOKafkaConsumer", return_value=consumer),
        mock.patch.object(dark_worker.asyncio, "create_task", side_effect=_skip_sweeper),
    ):
        captured: dict[str, DarkVesselDetector] = {}
        real_detector_cls = dark_worker.DarkVesselDetector

        def _capture(gfs):
            det = real_detector_cls(gfs)
            captured["det"] = det
            return det

        with mock.patch.object(dark_worker, "DarkVesselDetector", side_effect=_capture):
            asyncio.run(dark_worker.run(geofences, producer))

    assert consumer.started and consumer.stopped
    # The valid vessel was processed despite the earlier malformed message.
    det = captured["det"]
    assert det.sweep(now=1000.0 + 2000.0)  # 123 is tracked and goes dark
