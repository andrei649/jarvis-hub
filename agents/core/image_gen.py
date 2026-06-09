"""
image_gen.py — H21.C Idle image generation (no VRAM contention).

A night-shift ``image_gen`` task: unload the LLM, run the diffusion backend
(ComfyUI/diffusers, Flux FP8), then reload the LLM — so image generation never
contends with chat for VRAM. The diffusion backend + LLM load/unload are
injected (host seam); the swap orchestration is offline-testable and always
restores the LLM (even on diffusion failure).
"""

from __future__ import annotations

import inspect


async def _maybe_await(v):
    return await v if inspect.isawaitable(v) else v


class ImageGenOrchestrator:
    def __init__(self, diffusion=None, llm_unload=None, llm_load=None) -> None:
        self._diff = diffusion        # (prompt) -> image path
        self._unload = llm_unload     # () -> None
        self._load = llm_load         # () -> None

    async def generate(self, prompt: str) -> dict:
        if not prompt:
            return {"ok": False, "reason": "no_prompt"}
        if self._diff is None:
            return {"ok": False, "reason": "diffusion_unavailable"}   # host backend
        swapped = False
        if self._unload is not None:
            try:
                await _maybe_await(self._unload())
                swapped = True
            except Exception:
                pass
        try:
            path = await _maybe_await(self._diff(prompt))
            result = {"ok": True, "path": path, "swapped": swapped}
        except Exception as e:
            result = {"ok": False, "reason": "diffusion_error", "error": str(e), "swapped": swapped}
        finally:
            if swapped and self._load is not None:
                try:
                    await _maybe_await(self._load())   # always restore the LLM
                except Exception:
                    pass
        return result
