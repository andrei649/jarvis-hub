"""CEP output event contract (``worldview.event.v1``) — WorldView ticket H19.2.3.

An :class:`EventMessage` is the wire form of a *detected* complex event emitted by
the CEP engine to the ``osint.events`` topic, so the backend can persist /
fan-out insights (tipping, holding patterns, jamming onsets, ...). Mirrors
``recon/message.py``'s style: a frozen dataclass + a plain ``to_dict()`` so the
exact contract is unit-testable without Kafka.

Wire contract (value JSON)::

    { "schema": "worldview.event.v1", "event_type": <str>,
      "aoi_id": <str|null>, "entity_id": <str|null>,
      "t_start": <float>, "t_end": <float>, "severity": <float>,
      "contributors": [<str>, ...], "detail": {<...>} }

All times are UNIX-seconds floats (UTC).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from worldview_ingest.cep.tipping import TippingEvent

SCHEMA = "worldview.event.v1"


@dataclass(frozen=True)
class EventMessage:
    """Serializable form of a detected complex event.

    - ``event_type``: detector kind, e.g. ``"tipping"`` / ``"holding_pattern"`` /
      ``"jamming_onset"``.
    - ``aoi_id`` / ``entity_id``: optional provenance — the AOI or track entity
      the event is about (whichever the detector keys on; the other is ``None``).
    - ``t_start`` / ``t_end``: the event's time span (UTC UNIX-seconds floats).
    - ``severity``: a comparable score (higher = stronger); detector-defined.
    - ``contributors``: provenance ids that produced the event (e.g. NORAD ids as
      strings, or source window ids), kept as a tuple for immutability.
    - ``detail``: a free-form dict carrying the raw detector fields.
    """

    event_type: str
    t_start: float
    t_end: float
    severity: float
    aoi_id: str | None = None
    entity_id: str | None = None
    contributors: tuple[str, ...] = ()
    detail: dict = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    # constructors from detector outputs
    # ------------------------------------------------------------------ #
    @classmethod
    def from_tipping(cls, ev: TippingEvent) -> EventMessage:
        """Build a ``tipping`` event from a :class:`TippingEvent`.

        Severity is the number of stacked passes (``window_count``) — more
        converging passes = a stronger tip. Contributors are the NORAD ids (as
        strings) in cluster order; ``detail`` keeps the raw fields.
        """
        return cls(
            event_type="tipping",
            t_start=float(ev.t_start),
            t_end=float(ev.t_end),
            severity=float(ev.window_count),
            aoi_id=ev.aoi_id,
            entity_id=None,
            contributors=tuple(str(n) for n in ev.norad_ids),
            detail={
                "window_count": int(ev.window_count),
                "norad_ids": [int(n) for n in ev.norad_ids],
            },
        )

    @classmethod
    def from_anomaly(
        cls,
        event_type: str,
        *,
        t_start: float,
        t_end: float,
        severity: float,
        entity_id: str | None = None,
        aoi_id: str | None = None,
        contributors: tuple[str, ...] = (),
        detail: dict | None = None,
    ) -> EventMessage:
        """Generic builder for the anomaly detectors (holding pattern, jamming, ...).

        The anomaly detectors (``cep.anomaly``) return heterogeneous dataclasses,
        so this keeps a single typed entry point: the worker maps each detector's
        fields into the common ``severity`` / ``contributors`` / ``detail`` shape.
        """
        return cls(
            event_type=event_type,
            t_start=float(t_start),
            t_end=float(t_end),
            severity=float(severity),
            aoi_id=aoi_id,
            entity_id=entity_id,
            contributors=tuple(contributors),
            detail=dict(detail or {}),
        )

    # ------------------------------------------------------------------ #
    # wire form
    # ------------------------------------------------------------------ #
    def key(self) -> str:
        """Kafka partition key: ``"{event_type}:{aoi_id|entity_id|-}"``.

        Keying by the subject id keeps all events about one AOI/entity on the
        same partition (ordered), and falls back to ``"-"`` when neither id is
        present.
        """
        subject = self.aoi_id or self.entity_id or "-"
        return f"{self.event_type}:{subject}"

    def to_dict(self) -> dict:
        """Produce the ``worldview.event.v1`` contract dict (with the schema tag)."""
        return {
            "schema": SCHEMA,
            "event_type": str(self.event_type),
            "aoi_id": None if self.aoi_id is None else str(self.aoi_id),
            "entity_id": None if self.entity_id is None else str(self.entity_id),
            "t_start": float(self.t_start),
            "t_end": float(self.t_end),
            "severity": float(self.severity),
            "contributors": [str(c) for c in self.contributors],
            "detail": dict(self.detail),
        }
