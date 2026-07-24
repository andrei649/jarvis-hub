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
        """Wire the decision inbox to Telegram if a bot + owner chat are set.

        H34.2: the Telegram notifier is wrapped in an ``AwayNotifier`` so that,
        when the owner is away from the desk (``owner_presence.is_away()``), the
        same decision card is ALSO fanned out to the governed escalation channels
        (WhatsApp / Signal / …). That wrap runs *inside* the worker's single
        budget-gated push, so away-notify stays within the same ≤4/day interrupt
        budget; Telegram is excluded from the away fan-out to avoid a duplicate
        plain-text card on the channel that already got the rich one.
        """
        owner = os.environ.get("AUTONOMY_OWNER_CHAT_ID", "") or str(
            self._orch.get_setting("autonomy.owner_chat_id", "") or ""
        )
        tg = self._orch.channels.get("telegram")
        if tg and owner and hasattr(tg, "send_card"):
            async def base(task):
                return await tg.send_card(int(owner), build_decision_card(task))
            self._orch.autonomy.notifier = self._away_notifier(base, exclude={"telegram"})
            tg.on_callback = self._on_callback
            logger.info("Autonomy decision inbox wired to Telegram (H34.2 away-notify via escalation)")

    def _escalation_router(self):
        """Build a live ``EscalationRouter`` over the current channels + allowlist.

        Mirrors ``GET/POST /api/autonomy/escalate`` exactly (same channel set +
        the ``autonomy.escalation_channels`` allowlist), rebuilt per call so
        channel (re)starts and setting changes are always reflected.
        """
        from .autonomy.escalation import EscalationRouter
        channels = getattr(self._orch, "channels", {}) or {}
        allow = None
        try:
            allow = (self._orch._runtime_settings.get("autonomy", {}) or {}).get("escalation_channels")
        except Exception:
            allow = None
        return EscalationRouter(channels, allow=allow)

    def _away_notifier(self, base, *, exclude=None):
        """Wrap a base decision-card notifier with presence-aware away routing."""
        from .autonomy.escalation import AwayNotifier
        return AwayNotifier(
            base,
            getattr(self._orch, "owner_presence", None),
            self._escalation_router,
            exclude=exclude,
        )

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
                    pol.earned_autonomy_enabled = self._orch.get_setting(
                        "autonomy.earned_autonomy_enabled", False
                    ) is True
                    bud = getattr(self._orch.autonomy, "budget", None)
                    if bud is not None:
                        from .ambient.policy import bounded_attention_allowance

                        bud.per_day = bounded_attention_allowance(
                            self._orch.get_setting("autonomy.interrupt_budget", 4)
                        )
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
                # Nightly skill curator (H20.5) — same night window as reflection,
                # additionally gated by the learning-loop master flag (default OFF).
                _cur = getattr(self._orch, "curator", None)
                _cog = getattr(self._orch, "cognition", None)
                if (_cur is not None and _cog is not None
                        and _cog.sub_enabled("review_enabled")
                        and is_night_window(datetime.now().hour, start=22, end=7)):
                    await _cur.run()
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

    def _wire_agent_tool_runtime(self, action_kernel=None):
        """Build the shared, default-off governed tool loop for loaded agents."""
        # Keep imports local: AgentToolRuntime imports ToolRPCServer, while the
        # orchestrator imports this coordinator during boot.
        import time as _t

        from .agent_runtime import AgentToolRuntime
        from .acquisition.runtime import AcquisitionRuntime
        from .desktop_operator import DesktopProposalError, validate_desktop_run_args
        from .observability import capability_registry
        from .tool_rpc import ToolRPCServer, ToolRPCValidationError

        execution_token = object()

        def _approved_execution_context(context, task):
            """Trust only the TaskExecutor turn whose durable row is running."""
            if context is not execution_token:
                return False
            task_id = getattr(task, "id", None)
            queue = getattr(self._orch, "autonomy_queue", None)
            if not isinstance(task_id, int) or queue is None:
                return False
            persisted = queue.get(task_id)
            if persisted is None:
                return False
            return (
                persisted.status == "running"
                and persisted.kind == "toolrpc.desktop_run"
                and persisted.autonomy_level == "ask"
                and persisted.decision in {"accept", "edit"}
                and bool(persisted.decided_by)
                and str(persisted.decided_by).lower() != "policy"
                and persisted.payload == getattr(task, "payload", None)
                and persisted.kind == getattr(task, "kind", None)
            )

        def _get_setting(key, default):
            getter = getattr(self._orch, "get_setting", None)
            if not callable(getter):
                return default
            try:
                return getter(key, default)
            except Exception:
                logger.warning("agent tool runtime setting read failed closed")
                return default

        server = ToolRPCServer(
            secret_broker=getattr(self._orch, "secret_broker", None),
            enqueue=self._governed_enqueue,
            audit=getattr(self._orch, "intent_log", None),
            kernel=action_kernel,
            execution_context_check=_approved_execution_context,
        )

        async def _rpc_echo(args):
            return {"echo": args}

        async def _rpc_time(args):
            return {"now": _t.time()}

        async def _rpc_desktop_run(args):
            """Actuate only after the trusted executor verifies durable approval."""
            from .kernel import Decision, Verdict
            from .routers.multimodal import desktop_host_enabled, execute_desktop_steps

            if not desktop_host_enabled():
                return {"ok": False, "reason": "desktop_host_disabled"}

            def approved_authorizer(action, capability=None):
                decision = action_kernel(action, capability=capability)
                if decision.verdict is Verdict.QUEUE:
                    return Decision(
                        Verdict.GRANT,
                        reason="durably_approved",
                        tier=decision.tier,
                        card=decision.card,
                        task_id=decision.task_id,
                    )
                return decision

            async def approved_step(_action, _args):
                return True

            return await execute_desktop_steps(
                self._orch,
                args["steps"],
                approver=approved_step,
                authorizer=approved_authorizer,
            )

        def _desktop_preflight(args):
            try:
                return validate_desktop_run_args(args)
            except DesktopProposalError as exc:
                raise ToolRPCValidationError(exc.reason) from None

        server.register_tool(
            "desktop_run",
            _rpc_desktop_run,
            gated=True,
            description="Propose bounded governed desktop steps for approval.",
            input_schema={
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "maxItems": 100,
                        "items": {
                            "type": "object",
                            "properties": {
                                "action": {"type": "string", "maxLength": 64},
                                "args": {
                                    "type": "object",
                                    "maxProperties": 32,
                                    "additionalProperties": True,
                                },
                            },
                            "required": ["action"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["steps"],
                "additionalProperties": False,
            },
            capability_id="tool:desktop_run",
            preflight=_desktop_preflight,
            trusted_execution=True,
        )

        server.register_tool(
            "echo",
            _rpc_echo,
            description="Return the provided values.",
            input_schema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            capability_id="tool:echo",
        )
        server.register_tool(
            "time",
            _rpc_time,
            description="Return the current Unix timestamp.",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            capability_id="tool:time",
        )

        acquisition = AcquisitionRuntime(
            enabled=lambda: _get_setting("acquisition.enabled", False) is True,
        )
        self._orch.acquisition = acquisition

        runtime = AgentToolRuntime(
            server,
            enabled=lambda: _get_setting("llm.tool_loop_enabled", False) is True,
            registry_enabled=lambda: _get_setting(
                "llm.registry_planning_enabled", False
            ) is True,
            capability_snapshot=lambda: capability_registry.snapshot(self._orch),
            max_iterations=lambda: _get_setting("llm.tool_loop_max_iterations", 8),
            gap_callback=acquisition.capture_gap,
        )
        self._orch.tool_rpc = server
        self._orch.agent_tool_runtime = runtime

        async def _approved_desktop_tool_rpc_execute(task):
            return await server.execute(task, execution_context=execution_token)

        self._approved_desktop_tool_rpc_execute = _approved_desktop_tool_rpc_execute
        for agent in getattr(self._orch, "agents", {}).values():
            agent.tool_runtime = runtime
        return runtime

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
        from .env_config import env_float
        _task_budget_value = env_float("JARVIS_TASK_MAX_SECONDS", 0.0, minimum=0.0)
        _task_budget = _task_budget_value if _task_budget_value > 0 else None
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

        # H33 ambient tasks must never fall through to the generic LLM handler.
        # A domain binding can replace the longer exact prefix later; until then
        # silent action fails closed and an accepted ask is only acknowledged.
        from .ambient.execution import register_ambient_refusal_handlers

        register_ambient_refusal_handlers(executor)

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
            # 0.69: approved postiz.schedule tasks execute through the live
            # PostizPlugin (resolved lazily — plugins may rebuild at runtime).
            postiz_resolver=lambda: self._orch.plugins.get("postiz"),
        )
        executor.register("social", self._orch.social.execute)

        # Safe Comms v0 — governed replies to live telegram/web inbox threads.
        # Request time only queues a draft; approved tasks send through the
        # already-registered ChannelManager and record the outbound message in
        # the same bounded inbox thread.
        from .channel_reply import ChannelReplyBroker
        self._orch.channel_replies = ChannelReplyBroker(
            inbox=getattr(self._orch, "channel_inbox", None),
            enqueue=self._governed_enqueue,
            channel_manager=getattr(self._orch, "channel_manager", None),
            audit=getattr(self._orch, "audit", None),
            kernel=_action_kernel,
        )
        executor.register("channel.reply", self._orch.channel_replies.execute)

        # H12.22 — governed outbound voice / call-back. A call is an interruption,
        # so it's gated by BOTH the approval queue and the daily interrupt budget;
        # live telephony (Twilio/Telnyx) is deferred to a host-side client.
        from .autonomy.call_broker import CallBroker
        from .env_config import env_json_object
        _call_cfg = env_json_object("JARVIS_CALL_CONFIG", {})
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
        self._wire_agent_tool_runtime(action_kernel=_action_kernel)
        executor.register("toolrpc", self._orch.tool_rpc.execute)
        executor.register(
            "toolrpc.desktop_run",
            self._approved_desktop_tool_rpc_execute,
        )
        acquisition = getattr(self._orch, "acquisition", None)
        if acquisition is not None:
            def _acquisition_kernel_gate(payload):
                if _action_kernel is None:
                    return "queue"
                from .kernel import Action

                decision = _action_kernel(
                    Action(
                        kind="skill.install",
                        agent="jarvis",
                        title="Install acquired capability",
                        payload=dict(payload),
                        origin="generated",
                    )
                )
                return decision.verdict.value

            acquisition.bind_promotion(
                tool_rpc=self._orch.tool_rpc,
                marketplace=getattr(self._orch, "marketplace", None),
                kernel_gate=_acquisition_kernel_gate,
            )
            executor.register("skill.install", acquisition.execute_install_task)

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

        # Domain routers may register late-bound host handlers (for example the
        # default-off House Brain after owner configuration is available). Keep
        # the concrete executor; the worker still receives only ``execute``.
        self._orch.task_executor = executor
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
