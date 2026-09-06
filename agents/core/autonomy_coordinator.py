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
import contextvars
import logging
import os
from datetime import datetime

from .autonomy import TaskExecutor
from .autonomy.inbox import build_decision_card
from .autonomy.worker import is_night_window
from .orchestrator_bindings import bind_external_orchestrator_attribute
from .system_profiles import active_posture
from .workflows.pending_queue import WorkflowPendingQueue

# The durable approved task for the turn the trusted executor is running. Set only
# by the TaskExecutor handler below and read by the gated tools that need to prove a
# human accepted THIS row; deliberately not a model-facing tool argument, so a model
# can never forge an approval id through the input schema.
_APPROVED_TASK: contextvars.ContextVar = contextvars.ContextVar(
    "nerva_approved_task", default=None
)

# Gated ToolRPC tools whose approved tasks may reach trusted execution. Every
# entry actuates only through its own governed rail (desktop kernel steps, target
# policy plane, file scope + snapshot) after durable ask-tier approval.
_TRUSTED_TOOL_RPC_KINDS = frozenset({
    "toolrpc.desktop_run",
    "toolrpc.terminal_run",
    "toolrpc.file_write",
    "toolrpc.file_delete",
})

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
            logger.info(
                "Autonomy decision inbox wired to Telegram (H34.2 away-notify via escalation)"
            )

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
            allow = (self._orch._runtime_settings.get("autonomy", {}) or {}).get(
                "escalation_channels"
            )
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
        """Handle a decision-inbox button tap from Telegram, bound to the owner.

        SEC-B3. This used to discard the ``user_id`` and ``chat_id`` the channel passes
        and apply the decision unconditionally — an approval with no owner check at all.
        The blast radius was genuinely narrow (the card sender has one caller and targets
        the configured owner chat, and a callback query cannot be synthesised by someone
        who cannot see the button), but "narrow" was an accident of the surrounding wiring
        rather than a property of this function, and approving an autonomy task is the
        single most privileged thing a channel can do.

        Both dimensions are checked, because either alone is weak: the chat proves the
        button came from the conversation we sent it to, and the user proves it was tapped
        by the owner rather than by another member if that chat is a group.
        """
        chat_id = kwargs.get("chat_id")
        user_id = kwargs.get("user_id")
        if not self._callback_is_owner(chat_id, user_id):
            logger.warning(
                "Rejected Telegram decision for task #%s: sender is not the owner",
                task_id,
            )
            return None
        try:
            await self._orch.autonomy.apply_decision(task_id, action, decided_by="telegram")
            return f"Task #{task_id}: {action}"
        except Exception as e:
            logger.warning(f"Autonomy decision callback failed: {e}")
            return None

    def _callback_is_owner(self, chat_id, user_id) -> bool:
        """Is this button tap the owner's?

        Fails CLOSED when nothing identifies the owner. An approval surface with no owner
        binding configured should not approve — declining costs the owner one settings
        entry, whereas allowing costs them the guarantee that only they can approve.
        """
        owner_chat = str(self._orch.get_setting("autonomy.owner_chat_id", "") or "").strip()
        allowed_users = {
            str(u) for u in (getattr(self._telegram_channel(), "allowed_users", None) or [])
        }
        if not owner_chat and not allowed_users:
            return False
        if owner_chat and str(chat_id or "") != owner_chat:
            return False
        return not (allowed_users and str(user_id or "") not in allowed_users)

    def _telegram_channel(self):
        for channel in (getattr(self._orch, "channels", {}) or {}).values():
            if (
                getattr(channel, "name", "") == "telegram"
                or type(channel).__name__ == "TelegramChannel"
            ):
                return channel
        return None

    def _record_cycle(self, *, amode: str, max_tier: int | None, ok: bool, error: str = "") -> None:
        """Best-effort structured run-log entry (H23-tail: coordinator/heartbeat/night-shift
        supervisor observability). Absent ``runtime_log`` is the default, byte-identical
        no-op; a logging failure never turns a successful tick into a reported failure."""
        run_log = getattr(self._orch, "runtime_log", None)
        if run_log is None:
            return
        try:
            scheduler = getattr(self._orch, "heartbeat_scheduler", None)
            heartbeat = scheduler.get_status() if scheduler is not None else {"scheduler_running": False}
            run_log.record_cycle(
                heartbeat=heartbeat,
                coordinator={"mode": amode, "max_tier": max_tier},
                night_shift={
                    "enabled": bool(self._orch.get_setting("autonomy.night_shift", False)),
                    "active_window": max_tier == 1,
                },
                ok=ok,
                error=error,
            )
        except Exception:
            logger.warning("Runtime run-log cycle recording failed", exc_info=True)

    async def loop(self):
        """Periodically run approved autonomy tasks (the self-tasking worker).

        During the night window (H6.6) only reversible/read-only work runs, so
        external/irreversible tasks always wait for a waking human.
        """
        while True:
            interval = int(self._orch.get_setting("system.autonomy_tick", 60) or 60)
            await asyncio.sleep(max(15, interval))
            # Global emergency stop: skip the whole self-tasking tick while the
            # ESTOP sentinel exists (pause-new-work; in-flight work is not killed).
            from agents.core import estop
            if estop.check_paused("autonomy", logger):
                continue
            amode = "unknown"
            max_tier = None
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
                    pol.cap_per_action = float(
                        self._orch.get_setting("autonomy.cap_per_action", 50.0) or 50.0
                    )
                    pol.daily_ceiling = float(
                        self._orch.get_setting("autonomy.daily_ceiling", 200.0) or 200.0
                    )
                    try:
                        self._orch.autonomy.running_ttl_seconds = float(
                            self._orch.get_setting("autonomy.running_ttl_seconds", 3600)
                        )
                    except (TypeError, ValueError):
                        self._orch.autonomy.running_ttl_seconds = 3600.0
                    pol.earned_autonomy_enabled = (
                        self._orch.get_setting("autonomy.earned_autonomy_enabled", False) is True
                    )
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
                    if self._orch.observer and self._orch.get_setting(
                        "system.observer_enabled", True
                    ):
                        await self._orch.observer.observe()
                    # Sample personal events (Antigravity watchers)
                    if self._orch.event_watcher and self._orch.get_setting(
                        "system.watchers_enabled", True
                    ):
                        await self._orch.event_watcher.observe()
                # Nightly reflection & graph consolidation (H5.15)
                if self._orch.reflector and self._orch.get_setting(
                    "system.reflection_enabled", True
                ):
                    if is_night_window(datetime.now().hour, start=22, end=7):
                        await self._orch.reflector.run(enabled=True)
                # Nightly skill curator (H20.5) — same night window as reflection,
                # additionally gated by the learning-loop master flag (default OFF).
                _cur = getattr(self._orch, "curator", None)
                _cog = getattr(self._orch, "cognition", None)
                if (
                    _cur is not None
                    and _cog is not None
                    and _cog.sub_enabled("review_enabled")
                    and is_night_window(datetime.now().hour, start=22, end=7)
                ):
                    await _cur.run()
                # Continuous Ingestion Watcher (H5.1)
                if self._orch.ingestion_watcher and self._orch.get_setting(
                    "system.ingestion_watcher_enabled", True
                ):
                    await asyncio.to_thread(self._orch.ingestion_watcher.check_and_run)
                # Sync error/problem log to the git-ignored memory_logs/diagnostics.md
                # (never the tracked BACKLOG.md — that caused git conflicts).
                if self._orch.get_setting("system.error_backlog_sync_enabled", True):
                    from .autonomy.error_logger import sync_problems_to_diagnostics

                    sync_problems_to_diagnostics()
                # 0.34: drain any due durable workflow runs (opt-in; no-op unless
                # JARVIS_WORKFLOW_PERSIST is set).
                await self._drain_workflow_pending()
                self._record_cycle(amode=amode, max_tier=max_tier, ok=True)
            except Exception as e:
                logger.warning(f"Autonomy tick failed: {e}")
                self._record_cycle(amode=amode, max_tier=max_tier, ok=False, error=str(e)[:500])

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
                and persisted.kind in _TRUSTED_TOOL_RPC_KINDS
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

        def _durable_terminal_approval(task_id):
            """True only when *task_id* is the running, human-accepted terminal row.

            The local-host backend refuses to spawn anything without this, so the
            check re-reads the durable queue rather than trusting the caller —
            same shape as ``_approved_execution_context``.
            """
            queue = getattr(self._orch, "autonomy_queue", None)
            if queue is None or isinstance(task_id, bool) or not isinstance(task_id, int):
                return False
            persisted = queue.get(task_id)
            if persisted is None:
                return False
            return (
                persisted.status == "running"
                and persisted.kind == "toolrpc.terminal_run"
                and persisted.autonomy_level == "ask"
                and persisted.decision in {"accept", "edit"}
                and bool(persisted.decided_by)
                and str(persisted.decided_by).lower() != "policy"
            )

        async def _rpc_terminal_run(args):
            """Run a command on a named target AFTER durable approval (GAP-9).

            Policy layers, outermost first: JARVIS_TERMINAL_TARGETS default-off
            flag → this gated tool's kernel/approval rail → the target policy
            plane (audit-chained authorize) → the transport (docker, or the
            local host behind JARVIS_TERMINAL_LOCAL_HOST). The durable task id
            comes from the executor's contextvar, never from the model's args.
            """
            from .env_config import env_flag
            from .environments import GovernedTargetRunner

            if not env_flag("JARVIS_TERMINAL_TARGETS"):
                return {"ok": False, "reason": "terminal_targets_disabled"}
            approved = _APPROVED_TASK.get()
            approved_task_id = getattr(approved, "id", None) if approved is not None else None
            runner = GovernedTargetRunner(
                self._target_registry(),
                getattr(self._orch, "sandbox", None),
                authorizer=action_kernel,
                approval_check=_durable_terminal_approval,
            )
            return await runner.run(
                target=args["target"],
                agent="jarvis",
                command=args["command"],
                approved_task_id=approved_task_id,
                cwd=args.get("cwd"),
                timeout=args.get("timeout"),
            )

        server.register_tool(
            "terminal_run",
            _rpc_terminal_run,
            gated=True,
            description="Run one bounded shell command on a named governed target.",
            input_schema={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "maxLength": 64},
                    "command": {"type": "string", "maxLength": 4000},
                    "cwd": {"type": "string", "maxLength": 1024},
                    "timeout": {"type": "integer", "minimum": 1, "maximum": 600},
                },
                "required": ["target", "command"],
                "additionalProperties": False,
            },
            capability_id="tool:terminal_run",
            trusted_execution=True,
        )

        async def _rpc_desktop_plan(args):
            """T-0.25 / DRA-43 — the row's own "model ToolRPC registration".

            Ungated for the same reason as operator_plan: it plans and never
            executes. Running a returned step still means desktop_run, which is
            gated and approval-railed.
            """
            from .desktop_control import plan

            return plan(
                args.get("kind"),
                app=args.get("app"),
                action=args.get("action"),
                op=args.get("op"),
                value=args.get("value"),
            )

        server.register_tool(
            "desktop_plan",
            _rpc_desktop_plan,
            description="Plan an allowlisted desktop launch/OS action/recording; never executes it.",
            input_schema={
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "maxLength": 16},
                    "app": {"type": "string", "maxLength": 64},
                    "action": {"type": "string", "maxLength": 32},
                    "op": {"type": "string", "maxLength": 16},
                    "value": {},
                },
                "required": ["kind"],
                "additionalProperties": False,
            },
            capability_id="tool:desktop_plan",
        )

        async def _rpc_operator_plan(args):
            """H28.2 / DRA-22 / DRA-42 — choose API → CLI → structured UI for a goal.

            Ungated because it selects and never executes: the returned id still
            has to be run through its own governed surface, which keeps the kernel
            and approval boundaries intact.
            """
            from .operator_router import plan_payload

            try:
                return plan_payload(
                    args["goal"],
                    orch=self._orch,
                    params=args.get("params") or {},
                    allow_visual_fallback=bool(args.get("allow_visual_fallback")),
                )
            except ValueError as exc:
                return {"ok": False, "reason": str(exc)}

        server.register_tool(
            "operator_plan",
            _rpc_operator_plan,
            description="Select the governed operator surface for a goal; never executes it.",
            input_schema={
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "maxLength": 4000},
                    "params": {
                        "type": "object",
                        "maxProperties": 32,
                        "additionalProperties": True,
                    },
                    "allow_visual_fallback": {"type": "boolean"},
                },
                "required": ["goal"],
                "additionalProperties": False,
            },
            capability_id="tool:operator_plan",
        )

        async def _rpc_osint_enrich(args):
            """DRA-05 — follow the pivots investigate.py only ever suggested.

            Gated (not trusted_execution): this is the one OSINT surface that
            performs outbound lookups driven by attacker-influenceable indicators,
            so it rides the kernel/approval rail like desktop_run. The live client
            is the default-off ``osint_enrich`` plugin; with it absent or dark the
            call still returns an honest plan whose network pivots are refused by
            name rather than fabricated.
            """
            from .osint.enrich import investigate_and_enrich

            plugins = getattr(self._orch, "plugins", None)
            return await investigate_and_enrich(
                args["evidence"],
                client=(plugins.get("osint_enrich") if plugins else None),
                top=args.get("top", 8),
                max_lookups=args.get("max_lookups", 8),
            )

        server.register_tool(
            "osint_enrich",
            _rpc_osint_enrich,
            gated=True,
            description=(
                "Follow OSINT pivot suggestions with bounded live lookups; "
                "untrusted results stay tainted."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "evidence": {
                        "type": "array",
                        "maxItems": 2000,
                        "items": {
                            "type": "object",
                            "maxProperties": 8,
                            "additionalProperties": True,
                        },
                    },
                    "top": {"type": "integer"},
                    "max_lookups": {"type": "integer"},
                },
                "required": ["evidence"],
                "additionalProperties": False,
            },
            capability_id="tool:osint_enrich",
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
        # 1.1.0 operator wave — governed file read/list/write/delete. Default-off:
        # register_file_tools returns [] and touches nothing unless JARVIS_FILE_TOOLS
        # is set. The two mutating tools are gated, so they can only run from an
        # owner-approved durable task, and each write crosses the Action Kernel with
        # a snapshot already taken so the rollback contract is real.
        from .file_tools import FileTools, register_file_tools

        register_file_tools(
            server,
            FileTools.from_env(
                authorizer=action_kernel,
                audit=getattr(self._orch, "intent_log", None),
            ),
        )

        acquisition = AcquisitionRuntime(
            enabled=lambda: _get_setting("acquisition.enabled", False) is True,
        )
        bind_external_orchestrator_attribute(self._orch, "acquisition", acquisition)

        runtime = AgentToolRuntime(
            server,
            enabled=lambda: _get_setting("llm.tool_loop_enabled", False) is True,
            registry_enabled=lambda: _get_setting("llm.registry_planning_enabled", False) is True,
            capability_snapshot=lambda: capability_registry.snapshot(self._orch),
            max_iterations=lambda: _get_setting("llm.tool_loop_max_iterations", 8),
            gap_callback=acquisition.capture_gap,
        )
        bind_external_orchestrator_attribute(self._orch, "tool_rpc", server)
        bind_external_orchestrator_attribute(self._orch, "agent_tool_runtime", runtime)

        async def _approved_desktop_tool_rpc_execute(task):
            # Publish the durable row for the length of this turn so a gated tool can
            # prove a human accepted *this* task without the id passing through the
            # model-facing schema. Reset in `finally` so nothing leaks to the next turn.
            token = _APPROVED_TASK.set(task)
            try:
                return await server.execute(task, execution_context=execution_token)
            finally:
                _APPROVED_TASK.reset(token)

        self._approved_desktop_tool_rpc_execute = _approved_desktop_tool_rpc_execute
        self._targets = None
        for agent in getattr(self._orch, "agents", {}).values():
            agent.tool_runtime = runtime
        return runtime

    def _target_registry(self):
        """Build the named-target registry once, with a durable audit chain.

        First production consumer of the H28.3 policy plane (GAP-9). The
        chain file re-verifies on load and refuses tampered history; if the
        durable file is corrupt we fail closed to in-memory auditing rather
        than executing without a verified chain.
        """
        if self._targets is None:
            from .environments import TargetAuditChain, TargetRegistry, default_targets
            from .paths import data_path

            try:
                audit = TargetAuditChain(path=data_path("environments", "target-audit.jsonl"))
            except Exception:
                logger.warning(
                    "Durable target-audit chain unavailable; using in-memory chain",
                    exc_info=True,
                )
                audit = TargetAuditChain()
            self._targets = TargetRegistry(default_targets(), audit=audit)
        return self._targets

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
            execution_guard=getattr(self._orch.autonomy, "execution_allowed", None),
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

        # `orch.audit` is the guardrails AuditLogger, whose log() takes a
        # SecurityEvent — RemediationRunner calls log(event_str, dict), so every
        # remediation record silently failed into its except branch. Same sink as
        # the autonomy worker: signed action records with intent attribution.
        runner = RemediationRunner(
            permission_gate=self._orch.permission_gate,
            audit=getattr(self._orch, "action_audit", None),
        )

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
        from .autonomy.mediation import DetachedHMACSigner

        _intent_log = getattr(self._orch, "intent_log", None)
        _mediation_signer = DetachedHMACSigner(getattr(_intent_log, "sign_detached", None))
        _bind_mediation = getattr(self._orch.autonomy, "bind_mediation", None)
        _worker_kernel_gate = getattr(self._orch.autonomy, "kernel_gate", None)
        if callable(_bind_mediation):
            _bind_mediation(_action_kernel, _mediation_signer)
        _broker_kernel = (
            _worker_kernel_gate
            if _action_kernel is not None and callable(_worker_kernel_gate)
            else _action_kernel
        )

        from .writeback import WriteBackBroker

        bind_external_orchestrator_attribute(
            self._orch,
            "writeback",
            WriteBackBroker(
                enqueue=self._governed_enqueue,  # O26-P0.7 (F3): policy + inbox
                secret_broker=getattr(self._orch, "secret_broker", None),
                audit=getattr(self._orch, "audit", None),
                kernel=_broker_kernel,
            ),
        )
        executor.register("writeback", self._orch.writeback.execute)
        # TranscriptWatcher enqueues `create_task`; WriteBackBroker.execute accepts
        # both spellings. Without these two rows an approved transcript task fell
        # through to the generic LLM fallback instead of creating anything.
        executor.register("create_task", self._orch.writeback.execute)
        executor.register("task.create", self._orch.writeback.execute)

        # H12.21 — governed social actions (X/Twitter post/reply/DM). Same
        # governance: approved `social.*` tasks resolve OAuth/bearer credentials
        # at action time (behind approval) and post via an injectable client.
        from .social import SocialBroker

        bind_external_orchestrator_attribute(
            self._orch,
            "social",
            SocialBroker(
                enqueue=self._governed_enqueue,  # O26-P0.7 (F3): policy + inbox
                secret_broker=getattr(self._orch, "secret_broker", None),
                audit=getattr(self._orch, "audit", None),
                kernel=_broker_kernel,
                # 0.69: approved postiz.schedule tasks execute through the live
                # PostizPlugin (resolved lazily — plugins may rebuild at runtime).
                postiz_resolver=lambda: self._orch.plugins.get("postiz"),
            ),
        )
        executor.register("social", self._orch.social.execute)

        # Safe Comms v0 — governed replies to live telegram/web inbox threads.
        # Request time only queues a draft; approved tasks send through the
        # already-registered ChannelManager and record the outbound message in
        # the same bounded inbox thread.
        from .channel_reply import ChannelReplyBroker

        bind_external_orchestrator_attribute(
            self._orch,
            "channel_replies",
            ChannelReplyBroker(
                inbox=getattr(self._orch, "channel_inbox", None),
                enqueue=self._governed_enqueue,
                channel_manager=getattr(self._orch, "channel_manager", None),
                audit=getattr(self._orch, "audit", None),
                kernel=_broker_kernel,
            ),
        )
        executor.register("channel.reply", self._orch.channel_replies.execute)

        # H12.22 — governed outbound voice / call-back. A call is an interruption,
        # so it's gated by BOTH the approval queue and the daily interrupt budget;
        # live telephony (Twilio/Telnyx) is deferred to a host-side client.
        from .autonomy.call_broker import CallBroker
        from .env_config import env_json_object

        _call_cfg = env_json_object("JARVIS_CALL_CONFIG", {})
        bind_external_orchestrator_attribute(
            self._orch,
            "call_broker",
            CallBroker(
                enqueue=self._governed_enqueue,  # O26-P0.7 (F3): policy + inbox
                secret_broker=getattr(self._orch, "secret_broker", None),
                audit=getattr(self._orch, "audit", None),
                budget=getattr(self._orch.autonomy, "budget", None),
                config=_call_cfg,
                kernel=_broker_kernel,
                ledger=_budget_ledger,
            ),
        )
        executor.register("call", self._orch.call_broker.execute)

        # H12.17 — governed node mesh (phone/desktop execution nodes). Capability-
        # scoped (H17.3 broker + kill-switch) + approval-gated; the on-device run
        # is a host seam (Tauri/phone client).
        from .node_mesh import NodeMesh

        bind_external_orchestrator_attribute(
            self._orch,
            "node_mesh",
            NodeMesh(
                capability_broker=getattr(self._orch, "capabilities", None),
                kill_switch=getattr(self._orch, "kill_switch", None),
                enqueue=self._governed_enqueue,  # O26-P0.7 (F3): policy + inbox
                audit=getattr(self._orch, "audit", None),
                kernel=_broker_kernel,
            ),
        )
        executor.register("node", self._orch.node_mesh.execute)

        # H20.1 — governed Tool-RPC surface for sandboxed zero-context pipelines.
        # Read-only tools run inline; gated tools enqueue an ask-tier task (and
        # run via this executor only after approval). Starter allowlist is safe
        # built-ins; integrations register more (incl. gated) over time.
        self._wire_agent_tool_runtime(action_kernel=_broker_kernel)
        executor.register("toolrpc", self._orch.tool_rpc.execute)
        executor.register(
            "toolrpc.desktop_run",
            self._approved_desktop_tool_rpc_execute,
        )
        executor.register(
            "toolrpc.terminal_run",
            self._approved_desktop_tool_rpc_execute,
        )
        # 1.1.0 operator wave — the two mutating file tools take the same trusted
        # execution path: a gated tool only runs from the durable approved task.
        executor.register(
            "toolrpc.file_write",
            self._approved_desktop_tool_rpc_execute,
        )
        executor.register(
            "toolrpc.file_delete",
            self._approved_desktop_tool_rpc_execute,
        )
        # 1.1.0 operator wave — the durable consent ledger. The request half runs at
        # the routers/brokers (crossing the kernel first); the grant row itself is
        # only ever written from here, out of the owner-approved task's execution, so
        # a requester can never widen its own permissions.
        from .permission_ledger import PermissionLedger

        try:
            bind_external_orchestrator_attribute(
                self._orch,
                "permission_ledger",
                # secret_store stays default: os_input restore tokens go to the
                # encrypted SecretStore (set/get/delete), not the handle-shaped
                # SecretBroker facade.
                PermissionLedger(authorizer=_broker_kernel),
            )
        except Exception:
            logger.warning("permission ledger unavailable; consent stays default-deny",
                           exc_info=True)
        ledger = getattr(self._orch, "permission_ledger", None)
        if ledger is not None:
            executor.register("permission.grant", ledger.apply_grant)

        # The work-run ledger. Bound whatever the flag says, because reading past
        # runs is honest with company mode off — what it must never do is open one,
        # and only an owner-approved goal.approve task can do that.
        from .autonomy.work_runs import WorkRunLedger

        try:
            bind_external_orchestrator_attribute(
                self._orch, "work_runs", WorkRunLedger()
            )
        except Exception:
            logger.warning("work-run ledger unavailable; company mode stays inert",
                           exc_info=True)

        # E5.0 — the worker reconciles a blocked run the moment its ask is decided.
        # Bound as a seam rather than a constructor argument so a worker built
        # without company mode keeps working exactly as it did; the hook itself
        # still checks the flag before doing anything.
        _autonomy_worker = getattr(self._orch, "autonomy", None)
        if _autonomy_worker is not None and hasattr(_autonomy_worker, "work_run_ledger"):
            _autonomy_worker.work_run_ledger = getattr(self._orch, "work_runs", None)

        # E5.0 company mode — an approved goal becomes a work run here and only
        # here. Like permission.grant, the mint runs out of the owner's own
        # decision: goal_contract refuses any task a human did not accept, and the
        # ledger refuses a goal with no approval ref, so there is no path from a
        # policy auto-decision to a night of autonomous work.
        async def _open_approved_goal(task):
            from .autonomy.goal_contract import GoalContractError, approve_from_task
            from .autonomy.work_runs import WorkRunError, WorkRunLedger

            try:
                goal = approve_from_task(task)
            except GoalContractError as exc:
                return {"status": "refused", "reason": exc.reason}
            runs = getattr(self._orch, "work_runs", None)
            if not isinstance(runs, WorkRunLedger):
                return {"status": "refused", "reason": "work_run_ledger_unavailable"}
            try:
                run = await asyncio.to_thread(
                    runs.open_run, goal, budget=goal.budget, deadline_at=goal.deadline_at
                )
            except WorkRunError as exc:
                return {"status": "refused", "reason": exc.reason}
            return {"status": "ok", "kind": "goal.approve", "run_id": run.id,
                    "goal_id": goal.goal_id}

        executor.register("goal.approve", _open_approved_goal)

        acquisition = getattr(self._orch, "acquisition", None)
        if acquisition is not None:
            from .acquisition.promotion import make_skill_install_kernel_gate

            acquisition.bind_promotion(
                tool_rpc=self._orch.tool_rpc,
                marketplace=getattr(self._orch, "marketplace", None),
                kernel_gate=make_skill_install_kernel_gate(_action_kernel),
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

        bind_external_orchestrator_attribute(
            self._orch,
            "subagents",
            SubAgentManager(
                runner=_subagent_runner,
                max_concurrent=self._subagent_concurrency(),
                max_depth=int(self._orch.get_setting("autonomy.max_subagent_depth", 8) or 8),
                # Concurrency caps how many run at once; this caps how many may be
                # spawned in total for the life of the process, so a delegation loop
                # burns out instead of running all night. 0 keeps it unbounded.
                budget=self._subagent_spawn_budget(),
            ),
        )

        # Domain routers may register late-bound host handlers (for example the
        # default-off House Brain after owner configuration is available). Keep
        # the concrete executor; the worker still receives only ``execute``.
        bind_external_orchestrator_attribute(self._orch, "task_executor", executor)
        return executor

    def _subagent_spawn_budget(self):
        """Total-spawn budget for one boot, or ``None`` when the setting is 0.

        Reads ``autonomy.max_subagent_spawns_per_boot``; an unreadable or
        non-positive value means unbounded, which is the pre-1.1.0 behaviour."""
        from .iteration_budget import IterationBudget

        try:
            cap = int(self._orch.get_setting("autonomy.max_subagent_spawns_per_boot", 50) or 0)
        except (TypeError, ValueError):
            return None
        return IterationBudget(cap) if cap > 0 else None

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
