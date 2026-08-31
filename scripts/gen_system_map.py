#!/usr/bin/env python3
"""H34.7 M5 — export the Live System Map topology as an Archify architecture spec.

The product renders ``agents/core/system_map/topology.json`` natively (React
SVG in the HUD, vanilla SVG on ``/map``). This script is the out-of-band share
path: it converts the same checked-in topology into an Archify
(`tt-a1i/archify`, MIT) ``architecture`` specification, so a presentable,
self-contained HTML snapshot can be produced with Archify's own validator:

    python scripts/gen_system_map.py                      # spec -> docs/diagrams/nerva.architecture.json
    python scripts/gen_system_map.py --stdout             # spec -> stdout
    # then, with Archify available (dev tooling, never a product dependency):
    #   node <archify>/bin/archify.mjs deliver architecture \
    #       docs/diagrams/nerva.architecture.json docs/diagrams/nerva.architecture.html \
    #       --quality showcase

One topology, two renderers — the export can never drift from the live map
because both read the same contract file.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "agents"))

OUT_DEFAULT = REPO_ROOT / "docs" / "diagrams" / "nerva.architecture.json"

# Archify's component vocabulary is a superset of ours; ids map 1:1.
_ARCHIFY_TYPES = {"frontend", "backend", "database", "cloud", "security", "messagebus", "external"}

# Static presentation extras for the share artifact (labels/emphasis only —
# the semantic node/edge facts all come from topology.json).
_EMPHASIS_EDGES = {"hud-to-web", "web-to-orch", "orch-to-agents", "agents-to-llm", "llm-to-local"}
_DASHED_EDGES = {"llm-to-cloud", "autonomy-to-channels"}
_SECURITY_EDGES = {"orch-to-kernel", "autonomy-to-kernel"}

# Routing/label refinements that make Archify's showcase validator pass on this
# exact geometry (diagnosed 2026-08-31 against archify v2.16). Presentation
# only — they add no semantic facts to the topology.
_EDGE_GEOMETRY: dict[str, dict] = {
    "channels-to-orch": {"fromSide": "right", "toSide": "bottom"},
    "orch-to-plugins": {"fromSide": "top", "toSide": "left"},
    "orch-to-kernel": {"fromSide": "bottom", "toSide": "top"},
    "llm-to-cloud": {"labelDy": 24},
    "orch-to-memory": {"labelDx": -55},
}


def build_archify_spec(topology: dict) -> dict:
    """Pure conversion: topology contract -> Archify architecture JSON."""
    components = []
    for node in topology["nodes"]:
        if node["type"] not in _ARCHIFY_TYPES:
            raise ValueError(f"node {node['id']}: type {node['type']!r} unknown to Archify")
        comp = {
            "id": node["id"],
            "type": node["type"],
            "label": node["label"],
            "sublabel": node.get("sublabel", ""),
            "pos": list(node["pos"]),
            "size": list(node["size"]),
        }
        components.append(comp)
    node_ids = {c["id"] for c in components}

    connections = []
    for edge in topology["edges"]:
        if edge["from"] not in node_ids or edge["to"] not in node_ids:
            raise ValueError(f"edge {edge['id']}: endpoint not in topology")
        conn: dict = {"id": edge["id"], "from": edge["from"], "to": edge["to"]}
        if edge.get("label"):
            conn["label"] = edge["label"]
        if edge["id"] in _EMPHASIS_EDGES:
            conn["variant"] = "emphasis"
        elif edge["id"] in _DASHED_EDGES:
            conn["variant"] = "dashed"
        elif edge["id"] in _SECURITY_EDGES:
            conn["variant"] = "security"
        conn.update(_EDGE_GEOMETRY.get(edge["id"], {}))
        connections.append(conn)

    return {
        "schema_version": 1,
        "diagram_type": "architecture",
        "meta": {
            "title": topology.get("title", "Nerva — Live System Map"),
            "output": "nerva.architecture.html",
            "quality_profile": "showcase",
        },
        "components": components,
        "boundaries": [
            {
                "kind": "region",
                "label": "Owner's machine — local-first",
                "wraps": sorted(node_ids - {"cloud"}) if "cloud" in node_ids else sorted(node_ids),
            }
        ],
        "connections": connections,
        "cards": [
            {"dot": "cyan", "title": "Live map", "items": [
                f"Generated from agents/core/system_map/topology.json v{topology['version']}",
                "The product renders the same topology live at /map and in the HUD",
            ]},
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdout", action="store_true", help="write the spec to stdout")
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT, help="output path")
    args = parser.parse_args(argv)

    from agents.core.system_map import load_topology

    spec = build_archify_spec(load_topology())
    text = json.dumps(spec, indent=2, ensure_ascii=False) + "\n"
    if args.stdout:
        sys.stdout.write(text)
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out} ({len(spec['components'])} components, "
              f"{len(spec['connections'])} connections)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
