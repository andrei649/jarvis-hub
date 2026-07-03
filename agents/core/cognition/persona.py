"""
persona.py — H21.2 Persona module (personality × affect).

The cognition submodule that combines a per-agent :class:`Personality` (stable
trait distribution) with an :class:`Affect` mood attractor (alive layer) into:

  * a **prompt block** (Objective·Obstacle·Tactic framing + a status dial) that
    the prompt builders inject when ``cognition.affect_enabled`` is on;
  * a **prosody descriptor** (rate/pitch + a cache suffix) for TTS, so the same
    text spoken in a different mood is cached separately.

Per-agent state is reproducible (stable seed) and traits can be overridden from
SOUL front-matter. Master OFF ⇒ this is never consulted.
"""

from __future__ import annotations

from typing import Optional

from .affect import Affect
from .personality import Personality, stable_seed


def _status_dial(valence: float) -> str:
    if valence > 0.3:
        return "upbeat"
    if valence < -0.3:
        return "subdued"
    return "even"


class PersonaModule:
    """Per-agent personality + affect, with prompt-block and prosody outputs."""

    def __init__(self, tau: float = 600.0) -> None:
        self._tau = tau
        self._p: dict[str, Personality] = {}
        self._a: dict[str, Affect] = {}

    def configure(self, agent_id: str, traits: Optional[dict] = None,
                  valence_setpoint: float = 0.0, arousal_setpoint: float = 0.0) -> None:
        """Set an agent's traits / mood setpoints (e.g. from SOUL front-matter)."""
        self._p[agent_id] = Personality(traits=traits, seed=stable_seed(agent_id))
        self._a[agent_id] = Affect(valence_setpoint, arousal_setpoint, self._tau)

    def _ensure(self, agent_id: str) -> None:
        if agent_id not in self._p:
            self._p[agent_id] = Personality(seed=stable_seed(agent_id))
            self._a[agent_id] = Affect(tau=self._tau)

    def traits(self, agent_id: str, seed: Optional[int] = None) -> dict:
        self._ensure(agent_id)
        return self._p[agent_id].sample(seed)

    def affect(self, agent_id: str) -> dict:
        self._ensure(agent_id)
        return self._a[agent_id].state()

    def nudge(self, agent_id: str, valence: float = 0.0, arousal: float = 0.0) -> dict:
        self._ensure(agent_id)
        return self._a[agent_id].nudge(valence, arousal)

    def relax(self, agent_id: str, dt: float) -> dict:
        self._ensure(agent_id)
        return self._a[agent_id].relax(dt)

    def prompt_block(self, agent_id: str, seed: Optional[int] = None) -> str:
        traits = self.traits(agent_id, seed)
        aff = self.affect(agent_id)
        desc = ", ".join(f"{k} {v}" for k, v in traits.items())
        return (
            f"[persona] traits: {desc}; mood(valence={aff['valence']}, "
            f"arousal={aff['arousal']}) — {_status_dial(aff['valence'])}. "
            f"Let these color your tone and tactic, not the facts. Stay honest and "
            f"in character; do not flatter or over-agree."
        )

    def prosody(self, agent_id: str) -> dict:
        aff = self.affect(agent_id)
        return {
            "rate": round(1.0 + 0.2 * aff["arousal"], 2),
            "pitch": round(0.2 * aff["valence"], 2),
            "cache_suffix": f"v{aff['valence']}a{aff['arousal']}",
        }

    def voice_consent_status(self, consent_getter=None) -> dict:
        """Expose the voice-persona consent gate alongside persona state."""
        from ..voice.tts import voice_persona_consent_status
        return voice_persona_consent_status(consent_getter)

    def status(self) -> dict:
        return {
            "available": True,
            "agents": sorted(self._p.keys()),
        }
