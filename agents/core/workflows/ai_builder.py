"""
ai_builder.py — H10.7 AI-assisted workflow step builder.

Turn a plain-language description ("summarize the research, then redact any
secrets") into a validated workflow-step config the visual builder can drop on
the canvas. An LLM proposes the config; we validate it down to a known-safe
shape (kind allowlist, agent allowlist, no stray fields) and fall back to a
deterministic keyword heuristic whenever there's no LLM or its output doesn't
parse — so the feature always returns something usable, offline included.

Pure-Python and LLM-agnostic: the caller injects an ``async llm(prompt) -> str``;
tests pass a fake. It returns a plain dict (not a Pipeline object), so it stays
decoupled from the engine's internals.
"""

from __future__ import annotations

import json
import re
from typing import Awaitable, Callable, Optional

# The step kinds the engine understands (engine.py: agent/router/critic/
# transform/guardrail/loop/subflow) and the H10.3 transform operators.
KNOWN_KINDS = ("agent", "router", "critic", "transform", "guardrail", "loop", "subflow")
TRANSFORM_OPS = ("formatter", "validator", "json_extract", "summarize")

LLMFn = Callable[[str], Awaitable[str]]

_PROMPT = """You design ONE step of an agent workflow. Given the request, output
ONLY a JSON object with these fields:
  "kind": one of {kinds}
  "agent": one of {agents}  (only for kind "agent" or "critic")
  "prompt": the instruction/template for the step (use {{_input}} for the input)
  "transform": one of {ops}  (only for kind "transform")
Keep it minimal; omit fields that don't apply. Request: {desc}
JSON:"""


def _extract_json(text: str) -> Optional[dict]:
    """Pull the first JSON object out of a (possibly chatty) LLM reply."""
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except (ValueError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None


def _validate(cfg: dict, available_agents: list[str]) -> Optional[dict]:
    """Reduce an arbitrary dict to a known-safe step config, or None if unusable."""
    kind = str(cfg.get("kind", "")).strip().lower()
    if kind not in KNOWN_KINDS:
        return None
    out: dict = {"kind": kind}
    prompt = cfg.get("prompt")
    if isinstance(prompt, str) and prompt.strip():
        out["prompt"] = prompt.strip()[:2000]
    if kind in ("agent", "critic"):
        agent = str(cfg.get("agent", "")).strip().lower()
        lowered = [a.lower() for a in available_agents]
        if available_agents and agent not in lowered:
            agent = available_agents[0].lower()      # default to a real agent
        out["agent"] = agent or "jarvis"
    if kind == "transform":
        op = str(cfg.get("transform", "")).strip().lower()
        out["transform"] = op if op in TRANSFORM_OPS else "summarize"
    return out


def _heuristic(desc: str, available_agents: list[str]) -> dict:
    """Deterministic keyword fallback — no LLM required."""
    d = desc.lower()

    def has(*words) -> bool:
        return any(w in d for w in words)

    if has("redact", "secret", "block", "guardrail", "pii", "mask"):
        return {"kind": "guardrail", "prompt": desc[:2000]}
    if has("json", "extract"):
        return {"kind": "transform", "transform": "json_extract", "prompt": desc[:2000]}
    if has("format", "formatter"):
        return {"kind": "transform", "transform": "formatter", "prompt": desc[:2000]}
    if has("summari"):
        return {"kind": "transform", "transform": "summarize", "prompt": desc[:2000]}
    if has("route", "choose", "pick an agent", "decide which"):
        return {"kind": "router", "prompt": desc[:2000]}
    if has("score", "critic", "grade", "evaluate quality", "retry until"):
        return {"kind": "critic", "agent": (available_agents[0].lower() if available_agents else "jarvis"),
                "prompt": desc[:2000]}
    if has("loop", "repeat", "iterate", "until"):
        return {"kind": "loop", "prompt": desc[:2000]}
    # default: an agent step, matching a named agent if the text mentions one.
    agent = "jarvis"
    for a in available_agents:
        if a.lower() in d:
            agent = a.lower()
            break
    return {"kind": "agent", "agent": agent, "prompt": desc[:2000] or "{_input}"}


async def generate_step(description: str, available_agents: Optional[list[str]] = None,
                        llm: Optional[LLMFn] = None) -> dict:
    """Return a validated workflow-step config dict for *description*.

    Tries the LLM first (validated, ``source="ai"``); otherwise — or on any
    parse/validation miss — returns the keyword heuristic (``source="heuristic"``).
    """
    available_agents = available_agents or []
    desc = (description or "").strip()
    if not desc:
        return {"kind": "agent", "agent": (available_agents[0].lower() if available_agents else "jarvis"),
                "prompt": "{_input}", "source": "heuristic"}

    if llm is not None:
        try:
            raw = await llm(_PROMPT.format(
                kinds=list(KNOWN_KINDS), agents=available_agents,
                ops=list(TRANSFORM_OPS), desc=desc))
            cfg = _extract_json(raw)
            valid = _validate(cfg, available_agents) if cfg else None
            if valid:
                valid["source"] = "ai"
                return valid
        except Exception:
            # LLM unavailable or returned junk → deterministic fallback below.
            pass

    out = _heuristic(desc, available_agents)
    out["source"] = "heuristic"
    return out
