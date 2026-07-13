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

from .automation_contracts import ContractTemplate, predicate

logger = logging.getLogger("jarvis.media_gen")

KINDS = ("image", "thumbnail", "video")


def _media_generation_contract_template() -> ContractTemplate:
    allowed = set(KINDS)

    return ContractTemplate(
        kind="media_generation",
        description="Cloud media generation must be an explicit, supported, ask-tier request.",
        constraints=(
            predicate(
                "supported-kind",
                lambda view, _now: (
                    view.get("kind") in {f"media.{k}" for k in allowed}
                    and view.get("media_kind") in allowed
                ),
                reason="unsupported_kind",
            ),
            predicate(
                "cloud-only",
                lambda view, _now: view.get("cloud") is True,
                reason="cloud_required",
            ),
            predicate(
                "target-matches-kind",
                lambda view, _now: view.get("target") == view.get("media_kind"),
                reason="target_mismatch",
            ),
            predicate(
                "has-prompt",
                lambda view, _now: int(view.get("prompt_length") or 0) > 0,
                reason="no_prompt",
            ),
        ),
        requires_approval=True,
    )


MEDIA_GENERATION_CONTRACT = _media_generation_contract_template()


class _CatalogLike(Protocol):
    """Structural type for the one method this manager uses on a media catalog.

    Kept as a Protocol rather than importing ``MediaCatalog`` so ``media_gen``
    holds *no* reference to ``media_catalog`` (which imports ``KINDS`` from here)
    — there is no import cycle, static or runtime, in either direction."""

    def add(self, **kwargs: Any) -> dict: ...


async def _maybe_await(v):
    return await v if inspect.isawaitable(v) else v


class MediaGenManager:
    def __init__(
        self,
        backends: Optional[dict] = None,
        enqueue: Optional[Callable] = None,
        agent: str = "pepper",
        *,
        catalog: Optional[_CatalogLike] = None,
        clock: Optional[Callable[[], float]] = None,
        local_guard: Optional[Callable] = None,
    ) -> None:
        self._backends = backends or {}  # kind -> async backend(prompt, opts) -> result
        self._enqueue = enqueue
        self.agent = agent
        # 0.46 wiring: when a catalog is attached, each successful *local* generation
        # is recorded (opt-in; None → behaviour is byte-identical to before).
        self._catalog = catalog
        self._clock = clock or time.time
        self._local_guard = local_guard

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

    async def _queue_cloud(self, kind: str, prompt: str, opts: Optional[dict]) -> dict:
        opts_payload = opts or {}
        contract_kind = f"media.{kind}"
        contract_payload = {
            "kind": contract_kind,
            "media_kind": kind,
            "target": kind,
            "cloud": True,
            "prompt_length": len(prompt),
            "opts_keys": sorted(str(k) for k in opts_payload)
            if isinstance(opts_payload, dict)
            else [],
        }
        try:
            decision = MEDIA_GENERATION_CONTRACT.evaluate(contract_payload, now=time.time())
        except Exception:
            logger.warning("media generation contract evaluation failed", exc_info=True)
            return {"ok": False, "reason": "contract_error", "kind": contract_kind}
        if not decision.admissible:
            return {
                "ok": False,
                "reason": decision.reason or "contract_denied",
                "kind": contract_kind,
            }
        if self._enqueue is None:
            return {"ok": False, "reason": "approval_required"}
        task_id = self._enqueue(
            self.agent,
            f"media.{kind}",
            f"Generate {kind}: {prompt[:60]}",
            payload={
                "kind": kind,
                "prompt": prompt,
                "cloud": True,
                "target": kind,
                "opts": opts_payload,
            },
            risk_tier=2,
            autonomy_level="ask",
            origin="generated",
        )
        return {"ok": False, "reason": "approval_required", "task_id": task_id}

    async def _local_allowed(self, kind: str, prompt: str, opts: dict) -> bool:
        try:
            result = await _maybe_await(self._local_guard(kind, prompt, opts))
        except Exception:
            return False
        return bool(
            isinstance(result, (tuple, list))
            and len(result) == 2
            and result[0] is True
            and isinstance(result[1], str)
            and not result[1]
        )

    def _record_local_result(
        self,
        out: dict,
        *,
        kind: str,
        prompt: str,
        result,
        backend,
        opts: Optional[dict],
    ) -> None:
        if self._catalog is None:
            return
        try:
            rec = self._catalog.add(
                kind=kind,
                prompt=prompt,
                path=self._result_path(result),
                now=self._clock(),
                backend=getattr(backend, "__name__", "local"),
                cloud=False,
                tags=list((opts or {}).get("tags") or []),
            )
            out["catalog_id"] = rec["id"]
        except Exception:
            logger.warning("media catalog record failed", exc_info=True)

    async def _generate_local(self, kind: str, prompt: str, opts: Optional[dict]) -> dict:
        backend = self._backends.get(kind)
        if backend is None:
            return {"ok": False, "reason": "backend_unavailable", "kind": kind}
        if self._local_guard is None:
            return {"ok": False, "reason": "local_guard_unavailable", "kind": kind}
        local_opts = opts or {}
        if not await self._local_allowed(kind, prompt, local_opts):
            return {"ok": False, "reason": "local_refused", "kind": kind}
        try:
            result = await _maybe_await(backend(prompt, local_opts))
        except Exception:
            logger.warning("media generation failed", exc_info=True)
            return {"ok": False, "reason": "generation_error"}
        out = {"ok": True, "kind": kind, "result": result}
        self._record_local_result(
            out,
            kind=kind,
            prompt=prompt,
            result=result,
            backend=backend,
            opts=opts,
        )
        return out

    async def generate(
        self, kind: str, prompt: str, cloud: bool = False, opts: Optional[dict] = None
    ) -> dict:
        if not self.supports(kind):
            return {"ok": False, "reason": "unsupported_kind", "kind": kind}
        if not prompt:
            return {"ok": False, "reason": "no_prompt"}
        if cloud:
            # Paid/external generation is gated through the approval queue.
            return await self._queue_cloud(kind, prompt, opts)
        return await self._generate_local(kind, prompt, opts)

    def kinds(self) -> dict:
        return {k: self.available(k) for k in KINDS}
