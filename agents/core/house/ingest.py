"""Production presence writer — Home Assistant snapshot → PresenceInference.

GAP-9 (honest-gap analysis): ``/api/house/state.presence`` was structurally
``[]`` in every production configuration because nothing outside the hermetic
reality probe ever wrote presence predicates. This module closes that gap with
the one signal source that carries identity *and* room in the same object and
is already production-wired: the Home Assistant REST snapshot fetched on every
``/api/house/state`` request.

Deliberate boundaries:
- Default-off behind ``house.presence_enabled`` / ``JARVIS_HOUSE_PRESENCE``;
  with the flag off, behavior is byte-identical to before.
- Only identity-bearing HA domains (``person.*``, ``device_tracker.*``) feed
  ``person_tracker`` evidence; ``binary_sensor.*`` with a motion/occupancy/
  presence device class contributes anonymous ``motion`` corroboration.
  Camera feeds are anonymous by construction and stay out.
- HA state vocabulary is translated through an explicit alias table; an
  unknown state is dropped, never guessed (the autonomy/presence.py rule).
- The inference model's thresholds are untouched: a single evidence category
  can never cross the presence threshold by design (its anti-overclaim
  floor), so a lone tracker yields ``unknown`` and writes nothing — room
  presence is only claimed when identity AND same-room motion corroborate.
- Evidence ``observed_at`` is the snapshot fetch time: the honest claim is
  "as of this snapshot HA reports the occupant home", not a replay of the
  entity's possibly hours-old last state change.
- All privacy properties (pseudonymization, consent, private-room
  suppression, tombstones) stay enforced inside ``PresenceInference`` /
  ``PrivateHouseStore`` — this module adds no second policy layer.
"""

from __future__ import annotations

import logging

from .contracts import HouseSnapshot
from .presence import PresenceEvidence, PresenceInference

logger = logging.getLogger(__name__)

# HA → presence-evidence state vocabulary. Explicit and closed: anything not
# listed is dropped rather than guessed (a wrong guess writes a wrong fact).
_IDENTITY_STATES = {
    "home": "present",
    "on": "present",
    "not_home": "absent",
    "away": "absent",
    "off": "absent",
    "unavailable": "absent",
    "unknown": None,  # explicit: HA says it does not know — write nothing
}
_MOTION_STATES = {"on": "detected", "off": "clear"}
_MOTION_DEVICE_CLASSES = {"motion", "occupancy", "presence"}
_IDENTITY_CONFIDENCE = 0.9
_MOTION_CONFIDENCE = 0.6
_MAX_OCCUPANTS = 64


def _attribute(entity, key: str) -> str:
    for name, value in entity.attributes:
        if name == key:
            return value
    return ""


class HousePresenceIngestor:
    """Bounded, per-request translator from a live snapshot to inferences."""

    def __init__(self, inference: PresenceInference) -> None:
        if not isinstance(inference, PresenceInference):
            raise ValueError("inference must be a PresenceInference")
        self._inference = inference

    def ingest(self, snapshot: HouseSnapshot) -> int:
        """Feed one live snapshot; returns how many occupants were inferred.

        Never raises for malformed entities — one bad entity must not blank
        the whole presence view — but programming errors (a non-snapshot
        argument) still fail loudly.
        """
        if not isinstance(snapshot, HouseSnapshot):
            raise ValueError("snapshot must be a HouseSnapshot")
        if snapshot.status != "live":
            return 0

        observed_at = snapshot.observed_at
        identity: list[tuple[str, PresenceEvidence]] = []
        motion: list[PresenceEvidence] = []
        for entity in snapshot.entities:
            try:
                if entity.domain in {"person", "device_tracker"}:
                    state = _IDENTITY_STATES.get(entity.state.strip().lower())
                    if state is None:
                        continue
                    occupant_ref = entity.name or entity.entity_id
                    identity.append(
                        (
                            occupant_ref,
                            PresenceEvidence(
                                source_event_id=entity.entity_id,
                                category="person_tracker",
                                state=state,
                                observed_at=observed_at,
                                confidence=_IDENTITY_CONFIDENCE,
                                room_id=entity.area_id,
                                occupant_ref=occupant_ref,
                            ),
                        )
                    )
                elif (
                    entity.domain == "binary_sensor"
                    and _attribute(entity, "device_class") in _MOTION_DEVICE_CLASSES
                    and entity.area_id
                ):
                    state = _MOTION_STATES.get(entity.state.strip().lower())
                    if state is None:
                        continue
                    motion.append(
                        PresenceEvidence(
                            source_event_id=entity.entity_id,
                            category="motion",
                            state=state,
                            observed_at=observed_at,
                            confidence=_MOTION_CONFIDENCE,
                            room_id=entity.area_id,
                        )
                    )
            except ValueError:
                logger.debug("presence: dropped malformed entity %s", entity.entity_id)

        inferred = 0
        for occupant_ref, evidence in identity[:_MAX_OCCUPANTS]:
            room_motion = [item for item in motion if item.room_id == evidence.room_id]
            try:
                self._inference.infer(occupant_ref, [evidence, *room_motion])
                inferred += 1
            except ValueError:
                # Per-occupant isolation: one refused inference (e.g. an
                # occupant_ref over limits) never blanks the others.
                logger.debug("presence: inference refused for one occupant")
        return inferred


__all__ = ["HousePresenceIngestor"]
