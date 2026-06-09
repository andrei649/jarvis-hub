"""
media_gen.py — H12.24 Governed media generation (content-factory).

Generate images / thumbnails / video through injectable backends, *gated*: local
backends run inline; a **cloud** (paid/external) generation never fires
unprompted — it enqueues an ask-tier approval task. Pure and offline-testable;
the diffusion/cloud backends are the host seam.
"""

from __future__ import annotations

import inspect
import logging
from typing import Callable, Optional

logger = logging.getLogger("jarvis.media_gen")

KINDS = ("image", "thumbnail", "video")


async def _maybe_await(v):
    return await v if inspect.isawaitable(v) else v


class MediaGenManager:
    def __init__(self, backends: Optional[dict] = None, enqueue: Optional[Callable] = None,
                 agent: str = "pepper") -> None:
        self._backends = backends or {}     # kind -> async backend(prompt, opts) -> result
        self._enqueue = enqueue
        self.agent = agent

    @staticmethod
    def supports(kind: str) -> bool:
        return kind in KINDS

    def available(self, kind: str) -> bool:
        return kind in self._backends

    async def generate(self, kind: str, prompt: str, cloud: bool = False,
                       opts: Optional[dict] = None) -> dict:
        if not self.supports(kind):
            return {"ok": False, "reason": "unsupported_kind", "kind": kind}
        if not prompt:
            return {"ok": False, "reason": "no_prompt"}
        if cloud:
            # Paid/external generation is gated through the approval queue.
            if self._enqueue is None:
                return {"ok": False, "reason": "approval_required"}
            task_id = self._enqueue(self.agent, f"media.{kind}", f"Generate {kind}: {prompt[:60]}",
                                    payload={"kind": kind, "prompt": prompt, "cloud": True,
                                             "target": kind, "opts": opts or {}},
                                    risk_tier=2, autonomy_level="ask", origin="generated")
            return {"ok": False, "reason": "approval_required", "task_id": task_id}
        backend = self._backends.get(kind)
        if backend is None:
            return {"ok": False, "reason": "backend_unavailable", "kind": kind}
        try:
            result = await _maybe_await(backend(prompt, opts or {}))
        except Exception:
            logger.warning("media generation failed (kind=%s)", kind, exc_info=True)
            return {"ok": False, "reason": "generation_error"}
        return {"ok": True, "kind": kind, "result": result}

    def kinds(self) -> dict:
        return {k: self.available(k) for k in KINDS}
