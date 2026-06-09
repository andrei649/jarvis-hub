"""
video_prompt.py — H21.D Video prompt-builder (manual cloud, $0 API).

The local LLM drafts/refines a video prompt to paste manually into Gemini/Veo —
a small helper, not a pipeline, and **no paid API call**. The LLM is injected;
offline it returns a deterministic structured template.
"""

from __future__ import annotations

import inspect
from typing import Optional


async def _maybe_await(v):
    return await v if inspect.isawaitable(v) else v


async def build_video_prompt(idea: str, llm: Optional[object] = None,
                             style: str = "cinematic") -> dict:
    """Refine `idea` into a paste-ready video prompt (no paid API call)."""
    if not idea:
        return {"ok": False, "reason": "no_idea"}
    if llm is not None:
        try:
            refined = await _maybe_await(llm(idea))
            if refined:
                return {"ok": True, "prompt": str(refined), "source": "llm"}
        except Exception:
            # LLM refinement failed → fall back to the heuristic prompt below
            pass
    prompt = (f"{style} shot: {idea}. Camera: slow dolly-in. Lighting: natural, soft. "
              f"Composition: rule-of-thirds. Duration: 5s. Mood: evocative. "
              f"Negative: text, watermark, distortion.")
    return {"ok": True, "prompt": prompt, "source": "template"}
