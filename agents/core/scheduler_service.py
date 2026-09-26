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

#: H182 — what a heavy background job returns when it skipped a run on battery.
DEFERRED_ON_BATTERY = {"skipped": True, "reason": "deferred_on_battery"}   # scheduler health: "skipped"


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
        self.schedule_auto_archive()
        self.schedule_exec_cache_prune()
        self.schedule_memory_maintenance()
        self.schedule_tech_scout()
        self.schedule_llm_backend_refresh()
        self.schedule_power_monitor()
        self.schedule_pressure_monitor()
        self.schedule_company_mode()
        self.schedule_backups()
        self.schedule_owner_jobs()

    # ── scheduling (registration) ─────────────────────────────────
    def schedule_owner_jobs(self):
        """Put the owner's own jobs on the scheduler (Hermes absorption, wave 2)."""
        runner = getattr(self._orch, "jobs", None)
        if runner is None:
            return
        from agents.core import safe_mode

        if safe_mode.enabled():
            # H275: the owner's jobs stay saved; none is put on the scheduler.
            safe_mode.note("owner_jobs")
            logger.warning("Safe mode: owner jobs are not scheduled")
            return
        try:
            registered = runner.register_all()
            logger.info("Owner jobs registered: %d", registered)
        except Exception as e:
            logger.warning(f"Failed to register owner jobs: {e}")

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
            sched.add_job(self.run_learning_loop, "interval", hours=hours,
                          id="learning-loop-promotions", replace_existing=True)
            # DRA-41 — the H20.4 self-evolution twin: same cadence, same inbox,
            # nothing self-applies. This is the unattended production caller the
            # trajectory/prompt-optimization mechanism never had.
            sched.add_job(self.run_prompt_evolution, "interval", hours=hours,
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
            sched.add_job(self.run_worldview_kg_sync, "interval", seconds=interval,
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

    def schedule_auto_archive(self):
        """H218 — archive idle chats daily at 03:40; a no-op unless
        ``memory.auto_archive_days`` is set (0, the default, is off)."""
        sched = getattr(self._orch.heartbeat_scheduler, "scheduler", None)
        if sched is None:
            return
        try:
            sched.add_job(self.run_auto_archive, "cron", hour=3, minute=40,
                          id="session-auto-archive", replace_existing=True)
        except Exception as e:
            logger.warning(f"Failed to schedule the session auto-archive: {e}")

    async def run_auto_archive(self):
        from agents.core import session_archive

        days = session_archive.auto_archive_days(
            self._orch.get_setting(session_archive.SETTING_AUTO_DAYS, 0))
        if not days:
            return {"_scheduler_status": "skipped"}
        try:
            done = await asyncio.to_thread(
                session_archive.run_auto_archive, self._orch.checkpoints, days,
                active=getattr(self._orch, "session_id", None))
            return {"archived": len(done)}
        except Exception as e:
            logger.warning(f"Session auto-archive failed: {e}")
            return {"_scheduler_status": "failed"}

    def schedule_exec_cache_prune(self):
        """Hourly prune of the sandbox's managed run-directory cache (H667).

        Always on: the cache is the hub's own (``<data root>/cache/exec``), and a run
        directory is removed only when its newest file is older than
        ``security.sandbox_temp_max_age_hours`` (72 by default) and no sandbox holds it.
        It is pruned whatever root is chosen now; a root the owner chose
        (``JARVIS_EXEC_TEMP_DIR``, ``security.sandbox_temp_dir``) is never pruned.
        """
        sched = getattr(self._orch.heartbeat_scheduler, "scheduler", None)
        if sched is None:
            return
        try:
            sched.add_job(self.run_exec_cache_prune, "interval", hours=1,
                          id="exec-cache-prune", replace_existing=True)
        except Exception as e:
            logger.warning(f"Failed to schedule the sandbox cache prune: {e}")

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

    def schedule_backups(self):
        """One local backup a night, pruned to a week. **On by default.**

        Every other scheduled capability here is off until asked for, and this one
        is not — because the failure directions are opposite. `schedule_retention`
        *deletes*, so a wrong default loses data; a backup *preserves*, so a wrong
        default costs disk. A product that holds someone's whole life and never
        copies it has failed them in a way no flag protects against, and the copy
        never leaves the machine: it lands in the data root's sibling backups
        directory, exactly where `POST /api/admin/backup` already writes.

        Bounded by construction. `prune_backups` keeps `backup.keep` archives
        (7 by default), so this cannot grow without limit — which is the actual
        reason an automatic backup would have been a bad idea before there was a
        prune to pair it with.

        Encryption follows whatever the owner configured (`$JARVIS_BACKUP_KEY`);
        this never decides that for them, and `backup_health()` reports whether
        the archives are encrypted rather than leaving it to be inferred.
        """
        from agents.core.env_config import env_flag

        if env_flag("JARVIS_TESTING"):
            return
        sched = getattr(self._orch.heartbeat_scheduler, "scheduler", None)
        if sched is None:
            return
        try:
            sched.add_job(self.run_backup, "cron", hour=3, minute=20,
                          id="backup-nightly", replace_existing=True)
            logger.info("Scheduled nightly backup 03:20 (disable with backup.auto_enabled=false)")
        except Exception:
            logger.warning("Failed to schedule the nightly backup", exc_info=True)

    def run_backup(self) -> dict:
        """Take one backup and prune. Never raises into the scheduler.

        Returns the outcome so a caller (and the test) can read it. A failure is
        logged at WARNING rather than swallowed: a backup that has been failing
        quietly for a month is worse than none at all, because the owner believes
        they have one.
        """
        from agents.core.backup import (
            BACKUP_KEEP_DEFAULT,
            create_backup,
            prune_backups,
        )

        if not self._orch.get_setting("backup.auto_enabled", True):
            return {"ok": False, "skipped": "backup.auto_enabled is off"}
        try:
            result = create_backup(label="nightly")
        except Exception as exc:
            logger.warning("nightly backup failed", exc_info=True)
            return {"ok": False, "error": exc.__class__.__name__}
        try:
            keep = int(self._orch.get_setting("backup.keep", BACKUP_KEEP_DEFAULT))
            removed = prune_backups(keep)
        except Exception:
            # A prune that failed must not fail the backup that just succeeded.
            logger.warning("backup prune failed", exc_info=True)
            removed = []
        logger.info(
            "nightly backup: %s (%s bytes), pruned %d",
            result.get("archive"), result.get("bytes"), len(removed),
        )
        return {"ok": True, "archive": result.get("archive"),
                "bytes": result.get("bytes"), "pruned": removed}

    def schedule_company_mode(self):
        """Drive company-mode work runs (E5.0). **Off by default.**

        Nothing is registered unless ``JARVIS_COMPANY_MODE`` is set at boot. That
        asymmetry is deliberate: clearing the flag stops work at the very next
        tick (the runtime re-reads it each sweep), but *starting* a night of
        autonomous work should never happen because a config file changed while
        nobody was looking — it takes a restart, which is a person's decision.

        The job itself only sequences. Every effect a run arranges still enters
        the approval queue and crosses the Action Kernel, and opening a run still
        requires an owner-approved goal decided in the inbox: there is no path
        from this timer to an unapproved action.
        """
        from agents.core.env_config import env_flag

        if env_flag("JARVIS_TESTING"):
            return
        if not env_flag("JARVIS_COMPANY_MODE"):
            return
        sched = getattr(self._orch.heartbeat_scheduler, "scheduler", None)
        if sched is None:
            return
        try:
            from agents.core.autonomy.company_runtime import build_company_runtime
            from agents.core.orchestrator_bindings import (
                bind_external_orchestrator_attribute,
            )

            runtime = build_company_runtime(self._orch)
            if runtime is None:
                # build_company_runtime already logged the named reason. Registering
                # a job that can only no-op would report a working night shift.
                return
            bind_external_orchestrator_attribute(self._orch, "company_runtime", runtime)
            interval = max(60, int(self._orch.get_setting("autonomy.company_tick_seconds", 300)))
            sched.add_job(runtime.sweep, "interval", seconds=interval,
                          id="company-mode-sweep", replace_existing=True)
            logger.info("Scheduled company-mode sweep every %ss", interval)
        except Exception:
            logger.warning("Failed to schedule company mode", exc_info=True)

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
    def schedule_power_monitor(self):
        """H182 — read the power state every minute, so a resume from sleep is noticed
        (and streamed to the HUD) without anyone asking. Skipped under JARVIS_TESTING."""
        from agents.core.env_config import env_flag
        if env_flag("JARVIS_TESTING"):
            return
        sched = getattr(self._orch.heartbeat_scheduler, "scheduler", None)
        if sched is None:
            return
        try:
            sched.add_job(self.run_power_tick, "interval", seconds=60,
                          id="power-monitor", replace_existing=True)
        except Exception as e:
            logger.warning(f"Failed to schedule the power monitor: {e}")

    def schedule_pressure_monitor(self):
        """H161 — sample memory and disk every minute for the pressure banner, on the
        hub's scheduler rather than the autonomy tick, so autonomy off or ESTOP engaged
        does not blind it. Skipped under JARVIS_TESTING (the route samples on demand)."""
        from agents.core.env_config import env_flag
        if env_flag("JARVIS_TESTING"):
            return
        sched = getattr(self._orch.heartbeat_scheduler, "scheduler", None)
        if sched is None:
            return
        try:
            sched.add_job(self.run_pressure_tick, "interval", seconds=60,
                          id="pressure-monitor", replace_existing=True)
        except Exception as e:
            logger.warning(f"Failed to schedule the pressure monitor: {e}")

    async def run_pressure_tick(self):
        from agents.core import resource_pressure

        state = await asyncio.to_thread(resource_pressure.monitor().tick)
        return {"worst": (state.get("worst") or {}).get("condition")}

    async def run_power_tick(self):
        from agents.core import power

        state = await asyncio.to_thread(power.MONITOR.tick)
        return {"on_battery": bool(state.get("on_battery"))}

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

    async def _deferred_on_battery(self) -> bool:
        """H182 — on battery below ``system.battery_defer_percent``: skip this heavy run."""
        from agents.core import power

        try:
            return await asyncio.to_thread(power.defer_background, getattr(self._orch, "get_setting", None))
        except Exception:
            logger.debug("power state unavailable; the job runs", exc_info=True)
            return False

    async def run_learning_loop(self):
        """The learning-loop promotions (the body stays on the orchestrator), deferred on battery."""
        if await self._deferred_on_battery():
            return dict(DEFERRED_ON_BATTERY)
        return await self._orch._run_learning_loop()

    async def run_prompt_evolution(self):
        if await self._deferred_on_battery():
            return dict(DEFERRED_ON_BATTERY)
        return await self._orch._run_prompt_evolution()

    async def run_worldview_kg_sync(self):
        if await self._deferred_on_battery():
            return dict(DEFERRED_ON_BATTERY)
        return await self._orch._run_worldview_kg_sync()

    async def run_tech_scout(self):
        """Run one tech-scout pass, reading live settings each time (H27-self-improve)."""
        scout = getattr(self._orch, "tech_scout", None)
        if scout is None:
            return {"skipped": True, "reason": "unavailable"}
        if await self._deferred_on_battery():
            return dict(DEFERRED_ON_BATTERY)
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
        if await self._deferred_on_battery():
            return dict(DEFERRED_ON_BATTERY)

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
                decay_summary = {"available": False, "ranked": 0, "candidates": 0, "reason": "decay_failed"}

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

    async def run_exec_cache_prune(self):
        """Prune the managed sandbox cache off the event loop; the live sandbox is kept.
        Never raises into the scheduler: a failure is reported as its status."""
        from agents.core import exec_cache

        try:
            # The managed cache is the hub's own whatever root is chosen now: a choice
            # made after start never strands what is already there (review-H667 m5).
            sandbox = getattr(self._orch, "sandbox", None)
            live = [sandbox.work_dir] if getattr(sandbox, "work_dir", None) else []
            return await asyncio.to_thread(
                exec_cache.prune, exec_cache.managed_root(), managed=True,
                max_age_hours=exec_cache.max_age_hours(), live=live)
        except Exception as e:
            logger.warning(f"Sandbox cache prune failed: {e}")
            return {"_scheduler_status": "failed"}

    async def run_retention_purge(self):
        """Run the retention sweep off the event loop (file + SQLite I/O)."""
        if not self._orch.get_setting("retention.enabled", False):
            return {"_scheduler_status": "skipped"}

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
            return {"_scheduler_status": "failed"}

    async def run_log_quick_scan(self):
        """15-min scan: submit autonomy alert on spike or new error code."""
        if not self._orch.get_setting("system.log_scan_enabled", True):
            return {"_scheduler_status": "skipped"}
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
            return {"_scheduler_status": "failed"}

    async def run_log_hourly_scan(self):
        """Hourly scan: trend analysis and backlog sync."""
        if not self._orch.get_setting("system.log_scan_enabled", True):
            return {"_scheduler_status": "skipped"}
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
            return {"_scheduler_status": "failed"}

    async def run_log_daily_scan(self):
        """07:05 daily scan: write 24-h bug-report digest."""
        if not self._orch.get_setting("system.log_scan_enabled", True):
            return {"_scheduler_status": "skipped"}
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
            return {"_scheduler_status": "failed"}

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
            return {"_scheduler_status": "failed"}
        owner = os.environ.get("AUTONOMY_OWNER_CHAT_ID", "") or str(
            self._orch.get_setting("autonomy.owner_chat_id", "") or ""
        )
        tg = self._orch.channels.get("telegram")
        if tg and owner:
            try:
                if not await tg.send(text, chat_id=int(owner)):
                    return {"_scheduler_status": "failed"}
            except Exception as e:
                logger.warning(f"Digest send failed ({kind}): {e}")
                return {"_scheduler_status": "failed"}
        else:
            return {"_scheduler_status": "failed"}
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
