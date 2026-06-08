"""CEP consumer worker (WorldView ticket H19.2.3).

Consumes the recon stream (``osint.recon`` by default), drives the pure
:class:`worldview_ingest.cep.engine.WindowedKeyedEngine` over it, and publishes
the detected complex events to the CEP output topic (``osint.events``) as
``worldview.event.v1`` messages.

Structure mirrors ``recon/worker.py``: this worker owns its OWN clients — it
builds an :class:`AIOKafkaConsumer` over the configured input topic(s) and an
:class:`AIOKafkaProducer` to the output topic. Any clients handed in by the
``__main__`` dispatch are ignored by design; the optional ``consumer`` /
``producer`` parameters exist ONLY so the tests can drive ``run`` without a live
broker (in-memory fakes).

The wiring is intentionally thin:

- The engine is keyed by ``aoi_id`` (the tipping detector clusters per AOI), so
  per-AOI buffers stay isolated and out-of-order recon windows within the
  allowed lateness are still counted.
- Each closed window fires :func:`detect_tipping` over the window's buffered
  recon messages; every :class:`TippingEvent` becomes an :class:`EventMessage`.

Robustness notes (the bug classes this project has hit before):

- **Poison pills.** Every Kafka value is decoded with a *guarded* ``json.loads``
  inside ``try/except``; a malformed / unexpected message is logged and SKIPPED,
  never allowed to kill the loop (mirrors the backend live/recon writers and the
  history-writer fix).
- **Infra-optional.** All timestamps stay UTC UNIX-seconds floats coming off the
  ``worldview.recon.v1`` contract — no wall-clock / local-timezone leakage.
- **Reconnect/backoff** on ``(TimeoutError, OSError)`` and aiokafka errors with
  the same exponential bounds as the other workers.
"""

from __future__ import annotations

import asyncio
import json
import logging

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.errors import KafkaError

from worldview_ingest.cep.engine import Event, WindowedKeyedEngine, WindowResult
from worldview_ingest.cep.events import EventMessage
from worldview_ingest.cep.tipping import TippingEvent, detect_tipping
from worldview_ingest.config import settings
from worldview_ingest.recon.windows import ReconWindow

logger = logging.getLogger(__name__)

# Backoff bounds for the consume loop on transient errors (mirrors the other workers).
_BACKOFF_BASE = 1.0
_BACKOFF_MAX = 60.0

# aiokafka consumer group for the CEP worker (one logical insight engine).
_GROUP_ID = "worldview-cep"


def _input_topics() -> list[str]:
    """Parse ``settings.cep_input_topics`` (comma-separated) into a topic list."""
    return [t.strip() for t in settings.cep_input_topics.split(",") if t.strip()]


def _window_from_payload(payload: dict) -> ReconWindow:
    """Rebuild a :class:`ReconWindow` from a decoded ``worldview.recon.v1`` dict.

    Only the fields the tipping detector needs are load-bearing, but we
    reconstruct the full window so the detector sees a faithful object. Raises
    ``(KeyError, TypeError, ValueError)`` on a malformed payload — the caller
    guards those and skips the poison pill.
    """
    return ReconWindow(
        norad_id=int(payload["norad_id"]),
        aoi_id=str(payload["aoi_id"]),
        sensor_type=str(payload["sensor_type"]),
        t_ingress=float(payload["t_ingress"]),
        t_peak=float(payload["t_peak"]),
        t_egress=float(payload["t_egress"]),
        min_distance_km=float(payload["min_distance_km"]),
        sunlit_at_peak=bool(payload["sunlit_at_peak"]),
        quality=float(payload["quality"]),
    )


def _tipping_rule(
    key: str,  # noqa: ARG001 — the engine passes the key; the detector re-derives aoi_id
    window_start: float,  # noqa: ARG001 — bounds are provenance, not detector input
    window_end: float,  # noqa: ARG001
    events: list[Event[ReconWindow]],
) -> list[TippingEvent]:
    """Engine rule: run the pure tipping detector over a closed window's windows.

    The engine hands us the buffered events (payloads are :class:`ReconWindow`s
    routed by ``aoi_id`` key); we run :func:`detect_tipping` with the configured
    thresholds and return its (possibly empty) event list.
    """
    recon_windows = [e.payload for e in events]
    return detect_tipping(
        recon_windows,
        delta_s=float(settings.cep_tipping_delta_seconds),
        min_count=int(settings.cep_tipping_min_count),
    )


def _build_engine() -> WindowedKeyedEngine[ReconWindow, list[TippingEvent]]:
    """Construct the per-AOI tumbling engine wired to the tipping rule."""
    return WindowedKeyedEngine(
        window_s=float(settings.cep_window_seconds),
        allowed_lateness_s=float(settings.cep_lateness_seconds),
        rule=_tipping_rule,
    )


async def _emit(
    producer: AIOKafkaProducer,
    result: WindowResult[list[TippingEvent]],
) -> int:
    """Publish each :class:`TippingEvent` in a window result as an EventMessage.

    Returns the number of messages sent. Times stay UTC UNIX-seconds floats off
    the detector output.
    """
    sent = 0
    for ev in result.output:
        msg = EventMessage.from_tipping(ev)
        value = json.dumps(msg.to_dict()).encode()
        key = msg.key().encode()
        await producer.send_and_wait(settings.cep_output_topic, value=value, key=key)
        sent += 1
    return sent


def _decode(record) -> dict | None:
    """Guarded decode of one Kafka record value into a recon payload dict.

    Returns the decoded ``dict`` on success, or ``None`` for a poison pill (bad
    JSON, non-object, or missing the timestamp the engine keys on). Never raises
    — a single bad message must not kill the loop.
    """
    raw = record.value
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError) as exc:
        logger.warning("cep: skipping undecodable message: %s", exc)
        return None
    if not isinstance(payload, dict) or "t_ingress" not in payload or "aoi_id" not in payload:
        logger.warning("cep: skipping message missing required fields: %r", payload)
        return None
    return payload


async def _drive(
    consumer: AIOKafkaConsumer,
    producer: AIOKafkaProducer,
    engine: WindowedKeyedEngine[ReconWindow, list[TippingEvent]],
) -> None:
    """Consume the input topic(s), feed the engine, and emit detected events.

    Each recon message is keyed into the engine by ``aoi_id`` at event time
    ``t_ingress``; whenever the watermark closes a window the rule fires and any
    resulting events are published. Poison pills are skipped (see :func:`_decode`).
    """
    async for record in consumer:
        payload = _decode(record)
        if payload is None:
            continue
        try:
            window = _window_from_payload(payload)
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("cep: skipping malformed recon payload: %s", exc)
            continue
        # Key by AOI (tipping clusters per AOI); event time is the ingress instant.
        event = Event(key=window.aoi_id, ts=window.t_ingress, payload=window)
        for result in engine.push(event):
            published = await _emit(producer, result)
            if published:
                logger.info(
                    "cep: emitted %d event(s) for aoi=%s window=[%.0f,%.0f)",
                    published,
                    result.key,
                    result.window_start,
                    result.window_end,
                )


async def run(consumer=None, producer=None) -> None:
    """Run the CEP worker: consume recon windows, detect, publish to the events topic.

    Owns its own ``AIOKafkaConsumer`` (over ``settings.cep_input_topics``) and
    ``AIOKafkaProducer`` (to ``settings.cep_output_topic``) by default. The
    optional ``consumer`` / ``producer`` parameters are used ONLY when provided
    (the tests inject in-memory fakes); otherwise real clients are built here.

    The consume loop reconnects with exponential backoff on transient
    ``(TimeoutError, OSError)`` / aiokafka errors, and stops its clients in a
    ``finally``. When the (real) consumer is an unbounded stream the loop runs
    forever; an injected finite fake makes ``_drive`` return so tests terminate.
    """
    topics = _input_topics()
    owns_clients = consumer is None and producer is None
    logger.info(
        "cep worker: input=%s output=%s window=%ss lateness=%ss tipping(delta=%ss,min=%d)",
        topics,
        settings.cep_output_topic,
        settings.cep_window_seconds,
        settings.cep_lateness_seconds,
        settings.cep_tipping_delta_seconds,
        settings.cep_tipping_min_count,
    )

    if consumer is None:
        consumer = AIOKafkaConsumer(
            *topics,
            bootstrap_servers=settings.kafka_brokers,
            group_id=_GROUP_ID,
            enable_auto_commit=True,
            auto_offset_reset="latest",
        )
    if producer is None:
        producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_brokers)

    engine = _build_engine()

    await consumer.start()
    await producer.start()
    try:
        if owns_clients:
            # Live mode: keep the loop alive across transient errors.
            backoff = _BACKOFF_BASE
            while True:
                try:
                    await _drive(consumer, producer, engine)
                    backoff = _BACKOFF_BASE
                except (TimeoutError, OSError, KafkaError) as exc:
                    logger.warning("cep loop error: %s; backing off %.0fs", exc, backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, _BACKOFF_MAX)
        else:
            # Test / injected mode: a finite fake consumer makes _drive return; on
            # end-of-stream, flush any still-open windows so nothing is stranded.
            await _drive(consumer, producer, engine)
            for result in engine.flush():
                await _emit(producer, result)
    finally:
        await consumer.stop()
        await producer.stop()
