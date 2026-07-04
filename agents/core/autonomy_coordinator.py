"""autonomy_coordinator.py — autonomy wiring + worker loop extracted from the Orchestrator (CLN-2).

Owns the decision-inbox→Telegram wiring (``wire`` + the ``_on_callback`` handler),
the executor construction that maps task kinds to real capabilities (``build_executor``),
and the periodic self-tasking worker (``loop``, async). It holds a back-reference to the
orchestrator and reads/writes its live state (``autonomy``, ``channels``, ``plugins``,
``observer``, ``event_watcher``, ``reflector``, ``autonomy_queue``, …) at call time — the
same delegation pattern as SchedulerService / PluginGatherer.

``build_executor`` deliberately assigns several brokers BACK onto the orchestrator
(``writeback``, ``social``, ``call_broker``, ``node_mesh``, ``tool_rpc``, ``subagents``)
because ``agents/web.py`` reads them as ``getattr(orch, …)``; the coordinator writes them
via the back-ref so the public surface stays byte-compatible.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime

from .autonomy import TaskExecutor
from .autonomy.inbox import build_decision_card
from .autonomy.worker import is_night_window
from .system_profiles import active_posture
from .workflows.pending_queue import WorkflowPendingQueue

logger = logging.getLogger("jarvis.orchestrator")


class AutonomyCoordinator:
    def __init__(self, orchestrator):
        self._orch = orchestrator
        # 0.34 (opt-in): lazily-built durable workflow pending-queue, drained each
        # tick only when JARVIS_WORKFLOW_PERSIST is set (else stays None, no drain).
        self._pending_queue = None

    async def _drain_workflow_pending(self) -> None:
        """Drain due durable workflow runs once per tick (0.34 wiring).

        **Opt-in / default-off:** gated on ``JARVIS_WORKFLOW_PERSIST`` — when unset
        this returns immediately having touched nothing (the tick is byte-identical
        to before). When set, due items from the persistent queue are run via
        ``WorkflowEngine.drain_pending`` (resolving pipeline ids through the live
        registry); a failed run retries with backoff until its cap, then parks
        ``dead`` — the queue/engine mechanics are covered by the 0.34 tests. A
        drain hiccup is swallowed so it can never break the autonomy tick."""
        # O26-P2.1: same parse as the engine's persist_enabled() — pre-P2.1 this
        # was a presence check, so JARVIS_WORKFLOW_PERSIST=0 ENABLED the drain
        # while the engine read the same var as off.
        from .workflows.engine import persist_enabled
        if not persist_enabled():
            return
        engine = getattr(self._orch, "workflow_engine", None)
        registry = getattr(self._orch, "workflow_registry", None)
        if engine is None or registry is None:
            return
        if self._pending_queue is None:
            self._pending_queue = WorkflowPendingQueue()
        try:
            await engine.drain_pending(self._pending_queue, registry.get)
        except Exception as e:
            logger.warning(f"Workflow pending-drain failed: {e}")

    # ── Autonomy / Proactive Cortex (H6.1–H6.3) ────────────────────
    def wire(self):
        """Wire the decision inbox to Telegram if a bot + owner chat are set."""
        owner = os.environ.get("AUTONOMY_OWNER_CHAT_ID", "") or str(
            self._orch.get_setting("autonomy.owner_chat_id", "") or ""
        )
        tg = self._orch.channels.get("telegram")
        if tg and owner and hasattr(tg, "send_card"):
            async def notifier(task):
                return await tg.send_card(int(owner), build_decision_card(task))
            self._orch.autonomy.notifier = notifier
            tg.on_callback = self._on_callback
            logger.info("Autonomy decision inbox wired to Telegram")

    async def _on_callback(self, task_id: int, action: str, **kwargs):
        """Handle a decision-inbox button tap from Telegram."""
        try:
            await self._orch.autonomy.apply_decision(task_id, action, decided_by="telegram")
            return f"Task #{task_id}: {action}"
        except Exception as e:
            logger.warning(f"Autonomy decision callback failed: {e}")
            return None

    async def loop(self):
        """Periodically run approved autonomy tasks (the self-tasking worker).

        During the night window (H6.6) only reversible/read-only work runs, so
        external/irreversible tasks always wait for a waking human.
        """
        while True:
            interval = int(self._orch.get_setting("system.autonomy_tick", 60) or 60)
            await asyncio.sleep(max(15, interval))
            try:
                # Sync the live autonomy knobs (/admin) onto the policy each tick:
                # mode (AUTO/ASK/OFF) + the money caps + the interrupt budget.
                amode = str(self._orch.get_setting("autonomy.mode", "auto") or "auto").lower()
                if self._orch.autonomy:
                    pol = self._orch.autonomy.policy
                    if pol.mode != amode:
                        pol.mode = amode
                    # Per-agent mode overrides (HUD v3) — resynced live like the global mode.
                    _am = self._orch.get_setting("autonomy.agent_modes", {})
                    pol.agent_modes = dict(_am) if isinstance(_am, dict) else {}
                    pol.cap_per_action = float(self._orch.get_setting("autonomy.cap_per_action", 50.0) or 50.0)
                    pol.daily_ceiling = float(self._orch.get_setting("autonomy.daily_ceiling", 200.0) or 200.0)
                    bud = getattr(self._orch.autonomy, "budget", None)
                    if bud is not None:
                        bud.per_day = int(self._orch.get_setting("autonomy.interrupt_budget", 4) or 4)
                max_tier = None
                if self._orch.get_setting("autonomy.night_shift", False):
                    start = int(self._orch.get_setting("autonomy.night_start", 23) or 23)
                    end = int(self._orch.get_setting("autonomy.night_end", 6) or 6)
                    if is_night_window(datetime.now().hour, start, end):
                        max_tier = 1  # reversible/read-only only
                await self._orch.autonomy.tick(max_tier=max_tier)
                # Proactive passes self-generate new tasks — paused entirely in OFF mode.
                if amode != "off":
                    # Sample the host and turn state changes into gated tasks.
                    if self._orch.observer and self._orch.get_setting("system.observer_enabled", True):
                        await self._orch.observer.observe()
                    # Sample personal events (Antigravity watchers)
                    if self._orch.event_watcher and self._orch.get_setting("system.watchers_enabled", True):
                        await self._orch.event_watcher.observe()
                # Nightly reflection & graph consolidation (H5.15)
                if self._orch.reflector and self._orch.get_setting("system.reflection_enabled", True):
                    if is_night_window(datetime.now().hour, start=22, end=7):
                        await self._orch.reflector.run(enabled=True)
                # Continuous Ingestion Watcher (H5.1)
                if self._orch.ingestion_watcher and self._orch.get_setting("system.ingestion_watcher_enabled", True):
                    await asyncio.to_thread(self._orch.ingestion_watcher.check_and_run)
                # Sync error/problem log to the git-ignored memory_logs/diagnostics.md
                # (never the tracked BACKLOG.md — that caused git conflicts).
                if self._orch.get_setting("system.error_backlog_sync_enabled", True):
                    from .autonomy.error_logger import sync_problems_to_diagnostics
                    sync_problems_to_diagnostics()
                # 0.34: drain any due durable workflow runs (opt-in; no-op unless
                # JARVIS_WORKFLOW_PERSIST is set).
                await self._drain_workflow_pending()
            except Exception as e:
                logger.warning(f"Autonomy tick failed: {e}")

    def _governed_enqueue(self, *args, **kwargs) -> int:
        """O26-P0.7 (F3): broker proposals go through the worker's governed
        intake (risk policy + decision inbox + best-effort push) instead of
        raw TaskQueue.enqueue. Falls back to the raw queue only if the worker
        is somehow absent (fail-safe: the task is still persisted)."""
        worker = getattr(self._orch, "autonomy", None)
        if worker is not None and hasattr(worker, "govern_enqueue"):
            return worker.govern_enqueue(*args, **kwargs)
        return self._orch.autonomy_queue.enqueue(*args, **kwargs)

    def build_executor(self) -> TaskExecutor:
        """Wire task kinds to real capabilities, degrading gracefully."""
        async def _research(task):
            query = (task.payload or {}).get("query") or task.title
            ws = self._orch.plugins.get("websearch")
            if ws and hasattr(ws, "handle"):
                return {"status": "ok", "kind": "research", "output": await ws.handle(query)}
            return {"status": "noop", "note": "websearch unavailable"}

        async def _llm(task):
            prompt = (task.payload or {}).get("prompt") or task.title
            out = await self._orch.process(prompt, channel="autonomy")
            return {"status": "ok", "kind": task.kind, "output": out}

        # K3: optional per-task wall-time budget (JARVIS_TASK_MAX_SECONDS, unset = unbounded).
        _tms = os.environ.get("JARVIS_TASK_MAX_SECONDS", "").strip()
        try:
            _task_budget = float(_tms) if _tms else None
        except ValueError:
            _task_budget = None
        if _task_budget is not None and _task_budget <= 0:
            _task_budget = None
        _budget_ledger = getattr(self._orch, "budget_ledger", None)
        executor = TaskExecutor(
            fallback=_llm,
            max_wall_seconds=_task_budget,
            budget_ledger=_budget_ledger,
        )
        for kw in ("research", "search", "monitor", "scan", "lookup", "check"):
            executor.register(kw, _research)
        for kw in ("summarize", "analyze", "review", "draft", "plan", "prepare"):
            executor.register(kw, _llm)

        # Safe system recovery remediation handler (H6 / Antigravity recovery)
        from .autonomy.remediation import RemediationRunner
        runner = RemediationRunner(permission_gate=self._orch.permission_gate, audit=self._orch.audit)

        async def _restart_service(task):
            service = (task.payload or {}).get("service")
            agent = getattr(task, "agent", "steve")
            return await runner.restart(service, agent=agent)

        executor.register("restart_service", _restart_service)

        # H10.30 — governed write-back integrations (Notion/GitHub/Calendar).
        # Approved `writeback.*` tasks resolve credentials at action time (behind
        # approval) and call an injectable client (offline NullWriteBackClient by
        # default; the live HTTP rail is a host-side seam).
        # ORIZONT-24 K1: one bound kernel.authorize, injected into the wave-1 brokers
        # (default-off behind JARVIS_ACTION_KERNEL). Audit → intent_log (IntentLog.record),
        # not orch.audit. None if the policy isn't available → brokers stay kernel-less.
        # The binding lives in kernel.binding (shared with web.py's payment broker), so
        # there's one definition of what the kernel front door is bound to.
        # K3: the loop circuit breaker is bound ONLY here (the broker action path) — routes/
        # egress omit it (they legitimately repeat the same action.kind and would false-trip).
        from .kernel.binding import make_action_kernel
        _action_kernel = make_action_kernel(
            self._orch,
            loop_detector=getattr(self._orch, "loop_detector", None),
            budget_ledger=_budget_ledger,
        )

        from .writeback import WriteBackBroker
        self._orch.writeback = WriteBackBroker(
            enqueue=self._governed_enqueue,  # O26-P0.7 (F3): policy + inbox
            secret_broker=getattr(self._orch, "secret_broker", None),
            audit=getattr(self._orch, "audit", None),
            kernel=_action_kernel,
        )
        executor.register("writeback", self._orch.writeback.execute)

        # H12.21 — governed social actions (X/Twitter post/reply/DM). Same
        # governance: approved `social.*` tasks resolve OAuth/bearer credentials
        # at action time (behind approval) and post via an injectable client.
        from .social import SocialBroker
        self._orch.social = SocialBroker(
            enqueue=self._governed_enqueue,  # O26-P0.7 (F3): policy + inbox
            secret_broker=getattr(self._orch, "secret_broker", None),
            audit=getattr(self._orch, "audit", None),
            kernel=_action_kernel,
        )
        executor.register("social", self._orch.social.execute)

        # H12.22 — governed outbound voice / call-back. A call is an interruption,
        # so it's gated by BOTH the approval queue and the daily interrupt budget;
        # live telephony (Twilio/Telnyx) is deferred to a host-side client.
        import json as _json
        from .autonomy.call_broker import CallBroker
        try:
            _call_cfg = _json.loads(os.environ.get("JARVIS_CALL_CONFIG", "") or "{}")
        except Exception:
            _call_cfg = {}
        self._orch.call_broker = CallBroker(
            enqueue=self._governed_enqueue,  # O26-P0.7 (F3): policy + inbox
            secret_broker=getattr(self._orch, "secret_broker", None),
            audit=getattr(self._orch, "audit", None),
            budget=getattr(self._orch.autonomy, "budget", None),
            config=_call_cfg,
            kernel=_action_kernel,
            ledger=_budget_ledger,
        )
        executor.register("call", self._orch.call_broker.execute)

        # H12.17 — governed node mesh (phone/desktop execution nodes). Capability-
        # scoped (H17.3 broker + kill-switch) + approval-gated; the on-device run
        # is a host seam (Tauri/phone client).
        from .node_mesh import NodeMesh
        self._orch.node_mesh = NodeMesh(
            capability_broker=getattr(self._orch, "capabilities", None),
            kill_switch=getattr(self._orch, "kill_switch", None),
            enqueue=self._governed_enqueue,  # O26-P0.7 (F3): policy + inbox
            audit=getattr(self._orch, "audit", None),
            kernel=_action_kernel,
        )
        executor.register("node", self._orch.node_mesh.execute)

        # H20.1 — governed Tool-RPC surface for sandboxed zero-context pipelines.
        # Read-only tools run inline; gated tools enqueue an ask-tier task (and
        # run via this executor only after approval). Starter allowlist is safe
        # built-ins; integrations register more (incl. gated) over time.
        from .tool_rpc import ToolRPCServer
        import time as _t
        self._orch.tool_rpc = ToolRPCServer(
            secret_broker=getattr(self._orch, "secret_broker", None),
            enqueue=self._governed_enqueue,  # O26-P0.7 (F3): policy + inbox
            audit=getattr(self._orch, "audit", None),
            kernel=_action_kernel,   # ORIZONT-24 wave-3: mediate gated tools (default-off)
        )

        async def _rpc_echo(args):
            return {"echo": args}

        async def _rpc_time(args):
            return {"now": _t.time()}

        self._orch.tool_rpc.register_tool("echo", _rpc_echo)
        self._orch.tool_rpc.register_tool("time", _rpc_time)
        executor.register("toolrpc", self._orch.tool_rpc.execute)

        # H21.4: wire the calibration-gated autonomy hook (gated; no-op unless
        # cognition.learning_enabled — and it only ever ADDS caution).
        def _calibration_hook(action):
            cog = getattr(self._orch, "cognition", None)
            if cog is None or not cog.sub_enabled("learning_enabled"):
                return 0
            lm = cog.module("learning")
            if lm is None:
                return 0
            try:
                return lm.autonomy_adjustment(str(action.get("kind", "")))
            except Exception:
                return 0
        try:
            self._orch.autonomy.policy.calibration_hook = _calibration_hook
        except Exception:
            logger.debug("calibration hook wiring skipped", exc_info=True)

        # H20.6 — agent-initiated sub-agent delegation (isolated session, capped).
        from .subagents import SubAgentManager

        async def _subagent_runner(task, session_id, agent):
            picked = agent if agent in self._orch.agents else "jarvis"
            out = await self._orch.process(task, agent=picked, channel="subagent")
            return {"output": out, "session_id": session_id}

        self._orch.subagents = SubAgentManager(
            runner=_subagent_runner,
            max_concurrent=self._subagent_concurrency(),
            max_depth=int(self._orch.get_setting("autonomy.max_subagent_depth", 8) or 8),
        )

        return executor

    def _subagent_concurrency(self) -> int:
        """Effective subagent concurrency cap (0.62 system-profile consumer).

        The ``autonomy.max_subagents`` setting, **further capped** by the active
        system profile's ``max_parallel_agents`` posture hint when it sets one — so
        a constrained profile (e.g. a low-power box) can't be overridden upward by
        the setting. The default profile leaves the hint ``None`` → the cap is the
        setting unchanged (byte-identical). A bad profile read falls back to the
        setting, never raising."""
        base = int(self._orch.get_setting("autonomy.max_subagents", 3) or 3)
        hint = None
        try:
            hint = active_posture().get("max_parallel_agents")
        except Exception:
            logger.debug("system-profile concurrency hint unavailable", exc_info=True)
        if isinstance(hint, int) and not isinstance(hint, bool) and hint > 0:
            return min(base, hint)
        return base
