"""Non-sensitive room/device projection for the shared knowledge graph."""

from __future__ import annotations

import hashlib
import json
import math
import threading
import time

from .contracts import HouseSnapshot

_DEVICE_DOMAINS = frozenset(
    {
        "alarm_control_panel",
        "camera",
        "climate",
        "cover",
        "fan",
        "humidifier",
        "light",
        "lock",
        "media_player",
        "remote",
        "switch",
        "vacuum",
        "water_heater",
    }
)
_MAX_QUERY_ITEMS = 2_000


def _fresh_time(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    result = float(value)
    return result if math.isfinite(result) and result >= 0 else 0.0


class HouseGraph:
    """Projects topology to the generic KG while retaining live state locally.

    Occupants, presence, identity, and privacy context are deliberately absent
    from this class. Those values live only in :class:`PrivateHouseStore`.
    """

    def __init__(self, graph, *, clock=None) -> None:
        self._graph = graph
        self._clock = clock or time.time
        self._lock = threading.RLock()
        self._rooms: dict[str, dict] = {}
        self._devices: dict[str, dict] = {}
        self._observed_at = 0.0
        self._status = "empty"
        self._fingerprint = ""

    @staticmethod
    def _safe_devices(snapshot: HouseSnapshot) -> list:
        return [entity for entity in snapshot.entities if entity.domain in _DEVICE_DOMAINS]

    @staticmethod
    def _digest(snapshot: HouseSnapshot, devices: list) -> str:
        payload = {
            "status": snapshot.status,
            "observed_at": snapshot.observed_at,
            "areas": [area.to_dict() for area in snapshot.areas],
            "devices": [entity.to_dict() for entity in devices],
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _existing_edge(self, source: str, target: str) -> bool:
        try:
            return any(
                relation.get("relation") == "CONTAINS" and relation.get("target") == target
                for relation in self._graph.get_relations(source, "outgoing")
            )
        except Exception:
            return False

    def _write_projection(self, rooms: dict, devices: dict, observed_at: float) -> int:
        current_names = {f"house:room:{room_id}" for room_id in rooms}
        current_names.update(f"house:device:{entity_id}" for entity_id in devices)
        for old_name in {
            *(f"house:room:{room_id}" for room_id in self._rooms),
            *(f"house:device:{entity_id}" for entity_id in self._devices),
        } - current_names:
            self._graph.delete_entity(old_name)

        for room in rooms.values():
            if not self._graph.add_entity(
                f"house:room:{room['room_id']}",
                "HouseRoom",
                {
                    "room_id": room["room_id"],
                    "source": "home_assistant",
                    "observed_at": observed_at,
                },
            ):
                raise RuntimeError("generic graph rejected room")

        relations = 0
        for device in devices.values():
            target = f"house:device:{device['entity_id']}"
            if not self._graph.add_entity(
                target,
                "HouseDevice",
                {
                    "entity_id": device["entity_id"],
                    "domain": device["domain"],
                    "area_id": device["room_id"],
                    "source": "home_assistant",
                    "observed_at": observed_at,
                },
            ):
                raise RuntimeError("generic graph rejected device")
            if device["room_id"] in rooms:
                source = f"house:room:{device['room_id']}"
                if not self._existing_edge(source, target):
                    if not self._graph.add_relation(
                        source,
                        "CONTAINS",
                        target,
                        {"source": "home_assistant", "observed_at": observed_at},
                    ):
                        raise RuntimeError("generic graph rejected relation")
                    relations += 1
        return relations

    def project_snapshot(self, snapshot: HouseSnapshot) -> dict:
        if not isinstance(snapshot, HouseSnapshot):
            raise ValueError("snapshot must be a HouseSnapshot")
        with self._lock:
            if snapshot.observed_at < self._observed_at:
                return {"status": "stale_ignored", "rooms": 0, "devices": 0, "relations": 0}
            if snapshot.status != "live":
                self._status = snapshot.status
                self._observed_at = max(self._observed_at, snapshot.observed_at)
                return {
                    "status": snapshot.status,
                    "rooms": 0,
                    "devices": 0,
                    "relations": 0,
                }

            devices = self._safe_devices(snapshot)
            fingerprint = self._digest(snapshot, devices)
            if fingerprint == self._fingerprint:
                return {"status": "unchanged", "rooms": 0, "devices": 0, "relations": 0}

            rooms = {
                area.area_id: {
                    "room_id": area.area_id,
                    "name": area.name,
                    "observed_at": snapshot.observed_at,
                }
                for area in snapshot.areas
            }
            normalized_devices = {
                entity.entity_id: {
                    "entity_id": entity.entity_id,
                    "domain": entity.domain,
                    "state": entity.state,
                    "room_id": entity.area_id,
                    "observed_at": entity.updated_at,
                }
                for entity in devices
            }

            try:
                relations = self._write_projection(rooms, normalized_devices, snapshot.observed_at)
            except Exception:
                self._status = "degraded"
                return {
                    "status": "degraded",
                    "reason": "graph_projection_failed",
                    "rooms": 0,
                    "devices": 0,
                    "relations": 0,
                }

            self._rooms = rooms
            self._devices = normalized_devices
            self._observed_at = snapshot.observed_at
            self._status = "live"
            self._fingerprint = fingerprint
            return {
                "status": "projected",
                "rooms": len(rooms),
                "devices": len(normalized_devices),
                "relations": relations,
            }

    def query_state(self, *, room_id: str = "", limit: int = 500) -> dict:
        bounded_limit = max(1, min(int(limit), _MAX_QUERY_ITEMS))
        with self._lock:
            rooms = [
                dict(room)
                for room in self._rooms.values()
                if not room_id or room["room_id"] == room_id
            ]
            devices = [
                dict(device)
                for device in self._devices.values()
                if not room_id or device["room_id"] == room_id
            ]
            observed_at = self._observed_at
            status = self._status
        rooms.sort(key=lambda item: item["room_id"])
        devices.sort(key=lambda item: item["entity_id"])
        now = _fresh_time(self._clock())
        return {
            "status": status,
            "observed_at": observed_at,
            "confidence": 1.0 if status == "live" else 0.0,
            "freshness_seconds": max(0.0, now - observed_at) if observed_at else None,
            "rooms": rooms[:bounded_limit],
            "devices": devices[:bounded_limit],
        }
