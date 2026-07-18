"""
tech_scout.py — Proactive Technology Scout (Self-Improvement).

Jarvis already has *reactive* self-improvement: H32 Capability Acquisition
fires only when it hits a concrete capability miss (a tool call nothing can
serve). This module is the missing proactive half — a periodic, read-only
websearch scan for new AI/tech developments that might be worth Jarvis's
owner knowing about: new local inference engines, competing personal-AI
projects, on-device speech breakthroughs, and so on.

Design mirrors `observer.py`'s own rule: "observations inform, decisions
interrupt". A finding here is NEVER an action request — it has no side
effects, no executor is registered for its task kind, and it is filed at
`RiskTier.READ_ONLY` so it auto-lands in the task list / morning brief
exactly like a `monitor.alert`. Deciding whether to actually pursue one (e.g.
asking Jarvis to look into integrating something) stays a manual, separate
step — this module never files anything that looks like it needs approval
but silently does nothing when approved.

Default-off (`autonomy.tech_scout_enabled`), weekly cadence
(`autonomy.tech_scout_interval_hours`, default 168h), and it only ever calls
the already-configured `WebSearchPlugin.search()` — the same trust boundary
as the existing user-facing websearch feature (Tavily/SearXNG/DuckDuckGo,
results already taint-marked at the source). It never fetches arbitrary URLs
itself, so it carries none of H32 `GovernedResearch`'s SSRF-surface.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Awaitable, Callable

from agents.core.persistence import JsonStore

from .policy import RiskTier

logger = logging.getLogger("jarvis.autonomy.tech_scout")

DEFAULT_QUERIES = [
    "new open-source local LLM inference engine release",
    "new personal AI agent framework or assistant launch",
    "on-device speech recognition or wake-word breakthrough",
    "self-hosted AI operating system competitor",
]

MAX_SEEN = 500          # rotation cap, mirrors error_logger's problems.jsonl cap
MAX_NEW_PER_SCAN = 5    # never flood the task list/inbox from one scan

Search = Callable[..., Awaitable[list[dict]]]


class TechScoutStore(JsonStore):
    """Durable dedup ledger: which findings were already surfaced, and when the
    scout last ran — so a restart doesn't re-propose the same links."""

    def _serialize(self):
        return {"last_run": self._last_run, "seen": self._seen}

    def _deserialize(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        self._last_run = raw.get("last_run")
        seen = raw.get("seen", {})
        self._seen = seen if isinstance(seen, dict) else {}

    def last_run(self) -> float | None:
        with self._lock:
            return self._last_run

    def mark_run(self, ts: float) -> None:
        with self._lock:
            self._last_run = ts
            self._save()

    def has_seen(self, fingerprint: str) -> bool:
        with self._lock:
            return fingerprint in self._seen

    def mark_seen(self, fingerprint: str, *, url: str, title: str, ts: float) -> None:
        with self._lock:
            self._seen[fingerprint] = {"url": url, "title": title, "first_seen": ts}
            overflow = len(self._seen) - MAX_SEEN
            if overflow > 0:
                # Dicts preserve insertion order — evict the oldest entries first.
                for key in list(self._seen.keys())[:overflow]:
                    del self._seen[key]
            self._save()

    def seen_count(self) -> int:
        with self._lock:
            return len(self._seen)


def _fingerprint(url: str) -> str:
    return hashlib.sha256(url.strip().lower().encode("utf-8", errors="ignore")).hexdigest()


class TechScout:
    """Periodic, read-only technology-awareness scan → informational autonomy tasks."""

    def __init__(
        self,
        worker,
        search: Search | None,
        *,
        store: TechScoutStore | None = None,
        queries: list[str] | None = None,
        agent: str = "steve",
        max_results_per_query: int = 5,
        max_new_per_scan: int = MAX_NEW_PER_SCAN,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.worker = worker
        self.search = search
        self.store = store or TechScoutStore(None)
        self.queries = list(queries) if queries is not None else list(DEFAULT_QUERIES)
        self.agent = agent
        self.max_results_per_query = max_results_per_query
        self.max_new_per_scan = max_new_per_scan
        self._clock = clock

    async def scan(self, *, enabled: bool = True, force: bool = False,
                   interval_hours: float = 168.0) -> dict:
        """Run one scout pass. Idempotent per `interval_hours` unless `force`."""
        if not enabled:
            return {"skipped": True, "reason": "disabled"}
        if self.search is None:
            return {"skipped": True, "reason": "no_search_backend"}
        if not self.queries:
            return {"skipped": True, "reason": "no_queries_configured"}

        now = self._clock()
        last_run = self.store.last_run()
        if not force and last_run is not None and (now - last_run) < interval_hours * 3600:
            return {
                "skipped": True, "reason": "interval_not_elapsed",
                "next_eligible_in_s": interval_hours * 3600 - (now - last_run),
            }

        results_seen = new_findings = proposed = capped = 0

        for query in self.queries:
            try:
                results = await self.search(query, max_results=self.max_results_per_query)
            except Exception:
                logger.warning("tech scout search failed for %r", query, exc_info=True)
                continue
            for result in results or []:
                results_seen += 1
                url = str((result or {}).get("url") or "").strip()
                if not url:
                    continue
                fingerprint = _fingerprint(url)
                if self.store.has_seen(fingerprint):
                    continue
                new_findings += 1
                if proposed >= self.max_new_per_scan:
                    capped += 1
                    continue
                title = str(result.get("title") or url)[:200]
                snippet = str(result.get("snippet") or "")[:400]
                try:
                    await self.worker.submit(
                        agent=self.agent,
                        kind="tech_scout.finding",
                        title=f"\U0001f52d {title}",
                        payload={
                            "risk_tier": int(RiskTier.READ_ONLY),
                            "rationale": snippet or "New result for a tech-scout query.",
                            "expected": "Read-only finding — review, no action taken automatically.",
                            "url": url,
                            "query": query,
                            "source": "websearch",
                        },
                        origin="generated",
                    )
                except Exception:
                    logger.warning("tech scout submit failed for %r", url, exc_info=True)
                    continue
                proposed += 1
                self.store.mark_seen(fingerprint, url=url, title=title, ts=now)

        self.store.mark_run(now)
        if capped:
            logger.info("tech scout scan capped %d additional new finding(s) this pass", capped)
        return {
            "skipped": False,
            "queries": len(self.queries),
            "results_seen": results_seen,
            "new_findings": new_findings,
            "proposed": proposed,
            "capped": capped,
        }

    def status(self) -> dict:
        return {
            "configured": self.search is not None,
            "last_run": self.store.last_run(),
            "queries": list(self.queries),
            "total_seen": self.store.seen_count(),
        }


__all__ = ["TechScout", "TechScoutStore", "DEFAULT_QUERIES", "MAX_NEW_PER_SCAN"]
