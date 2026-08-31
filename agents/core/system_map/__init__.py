"""H34.7 Live System Map — the topology contract.

The map of what Nerva *is*, consumed by the live feed that shows what Nerva
is *doing* (``agents/core/routers/system_map.py``). The topology is data, not
code: nodes/edges live in ``topology.json`` and every node declares the
``health_source`` reducer that produces its live status. A parity test
(`tests/test_system_map.py`) pins each declared source to an implemented
reducer, so the map cannot silently drift from the code it claims to draw.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_TOPOLOGY_PATH = Path(__file__).resolve().parent / "topology.json"

NODE_TYPES = {"frontend", "backend", "database", "cloud", "security", "external"}

# The complete, closed status vocabulary. "unknown" is a first-class value —
# an unmeasured subsystem renders as unknown, never as green.
STATUSES = ("ok", "degraded", "attention", "off", "unknown")


class TopologyError(ValueError):
    """The topology file is malformed — fail loudly, never render a wrong map."""


def _validate(data: dict) -> dict:
    if not isinstance(data, dict):
        raise TopologyError("topology root must be an object")
    for key in ("version", "title", "view_box", "nodes", "edges"):
        if key not in data:
            raise TopologyError(f"topology missing required key: {key}")
    node_ids: set[str] = set()
    for node in data["nodes"]:
        nid = node.get("id")
        if not nid or not isinstance(nid, str):
            raise TopologyError("every node needs a string id")
        if nid in node_ids:
            raise TopologyError(f"duplicate node id: {nid}")
        node_ids.add(nid)
        if node.get("type") not in NODE_TYPES:
            raise TopologyError(f"node {nid}: unknown type {node.get('type')!r}")
        if not node.get("health_source"):
            raise TopologyError(f"node {nid}: missing health_source")
        pos, size = node.get("pos"), node.get("size")
        if not (isinstance(pos, list) and len(pos) == 2 and isinstance(size, list) and len(size) == 2):
            raise TopologyError(f"node {nid}: pos/size must be [x, y] / [w, h]")
    edge_ids: set[str] = set()
    for edge in data["edges"]:
        eid = edge.get("id")
        if not eid or eid in edge_ids:
            raise TopologyError(f"edge id missing or duplicate: {eid!r}")
        edge_ids.add(eid)
        for end in ("from", "to"):
            if edge.get(end) not in node_ids:
                raise TopologyError(f"edge {eid}: {end}={edge.get(end)!r} is not a node id")
    return data


@lru_cache(maxsize=1)
def load_topology() -> dict:
    """Load and validate the checked-in topology (cached — it only changes with a deploy)."""
    return _validate(json.loads(_TOPOLOGY_PATH.read_text(encoding="utf-8")))


def health_sources() -> set[str]:
    """Every health_source the topology declares — the parity test's left-hand side."""
    return {node["health_source"] for node in load_topology()["nodes"]}


def activity_sources() -> set[str]:
    """Every activity_source any edge declares (edges without one render static)."""
    return {
        edge["activity_source"]
        for edge in load_topology()["edges"]
        if edge.get("activity_source")
    }
