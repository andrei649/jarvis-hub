"""0.47 Creative Asset Pipeline — content-addressed provenance chain.

Tamper-evident lineage over a plan_pipeline() result: parent-linked records, stable SHA-256
fingerprints (dedup/verify without storing content), cycle-guarded lineage walk. Pure + offline.
"""
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.creative import pipeline as cp  # noqa: E402
from core.creative import provenance as pv  # noqa: E402


def _plan():
    return cp.plan_pipeline({"goal": "launch teaser", "platforms": ["youtube", "readme"]})


def test_chain_is_parent_linked_and_ordered():
    chain = pv.build_chain(_plan())
    assert [r["stage"] for r in chain] == ["script", "image_prompts", "render", "assemble", "export"]
    assert chain[0]["parent_id"] is None
    # each record's parent is the previous record's id
    for prev, cur in zip(chain, chain[1:], strict=False):
        assert cur["parent_id"] == prev["id"]
    assert all(r["generated"] is False for r in chain)


def test_fingerprint_is_deterministic_and_verifies():
    plan = _plan()
    chain = pv.build_chain(plan)
    # same plan → identical hashes (no clock/randomness)
    assert [r["content_hash"] for r in pv.build_chain(plan)] == [r["content_hash"] for r in chain]
    # a record verifies against its own stage, and fails against a tampered one
    stages = {s["id"]: s for s in plan["stages"]}
    rec = chain[0]
    assert pv.verify(rec, stages["script"]) is True
    tampered = dict(stages["script"])
    tampered["generator"] = "evil"
    assert pv.verify(rec, tampered) is False


def test_lineage_walks_child_to_root_and_is_cycle_safe():
    chain = pv.build_chain(_plan())
    export_id = chain[-1]["id"]
    walk = pv.lineage(chain, export_id)
    assert walk[0] == export_id and walk[-1] == chain[0]["id"]   # export → … → script
    assert len(walk) == len(chain)
    # inject a cycle → still terminates
    cyc = [dict(r) for r in chain]
    cyc[0]["parent_id"] = cyc[-1]["id"]
    out = pv.lineage(cyc, export_id)
    assert len(out) == len(set(out))                             # no id repeats


def test_empty_plan_yields_empty_chain():
    assert pv.build_chain({}) == []
    assert pv.lineage([], "nope") == []
