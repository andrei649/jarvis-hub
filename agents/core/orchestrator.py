"""
orchestrator.py — Main orchestration loop for Jarvis Beta.
Integrates: intent routing, LLM backend, memory, live plugins, streaming, voice, channels,
skills system, checkpointing, agent handoff, promotion/demotion.
"""

import asyncio
import contextvars
import hashlib
import inspect
import logging
import importlib
import os
import re
import time
import uuid
from contextlib import nullcontext
from pathlib import Path
from typing import Callable, Optional

from .agent import Agent
from .router import IntentRouter
from .config import JarvisConfig
from .llm.base import LOCAL_SELECTION_UNAVAILABLE_REPLY, is_degraded_reply
from .llm.auth_rotation import AuthLease
from .llm.gemini import GeminiBackend
from .llm.hybrid_router import HybridRouter, LocalBackendUnavailableError
from .llm.gemini_cache import ContextCache
from .llm.gemini_context import GeminiRequestBinding
from .llm.tokenizer import estimate_tokens
from .memory.manager import MemoryManager
from .checkpoint import CheckpointManager
from .heartbeat import HeartbeatScheduler
from .scheduler_service import SchedulerService
from .autonomy_coordinator import AutonomyCoordinator
from .action_origin import (
    bind_action_origin,
    bind_turn_action_origin,
    origin_for_channel,
    reset_action_origin,
)
from . import llm_control  # CLN-2: NL LLM-control detection + execution
from .llm_control import detect_llm_control  # re-exported: NL LLM-control detection (CLN-2)
from . import cognition_trace  # CLN-2: builds + persists the per-turn cognition trace
from . import plugin_gatherer  # live-plugin data gathering (CLN-2)
from .plugin_manager import PluginManager  # CLN-2: owns the live-plugin registry + I/O
from .learning.loop import LearningLoop
from .skills.loader import SkillLoader
from .skills.importer import SkillImporter
from .skills.marketplace import SkillMarketplace
from .skills.skill_history import SkillHistory
from .mcp.client import MCPManager
from .autonomy import AutonomyWorker, TaskQueue, AutonomyPolicy, PreferenceStore, InterruptBudget, MissionStore
from .autonomy import ProactiveObserver, default_probes
from .autonomy.audit_sink import ActionAuditSink
from .autonomy.reflection import DailyReflector, ReflectionRunStore
from .autonomy.log_scanner import LogBugScanner
from .autonomy.tech_scout import TechScout, TechScoutStore, DEFAULT_QUERIES as _TECH_SCOUT_DEFAULT_QUERIES
from .workflows import WorkflowEngine, WorkflowRegistry
from .sandbox import Sandbox
from .bench import LatencyBenchmark
from .plugin_gate import PermissionGate
from .security import GuardrailsEngine, bind_guardrails
from .security.audit import AuditLogger
from .security.types import RedactionMode, SecurityEvent, SecurityEventType
from .env_config import env_flag, truthy
from .log import log_error
from .errors import (
    E_LLM_BACKEND_MISSING, E_LLM_TIMEOUT,
    E_INTERNAL_UNEXPECTED,
)
from .channels.base import ChannelAdapter
from .channels.manager import ChannelManager
from .settings_db import get_all as _get_settings
# Live-plugin classes + oauth helpers moved with the registry to PluginManager (CLN-2).

logger = logging.getLogger("jarvis.orchestrator")


def _is_failed_agent_reply(agent_id: str | None, response: object) -> bool:
    """Classify stable degraded replies and exact per-agent failure markers."""

    return is_degraded_reply(response) or bool(
        agent_id
        and re.match(
            rf"^\[{re.escape(agent_id)} (error|timeout)\b",
            str(response),
        )
    )


def _log_task_result(task: "asyncio.Task") -> None:
    """B6: done-callback so a fire-and-forget task's exception isn't swallowed."""
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    if exc is not None:
        logger.error("background task %r failed: %s",
                     task.get_name(), exc, exc_info=exc)


HANDOFF_PREFIX = "[handoff:"
SKILL_PREFIX = "[learn:"


def _as_bool(value, default: bool = True) -> bool:
    """Coerce a runtime-settings value (bool / int / "true" / "off" / ...) to bool.

    Settings-plane semantics (unchanged in O26-P2.1): empty string → False,
    an unrecognized word → True — a stored setting is an explicit opt-in,
    unlike an env flag where junk falls back to the default."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip()
    return bool(text) and truthy(text, default=True)


def skill_history_enabled() -> bool:
    """Opt-in version-history ledger flag using the shared env convention."""
    return env_flag("JARVIS_SKILL_HISTORY")






# BUG-5: per-request session isolation.
#
# Orchestrator is a process-wide singleton (web.py builds one `orch`), so a
# single shared `self.session_id` mutated mid-method let two concurrent turns
# (two tabs, or web+telegram) interleave across `await` points and land a reply
# in the WRONG conversation. We make the active session an async-context-local
# value: `handle_input`/`handle_input_stream` resolve the session once at the
# top and set this ContextVar, so every downstream read (memory, recall,
# checkpoint, tracer — including those dispatched via `asyncio.to_thread`, which
# copies the current context) sees that request's own session and never another
# request's. The sentinel distinguishes "no active request context" (boot,
# checkpoint restore, autonomy, status reads) so `self.session_id` falls back to
# the shared instance default in those paths, preserving prior behavior.
_SESSION_UNSET = object()
_active_session: contextvars.ContextVar = contextvars.ContextVar(
    "jarvis_active_session", default=_SESSION_UNSET
)


class Orchestrator:
    def __init__(self, config: JarvisConfig):
        self.config = config
        self.agents: dict[str, Agent] = {}
        self.router = IntentRouter(config)
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
        self.llm_router = HybridRouter(gemini_api_key=gemini_key, anthropic_api_key=anthropic_key)
        # The auth-profile pool does not exist until HybridRouter.detect().  In
        # particular, GEMINI_API_KEYS-only deployments have no single boot key.
        self.context_cache: ContextCache | None = None
        self._cache_tasks: set[asyncio.Task] = set()
        self.memory = MemoryManager()

        # ── optional components via the registry (A2: tames the god-object) ──
        from .component_registry import ComponentRegistry
        self.components = ComponentRegistry(self, logger)
        reg = self.components

        # K3: one process-wide loop circuit breaker (OWASP unbounded-consumption guard).
        # Set eagerly (trivial in-memory) so it's present before autonomy wiring; bound
        # ONLY into the broker-mediated kernel (the agent action path) — never routes/egress.
        from .kernel.budget import LoopDetector
        from .kernel.binding import make_budget_ledger
        self.loop_detector = LoopDetector()
        self.budget_ledger = make_budget_ledger()

        def _capabilities():
            m = importlib.import_module(".security.capability", "agents.core")
            return m.CapabilityBroker(), m.KillSwitch()

        def _audit_anchor():
            m = importlib.import_module(".security.anchor", "agents.core")
            return m.IntentLog(), m.TransparencyAnchor()

        def _secret_broker():
            from .security.secret_broker import SecretBroker
            try:
                from .secrets import SecretStore
                return SecretBroker(SecretStore())
            except Exception:
                return SecretBroker()   # in-memory fallback

        reg.add("entities", ".memory.entity", "EntityStore", label="entity memory")           # H8.1b
        reg.add("bitemporal", ".memory.bitemporal", "BiTemporalKG", label="bi-temporal KG")    # H14.1
        reg.register_group(("capabilities", "kill_switch"), _capabilities, "capability/kill-switch")  # H17.3
        reg.register_group(("intent_log", "transparency"), _audit_anchor, "audit anchor")      # H17.4
        reg.add("arena", ".arena", "Arena", label="model arena")                               # H10.19
        reg.add("quality", ".observability.quality", "QualityMonitor", label="quality monitor")  # H10.23
        reg.add("widgets", ".widget", "WidgetStore", label="chat widget")                      # H10.1
        reg.add("consolidation", ".memory.consolidation", "ConsolidationEngine", label="consolidation")  # H14.3
        reg.add("rooms", ".rooms", "RoomStore", label="chat rooms")                            # H10.20
        reg.add("sender_pairing", ".channels.pairing", "SenderPairing",
                path="memory_logs/sender_pairing.json", label="sender pairing")                 # H12.19
        reg.add("canvas", ".canvas", "CanvasStore",
                path="memory_logs/canvas.json", label="agent canvas")                           # H12.18
        reg.add("action_approvals", ".autonomy.action_approvals", "ActionApprovalQueue",
                path="memory_logs/action_approvals.json", label="action approvals")            # H10.18
        reg.add("notes", ".notes", "NotesStore", label="conversation notes")                   # H10.21
        reg.add("review_queue", ".observability.review_queue", "ReviewQueue", label="review queue")  # H10.25
        reg.register("secret_broker", _secret_broker, "secret broker")                         # H15.4
        reg.add("decay", ".memory.decay", "DecayMemory", label="decay forgetting")             # H14.4
        reg.register("kg_updater", lambda: importlib.import_module(  # H12.6
            ".memory.incremental", "agents.core").IncrementalKGUpdater(
            getattr(self.memory, "graph", None), bitemporal=self.bitemporal),
            "incremental KG")
        reg.add("run_history", ".run_history", "RunHistory", label="run history")              # H10.17
        reg.add("soul_versions", ".soul_versioning", "SoulVersionStore", label="prompt VC")    # H10.22
        reg.add("e2e_sync", ".e2e_sync", "E2ESync", label="E2E device sync")                   # H12.13
        reg.add("satellite_hub", ".satellite_hub", "SatelliteHub", label="satellite hub")      # H12.8
        reg.add("cognition", ".cognition", "CognitionFacade",
                get_setting=self.get_setting, label="cognition (H21)")                          # H21.0
        if getattr(self, "cognition", None) is not None:                                         # H21.1
            from .cognition.honesty import HonestyModule
            self.cognition.register_module("honesty", HonestyModule())
            from .cognition.persona import PersonaModule                                          # H21.2
            self.cognition.register_module("persona", PersonaModule())
            from .cognition.memory import LivingMemory                                            # H21.3
            from .paths import data_path
            self.cognition.register_module(
                "memory",
                LivingMemory(
                    core_path=data_path("cognition", "core_memory.json"),
                    tiers_path=data_path("cognition", "living_tiers.json"),
                    user_path=data_path("cognition", "user_core.json"),
                ),
            )
            from .cognition.learning import LearningModule                                        # H21.4
            self.cognition.register_module("learning", LearningModule())
            from .cognition.ensemble import EnsembleModule                                        # H21.5
            self.cognition.register_module("ensemble", EnsembleModule())
        # ── end optional components ──
        self.plugin_manager = PluginManager()  # CLN-2: owns the live-plugin registry + I/O
        self.skills = SkillLoader()
        self.skill_importer = SkillImporter()
        # 0.58 (opt-in): attach a version-history ledger so publish/install/uninstall
        # are recorded (enables rollback_target + the read surface). Default-off via
        # JARVIS_SKILL_HISTORY → history=None → marketplace behaviour byte-identical.
        self.marketplace = SkillMarketplace(
            history=SkillHistory() if skill_history_enabled() else None)
        self.mcp = MCPManager()
        self.channel_manager = ChannelManager()  # CLN-2: owns the channel registry + I/O
        self.checkpoints = CheckpointManager()
        self.learning = LearningLoop()
        rules = config.get_promotion_rules() if hasattr(config, "get_promotion_rules") else None
        if rules:
            self.learning.set_promotion_rules(rules)
        self.bench = LatencyBenchmark()
        from .settings_db import get_value as _gv
        # /admin → security.sandbox_timeout / sandbox_memory. allow_subprocess stays
        # OFF (HF-6): the host-exec fallback is never enabled by these knobs.
        self.sandbox = Sandbox(
            timeout=int(_gv("security", "sandbox_timeout", 30)),
            max_memory_mb=int(_gv("security", "sandbox_memory", 256)),
        )
        self.heartbeat_scheduler = HeartbeatScheduler(agents_dir=str(Path(__file__).resolve().parent.parent.parent / "agents"))
        self._scheduler = SchedulerService(self)  # CLN-2: owns the cron/interval job wiring
        self._autonomy = AutonomyCoordinator(self)  # CLN-2: owns autonomy wiring + worker loop
        self.security: Optional[GuardrailsEngine] = None
        self.permission_gate = PermissionGate()
        self.audit = AuditLogger()
        # B3: route the strict-egress downgrade (escape hatch) through a durable audit
        # record so it's no longer a silent log line. No-op in strict mode (the default).
        from . import http_client as _http_client

        def _egress_downgrade_audit(plugin: str, violation: str) -> None:
            self.audit.log(SecurityEvent(
                event_type=SecurityEventType.EGRESS_DOWNGRADE,
                timestamp=time.time(),
                content_preview=f"{plugin}: {violation}"[:200],
                action_taken="allowed (JARVIS_STRICT_EGRESS=0)",
            ))

        _http_client.set_egress_audit_sink(_egress_downgrade_audit)
        # ORIZONT-24 K1 wave-2: route policy-passing plugin egress through the Action
        # Kernel (default-off behind JARVIS_ACTION_KERNEL). The kernel is rebuilt lazily
        # per call so it reads live state (kill-switch engaged → egress denied). Decoupled:
        # http_client never imports the kernel; we hand it a plain callable hook.
        from .kernel.binding import make_action_kernel, make_egress_kernel_hook
        _http_client.set_egress_kernel_hook(
            make_egress_kernel_hook(lambda: make_action_kernel(self)))
        # LM Studio lifecycle control (start server / load / unload). Shares the
        # live router so a model change refreshes routing + reported state.
        from .llm.lmstudio_control import LMStudioController
        # enabled is re-synced from live settings in load_runtime_settings(); the
        # env var is the boot-time default and a hard kill-switch (see docs).
        self.lmstudio = LMStudioController(
            router=self.llm_router,
            enabled=env_flag("JARVIS_LMSTUDIO_CONTROL", True),
        )
        # H22.5 — attach the LRU residency manager, backed by the LM Studio
        # controller above. Default-off via JARVIS_MODEL_MANAGER (GPU-unvalidated):
        # when off, the router's ensure_resident hook is a no-op and behavior is
        # exactly today's. Best-effort, never raises into routing.
        try:
            from .llm.model_manager import ModelManager, LMStudioControllerAdapter
            self.llm_router.attach_model_manager(
                ModelManager(LMStudioControllerAdapter(self.lmstudio))
            )
        except Exception:
            logger.warning("model_manager attach failed — residency tracking off", exc_info=True)
        # Backing store for the shared/default session (see `session_id` property
        # below). Per-request turns override this via the `_active_session`
        # ContextVar; this default serves boot, checkpoint restore, autonomy and
        # status reads that run outside a chat request's async context.
        self._session_id_default: Optional[str] = None
        self.on_token: Optional[Callable] = None
        self._runtime_settings: dict = {}
        self._channel_sessions: dict[str, str] = {}
        self._last_channel: str = "unknown"
        self._settings_watcher_task: Optional[asyncio.Task] = None
        # ── Autonomy / Proactive Cortex (H6.1–H6.6) ──
        self.autonomy_queue = TaskQueue()
        self.autonomy_prefs = PreferenceStore()
        # Mission Workspaces (0.32): persistent long-horizon workspaces — goal,
        # plan, budget, pause/resume, on-disk artifacts + an append-only event
        # audit trail. Independent of the task queue (a mission can span many
        # tasks/turns and survive restarts).
        self.missions = MissionStore(ledger=self.budget_ledger)
        # /admin → autonomy.cap_per_action / daily_ceiling / interrupt_budget.
        # These were dataclass defaults (50/200/4); live-resynced each tick by the
        # autonomy coordinator (like autonomy.mode).
        from .settings_db import get_value as _gv
        from .ambient.policy import AttentionLedger, bounded_attention_allowance
        from .paths import data_path as _attention_path

        interrupt_limit = bounded_attention_allowance(
            _gv("autonomy", "interrupt_budget", 4)
        )
        self.attention_ledger = AttentionLedger(
            _attention_path("ambient", "attention.db"),
            timezone_name=str(_gv("general", "timezone", "Europe/Bucharest")),
            per_day=interrupt_limit,
            k3=self.budget_ledger,
        )
        # Action-level audit sink, shared by every governed-action recorder (the
        # autonomy worker below, the remediation runner in autonomy_coordinator).
        self.action_audit = ActionAuditSink(getattr(self, "intent_log", None))
        self.autonomy = AutonomyWorker(
            self.autonomy_queue,
            policy=AutonomyPolicy(
                cap_per_action=float(_gv("autonomy", "cap_per_action", 50.0)),
                daily_ceiling=float(_gv("autonomy", "daily_ceiling", 200.0)),
                earned_autonomy_enabled=bool(
                    _gv("autonomy", "earned_autonomy_enabled", False)
                ),
            ),
            prefs=self.autonomy_prefs,
            budget=InterruptBudget(
                per_day=interrupt_limit,
                ledger=self.budget_ledger,
                attention_ledger=self.attention_ledger,
                timezone_name=str(_gv("general", "timezone", "Europe/Bucharest")),
            ),
            # Without this the whole autonomy lifecycle — auto-approve, push,
            # human decision, execute, fail — was recorded nowhere in production:
            # `audit` defaulted to None, so `_audit()` returned immediately. The
            # sink is IntentLog (always HMAC-signed, key held out of the log tree)
            # rather than the guardrails DB, whose rows are plain sha256 unless an
            # optional env key is set.
            audit=self.action_audit,
        )
        # H34.2: owner desk-presence. Default 'unknown' (fail-calm) until a host
        # daemon reports; when 'away', decision cards additionally escalate to the
        # governed channels (autonomy_coordinator.wire → AwayNotifier).
        from .autonomy.presence import OwnerPresence
        self.owner_presence = OwnerPresence(
            ttl_seconds=float(_gv("autonomy", "presence_ttl", 900) or 900),
        )
        # Proactive OS Observer — the trigger layer that feeds the queue.
        self.observer: Optional[ProactiveObserver] = None
        # Proactive Event Watcher — personal event trigger layer.
        self.event_watcher = None
        self._autonomy_task: Optional[asyncio.Task] = None
        self._warmup_task: Optional[asyncio.Task] = None
        self._drive_ai_task: Optional[asyncio.Task] = None
        self.last_cognition = None
        # H20 learning loop: frozen-per-session core-memory prompt block + the
        # last background-review result (surfaced via /api/cognition/learning).
        self._core_block_cache: Optional[tuple] = None
        self.last_learning_review: Optional[dict] = None
        self.reviewer = None            # BackgroundReviewer, built in load_agents
        self.curator = None             # SkillCurator, built in load_agents
        # Daily Reflection & Graph Consolidation (H5.15)
        self.reflector: Optional[DailyReflector] = None
        # Proactive Technology Scout (Self-Improvement) — default-off, read-only.
        self.tech_scout: Optional[TechScout] = None
        # Log-bug-finding scanner (multi-cadence scheduled pipeline)
        self.log_scanner = LogBugScanner()
        # Multi-Agent Workflows (H5.6)
        self.workflow_registry = WorkflowRegistry()
        self.workflow_engine: Optional[WorkflowEngine] = None
        # Continuous Ingestion Watcher (H5.1)
        self.ingestion_watcher = None
        # H7.3: debounce checkpoint — counts turns since last full save
        self._turns_since_checkpoint: int = 0
        # H9.2: trace explorer — in-memory ring buffer.
        # H23.2 (opt-in): when JARVIS_MODEL_INFO is set, attach a model-fingerprint
        # registry as the tracer's resolver so each trace records {id,version,quant,
        # sha256}; unset → registry is None and behavior is byte-identical.
        from .observability.model_info import default_registry_if_enabled
        self.model_info = default_registry_if_enabled()
        try:
            from .observability.tracer import Tracer
            self.tracer = Tracer(maxlen=500, model_info=self.model_info)
        except Exception:
            logger.warning("Tracer initialisation failed — tracing disabled", exc_info=True)
            self.tracer = None

    # ── BUG-5: session_id is async-context-local ────────────────────────────
    #
    # Reads return the per-request session when one is active (set by
    # handle_input/handle_input_stream/channel_handler via the `_active_session`
    # ContextVar), otherwise the shared instance default. Writes that happen
    # *inside* an active request context update only that context (so a turn
    # cannot clobber another concurrent turn's session); writes outside any
    # request context (boot, checkpoint restore, new_session, /reset) update the
    # shared default, preserving the original single-request behavior.
    @property
    def channels(self) -> dict[str, ChannelAdapter]:
        """CLN-2: the channel registry now lives in ChannelManager; this delegating
        property keeps existing `orch.channels[...]` access working unchanged."""
        return self.channel_manager.channels

    @channels.setter
    def channels(self, value: dict) -> None:
        self.channel_manager.channels = value

    @property
    def plugins(self) -> dict:
        """CLN-2: the live-plugin registry now lives in PluginManager; this
        delegating property keeps existing `orch.plugins[...]` / `.get(...)`
        access working unchanged."""
        return self.plugin_manager.plugins

    @plugins.setter
    def plugins(self, value: dict) -> None:
        self.plugin_manager.plugins = value

    @property
    def session_id(self) -> Optional[str]:
        val = _active_session.get()
        if val is _SESSION_UNSET:
            return self._session_id_default
        return val

    @session_id.setter
    def session_id(self, value: Optional[str]) -> None:
        if _active_session.get() is _SESSION_UNSET:
            self._session_id_default = value
        else:
            _active_session.set(value)

    def _ensure_context_cache(self) -> None:
        """Create the cache only from the auth pool produced by detection."""
        gemini_pool = getattr(self.llm_router, "_gemini_pool", None)
        if (
            getattr(self, "context_cache", None) is None
            and gemini_pool is not None
            and getattr(gemini_pool, "size", 0) > 0
        ):
            self.context_cache = ContextCache(
                lambda: self.llm_router._gemini_pool,
            )
            if not hasattr(self, "_cache_tasks"):
                self._cache_tasks = set()

    async def load_agents(self):
        await self.llm_router.detect()
        logger.info(f"LLM backend: {self.llm_router.name}")

        # Context caching shares the router's detected auth pool.  Build it only
        # now (never from the single-key constructor snapshot), so multi-profile
        # GEMINI_API_KEYS configurations work and later requests see pool updates.
        self._ensure_context_cache()

        # Preload the detected local model so the first turn (often a voice
        # command) skips the cold-load cost. Fire-and-forget — the model load
        # can take seconds and must not delay startup. Gate with
        # JARVIS_LLM_WARMUP=0 for environments where preloading is unwanted.
        if env_flag("JARVIS_LLM_WARMUP", True):
            self._warmup_task = asyncio.create_task(self.llm_router.warm_up())
            self._warmup_task.add_done_callback(_log_task_result)

        # Personalization (PRIVATE) — import the owner's Drive "AI" folder via
        # rclone into a gitignored local dir and ingest it into memory. Opt-in
        # (JARVIS_DRIVE_AI_SYNC=1) and fire-and-forget so it never blocks startup.
        if env_flag("JARVIS_DRIVE_AI_SYNC"):
            self._drive_ai_task = asyncio.create_task(self._drive_ai_startup())
            self._drive_ai_task.add_done_callback(_log_task_result)

        # /admin → security.guardrails_mode / scan_input / scan_output. Keep an
        # unbound policy prototype even when no provider is available at boot;
        # each request binds it only after the router selects a backend.
        from .settings_db import get_value as _gv
        from .security import hardened as _hardened
        # CDX-12: the hardened profile tightens the *default* to REDACT; an
        # explicit security.guardrails_mode setting still wins.
        _mode_raw = str(_gv("security", "guardrails_mode",
                            _hardened.guardrails_default())).upper()
        _mode = RedactionMode[_mode_raw] if _mode_raw in RedactionMode.__members__ else RedactionMode.WARN
        self.security = GuardrailsEngine(
            backend=None,
            mode=_mode,
            scan_input=bool(_gv("security", "scan_input", True)),
            scan_output=bool(_gv("security", "scan_output", True)),
        )
        logger.info("Security guardrails enabled (mode=%s, scan_in=%s, scan_out=%s)",
                    _mode.value, self.security._scan_input, self.security._scan_output)

        for agent_id, agent_config in self.config.agents.items():
            if agent_config.status == "active":
                agent_dict = {
                    "name": agent_config.name,
                    "model": agent_config.model,
                    "heartbeat": agent_config.has_heartbeat,
                    "channel": agent_config.channel,
                    "plugins": agent_config.plugins,
                    "tier": agent_config.tier,
                }
                agent = Agent(agent_id, agent_dict, self.llm_router, permission_gate=self.permission_gate)
                agent.guardrails = self.security
                self.agents[agent_id] = agent
                logger.info(f"Loaded: {agent_id}")

        self._configure_cognition_roster()

        # K2: issue a least-privilege capability token per agent, derived from its declared
        # config (plugins/channel/policy). Inert until the per-action enforcement waves
        # check it — populated here so every agent has a scoped capability set (generalizing
        # the seeded broker tokens to the whole fleet). Best-effort: never breaks boot.
        self.agent_capabilities: dict[str, str] = {}
        try:
            if getattr(self, "capabilities", None) is not None:
                from .kernel.capabilities import issue_all
                self.agent_capabilities = issue_all(self.capabilities, self.config.agents)
        except Exception:
            logger.warning("per-agent capability issuance failed", exc_info=True)

        # CLN-2: live-plugin registry build moved to PluginManager (byte-identical
        # construction order + env/settings reads; sets self.oracle_bridge + self.argus).
        self.plugin_manager.build(self)

        # Autonomy queue — durable self-tasking store (H6.1)
        try:
            self.autonomy_queue.initialize()
            self.autonomy_prefs.initialize()
            self.missions.initialize()
            self.autonomy.executor = self._autonomy.build_executor().execute
            self.observer = ProactiveObserver(self.autonomy, probes=default_probes())

            # Setup personal event probes using active plugins (Antigravity watchers)
            from .autonomy.watchers import EventWatcher, EmailProbe, CalendarProbe, FinanceProbe, HealthProbe, WorldViewProbe
            gmail = self.plugins.get("gmail")
            calendar = self.plugins.get("google-calendar")
            balance = self.plugins.get("balance")
            health = self.plugins.get("apple-health")
            worldview = self.plugins.get("worldview")

            event_probes = [
                EmailProbe(gmail_plugin=gmail, priority_senders=self.get_setting("autonomy.priority_senders", ["andrei"]), get_setting=self.get_setting),
                CalendarProbe(calendar_plugin=calendar, lead_time_min=int(self.get_setting("autonomy.calendar_lead_time", 30)), get_setting=self.get_setting),
                FinanceProbe(balance_plugin=balance, min_ron=float(self.get_setting("autonomy.finance_min_ron", 2000.0)), min_eur=float(self.get_setting("autonomy.finance_min_eur", 400.0)), get_setting=self.get_setting),
                HealthProbe(health_plugin=health, min_sleep_hrs=float(self.get_setting("autonomy.health_min_sleep", 5.0)), min_hrv_ms=float(self.get_setting("autonomy.health_min_hrv", 30.0)), get_setting=self.get_setting),
                # WorldView 4D OSINT: recon passes + dark-vessel alerts → digest (degrades to no-op if WorldView is down).
                WorldViewProbe(worldview_plugin=worldview, lead_min=int(self.get_setting("autonomy.worldview_lead_min", 30)), get_setting=self.get_setting),
            ]
            self.event_watcher = EventWatcher(self.autonomy, event_probes)

            async def _reflect_llm(prompt: str) -> str:
                return await self.process(prompt, agent="jarvis", channel="reflection")

            def _reflection_living_memory():
                cog = getattr(self, "cognition", None)
                if cog is None or not cog.sub_enabled("memory_enabled"):
                    return None
                return cog.module("memory")

            from .paths import data_path
            self.reflector = DailyReflector(
                self.memory,
                _reflect_llm,
                run_store=ReflectionRunStore(data_path("reflection", "daily_reflector.json")),
                living_memory=_reflection_living_memory,
            )

            # Proactive Technology Scout (Self-Improvement) — reuses the same
            # WebSearchPlugin the assistant's own websearch feature calls; None if
            # no search backend is configured (scan() then reports itself unavailable).
            websearch = self.plugins.get("websearch")
            self.tech_scout = TechScout(
                self.autonomy,
                search=(websearch.search if websearch else None),
                store=TechScoutStore(data_path("autonomy", "tech_scout.json")),
                queries=self.get_setting("autonomy.tech_scout_queries", _TECH_SCOUT_DEFAULT_QUERIES),
            )

            # Continuous Ingestion Watcher (H5.1)
            from .ingestion.watcher import IngestionWatcher
            self.ingestion_watcher = IngestionWatcher()

            # Multi-agent workflow engine (H5.6)
            self.workflow_engine = WorkflowEngine(self)

            logger.info("Autonomy queue + executor + observer + event_watcher + reflection + tech_scout + workflows initialized")
        except Exception as e:
            logger.warning(f"Autonomy init failed: {e}")

        self.skills.discover()
        logger.info(f"Skills loaded: {list(self.skills.skills.keys())}")

        # ── H20 learning loop: per-turn background reviewer (default-off) ──
        # Gated at spawn time by cognition.review_enabled; the LLM policy is
        # strict-local by construction (router.local_backend fails closed —
        # no local backend up ⇒ the review pass just skips; NEVER the cloud-
        # preferring HybridRouter.backend property).
        try:
            from .learning.background_review import BackgroundReviewer
            from .skills.proposals import SkillProposalStore
            from .paths import data_path as _dp
            self.skill_proposals = SkillProposalStore(
                path=_dp("learning", "skill_proposals.json"))

            async def _review_llm(prompt: str) -> str:
                router = self.llm_router
                # STRICT-LOCAL by construction: `local_backend` fails closed —
                # never the HybridRouter `.backend` property, which prefers
                # cloud Claude/Gemini when keys are configured. Review prompts
                # embed raw conversation content and must not egress; no local
                # backend up ⇒ RuntimeError ⇒ this review pass is skipped.
                backend = router.local_backend
                model = router.active_model or "google/gemma-4-31b-a4b"
                max_tokens = int(self.get_setting("learning.review_max_tokens", 512) or 512)
                return await backend.generate(
                    model=model, prompt=prompt,
                    system="You are a precise background reviewer. Output only JSON.",
                    max_tokens=max_tokens, temperature=0.2)

            def _review_living():
                cog = getattr(self, "cognition", None)
                if cog is None or not cog.sub_enabled("memory_enabled"):
                    return None
                return cog.module("memory")

            self.reviewer = BackgroundReviewer(
                _review_llm,
                living=_review_living,
                skills=self.skills,
                learning=(self.cognition.module("learning")
                          if getattr(self, "cognition", None) is not None else None),
                proposals=self.skill_proposals,
                approvals=getattr(self, "action_approvals", None),
                get_setting=self.get_setting,
            )

            # H20.5 — usage telemetry (sidecar, best-effort) + the nightly skill
            # curator (lifecycle + approved-patch application; gated at the tick).
            from .skills.usage import SkillUsageStore
            from .skills.curator import SkillCurator
            self.skill_usage = SkillUsageStore(path=_dp("learning", "skill_usage.json"))
            self.skills.attach_usage(self.skill_usage)
            self.curator = SkillCurator(
                self.skills, self.skill_usage,
                proposals=self.skill_proposals,
                approvals=getattr(self, "action_approvals", None),
                get_setting=self.get_setting,
                run_store=ReflectionRunStore(_dp("learning", "curator_runs.json")),
                archive_dir=_dp("skills", "archive"),
            )
        except Exception:
            logger.warning("learning reviewer init failed", exc_info=True)

        self.checkpoints.initialize()
        restored = self.checkpoints.restore(self)
        if restored:
            logger.info(f"Restored from checkpoint — session: {self.session_id}")
            # The checkpoint restores the *id*; ConversationMemory only auto-loads
            # the newest session at construction time, so without this the two
            # disagree — self.session_id points at a session whose turns were
            # never loaded, and the next turn starts from an empty history that
            # then overwrites the snapshot. Resume is a no-op when the memory
            # already holds that session.
            if self.session_id:
                try:
                    await self.memory.resume_session(self.session_id)
                except Exception:
                    logger.debug("session resume after checkpoint restore skipped",
                                 exc_info=True)

        if not self.session_id:
            self.session_id = self.memory.conversation.current_session_id or await self.memory.new_session()
            logger.info(f"Session: {self.session_id}")

        self.load_runtime_settings()
        self.heartbeat_scheduler.load_all()
        self.heartbeat_scheduler.load_from_config(self.config)

        for agent_id, hb_config in self.heartbeat_scheduler._heartbeat_configs.items():
            if agent_id in self.agents:
                self.agents[agent_id]._heartbeat_config = hb_config

    @staticmethod
    def _normalize_trait_config(raw) -> Optional[dict]:
        """Normalize SOUL front-matter traits into Personality distributions."""
        if not isinstance(raw, dict):
            return None
        out = {}
        for name, spec in raw.items():
            try:
                if isinstance(spec, dict):
                    mu = float(spec.get("mu", spec.get("mean", 0.5)))
                    sigma = float(spec.get("sigma", 0.0))
                    skew = float(spec.get("skew", 0.0))
                else:
                    mu = float(spec)
                    sigma = 0.0
                    skew = 0.0
            except (TypeError, ValueError):
                continue
            out[str(name)] = {
                "mu": max(0.0, min(1.0, mu)),
                "sigma": max(0.0, sigma),
                "skew": skew,
            }
        return out or None

    @staticmethod
    def _trait_mu(traits: Optional[dict]) -> dict:
        if not traits:
            return {}
        out = {}
        for name, spec in traits.items():
            if isinstance(spec, dict):
                out[str(name)] = round(float(spec.get("mu", 0.5)), 4)
        return out

    def _configure_cognition_roster(self) -> None:
        """Give cognition modules the real active-agent roster once agents load."""
        cog = getattr(self, "cognition", None)
        if cog is None:
            return
        persona = cog.module("persona")
        ensemble = cog.module("ensemble")
        if persona is None and ensemble is None:
            return

        for agent_id, agent in sorted(self.agents.items()):
            meta = dict((getattr(agent, "soul", {}) or {}).get("meta") or {})
            personality_meta = meta.get("personality") if isinstance(meta.get("personality"), dict) else {}
            raw_traits = meta.get("traits") or personality_meta.get("traits")
            traits = self._normalize_trait_config(raw_traits)

            affect_meta = meta.get("affect") if isinstance(meta.get("affect"), dict) else {}
            try:
                valence = float(affect_meta.get("valence_setpoint", affect_meta.get("valence", 0.0)))
                arousal = float(affect_meta.get("arousal_setpoint", affect_meta.get("arousal", 0.0)))
            except (TypeError, ValueError):
                valence, arousal = 0.0, 0.0

            baseline = self._trait_mu(traits)
            if persona is not None:
                persona.configure(
                    agent_id,
                    traits=traits,
                    valence_setpoint=valence,
                    arousal_setpoint=arousal,
                )
                if not baseline:
                    baseline = persona.traits(agent_id)
            if ensemble is not None and baseline:
                ensemble.register_persona(agent_id, baseline)

    def load_runtime_settings(self):
        try:
            all_s = _get_settings()
            flat = {}
            for cat, items in all_s.items():
                for item in items:
                    flat[f"{cat}.{item['key']}"] = item["value"]
            from .product_posture import apply_to_runtime_settings
            flat = apply_to_runtime_settings(flat)
            self._runtime_settings = flat
            logger.debug(f"Runtime settings loaded: {len(flat)} keys")
            # Product Posture wave 1 can wake turn embeddings without replacing
            # the legacy MEMORY_EMBED_TURNS env default; off/no key preserves it.
            if getattr(self, "memory", None) is not None and "memory.embed_turns" in flat:
                self.memory.embed_turns = bool(flat["memory.embed_turns"])
            # Propagate the live kill-switch to the controller (≤30s to take
            # effect via the settings watcher) — no restart needed to disable.
            ctrl = getattr(self, "lmstudio", None)
            if ctrl is not None:
                ctrl.set_enabled(self._control_master_enabled())
            # Propagate llm.cloud_fallback (never|on-demand|always) to the router
            # so the /admin privacy knob actually governs cloud escalation live.
            router = getattr(self, "llm_router", None)
            if router is not None and hasattr(router, "set_cloud_fallback_mode"):
                mode = flat.get("llm.cloud_fallback", "on-demand")
                # 0.62: a constrained system-profile model_tier (gaming → local-light,
                # multimedia → local) keeps inference local — never escalate to cloud,
                # regardless of the setting. "auto" (balanced/ai/admin) imposes nothing.
                from .system_profiles import preferred_model_tier
                if preferred_model_tier() != "auto":
                    mode = "never"
                router.set_cloud_fallback_mode(mode)
            # Propagate the prompt-size routing thresholds (local vs cloud-flash)
            # so the /admin knobs actually govern routing live. 0 = unlimited.
            if router is not None and hasattr(router, "set_local_max"):
                router.set_local_max(flat.get("llm.hybrid_local_max"))
                router.set_flash_max(flat.get("llm.hybrid_flash_max"))
        except Exception as e:
            log_error(logger, E_INTERNAL_UNEXPECTED, component="settings_db", detail=str(e))

    def get_setting(self, key: str, default=None):
        return self._runtime_settings.get(key, default)

    async def _settings_watcher_loop(self):
        while True:
            await asyncio.sleep(30)
            self.load_runtime_settings()

    # ── Autonomy / Proactive Cortex (H6.1–H6.3) ────────────────────
    # Autonomy wiring (inbox→Telegram), the executor build, and the worker
    # loop live in AutonomyCoordinator (CLN-2); see self._autonomy.

    async def _run_learning_loop(self) -> list[dict]:
        """Propose agent promotions into the decision inbox (gated, reversible)."""
        from .learning.scheduler import propose_promotions
        return propose_promotions(self.learning, self.autonomy_queue, list(self.agents.keys()))

    async def _run_worldview_kg_sync(self):
        """Run one WorldView ontology -> knowledge-graph sync pass (best-effort)."""
        plugin = self.plugins.get("worldview")
        if plugin is None or getattr(self, "memory", None) is None:
            return
        try:
            from .memory.worldview_sync import WorldViewKGSync
            summary = await WorldViewKGSync(self.memory, plugin).sync()
            if summary.get("events"):
                logger.info("WorldView KG sync: %s", summary)
        except Exception as e:
            logger.warning(f"WorldView KG sync failed: {e}")

    async def register_channel(self, channel: ChannelAdapter):
        self.channel_manager.register(channel)

    async def start_channels(self):
        await self.channel_manager.start_all()
        self.heartbeat_scheduler.start(self)
        self._settings_watcher_task = asyncio.create_task(self._settings_watcher_loop())
        self._settings_watcher_task.add_done_callback(_log_task_result)
        self._autonomy.wire()
        self._scheduler.schedule_all()
        self._autonomy_task = asyncio.create_task(self._autonomy.loop())
        self._autonomy_task.add_done_callback(_log_task_result)
        # Oracle GitHub watcher is OFF by default: it polls a GitHub repo every 30s,
        # which a privacy-first local product should not do unsolicited. It's a
        # dev/dogfooding feature — enable with JARVIS_ORACLE_WATCH=1 or the
        # `oracle.watch_enabled` setting.
        _oracle_watch = env_flag("JARVIS_ORACLE_WATCH") or self.get_setting("oracle.watch_enabled", False)
        if hasattr(self, 'oracle_bridge') and not env_flag("JARVIS_TESTING") and _oracle_watch:
            self.oracle_bridge.start_watcher()
        if not env_flag("JARVIS_TESTING"):
            from agents.core.learning_loop import run_learning_loop
            _ll = asyncio.create_task(run_learning_loop(self))
            _ll.add_done_callback(_log_task_result)
        logger.info(f"Channels started: {list(self.channels.keys())}")
        logger.info("Components: %s", self.components.summary())  # A8: startup health report

    async def stop_channels(self):
        await self.channel_manager.stop_all()
        self.heartbeat_scheduler.stop()
        if self._settings_watcher_task:
            self._settings_watcher_task.cancel()
        # Close all active plugins gracefully (CLN-2: owned by PluginManager).
        await self.plugin_manager.close_all()
        logger.info("Channels stopped")

    async def channel_handler(self, text: str, channel: str = "voice", **kwargs) -> Optional[str]:
        action_origin = kwargs.pop("origin", origin_for_channel(channel))
        kwargs.pop("_inbound_meta", None)
        origin_token = bind_action_origin(action_origin)
        chat_id = kwargs.get("chat_id")
        try:
            # H3.3: cross-channel context is opt-in. When enabled, every channel
            # shares self.session_id (web<->telegram continuity). When off (default),
            # telegram keeps per-chat_id isolation (H1.2).
            cross_channel = self.get_setting("memory.cross_channel_sessions", False)
            if not cross_channel and channel == "telegram" and chat_id:
                ck = f"tg:{chat_id}"
                if ck not in self._channel_sessions:
                    self._channel_sessions[ck] = await self.memory.new_session()
                # BUG-5: bind this telegram chat's session into the per-request async
                # context instead of mutating shared `self.session_id` and restoring
                # it in a finally. The old save/restore-on-self clobbered concurrent
                # turns (the finally reset the *shared* attribute another in-flight
                # request was reading). Here we set a *context-local* token and reset
                # it in finally, so the binding is scoped to this request's async
                # context only and never touches the shared default. `_resolve_session`
                # inside handle_input keeps the value we set here.
                token = _active_session.set(self._channel_sessions[ck])
                try:
                    response = await self.handle_input(text, channel)
                finally:
                    _active_session.reset(token)
            else:
                response = await self.handle_input(text, channel)

            await self.channel_manager.send(channel, response, **kwargs)
            return response
        finally:
            reset_action_origin(origin_token)

    def _resolve_session(self, session_id: Optional[str]) -> str:
        """BUG-5: bind the active session into the per-request async context.

        Pins the session this turn should use into the `_active_session`
        ContextVar so that, for the rest of this call, `self.session_id` reads
        resolve to a request-local value and any in-turn `self.session_id =`
        write updates only this context — never the shared instance default
        another concurrent turn might be reading.

        Resolution order:
          1. an explicit `session_id` passed by the caller (per-request value);
          2. a session already bound in this async context (e.g. `channel_handler`
             pinned a per-chat_id telegram session before delegating here);
          3. the shared instance default (`self.session_id`) — preserves the
             single-request behavior for callers that don't pass a session.
        """
        if session_id is not None:
            _active_session.set(session_id)
            return session_id
        existing = _active_session.get()
        if existing is not _SESSION_UNSET:
            return existing
        sid = self._session_id_default
        _active_session.set(sid)
        return sid

    async def process(self, prompt: str, agent: str = "jarvis", channel: str = "internal") -> str:
        """Single LLM completion via the default-agent path — fails safe.

        Internal helper for callers that need a one-shot LLM answer outside the
        full handle_input pipeline (nightly reflection, the autonomy `_llm` task
        executor). Routes the prompt through the requested agent (default
        `jarvis`) using the same `_call_agents_parallel` path handle_input uses,
        so backend selection / routing / guardrails all apply.

        Never raises: returns "" on any failure (missing agent, no LLM backend,
        unexpected error) so swallow-and-continue callers degrade to a no-op
        instead of silently throwing an AttributeError.
        """
        if not prompt:
            return ""
        agent_id = agent if agent in self.agents else "jarvis"
        if agent_id not in self.agents:
            logger.warning(f"process(): no agent available for completion (agent={agent})")
            return ""
        try:
            responses = await self._call_agents_parallel([agent_id], prompt, {}, {})
        except RuntimeError:
            # No LLM backend up — degrade quietly (callers swallow errors anyway).
            log_error(logger, E_LLM_BACKEND_MISSING, backend=f"process:{channel}")
            return ""
        except Exception as e:
            log_error(logger, E_INTERNAL_UNEXPECTED, component=f"process:{channel}", detail=str(e))
            return ""
        resp = responses.get(agent_id, "") if responses else ""
        # _call_agents_parallel returns structured error/timeout markers instead
        # of raising; treat those as a soft failure and return "".
        if resp and re.match(rf"^\[{re.escape(agent_id)} (error|timeout)\b", resp):
            return ""
        return resp or ""

    async def handle_input(self, text: str, channel: str = "voice", agent_override: str = None,
                           session_id: str = None) -> str:
        origin_token = bind_turn_action_origin(channel)
        try:
            return await self._handle_input(text, channel, agent_override, session_id)
        finally:
            reset_action_origin(origin_token)

    async def _handle_input(self, text: str, channel: str = "voice", agent_override: str = None,
                            session_id: str = None) -> str:
        # BUG-5: pin this turn to its own session for the whole call. Resolving
        # the session into the async-context-local `_active_session` here means
        # every downstream `self.session_id` read (memory, recall, checkpoint,
        # tracer, and even `_log_session`/checkpoint saves dispatched through
        # `asyncio.to_thread`, which copies the current context) sees THIS
        # request's session — never a concurrent request's. Pass an explicit
        # `session_id` for per-request isolation; omit it to keep the prior
        # single-shared-session behavior (or to honor a session a caller like
        # `channel_handler` already pinned in this context).
        self._resolve_session(session_id)
        self._last_channel = channel  # captured for H9.2 tracer
        await self.memory.add_turn(self.session_id, "user", text, channel=channel)

        skill_cmd = self.skills.parse_command(text)
        if skill_cmd:
            skill_name, command, args = skill_cmd
            skill = self.skills.get_skill(skill_name)
            if skill:
                result = await skill.execute(command, args, {"channel": channel})
                if result:
                    await self.memory.add_turn(self.session_id, "assistant", result, agent_id=skill_name)
                    self.last_cognition = {
                        "scoring": [],
                        "decision": {
                            "source": "skill",
                            "confidence": 1.0,
                            "agents_selected": [skill_name],
                            "alternatives": [],
                            "timing": {"classify": 0, "route": 0, "total": 0}
                        },
                        "trace": [{"step": "skill_execution", "duration_ms": 10, "result": skill_name}]
                    }
                    return result

        # Natural-language LLM-backend control (start / load / unload / status).
        if self._chat_control_enabled():
            llm_ctl = detect_llm_control(text)
            if llm_ctl:
                reply = await self._run_llm_control(*llm_ctl)
                if reply:
                    await self.memory.add_turn(self.session_id, "assistant", reply, agent_id="jarvis")
                    self.last_cognition = self._control_cognition(llm_ctl[0])
                    return reply

        t_c0 = time.perf_counter()
        intent = await self.router.classify(text, self.agents)
        t_classify = int((time.perf_counter() - t_c0) * 1000)
        t_route = 5

        t_p0 = time.perf_counter()
        plugin_data = await self._gather_plugin_data(text, intent)
        t_plugin = int((time.perf_counter() - t_p0) * 1000)

        if agent_override and agent_override in self.agents:
            try:
                _, _, route_name = self.llm_router.select_backend(agent_override, text)
            except RuntimeError:
                route_name = ""
            t_s0 = time.perf_counter()
            responses = await self._call_agents_parallel(
                [agent_override], text, intent.context, plugin_data
            )
            synthesized = list(responses.values())[0] if responses else ""
            t_synthesize = int((time.perf_counter() - t_s0) * 1000)
            await self._complete_llm_turn(
                text=text,
                intent=intent,
                plugin_data=plugin_data,
                responses=responses,
                synthesized=synthesized,
                responder_id=agent_override,
                route_name=route_name,
                channel=channel,
                action_taken=f"handle_input(agent_override={agent_override}) via {channel}",
                t_classify=t_classify,
                t_route=t_route,
                t_plugin=t_plugin,
                t_synthesize=t_synthesize,
            )
            return synthesized

        # Determine route for the primary target agent
        primary_agent = (intent.target_agents or ["jarvis"])[0]
        try:
            _, _, route_name = self.llm_router.select_backend(primary_agent, text)
        except RuntimeError:
            route_name = ""

        if intent.target_agents:
            responses = await self._call_agents_parallel(
                self._route_candidates(intent), text, intent.context, plugin_data
            )
        elif intent.is_general:
            responses = await self._call_agents_parallel(
                ["jarvis"], text, intent.context, plugin_data
            )
        else:
            responses = {"jarvis": "I don't have a specialist for that yet."}

        handoff_target = self._detect_handoff(responses)
        if handoff_target:
            logger.info(f"Handoff detected: {handoff_target}")
            handoff_responses = await self._call_agents_parallel(
                [handoff_target], text, intent.context, plugin_data
            )
            responses.update(handoff_responses)

        was_synthesized = len(responses) > 1 or "jarvis" not in responses
        # Attribute the turn to the agent that actually produced it: Jarvis when
        # it synthesized a multi-agent answer, otherwise the single responder.
        responder_id = "jarvis"
        t_s0 = time.perf_counter()
        try:
            if was_synthesized:
                synthesized = await self._synthesize(responses, intent)
            else:
                responder_id = next(iter(responses))
                synthesized = responses[responder_id]
        except RuntimeError:
            synthesized = "I'm sorry, sir — my language backend is not available. Please start Ollama or LM Studio and try again."
            log_error(logger, E_LLM_BACKEND_MISSING, backend="synthesize")
        except Exception as e:
            synthesized = f"I hit an issue processing that: {e}"
            log_error(logger, E_INTERNAL_UNEXPECTED, component="synthesize", detail=str(e))
        t_synthesize = int((time.perf_counter() - t_s0) * 1000)

        skill_name = self._detect_skill_learning(responses, synthesized, intent)
        if skill_name:
            logger.info(f"Learned new skill: {skill_name}")

        await self._complete_llm_turn(
            text=text,
            intent=intent,
            plugin_data=plugin_data,
            responses=responses,
            synthesized=synthesized,
            responder_id=responder_id,
            route_name=route_name,
            channel=channel,
            action_taken=f"handle_input via {channel}",
            t_classify=t_classify,
            t_route=t_route,
            t_plugin=t_plugin,
            t_synthesize=t_synthesize,
        )
        return synthesized

    async def handle_input_stream(self, text: str, channel: str = "voice", on_token: Callable = None,
                                  agent_override: str = None, session_id: str = None) -> str:
        origin_token = bind_turn_action_origin(channel)
        try:
            return await self._handle_input_stream(text, channel, on_token, agent_override, session_id)
        finally:
            reset_action_origin(origin_token)

    async def _handle_input_stream(self, text: str, channel: str = "voice", on_token: Callable = None,
                                   agent_override: str = None, session_id: str = None) -> str:
        # BUG-5: see handle_input — pin this turn to its own session so it can
        # never read or write another concurrent request's conversation.
        self._resolve_session(session_id)
        self._last_channel = channel  # captured for H9.2 tracer
        await self.memory.add_turn(self.session_id, "user", text, channel=channel)

        skill_cmd = self.skills.parse_command(text)
        if skill_cmd:
            skill_name, command, args = skill_cmd
            skill = self.skills.get_skill(skill_name)
            if skill:
                result = await skill.execute(command, args, {"channel": channel})
                if result:
                    await self.memory.add_turn(self.session_id, "assistant", result, agent_id=skill_name)
                    if on_token:
                        on_token(result)
                    self.last_cognition = {
                        "scoring": [],
                        "decision": {
                            "source": "skill",
                            "confidence": 1.0,
                            "agents_selected": [skill_name],
                            "alternatives": [],
                            "timing": {"classify": 0, "route": 0, "total": 0}
                        },
                        "trace": [{"step": "skill_execution", "duration_ms": 10, "result": skill_name}]
                    }
                    return result

        # Natural-language LLM-backend control (start / load / unload / status).
        if self._chat_control_enabled():
            llm_ctl = detect_llm_control(text)
            if llm_ctl:
                reply = await self._run_llm_control(*llm_ctl)
                if reply:
                    await self.memory.add_turn(self.session_id, "assistant", reply, agent_id="jarvis")
                    if on_token:
                        on_token(reply)
                    self.last_cognition = self._control_cognition(llm_ctl[0])
                    return reply

        t_c0 = time.perf_counter()
        intent = await self.router.classify(text, self.agents)
        t_classify = int((time.perf_counter() - t_c0) * 1000)
        t_route = 5

        t_p0 = time.perf_counter()
        plugin_data = await self._gather_plugin_data(text, intent)
        t_plugin = int((time.perf_counter() - t_p0) * 1000)

        if agent_override and agent_override in self.agents:
            target = [agent_override]
        else:
            target = self._route_candidates(intent) if intent.target_agents else ["jarvis"]

        context_window = self.get_setting("memory.context_window", 6)
        history, history_parts = await self._history_for_prompt_parts(
            context_window,
            current_user_text=text,
        )
        plugin_block = self._format_plugin_data(plugin_data)
        recall_block = await self._recall_block(text)
        runtime_block = self._runtime_state_block() + self._language_block() + self._data_grounding_block(plugin_data)
        synthesized = ""
        # Pre-bind so the post-loop persist/audit never hit UnboundLocalError when
        # `target` is empty (e.g. _route_candidates returns nothing).
        agent_id = None
        route_name = ""
        t_s0 = time.perf_counter()
        for agent_id in target:
            if agent_id in self.agents:
                agent = self.agents[agent_id]
                system_prompt = agent.soul.get("content", "")
                turn_text = await self._build_agent_turn_text(
                    agent_id,
                    text,
                    history=history,
                    plugin_block=plugin_block,
                    recall_block=recall_block,
                    runtime_block=runtime_block,
                )
                prompt = self._build_agent_prompt(agent, turn_text, intent.context)
                model = self._agent_default_model(agent_id, agent)

                checkpoint = self.checkpoints.load(agent_id, self.session_id)
                if checkpoint:
                    prompt = f"[RESUMED FROM CHECKPOINT]\n{checkpoint['prompt']}\n---\n{prompt}"

                try:
                    backend, router_model, route_name = self.llm_router.select_backend(agent_id, prompt)
                    if router_model:
                        model = router_model
                    # Reasoning models on the deep slot need a far larger budget:
                    # 1–2k tokens is consumed by chain-of-thought before any
                    # answer, so a small cap truncates mid-thought.
                    eff_max_tokens, temperature = self._agent_gen_params(agent, route_name)
                    cap_label = "auto" if eff_max_tokens <= 0 else eff_max_tokens
                    logger.info(f"Routing {agent_id} via {route_name} ({estimate_tokens(prompt)} tokens, max_tokens={cap_label})")

                    request_scope = nullcontext()
                    if isinstance(backend, GeminiBackend):
                        # One immutable lease owns both this generation and any
                        # cache lookup/create decision made for it.
                        lease = backend.acquire_lease()
                        request_binding = GeminiRequestBinding(
                            lease=lease,
                            session_id=self.session_id,
                        )
                        if (
                            self.context_cache is not None
                            and history_parts
                            and self.security is not None
                        ):
                            cache_material = self.security.prepare_cache_material(
                                system_prompt,
                                history_parts,
                            )
                            cache_binding = await self.context_cache.acquire_binding(
                                session_id=self.session_id,
                                model=model,
                                system_instruction=cache_material.system_instruction,
                                history=cache_material.history,
                                policy_fingerprint=cache_material.policy_fingerprint,
                                lease=lease,
                            )
                            if cache_binding is not None:
                                request_binding = cache_binding
                                tail_history = "\n".join(
                                    history_parts[cache_binding.cached_prefix_count :]
                                )
                                cached_turn_text = await self._build_agent_turn_text(
                                    agent_id,
                                    text,
                                    history=tail_history,
                                    plugin_block=plugin_block,
                                    recall_block=recall_block,
                                    runtime_block=runtime_block,
                                )
                                prompt = self._build_agent_prompt(
                                    agent,
                                    cached_turn_text,
                                    intent.context,
                                )
                                if checkpoint:
                                    prompt = (
                                        "[RESUMED FROM CHECKPOINT]\n"
                                        f"{checkpoint['prompt']}\n---\n{prompt}"
                                    )
                            else:
                                self._spawn_cache_task(
                                    self._async_create_cache(
                                        session_id=self.session_id,
                                        system_instruction=cache_material.system_instruction,
                                        history_texts=cache_material.history,
                                        model=model,
                                        policy_fingerprint=cache_material.policy_fingerprint,
                                        lease=lease,
                                    ),
                                    session_id=self.session_id,
                                )
                        request_scope = backend.request_scope(request_binding)
                except LocalBackendUnavailableError:
                    msg = LOCAL_SELECTION_UNAVAILABLE_REPLY
                    log_error(logger, E_LLM_BACKEND_MISSING, backend="stream-local")
                    if on_token:
                        on_token(msg)
                    return msg
                except RuntimeError:
                    msg = "I'm sorry, sir — my language backend is not available. Please start Ollama or LM Studio and try again."
                    log_error(logger, E_LLM_BACKEND_MISSING, backend="stream")
                    if on_token:
                        on_token(msg)
                    return msg

                t_s0 = time.perf_counter()
                with request_scope:
                    guarded_backend = bind_guardrails(self.security, backend)
                    response = await agent.generate_response(
                        backend=guarded_backend,
                        model=model,
                        prompt=prompt,
                        system=system_prompt,
                        max_tokens=eff_max_tokens,
                        temperature=temperature,
                        on_token=on_token,
                    )
                synthesized = response
                break

        # Truncated-before-answer (or otherwise empty) replies must not surface
        # as a blank bubble. The backend already refuses to leak raw reasoning,
        # so an empty string here means "no answer was produced".
        if not (synthesized or "").strip():
            synthesized = "My reply was cut short before I finished, sir — the model ran out of context while thinking. Try again, simplify the request, or load a larger-context model in LM Studio."
            if on_token:
                emitted = on_token(synthesized)
                if inspect.isawaitable(emitted):
                    await emitted
        _stream_responses = {agent_id: synthesized} if agent_id else {}
        t_synthesize = int((time.perf_counter() - t_s0) * 1000)
        await self._complete_llm_turn(
            text=text,
            intent=intent,
            plugin_data=plugin_data,
            responses=_stream_responses,
            synthesized=synthesized,
            responder_id=agent_id,
            route_name=route_name,
            channel=channel,
            action_taken=f"handle_input_stream({agent_id}) via {channel}",
            t_classify=t_classify,
            t_route=t_route,
            t_plugin=t_plugin,
            t_synthesize=t_synthesize,
        )
        return synthesized

    def _update_cognition(self, text, intent, plugin_data, synthesized, t_classify, t_route, t_plugin, t_synthesize):
        """Build + persist the per-turn cognition trace (delegates to cognition_trace, CLN-2)."""
        cognition_trace.update_cognition(
            self, text, intent, plugin_data, synthesized,
            t_classify, t_route, t_plugin, t_synthesize)

    def _detect_handoff(self, responses: dict[str, str]) -> Optional[str]:
        for agent_id, resp in responses.items():
            if resp and HANDOFF_PREFIX in resp:
                start = resp.index(HANDOFF_PREFIX) + len(HANDOFF_PREFIX)
                end = resp.index("]", start) if "]" in resp[start:] else len(resp)
                target = resp[start:end].strip()
                if target in self.agents:
                    return target
        return None

    def _detect_skill_learning(self, responses: dict, synthesized: str, intent) -> Optional[str]:
        for agent_id, resp in responses.items():
            if resp and SKILL_PREFIX in resp:
                try:
                    start = resp.index(SKILL_PREFIX) + len(SKILL_PREFIX)
                    end = resp.index("]", start)
                    block = resp[start:end]
                    parts = [p.strip() for p in block.split("|")]
                    task_desc = parts[0] if len(parts) > 0 else "custom task"
                    steps = [s.strip() for s in parts[1].split(",")] if len(parts) > 1 else ["implemented solution"]
                    cmd = parts[2].strip() if len(parts) > 2 else None
                    return self.skills.generate_skill(
                        agent_id=agent_id,
                        task_description=task_desc,
                        solution_steps=steps,
                        command_name=cmd,
                        output=resp[:200],
                    )
                except (ValueError, IndexError):
                    continue
        return None

    def _route_candidates(self, intent) -> list[str]:
        """Apply the live learning loop to routing: reorder candidate agents by
        recent health and drop chronically-failing ones when an alternative
        exists. Explicit wake-word calls are never rerouted."""
        agents = list(intent.target_agents or [])
        if len(agents) <= 1 or intent.context.get("source") == "wake_word":
            return agents
        ranked = self.learning.rank_candidates(agents)
        healthy = [a for a in ranked if not self.learning.is_unhealthy(a)]
        chosen = healthy if healthy else ranked[:1]
        if chosen != agents:
            logger.info(f"Routing adjusted by learning: {agents} -> {chosen}")
        return chosen

    def _first_target_agent(self, intent) -> str:
        return plugin_gatherer.first_target_agent(self, intent)

    def _any_agent_can(self, plugin: str, intent) -> bool:
        return plugin_gatherer.any_agent_can(self, plugin, intent)

    async def _gather_plugin_data(self, text: str, intent) -> dict:
        return await plugin_gatherer.gather_plugin_data(self, text, intent)

    def _extract_location(self, text: str) -> str:
        return plugin_gatherer.extract_location(text)

    def _format_plugin_data(self, data: dict) -> str:
        return plugin_gatherer.format_plugin_data(data)

    async def _drive_ai_startup(self) -> None:
        """PRIVATE personalization: rclone-import the owner's Drive "AI" folder
        into a gitignored local dir, then ingest it into memory via the existing
        local-docs indexer (H12.2). Best-effort; never raises."""
        from agents.core.ingestion.drive_sync import DriveAISync
        sync = DriveAISync.from_env()
        if not sync.available():
            logger.info("Drive AI sync skipped (no JARVIS_DRIVE_AI_REMOTE or rclone not on PATH)")
            return
        summary = await sync.sync()
        if not summary.get("ok"):
            logger.warning("Drive AI sync failed: %s", summary.get("error"))
            return
        logger.info("Drive AI synced → %s", summary.get("dest"))
        # Ingest into memory unless disabled (JARVIS_DRIVE_AI_INDEX=0 = sync only).
        if not env_flag("JARVIS_DRIVE_AI_INDEX", True):
            return
        try:
            from agents.core.local_docs import LocalDocsIndexer

            async def _remember(text: str, metadata: dict):
                return await self.memory.remember(text, metadata=metadata)

            result = await LocalDocsIndexer(_remember).index(summary["dest"])
            logger.info("Drive AI indexed into memory: %s", result)
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("Drive AI index failed: %s", e)

    def _runtime_state_block(self) -> str:
        """Ground-truth runtime facts injected into the prompt so agents report
        the model/backend that is *actually* serving them instead of inventing
        one. The active model is auto-detected from the live backend at startup
        (LLMRouter.detect), so this stays honest when the loaded model changes."""
        router = getattr(self, "llm_router", None)
        backend = getattr(router, "name", None) if router else None
        if not backend or backend == "none":
            return ""
        model = getattr(router, "active_model", None) or "unknown"
        return (
            "System runtime (ground truth — use this if asked which model, brain, "
            "or backend you run on; never invent model names or hardware):\n"
            f"- LLM backend: {backend}\n"
            f"- Active model: {model}\n\n"
        )

    def _language_block(self) -> str:
        """Mirror the owner's language, for EVERY agent.

        The rule "Romanian in, Romanian out" lived only in `agents/jarvis/SOUL.md`, so an
        agent-pinned turn never saw it: the 2026-07-27 QA run asked Steve
        "dă-mi un raport de sănătate a sistemului" and got a wholly English reply, while
        Gecko happened to mirror correctly. Per-persona wording cannot hold a
        cross-cutting rule — so it joins the runtime and data rails, which every agent
        receives regardless of routing."""
        return (
            "Language (applies to every agent, whatever your persona says):\n"
            "- Reply in the SAME language the owner just used. Romanian in → Romanian "
            "out; English in → English out. Do not switch language mid-conversation "
            "unless asked.\n"
            "- Keep technical identifiers (route paths, model names, env vars, code) "
            "verbatim — translate the prose around them, never the identifier.\n\n"
        )

    def _data_grounding_block(self, plugin_data: dict) -> str:
        """Ground truth for *data* — the counterpart to `_runtime_state_block`'s
        ground truth for *model identity*. Injected every turn so an agent can't
        narrate a SOUL-described capability (calendar, finances, system health,
        service status…) as fact when no tool actually returned data. It names the
        live sources present this turn and forbids inventing the rest.

        This closes the fabrication gap found in the 2026-07-24 QA run: with a
        connector disconnected the gatherer stays silent (`format_plugin_data`
        emits nothing), so previously the model saw only its persona + the
        question and confabulated. Now it is told, by construction, what it may
        read and that it must refuse honestly otherwise."""
        connected = sorted(k for k, v in (plugin_data or {}).items() if v)
        have = ", ".join(connected) if connected else "none"
        return (
            "Data grounding (ground truth — obey this over any capability your "
            "persona describes):\n"
            f"- Live data sources connected this turn: {have}.\n"
            "- Report ONLY data shown in a [REAL-TIME DATA] block above. Do NOT "
            "invent, assume, or role-play calendar events, meetings, emails, account "
            "balances, financial figures, system/hardware metrics, or service status. "
            "If asked for something with no live data here, say plainly it is not "
            "connected — never fabricate a value, and never claim you performed an "
            "action (saved, sent, booked, logged, blocked, briefed) that you did "
            "not actually perform.\n"
            "- This applies to actions in ANY tense. Do not say a check, connection, "
            "sync or hand-off is in progress, queued, being verified, or will report "
            "back later — nothing runs between turns, so a promised follow-up can "
            "never arrive. If a connector is missing, say it is not connected and "
            "state what the owner must do; do not describe work happening on their "
            "behalf.\n\n"
        )

    def _control_master_enabled(self) -> bool:
        """Master switch for LM Studio lifecycle control (chat + admin API + HUD).
        Off if EITHER the env var or the live ``llm.control_enabled`` setting is
        off, so any single kill signal wins. Both default on."""
        return (env_flag("JARVIS_LMSTUDIO_CONTROL", True)
                and _as_bool(self.get_setting("llm.control_enabled", True)))

    def _chat_control_enabled(self) -> bool:
        """Whether a natural-language chat message may drive LLM control. Needs the
        master switch plus its own ``JARVIS_LMSTUDIO_CHAT_CONTROL`` env /
        ``llm.chat_control`` setting — lets you mute ambient detection while
        keeping the explicit admin buttons live."""
        return (self._control_master_enabled()
                and env_flag("JARVIS_LMSTUDIO_CHAT_CONTROL", True)
                and _as_bool(self.get_setting("llm.chat_control", True)))

    def _control_cognition(self, action: str) -> dict:
        return llm_control.control_cognition(action)

    async def _run_llm_control(self, action: str, model: Optional[str]) -> Optional[str]:
        """Execute a detected LLM-control action (delegates to llm_control, CLN-2)."""
        return await llm_control.run_llm_control(self, action, model)

    async def _recall_block(self, text: str) -> str:
        """Long-term memory recall injected into the prompt (RAG, all agents).

        Off by default — enable with the `memory.recall_enabled` setting. Pairs
        with `MEMORY_EMBED_TURNS=true` or explicit `/api/memory/remember` so there
        is something to recall. Embeds the query and runs fused recall (vector ⊕
        graph); any failure degrades to an empty block (never breaks a turn)."""
        if not self.get_setting("memory.recall_enabled", False):
            return ""
        try:
            k = self.get_setting("memory.recall_top_k", 5)
            hits = await self.memory.recall(text, top_k=k)
            hits = self._living_memory_rerank_hits(hits)
        except Exception as e:
            logger.warning(f"recall failed: {e}")
            return ""
        # CDX-7: retrieved memory is an indirect-injection surface — fence it as scanned,
        # capped, provenance-tagged DATA (never a raw splice) via the rag_guard choke point.
        from .security.rag_guard import provenance_from_hit, wrap_memory
        wrapped = wrap_memory([provenance_from_hit(h) for h in (hits or [])],
                              label="long-term memory (recall)")
        return wrapped.block

    def _living_memory_rerank_hits(self, hits: list) -> list:
        """Use cognition LivingMemory metadata as a post-fusion recall hint."""
        cog = getattr(self, "cognition", None)
        if cog is None or not cog.sub_enabled("memory_enabled"):
            return hits
        living = cog.module("memory")
        if living is None:
            return hits
        from .memory.living_recall import rerank_with_living_memory
        return rerank_with_living_memory(hits, living, decay_memory=getattr(self, "decay", None))

    def _living_core_memory_block(self) -> str:
        """Render bounded LivingMemory core facts for prompt context.

        Frozen-snapshot discipline (hermes-agent pattern): the block is rendered
        once per session and cached, so mid-session core writes reach disk but
        never mutate the in-flight prompt prefix — the stable prefix keeps local
        llama.cpp/LM Studio (and cloud) prompt caches warm. A new session (or
        /reset) re-renders. Entries are injection-scanned by the renderer; see
        agents/core/learning/core_block.py.
        """
        cog = getattr(self, "cognition", None)
        if cog is None or not cog.sub_enabled("memory_enabled"):
            return ""
        # Key on (session, day): jarvis sessions can live for days (unlike
        # hermes conversation-scoped ones), and the nightly reflector writes
        # core lessons — the day component bounds snapshot staleness to a day
        # without giving up intra-day prefix stability. AttributeError-safe so
        # partially-constructed orchestrators (test stubs via __new__) work.
        try:
            session = self.session_id or "default"
        except AttributeError:
            session = "default"
        cache_key = (session, time.strftime("%Y-%m-%d"))
        cached = getattr(self, "_core_block_cache", None)
        if cached is not None and cached[0] == cache_key:
            return cached[1]
        living = cog.module("memory")
        try:
            from .learning.core_block import render_core_block
            block = render_core_block(living)
        except Exception:
            logger.debug("LivingMemory core render skipped", exc_info=True)
            return ""
        self._core_block_cache = (cache_key, block)
        return block

    def _persona_prompt_block(self, agent_id: str) -> str:
        """Persona prompt block for a single agent, gated by cognition settings."""
        cog = getattr(self, "cognition", None)
        if cog is None or not cog.sub_enabled("affect_enabled"):
            return ""
        module = cog.module("persona")
        if module is None:
            return ""
        try:
            return module.prompt_block(agent_id) or ""
        except Exception:
            logger.debug("persona prompt block skipped for %s", agent_id, exc_info=True)
            return ""

    async def _build_agent_turn_text(
        self,
        agent_id: str,
        text: str,
        *,
        history: str = "",
        plugin_block: str = "",
        recall_block: str = "",
        runtime_block: str = "",
    ) -> str:
        """Shared per-turn prompt ingredients before the agent prompt wrapper.

        Both non-stream and stream turns feed this text into ``Agent.build_prompt``.
        That keeps persona, memory context, plugin data, long-term recall and
        runtime truth aligned across the two surfaces.
        """
        base = text
        if history:
            base = f"Context:\n{history}\n\nUser: {text}"

        parts = []
        persona_block = self._persona_prompt_block(agent_id)
        if persona_block:
            parts.append(persona_block)

        agent_context = await self.memory.get_agent_context(agent_id)
        if agent_context:
            parts.append(f"Agent context: {agent_context}")

        core_memory_block = self._living_core_memory_block()
        if core_memory_block:
            parts.append(core_memory_block)

        for block in (plugin_block, recall_block, runtime_block):
            block = (block or "").strip()
            if block:
                parts.append(block)
        parts.append(base)
        return "\n\n".join(parts)

    def _build_agent_prompt(self, agent, text: str, context: dict) -> str:
        build_prompt = getattr(agent, "build_prompt", None)
        if callable(build_prompt):
            return build_prompt(text, context)
        name = getattr(agent, "name", "agent")
        return f"User said: {text}\nRespond as {name}."

    def _agent_default_model(self, agent_id: str, agent) -> str:
        default_model = getattr(agent, "default_model", None)
        if callable(default_model):
            return default_model()
        if agent_id == "howard" and hasattr(self.llm_router, "get_howard_model"):
            return self.llm_router.get_howard_model()
        config = getattr(agent, "config", {}) or {}
        return config.get("model", "google/gemma-4-31b-a4b")

    def _agent_gen_params(self, agent, route_name: str) -> tuple[int, float]:
        gen_params = getattr(agent, "_gen_params", None)
        if callable(gen_params):
            return gen_params(route_name)
        max_tokens = self.get_setting("llm.max_tokens", 0)
        if route_name == "local-deep":
            max_tokens = self.get_setting("llm.deep_max_tokens", max_tokens)
        return int(max_tokens or 0), float(self.get_setting("llm.temperature", 0.7))

    def _nudge_persona_after_turn(self, agent_id: Optional[str], response: str) -> None:
        """Small affect nudge after a completed LLM turn, gated by cognition."""
        if not agent_id:
            return
        cog = getattr(self, "cognition", None)
        if cog is None or not cog.sub_enabled("affect_enabled"):
            return
        module = cog.module("persona")
        if module is None:
            return
        failed = _is_failed_agent_reply(agent_id, response)
        try:
            module.nudge(
                agent_id,
                valence=-0.04 if failed else 0.03,
                arousal=0.02,
            )
        except Exception:
            logger.debug("persona nudge skipped for %s", agent_id, exc_info=True)

    # Channels whose turns must never trigger a review pass — they are the
    # loop's own machinery (reflection/autonomy) or delegated sub-agent work,
    # and would recurse, double-learn, or burn GPU once per spawn.
    _REVIEW_SKIP_CHANNELS = frozenset(
        {"reflection", "autonomy", "learning_review", "subagent"})

    def _spawn_background_review(self, text: str, synthesized: str, channel: str) -> None:
        """H20: spawn the per-turn learning distiller (fire-and-forget, gated)."""
        try:
            if is_degraded_reply(synthesized):
                return
            cog = getattr(self, "cognition", None)
            if cog is None or not cog.sub_enabled("review_enabled"):
                return
            if channel in self._REVIEW_SKIP_CHANNELS:
                return
            reviewer = getattr(self, "reviewer", None)
            if reviewer is None:
                return
            ok, reason = reviewer.should_run()
            if not ok:
                logger.debug("background review skipped (%s)", reason)
                return
            task = asyncio.create_task(self._background_review_task(text, synthesized))
            task.add_done_callback(_log_task_result)
        except Exception:
            logger.debug("background review spawn skipped", exc_info=True)

    async def _background_review_task(self, text: str, synthesized: str) -> None:
        """Run one review pass in the background and surface its actions."""
        history = ""
        try:
            turns = await self.memory.get_history(self.session_id or "default", last_n=6)
            history = "\n".join(
                f"{t.get('role', '?')}: {str(t.get('content', ''))[:300]}"
                for t in (turns or []))
        except Exception:
            logger.debug("review history gather skipped", exc_info=True)
        result = await self.reviewer.run(text, synthesized, history=history)
        self.last_learning_review = result
        for action in result.get("actions", []):
            logger.info("learning review: %s", action)

    async def _record_living_memory_after_turn(
        self,
        *,
        user_text: str,
        assistant_text: str,
        responder_id: Optional[str],
        channel: str,
    ) -> None:
        """Feed completed LLM turns into LivingMemory + decay when cognition is on."""
        cog = getattr(self, "cognition", None)
        if cog is None or not cog.sub_enabled("memory_enabled"):
            return
        living = cog.module("memory")
        if living is None:
            return
        session_id = self.session_id or "default"
        mem_id = f"turn:{session_id}:{int(time.time() * 1000)}:{uuid.uuid4().hex[:8]}"
        input_text = user_text or ""
        output_text = assistant_text or ""
        turn_text = "\n".join(part for part in (input_text, output_text) if part)
        text_sha256 = hashlib.sha256(turn_text.encode("utf-8", errors="ignore")).hexdigest()
        content = {
            "session": session_id,
            "agent": responder_id or "",
            "channel": channel,
            "turn_ref": mem_id,
            "text_sha256": text_sha256,
            "chars": {"input": len(input_text), "output": len(output_text)},
            "ts": time.time(),
        }
        try:
            from .cognition.memory import neuromodulators
            has_digest = getattr(living, "has_text_digest", None)
            duplicate_digest = bool(has_digest(text_sha256)) if callable(has_digest) else False
            surprise = 0.0 if duplicate_digest else 1.0
            novelty = 0.0 if duplicate_digest else 1.0
            failed = _is_failed_agent_reply(responder_id, assistant_text)
            result = living.encode(
                mem_id,
                content,
                surprise=surprise,
                nm=neuromodulators(
                    reward=0.0 if failed else 1.0,
                    surprise=surprise,
                    novelty=novelty,
                ),
            )
            if duplicate_digest and not result.get("encoded"):
                result = {**result, "reason": "duplicate_turn_digest"}
            if result.get("encoded") and getattr(self, "decay", None) is not None:
                label = f"turn:{session_id}:{responder_id or 'unknown'}:{channel}"
                await asyncio.to_thread(self.decay.add, mem_id, label=label)
            self.last_living_memory_record = {"id": mem_id, **result}
        except Exception:
            logger.debug("LivingMemory turn record skipped", exc_info=True)

    async def _complete_llm_turn(
        self,
        *,
        text: str,
        intent,
        plugin_data: dict,
        responses: dict,
        synthesized: str,
        responder_id: Optional[str],
        route_name: str,
        channel: str,
        action_taken: str,
        t_classify: int,
        t_route: int,
        t_plugin: int,
        t_synthesize: int,
    ) -> None:
        """Single post-LLM seam: memory, checkpoint, logs, learning and trace."""
        await self.memory.add_turn(self.session_id, "assistant", synthesized, agent_id=responder_id)
        await self._maybe_checkpoint()
        await asyncio.to_thread(self._log_session, text, intent, responses, synthesized)
        await asyncio.to_thread(
            self._record_interactions, text, responses, synthesized, route_name, channel
        )
        event = SecurityEvent(
            event_type=SecurityEventType.LLM_CALL,
            timestamp=time.time(),
            findings=[],
            content_preview=synthesized[:100],
            action_taken=action_taken,
        )
        await asyncio.to_thread(self.audit.log, event)
        self._nudge_persona_after_turn(responder_id, synthesized)
        await self._record_living_memory_after_turn(
            user_text=text,
            assistant_text=synthesized,
            responder_id=responder_id,
            channel=channel,
        )
        self._update_cognition(
            text, intent, plugin_data, synthesized,
            t_classify, t_route, t_plugin, t_synthesize,
        )
        # H20 learning loop: fire-and-forget per-turn review (default-off, gated
        # inside — cognition.review_enabled + cadence/daily budget). Never blocks
        # the turn; never raises into the seam.
        self._spawn_background_review(text, synthesized, channel)

    def _agent_call_timeout(self) -> float:
        """CDX-6: the per-agent LLM-call ceiling, in seconds.

        Was a hard-coded ``120.0`` shared invisibly across chat / deep-research /
        autonomy / eval; now a visible ``agents.agent_timeout_seconds`` setting,
        clamped to ≥1s and falling back to 120 on a non-numeric value so a bad
        config can never disable the timeout entirely.
        """
        try:
            return max(1.0, float(self.get_setting("agents.agent_timeout_seconds", 120)))
        except (TypeError, ValueError):
            return 120.0

    def _compression_summarizer(self):
        """Strict-local LLM summarizer for context compression, or ``None``.

        Only built when ``memory.compression_summarizer`` is on (default OFF).
        Mirrors the H20 background-review rail: the summarizer reads raw
        conversation content, so it uses ``LLMRouter.local_backend`` ONLY —
        the fail-closed accessor that never falls through to a cloud backend.
        No local backend ⇒ the call raises inside the compressor, which
        degrades to its deterministic offline digest. Never cloud, never raises
        into the turn.
        """
        router = getattr(self, "llm_router", None)
        if router is None:
            return None

        async def _summarize(prompt: str) -> str:
            from .llm.model_config import DEFAULT_LOCAL_MODEL
            backend = router.local_backend      # strict-local; raises if none
            model = router.active_model or DEFAULT_LOCAL_MODEL
            max_tokens = int(self.get_setting(
                "memory.compression_summary_max_tokens", 256) or 256)
            return await backend.generate(
                model=model, prompt=prompt,
                system="You compress conversation context. Output only the summary.",
                max_tokens=max_tokens, temperature=0.2)

        return _summarize

    async def _history_for_prompt(self, last_n: int) -> str:
        """Conversation history for a prompt, optionally token-budget compressed.

        Default (``memory.context_compression`` off): byte-identical to
        ``memory.get_context`` — the flag guards the whole path. When on, the
        raw turns go through ``ContextCompressor``: within budget it keeps
        every turn verbatim; over budget the older turns collapse into a
        summary (H20.3). By default ``summarizer`` is ``None`` — zero
        LLM/egress, deterministic digest, safe even for LOCAL_ONLY agents.

        Hermes Phase 2 (all opt-in): ``memory.compression_summarizer`` swaps
        in a STRICT-LOCAL LLM summarizer with hermes's structured template and
        an iterative per-session summary-merge (only unseen turns are re-read);
        ``memory.compression_keep_first`` protects the leading N turns verbatim
        so the session's original ask survives eviction. Output stays formatted
        like ``get_context`` (``[speaker]: content`` lines) so prompt assembly
        downstream is unchanged.
        """
        if not self.get_setting("memory.context_compression", False):
            return await self.memory.get_context(self.session_id, last_n=last_n)
        turns = await self.memory.get_history(self.session_id, last_n)
        if not turns:
            return ""
        from .context_compressor import ContextCompressor
        summarizer = None
        if self.get_setting("memory.compression_summarizer", False):
            summarizer = self._compression_summarizer()
        compressor = ContextCompressor(
            summarizer=summarizer,
            max_tokens=int(self.get_setting("memory.compression_max_tokens", 2000)),
            keep_first=int(self.get_setting("memory.compression_keep_first", 0) or 0),
            structured=summarizer is not None,
        )
        cache = getattr(self, "_ctx_summary_cache", None)
        if cache is None:
            cache = self._ctx_summary_cache = {}
        prior = cache.get(self.session_id) if summarizer is not None else None
        result = await compressor.compress(turns, prior=prior)
        if summarizer is not None and result["compressed"]:
            # Iterative merge state (bounded: one entry per live session key).
            cache[self.session_id] = {"summary": result["summary"],
                                      "covered": result["covered"]}
        def _fmt(ts):
            return [f"[{t.get('agent_id') or t.get('role', '')}]: {t.get('content', '')}"
                    for t in ts]

        if result["compressed"] and result["summary"]:
            return "\n".join(_fmt(result.get("kept_first", []))
                             + [result["summary"]] + _fmt(result["kept"]))
        return "\n".join(_fmt(result["kept"]))

    @staticmethod
    def _split_prompt_history(history_text: str) -> tuple[str, ...]:
        """Split rendered memory at real ``[speaker]:`` entry boundaries.

        Conversation memory is newline-delimited, not ``---``-delimited, and a
        turn body may itself contain newlines. Anchoring at the rendered speaker
        prefix keeps multiline bodies together while allowing a compression
        summary prefix to remain its own stable cache part.
        """
        chunks = re.split(r"(?m)(?=^\[[^\]\r\n]+\]: )", history_text)
        parts: list[str] = []
        for chunk in chunks:
            if chunk.endswith("\r\n"):
                chunk = chunk[:-2]
            elif chunk.endswith("\n"):
                chunk = chunk[:-1]
            if chunk.strip():
                parts.append(chunk)
        return tuple(parts)

    async def _history_for_prompt_parts(
        self,
        last_n: int,
        current_user_text: str | None = None,
    ) -> tuple[str, tuple[str, ...]]:
        """Return prior rendered history plus stable cache-boundary parts.

        ``_handle_input_stream`` persists the current user turn before reading
        memory. Remove only that exact final rendered entry so the prompt and
        cache contain prior context while the current request is appended once.
        """
        history_text = await self._history_for_prompt(last_n)
        if current_user_text is not None:
            current_entry = f"[user]: {current_user_text}"
            if history_text == current_entry:
                history_text = ""
            else:
                suffix = f"\n{current_entry}"
                if history_text.endswith(suffix):
                    history_text = history_text[: -len(suffix)]
        return history_text, self._split_prompt_history(history_text)

    async def _call_agents_parallel(
        self, agent_ids: list[str], text: str, context: dict, plugin_data: dict = None
    ) -> dict[str, str]:
        # CDX-3: honor memory.context_window like the main per-agent path (:850);
        # was a hard-coded 6, so changing the setting silently left this tail behind.
        history = await self._history_for_prompt(
            self.get_setting("memory.context_window", 6))
        plugin_block = self._format_plugin_data(plugin_data or {})
        recall_block = await self._recall_block(text)
        agent_timeout = self._agent_call_timeout()  # CDX-6: tunable, not a hard-coded 120s
        runtime_block = self._runtime_state_block() + self._language_block() + self._data_grounding_block(plugin_data or {})

        async def _run_agent(agent_id: str) -> tuple[str, str, float]:
            enriched_text = await self._build_agent_turn_text(
                agent_id,
                text,
                history=history,
                plugin_block=plugin_block,
                recall_block=recall_block,
                runtime_block=runtime_block,
            )
            try:
                resp = await asyncio.wait_for(
                    self.agents[agent_id].process(enriched_text, context),
                    timeout=agent_timeout,
                )
                return agent_id, resp, self.agents[agent_id].last_latency
            except asyncio.TimeoutError:
                self.agents[agent_id]._record_failure("timeout")
                log_error(logger, E_LLM_TIMEOUT, timeout=int(agent_timeout))
                return agent_id, f"[{agent_id} timeout]", 0.0
            except Exception as e:
                self.agents[agent_id]._record_failure(str(e))
                log_error(logger, E_INTERNAL_UNEXPECTED, component=f"agent:{agent_id}", detail=str(e))
                # First-run UX: "no model loaded" is the single most common failure,
                # and a raw "[jarvis error: No LLM backend available]" tells the user
                # nothing. Return one friendly, actionable line instead — on every
                # channel (web/telegram/discord/CLI), not just the HUD.
                if "No LLM backend available" in str(e):
                    return agent_id, (
                        "No language model is loaded yet. Start LM Studio (or Ollama) "
                        "and load a model, then try again — or enable DEMO mode in the "
                        "HUD to preview the interface."
                    ), 0.0
                return agent_id, f"[{agent_id} error: {e}]", 0.0

        valid_ids = [aid for aid in agent_ids if aid in self.agents]
        for aid in agent_ids:
            if aid not in self.agents:
                logger.warning(f"Agent {aid} not loaded")

        coros = [_run_agent(aid) for aid in valid_ids]
        results_list = await asyncio.gather(*coros)

        results = {}
        self._last_latencies = {}
        # Per-agent routes, alongside the per-agent latencies that already live here.
        # Before this, ONE route_name was computed from target_agents[0] and recorded for
        # every agent that answered — so a turn where stark answered locally and athena
        # answered on cloud was recorded as two local runs, and
        # GET /api/metrics/north-star reported 100% local. `local_pct` gates a 50% floor
        # on the release, and docs/METRICS.md defines it as "% served on-device", so the
        # error was both systematic and in the flattering direction.
        # The streaming path was never affected: it selects the backend inside its own
        # per-agent loop. This is the non-streaming half (Telegram, Discord, voice,
        # /chat, MCP, rooms, webhooks, eval, workflows).
        self._last_routes = {}
        for agent_id, resp, latency in results_list:
            results[agent_id] = resp
            self._last_latencies[agent_id] = latency
            route = self._route_for_agent(agent_id, text)
            if route:
                self._last_routes[agent_id] = route
        return results

    def _route_for_agent(self, agent_id: str, text: str) -> str:
        """The route this agent's backend actually resolved to, or "" if unknowable.

        Asks the router the same question the agent's own generation asked. Returning ""
        rather than guessing matters: ``RunHistory.locality`` excludes unrouted rows from
        the percentage instead of counting them as local, so an honest blank keeps the
        meter from fabricating a split — which is the behaviour this fix is protecting.
        """
        router = getattr(self, "llm_router", None)
        if router is None:
            return ""
        try:
            res = router.select_backend(agent_id, text)
        except Exception:
            return ""
        if isinstance(res, tuple) and len(res) == 3:
            return res[2] or ""
        return ""

    async def _synthesize(self, responses: dict[str, str], intent) -> str:
        jarvis = self.agents.get("jarvis")
        if not jarvis:
            parts = []
            for agent_id, resp in responses.items():
                if agent_id != "jarvis" and resp:
                    parts.append(f"[{agent_id}]: {resp}")
            return "\n".join(parts) if parts else responses.get("jarvis", "")
        # H21.1: preserve specialist voices when the honesty module is active.
        cog = getattr(self, "cognition", None)
        in_character = bool(cog is not None and cog.sub_enabled("honesty_enabled"))
        return await jarvis.synthesize(responses, intent, in_character=in_character)

    async def run_heartbeat(self, agent_id: str) -> Optional[str]:
        # 0.62: a system profile with background_autonomy=False (gaming/multimedia)
        # pauses proactive agent heartbeats to free local resources. The default
        # 'balanced' profile keeps it True, so this is a no-op unless the owner
        # selects a quieter profile via JARVIS_SYSTEM_PROFILE.
        from .system_profiles import active_posture
        if not active_posture().get("background_autonomy", True):
            return None
        agent = self.agents.get(agent_id)
        if agent and agent.has_heartbeat:
            if agent._heartbeat_config is None:
                agent._heartbeat_config = self.heartbeat_scheduler._heartbeat_configs.get(agent_id, {})
            return await agent.run_heartbeat(orchestrator=self)
        return None

    def promote_bench_agent(self, bench_id: str) -> bool:
        """Instantiate and register a bench agent as active + routable.

        Returns True if promotion happened, False if already active (idempotent).
        If the agent has no SOUL.md a minimal stub is written so Agent loads cleanly.
        """
        # BUG-9 hardening: bench_id becomes a filesystem path (agents/<id>/SOUL.md),
        # so reject anything but a plain identifier — a "../" id must never escape agents/.
        if not bench_id or not bench_id.replace("_", "").replace("-", "").isalnum():
            logger.warning(f"promote_bench_agent: rejected invalid bench_id {bench_id!r}")
            return False
        if bench_id in self.agents:
            logger.debug(f"promote_bench_agent: {bench_id} already active — no-op")
            return False

        bench_entry = self.config.bench.get(bench_id)
        if not bench_entry or not isinstance(bench_entry, dict):
            logger.warning(f"promote_bench_agent: {bench_id} not found in bench config")
            return False

        archetype = bench_entry.get("archetype", "Specialist")
        name = bench_entry.get("name", bench_id.capitalize())

        # Ensure SOUL.md exists so Agent._load_soul() doesn't just warn.
        soul_dir = Path(f"agents/{bench_id}")
        soul_path = soul_dir / "SOUL.md"
        if not soul_path.exists():
            soul_dir.mkdir(parents=True, exist_ok=True)
            stub = (
                f"# {name}\n"
                f"> {archetype} — auto-promoted bench agent.\n\n"
                f"## Identity\n"
                f"{name} is a specialist agent promoted from the bench because "
                f"demand crossed its activation threshold.\n\n"
                f"## Mission\n"
                f"Serve as the dedicated {archetype} for Andrei.\n\n"
                f"## Voice & Tone\n"
                f"**Register:** formal-conversational\n"
                f"**Language:** English / Romanian as appropriate\n"
            )
            soul_path.write_text(stub, encoding="utf-8")
            logger.info(f"promote_bench_agent: wrote stub SOUL.md for {bench_id}")

        agent_dict = {
            "name": name,
            "model": "google/gemma-4-31b-a4b",
            "heartbeat": False,
            "channel": "web-dashboard",
            "plugins": [],
            "tier": "foundation",
        }
        agent = Agent(bench_id, agent_dict, self.llm_router, permission_gate=self.permission_gate)
        # Propagate guardrails if available (same pattern as load_agents).
        agent.guardrails = self.security  # may be None — Agent checks truthiness
        # Bench agents are loaded after autonomy wiring; inherit the same governed
        # default-off runtime as agents that were present at boot.
        agent.tool_runtime = getattr(self, "agent_tool_runtime", None)

        self.agents[bench_id] = agent

        # Register in router so the agent is wake-word routable.
        if bench_id not in self.router.ROUTING_TABLE:
            self.router.ROUTING_TABLE[bench_id] = [bench_id]
            logger.info(f"promote_bench_agent: added {bench_id} to ROUTING_TABLE")

        logger.info(f"promote_bench_agent: {bench_id} ({name}) is now active")
        return True

    def _record_interactions(self, text: str, responses: dict, synthesized: str, route_name: str = "", channel: str = "web"):
        # H8.1b: index named entities from the user's turn (best-effort, offline).
        if getattr(self, "entities", None) is not None and text:
            try:
                self.entities.ingest_text(text, source="conversation")
            except Exception:
                logger.debug("entity ingest skipped", exc_info=True)
        # H12.6: incrementally extract triples into the KG (same-session memory).
        if getattr(self, "kg_updater", None) is not None and text:
            try:
                self.kg_updater.ingest(text, source="conversation")
            except Exception:
                logger.debug("incremental KG ingest skipped", exc_info=True)
        for agent_id, resp in responses.items():
            if agent_id in self.agents and resp:
                # Match the exact structured markers _call_agents_parallel emits:
                #   error   → f"[{agent_id} error: {e}]"   (orchestrator.py ~:1641)
                #   timeout → f"[{agent_id} timeout]"      (orchestrator.py ~:1637)
                # A naive "error:" in resp false-positives on any normal answer
                # that merely mentions the word "error:"; anchor to the marker.
                success = not _is_failed_agent_reply(agent_id, resp)
                latency = getattr(self, "_last_latencies", {}).get(agent_id, 0.0)
                # Prefer THIS agent's route over the turn-level scalar, which is computed
                # from target_agents[0] and is only right for the primary responder.
                agent_route = getattr(self, "_last_routes", {}).get(agent_id) or route_name
                metadata = {
                    # CDX-2: record the real origin (web/telegram/discord/voice/
                    # autonomy/…) instead of always "web", so the %-local/cloud
                    # ratio and per-channel analytics aren't silently skewed.
                    "channel": channel,
                    "input_tokens": estimate_tokens(text),
                    "output_tokens": estimate_tokens(resp),
                    "cached_tokens": 0,
                    "cache_hit": False,
                }
                self.learning.record(
                    agent_id=agent_id,
                    task=text[:200],
                    response=resp[:500],
                    success=success,
                    latency=latency,
                    error=resp if not success else None,
                    metadata=metadata,
                    route_name=agent_route,
                )
                self.bench.record(
                    agent_id=agent_id,
                    latency=latency,
                    success=success,
                    output_length=len(resp),
                    model=self.agents[agent_id].config.get("model", ""),
                )
                # H10.17: append to the per-agent run-history timeline.
                if getattr(self, "run_history", None) is not None:
                    try:
                        self.run_history.record(
                            agent_id=agent_id,
                            input_text=text,
                            output_text=resp,
                            latency_ms=latency * 1000,
                            ok=success,
                            route=agent_route,
                        )
                    except Exception:
                        logger.debug("run_history record skipped", exc_info=True)
                if not success and agent_id in self.agents:
                    agent = self.agents[agent_id]
                    if agent.should_demote:
                        target = agent.get_demotion_target()
                        logger.warning(f"Demoting {agent_id} to {target} — {agent._failures} consecutive failures")
                        old_cfg = dict(agent.config)
                        old_cfg["tier"] = target
                        agent.config = old_cfg

        # Auto-promotion: only when learning.auto_promote is ON (default OFF).
        if self.get_setting("learning.auto_promote", False):
            suggestions = self.learning.suggest_promotions(active_ids=set(self.agents.keys()))
            for suggestion in suggestions:
                bench_id = suggestion["bench_agent"]
                promoted = self.promote_bench_agent(bench_id)
                if promoted:
                    logger.info(
                        f"Auto-promoted {bench_id}: {suggestion['reason']}"
                    )

    def _spawn_cache_task(self, coroutine, *, session_id: str) -> None:
        task = asyncio.create_task(coroutine, name=f"gemini-cache:{session_id}")
        cache_tasks = getattr(self, "_cache_tasks", None)
        if cache_tasks is None:
            cache_tasks = self._cache_tasks = set()
        cache_tasks.add(task)
        task.add_done_callback(cache_tasks.discard)
        task.add_done_callback(_log_task_result)

    async def _async_create_cache(
        self,
        session_id: str,
        system_instruction: str,
        history_texts: tuple[str, ...],
        model: str,
        policy_fingerprint: str,
        lease: AuthLease,
    ) -> None:
        if not self.context_cache or not history_texts:
            return
        await self.context_cache.create_or_extend(
            session_id=session_id,
            system_instruction=system_instruction,
            history=history_texts,
            model=model,
            policy_fingerprint=policy_fingerprint,
            lease=lease,
        )

    def _log_session(self, text, intent, responses, synthesized):
        logger.info(f"[{(self.session_id or 'none')[:20]}]: {text[:40]}... -> {synthesized[:40]}...")

    # ── H7.2 / H7.3: checkpoint debounce helpers ────────────────────────────

    async def _maybe_checkpoint(self):
        """H7.3: increment turn counter; only persist every N turns.

        The N threshold is read from the runtime settings (default 5) so it
        can be tuned live without a restart.  Runs the actual SQLite write
        off the event loop via asyncio.to_thread (H7.2).
        """
        self._turns_since_checkpoint += 1
        every = int(self.get_setting("memory.checkpoint_every", 5) or 5)
        if self._turns_since_checkpoint >= every:
            await asyncio.to_thread(self.checkpoints.save, self)
            self._turns_since_checkpoint = 0

    async def _flush_checkpoint(self):
        """Force an immediate checkpoint save and reset the turn counter.

        Called on session boundaries so no active session state is lost.
        """
        await asyncio.to_thread(self.checkpoints.save, self)
        self._turns_since_checkpoint = 0

    async def new_session(self) -> str:
        """Wrapper around memory.new_session() that flushes the checkpoint first
        so the outgoing session is not lost before we switch context.
        """
        await self._flush_checkpoint()
        sid = await self.memory.new_session()
        self.session_id = sid
        return sid

    async def aclose(self):
        """Graceful shutdown: flush checkpoint + close LLM/MCP/queue pools (BUG-7 / NEW-1).

        Defensive throughout — every step is guarded so a failure in one does
        not abort the rest, and shutdown never raises.
        """
        await self._flush_checkpoint()
        cache_tasks = getattr(self, "_cache_tasks", None)
        if cache_tasks:
            pending_cache_tasks = tuple(cache_tasks)
            for task in pending_cache_tasks:
                task.cancel()
            await asyncio.gather(*pending_cache_tasks, return_exceptions=True)
            cache_tasks.clear()
        router = getattr(self, "llm_router", None)
        if router is not None:
            try:
                await router.aclose()
            except Exception as e:
                logger.warning(f"Error closing LLM router: {e}")
        # Close MCP sessions (httpx/stdio transports) if any are open.
        mcp = getattr(self, "mcp", None)
        close_all = getattr(mcp, "close_all", None)
        if close_all is not None:
            try:
                await close_all()
            except Exception as e:
                logger.warning(f"Error closing MCP sessions: {e}")
        # Close the autonomy sqlite queue connection.
        queue = getattr(self, "autonomy_queue", None)
        queue_close = getattr(queue, "close", None)
        if queue_close is not None:
            try:
                queue_close()
            except Exception as e:
                logger.warning(f"Error closing autonomy queue: {e}")
        # AUD-18: close the Gemini context-cache httpx client (created only when a
        # Gemini key is set — leaked its pool on shutdown otherwise).
        cache = getattr(self, "context_cache", None)
        cache_close = getattr(cache, "close", None)
        if cache_close is not None:
            try:
                await cache_close()
            except Exception as e:
                logger.warning(f"Error closing context cache: {e}")
        # AUD-18: drain the pooled per-plugin HTTP clients (PluginHTTPClient registry).
        try:
            from . import http_client as _http_client
            await _http_client.close_all()
        except Exception as e:
            logger.warning(f"Error closing plugin HTTP clients: {e}")
        # AUD-18: close channel transports that hold a long-lived client (e.g. the
        # Telegram httpx client). Only the async `aclose` convention is honored;
        # best-effort so one channel can't abort the rest of shutdown.
        for cid, ch in list(getattr(self, "channels", {}).items()):
            closer = getattr(ch, "aclose", None)
            if closer is None:
                continue
            try:
                await closer()
            except Exception as e:
                logger.warning(f"Error closing channel '{cid}': {e}")

    async def get_status(self) -> dict:
        return {
            "llm_backend": self.llm_router.name,
            "agents": list(self.agents.keys()),
            "session": self.session_id,
            "memory": await self.memory.get_session_stats(),
            "skills": list(self.skills.skills.keys()),
            "checkpoint": self.checkpoints.info(),
            "learning": self.learning.get_stats(active_ids=set(self.agents.keys())),
            "bench": self.bench.get_summary(),
            "security": self.security is not None,
            "sandbox_available": self.sandbox._has_docker,
        }
