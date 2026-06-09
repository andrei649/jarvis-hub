"""H21.2 — Affect + personality (sampler, mood attractor, persona, front-matter)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

from agents.core.cognition.personality import Personality, DEFAULT_TRAITS, sample_trait
from agents.core.cognition.affect import Mood, Affect
from agents.core.cognition.persona import PersonaModule
from agents.core.cognition.frontmatter import parse_frontmatter


# ── personality sampler ───────────────────────────────────────────────────────

def test_realized_mean_tracks_mu():
    p = Personality()
    realized = p.realized_mean(n=3000)
    for name, spec in DEFAULT_TRAITS.items():
        assert abs(realized[name] - spec["mu"]) < 0.05   # AC: ±0.05


def test_sample_is_reproducible():
    assert Personality(seed=42).sample() == Personality(seed=42).sample()


def test_sample_has_live_variance():
    p = Personality()
    a, b = p.sample(seed=1), p.sample(seed=2)
    assert a != b                       # different seeds → different (alive)


def test_traits_bounded():
    vals = Personality().sample(seed=7).values()
    assert all(0.0 <= v <= 1.0 for v in vals)


# ── mood attractor ────────────────────────────────────────────────────────────

def test_mood_relaxes_toward_setpoint():
    m = Mood(setpoint=0.0, tau=10.0, value=1.0)
    after = m.relax(10.0)
    assert 0.0 < after < 1.0            # moved toward setpoint, not past it
    for _ in range(50):
        m.relax(10.0)
    assert abs(m.value) < 0.05          # converges to setpoint


def test_mood_clamps():
    m = Mood(lo=-1.0, hi=1.0, value=0.0)
    assert m.nudge(5.0) == 1.0
    assert m.nudge(-5.0) == -1.0


def test_affect_state_and_nudge():
    a = Affect(tau=100.0)
    a.nudge(valence=0.5, arousal=0.3)
    st = a.state()
    assert st["valence"] == 0.5 and st["arousal"] == 0.3
    a.relax(1000.0)                     # long dt → back near setpoint 0
    assert abs(a.state()["valence"]) < 0.1


# ── persona module ────────────────────────────────────────────────────────────

def test_persona_traits_reproducible_per_agent():
    assert PersonaModule().traits("jarvis") == PersonaModule().traits("jarvis")
    assert PersonaModule().traits("jarvis") != PersonaModule().traits("vision")


def test_prompt_block_contains_persona():
    block = PersonaModule().prompt_block("jarvis")
    assert "[persona]" in block and "traits:" in block and "mood(" in block
    assert any(w in block for w in ("upbeat", "even", "subdued"))


def test_prosody_descriptor():
    pm = PersonaModule()
    pm.nudge("jarvis", valence=0.5, arousal=1.0)
    pr = pm.prosody("jarvis")
    assert pr["rate"] > 1.0 and "cache_suffix" in pr and pr["pitch"] != 0.0


def test_configure_custom_traits():
    pm = PersonaModule()
    pm.configure("bot", traits={"warmth": {"mu": 0.9, "sigma": 0.0, "skew": 0.0}})
    assert pm.traits("bot") == {"warmth": 0.9}


def test_status_lists_agents():
    pm = PersonaModule()
    pm.traits("a")
    pm.traits("b")
    assert pm.status() == {"available": True, "agents": ["a", "b"]}


# ── front-matter parser ───────────────────────────────────────────────────────

def test_frontmatter_parsed():
    text = "---\nmood: cheerful\ntraits:\n  warmth: 0.8\n---\nI am the body."
    meta, body = parse_frontmatter(text)
    assert meta == {"mood": "cheerful", "traits": {"warmth": 0.8}}
    assert body == "I am the body."


def test_no_frontmatter_is_noop():
    meta, body = parse_frontmatter("# Just a SOUL\nNo front-matter here.")
    assert meta == {} and body == "# Just a SOUL\nNo front-matter here."


def test_malformed_frontmatter_tolerated():
    meta, body = parse_frontmatter("---\nnot: closed\nstill body")
    assert meta == {} and body == "---\nnot: closed\nstill body"
