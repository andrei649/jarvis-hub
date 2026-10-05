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
import math
# Telegram destinations use the shared channels.outbound resolver.
import time
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
#: K2 switches, read at composition. Kept next to the coordinator's other wiring
#: constants so the two settings that arm a resident interpreter are visible in one
#: place rather than spelled out at the call site.
CODE_SESSIONS_SETTING = "llm.execute_code_sessions"
CHILD_RPC_ROOT = "/nerva-rpc"

_APPROVED_TASK: contextvars.ContextVar = contextvars.ContextVar(
    "nerva_approved_task", default=None
)

# H661 — the tool names the profile offered the turn in flight. Written by the resolver
# the tool loop calls at the top of each run, which happens inside that run's own copied
# context (so concurrent turns never see each other's offer), and read by the spill
# store's read-back probe: a spilled result's notice may name `file_read` only when this
# turn was offered it — otherwise the model's call is refused with tool_not_allowed.
# None outside a loop; then the registry decides, and execute_code adds its own run's
# offer on top.
_TURN_TOOL_OFFER: contextvars.ContextVar = contextvars.ContextVar(
    "nerva_turn_tool_offer", default=None
)

# Gated ToolRPC tools whose approved tasks may reach trusted execution. Every
# entry actuates only through its own governed rail (desktop kernel steps, target
# policy plane, file scope + snapshot) after durable ask-tier approval.
_TRUSTED_TOOL_RPC_KINDS = frozenset({
    "toolrpc.desktop_run",
    "toolrpc.terminal_run",
    "toolrpc.file_write",
    "toolrpc.file_delete",
    # H313 — speaking into a room presents through the kernel-mediated
    # media.present facade, only from the owner-accepted durable row.
    "toolrpc.speak",
})

logger = logging.getLogger("jarvis.orchestrator")
# Hermes absorption 5a — rows one research task hands back from the web search plugin.
_RESEARCH_MAX_RESULTS = 5


_DESKTOP_RUN_SCHEMA = {
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
}


_DESKTOP_RUN_DESCRIPTION = "Propose bounded governed desktop steps for approval."
#: H296 — how long desktop_run trusts one look at this host's desktop driver: the tool
#: list is built several times a turn, and the host probe touches the OS.
_DESKTOP_DRIVER_TTL = 60.0
#: That look: (when, the refusal reason or "", the actions the driver performs).
_desktop_driver_seen: tuple[float, str, frozenset] | None = None


def _desktop_driver_actions() -> tuple[str, frozenset]:
    """Why this host has no desktop driver ("" when it has one) and what its driver
    performs, from the same ``driver_for_host`` the approved run binds."""
    global _desktop_driver_seen
    import time

    from .desktop_drivers import SUPPORTED_ACTIONS
    from .routers import multimodal

    now = time.monotonic()
    seen = _desktop_driver_seen
    if seen is None or now - seen[0] >= _DESKTOP_DRIVER_TTL:
        choice = multimodal.driver_for_host()
        if choice.ok and choice.driver is not None:
            seen = (now, "", frozenset(getattr(choice.driver, "supported_actions", SUPPORTED_ACTIONS)))
        else:
            seen = (now, choice.reason or "desktop_dependency_unavailable", frozenset())
        _desktop_driver_seen = seen
    return seen[1], seen[2]


def _desktop_run_overrides() -> dict:
    """H296 — desktop_run names the step actions both its validator (the table
    ``validate_desktop_run_args`` checks) and this host's driver accept, or says why
    every call is refused: the desktop flags are off, or the host has no driver."""
    from copy import deepcopy

    from .desktop_operator import _DESKTOP_ARG_RULES
    from .routers.multimodal import desktop_host_enabled

    if not desktop_host_enabled():
        return {"description": _DESKTOP_RUN_DESCRIPTION + " The desktop operator is switched off on this "
                               "hub (JARVIS_DESKTOP_HOST, JARVIS_DESKTOP_ISOLATED), so every call is refused."}
    refusal, actions = _desktop_driver_actions()
    if refusal:
        return {"description": _DESKTOP_RUN_DESCRIPTION + f" This host has no desktop driver ({refusal}), "
                               "so every call is refused."}
    steps = deepcopy(_DESKTOP_RUN_SCHEMA["properties"]["steps"])
    steps["items"]["properties"]["action"]["enum"] = sorted(set(_DESKTOP_ARG_RULES) & actions)
    return {"properties": {"steps": steps}}


class AutonomyCoordinator:
    def __init__(self, orchestrator):
        self._orch = orchestrator
        self._kanban_dispatcher = None
        self._kanban_network_adapter = None
        self._reason_windows = {}
        self._reason_prompts = {}
        self._reason_clock = time.monotonic
        # 0.34 (opt-in): lazily-built durable workflow pending-queue, drained each
        # tick only when JARVIS_WORKFLOW_PERSIST is set (else stays None, no drain).
        self._pending_queue = None

    def kanban_dispatcher(self):
        """One controller shared by intake, the admin route, and approved execution."""
        if self._kanban_dispatcher is None:
            from .kanban.dispatcher import KanbanDispatcher

            self._kanban_dispatcher = KanbanDispatcher(self._orch)
        return self._kanban_dispatcher

    def kanban_network(self):
        """Share the URL approval adapter between ToolRPC and queued execution."""
        if self._kanban_network_adapter is None:
            from .kanban.network import NetworkAttachmentAdapter
            from .paths import data_path

            self._kanban_network_adapter = NetworkAttachmentAdapter(
                self._orch, home=data_path("kanban")
            )
        return self._kanban_network_adapter

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
        from .channels.outbound import _owner_chat_id

        self._wire_owner_once_prompts()
        self._wire_consent_prompts()
        owner = _owner_chat_id(self._orch, configured_owner=self._owner_settings().get("autonomy.owner_chat_id"))
        tg = self._orch.channels.get("telegram")
        if tg and owner and hasattr(tg, "send_card"):

            async def base(task):
                queue = getattr(self._orch, 'autonomy_queue', None)
                prompts = getattr(self._orch.autonomy, '_consent_prompts', None)
                offer = getattr(queue, 'pending_consent_offer', None)
                if prompts is not None and callable(offer) and offer(task.id) is not None:
                    return await prompts.notify(task, tg, int(owner))
                pending_group = getattr(queue, 'pending_group', None)
                group = pending_group(task.id) if callable(pending_group) else None
                card = build_decision_card(task, group=group) if group is not None else build_decision_card(task)
                return await tg.send_card(int(owner), card)

            self._orch.autonomy.notifier = self._away_notifier(base, exclude={"telegram"})
            tg.on_callback = self._on_callback
            tg.on_decision_reason = self._on_reason_reply
            # H117: the poll loop asks this (it has no side effects) whether a reply is a
            # reason, and runs the hook above in the chat's lane only when it is.
            tg.decision_reason_pending = self.would_consume_reason_reply
            # ...and reads this clock once per getUpdates page, stamping a claimed reply from
            # its page (credited by Telegram's date, never before the previous page came back),
            # so the hook judges the reason window by that stamp, not by when the chat's lane
            # reached the reply.
            tg.decision_reason_clock = self.reason_clock
            logger.info(
                "Autonomy decision inbox wired to Telegram (H34.2 away-notify via escalation)"
            )

    def _wire_owner_once_prompts(self):
        """Enroll the current reply transport before native intake can settle DENY."""
        from .autonomy.owner_once_prompts import OwnerOncePrompts
        from .channels.telegram import TelegramChannel

        worker = getattr(self._orch, 'autonomy', None)
        channel = (getattr(self._orch, 'channels', {}) or {}).get('telegram')
        previous = getattr(self, '_owner_once_prompts', None)
        old_channel = getattr(self, '_owner_once_channel', None)
        if (previous is not None and (previous.worker is not worker
                or previous.queue is not getattr(worker, 'queue', None)
                or old_channel is not channel)):
            previous.stop(getattr(old_channel, '_owner_once_generation', None))
            if getattr(previous.worker, '_owner_once_prompts', None) is previous:
                previous.worker._owner_once_prompts = None
            self._owner_once_prompts = previous = None
        if worker is None or not isinstance(channel, TelegramChannel):
            return
        if previous is None:
            previous = OwnerOncePrompts(self)
            self._owner_once_prompts = previous
            self._owner_once_channel = channel
        # Retain stable hooks/registrations across ordinary runtime rewiring.
        previous.install(channel)
        worker._owner_once_prompts = previous

    def _wire_consent_prompts(self):
        """Retain reusable reply registrations only for the current transport."""
        from .autonomy.consent_prompts import ConsentPrompts
        from .channels.telegram import TelegramChannel

        worker = getattr(self._orch, 'autonomy', None)
        channel = (getattr(self._orch, 'channels', {}) or {}).get('telegram')
        previous = getattr(self, '_consent_prompts', None)
        old_channel = getattr(self, '_consent_channel', None)
        if previous is not None and (previous.worker is not worker
                or previous.queue is not getattr(worker, 'queue', None)
                or old_channel is not channel):
            previous.stop(getattr(old_channel, '_owner_once_generation', None))
            if getattr(previous.worker, '_consent_prompts', None) is previous:
                previous.worker._consent_prompts = None
            self._consent_prompts = previous = None
        if worker is None or not isinstance(channel, TelegramChannel):
            return
        if previous is None:
            previous = ConsentPrompts(self)
            self._consent_prompts = previous
            self._consent_channel = channel
        previous.install(channel)
        worker._consent_prompts = previous

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
            task = await self._orch.autonomy.apply_decision(task_id, action, decided_by="telegram")
            windows = getattr(self, "_reason_windows", {})
            windows.pop((str(chat_id), str(user_id)), None)
            if action == "reject" and isinstance(getattr(task, "human_decision", None), dict):
                await self._offer_reason(task, chat_id, user_id)
            return f"Task #{task_id}: {action}"
        except Exception as e:
            logger.warning(f"Autonomy decision callback failed: {e}")
            return None

    async def _offer_reason(self, task, chat_id, user_id):
        channel = self._telegram_channel()
        record = task.human_decision
        if (record.get("action") != "reject" or record.get("by") != "telegram"
                or record.get("reason") is not None or not record.get("id")):
            return
        try:
            prompt = await channel.request_decision_reason(task.id, chat_id=chat_id)
            if type(prompt) is not int or prompt <= 0:
                return
        except Exception:
            logger.warning("Telegram decision reason prompt unavailable")
            return
        now = self._reason_clock()
        # Expired windows are pruned only to make room: a reply that arrived in time may still
        # be waiting in the chat's lane behind this rejection (another member of a group owner
        # chat), and it is judged by when it arrived, so its window must still be there (H117).
        if len(self._reason_windows) >= 32:
            self._reason_windows = {key: window for key, window in self._reason_windows.items()
                                    if window["deadline"] > now}
        if len(self._reason_windows) >= 32:
            self._reason_windows.pop(next(iter(self._reason_windows)))
        self._reason_windows[(str(chat_id), str(user_id))] = {
            "task_id": task.id, "prompt": prompt, "expected": dict(record), "deadline": now + 120,
        }
        self._reason_prompts[(str(chat_id), str(user_id), prompt)] = True
        if len(self._reason_prompts) > 64:
            self._reason_prompts.pop(next(iter(self._reason_prompts)))

    def _reason_reply_target(self, chat_id, user_id, reply_to_message_id):
        """What a reply answers, read without side effects: ``None`` when it is no reason
        reply (it stays a chat message); ``("window", key, window)`` when it answers the
        owner's open window (live or expired); ``("stale", key, None)`` when it answers an
        earlier prompt of this owner (superseded, answered, or expired and pruned)."""
        if type(reply_to_message_id) is not int or reply_to_message_id <= 0:
            return None
        if not self._callback_is_owner(chat_id, user_id):
            return None
        key = (str(chat_id), str(user_id))
        window = self._reason_windows.get(key)
        if window is not None and window["prompt"] == reply_to_message_id:
            return "window", key, window
        if (*key, reply_to_message_id) in self._reason_prompts:
            return "stale", key, None
        return None

    def reason_clock(self) -> float:
        """Now, on the clock reason windows are opened and closed with (read live, so a clock
        swapped after :meth:`wire` counts). Telegram's poll loop reads it once per getUpdates
        page and hands a claimed reply's stamp, taken from that reading, to
        :meth:`_on_reason_reply` as ``received_at`` (H117)."""
        return self._reason_clock()

    def would_consume_reason_reply(self, chat_id, user_id, reply_to_message_id) -> bool:
        """Would :meth:`_on_reason_reply` consume this reply right now? Exactly the same
        test (the owner, in the owner chat, replying to one of their reason prompts), with
        no side effect: nothing is saved, sent or closed. Telegram's poll loop asks this to
        decide, and runs the reply through ``_on_reason_reply`` in the chat's lane (H117)."""
        return self._reason_reply_target(chat_id, user_id, reply_to_message_id) is not None

    async def _reason_ack(self, chat_id, text) -> None:
        """Answer a consumed reason reply with a service line. Never spoken (``voice=False``:
        it neither goes to TTS nor takes the voice-for-voice mark of a turn in that chat),
        and best effort: once a reply is consumed, and above all once its reason is saved,
        a failed acknowledgement never turns it back into a chat turn."""
        try:
            await self._telegram_channel().send(text, chat_id=chat_id, voice=False)
        except Exception:
            logger.warning("Telegram decision reason acknowledgement failed", exc_info=True)

    async def _on_reason_reply(self, text, *, chat_id, user_id, reply_to_message_id, received_at=None):
        """Consume only the owner's reply to a live prompt for an exact decision.

        Returns False, before any side effect, only for a reply that is no reason reply
        (see :meth:`would_consume_reason_reply`); every other outcome is True. It never
        raises once the reason is saved, so a caller's fallback on an exception (running the
        reply as a turn) can only follow a failure before anything was saved.

        ``received_at`` is the channel's stamp of when the reply arrived, on
        :meth:`reason_clock`. Telegram stamps it from the getUpdates page that carried the
        reply: never later than when that page came back, never earlier than when the page
        before it did (the first bound wins should this clock step back between pages), and
        within those bounds moved back by Telegram's date for the reply, as far as the host's
        clock and Telegram's agree (see ``TelegramChannel._reason_arrival``); the reply may
        then wait in the chat's lane behind a slow turn. The deadline is checked against the
        stamp, so the time the reply waits after its page came back never counts against it,
        and a reply stamped at or after the deadline is refused however soon it runs. Missing,
        or not a finite instant, it is now (an older caller). Whether the prompt is still the
        live one is decided here, when the lane reaches the reply: a tap read before the reply
        runs before it and supersedes the prompt."""
        target = self._reason_reply_target(chat_id, user_id, reply_to_message_id)
        if target is None:
            return False
        kind, key, window = target
        if kind == "stale":
            await self._reason_ack(chat_id, "That reason prompt is no longer active; no decision changed.")
            return True
        arrived = (received_at if type(received_at) in (int, float) and math.isfinite(received_at)
                   else self._reason_clock())
        if arrived >= window["deadline"]:
            self._reason_windows.pop(key, None)
            await self._reason_ack(chat_id, "The reason window expired; the rejection is unchanged.")
            return True
        try:
            task = self._orch.autonomy_queue.attach_human_reason(
                window["task_id"], text, expected_decision=window["expected"],
            )
        except ValueError:
            await self._reason_ack(chat_id, "Use a nonempty reason of at most 280 characters.")
            return True
        except Exception:
            logger.warning("Telegram decision reason could not be saved")
            await self._reason_ack(chat_id, "The reason could not be saved; the rejection is unchanged.")
            return True
        self._reason_windows.pop(key, None)
        if task is not None:
            try:
                self._orch.autonomy._audit("autonomy.decision.reason", task,
                                          "by telegram: " + task.human_decision["reason"])
            except Exception:
                logger.warning("Telegram decision reason audit failed after the save", exc_info=True)
        await self._reason_ack(chat_id, "Reason saved." if task is not None else "That decision no longer accepts a reason.")
        return True

    def _callback_is_owner(self, chat_id, user_id) -> bool:
        """Is this button tap the owner's?

        A configured destination must match. Sender identity comes from the explicit
        owner allowlist or the exact private owner chat; a group destination alone
        identifies no owner.
        """
        from .telegram_owner import is_telegram_owner_sender, telegram_owner_user_ids
        from .channels.outbound import _owner_chat_id

        owner_settings = self._owner_settings()
        owner_chat = _owner_chat_id(self._orch, configured_owner=owner_settings.get("autonomy.owner_chat_id"))
        if not owner_chat or str(chat_id or "") != owner_chat:
            return False
        return is_telegram_owner_sender(
            user_id, chat_id=chat_id, owner_chat_id=owner_chat,
            allowed_user_ids=telegram_owner_user_ids(
                owner_settings.get("autonomy.owner_user_ids"),
                allowed_user_ids=getattr(self._telegram_channel(), "allowed_users", None),
            ),
        )

    def _owner_settings(self) -> dict:
        provider = getattr(self._orch, "_telegram_owner_settings", None)
        if callable(provider):
            return provider()
        return {key: self._orch.get_setting(key, None)
                for key in ("autonomy.owner_chat_id", "autonomy.owner_user_ids")}

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
                # Expiry is queue metadata only under e-stop. Ledger resume and
                # notifications stay in the durable outbox until release.
                worker = getattr(self._orch, "autonomy", None)
                if worker is not None:
                    try:
                        await worker.approval_housekeeping(reconcile=False, notify_promotions=False)
                    except Exception:
                        logger.warning("Approval expiry metadata sweep failed under e-stop", exc_info=True)
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
                dispatch_settings_unavailable = False
                try:
                    dispatch_enabled = amode != "off" and all(
                        self._orch.get_setting(key, False) is True
                        for key in ("llm.kanban", "llm.kanban_dispatch", "llm.tool_loop_enabled")
                    )
                except Exception:
                    logger.warning("Kanban dispatch settings unavailable", exc_info=True)
                    dispatch_enabled = False
                    dispatch_settings_unavailable = True
                if dispatch_enabled:
                    await self.kanban_dispatcher().approved_tick(max_tier=max_tier)
                elif dispatch_settings_unavailable:
                    from .kanban.dispatcher import KanbanDispatcher

                    await self._orch.autonomy.tick(
                        max_tier=max_tier,
                        parallel_kind=KanbanDispatcher.KIND,
                        parallel_limit=0,
                        parallel_agent_limit=0,
                    )
                else:
                    await self._orch.autonomy.tick(max_tier=max_tier)
                try:
                    if dispatch_enabled:
                        await self.kanban_dispatcher().tick()
                except Exception:
                    logger.warning("Kanban dispatcher intake failed", exc_info=True)
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

    def _submit_job_script(self, payload, origin):
        """A scheduler proposal gets a new ask-tier task, never a standing grant."""
        from .autonomy.jobs_scripts import ScriptSubmissionRefused
        from .env_config import env_flag

        worker = getattr(self._orch, 'autonomy', None)
        if (not env_flag('JARVIS_TERMINAL_TARGETS') or not env_flag('JARVIS_TERMINAL_LOCAL_HOST')
                or not callable(getattr(worker, 'govern_enqueue', None))):
            raise ScriptSubmissionRefused('governed local terminal script intake is unavailable')
        if payload.get('tool') != 'terminal_run' or payload.get('args', {}).get('target') != 'local-host':
            raise ScriptSubmissionRefused('scheduled scripts require the governed local terminal')
        return worker.govern_enqueue(agent='jarvis', kind='toolrpc.terminal_run',
            title='Scheduled Python script awaiting this run approval', payload=payload,
            risk_tier=3, autonomy_level='ask', origin=origin)

    def _wire_agent_tool_runtime(self, action_kernel=None):
        """Build the shared, default-off governed tool loop for loaded agents."""
        # Keep imports local: AgentToolRuntime imports ToolRPCServer, while the
        # orchestrator imports this coordinator during boot.
        import time as _t

        from .agent_runtime import AgentToolRuntime
        from .tool_profiles import ToolProfileResolver
        from .tool_result_store import ToolResultStore
        from .acquisition.runtime import AcquisitionRuntime
        from .desktop_operator import DesktopProposalError, validate_desktop_run_args
        from .observability import capability_registry
        from .tool_rpc import ToolRPCServer, ToolRPCValidationError

        execution_token = object()

        def _smart_terminal_approved(task_id):
            worker = getattr(self._orch, 'autonomy', None)
            check = getattr(worker, 'smart_terminal_approved', None)
            try:
                return callable(check) and check(task_id) is True
            except Exception:
                return False

        def _human_terminal_approval(task):
            metadata = task.human_decision
            return (task.decision in {'accept', 'edit'}
                    and str(task.decided_by).lower() not in {'policy', 'smart_approval'}
                    and isinstance(metadata, dict) and metadata.get('action') == task.decision
                    and metadata.get('by') == task.decided_by)

        def _smart_terminal_marker(task_id):
            # Classification is independent of live consent. Revocation must
            # refuse a machine operation, never downgrade it to legacy Docker.
            task = self._orch.autonomy_queue.get(task_id)
            return task is not None and (task.decision == 'smart-approve'
                                        or task.decided_by == 'smart_approval')

        def _owner_terminal_marker(task_id):
            task = self._orch.autonomy_queue.get(task_id)
            return task is not None and (task.decision == 'owner-once'
                                        or task.decided_by == 'owner_once')

        def _owner_terminal_approved(task_id):
            from .autonomy.owner_once_execution import owner_once_current

            return owner_once_current(task_id)

        def _consent_terminal_marker(task_id):
            queue = getattr(self._orch, 'autonomy_queue', None)
            marker = getattr(queue, 'consent_task_marker', None)
            return callable(marker) and marker(task_id)

        def _consent_terminal_approved(task_id):
            from .autonomy.consent_execution import consent_current

            return _consent_terminal_marker(task_id) and consent_current(task_id)

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
            if persisted.kind in {'toolrpc.file_write', 'toolrpc.file_delete'} and queue.mediation_mode != 'off':
                worker = getattr(self._orch, 'autonomy', None)
                if queue.mediation_mode != 'enforce' or getattr(worker, 'queue', None) is not queue:
                    return False
                try:
                    permit = worker._execution_context.get()
                    fingerprint = queue.execution_fingerprint(task)
                    if (permit is None or not permit.consumed or not fingerprint
                            or getattr(permit, '_fingerprint', None) != fingerprint
                            or not queue.validate_mediated_execution(task, fingerprint)):
                        return False
                except Exception:
                    return False
            if is_video_task(persisted):
                if queue.mediation_mode != "enforce":
                    return False
                try:
                    if not queue.validate_mediated_execution(
                            task, queue.execution_fingerprint(task)):
                        return False
                except Exception:
                    return False
            return (
                persisted.status == "running"
                and (persisted.kind in _TRUSTED_TOOL_RPC_KINDS or is_image_task(persisted)
                     or is_video_task(persisted))
                and persisted.autonomy_level == "ask"
                and ((persisted.decision in {"accept", "edit"}
                      and (persisted.kind != 'toolrpc.terminal_run' or _human_terminal_approval(persisted)))
                     or (persisted.kind == 'toolrpc.terminal_run'
                         and persisted.decision == 'smart-approve'
                         and queue.execution_fingerprint(persisted) == queue.execution_fingerprint(task)
                         and _smart_terminal_approved(task_id))
                     or (persisted.kind == 'toolrpc.terminal_run'
                         and _owner_terminal_marker(task_id)
                         and queue.execution_fingerprint(persisted) == queue.execution_fingerprint(task)
                         and _owner_terminal_approved(task_id))
                     or (persisted.kind == 'toolrpc.terminal_run'
                         and _consent_terminal_marker(task_id)
                         and queue.execution_fingerprint(persisted) == queue.execution_fingerprint(task)
                         and _consent_terminal_approved(task_id)))
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

        from .image_generation_runtime import LocalImageRuntime, is_image_task
        from .video_analysis import is_video_task
        from .image_tool_dispatcher import INPUT_SCHEMA, ImageToolDispatcher

        image_runtime = LocalImageRuntime(
            queue=getattr(self._orch, "autonomy_queue", None),
            approved_task=_APPROVED_TASK.get,
            authorizer=action_kernel,
            enqueue=self._governed_enqueue,
        )
        image_dispatcher = ImageToolDispatcher(
            image_runtime, cloud_runtime=lambda: getattr(self._orch, "cloud_images", None),
            approved_task=_APPROVED_TASK.get,
        )
        server = ToolRPCServer(
            secret_broker=getattr(self._orch, "secret_broker", None),
            enqueue=self._governed_enqueue,
            audit=getattr(self._orch, "intent_log", None),
            kernel=action_kernel,
            execution_context_check=_approved_execution_context,
        )
        from .channels.pending_input_runtime import register_clarify_tool

        register_clarify_tool(server, self._orch)
        server.register_tool(
            "image_generate", image_dispatcher.execute, gated=True,
            description="Propose one image: local ComfyUI by default, or explicit paid OpenAI cloud generation; human approval required.",
            input_schema=INPUT_SCHEMA, capability_id="tool:image_generate",
            preflight=image_dispatcher.preflight, trusted_execution=True,
            gated_intake=image_dispatcher.intake,
        )
        from .env_config import env_flag
        if env_flag("JARVIS_VIDEO_ANALYSIS"):
            from .video_analysis import INPUT_SCHEMA as VIDEO_INPUT_SCHEMA, VideoAnalysisTool

            video_tool = VideoAnalysisTool(
                approved_task=_APPROVED_TASK.get,
                execution_check=lambda task: _approved_execution_context(execution_token, task),
                kernel_check=lambda args, task: server._kernel_denial(
                    "video_analyze", args, getattr(task, "agent", None) or server.agent),
                enqueue=self._governed_enqueue,
                queue=getattr(self._orch, "autonomy_queue", None),
                router=getattr(self._orch, "llm_router", None),
            )
            server.register_tool(
                "video_analyze", video_tool.execute, gated=True,
                description="Analyze one scoped workspace video or public video URL with the configured video model; owner approval required.",
                input_schema=VIDEO_INPUT_SCHEMA, capability_id="tool:video_analyze",
                preflight=video_tool.preflight, classifier=video_tool.classifier,
                trusted_execution=True, gated_intake=video_tool.intake,
                untrusted_output=True,
                max_result_bytes=16_384,
            )
        # H313 — the model may decide to say one thing aloud on one room's speaker.
        # Default-off (registered only with the Media Director on) and gated like
        # image_generate, with its own intake so the kernel sees the exact row the
        # card becomes; the approved run presents the clip through
        # CapabilityActionAPI("action:media.present", mode announce), so the kernel
        # authorizes the effect and the tool itself never reaches a driver.
        from .voice.speak_tool import register_speak_tool

        def _media_director():
            from .routers.media_director import get_director

            return get_director()

        register_speak_tool(
            server,
            director=_media_director,
            approved_task=_APPROVED_TASK.get,
            authorizer=action_kernel,
            enqueue=self._governed_enqueue,
            interrupt_budget=lambda: getattr(
                getattr(self._orch, "autonomy", None), "budget", None),
            audit=lambda: getattr(self._orch, "intent_log", None),
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
            description=_DESKTOP_RUN_DESCRIPTION,
            # H296: the actions the step validator and this host's driver accept.
            schema_overrides=_desktop_run_overrides,
            input_schema=_DESKTOP_RUN_SCHEMA,
            capability_id="tool:desktop_run",
            preflight=_desktop_preflight,
            trusted_execution=True,
        )

        def _durable_terminal_approval(task_id):
            """True only for a running terminal row with owner or sealed machine approval.

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
                and (_human_terminal_approval(persisted)
                     or (persisted.decision == 'smart-approve' and _smart_terminal_approved(task_id))
                     or (_owner_terminal_marker(task_id) and _owner_terminal_approved(task_id))
                     or (_consent_terminal_marker(task_id) and _consent_terminal_approved(task_id)))
                and bool(persisted.decided_by)
                and str(persisted.decided_by).lower() != "policy"
            )

        def _terminal_request_check(task_id, request):
            from .autonomy.smart_approvals import smart_policy
            from .env_config import env_flag
            from .kernel import kernel_enabled

            queue = getattr(self._orch, 'autonomy_queue', None)
            if (queue is None or not env_flag('JARVIS_TERMINAL_TARGETS')
                    or not smart_policy().command_allowed(request.get('command'))):
                return False
            task = queue.get(task_id)
            from .tool_rpc import current_tool_actor

            if task is not None and (_smart_terminal_marker(task_id) or _owner_terminal_marker(task_id)
                                     or _consent_terminal_marker(task_id)):
                from .autonomy.approval_judge import action_is_tainted

                if (not kernel_enabled()
                        or action_is_tainted({'origin': task.origin, 'payload': task.payload})):
                    return False

            return (task is not None and task.payload.get('args') == request
                    and task.agent == current_tool_actor()
                    and _durable_terminal_approval(task_id))

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
            from .autonomy.consent_registration import trusted_registration_key

            worker = getattr(self._orch, 'autonomy', None)
            terminal_spec = server._tools.get('terminal_run')
            registration_snapshot = (trusted_registration_key('terminal_run', terminal_spec)
                                     if terminal_spec is not None else None)
            manual_task = (approved if approved is not None
                           and _human_terminal_approval(approved) else None)
            manual_queue = getattr(self._orch, 'autonomy_queue', None)
            manual_mode = getattr(manual_queue, 'mediation_mode', None)
            manual_fingerprint = (manual_queue.execution_fingerprint(manual_task)
                                  if manual_task is not None and manual_queue is not None else None)
            manual_mediated = (manual_task is not None and any(
                getattr(manual_task, name, None) not in (None, '')
                for name in ('mediation_enqueue_id', 'mediation_enqueue_revision',
                             'mediation_scope', 'mediation_policy_revision',
                             'mediation_receipt', 'mediation_task_sha256',
                             'mediation_execution_id')
            ))

            def manual_execution_current(task_id):
                if manual_task is None:
                    return True
                if (task_id != manual_task.id or not manual_fingerprint
                        or manual_mode not in {'off', 'enforce'}
                        or (manual_mediated and manual_mode != 'enforce')
                        or self._orch.autonomy_queue is not manual_queue
                        or getattr(worker, 'queue', None) is not manual_queue
                        or manual_queue.mediation_mode != manual_mode):
                    return False
                try:
                    if manual_queue.execution_fingerprint(manual_task) != manual_fingerprint:
                        return False
                    if manual_mode == 'enforce':
                        return manual_queue.validate_mediated_execution(
                            manual_task, manual_fingerprint) is True
                    persisted = manual_queue.get(task_id)
                    return (persisted is not None and persisted.status == 'running'
                            and manual_queue.execution_fingerprint(persisted)
                            == manual_fingerprint
                            and manual_queue.mediation_mode == 'off')
                except Exception:
                    return False

            def current_request(task_id, request):
                if approved is not None and isinstance(approved.payload, dict) and 'kanban_child' in approved.payload:
                    from .kanban.workspace_context import current_workspace

                    try:
                        binding = current_workspace()
                        if binding is None or str(binding.cwd) != approved.payload['kanban_child']['cwd']:
                            return False
                        binding.check()
                    except Exception:
                        return False
                return (self._orch.autonomy is worker
                        and self._orch.tool_rpc is server
                        and terminal_spec is not None
                        and server._tools.get('terminal_run') is terminal_spec
                        and registration_snapshot is not None
                        and trusted_registration_key('terminal_run', terminal_spec)
                        == registration_snapshot
                        and manual_execution_current(task_id)
                        and _terminal_request_check(task_id, request))

            def checkpoint_origin_lookup(task_id):
                """Read only the exact executing birth's durable provenance."""
                import uuid

                if (type(task_id) is not int or task_id <= 0 or approved is None
                        or task_id != approved.id or manual_queue is None
                        or self._orch.autonomy is not worker
                        or self._orch.autonomy_queue is not manual_queue
                        or getattr(worker, 'queue', None) is not manual_queue):
                    return None
                try:
                    task = manual_queue.get(task_id)
                    if (task is None or task.kind != 'toolrpc.terminal_run'
                            or task.created_at != approved.created_at):
                        return None
                    origin = manual_queue.checkpoint_origin_turn(task_id, task.created_at)
                    return task.created_at, str(uuid.UUID(hex=origin)) if origin else None
                except Exception:
                    return None

            child_transport = None
            if approved is not None and isinstance(approved.payload, dict) and 'kanban_child' in approved.payload:
                from .environments.local_transport import LocalHostTransport, default_timeout
                from .kanban.workspace_context import current_workspace

                binding = current_workspace()
                if binding is None or args.get('target') != 'local-host' or args.get('cwd') != str(binding.cwd):
                    return {'ok': False, 'reason': 'kanban_terminal_execution_unbound'}
                child_transport = LocalHostTransport([binding.cwd], default_timeout=default_timeout())

            runner = GovernedTargetRunner(
                self._target_registry(),
                getattr(self._orch, "sandbox", None),
                local_transport=child_transport,
                authorizer=action_kernel,
                approval_check=_durable_terminal_approval,
                request_check=current_request,
                smart_approval_check=_smart_terminal_marker,
                owner_approval_check=_owner_terminal_marker,
                owner_kernel_check=getattr(worker, 'kernel_dispatch_current', None),
                consent_approval_check=_consent_terminal_marker,
                consent_kernel_check=getattr(worker, 'kernel_dispatch_current', None),
                legacy_kernel_check=getattr(worker, 'kernel_dispatch_current', None),
                checkpoint_origin_lookup=checkpoint_origin_lookup,
            )
            from .action_origin import bind_action_origin, reset_action_origin

            origin_token = bind_action_origin(getattr(approved, 'origin', 'generated'))
            try:
                result = await runner.run(
                    target=args["target"], agent=getattr(approved, 'agent', ''),
                    command=args["command"], approved_task_id=approved_task_id,
                    cwd=args.get("cwd"), timeout=args.get("timeout"),
                )
            finally:
                reset_action_origin(origin_token)
            from .security.log_redaction import SecretRedactionFilter

            output_redactor = SecretRedactionFilter()
            for stream in ("stdout", "stderr"):
                if isinstance(result.get(stream), str):
                    # The transport already exposes this validated directory as
                    # metadata. Do not mistake its exact pwd echo for a secret;
                    # broker redaction still applies before ToolRPC returns it.
                    if (stream == "stdout" and result.get("cwd")
                            and result[stream].rstrip("\r\n") == result["cwd"]):
                        continue
                    result[stream] = output_redactor.redact_text(result[stream])
            from . import project_context   # H594: the terminal moved into a project directory

            if approved_task_id is not None and args.get("cwd"):
                await asyncio.to_thread(project_context.note_terminal, approved_task_id, result, args["cwd"])
            return result

        def _terminal_intake(actor, args):
            """Finalize the typed terminal task before its kernel/intake decision."""
            from .kanban.context import current_context, scope_is_bound

            board_scope = current_context()
            from .kanban.child_tools import ChildToolAdapter

            child_adapter = ChildToolAdapter(self.kanban_dispatcher())
            if scope_is_bound() and (board_scope is None or board_scope.task_id is not None
                                     or board_scope.run_id is not None):
                try:
                    child = child_adapter.prepare(actor, 'terminal_run', args, {})
                except ToolRPCValidationError as exc:
                    raise ToolRPCValidationError('kanban_terminal_execution_unbound') from exc
            else:
                child = None
            from .approval_outcomes import tool_approval_scope
            from .autonomy.approval_grouping import model_request_scope
            from .autonomy.consent_registration import trusted_registration_key
            from .kernel import Action, Decision, Verdict, kernel_enabled

            worker = getattr(self._orch, 'autonomy', None)
            if not callable(getattr(worker, 'govern_enqueue', None)):
                raise ToolRPCValidationError('terminal_intake_unavailable')
            self._wire_owner_once_prompts()
            self._wire_consent_prompts()
            title = "Tool 'terminal_run' via RPC"
            payload = {'tool': 'terminal_run', 'target': 'terminal_run', 'args': dict(args),
                       **child_adapter.payload(child)}
            # Production worker intake owns the bridge and creates one exact
            # typed Action; do not leave a broad tool.rpc decision for that CAS.
            if action_kernel is not None and kernel_enabled():
                decision = action_kernel(Action(kind='toolrpc.terminal_run', agent=actor,
                                                title=title, payload=payload))
                if not isinstance(decision, Decision) or decision.verdict is Verdict.DENY:
                    raise ToolRPCValidationError('kernel_denied')
            spec = server._tools.get('terminal_run')
            with tool_approval_scope('terminal_run'), model_request_scope(
                actor=actor, tool='terminal_run', args=args,
                epoch=spec.get('_grouping_epoch') if spec else None,
                registration_is_live=lambda: server._tools.get('terminal_run') is spec,
                registration_key=spec.get('_consent_registration_key') if spec else None,
                registration_key_is_live=lambda candidate: (
                    server._tools.get('terminal_run') is spec
                    and trusted_registration_key('terminal_run', spec) == candidate
                ),
            ):
                task_id = worker.govern_enqueue(actor, 'toolrpc.terminal_run', title,
                                                payload=payload, risk_tier=3,
                                                autonomy_level='ask', origin='generated')
            child_adapter.bind(child, task_id)
            prompts = getattr(worker, '_owner_once_prompts', None)
            if prompts is not None:
                prompts.register_invocation(
                    task_id, check=lambda: (server._tools.get('terminal_run') is spec
                                              and getattr(self._orch, 'autonomy', None) is worker),
                )
            consent_prompts = getattr(worker, '_consent_prompts', None)
            if consent_prompts is not None:
                consent_prompts.register_invocation(
                    task_id, check=lambda: (server._tools.get('terminal_run') is spec
                                              and getattr(self._orch, 'autonomy', None) is worker),
                )
            from . import project_context

            project_context.note_task(task_id)
            return task_id

        async def _terminal_review(actor, args, task_id):
            from .autonomy.terminal_review import review_terminal_task

            worker = getattr(self._orch, 'autonomy', None)
            spec = server._tools.get('terminal_run')
            try:
                return await review_terminal_task(
                    worker, actor=actor, args=args, task_id=task_id,
                    registration_is_live=lambda: (server._tools.get('terminal_run') is spec
                                                   and getattr(self._orch, 'autonomy', None) is worker),
                )
            finally:
                prompts = getattr(worker, '_owner_once_prompts', None)
                if prompts is not None:
                    prompts.release_invocation(task_id)
                consent_prompts = getattr(worker, '_consent_prompts', None)
                if consent_prompts is not None:
                    consent_prompts.release_invocation(task_id)
                worker._settle_terminal_denial(task_id)

        server.register_tool(
            "terminal_run",
            _rpc_terminal_run,
            gated=True,
            gated_intake=_terminal_intake,
            gated_review=_terminal_review,
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
            schema_overrides=self._terminal_run_overrides,
            consent_revision="nerva.terminal_run.v1",
        )

        queue = getattr(self._orch, 'autonomy_queue', None)
        bind_consent = getattr(queue, 'bind_consent_resolver', None)
        if callable(bind_consent):
            from .autonomy.terminal_consent_runtime import build_terminal_consent_resolver

            bind_consent(build_terminal_consent_resolver(
                self._orch, self._target_registry, server, server._tools['terminal_run'],
            ))

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
            # Hermes absorption 5a — its rows come from live lookups on
            # attacker-influenceable indicators, so the loop fences them as data. Today
            # the declaration is dormant: gated, the tool answers approval_required in the
            # loop and its approved run lands in the task row, never in a transcript; it
            # takes effect the day a gated result is fed back to the model.
            untrusted_output=True,
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
        # Hermes absorption 3a — the model may search what was actually said. Read-only,
        # inside the data root, bounded, and every hit is scanned for injection before it
        # reaches the model. Who may ask is the tool profile's decision (3b), not the tool's.
        from .memory.session_search import register_session_search

        register_session_search(server)
        # 1.1.0 operator wave — governed file read/list/search/write/delete. Default-off:
        # register_file_tools returns [] and touches nothing unless JARVIS_FILE_TOOLS
        # is set. The two mutating tools are gated, so they can only run from an
        # owner-approved durable task, and each write crosses the Action Kernel with
        # a snapshot already taken so the rollback contract is real.
        from .file_tools import FileTools, register_file_tools
        from .tool_result_store import default_root as spill_root

        # H661 — `file_read` also gets the tool-result spill directory as a read-only
        # door for exact spill names, so an owner's JARVIS_FILE_ROOTS cannot strand the
        # file a spilled result's notice tells the model to page. Inert while the file
        # tools are off: nothing is registered, and the probe below says no.
        file_tools = FileTools.from_env(
            authorizer=action_kernel,
            audit=getattr(self._orch, "intent_log", None),
            spill_dirs=(spill_root(),),
        )
        def _file_mutation_intake(actor, name, args, labels):
            """Queue the registered, finalized file operation under its exact kind."""
            from .kanban.child_tools import ChildToolAdapter
            from .kernel import Action, Decision, Verdict, kernel_enabled
            from .approval_outcomes import tool_approval_scope

            child_adapter = ChildToolAdapter(self.kanban_dispatcher())
            child = child_adapter.prepare(actor, name, args, labels)
            worker = getattr(self._orch, 'autonomy', None)
            if name not in {'file_write', 'file_delete'} or not callable(getattr(worker, 'govern_enqueue', None)):
                raise ToolRPCValidationError('file_intake_unavailable')
            title = f"Tool '{name}' via RPC"
            notice = (labels or {}).get('notice')
            if isinstance(notice, str) and notice:
                title += f" — {notice}"
            payload = {'tool': name, 'target': name, 'args': dict(args),
                       **dict(labels or {}), **child_adapter.payload(child)}
            if action_kernel is not None and kernel_enabled():
                decision = action_kernel(Action(kind='toolrpc.' + name, agent=actor,
                                                title=title, payload=payload))
                if not isinstance(decision, Decision) or decision.verdict is Verdict.DENY:
                    raise ToolRPCValidationError('kernel_denied')
            from .autonomy.approval_grouping import model_request_scope
            from .autonomy.consent_registration import trusted_registration_key

            spec = server._tools.get(name)
            with tool_approval_scope(name), model_request_scope(
                actor=actor, tool=name, args=args,
                epoch=spec.get('_grouping_epoch') if spec else None,
                registration_is_live=lambda: server._tools.get(name) is spec,
                registration_key=spec.get('_consent_registration_key') if spec else None,
                registration_key_is_live=lambda candidate: (
                    server._tools.get(name) is spec and trusted_registration_key(name, spec) == candidate
                ),
            ):
                task_id = worker.govern_enqueue(actor, 'toolrpc.' + name, title,
                                               payload=payload, risk_tier=3,
                                               autonomy_level='ask', origin='generated')
            child_adapter.bind(child, task_id)
            return task_id

        register_file_tools(server, file_tools, mutation_intake=_file_mutation_intake)

        def _spill_readable(path: str) -> bool:
            # H661 — a spill notice names `file_read(path=…)` only when that call would
            # be answered: the tool is registered and not fenced off by a job toolset,
            # the turn in flight was offered it, and the live scope (or the spill door)
            # opens this very path. Registered alone is not reachable.
            from .job_toolsets import allows

            if not server.allows("file_read") or not allows("file_read"):
                return False
            offer = _TURN_TOOL_OFFER.get()
            if offer is not None and "file_read" not in offer:
                return False
            return file_tools.reaches(path)
        # Hermes absorption 5a — the model can look things up and search its own memory.
        # What it reads is declared data: the two web tools are registered
        # untrusted_output, search_memory declares taint per hit, and the tool loop fences
        # every such result and marks the turn. Who may ask is still the tool profile's
        # decision (3b); the plugin and the memory manager are read per call, so a plugin
        # that appears or disappears after boot is honoured without a re-wire.
        from .web_tools import register_web_tools

        register_web_tools(
            server,
            lambda: (getattr(self._orch, "plugins", None) or {}).get("websearch"),
        )
        from .memory.rag_tool import register_search_memory

        register_search_memory(
            server,
            lambda: getattr(getattr(self._orch, "memory", None), "recall", None),
        )

        acquisition = AcquisitionRuntime(
            enabled=lambda: _get_setting("acquisition.enabled", False) is True,
        )
        bind_external_orchestrator_attribute(self._orch, "acquisition", acquisition)

        # Hermes absorption 3b — least privilege at the moment of offering: the profile
        # (agent × surface × principal) decides which registered tools this turn's model
        # even sees. Principal and origin are read per call, so a Telegram guest's turn and
        # the owner's HUD turn resolve differently on the same runtime.
        def _turn_principal():
            from .orchestrator import current_principal

            return current_principal()

        from .kanban.runtime import register_kanban_tools
        from .paths import data_path
        register_kanban_tools(
            server,
            home=lambda: data_path("kanban"),
            enabled=lambda: _get_setting("llm.kanban", False) is True,
            principal=_turn_principal,
            session_id=lambda: str(getattr(self._orch, "session_id", "") or "") or None,
            profiles=lambda: tuple(getattr(self._orch, "agents", {}) or {}),
            network=self.kanban_network,
        )

        def _agent_tool_patterns(agent_id):
            config = getattr(self._orch, "config", None)
            agents = getattr(config, "agents", None) or {}
            return getattr(agents.get(agent_id), "tools", None)

        def _on_shared_session() -> bool:
            # H315 review — a turn with no session of its own runs on the HUD's shared
            # session; what a session-scoped tool keeps there is the owner's. A double
            # without the probe counts as shared (fail closed).
            probe = getattr(self._orch, "on_shared_session", None)
            return True if not callable(probe) else bool(probe())

        # K1 — the model may write one script that orchestrates many tool calls. Off
        # unless `llm.execute_code` is on, and registered last on purpose: the tool
        # offers a script exactly the tools registered above, minus itself, narrowed by
        # this same profile. It is composed with the two resolvers rather than reading
        # them itself so the authority it binds (K0) comes from the host, never from an
        # argument.
        from .code_tools import register_code_tools
        from .code_env import CodeEnvRegistry

        code_environment = CodeEnvRegistry()

        def _redact_code_project(text):
            # Secret sources may be initialized lazily after tool composition.
            redact = getattr(getattr(self._orch, "secret_broker", None), "redact", None)
            if not callable(redact):
                from .code_context import ProjectSnapshotError
                raise ProjectSnapshotError("redactor_unavailable")
            return redact(text)

        kernels = self._session_kernels(_get_setting)
        register_code_tools(
            server,
            sandbox=lambda: getattr(self._orch, "sandbox", None),
            settings=_get_setting,
            agent_patterns=_agent_tool_patterns,
            principal=_turn_principal,
            session_id=lambda: str(getattr(self._orch, "session_id", "") or ""),
            # A script's reach is narrowed as the turn's offer is, the shared session included.
            shared_session=_on_shared_session,
            # K2 — a resident interpreter per authorized session, behind its own
            # switch. Docker only and pinned by digest: a kernel that survives an
            # hour deserves the pin the acquisition profile already demands, and a
            # moving tag is a different program tomorrow.
            kernels=kernels,
            authorizer=action_kernel,
            environment_registry=code_environment,
            project_redactor=_redact_code_project,
            # H305/H595 — a run's stdout over the ceiling is spooled to disk as it
            # arrives and the result names the file, instead of the bytes being
            # dropped. Same store and same retention as a spilled tool result.
            result_store=ToolResultStore(
                retention_seconds=float(
                    _get_setting("llm.tool_result_retention_seconds", 86400) or 86400),
                max_files=int(_get_setting("llm.tool_result_max_files", 512) or 512),
                # H661 — the notice names `file_read` only when it can page this file
                # from this turn; a call that would be refused is no recipe.
                read_back=_spill_readable,
            ),
        )
        # K3 — the operator surface reads and resets what K2 owns, so the manager has
        # to be reachable from a route. Bound even when it is None: "sessions are off"
        # is a state the status route has to be able to report honestly.
        bind_external_orchestrator_attribute(self._orch, "session_kernels", kernels)

        tool_profile = ToolProfileResolver(
            settings=_get_setting,
            agent_patterns=_agent_tool_patterns,
            principal=_turn_principal,
            shared_session=_on_shared_session,
        )
        # H315 — the model keeps a checklist of the turn's work and re-reads it on every
        # call. Ungated: it writes the session's own list, which the owner reads next to
        # the approval queue with each item's posture and taint. On the shared session
        # only an owner's turn keeps one.
        from .todo_tool import register_todo_tool

        register_todo_tool(
            server,
            session_id=lambda: str(getattr(self._orch, "session_id", "") or ""),
            posture=lambda: tool_profile.posture().key,
            shared_session=_on_shared_session,
        )
        # H314 — the model writes its long-term memory (the LivingMemory core and user
        # rings): owner-operator turns only, audited in the intent log, undoable.
        from .memory_tool import register_memory_tool

        def _living_memory():
            cog = getattr(self._orch, "cognition", None)
            if cog is None or not cog.sub_enabled("memory_enabled"):
                return None
            return cog.module("memory")

        register_memory_tool(
            server,
            living=_living_memory,
            audit=lambda: getattr(self._orch, "intent_log", None),
            posture=lambda: tool_profile.posture().key,
        )
        # H318 + H340 — the model lists and reads its skills under the catalog's trust
        # gates (the body rendered with its template variables) and proposes changes into
        # the governed pipeline; nothing here writes a live SKILL.md.
        from .skills.tools import register_skill_tools

        register_skill_tools(
            server,
            loader=lambda: getattr(self._orch, "skills", None),
            proposals=lambda: getattr(self._orch, "skill_proposals", None),
            approvals=lambda: getattr(self._orch, "action_approvals", None),
            session_id=lambda: str(getattr(self._orch, "session_id", "") or ""),
            posture=lambda: tool_profile.posture().key,
            settings=_get_setting,
            environment_registry=code_environment,
            principal=_turn_principal,
        )
        # H309 — the model points at the owner's HUD (a tip, or a short tour) through
        # the canvas; ungated, named anchors only, marked when an untrusted turn wrote it.
        from .pointer_tool import register_pointer_tool

        register_pointer_tool(server, canvas=lambda: getattr(self._orch, "canvas", None),
                              posture=lambda: tool_profile.posture().key)

        def _profile_and_note_offer(agent_id, tools):
            # H661 — the same decision, unchanged, plus a note of what it offered in the
            # turn's context, so a spilled result further down this turn names
            # `file_read` only if the turn can call it (see _TURN_TOOL_OFFER). Noted
            # only from inside a task — the loop always runs in one, in its own copied
            # context — so a synchronous caller cannot leave an offer behind in a
            # context that outlives it.
            offered, decision = tool_profile(agent_id, tools)
            try:
                in_task = asyncio.current_task() is not None
            except RuntimeError:
                in_task = False
            if in_task:
                _TURN_TOOL_OFFER.set(
                    frozenset(str(tool.get("name") or "") for tool in offered))
            return offered, decision

        def _guidance_context(agent_id):
            # Presentation follows the authenticated turn, never the prompt text.
            # Missing/unreadable advice does not change the profiled tool offer.
            config = _get_setting("llm.operating_guidance", None)
            if not isinstance(config, dict) or config.get("enabled") is not True:
                return None
            agents = config.get("agents", {})
            if not isinstance(agents, dict) or len(agents) > 256:
                return None
            specific = agents.get(agent_id, {})
            if not isinstance(specific, dict) or specific.get("enabled", True) is not True:
                return None
            flags, overrides = config.get("flags", {}), specific.get("flags", {})
            if not isinstance(flags, dict) or not isinstance(overrides, dict):
                return None
            from .execution_guidance_context import execution_guidance_context

            return {
                "surface": _turn_principal().channel,
                "enabled": {**flags, **overrides},
                "platform_overrides": config.get("platform_overrides"),
                "profile": agent_id,
                "execution_context": lambda: execution_guidance_context(self, agent_id),
            }

        runtime = AgentToolRuntime(
            server,
            enabled=lambda: _get_setting("llm.tool_loop_enabled", False) is True,
            registry_enabled=lambda: _get_setting("llm.registry_planning_enabled", False) is True,
            capability_snapshot=lambda: capability_registry.snapshot(self._orch),
            max_iterations=lambda: _get_setting("llm.tool_loop_max_iterations", 8),
            gap_callback=acquisition.capture_gap,
            context_budget_tokens=lambda: _get_setting("llm.tool_loop_context_tokens", 0),
            per_tool_limit=lambda: _get_setting("llm.tool_loop_per_tool_cap", 0),
            # H298 — an oversized tool result is spilled to disk instead of being
            # thrown away, and the caps scale to the model's real context window.
            # The store writes under the file tools' default root, so the path in a
            # preview footer is one `file_read` can actually open.
            result_store=ToolResultStore(
                retention_seconds=float(
                    _get_setting("llm.tool_result_retention_seconds", 86400) or 86400),
                max_files=int(_get_setting("llm.tool_result_max_files", 512) or 512),
                read_back=_spill_readable,
            ),
            result_thresholds=lambda: _get_setting("llm.tool_result_thresholds", {}) or {},
            # Left at 0 the window comes from the model the turn is running on.
            # `llm.tool_loop_context_tokens` is deliberately NOT reused here: that
            # setting is the transcript budget compaction folds against, not the
            # size of the window, and borrowing it made the scaling read a number
            # that means something else — and stay inert whenever it was unset.
            context_window_tokens=lambda: int(
                _get_setting("llm.tool_result_context_window", 0) or 0),
            tool_profile=_profile_and_note_offer,
            guidance_context=_guidance_context,
        )
        bind_external_orchestrator_attribute(self._orch, "tool_rpc", server)
        bind_external_orchestrator_attribute(self._orch, "agent_tool_runtime", runtime)
        jobs = getattr(self._orch, 'jobs', None)
        queue = getattr(self._orch, 'autonomy_queue', None)
        if callable(getattr(jobs, 'bind_scripts', None)) and queue is not None:
            jobs.bind_scripts(submit=self._submit_job_script, get=queue.get,
                              find=lambda origin: queue.list(origin=origin, limit=2))

        async def _approved_desktop_tool_rpc_execute(task):
            # Publish the durable row for the length of this turn so a gated tool can
            # prove a human accepted *this* task without the id passing through the
            # model-facing schema. Reset in `finally` so nothing leaks to the next turn.
            token = _APPROVED_TASK.set(task)
            try:
                if isinstance(task.payload, dict) and 'kanban_child' in task.payload:
                    from .kanban.child_tools import ChildToolAdapter

                    async def invoke(child):
                        return await server.execute(child, execution_context=execution_token)

                    return await ChildToolAdapter(self.kanban_dispatcher()).execute(task, invoke)
                return await server.execute(task, execution_context=execution_token)
            finally:
                _APPROVED_TASK.reset(token)

        self._approved_desktop_tool_rpc_execute = _approved_desktop_tool_rpc_execute

        async def _approved_image_tool_rpc_execute(task):
            # Canonical tool.rpc admits only these server-owned media tuples.
            if not (is_image_task(task) or is_video_task(task)):
                return {"status": "failed", "reason": "image_task_required"}
            return await _approved_desktop_tool_rpc_execute(task)

        self._approved_image_tool_rpc_execute = _approved_image_tool_rpc_execute
        self._targets = None
        for agent in getattr(self._orch, "agents", {}).values():
            agent.tool_runtime = runtime
        return runtime

    def _session_kernels(self, get_setting):
        """Compose the K2 kernel manager, or None when it cannot be real.

        None is the honest answer whenever code execution is off, the owner opts
        out or the pinned image is missing: `code_tools` stays on K1 and says so,
        than advertising persistence it cannot keep.
        """
        from .code_tools import SETTING

        if (get_setting(SETTING, False) is not True
                or get_setting(CODE_SESSIONS_SETTING, True) is not True):
            return None
        image = str(get_setting("llm.execute_code_image", "") or "").strip()
        if "@sha256:" not in image:
            logger.warning(
                "session kernels need llm.execute_code_image pinned by digest; staying off")
            return None
        from .estop import is_engaged
        from .paths import data_path
        from .session_kernels import SessionKernelManager
        from .detached_kernel import DetachedDockerBackend

        sandbox = getattr(self._orch, "sandbox", None)
        backend = DetachedDockerBackend(
            image,
            available=lambda: getattr(sandbox, "active_backend", lambda: "")() == "docker",
        )
        return SessionKernelManager(
            backend,
            max_kernels=int(get_setting("llm.execute_code_max_kernels", 4) or 4),
            idle_ttl_seconds=float(get_setting("llm.execute_code_idle_ttl", 900) or 900),
            cell_timeout_seconds=float(getattr(sandbox, "timeout", 30) or 30),
            estop=is_engaged,
            rpc_root=str(data_path("code_sessions")),
            max_tool_calls=int(get_setting("security.sandbox_max_tool_calls", 50) or 50),
        )

    def _terminal_run_overrides(self) -> dict:
        """H296 — terminal_run names the targets its runner would run on (enabled, open to
        this agent, granting terminal.exec — the handler's own agent and capability), or
        says it is off."""
        from .env_config import env_flag

        if not env_flag("JARVIS_TERMINAL_TARGETS"):
            return {"description": "Run one bounded shell command on a named governed target. "
                                   "Terminal targets are switched off on this hub "
                                   "(JARVIS_TERMINAL_TARGETS), so every call is refused."}
        names = self._target_registry().usable_names("jarvis", "terminal.exec")
        if not names:
            return {"description": "Run one bounded shell command on a named governed target. "
                                   "No target it can run on is enabled, so every call is refused."}
        return {"properties": {"target": {"enum": names[:64]}}}

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

    def _wire_url_monitor(self, executor):
        """An exact approved URL hop, never the generic plugin/LLM fallback."""
        from .autonomy.jobs_url import URLMonitorExecutor, url_payload_current
        worker = getattr(self._orch, 'autonomy', None)
        jobs = getattr(self._orch, 'jobs', None)
        redact = getattr(getattr(self._orch, 'secret_broker', None), 'redact', None)
        async def unavailable(task):
            return {'status': 'refused', 'reason': 'URL monitor unavailable'}
        executor.register('plugin.egress', unavailable)
        if (worker is None or not callable(getattr(jobs, 'bind_url_monitor', None))
                or not callable(redact)):
            return
        adapter = URLMonitorExecutor(worker, kernel=getattr(worker, 'kernel_gate', None),
            redact=redact, current=lambda payload: url_payload_current(jobs.store, payload))
        executor.execution_guard = adapter.guard
        executor.register('plugin.egress', adapter.execute)
        jobs.bind_url_monitor(adapter)

    def _wire_cloud_image(self, executor):
        """Compose exact egress domains before consuming one worker permit."""
        from .cloud_image_runtime import CloudImageRuntime, matches
        worker = getattr(self._orch, 'autonomy', None)
        redact = getattr(getattr(self._orch, 'secret_broker', None), 'redact', None)
        if worker is None or not callable(redact):
            return
        runtime = CloudImageRuntime(worker, kernel=getattr(worker, 'kernel_gate', None), redact=redact,
                                    gate=getattr(self._orch, 'permission_gate', None))
        previous_guard, previous_execute = executor.execution_guard, executor.resolve('plugin.egress')

        def guard(task):
            if matches(task):
                return runtime.guard(task)
            if task.kind == 'plugin.egress' and (not isinstance(task.payload, dict)
                    or task.payload.get('plugin') != 'job-url-monitor'):
                return False
            return callable(previous_guard) and previous_guard(task)

        async def execute(task):
            if matches(task):
                return await runtime.execute(task)
            if (isinstance(task.payload, dict) and task.payload.get('plugin') == 'job-url-monitor'
                    and callable(previous_execute)):
                return await previous_execute(task)
            return {'status': 'refused', 'reason': 'unsupported egress operation'}

        executor.execution_guard = guard
        executor.register('plugin.egress', execute)
        bind_external_orchestrator_attribute(self._orch, "cloud_images", runtime)

    def _wire_kanban_network(self, executor):
        """Compose the attachment domain without bypassing other egress guards."""
        redact = getattr(getattr(self._orch, "secret_broker", None), "redact", None)
        if getattr(self._orch, "autonomy", None) is None or not callable(redact):
            return
        adapter = self.kanban_network()
        previous_guard = executor.execution_guard
        previous_execute = executor.resolve("plugin.egress")

        def guard(task):
            if adapter.matches(task):
                return adapter.guard(task)
            return callable(previous_guard) and previous_guard(task)

        async def execute(task):
            if adapter.matches(task):
                return await adapter.execute(task)
            if callable(previous_execute):
                return await previous_execute(task)
            return {"status": "refused", "reason": "unsupported egress operation"}

        executor.execution_guard = guard
        executor.register("plugin.egress", execute)

    def build_executor(self) -> TaskExecutor:
        """Wire task kinds to real capabilities, degrading gracefully."""

        async def _research(task):
            # Hermes absorption 5a — the branch used to test for a ``handle`` attribute the
            # plugin never had, so every research/search/monitor/scan/lookup/check task was
            # a permanent noop. The plugin's ``search`` is the real surface; its rows keep
            # the plugin's taint marks so a consumer still treats them as data. The log
            # carries the exception type only, never the query or a result.
            query = (task.payload or {}).get("query") or task.title
            ws = (getattr(self._orch, "plugins", None) or {}).get("websearch")
            if ws is None or not callable(getattr(ws, "search", None)):
                return {"status": "noop", "note": "websearch unavailable"}
            # A research task auto-runs under policy (read-only tier) with nobody in the
            # turn, so its egress must be one the owner set up: a configured backend
            # (TAVILY_API_KEY / SEARXNG_URL). The keyless fallback stays with the
            # interactive tool, where the owner asked and the tool loop is opt-in.
            available = getattr(ws, "available", None)
            if callable(available) and not available():
                return {"status": "noop", "note": "websearch backend not configured"}
            try:
                results = await ws.search(query, max_results=_RESEARCH_MAX_RESULTS)
            except Exception as exc:
                logger.warning("research task search failed (type=%s)", type(exc).__name__)
                return {"status": "failed", "note": "websearch error"}
            rows = list(results or [])[:_RESEARCH_MAX_RESULTS]
            return {
                "status": "ok",
                "kind": "research",
                "output": {"query": query, "results": rows, "count": len(rows)},
            }

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
        from .kanban.dispatcher import KanbanDispatcher

        async def _kanban_worker(task):
            return await self.kanban_dispatcher().execute(task)

        executor.register(KanbanDispatcher.KIND, _kanban_worker)
        self._wire_url_monitor(executor)
        self._wire_cloud_image(executor)
        self._wire_kanban_network(executor)
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
                task_reader=getattr(getattr(self._orch, "autonomy_queue", None), "get", None),
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
        # H313 — an approved `speak` row takes the same trusted execution path.
        executor.register(
            "toolrpc.speak",
            self._approved_desktop_tool_rpc_execute,
        )
        executor.register(
            "tool.rpc",
            self._approved_image_tool_rpc_execute,
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
                # The ledger is bound above whatever the flag says, so its absence
                # means it failed to construct: machinery, a failure — never a
                # ``refused`` that ran nothing (review round 4, item 5).
                return {"status": "failed", "reason": "work_run_ledger_unavailable"}
            try:
                run = await asyncio.to_thread(
                    runs.open_run, goal, budget=goal.budget, deadline_at=goal.deadline_at
                )
            except WorkRunError as exc:
                return {"status": "refused", "reason": exc.reason}
            # H464c: one approval opens one run, so a retry gets the run the first
            # attempt opened — reported with that run's goal id, not the retry's.
            return {"status": "ok", "kind": "goal.approve", "run_id": run.id,
                    "goal_id": run.goal_id}

        executor.register("goal.approve", _open_approved_goal)

        # H262 — the irreversible tier (settings.retention, …): applied only out of a
        # human's accept on the task itself. Registered here because an unhandled kind
        # would fall to the LLM fallback and run its title as a prompt.
        from .autonomy import irreversible

        async def _apply_irreversible(task):
            return await irreversible.execute(task, orch=self._orch)

        for kind in irreversible.kinds():
            executor.register(kind, _apply_irreversible)

        from .checkpoint_controller import CHECKPOINT_KINDS, CheckpointController

        checkpoints = CheckpointController(self._orch)
        for kind in CHECKPOINT_KINDS:
            executor.register(kind, checkpoints.execute)

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

        bind_external_orchestrator_attribute(
            self._orch,
            "subagents",
            SubAgentManager(
                runner=make_subagent_runner(self._orch),
                # H681: a child names no model → autonomy.subagent_model / _provider.
                selection_defaults=self._subagent_selection_defaults,
                fallback_probe=self._subagent_fallback_model,
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

    def _subagent_selection_defaults(self) -> dict:
        """``autonomy.subagent_model`` / ``autonomy.subagent_provider``, read at each
        spawn (empty = the child runs on its agent's own route)."""
        def read(key):
            value = self._orch.get_setting(key, "")
            return value.strip() if isinstance(value, str) else ""

        return {"model": read("autonomy.subagent_model"), "provider": read("autonomy.subagent_provider")}

    def _subagent_fallback_model(self, rejected: str):
        """The model children would run on with the setting cleared: what the governed
        router picks for the default agent, asked outside any pin. None when it cannot
        say, or picks the rejected model."""
        router = getattr(self._orch, "llm_router", None)
        select = getattr(router, "select_backend", None)
        if not callable(select):
            return None
        try:
            _backend, model, _route = select("jarvis", "")
        except Exception:
            logger.debug("no fallback model for the sub-agent notice", exc_info=True)
            return None
        return model if isinstance(model, str) and model and model != rejected else None

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


def make_subagent_runner(orch):
    """The production sub-agent runner (H681): one turn through the orchestrator, with
    the child's pin checked against the governed router before it runs, and a failed
    turn raised as :class:`SubAgentProviderError` (with what the backends noted), never
    answered as an empty success. The manager has already opened the child's selection
    and override scopes around this call."""
    from .llm.job_selection import current_selection
    from .llm.provider_errors import provider_failure_scope
    from .subagents import SubAgentProviderError

    async def _subagent_runner(task, session_id, agent, *, steer=None):
        picked = agent if agent in orch.agents else "jarvis"
        from .steering import steering_scope
        from .kanban.runtime import delegate_scope

        with provider_failure_scope() as failures, steering_scope(steer, agent_id=picked), delegate_scope():
            if current_selection() is not None:
                router = getattr(orch, "llm_router", None)
                if not callable(getattr(router, "select_backend", None)):
                    raise SubAgentProviderError(
                        "selection refused: a model or provider pin requires the governed model router")
                try:
                    router.select_backend(picked, task)
                except Exception as exc:
                    raise SubAgentProviderError(f"selection refused: {exc}") from exc
            detailed = getattr(orch, "process_detailed", None)
            if callable(detailed):
                text, error = await detailed(task, agent=picked, channel="subagent")
            else:
                text = await orch.process(task, agent=picked, channel="subagent")
                error = None if (text or "").strip() else "empty reply"
        if error is not None:
            raise SubAgentProviderError(error, failures=list(failures))
        return {"output": text, "session_id": session_id}

    return _subagent_runner
