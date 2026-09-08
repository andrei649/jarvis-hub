"""
moe_routing.py — H13.4 MoE hybrid-reasoning routing.

A single MoE model with a thinking / non-thinking mode (gpt-oss-20b,
Qwen3-30B-A3B) can collapse the fast/deep tier split: toggle "thinking" on for
complex prompts (more budget, reasoning) and off for simple ones (fast). This
module is the routing *decision* — pure and offline-testable; selecting the
actual backend/model is wired in the hybrid router (host).
"""

from __future__ import annotations

from typing import Optional

# Apache-2.0 MoE models with a hybrid thinking mode.
MOE_MODELS = {
    "gpt-oss-20b": {"supports_thinking": True, "context": 131_072},
    "qwen3-30b-a3b": {"supports_thinking": True, "context": 131_072},
}

_REASONING_HINTS = ("why", "how", "explain", "prove", "derive", "step by step",
                    "reason", "analyze", "compare", "plan", "debug", "calculate",
                    "solve", "trade-off", "design")


def decide_thinking_mode(prompt: str, threshold_chars: int = 280) -> bool:
    """Heuristic: is this prompt complex enough to warrant thinking mode?"""
    p = (prompt or "").lower()
    if any(h in p for h in _REASONING_HINTS):
        return True
    if len(prompt or "") > threshold_chars:
        return True
    if p.count("?") >= 2:
        return True
    return False


def route_moe(prompt: str, model: str = "gpt-oss-20b",
              force: Optional[bool] = None) -> dict:
    """Decide model + thinking mode + token budget for an MoE completion."""
    cfg = MOE_MODELS.get(model, {"supports_thinking": False})
    supports = bool(cfg.get("supports_thinking", False))
    thinking = force if force is not None else (decide_thinking_mode(prompt) and supports)
    return {"model": model, "thinking": bool(thinking),
            "max_tokens": 8192 if thinking else 1024,
            "directive": "/think" if thinking else "/no_think",
            "collapses_tiers": supports}


# Hermes absorption 5c — model families that spend tokens thinking before they
# answer. A name that starts with one of these (after the vendor prefix is
# dropped) gets the reasoning timeout floor in the orchestrator; the tuple is
# data, so a new family is one entry here, not a code path.
# Prefixes of the model names that think before they answer. The bare "phi4" is not
# a family here, so it never fires: a prefix test is order-independent and only the
# spelled-out reasoning variants are listed.
REASONING_FAMILIES = (
    "qwen3", "deepseek-r1", "gpt-oss", "qwq", "magistral",
    "phi4-reasoning", "phi4-mini-reasoning",
)


def is_reasoning_model(model: str | None) -> bool:
    """True when this model name belongs to a thinking / reasoning family.

    Why: a reasoning model on the deep slot spends its first minutes on
    chain-of-thought, so the flat per-agent timeout kills it on exactly the hard
    questions. The orchestrator asks this before choosing the timeout floor.
    Pure and offline: lower-case, strip whitespace, drop a vendor prefix
    ("vendor/name" → "name"), then match a family prefix (an Ollama ":tag"
    suffix rides along untouched) or an MoE entry that supports thinking.
    Hermes absorption 5c.
    """
    if not model or not isinstance(model, str):
        return False
    name = model.strip().lower()
    if not name:
        return False
    name = name.rsplit("/", 1)[-1]
    if any(name.startswith(family) for family in REASONING_FAMILIES):
        return True
    return MOE_MODELS.get(name, {}).get("supports_thinking") is True
