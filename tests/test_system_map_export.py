"""H34.7 M5 — the Archify export shares one contract with the live map.

`scripts/gen_system_map.py` converts `agents/core/system_map/topology.json`
into an Archify architecture spec. These tests pin the one-topology-two-
renderers rule: every exported component/connection comes from the topology,
so the share artifact can never drift from what the product renders live.
"""

import json
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

sys.path.insert(0, str(repo_root / "scripts"))
from gen_system_map import build_archify_spec, main  # noqa: E402

from agents.core.system_map import load_topology  # noqa: E402


def test_export_mirrors_the_topology_exactly():
    topo = load_topology()
    spec = build_archify_spec(topo)
    assert spec["schema_version"] == 1
    assert spec["diagram_type"] == "architecture"
    assert spec["meta"]["quality_profile"] == "showcase"
    assert {c["id"] for c in spec["components"]} == {n["id"] for n in topo["nodes"]}
    assert {c["id"] for c in spec["connections"]} == {e["id"] for e in topo["edges"]}
    # geometry passes through untouched — one layout, two renderers
    by_id = {n["id"]: n for n in topo["nodes"]}
    for comp in spec["components"]:
        assert comp["pos"] == by_id[comp["id"]]["pos"]
        assert comp["size"] == by_id[comp["id"]]["size"]


def test_export_excludes_cloud_from_the_local_boundary():
    spec = build_archify_spec(load_topology())
    region = spec["boundaries"][0]
    assert "cloud" not in region["wraps"]
    assert "orch" in region["wraps"]


def test_export_rejects_a_type_archify_does_not_know():
    topo = json.loads(json.dumps(load_topology()))
    topo["nodes"][0]["type"] = "mystery"
    with pytest.raises(ValueError):
        build_archify_spec(topo)


def test_cli_writes_the_spec_file(tmp_path):
    out = tmp_path / "spec.json"
    assert main(["--out", str(out)]) == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["diagram_type"] == "architecture"
    assert len(written["components"]) == len(load_topology()["nodes"])
