"""H21.3 — Living, unlimited memory (cognition algorithm layer). All offline."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import pytest

from agents.core.cognition.memory import (
    neuromodulators, salience, surprise_score, encoding_gate, encoding_strength,
    pattern_separate, pattern_complete, tcm_rerank, tier_for, TieredMemory,
    needs_reprojection, reproject, CoreMemory, LivingMemory, HOT, COLD,
)


# ── neuromodulators + encoding ────────────────────────────────────────────────

def test_neuromodulators_and_salience():
    nm = neuromodulators(reward=0.5, surprise=1.5, novelty=-0.2)  # clamps to [0,1]
    assert nm == {"DA": 0.5, "NE": 1.0, "ACh": 0.0}
    assert salience(nm) == 0.5


def test_surprise_text_and_vector():
    assert surprise_score("the cat sat", "the cat sat") == 0.0          # identical
    assert surprise_score("alpha beta", "gamma delta") == 1.0           # disjoint
    assert surprise_score([1.0, 0.0], [1.0, 0.0]) == 0.0                # same vector
    assert surprise_score([1.0, 0.0], [0.0, 1.0]) == 1.0               # orthogonal


def test_encoding_gate_and_strength():
    assert encoding_gate(0.5) is True and encoding_gate(0.1) is False
    base = encoding_strength(0.5)
    boosted = encoding_strength(0.5, neuromodulators(reward=1, surprise=1, novelty=1))
    assert boosted > base


# ── pattern separation / completion ───────────────────────────────────────────

def test_pattern_separate_pushes_apart():
    v = [0.5, 0.5]
    out = pattern_separate(v, [[0.5, 0.5]], strength=0.5)  # neighbor identical
    # identical neighbor → no push (diff is zero); distinct neighbor → moves away
    out2 = pattern_separate([0.5, 0.5], [[0.0, 0.0]], strength=0.5)
    assert out == [0.5, 0.5] and out2 != [0.5, 0.5]


def test_pattern_complete_finds_closest():
    mems = [{"id": "a", "vector": [1.0, 0.0]}, {"id": "b", "vector": [0.0, 1.0]}]
    assert pattern_complete([0.9, 0.1], mems)["id"] == "a"


# ── TCM re-rank ───────────────────────────────────────────────────────────────

def test_tcm_rerank_boosts_recent_context():
    now = 1000.0
    results = [{"id": "old", "score": 0.5, "ts": 0.0},
               {"id": "recent", "score": 0.5, "ts": 1000.0}]
    ranked = tcm_rerank(results, context_ts=now, half_life=100.0)
    assert ranked[0]["id"] == "recent"   # equal base score → recency wins


# ── tiered store: demote, NEVER delete ────────────────────────────────────────

def test_tier_for():
    assert tier_for(0.9) == HOT and tier_for(0.05) == COLD


def test_maintain_demotes_but_never_deletes():
    t = TieredMemory(decay=0.3)
    t.add("m1", "fact", activation=1.0)
    assert t.by_tier()[HOT] == 1
    for _ in range(5):
        t.maintain()
    assert t.by_tier()[COLD] == 1        # demoted to cold
    assert t.get("m1") is not None       # but NOT deleted


def test_access_reactivates():
    t = TieredMemory()
    t.add("m1", "x", activation=0.1)
    t.access("m1")
    assert t.get("m1")["activation"] > 0.1 and t.get("m1")["accesses"] == 1


def test_only_user_forget_deletes():
    t = TieredMemory()
    t.add("m1", "x")
    assert t.forget("m1") is True and t.get("m1") is None


def test_tiered_memory_persists_when_path_is_provided(tmp_path):
    path = tmp_path / "tiers.json"
    t = TieredMemory(path=path)
    t.add("m1", {"kind": "turn"}, activation=1.0)

    reloaded = TieredMemory(path=path)
    assert reloaded.get("m1")["content"] == {"kind": "turn"}

    reloaded.maintain()
    maintained = TieredMemory(path=path)
    assert maintained.get("m1")["activation"] == 0.5

    assert maintained.forget("m1") is True
    assert TieredMemory(path=path).get("m1") is None


# ── re-projection ─────────────────────────────────────────────────────────────

def test_needs_reprojection():
    assert needs_reprojection({"embed_version": 1}, 2) is True
    assert needs_reprojection({"embed_version": 2}, 2) is False


@pytest.mark.asyncio
async def test_reproject_reembeds_stale():
    recs = [{"content": "a", "embed_version": 1}, {"content": "b", "embed_version": 2}]

    def embedder(text):
        return [float(len(text))]

    out = await reproject(recs, current_version=2, embedder=embedder)
    assert out["reprojected"] == 1
    assert recs[0]["embed_version"] == 2 and recs[0]["vector"] == [1.0]
    assert "vector" not in recs[1]       # already current → untouched


@pytest.mark.asyncio
async def test_living_memory_reproject_stale_persists_updates(tmp_path):
    path = tmp_path / "tiers.json"
    lm = LivingMemory(embed_version=2, tiers_path=path)
    lm.tiers.add("old", "abc", activation=1.0, embed_version=1)
    lm.tiers.add("fresh", "abcd", activation=1.0, embed_version=2)

    def embedder(content):
        return [float(len(content))]

    out = await lm.reproject_stale(embedder=embedder)

    assert out["available"] is True
    assert out["checked"] == 2
    assert out["reprojected"] == 1
    reloaded = LivingMemory(tiers_path=path)
    old = reloaded.records(prefix="old")[0]
    fresh = reloaded.records(prefix="fresh")[0]
    assert old["embed_version"] == 2
    assert old["vector"] == [3.0]
    assert "vector" not in fresh


# ── core memory ───────────────────────────────────────────────────────────────

def test_core_memory_bounded_and_deduped():
    c = CoreMemory(cap=2)
    c.put("a")
    c.put("a")                 # dedup
    c.put("b")
    c.put("c")                 # evicts oldest
    assert c.list() == ["b", "c"]
    assert "[core memory]" in c.render()


def test_core_memory_persists_when_path_is_provided(tmp_path):
    path = tmp_path / "core.json"
    c = CoreMemory(cap=2, path=path)
    c.put("a")
    c.put("b")

    reloaded = CoreMemory(cap=2, path=path)
    assert reloaded.list() == ["a", "b"]

    reloaded.put("c")
    assert CoreMemory(cap=2, path=path).list() == ["b", "c"]


# ── living memory module ──────────────────────────────────────────────────────

def test_encode_respects_surprise_gate():
    lm = LivingMemory(encode_threshold=0.3)
    assert lm.encode("m1", "x", surprise=0.1)["encoded"] is False
    out = lm.encode("m2", "y", surprise=0.8)
    assert out["encoded"] is True and out["tier"] == HOT


@pytest.mark.asyncio
async def test_consolidate_phases():
    lm = LivingMemory()
    lm.encode("m1", "x", surprise=0.9)
    nrem = await lm.consolidate("nrem")
    assert nrem["phase"] == "nrem" and "demoted" in nrem
    rem = await lm.consolidate("rem")
    assert rem["phase"] == "rem"


def test_status_shape():
    lm = LivingMemory()
    lm.encode("m1", "x", surprise=0.9)
    st = lm.status()
    assert st["available"] is True and st["tiers"][HOT] == 1 and st["embed_version"] == 1


def test_living_memory_accepts_persistent_core_path(tmp_path):
    path = tmp_path / "core.json"
    lm = LivingMemory(core_path=path)
    lm.core.put("Andrei wants durable core memory.")

    reloaded = LivingMemory(core_path=path)
    assert reloaded.core.list() == ["Andrei wants durable core memory."]
    assert reloaded.status()["core"] == 1


def test_living_memory_accepts_persistent_tier_path(tmp_path):
    path = tmp_path / "tiers.json"
    lm = LivingMemory(tiers_path=path)
    lm.encode("m1", {"kind": "reflection"}, surprise=0.9)

    reloaded = LivingMemory(tiers_path=path)
    assert reloaded.records(prefix="m1")[0]["content"] == {"kind": "reflection"}
    assert reloaded.status()["tiers"][HOT] == 1
