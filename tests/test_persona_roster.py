"""Persona roster — every agent has an authored character, not a random draw.

H21.2 shipped the whole personality machine (trait sampler, mood attractor,
ensemble diversity, identity-anchored drift) but no SOUL ever declared a
``personality`` block, so all 17 agents fell back to one shared default trait
set and differed only by a name-derived seed. The numbers injected into every
prompt were noise, and the noise frequently contradicted the SOUL prose sitting
beside it — the "no tone, just numbers" agent drew the cast's second-highest
humor, the "no wit" agent its fourth.

These tests pin the fix at three levels: the SOULs actually declare characters,
the characters stay distinguishable, and the config layer no longer silently
drops or freezes what an author writes.
"""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))
sys.path.insert(0, str(repo_root / "tests"))

import yaml  # noqa: E402
from golden_harness import make_golden_orchestrator  # noqa: E402

from agents.core.cognition.frontmatter import parse_frontmatter  # noqa: E402
from agents.core.cognition.persona import PersonaModule, trait_directives  # noqa: E402
from agents.core.cognition.personality import DEFAULT_TRAITS, Personality  # noqa: E402
from agents.core.orchestrator import Orchestrator, _bench_soul_stub  # noqa: E402

TRAIT_NAMES = set(DEFAULT_TRAITS)
DEFAULT_MEANS = {k: round(float(v["mu"]), 3) for k, v in DEFAULT_TRAITS.items()}
SOULS = sorted(p for p in (repo_root / "agents").glob("*/SOUL.md"))
REGISTRY = yaml.safe_load(
    (repo_root / "agents" / "_system" / "agents.yaml").read_text(encoding="utf-8")
)


def _meta(soul_path):
    meta, body = parse_frontmatter(soul_path.read_text(encoding="utf-8"))
    return meta, body


# ── the roster carries authored characters ────────────────────────────────────

def test_every_soul_ships_a_persona_block():
    assert SOULS, "no SOUL.md files discovered"
    missing = []
    for path in SOULS:
        meta, _ = _meta(path)
        personality = meta.get("personality") if isinstance(meta.get("personality"), dict) else {}
        traits = meta.get("traits") or personality.get("traits")
        if not isinstance(traits, dict) or set(traits) != TRAIT_NAMES:
            missing.append(path.parent.name)
    assert missing == [], f"SOULs without a complete persona block: {missing}"


@pytest.mark.asyncio
async def test_no_active_agent_falls_back_to_the_shared_defaults(monkeypatch, tmp_path):
    """A persona identical to DEFAULT_TRAITS means the SOUL was never read."""
    orch, _ = await make_golden_orchestrator(monkeypatch, tmp_path)
    persona = orch.cognition.module("persona")

    unauthored = [a for a in sorted(orch.agents) if persona.means(a) == DEFAULT_MEANS]
    assert unauthored == [], f"agents still on the default persona: {unauthored}"


@pytest.mark.asyncio
async def test_roster_stays_diverse_with_margin(monkeypatch, tmp_path):
    """Distinctness must be designed, not lucky.

    The previous accidental spread cleared the ε=0.1 floor by 17%; authored
    characters are expected to hold a far wider berth, so a future edit that
    collapses two agents toward each other fails here rather than in the field.
    """
    orch, _ = await make_golden_orchestrator(monkeypatch, tmp_path)
    diversity = orch.cognition.module("ensemble").diversity()

    assert diversity["ok"], diversity["violations"]
    assert diversity["min_distance"] >= 0.15, diversity


@pytest.mark.asyncio
async def test_ensemble_anchor_is_mu_not_a_live_sample(monkeypatch, tmp_path):
    """The ±0.10 lifetime drift bound is only meaningful against a stable anchor."""
    orch, _ = await make_golden_orchestrator(monkeypatch, tmp_path)
    persona = orch.cognition.module("persona")
    ensemble = orch.cognition.module("ensemble")

    for agent_id in sorted(orch.agents):
        assert ensemble.diff(agent_id)["baseline"] == persona.means(agent_id)


def test_persona_config_never_reaches_the_prompt():
    for path in SOULS:
        _, body = _meta(path)
        assert "personality:" not in body, path.parent.name
        assert "mu:" not in body, path.parent.name


# ── the characters match the prose they were derived from ─────────────────────

@pytest.mark.parametrize("agent_id,trait,bound,limit", [
    # "No tone. Just numbers." — Gecko refuses to have a personality.
    ("gecko", "humor", "max", 0.3),
    ("gecko", "warmth", "max", 0.3),
    # "Clipped-operational. No metaphors, no wit."
    ("friday", "humor", "max", 0.3),
    # "Ruthless about routing", "surgical", never second-guesses a delegation.
    ("jarvis", "assertiveness", "min", 0.7),
    # "Warm, maternal" — must not read as the cast's stiffest register.
    ("frigga", "warmth", "min", 0.7),
    ("frigga", "formality", "max", 0.3),
    # "Assume breach and verify everything."
    ("ultron", "curiosity", "min", 0.7),
    # "Suggestions, never commands"; the only agent allowed to say stop working.
    ("jerome", "assertiveness", "max", 0.3),
    # "Every substantive claim has a source" — the deepest reader in the cast.
    ("vision", "curiosity", "min", 0.7),
])
def test_character_invariants_hold(agent_id, trait, bound, limit):
    meta, _ = _meta(repo_root / "agents" / agent_id / "SOUL.md")
    mu = float(meta["personality"]["traits"][trait]["mu"])
    if bound == "max":
        assert mu <= limit, f"{agent_id}.{trait}={mu} contradicts its SOUL prose"
    else:
        assert mu >= limit, f"{agent_id}.{trait}={mu} contradicts its SOUL prose"


def test_code_switching_agents_declare_a_wide_register():
    """Howard mirrors the owner and Veronica runs five voice profiles.

    σ is how a SOUL declares "this register is supposed to move"; it feeds the
    sampled state the persona API and the drift machinery read.
    """
    for agent_id in ("howard", "veronica"):
        meta, _ = _meta(repo_root / "agents" / agent_id / "SOUL.md")
        sigma = float(meta["personality"]["traits"]["formality"]["sigma"])
        assert sigma >= 0.15, f"{agent_id} is supposed to code-switch (σ={sigma})"


# ── the config layer keeps what an author writes ──────────────────────────────

def test_partial_traits_merge_over_the_defaults():
    """Tuning one trait must not silently delete the other four."""
    merged = Orchestrator._normalize_trait_config({"warmth": {"mu": 0.9}})
    assert set(merged) == TRAIT_NAMES
    assert merged["warmth"]["mu"] == 0.9
    assert merged["curiosity"]["mu"] == DEFAULT_TRAITS["curiosity"]["mu"]


def test_omitted_sigma_inherits_liveness_instead_of_freezing():
    """σ=0 is the documented 'personality feels flat' defect — never a default."""
    from_dict = Orchestrator._normalize_trait_config({"warmth": {"mu": 0.8}})
    from_scalar = Orchestrator._normalize_trait_config({"warmth": 0.8})
    for cfg in (from_dict, from_scalar):
        assert cfg["warmth"]["sigma"] == DEFAULT_TRAITS["warmth"]["sigma"] > 0


def test_explicit_sigma_zero_is_still_honored():
    cfg = Orchestrator._normalize_trait_config({"warmth": {"mu": 0.8, "sigma": 0.0}})
    assert cfg["warmth"]["sigma"] == 0.0


def test_unauthored_traits_stay_none():
    assert Orchestrator._normalize_trait_config(None) is None
    assert Orchestrator._normalize_trait_config({}) is None


# ── the prompt block speaks behavior ──────────────────────────────────────────

def test_prompt_block_carries_directives_not_raw_floats():
    pm = PersonaModule()
    pm.configure("flat", traits=Orchestrator._normalize_trait_config(
        {"warmth": {"mu": 0.05}, "humor": {"mu": 0.02}, "assertiveness": {"mu": 0.9}}))
    block = pm.prompt_block("flat")

    assert "no jokes" in block and "impersonal" in block and "commit to a call" in block
    assert "0.05" not in block and "0.02" not in block and "0.9" not in block


def test_mid_band_traits_stay_silent():
    """Five soft instructions per turn would crowd out the identity-bearing two."""
    directives = trait_directives({"warmth": 0.5, "assertiveness": 0.9,
                                   "humor": 0.5, "formality": 0.5, "curiosity": 0.5})
    assert directives == ["commit to a call and defend it; no hedging"]


def test_a_wholly_mid_band_persona_still_speaks():
    directives = trait_directives(dict.fromkeys(TRAIT_NAMES, 0.5) | {"curiosity": 0.45})
    assert directives, "an all-neutral persona must not produce an empty block"


def test_directives_hold_still_while_mood_moves():
    """Banding reads μ, so a directive can neither flicker nor reorder."""
    pm = PersonaModule()
    pm.configure("agent", traits=Orchestrator._normalize_trait_config(
        # μ sits just inside the high band with liveness wide enough to cross it,
        # so a sample-driven block would visibly churn here.
        {"formality": {"mu": 0.72, "sigma": 0.2}, "curiosity": {"mu": 0.78, "sigma": 0.2}}))

    first = pm.prompt_block("agent")
    seen = set()
    for _ in range(30):
        pm.nudge("agent", valence=0.05, arousal=0.02)
        seen.add(pm.prompt_block("agent").split("mood(")[0])
    assert seen == {first.split("mood(")[0]}
    assert pm.prompt_block("agent") != first, "mood should still be moving"


# ── liveness is observable ────────────────────────────────────────────────────

def test_seedless_samples_advance_so_sigma_has_an_effect():
    """A per-call reseed would hand back one frozen draw forever."""
    p = Personality(traits={"warmth": {"mu": 0.5, "sigma": 0.2}}, seed=11)
    draws = {p.sample()["warmth"] for _ in range(20)}
    assert len(draws) > 1


def test_equally_seeded_personalities_still_agree():
    a, b = Personality(seed=42), Personality(seed=42)
    assert [a.sample() for _ in range(5)] == [b.sample() for _ in range(5)]


def test_means_are_free_of_liveness():
    p = Personality(traits={"warmth": {"mu": 0.8, "sigma": 0.3}}, seed=3)
    assert p.means() == {"warmth": 0.8}
    assert p.means() == p.means()


# ── the registry and the SOULs agree ──────────────────────────────────────────

def test_every_active_agent_has_a_soul_and_vice_versa():
    registered = {a for a, c in REGISTRY["agents"].items()
                  if (c or {}).get("status", "active") == "active"}
    on_disk = {p.parent.name for p in SOULS}
    assert registered == on_disk, (
        f"registry-only: {sorted(registered - on_disk)}; "
        f"soul-only: {sorted(on_disk - registered)}"
    )


def test_registry_and_soul_archetypes_match():
    """Two sources of truth for one fact drift; this makes the drift loud."""
    drift = []
    for agent_id, entry in REGISTRY["agents"].items():
        meta, _ = _meta(repo_root / "agents" / agent_id / "SOUL.md")
        if str(meta.get("archetype", "")).lower() != str((entry or {}).get("archetype", "")).lower():
            drift.append((agent_id, entry.get("archetype"), meta.get("archetype")))
    assert drift == [], f"registry/SOUL archetype drift: {drift}"


def test_active_roster_stays_within_the_cardinality_cap():
    cap = REGISTRY["jarvis"]["cardinality_cap"]
    active = sum(1 for c in REGISTRY["agents"].values()
                 if (c or {}).get("status", "active") == "active")
    assert active <= cap, (
        f"{active} active agents exceeds cardinality_cap={cap}; agents.yaml requires an "
        "architecture review before going over"
    )


def test_bench_names_never_collide_with_active_agents_or_sub_brands():
    """A reserved name is only reservable if promoting it stays unambiguous.

    The sub-brands come from NERVA_VISION.md §2; `hermes` is additionally the
    upstream project this repo benchmarks against, so it is not a free name.
    """
    reserved = {"cortex", "atlas", "synapse", "nerva", "digitaholic", "hermes"}
    bench = set(REGISTRY["bench"])
    assert not (bench & set(REGISTRY["agents"])), "a bench name shadows an active agent"
    assert not (bench & reserved), f"bench name collides with a reserved name: {bench & reserved}"


# ── a promoted bench agent is born with a character ───────────────────────────

def test_bench_promotion_stub_ships_a_persona():
    """Promotion writes this file; without a persona block the new agent would
    silently inherit the shared defaults — the exact defect the roster fixes."""
    meta, body = parse_frontmatter(_bench_soul_stub("bruce", "Bruce", "Data Science"))

    assert meta["id"] == "bruce" and meta["archetype"] == "Data Science"
    traits = meta["personality"]["traits"]
    assert set(traits) == TRAIT_NAMES
    assert all(float(t["sigma"]) > 0 for t in traits.values()), "a frozen persona is not alive"
    assert Orchestrator._normalize_trait_config(traits) is not None
    assert "## Voice & Tone" in body


def test_bench_promotion_stub_is_not_the_shared_default():
    meta, _ = parse_frontmatter(_bench_soul_stub("bruce", "Bruce", "Data Science"))
    cfg = Orchestrator._normalize_trait_config(meta["personality"]["traits"])
    assert Orchestrator._trait_mu(cfg) != DEFAULT_MEANS


def test_bench_promotion_stub_carries_no_personal_details():
    """Shipped SOULs are generic; personal specifics live in SOUL.local.md."""
    body = _bench_soul_stub("bruce", "Bruce", "Data Science").lower()
    assert "andrei" not in body
    assert "the owner" in body


def test_house_agent_is_code_enforced_local_only():
    """Hestia's SOUL promises the house picture never leaves the LAN.

    Room-level occupancy answers "is anyone home right now", so the promise has
    to hold in code, not only in the registry — `get_agent_policy` consults
    LOCAL_ONLY_AGENTS before any `llm_policy` the registry declares.
    """
    from agents.core.llm.hybrid_router import LOCAL_ONLY_AGENTS

    assert "hestia" in LOCAL_ONLY_AGENTS
    assert REGISTRY["agents"]["hestia"]["llm_policy"] == "local"
    _, body = _meta(repo_root / "agents" / "hestia" / "SOUL.md")
    assert "No cloud" in body
