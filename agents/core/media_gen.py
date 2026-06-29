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
import time
from typing import Any, Callable, Optional, Protocol

logger = logging.getLogger("jarvis.media_gen")

KINDS = ("image", "thumbnail", "video")


class _CatalogLike(Protocol):
    """Structural type for the one method this manager uses on a media catalog.

    Kept as a Protocol rather than importing ``MediaCatalog`` so ``media_gen``
    holds *no* reference to ``media_catalog`` (which imports ``KINDS`` from here)
    — there is no import cycle, static or runtime, in either direction."""

    def add(self, **kwargs: Any) -> dict:
        ...


async def _maybe_await(v):
    return await v if inspect.isawaitable(v) else v


class MediaGenManager:
    def __init__(self, backends: Optional[dict] = None, enqueue: Optional[Callable] = None,
                 agent: str = "pepper", *, catalog: Optional[_CatalogLike] = None,
                 clock: Optional[Callable[[], float]] = None) -> None:
        self._backends = backends or {}     # kind -> async backend(prompt, opts) -> result
        self._enqueue = enqueue
        self.agent = agent
        # 0.46 wiring: when a catalog is attached, each successful *local* generation
        # is recorded (opt-in; None → behaviour is byte-identical to before).
        self._catalog = catalog
        self._clock = clock or time.time

    @staticmethod
    def _result_path(result) -> str:
        """Best-effort extraction of the produced artifact's path/url from a
        backend result (dicts vary by backend; a plain str is taken as the path)."""
        if isinstance(result, dict):
            for key in ("path", "file", "url", "uri"):
                if result.get(key):
                    return str(result[key])
            return ""
        return result if isinstance(result, str) else ""

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
            logger.warning("media generation failed", exc_info=True)
            return {"ok": False, "reason": "generation_error"}
        out = {"ok": True, "kind": kind, "result": result}
        # Catalog the successful local generation (opt-in, best-effort: a catalog
        # hiccup must never fail a generation that already produced an artifact).
        if self._catalog is not None:
            try:
                rec = self._catalog.add(
                    kind=kind, prompt=prompt, path=self._result_path(result),
                    now=self._clock(), backend=getattr(backend, "__name__", "local"),
                    cloud=False, tags=list((opts or {}).get("tags") or []),
                )
                out["catalog_id"] = rec["id"]
            except Exception:
                logger.warning("media catalog record failed", exc_info=True)
        return out

    def kinds(self) -> dict:
        return {k: self.available(k) for k in KINDS}
