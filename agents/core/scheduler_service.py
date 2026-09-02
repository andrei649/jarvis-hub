"""scheduler_service.py — APScheduler wiring extracted from the Orchestrator (CLN-2).

Owns the registration of the cron/interval jobs (daily digests, the autonomy
budget reset, the learning-loop promotions, the log-bug scans, and the optional
WorldView KG sync) plus the job bodies that have no external callers. It holds a
back-reference to the orchestrator and reads its live collaborators
(heartbeat_scheduler, autonomy, log_scanner, channels, settings) at call time —
the same delegation pattern as ComponentRegistry / ChannelManager.

Two job bodies deliberately stay on the Orchestrator because callers reach them
there: ``_run_learning_loop`` (the admin endpoint ``POST /api/learning/propose``)
and ``_run_worldview_kg_sync`` (invoked unbound in tests). This service registers
those via the orchestrator back-ref.
"""

from __future__ import annotations

import asyncio
import logging
import os

from agents.core.paths import data_path

from .autonomy.digest import build_evening_retro, build_morning_brief
from .orchestrator_bindings import bind_external_orchestrator_attribute

logger = logging.getLogger("jarvis.orchestrator")


class SchedulerService:
    def __init__(self, orchestrator):
        self._orch = orchestrator

    def schedule_all(self) -> None:
        """Register every scheduled job (called once from start_channels)."""
        self.schedule_daily_digests()
        self.schedule_log_scans()
        self.schedule_learning_loop()
        self.schedule_daily_budget_reset()
        self.schedule_worldview_kg_sync()
        self.schedule_retention()
        self.schedule_memory_maintenance()
        self.schedule_tech_scout()
        self.schedule_llm_backend_refresh()

    # ── scheduling (registration) ─────────────────────────────────
    def schedule_daily_digests(self):
        """Cron the morning brief (07:00) and evening retro (20:00) — H6.4."""
        sched = getattr(self._orch.heartbeat_scheduler, "scheduler", None)
        if sched is None:
            return
        try:
            sched.add_job(self.run_daily_digest, "cron", hour=7, minute=0,
                          args=["morning"], id="autonomy-morning-brief", replace_existing=True)
            sched.add_job(self.run_daily_digest, "cron", hour=20, minute=0,
                          args=["evening"], id="autonomy-evening-retro", replace_existing=True)
            logger.info("Scheduled daily digests: morning 07:00, evening 20:00")
        except Exception as e:
            logger.warning(f"Failed to schedule daily digests: {e}")

    def schedule_daily_budget_reset(self):
        """Reset the autonomy daily-spend ceiling at local midnight (BUG-10).

        Without this, AutonomyPolicy._spent_today accrues across calendar days
        until a restart, so `daily_ceiling` fills permanently and blocks
        autonomous spend. reset_daily() existed but was never scheduled in prod.
        """
        sched = getattr(self._orch.heartbeat_scheduler, "scheduler", None)
        policy = getattr(getattr(self._orch, "autonomy", None), "policy", None)
        if sched is None or policy is None:
            return
        try:
            sched.add_job(policy.reset_daily, "cron", hour=0, minute=0,
                          id="autonomy-daily-budget-reset", replace_existing=True)
            logger.info("Scheduled daily autonomy-budget reset: 00:00")
        except Exception as e:
            logger.warning(f"Failed to schedule daily budget reset: {e}")

    def schedule_learning_loop(self):
        """H7.11 — periodically propose agent promotions to the decision inbox.

        Cadence from config (autonomy.learning_loop_interval_hours, default 168h =
        weekly). Each run proposes gated, reversible promotions via the queue, and
        (DRA-41) gated prompt optimizations from the same learning-loop evidence.
        """
        sched = getattr(self._orch.heartbeat_scheduler, "scheduler", None)
        if sched is None:
            return
        try:
            hours = float((self._orch.config.get("autonomy", {}) or {}).get(
                "learning_loop_interval_hours", 168))
        except Exception:
            hours = 168.0
        if hours <= 0:
            return
        try:
            sched.add_job(self._orch._run_learning_loop, "interval", hours=hours,
                          id="learning-loop-promotions", replace_existing=True)
            # DRA-41 — the H20.4 self-evolution twin: same cadence, same inbox,
            # nothing self-applies. This is the unattended production caller the
            # trajectory/prompt-optimization mechanism never had.
            sched.add_job(self._orch._run_prompt_evolution, "interval", hours=hours,
                          id="learning-loop-prompt-evolution", replace_existing=True)
            logger.info("Scheduled learning-loop promotions + prompt evolution every %sh", hours)
        except Exception as e:
            logger.warning(f"Failed to schedule learning loop: {e}")

    def schedule_log_scans(self):
        """Register the three log-bug-finding cadences on the APScheduler.

        quick  — every 15 min: spike + new-code detection
        hourly — every hour:   trend analysis + backlog sync
        daily  — 07:05 daily:  full 24-h digest → memory_logs/reports/
        """
        sched = getattr(self._orch.heartbeat_scheduler, "scheduler", None)
        if sched is None:
            return
        try:
            sched.add_job(self.run_log_quick_scan, "interval", seconds=900,
                          id="log-scan-quick", replace_existing=True)
            sched.add_job(self.run_log_hourly_scan, "interval", seconds=3600,
                          id="log-scan-hourly", replace_existing=True)
            sched.add_job(self.run_log_daily_scan, "cron", hour=7, minute=5,
                          id="log-scan-daily", replace_existing=True)
            logger.info("Scheduled log-bug scans: quick/15min, hourly, daily/07:05")
        except Exception as e:
            logger.warning(f"Failed to schedule log scans: {e}")

    def schedule_worldview_kg_sync(self):
        """Periodically sync the WorldView ontology into the knowledge graph (H19.3.5).

        OFF by default — like the Oracle watcher, a privacy-first local product should not
        poll a service unsolicited. Enable with JARVIS_WORLDVIEW_KG_SYNC=1 or the
        `worldview.kg_sync_enabled` setting. Each pass degrades to a no-op when WorldView
        is unreachable (the plugin fails closed), so an enabled-but-offline deployment is
        harmless. Skipped under JARVIS_TESTING.
        """
        from agents.core.env_config import env_flag
        if env_flag("JARVIS_TESTING"):
            return
        enabled = env_flag("JARVIS_WORLDVIEW_KG_SYNC") or self._orch.get_setting(
            "worldview.kg_sync_enabled", False
        )
        if not enabled:
            return
        sched = getattr(self._orch.heartbeat_scheduler, "scheduler", None)
        if sched is None:
            return
        interval = max(60, int(self._orch.get_setting("worldview.kg_sync_interval", 900)))
        try:
            sched.add_job(self._orch._run_worldview_kg_sync, "interval", seconds=interval,
                          id="worldview-kg-sync", replace_existing=True)
            logger.info("Scheduled WorldView KG sync every %ss", interval)
        except Exception as e:
            logger.warning(f"Failed to schedule WorldView KG sync: {e}")

    def schedule_retention(self):
        """Daily data-retention sweep (H23.10) — prune transcripts, audit and private ingestion past TTL.

        Always registered, but a no-op at run time unless ``retention.enabled`` is
        set, so the job is harmless by default. Runs at 03:30, off the busy hours.
        """
        sched = getattr(self._orch.heartbeat_scheduler, "scheduler", None)
        if sched is None:
            return
        try:
            sched.add_job(self.run_retention_purge, "cron", hour=3, minute=30,
                          id="data-retention-sweep", replace_existing=True)
            logger.info("Scheduled data-retention sweep: 03:30 daily (no-op unless retention.enabled)")
        except Exception as e:
            logger.warning(f"Failed to schedule retention sweep: {e}")

    def schedule_memory_maintenance(self):
        """Nightly LivingMemory consolidation + decay inspection (O26-P2.2).

        Always registered, but the body is gated by ``cognition.memory_enabled``.
        The decay half only ranks/candidates low-activation items; it never
        deletes without an explicit user forget action.
        """
        sched = getattr(self._orch.heartbeat_scheduler, "scheduler", None)
        if sched is None:
            return
        try:
            sched.add_job(self.run_memory_maintenance, "cron", hour=2, minute=40,
                          id="memory-consolidation-decay", replace_existing=True)
            logger.info("Scheduled memory maintenance: 02:40 daily")
        except Exception:
            logger.warning("Failed to schedule memory maintenance", exc_info=True)

    def schedule_tech_scout(self):
        """Weekly proactive technology scan (Self-Improvement, default-off).

        Always registered, but a no-op unless ``autonomy.tech_scout_enabled`` is
        set — same harmless-by-default posture as ``schedule_retention``. Runs
        Monday 09:30; ``TechScout.scan`` is separately idempotent per
        ``autonomy.tech_scout_interval_hours`` (168h/weekly default), so a missed
        or restarted run just catches up on the next tick instead of duplicating.
        """
        sched = getattr(self._orch.heartbeat_scheduler, "scheduler", None)
        if sched is None:
            return
        try:
            sched.add_job(self.run_tech_scout, "cron", hour=9, minute=30, day_of_week="mon",
                          id="tech-scout-scan", replace_existing=True)
            logger.info("Scheduled tech scout: weekly Mon 09:30 (no-op unless autonomy.tech_scout_enabled)")
        except Exception:
            logger.warning("Failed to schedule tech scout", exc_info=True)

    def schedule_llm_backend_refresh(self):
        """Re-probe the local LLM backends every 5 minutes (H23 log finding).

        `LLMRouter.detect()` otherwise runs exactly once, at startup, so a model
        server started *after* Jarvis stayed invisible for the life of the
        process. Observed in a real session: Ollama was down at boot and
        answering from 11:38, and Howard kept falling back for the next two hours.

        The pass is two GETs on a 3s budget unless something actually changed —
        `refresh_availability` only pays for a full re-detect on a transition.
        """
        sched = getattr(self._orch.heartbeat_scheduler, "scheduler", None)
        if sched is None:
            return
        try:
            sched.add_job(self.run_llm_backend_refresh, "interval", seconds=300,
                          id="llm-backend-refresh", replace_existing=True)
            logger.info("Scheduled local LLM backend re-probe every 5 min")
        except Exception:
            logger.warning("Failed to schedule the LLM backend re-probe", exc_info=True)

    # ── job bodies (no external callers) ──────────────────────────
    async def run_llm_backend_refresh(self):
        """One availability pass. Never raises — a failed probe is not fatal."""
        router = getattr(self._orch, "llm_router", None)
        refresh = getattr(router, "refresh_availability", None)
        if refresh is None:
            return {"skipped": True, "reason": "unavailable"}
        try:
            return {"redetected": bool(await refresh())}
        except Exception:
            logger.warning("Local LLM backend re-probe failed", exc_info=True)
            return {"skipped": True, "reason": "probe_failed"}

    async def run_tech_scout(self):
        """Run one tech-scout pass, reading live settings each time (H27-self-improve)."""
        scout = getattr(self._orch, "tech_scout", None)
        if scout is None:
            return {"skipped": True, "reason": "unavailable"}
        enabled = bool(self._orch.get_setting("autonomy.tech_scout_enabled", False))
        try:
            interval_hours = float(self._orch.get_setting("autonomy.tech_scout_interval_hours", 168))
        except (TypeError, ValueError):
            interval_hours = 168.0
        queries = self._orch.get_setting("autonomy.tech_scout_queries", None)
        if queries:
            scout.queries = list(queries)
        try:
            result = await scout.scan(enabled=enabled, interval_hours=interval_hours)
            logger.info("Tech scout scan: %s", result)
            return result
        except Exception:
            logger.warning("Tech scout scan failed", exc_info=True)
            return {"skipped": True, "reason": "scan_failed"}

    async def run_memory_maintenance(self):
        """Run the nightly memory maintenance pass.

        LivingMemory does the NREM/REM tier maintenance; the H14 decay store is
        inspected for low-activation candidates but never auto-forgotten.
        """
        cog = getattr(self._orch, "cognition", None)
        if cog is None or not cog.sub_enabled("memory_enabled"):
            return {"skipped": True, "reason": "cognition_memory_disabled"}
        living = cog.module("memory")
        if living is None:
            return {"skipped": True, "reason": "living_memory_unavailable"}

        try:
            nrem = await living.consolidate("nrem")
            rem = await living.consolidate("rem")
        except Exception:
            logger.warning("LivingMemory consolidation failed", exc_info=True)
            return {"skipped": True, "reason": "living_memory_failed"}

        reprojection = {"available": False, "reason": "reprojection_unavailable"}
        if hasattr(living, "reproject_stale"):
            try:
                memory = getattr(self._orch, "memory", None)
                embedder = getattr(memory, "embed", None)
                if callable(embedder):
                    reprojection = await living.reproject_stale(embedder=embedder)
                else:
                    reprojection = await living.reproject_stale()
            except Exception:
                logger.warning("LivingMemory re-projection failed", exc_info=True)
                reprojection = {"available": False, "reason": "reprojection_failed"}

        decay_summary = {"available": False, "ranked": 0, "candidates": 0}
        decay = getattr(self._orch, "decay", None)
        if decay is not None:
            try:
                threshold = float(self._orch.get_setting("memory.decay_candidate_threshold", 0.0))
            except Exception:
                threshold = 0.0
            try:
                ranking = await asyncio.to_thread(decay.ranking, limit=1000)
                candidates = await asyncio.to_thread(decay.forget_candidates, threshold)
                decay_summary = {
                    "available": True,
                    "ranked": len(ranking or []),
                    "candidates": len(candidates or []),
                    "threshold": threshold,
                }
            except Exception:
                logger.warning("Decay inspection failed", exc_info=True)
                decay_summary = {"available": False, "ranked": 0, "candidates": 0}

        result = {
            "skipped": False,
            "living_memory": {"nrem": nrem, "rem": rem},
            "reprojection": reprojection,
            "decay": decay_summary,
        }
        bind_external_orchestrator_attribute(
            self._orch, "last_memory_maintenance", result
        )
        logger.info(
            "Memory maintenance complete: nrem_total=%s rem_recombined=%s "
            "reprojected=%s decay_ranked=%s decay_candidates=%s",
            nrem.get("total") if isinstance(nrem, dict) else None,
            rem.get("recombined") if isinstance(rem, dict) else None,
            reprojection.get("reprojected") if isinstance(reprojection, dict) else None,
            decay_summary.get("ranked"),
            decay_summary.get("candidates"),
        )
        return result

    async def run_retention_purge(self):
        """Run the retention sweep off the event loop (file + SQLite I/O)."""
        if not self._orch.get_setting("retention.enabled", False):
            return

        from agents.core import retention
        try:
            watcher = getattr(self._orch, "ingestion_watcher", None)
            result = await asyncio.to_thread(
                retention.run_retention,
                self._orch.get_setting,
                getattr(self._orch, "audit", None),
                ingestion_pipeline=getattr(watcher, "pipeline", None),
            )
            logger.info("Retention sweep complete: %s", result)
            return result
        except Exception as e:
            logger.warning(f"Retention sweep failed: {e}")

    async def run_log_quick_scan(self):
        """15-min scan: submit autonomy alert on spike or new error code."""
        if not self._orch.get_setting("system.log_scan_enabled", True):
            return
        try:
            problems_path = str(data_path("problems.jsonl"))
            result = self._orch.log_scanner.quick_scan(problems_path)
            if result.healthy:
                return
            issues = ", ".join(
                f"{i['code']}×{i['count']}" for i in result.top_issues[:3]
            )
            parts = []
            if result.spike_detected:
                parts.append(f"spike: {result.total_errors} errors in 15 min")
            if result.new_codes:
                parts.append(f"new codes: {', '.join(result.new_codes[:3])}")
            title = "Log spike detected — " + "; ".join(parts)
            if issues:
                title += f" [{issues}]"
            await self._orch.autonomy.submit(
                agent="steve", kind="monitor.log_spike", title=title,
                payload={"risk_tier": 0, "spike": result.spike_detected,
                         "new_codes": result.new_codes,
                         "total_errors": result.total_errors},
                origin="log_scanner",
            )
        except Exception as e:
            logger.warning(f"Log quick scan failed: {e}")

    async def run_log_hourly_scan(self):
        """Hourly scan: trend analysis and backlog sync."""
        if not self._orch.get_setting("system.log_scan_enabled", True):
            return
        try:
            problems_path = str(data_path("problems.jsonl"))
            result = self._orch.log_scanner.hourly_scan(problems_path)
            from .autonomy.error_logger import sync_problems_to_diagnostics
            sync_problems_to_diagnostics()
            if result.healthy:
                return
            parts = []
            if result.spike_detected:
                parts.append(f"spike: {result.total_errors} errors this hour")
            if result.new_codes:
                parts.append(f"new codes: {', '.join(result.new_codes[:3])}")
            if parts:
                await self._orch.autonomy.submit(
                    agent="steve", kind="monitor.log_trend", title="Hourly log trend — " + "; ".join(parts),
                    payload={"risk_tier": 0, "spike": result.spike_detected,
                             "new_codes": result.new_codes,
                             "total_errors": result.total_errors},
                    origin="log_scanner",
                )
        except Exception as e:
            logger.warning(f"Log hourly scan failed: {e}")

    async def run_log_daily_scan(self):
        """07:05 daily scan: write 24-h bug-report digest."""
        if not self._orch.get_setting("system.log_scan_enabled", True):
            return
        try:
            problems_path = str(data_path("problems.jsonl"))
            result = self._orch.log_scanner.daily_scan(problems_path)
            logger.info(
                f"Daily log scan: {result.total_errors} errors, "
                f"{len(result.new_codes)} new codes, report={result.report_path}"
            )
            if result.healthy:
                return
            issues_summary = ", ".join(
                f"{i['code']}×{i['count']}" for i in result.top_issues[:5]
            )
            title = f"Daily bug digest: {result.total_errors} errors"
            if result.new_codes:
                title += f", {len(result.new_codes)} new codes"
            await self._orch.autonomy.submit(
                agent="steve", kind="monitor.log_daily", title=title,
                payload={"risk_tier": 0, "total_errors": result.total_errors,
                         "new_codes": result.new_codes, "top_issues": issues_summary,
                         "report_path": result.report_path},
                origin="log_scanner",
            )
        except Exception as e:
            logger.warning(f"Log daily scan failed: {e}")

    async def run_daily_digest(self, kind: str):
        """Build and ship the morning brief / evening retro to the owner."""
        try:
            if kind == "morning":
                memory_entries = await self._memory_entries_for_brief()
                text = build_morning_brief(
                    self._orch.autonomy_queue,
                    memory_entries=memory_entries,
                    runtime_health=_runtime_health_or_none(),
                    signal_briefs=await _signal_briefs_or_none(self._orch),
                )
            else:
                text = build_evening_retro(self._orch.autonomy_queue)
        except Exception as e:
            logger.warning(f"Digest build failed ({kind}): {e}")
            return
        owner = os.environ.get("AUTONOMY_OWNER_CHAT_ID", "") or str(
            self._orch.get_setting("autonomy.owner_chat_id", "") or ""
        )
        tg = self._orch.channels.get("telegram")
        if tg and owner:
            try:
                await tg.send(text, chat_id=int(owner))
            except Exception as e:
                logger.warning(f"Digest send failed ({kind}): {e}")
        logger.info(f"Daily digest ready: {kind}")

    async def _memory_entries_for_brief(self) -> list[dict]:
        try:
            from agents.core.memory.store import MemoryStore
            allmem = await MemoryStore().get_all()
            rows: list[dict] = []
            for entries in (allmem or {}).values():
                rows.extend(entries)
            return rows
        except Exception:
            return []


# T-0.41: which domains the morning brief reports on. Argus subscribes to all of
# them (signal_routing.AGENT_INTERESTS), so this is the owner-facing superset
# rather than a second, drifting list.
_BRIEF_SIGNAL_DOMAINS = ("conflict", "cyber", "economy", "energy")


async def _signal_briefs_or_none(orch):
    """Per-domain world-signal briefs for the morning brief (T-0.41), or None.

    Reads the Signal Layer sidecar ONCE and routes that single fetch into each
    domain, rather than calling `build_domain_brief` per domain (which would
    re-fetch). Returns None whenever there is no sidecar, it is unreachable, or
    it yields nothing — the digest renders no section at all in that case, which
    is the honest outcome: silence, not an empty "all quiet" heading.
    """
    try:
        plugin = (getattr(orch, "plugins", None) or {}).get("signal-layer")
        if plugin is None:
            return None
        body = await plugin.signals(limit=50)
        if not isinstance(body, dict) or body.get("status") != "ok":
            return None
        signals = list(body.get("signals") or [])
        if not signals:
            return None

        from agents.core.signal_routing import build_domain_brief

        briefs = [build_domain_brief(signals, d, top=3) for d in _BRIEF_SIGNAL_DOMAINS]
        return [b for b in briefs if b.get("count")] or None
    except Exception:  # pragma: no cover - the sidecar never breaks the brief
        logger.debug("Signal briefs read failed for the morning brief", exc_info=True)
        return None


def _runtime_health_or_none():
    """Loop-health summary for the morning brief (H23.29), or None.

    The run-log only exists when the headless runtime supervisor is in use, so
    a missing file is the normal single-process case, not an error — and the
    brief must ship either way, so nothing here is allowed to raise.
    """
    try:
        from agents.core.observability.runtime_log import default_log_path, read_runtime_health

        return read_runtime_health(default_log_path())
    except Exception:  # pragma: no cover - observability never breaks the brief
        logger.debug("Runtime health read failed for the morning brief", exc_info=True)
        return None
