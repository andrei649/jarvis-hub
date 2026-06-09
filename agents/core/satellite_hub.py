"""
satellite_hub.py — H12.8 Split mic satellites → one shared home-GPU inference.

Several cheap microphone endpoints (Wyoming satellites, H12.4) shouldn't each
need a GPU. They register with the hub and forward their STT/inference requests
to a SINGLE shared inference backend (the home GPU). A concurrency guard models
the one-GPU contention: dispatches serialize (default ``max_concurrency=1``) so
satellites queue politely instead of thrashing the device.

The inference backend is injected (``NullInference`` echoes, for offline tests;
the real backend is a Wyoming/LM-Studio host process). Registration is explicit
(an allowlist) — an unknown satellite is rejected, not auto-trusted.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Optional

logger = logging.getLogger("jarvis.satellite_hub")


class NullInference:
    """Offline default — echoes the payload, no GPU."""

    async def process(self, kind: str, data) -> dict:
        return {"engine": "null", "kind": kind, "text": str(data)}


class SatelliteHub:
    """Registry of mic satellites + a contention-guarded shared inference rail."""

    def __init__(self, inference=None, max_concurrency: int = 1) -> None:
        self._inf = inference or NullInference()
        self.max_concurrency = max(1, int(max_concurrency))
        self._sem = asyncio.Semaphore(self.max_concurrency)
        self._sats: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._inflight = 0
        self._peak_inflight = 0

    # ── registry ─────────────────────────────────────────────────────────────

    def register(self, satellite_id: str, meta: Optional[dict] = None) -> dict:
        sid = str(satellite_id)
        with self._lock:
            if sid not in self._sats:
                self._sats[sid] = {"id": sid, "meta": meta or {}, "calls": 0,
                                   "registered_at": time.time(), "last_seen": 0.0}
            elif meta is not None:
                self._sats[sid]["meta"] = meta
            return dict(self._sats[sid])

    def unregister(self, satellite_id: str) -> bool:
        with self._lock:
            return self._sats.pop(str(satellite_id), None) is not None

    def list(self) -> "list[dict]":
        with self._lock:
            return [dict(v) for v in self._sats.values()]

    def get(self, satellite_id: str) -> Optional[dict]:
        with self._lock:
            v = self._sats.get(str(satellite_id))
            return dict(v) if v else None

    # ── dispatch ─────────────────────────────────────────────────────────────

    async def dispatch(self, satellite_id: str, payload, kind: str = "transcribe") -> dict:
        sid = str(satellite_id)
        with self._lock:
            if sid not in self._sats:
                return {"ok": False, "reason": "unknown_satellite", "satellite": sid}

        async with self._sem:  # shared GPU — serialize to model contention
            with self._lock:
                self._inflight += 1
                self._peak_inflight = max(self._peak_inflight, self._inflight)
            try:
                result = await self._inf.process(kind, payload)
            except Exception as e:
                logger.warning("satellite inference failed", exc_info=True)
                with self._lock:
                    self._inflight -= 1
                return {"ok": False, "reason": "inference_error", "error": str(e),
                        "satellite": sid}
            with self._lock:
                self._inflight -= 1
                self._sats[sid]["calls"] += 1
                self._sats[sid]["last_seen"] = time.time()
        return {"ok": True, "satellite": sid, "kind": kind, "result": result}

    def stats(self) -> dict:
        with self._lock:
            return {"satellites": len(self._sats),
                    "max_concurrency": self.max_concurrency,
                    "peak_inflight": self._peak_inflight,
                    "by_satellite": {k: v["calls"] for k, v in self._sats.items()}}
