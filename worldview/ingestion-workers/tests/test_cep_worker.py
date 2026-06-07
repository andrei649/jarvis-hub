"""Tests for the async CEP worker (worldview_ingest.cep.worker).

No Kafka / network: ``run`` is driven with an in-memory FAKE consumer (an
async-iterable yielding a finite set of records, including a poison pill that
must be skipped) and a FAKE producer that records everything published. The
loop terminates cleanly because the fake consumer is finite (``_drive`` returns,
then the injected-mode branch flushes). Mirrors the fakes in the other worker
tests; async code is driven with ``asyncio.run`` (no pytest-asyncio).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from unittest import mock

from worldview_ingest.cep import worker as cep_worker
from worldview_ingest.config import Settings

# Window/lateness/threshold knobs pinned for the tests (independent of env defaults).
_TEST_SETTINGS = replace(
    Settings(),
    cep_input_topics="osint.recon",
    cep_output_topic="osint.events",
    cep_window_seconds=600,
    cep_lateness_seconds=120,
    cep_tipping_delta_seconds=600,
    cep_tipping_min_count=3,
)

# A round base so three ingress times all land inside one 600s tumbling window.
BASE = 1_700_000_400.0  # floor(BASE/600)*600 == 1_700_000_400 (aligned start)


class FakeRecord:
    """Stand-in for an aiokafka ConsumerRecord: only ``value`` (bytes) is read."""

    def __init__(self, value: bytes) -> None:
        self.value = value


class FakeConsumer:
    """Finite async-iterable fake consumer (start/stop + ``async for``)."""

    def __init__(self, records: list[FakeRecord]) -> None:
        self._records = records
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    def __aiter__(self):
        async def _gen():
            for rec in self._records:
                yield rec

        return _gen()


class FakeProducer:
    """Records every ``send_and_wait`` call so the test can assert on output."""

    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.sent: list[tuple[str, bytes, bytes]] = []

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def send_and_wait(self, topic: str, value: bytes, key: bytes) -> None:
        self.sent.append((topic, value, key))


def _recon_value(norad_id: int, aoi_id: str, t_ingress: float) -> bytes:
    """A valid ``worldview.recon.v1`` message value (bytes)."""
    return json.dumps(
        {
            "schema": "worldview.recon.v1",
            "norad_id": norad_id,
            "aoi_id": aoi_id,
            "sensor_type": "optical",
            "t_ingress": t_ingress,
            "t_peak": t_ingress + 30.0,
            "t_egress": t_ingress + 60.0,
            "min_distance_km": 10.0,
            "sunlit_at_peak": True,
            "quality": 0.9,
        }
    ).encode()


def _run_worker(records: list[FakeRecord]) -> FakeProducer:
    """Drive ``cep_worker.run`` with the given records under the test settings."""
    consumer = FakeConsumer(records)
    producer = FakeProducer()
    with mock.patch.object(cep_worker, "settings", _TEST_SETTINGS):
        asyncio.run(cep_worker.run(consumer=consumer, producer=producer))
    assert consumer.started and consumer.stopped
    assert producer.started and producer.stopped
    return producer


# --------------------------------------------------------------------------- #
# happy path: a stacked cluster within one window emits a tipping event
# --------------------------------------------------------------------------- #


def test_clustered_passes_emit_tipping_event() -> None:
    """Three passes stacked over one AOI within a window emit one tipping event."""
    records = [
        FakeRecord(_recon_value(100, "aoi-1", BASE + 0.0)),
        FakeRecord(_recon_value(200, "aoi-1", BASE + 120.0)),
        FakeRecord(_recon_value(300, "aoi-1", BASE + 250.0)),
    ]
    producer = _run_worker(records)

    assert len(producer.sent) == 1
    topic, value, key = producer.sent[0]
    assert topic == "osint.events"
    msg = json.loads(value)
    assert msg["schema"] == "worldview.event.v1"
    assert msg["event_type"] == "tipping"
    assert msg["aoi_id"] == "aoi-1"
    assert msg["severity"] == 3.0
    assert msg["contributors"] == ["100", "200", "300"]
    assert msg["t_start"] == BASE + 0.0
    assert msg["t_end"] == BASE + 250.0
    # Key is "{event_type}:{aoi_id}".
    assert key == b"tipping:aoi-1"


# --------------------------------------------------------------------------- #
# poison pill must be skipped, not crash the loop
# --------------------------------------------------------------------------- #


def test_poison_pill_is_skipped_and_loop_survives() -> None:
    """A malformed message between valid ones is skipped; the rest still emit."""
    records = [
        FakeRecord(_recon_value(100, "aoi-1", BASE + 0.0)),
        FakeRecord(b"{not valid json"),  # poison pill: undecodable
        FakeRecord(_recon_value(200, "aoi-1", BASE + 120.0)),
        FakeRecord(b'{"schema": "x"}'),  # decodable but missing required fields
        FakeRecord(_recon_value(300, "aoi-1", BASE + 250.0)),
    ]
    producer = _run_worker(records)

    # The two poison pills were skipped; the three good passes still tipped.
    assert len(producer.sent) == 1
    msg = json.loads(producer.sent[0][1])
    assert msg["event_type"] == "tipping"
    assert msg["contributors"] == ["100", "200", "300"]


def test_non_object_json_is_skipped() -> None:
    """A valid-JSON but non-object value (e.g. a list) is treated as a poison pill."""
    records = [
        FakeRecord(b"[1, 2, 3]"),  # valid JSON, not a dict
        FakeRecord(_recon_value(100, "aoi-1", BASE + 0.0)),
        FakeRecord(_recon_value(200, "aoi-1", BASE + 120.0)),
        FakeRecord(_recon_value(300, "aoi-1", BASE + 250.0)),
    ]
    producer = _run_worker(records)
    assert len(producer.sent) == 1
    assert json.loads(producer.sent[0][1])["event_type"] == "tipping"


# --------------------------------------------------------------------------- #
# per-AOI isolation + below-threshold clusters
# --------------------------------------------------------------------------- #


def test_distinct_aois_do_not_combine() -> None:
    """Two passes per AOI never reach min_count=3 — no events emitted."""
    records = [
        FakeRecord(_recon_value(100, "aoi-1", BASE + 0.0)),
        FakeRecord(_recon_value(400, "aoi-2", BASE + 30.0)),
        FakeRecord(_recon_value(200, "aoi-1", BASE + 120.0)),
        FakeRecord(_recon_value(500, "aoi-2", BASE + 150.0)),
    ]
    producer = _run_worker(records)
    assert producer.sent == []


def test_no_records_emits_nothing() -> None:
    """An empty stream cleanly starts/stops clients and emits nothing."""
    producer = _run_worker([])
    assert producer.sent == []


def test_late_event_beyond_lateness_is_dropped() -> None:
    """A pass older than the watermark is dropped and cannot complete a cluster.

    Two in-window passes plus a far-future pass (which advances the watermark past
    the window) then a stale pass arriving too late: the stale one is dropped, so
    the original AOI window never reaches min_count and no event is emitted.
    """
    far_future = BASE + 10_000.0  # advances watermark well past the BASE window
    records = [
        FakeRecord(_recon_value(100, "aoi-1", BASE + 0.0)),
        FakeRecord(_recon_value(200, "aoi-1", BASE + 120.0)),
        FakeRecord(_recon_value(900, "aoi-9", far_future)),  # jumps the watermark
        FakeRecord(_recon_value(300, "aoi-1", BASE + 250.0)),  # now far too late -> dropped
    ]
    producer = _run_worker(records)
    # aoi-1 only ever buffered 2 passes (the 3rd was dropped) -> below min_count -> nothing.
    assert producer.sent == []
