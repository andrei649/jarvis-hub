"""
persona.py — H21.2 Persona module (personality × affect).

The cognition submodule that combines a per-agent :class:`Personality` (stable
trait distribution) with an :class:`Affect` mood attractor (alive layer) into:

  * a **prompt block** (behavioral directives banded off each trait's μ, plus a
    mood status dial) that the prompt builders inject when
    ``cognition.affect_enabled`` is on;
  * a **prosody descriptor** (rate/pitch + a cache suffix) for TTS, so the same
    text spoken in a different mood is cached separately.

The two layers are deliberately split by timescale: μ fixes *who the agent is*
and drives the prompt, while affect is the only thing that moves turn to turn.
Raw trait numbers stay out of the prompt — they are telemetry (``traits()``,
``/api/cognition/personality``) and drift-machinery input, not instructions a
local model has to decode.

Per-agent state is reproducible (stable seed) and traits are configured from
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


# Behavioral reading of each trait at its extremes: (low band, high band).
# A local 7-12B model follows an imperative far more reliably than it maps a
# float onto behavior, so the prompt carries these and the raw numbers stay in
# telemetry (``traits()``) and prosody.
_TRAIT_BANDS = {
    "warmth": (
        "keep it impersonal — no small talk, no reassurance",
        "warm and personal; acknowledge the human before the data",
    ),
    "assertiveness": (
        "offer, never push; leave the decision with the owner",
        "commit to a call and defend it; no hedging",
    ),
    "humor": (
        "no jokes, no wordplay, no wry asides",
        "dry wit when it lands, never at the owner's expense",
    ),
    "formality": (
        "plain, direct speech; contractions and shorthand are fine",
        "composed, precise register; exact words, full sentences",
    ),
    "curiosity": (
        "answer what was asked; do not widen the question",
        "follow the thread — surface the question behind the question",
    ),
}

_LOW_BAND, _HIGH_BAND = 0.3, 0.7


def trait_directives(means: dict) -> list:
    """Behavioral directives for the traits that are actually distinctive.

    Banding reads μ, never the per-turn sample. A directive that appears one
    turn and vanishes the next reads as an inconsistent character — the exact
    opposite of what a personality layer is for — and permuting the block each
    turn would churn the head of every prompt for no behavioral gain. Liveness
    belongs to mood and prosody, which move on their own clock; μ is what keeps
    the agent the same agent.

    Mid-band traits stay silent: five soft instructions every turn crowd out
    the two that actually carry the agent's identity.
    """
    picked = []
    for name, mu in means.items():
        band = _TRAIT_BANDS.get(name)
        if band is None:
            continue
        if mu <= _LOW_BAND:
            picked.append((name, band[0]))
        elif mu >= _HIGH_BAND:
            picked.append((name, band[1]))

    if not picked:
        # A deliberately mid-range persona still deserves a voice: speak the two
        # traits furthest from neutral rather than emitting an empty block.
        ranked = sorted((n for n in means if n in _TRAIT_BANDS),
                        key=lambda n: (-abs(means[n] - 0.5), n))
        picked = [(n, _TRAIT_BANDS[n][0 if means[n] < 0.5 else 1]) for n in ranked[:2]]

    return [text for _, text in picked]


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

    def means(self, agent_id: str) -> dict:
        """Configured μ per trait — the stable identity behind the sampling."""
        self._ensure(agent_id)
        return self._p[agent_id].means()

    def affect(self, agent_id: str) -> dict:
        self._ensure(agent_id)
        return self._a[agent_id].state()

    def nudge(self, agent_id: str, valence: float = 0.0, arousal: float = 0.0) -> dict:
        self._ensure(agent_id)
        return self._a[agent_id].nudge(valence, arousal)

    def relax(self, agent_id: str, dt: float) -> dict:
        self._ensure(agent_id)
        return self._a[agent_id].relax(dt)

    def prompt_block(self, agent_id: str) -> str:
        directives = trait_directives(self.means(agent_id))
        aff = self.affect(agent_id)
        return (
            f"[persona] traits: {'; '.join(directives)}. "
            f"mood(valence={aff['valence']}, arousal={aff['arousal']}) — "
            f"{_status_dial(aff['valence'])}. Let these color your tone and tactic, "
            f"not the facts. Stay honest and in character; do not flatter or over-agree."
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
