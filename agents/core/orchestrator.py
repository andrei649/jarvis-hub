"""
orchestrator.py — Main orchestration loop for Jarvis Beta.
Integrates: intent routing, LLM backend, memory, live plugins, streaming, voice, channels,
skills system, checkpointing, agent handoff, promotion/demotion.
"""

import asyncio
import contextvars
import logging
import importlib
import os
import re
import time
from pathlib import Path
from typing import Callable, Optional

from dotenv import load_dotenv

from .agent import Agent
from .router import IntentRouter
from .config import JarvisConfig
from .llm.hybrid_router import HybridRouter
from .llm.gemini_cache import ContextCache
from .llm.tokenizer import estimate_tokens
from .memory.manager import MemoryManager
from .checkpoint import CheckpointManager
from .heartbeat import HeartbeatScheduler
from .learning.loop import LearningLoop
from .skills.loader import SkillLoader
from .skills.importer import SkillImporter
from .skills.marketplace import SkillMarketplace
from .mcp.client import MCPManager
from .autonomy import AutonomyWorker, TaskQueue, AutonomyPolicy, PreferenceStore, TaskExecutor
from .autonomy import ProactiveObserver, default_probes
from .autonomy.inbox import build_decision_card
from .autonomy.digest import build_morning_brief, build_evening_retro
from .autonomy.worker import is_night_window
from .autonomy.reflection import DailyReflector
from .autonomy.log_scanner import LogBugScanner
from .workflows import WorkflowEngine, WorkflowRegistry
from .sandbox import Sandbox
from .bench import LatencyBenchmark
from .plugin_gate import PermissionGate
from .security.guardrails import GuardrailsEngine
from .security.audit import AuditLogger
from .security.types import RedactionMode, SecurityEvent, SecurityEventType, ThreatLevel
from .log import log_error
from .errors import (
    E_CONFIG_MISSING_ENV, E_PLUGIN_BLOCKED, E_LLM_BACKEND_MISSING, E_LLM_TIMEOUT,
    E_INTERNAL_UNEXPECTED, E_CHANNEL_START_FAIL,
)
from .channels.base import ChannelAdapter
from .channels.web import WebChannel
from .channels.voice import VoiceChannel
from .channels.telegram import TelegramChannel
from .channels.discord import DiscordChannel
from .channels.email import EmailChannel
from .channels.slack import SlackChannel
from .settings_db import get_all as _get_settings, get_category as _get_settings_category
from .plugins.oauth import init_from_env as _oauth_init, load_token as _load_token
from .plugins.weather import WeatherPlugin
from .plugins.news import NewsPlugin
from .plugins.cloud_llm import CloudLLMPlugin
from .plugins.telegram_bot import TelegramBotPlugin
from .plugins.gmail_plugin import GmailPlugin
from .plugins.whatsapp_bridge import WhatsAppBridgePlugin
from .plugins.spotify_plugin import SpotifyPlugin
from .plugins.google_calendar import GoogleCalendarPlugin
from .plugins.apple_health import AppleHealthPlugin
from .plugins.websearch import WebSearchPlugin
from .plugins.homebridge import HomebridgePlugin
from .plugins.balance import BalanceReaderPlugin
from .plugins.analytics import AnalyticsPlugin
from .plugins.oracle_bridge import OracleBridgePlugin
from .plugins.n8n import N8NPlugin
from .plugins.sms_alerts import SMSAlertsPlugin
from .plugins.crm_sync import CRMSyncPlugin
from .plugins.iot_control import IoTControlPlugin
from .plugins.worldview import WorldViewPlugin

logger = logging.getLogger("jarvis.orchestrator")


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


# ── Natural-language LLM-backend control (start / load / unload / status) ─────
# Lets a chat message drive LMStudioController. Deliberately conservative: a
# load needs a *plausible* model token, so ordinary phrases like "load up our
# friends and test them" never trigger a model load. Status questions that slip
# through still get answered truthfully by the normal chat path (the runtime
# state block injects the real model), so missing one here is harmless.

_LLM_PREFIX_RE = re.compile(r"^\s*(?:llm|lm[\s\-]?studio)\b[:\s]+(.+)$", re.IGNORECASE)
_MODEL_FAMILY_RE = re.compile(
    r"(gemma|qwen|deepseek|llama|mistral|mixtral|phi|gpt|granite|nemotron|smol|yi|command-?r|qwq)",
    re.IGNORECASE,
)
_LOAD_VERB_RE = re.compile(r"\b(load|reload|încarc|incarc|switch|schimb)\w*\b", re.IGNORECASE)
_START_RE = re.compile(r"\b(start|launch|boot|pornes\w*|porneșt\w*)\b", re.IGNORECASE)
_UNLOAD_RE = re.compile(r"\b(unload|descarc)\w*\b", re.IGNORECASE)
_LLM_NOUN_RE = re.compile(r"\b(lm[\s\-]?studio|llm|language model|model|brain|creier|server)\b", re.IGNORECASE)
_START_TARGET_RE = re.compile(r"\b(lm[\s\-]?studio|llm|language (?:model|server)|the server)\b", re.IGNORECASE)
_STATUS_RE = re.compile(
    r"\bwhat are you running\b"
    r"|\b(?:what|which|ce)\b[^?.!]{0,40}\b(?:llm|lm[\s\-]?studio|language model|ai model|brain|creier)\b"
    r"|\b(?:what|which|ce)\b[^?.!]{0,30}\bmodel\b[^?.!]{0,30}\b(?:you|run|running|loaded|using|use|rulez\w*|folos\w*|încărc\w*|incarc\w*|activ)\b"
    r"|\bmodel\b[^?.!]{0,20}\b(?:loaded|running|active|încărcat|incarcat)\b",
    re.IGNORECASE,
)
_MODEL_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/:@\-]{1,199}")
_MODEL_STOPWORDS = {
    "the", "a", "an", "model", "models", "modelul", "modele", "up", "please", "sir",
    "to", "into", "my", "our", "your", "new", "llm", "lm", "studio", "lmstudio",
    "load", "reload", "unload", "switch", "use", "start", "server", "and", "test",
    "them", "on", "with", "running", "loaded", "active", "now", "current", "default",
}


def _is_plausible_model(tok: str) -> bool:
    """A model id either looks structured (digit / path / quant) or names a known family."""
    return bool(re.search(r"[0-9/:@]", tok) or _MODEL_FAMILY_RE.search(tok))


def _extract_model(s: str) -> Optional[str]:
    for tok in _MODEL_TOKEN_RE.findall(s or ""):
        if tok.lower() in _MODEL_STOPWORDS:
            continue
        if _is_plausible_model(tok):
            return tok
    return None


def _env_flag(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off", "disable", "disabled")


def _as_bool(value, default: bool = True) -> bool:
    """Coerce a runtime-settings value (bool / int / "true" / "off" / ...) to bool."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() not in ("0", "false", "no", "off", "disable", "disabled", "")


def detect_llm_control(text: str) -> Optional[tuple[str, Optional[str]]]:
    """Detect a chat request to control the LLM backend.

    Returns (action, model) where action ∈ {status, start, load, unload} and
    model is an optional id, or None if the message is not LLM control.
    """
    if not text or not text.strip():
        return None
    t = text.strip()

    # Explicit "llm <sub> [args]" / "lm studio <sub>" command form.
    m = _LLM_PREFIX_RE.match(t)
    if m:
        rest = m.group(1).strip()
        sub, _, arg = rest.partition(" ")
        sub = sub.lower()
        if sub in ("status", "state", "ps", "info"):
            return ("status", None)
        if sub in ("start", "up", "boot", "launch"):
            return ("start", None)
        if sub in ("unload", "stop"):
            return ("unload", _extract_model(arg))
        if sub in ("load", "use", "switch"):
            return ("load", _extract_model(arg))
        # Unknown sub-command: only act if it names a model ("llm gemma"),
        # otherwise let normal chat handle it (avoids "lm studio is great").
        model = _extract_model(rest)
        return ("load", model) if model else None

    low = t.lower()

    if _UNLOAD_RE.search(low):
        model = _extract_model(low)
        if model or _LLM_NOUN_RE.search(low):
            return ("unload", model)

    if _START_RE.search(low) and _START_TARGET_RE.search(low):
        return ("start", None)

    if _LOAD_VERB_RE.search(low):
        model = _extract_model(low)
        if model and (_LLM_NOUN_RE.search(low) or _is_plausible_model(model)):
            return ("load", model)

    if _STATUS_RE.search(low):
        return ("status", None)

    return None





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
        self.context_cache = ContextCache(api_key=gemini_key) if gemini_key else None
        self.memory = MemoryManager()

        # ── optional components via the registry (A2: tames the god-object) ──
        from .component_registry import ComponentRegistry
        self.components = ComponentRegistry(self, logger)
        reg = self.components

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
            self.cognition.register_module("memory", LivingMemory())
            from .cognition.learning import LearningModule                                        # H21.4
            self.cognition.register_module("learning", LearningModule())
            from .cognition.ensemble import EnsembleModule                                        # H21.5
            self.cognition.register_module("ensemble", EnsembleModule())
        # ── end optional components ──
        self.plugins: dict = {}
        self.skills = SkillLoader()
        self.skill_importer = SkillImporter()
        self.marketplace = SkillMarketplace()
        self.mcp = MCPManager()
        self.channels: dict[str, ChannelAdapter] = {}
        self.checkpoints = CheckpointManager()
        self.learning = LearningLoop()
        rules = config.get_promotion_rules() if hasattr(config, "get_promotion_rules") else None
        if rules:
            self.learning.set_promotion_rules(rules)
        self.bench = LatencyBenchmark()
        self.sandbox = Sandbox()
        self.heartbeat_scheduler = HeartbeatScheduler(agents_dir=str(Path(__file__).resolve().parent.parent.parent / "agents"))
        self.security: Optional[GuardrailsEngine] = None
        self.permission_gate = PermissionGate()
        self.audit = AuditLogger()
        # LM Studio lifecycle control (start server / load / unload). Shares the
        # live router so a model change refreshes routing + reported state.
        from .llm.lmstudio_control import LMStudioController
        # enabled is re-synced from live settings in load_runtime_settings(); the
        # env var is the boot-time default and a hard kill-switch (see docs).
        self.lmstudio = LMStudioController(
            router=self.llm_router,
            enabled=_env_flag("JARVIS_LMSTUDIO_CONTROL", True),
        )
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
        self.autonomy = AutonomyWorker(
            self.autonomy_queue, policy=AutonomyPolicy(), prefs=self.autonomy_prefs,
        )
        # Proactive OS Observer — the trigger layer that feeds the queue.
        self.observer: Optional[ProactiveObserver] = None
        # Proactive Event Watcher — personal event trigger layer.
        self.event_watcher = None
        self._autonomy_task: Optional[asyncio.Task] = None
        self.last_cognition = None
        # Daily Reflection & Graph Consolidation (H5.15)
        self.reflector: Optional[DailyReflector] = None
        # Log-bug-finding scanner (multi-cadence scheduled pipeline)
        self.log_scanner = LogBugScanner()
        # Multi-Agent Workflows (H5.6)
        self.workflow_registry = WorkflowRegistry()
        self.workflow_engine: Optional[WorkflowEngine] = None
        # Continuous Ingestion Watcher (H5.1)
        self.ingestion_watcher = None
        # H7.3: debounce checkpoint — counts turns since last full save
        self._turns_since_checkpoint: int = 0
        # H9.2: trace explorer — in-memory ring buffer
        try:
            from .observability.tracer import Tracer
            self.tracer = Tracer(maxlen=500)
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

    async def load_agents(self):
        await self.llm_router.detect()
        logger.info(f"LLM backend: {self.llm_router.name}")

        try:
            backend = self.llm_router.backend
            self.security = GuardrailsEngine(
                backend=backend,
                mode=RedactionMode.WARN,
                scan_input=True,
                scan_output=True,
            )
            logger.info("Security guardrails enabled")
        except RuntimeError:
            log_error(logger, E_LLM_BACKEND_MISSING, backend="guardrails")
            self.security = None

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
                if self.security:
                    agent.guardrails = self.security
                self.agents[agent_id] = agent
                logger.info(f"Loaded: {agent_id}")

        self.plugins["weather"] = WeatherPlugin()
        self.plugins["news"] = NewsPlugin()
        env_path = Path(__file__).resolve().parent.parent.parent / ".env"
        load_dotenv(env_path)
        self.plugins["cloud-llm"] = CloudLLMPlugin(
            anthropic_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            openai_key=os.environ.get("OPENAI_API_KEY", ""),
            gemini_key=os.environ.get("GEMINI_API_KEY", ""),
        )
        self.plugins["telegram"] = TelegramBotPlugin(
            token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        )
        _oauth_init()
        _gmail_token = os.environ.get("GMAIL_ACCESS_TOKEN", "") or (_load_token("google") or {}).get("access_token", "")
        self.plugins["gmail"] = GmailPlugin(
            access_token=_gmail_token,
        )
        self.plugins["whatsapp"] = WhatsAppBridgePlugin(
            bridge_url=os.environ.get("WHATSAPP_BRIDGE_URL", "http://192.168.1.100:3000"),
        )
        _spotify_token = os.environ.get("SPOTIFY_ACCESS_TOKEN", "") or (_load_token("spotify") or {}).get("access_token", "")
        _spotify_refresh = os.environ.get("SPOTIFY_REFRESH_TOKEN", "") or (_load_token("spotify") or {}).get("refresh_token", "")
        self.plugins["spotify"] = SpotifyPlugin(
            client_id=os.environ.get("SPOTIFY_CLIENT_ID", ""),
            client_secret=os.environ.get("SPOTIFY_CLIENT_SECRET", ""),
            access_token=_spotify_token,
            refresh_token=_spotify_refresh,
        )
        _cal_token = os.environ.get("GOOGLE_CALENDAR_TOKEN", "") or (_load_token("google") or {}).get("access_token", "")
        self.plugins["google-calendar"] = GoogleCalendarPlugin(
            access_token=_cal_token,
        )
        self.plugins["apple-health"] = AppleHealthPlugin(
            bridge_url=os.environ.get("APPLE_HEALTH_BRIDGE_URL", "http://192.168.1.100:8081"),
        )
        self.plugins["homebridge"] = HomebridgePlugin(
            bridge_url=os.environ.get("HOMEBRIDGE_URL", "http://192.168.1.100:8581"),
            api_token=os.environ.get("HOMEBRIDGE_TOKEN", ""),
        )
        self.plugins["websearch"] = WebSearchPlugin(
            tavily_api_key=os.environ.get("TAVILY_API_KEY", ""),
            searxng_url=os.environ.get("SEARXNG_URL", ""),
        )

        self.plugins["balance"] = BalanceReaderPlugin(
            ing_client_id=self.get_setting("plugins.gecko_ing_client_id", ""),
            ing_client_secret=self.get_setting("plugins.gecko_ing_client_secret", ""),
            libra_token=self.get_setting("plugins.gecko_libra_token", ""),
            csv_path=self.get_setting("plugins.gecko_csv_path", ""),
        )
        self.plugins["analytics"] = AnalyticsPlugin(
            ga4_service_account=self.get_setting("plugins.stark_ga4_service_account", ""),
            ga4_property_id=self.get_setting("plugins.stark_ga4_property_id", ""),
        )

        self.plugins["oracle-bridge"] = OracleBridgePlugin(
            github_token=os.environ.get("GITHUB_TOKEN", ""),
        )
        self.oracle_bridge = self.plugins["oracle-bridge"]
        self.plugins["n8n"] = N8NPlugin(
            base_url=os.environ.get("N8N_BASE_URL", ""),
            api_key=os.environ.get("N8N_API_KEY", ""),
        )
        self.plugins["sms-alerts"] = SMSAlertsPlugin(
            account_sid=self.get_setting("plugins.twilio_account_sid", ""),
            auth_token=self.get_setting("plugins.twilio_auth_token", ""),
            from_number=self.get_setting("plugins.twilio_from_number", ""),
        )
        self.plugins["crm-sync"] = CRMSyncPlugin(
            integration_token=self.get_setting("plugins.notion_integration_token", ""),
            database_id=self.get_setting("plugins.notion_database_id", ""),
        )
        self.plugins["iot-control"] = IoTControlPlugin(
            client_id=self.get_setting("plugins.tuya_client_id", ""),
            secret=self.get_setting("plugins.tuya_secret", ""),
            device_id=self.get_setting("plugins.tuya_device_id", ""),
        )
        # WorldView 4D OSINT (local-first; override host with WORLDVIEW_API_URL).
        self.plugins["worldview"] = WorldViewPlugin(
            api_url=os.environ.get("WORLDVIEW_API_URL", ""),
        )

        # Autonomy queue — durable self-tasking store (H6.1)
        try:
            self.autonomy_queue.initialize()
            self.autonomy_prefs.initialize()
            self.autonomy.executor = self._build_autonomy_executor().execute
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

            self.reflector = DailyReflector(self.memory, _reflect_llm)

            # Continuous Ingestion Watcher (H5.1)
            from .ingestion.watcher import IngestionWatcher
            self.ingestion_watcher = IngestionWatcher()

            # Multi-agent workflow engine (H5.6)
            self.workflow_engine = WorkflowEngine(self)

            logger.info("Autonomy queue + executor + observer + event_watcher + reflection + workflows initialized")
        except Exception as e:
            logger.warning(f"Autonomy init failed: {e}")

        self.skills.discover()
        logger.info(f"Skills loaded: {list(self.skills.skills.keys())}")

        self.checkpoints.initialize()
        restored = self.checkpoints.restore(self)
        if restored:
            logger.info(f"Restored from checkpoint — session: {self.session_id}")

        if not self.session_id:
            self.session_id = self.memory.conversation.current_session_id or await self.memory.new_session()
            logger.info(f"Session: {self.session_id}")

        self.load_runtime_settings()
        self.heartbeat_scheduler.load_all()
        self.heartbeat_scheduler.load_from_config(self.config)

        for agent_id, hb_config in self.heartbeat_scheduler._heartbeat_configs.items():
            if agent_id in self.agents:
                self.agents[agent_id]._heartbeat_config = hb_config

    def load_runtime_settings(self):
        try:
            all_s = _get_settings()
            flat = {}
            for cat, items in all_s.items():
                for item in items:
                    flat[f"{cat}.{item['key']}"] = item["value"]
            self._runtime_settings = flat
            logger.debug(f"Runtime settings loaded: {len(flat)} keys")
            # Propagate the live kill-switch to the controller (≤30s to take
            # effect via the settings watcher) — no restart needed to disable.
            ctrl = getattr(self, "lmstudio", None)
            if ctrl is not None:
                ctrl.set_enabled(self._control_master_enabled())
        except Exception as e:
            log_error(logger, E_INTERNAL_UNEXPECTED, component="settings_db", detail=str(e))

    def get_setting(self, key: str, default=None):
        return self._runtime_settings.get(key, default)

    async def _settings_watcher_loop(self):
        while True:
            await asyncio.sleep(30)
            self.load_runtime_settings()

    # ── Autonomy / Proactive Cortex (H6.1–H6.3) ────────────────────
    def _wire_autonomy(self):
        """Wire the decision inbox to Telegram if a bot + owner chat are set."""
        owner = os.environ.get("AUTONOMY_OWNER_CHAT_ID", "") or str(
            self.get_setting("autonomy.owner_chat_id", "") or ""
        )
        tg = self.channels.get("telegram")
        if tg and owner and hasattr(tg, "send_card"):
            async def notifier(task):
                return await tg.send_card(int(owner), build_decision_card(task))
            self.autonomy.notifier = notifier
            tg.on_callback = self._on_autonomy_callback
            logger.info("Autonomy decision inbox wired to Telegram")

    async def _on_autonomy_callback(self, task_id: int, action: str, **kwargs):
        """Handle a decision-inbox button tap from Telegram."""
        try:
            await self.autonomy.apply_decision(task_id, action, decided_by="telegram")
            return f"Task #{task_id}: {action}"
        except Exception as e:
            logger.warning(f"Autonomy decision callback failed: {e}")
            return None

    def _schedule_daily_digests(self):
        """Cron the morning brief (07:00) and evening retro (20:00) — H6.4."""
        sched = getattr(self.heartbeat_scheduler, "scheduler", None)
        if sched is None:
            return
        try:
            sched.add_job(self._run_daily_digest, "cron", hour=7, minute=0,
                          args=["morning"], id="autonomy-morning-brief", replace_existing=True)
            sched.add_job(self._run_daily_digest, "cron", hour=20, minute=0,
                          args=["evening"], id="autonomy-evening-retro", replace_existing=True)
            logger.info("Scheduled daily digests: morning 07:00, evening 20:00")
        except Exception as e:
            logger.warning(f"Failed to schedule daily digests: {e}")

    def _schedule_daily_budget_reset(self):
        """Reset the autonomy daily-spend ceiling at local midnight (BUG-10).

        Without this, AutonomyPolicy._spent_today accrues across calendar days
        until a restart, so `daily_ceiling` fills permanently and blocks
        autonomous spend. reset_daily() existed but was never scheduled in prod.
        """
        sched = getattr(self.heartbeat_scheduler, "scheduler", None)
        policy = getattr(getattr(self, "autonomy", None), "policy", None)
        if sched is None or policy is None:
            return
        try:
            sched.add_job(policy.reset_daily, "cron", hour=0, minute=0,
                          id="autonomy-daily-budget-reset", replace_existing=True)
            logger.info("Scheduled daily autonomy-budget reset: 00:00")
        except Exception as e:
            logger.warning(f"Failed to schedule daily budget reset: {e}")

    def _schedule_learning_loop(self):
        """H7.11 — periodically propose agent promotions to the decision inbox.

        Cadence from config (autonomy.learning_loop_interval_hours, default 168h =
        weekly). Each run proposes gated, reversible promotions via the queue.
        """
        sched = getattr(self.heartbeat_scheduler, "scheduler", None)
        if sched is None:
            return
        try:
            hours = float((self.config.get("autonomy", {}) or {}).get(
                "learning_loop_interval_hours", 168))
        except Exception:
            hours = 168.0
        if hours <= 0:
            return
        try:
            sched.add_job(self._run_learning_loop, "interval", hours=hours,
                          id="learning-loop-promotions", replace_existing=True)
            logger.info("Scheduled learning-loop promotions every %sh", hours)
        except Exception as e:
            logger.warning(f"Failed to schedule learning loop: {e}")

    async def _run_learning_loop(self) -> list[dict]:
        """Propose agent promotions into the decision inbox (gated, reversible)."""
        from .learning.scheduler import propose_promotions
        return propose_promotions(self.learning, self.autonomy_queue, list(self.agents.keys()))

    def _schedule_log_scans(self):
        """Register the three log-bug-finding cadences on the APScheduler.

        quick  — every 15 min: spike + new-code detection
        hourly — every hour:   trend analysis + backlog sync
        daily  — 07:05 daily:  full 24-h digest → memory_logs/reports/
        """
        sched = getattr(self.heartbeat_scheduler, "scheduler", None)
        if sched is None:
            return
        try:
            sched.add_job(self._run_log_quick_scan, "interval", seconds=900,
                          id="log-scan-quick", replace_existing=True)
            sched.add_job(self._run_log_hourly_scan, "interval", seconds=3600,
                          id="log-scan-hourly", replace_existing=True)
            sched.add_job(self._run_log_daily_scan, "cron", hour=7, minute=5,
                          id="log-scan-daily", replace_existing=True)
            logger.info("Scheduled log-bug scans: quick/15min, hourly, daily/07:05")
        except Exception as e:
            logger.warning(f"Failed to schedule log scans: {e}")

    async def _run_log_quick_scan(self):
        """15-min scan: submit autonomy alert on spike or new error code."""
        if not self.get_setting("system.log_scan_enabled", True):
            return
        try:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            problems_path = os.path.join(base, "..", "memory_logs", "problems.jsonl")
            result = self.log_scanner.quick_scan(problems_path)
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
            await self.autonomy.submit(
                agent="steve", kind="monitor.log_spike", title=title,
                payload={"risk_tier": 0, "spike": result.spike_detected,
                         "new_codes": result.new_codes,
                         "total_errors": result.total_errors},
                origin="log_scanner",
            )
        except Exception as e:
            logger.warning(f"Log quick scan failed: {e}")

    async def _run_log_hourly_scan(self):
        """Hourly scan: trend analysis and backlog sync."""
        if not self.get_setting("system.log_scan_enabled", True):
            return
        try:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            problems_path = os.path.join(base, "..", "memory_logs", "problems.jsonl")
            result = self.log_scanner.hourly_scan(problems_path)
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
                await self.autonomy.submit(
                    agent="steve", kind="monitor.log_trend", title="Hourly log trend — " + "; ".join(parts),
                    payload={"risk_tier": 0, "spike": result.spike_detected,
                             "new_codes": result.new_codes,
                             "total_errors": result.total_errors},
                    origin="log_scanner",
                )
        except Exception as e:
            logger.warning(f"Log hourly scan failed: {e}")

    async def _run_log_daily_scan(self):
        """07:05 daily scan: write 24-h bug-report digest."""
        if not self.get_setting("system.log_scan_enabled", True):
            return
        try:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            problems_path = os.path.join(base, "..", "memory_logs", "problems.jsonl")
            result = self.log_scanner.daily_scan(problems_path)
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
            await self.autonomy.submit(
                agent="steve", kind="monitor.log_daily", title=title,
                payload={"risk_tier": 0, "total_errors": result.total_errors,
                         "new_codes": result.new_codes, "top_issues": issues_summary,
                         "report_path": result.report_path},
                origin="log_scanner",
            )
        except Exception as e:
            logger.warning(f"Log daily scan failed: {e}")

    async def _autonomy_loop(self):
        """Periodically run approved autonomy tasks (the self-tasking worker).

        During the night window (H6.6) only reversible/read-only work runs, so
        external/irreversible tasks always wait for a waking human.
        """
        from datetime import datetime
        while True:
            interval = int(self.get_setting("system.autonomy_tick", 60) or 60)
            await asyncio.sleep(max(15, interval))
            try:
                # Sync the live autonomy mode (HUD AUTO/ASK/OFF) onto the policy each tick.
                amode = str(self.get_setting("autonomy.mode", "auto") or "auto").lower()
                if self.autonomy and self.autonomy.policy.mode != amode:
                    self.autonomy.policy.mode = amode
                max_tier = None
                if self.get_setting("autonomy.night_shift", False):
                    start = int(self.get_setting("autonomy.night_start", 23) or 23)
                    end = int(self.get_setting("autonomy.night_end", 6) or 6)
                    if is_night_window(datetime.now().hour, start, end):
                        max_tier = 1  # reversible/read-only only
                await self.autonomy.tick(max_tier=max_tier)
                # Proactive passes self-generate new tasks — paused entirely in OFF mode.
                if amode != "off":
                    # Sample the host and turn state changes into gated tasks.
                    if self.observer and self.get_setting("system.observer_enabled", True):
                        await self.observer.observe()
                    # Sample personal events (Antigravity watchers)
                    if self.event_watcher and self.get_setting("system.watchers_enabled", True):
                        await self.event_watcher.observe()
                # Nightly reflection & graph consolidation (H5.15)
                if self.reflector and self.get_setting("system.reflection_enabled", True):
                    if is_night_window(datetime.now().hour, start=22, end=7):
                        await self.reflector.run(enabled=True)
                # Continuous Ingestion Watcher (H5.1)
                if self.ingestion_watcher and self.get_setting("system.ingestion_watcher_enabled", True):
                    await asyncio.to_thread(self.ingestion_watcher.check_and_run)
                # Sync error/problem log to the git-ignored memory_logs/diagnostics.md
                # (never the tracked BACKLOG.md — that caused git conflicts).
                if self.get_setting("system.error_backlog_sync_enabled", True):
                    from .autonomy.error_logger import sync_problems_to_diagnostics
                    sync_problems_to_diagnostics()
            except Exception as e:
                logger.warning(f"Autonomy tick failed: {e}")

    def _build_autonomy_executor(self) -> TaskExecutor:
        """Wire task kinds to real capabilities, degrading gracefully."""
        async def _research(task):
            query = (task.payload or {}).get("query") or task.title
            ws = self.plugins.get("websearch")
            if ws and hasattr(ws, "handle"):
                return {"status": "ok", "kind": "research", "output": await ws.handle(query)}
            return {"status": "noop", "note": "websearch unavailable"}

        async def _llm(task):
            prompt = (task.payload or {}).get("prompt") or task.title
            out = await self.process(prompt, channel="autonomy")
            return {"status": "ok", "kind": task.kind, "output": out}

        executor = TaskExecutor(fallback=_llm)
        for kw in ("research", "search", "monitor", "scan", "lookup", "check"):
            executor.register(kw, _research)
        for kw in ("summarize", "analyze", "review", "draft", "plan", "prepare"):
            executor.register(kw, _llm)

        # Safe system recovery remediation handler (H6 / Antigravity recovery)
        from .autonomy.remediation import RemediationRunner
        runner = RemediationRunner(permission_gate=self.permission_gate, audit=self.audit)

        async def _restart_service(task):
            service = (task.payload or {}).get("service")
            agent = getattr(task, "agent", "steve")
            return await runner.restart(service, agent=agent)

        executor.register("restart_service", _restart_service)

        # H10.30 — governed write-back integrations (Notion/GitHub/Calendar).
        # Approved `writeback.*` tasks resolve credentials at action time (behind
        # approval) and call an injectable client (offline NullWriteBackClient by
        # default; the live HTTP rail is a host-side seam).
        from .writeback import WriteBackBroker
        self.writeback = WriteBackBroker(
            enqueue=self.autonomy_queue.enqueue,
            secret_broker=getattr(self, "secret_broker", None),
            audit=getattr(self, "audit", None),
        )
        executor.register("writeback", self.writeback.execute)

        # H12.21 — governed social actions (X/Twitter post/reply/DM). Same
        # governance: approved `social.*` tasks resolve OAuth/bearer credentials
        # at action time (behind approval) and post via an injectable client.
        from .social import SocialBroker
        self.social = SocialBroker(
            enqueue=self.autonomy_queue.enqueue,
            secret_broker=getattr(self, "secret_broker", None),
            audit=getattr(self, "audit", None),
        )
        executor.register("social", self.social.execute)

        # H12.22 — governed outbound voice / call-back. A call is an interruption,
        # so it's gated by BOTH the approval queue and the daily interrupt budget;
        # live telephony (Twilio/Telnyx) is deferred to a host-side client.
        import json as _json
        from .autonomy.call_broker import CallBroker
        try:
            _call_cfg = _json.loads(os.environ.get("JARVIS_CALL_CONFIG", "") or "{}")
        except Exception:
            _call_cfg = {}
        self.call_broker = CallBroker(
            enqueue=self.autonomy_queue.enqueue,
            secret_broker=getattr(self, "secret_broker", None),
            audit=getattr(self, "audit", None),
            budget=getattr(self.autonomy, "budget", None),
            config=_call_cfg,
        )
        executor.register("call", self.call_broker.execute)

        # H12.17 — governed node mesh (phone/desktop execution nodes). Capability-
        # scoped (H17.3 broker + kill-switch) + approval-gated; the on-device run
        # is a host seam (Tauri/phone client).
        from .node_mesh import NodeMesh
        self.node_mesh = NodeMesh(
            capability_broker=getattr(self, "capabilities", None),
            kill_switch=getattr(self, "kill_switch", None),
            enqueue=self.autonomy_queue.enqueue,
            audit=getattr(self, "audit", None),
        )
        executor.register("node", self.node_mesh.execute)

        # H20.1 — governed Tool-RPC surface for sandboxed zero-context pipelines.
        # Read-only tools run inline; gated tools enqueue an ask-tier task (and
        # run via this executor only after approval). Starter allowlist is safe
        # built-ins; integrations register more (incl. gated) over time.
        from .tool_rpc import ToolRPCServer
        import time as _t
        self.tool_rpc = ToolRPCServer(
            secret_broker=getattr(self, "secret_broker", None),
            enqueue=self.autonomy_queue.enqueue,
            audit=getattr(self, "audit", None),
        )

        async def _rpc_echo(args):
            return {"echo": args}

        async def _rpc_time(args):
            return {"now": _t.time()}

        self.tool_rpc.register_tool("echo", _rpc_echo)
        self.tool_rpc.register_tool("time", _rpc_time)
        executor.register("toolrpc", self.tool_rpc.execute)

        # H21.4: wire the calibration-gated autonomy hook (gated; no-op unless
        # cognition.learning_enabled — and it only ever ADDS caution).
        def _calibration_hook(action):
            cog = getattr(self, "cognition", None)
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
            self.autonomy.policy.calibration_hook = _calibration_hook
        except Exception:
            logger.debug("calibration hook wiring skipped", exc_info=True)

        # H20.6 — agent-initiated sub-agent delegation (isolated session, capped).
        from .subagents import SubAgentManager

        async def _subagent_runner(task, session_id, agent):
            picked = agent if agent in self.agents else "jarvis"
            out = await self.process(task, agent=picked, channel="subagent")
            return {"output": out, "session_id": session_id}

        self.subagents = SubAgentManager(
            runner=_subagent_runner,
            max_concurrent=int(self.get_setting("autonomy.max_subagents", 3) or 3),
        )

        return executor

    def _schedule_worldview_kg_sync(self):
        """Periodically sync the WorldView ontology into the knowledge graph (H19.3.5).

        OFF by default — like the Oracle watcher, a privacy-first local product should not
        poll a service unsolicited. Enable with JARVIS_WORLDVIEW_KG_SYNC=1 or the
        `worldview.kg_sync_enabled` setting. Each pass degrades to a no-op when WorldView
        is unreachable (the plugin fails closed), so an enabled-but-offline deployment is
        harmless. Skipped under JARVIS_TESTING.
        """
        if os.getenv("JARVIS_TESTING") == "1":
            return
        enabled = os.getenv("JARVIS_WORLDVIEW_KG_SYNC") == "1" or self.get_setting(
            "worldview.kg_sync_enabled", False
        )
        if not enabled:
            return
        sched = getattr(self.heartbeat_scheduler, "scheduler", None)
        if sched is None:
            return
        interval = max(60, int(self.get_setting("worldview.kg_sync_interval", 900)))
        try:
            sched.add_job(self._run_worldview_kg_sync, "interval", seconds=interval,
                          id="worldview-kg-sync", replace_existing=True)
            logger.info("Scheduled WorldView KG sync every %ss", interval)
        except Exception as e:
            logger.warning(f"Failed to schedule WorldView KG sync: {e}")

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

    async def _run_daily_digest(self, kind: str):
        """Build and ship the morning brief / evening retro to the owner."""
        try:
            if kind == "morning":
                text = build_morning_brief(self.autonomy_queue)
            else:
                text = build_evening_retro(self.autonomy_queue)
        except Exception as e:
            logger.warning(f"Digest build failed ({kind}): {e}")
            return
        owner = os.environ.get("AUTONOMY_OWNER_CHAT_ID", "") or str(
            self.get_setting("autonomy.owner_chat_id", "") or ""
        )
        tg = self.channels.get("telegram")
        if tg and owner:
            try:
                await tg.send(text, chat_id=int(owner))
            except Exception as e:
                logger.warning(f"Digest send failed ({kind}): {e}")
        logger.info(f"Daily digest ready: {kind}")

    async def register_channel(self, channel: ChannelAdapter):
        self.channels[channel.channel_id] = channel
        logger.info(f"Channel registered: {channel.channel_id}")

    async def start_channels(self):
        for cid, ch in self.channels.items():
            try:
                await ch.start()
            except Exception as e:
                log_error(logger, E_CHANNEL_START_FAIL, name=cid, detail=str(e))
        self.heartbeat_scheduler.start(self)
        self._settings_watcher_task = asyncio.create_task(self._settings_watcher_loop())
        self._settings_watcher_task.add_done_callback(_log_task_result)
        self._wire_autonomy()
        self._schedule_daily_digests()
        self._schedule_log_scans()
        self._schedule_learning_loop()
        self._schedule_daily_budget_reset()
        self._schedule_worldview_kg_sync()
        self._autonomy_task = asyncio.create_task(self._autonomy_loop())
        self._autonomy_task.add_done_callback(_log_task_result)
        # Oracle GitHub watcher is OFF by default: it polls a GitHub repo every 30s,
        # which a privacy-first local product should not do unsolicited. It's a
        # dev/dogfooding feature — enable with JARVIS_ORACLE_WATCH=1 or the
        # `oracle.watch_enabled` setting.
        _oracle_watch = os.getenv("JARVIS_ORACLE_WATCH") == "1" or self.get_setting("oracle.watch_enabled", False)
        if hasattr(self, 'oracle_bridge') and os.getenv("JARVIS_TESTING") != "1" and _oracle_watch:
            self.oracle_bridge.start_watcher()
        if os.getenv("JARVIS_TESTING") != "1":
            from agents.core.learning_loop import run_learning_loop
            _ll = asyncio.create_task(run_learning_loop(self))
            _ll.add_done_callback(_log_task_result)
        logger.info(f"Channels started: {list(self.channels.keys())}")
        logger.info("Components: %s", self.components.summary())  # A8: startup health report

    async def stop_channels(self):
        for cid, ch in self.channels.items():
            await ch.stop()
        self.heartbeat_scheduler.stop()
        if self._settings_watcher_task:
            self._settings_watcher_task.cancel()
        # Close all active plugins gracefully
        for pid, plugin in self.plugins.items():
            if hasattr(plugin, "close"):
                try:
                    await plugin.close()
                except Exception as e:
                    logger.warning(f"Error closing plugin {pid}: {e}")
        logger.info("Channels stopped")

    async def channel_handler(self, text: str, channel: str = "voice", **kwargs) -> Optional[str]:
        chat_id = kwargs.get("chat_id")
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

        ch = self.channels.get(channel)
        if ch:
            if channel == "telegram":
                await ch.send(response, **kwargs)
            elif channel == "web":
                await ch.send(response, **kwargs)
            elif channel == "voice":
                await ch.send(response)
        return response

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
        t_start = time.perf_counter()
        await self.memory.add_turn(self.session_id, "user", text)

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
            await self.memory.add_turn(self.session_id, "assistant", synthesized, agent_id=agent_override)
            await self._maybe_checkpoint()
            await asyncio.to_thread(self._log_session, text, intent, responses, synthesized)
            await asyncio.to_thread(self._record_interactions, text, responses, synthesized, route_name)
            _event_override = SecurityEvent(
                event_type=SecurityEventType.LLM_CALL,
                timestamp=time.time(),
                findings=[],
                content_preview=synthesized[:100],
                action_taken=f"handle_input(agent_override={agent_override}) via {channel}",
            )
            await asyncio.to_thread(self.audit.log, _event_override)
            self._update_cognition(text, intent, plugin_data, synthesized, t_classify, t_route, t_plugin, t_synthesize)
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

        await self.memory.add_turn(self.session_id, "assistant", synthesized, agent_id=responder_id)
        await self._maybe_checkpoint()
        await asyncio.to_thread(self._log_session, text, intent, responses, synthesized)
        await asyncio.to_thread(self._record_interactions, text, responses, synthesized, route_name)

        _event_main = SecurityEvent(
            event_type=SecurityEventType.LLM_CALL,
            timestamp=time.time(),
            findings=[],
            content_preview=synthesized[:100],
            action_taken=f"handle_input via {channel}",
        )
        await asyncio.to_thread(self.audit.log, _event_main)

        self._update_cognition(text, intent, plugin_data, synthesized, t_classify, t_route, t_plugin, t_synthesize)
        return synthesized

    async def handle_input_stream(self, text: str, channel: str = "voice", on_token: Callable = None,
                                  agent_override: str = None, session_id: str = None) -> str:
        # BUG-5: see handle_input — pin this turn to its own session so it can
        # never read or write another concurrent request's conversation.
        self._resolve_session(session_id)
        self._last_channel = channel  # captured for H9.2 tracer
        await self.memory.add_turn(self.session_id, "user", text)

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

        temperature = self.get_setting("llm.temperature", 0.7)
        max_tokens = self.get_setting("llm.max_tokens", 2048)
        deep_max_tokens = self.get_setting("llm.deep_max_tokens", 8192)
        context_window = self.get_setting("memory.context_window", 6)
        synthesized = ""
        # Pre-bind so the post-loop persist/audit never hit UnboundLocalError when
        # `target` is empty (e.g. _route_candidates returns nothing).
        agent_id = None
        t_s0 = time.perf_counter()
        for agent_id in target:
            if agent_id in self.agents:
                agent = self.agents[agent_id]
                history = await self.memory.get_context(self.session_id, last_n=context_window)
                system_prompt = agent.soul.get("content", "")
                plugin_block = self._format_plugin_data(plugin_data)
                agent_context = await self.memory.get_agent_context(agent_id)
                context_block = ""
                if agent_context:
                    context_block = f"Agent context: {agent_context}\n"

                rag_block = ""
                if agent_id == "howard":
                    try:
                        from .ingestion.pipeline import IngestionPipeline
                        pipeline = IngestionPipeline()
                        similar = pipeline.search_similar(text, k=5, only_me=True)
                        if similar:
                            shot_lines = [f"- Andrei: \"{m.text}\"" for m in similar]
                            rag_block = "Here are some of your past matching responses from the archive (RAG), mirroring your stylometry, tone, and opinions:\n" + "\n".join(shot_lines) + "\n\n"
                            logger.info(f"Howard RAG: injected {len(similar)} few-shot messages into stream prompt")
                    except Exception as e:
                        logger.warning(f"Howard RAG stream lookup failed: {e}")

                recall_block = await self._recall_block(text)
                runtime_block = self._runtime_state_block()
                prompt = (
                    f"Conversation history:\n{history}\n\n"
                    f"{plugin_block}{context_block}{rag_block}{recall_block}{runtime_block}"
                    f"User: {text}\n"
                    f"Respond as {agent.name}."
                )
                model = self.llm_router.get_model(agent_id) or self.get_setting("llm.default_model") or "qwen3:7b"

                checkpoint = self.checkpoints.load(agent_id, self.session_id)
                if checkpoint:
                    prompt = f"[RESUMED FROM CHECKPOINT]\n{checkpoint['prompt']}\n---\n{prompt}"

                try:
                    backend, router_model, route_name = self.llm_router.select_backend(agent_id, prompt)
                    if router_model:
                        model = router_model
                    if self.security:
                        backend = self.security
                    # Reasoning models on the deep slot need a far larger budget:
                    # 1–2k tokens is consumed by chain-of-thought before any
                    # answer, so a small cap truncates mid-thought.
                    eff_max_tokens = deep_max_tokens if route_name == "local-deep" else max_tokens
                    logger.info(f"Routing {agent_id} via {route_name} ({estimate_tokens(prompt)} tokens, max_tokens={eff_max_tokens})")
                except RuntimeError:
                    msg = "I'm sorry, sir — my language backend is not available. Please start Ollama or LM Studio and try again."
                    log_error(logger, E_LLM_BACKEND_MISSING, backend="stream")
                    if on_token:
                        on_token(msg)
                    return msg

                # Context caching for Gemini cloud routes
                use_cache_name = None
                is_gemini_route = route_name in ("cloud", "cloud-flash", "cloud-pro", "cloud-fallback", "gemini")
                if is_gemini_route and self.context_cache and history:
                    cache_entry = self.context_cache.get_cache_info(self.session_id)
                    if cache_entry:
                        use_cache_name = cache_entry["cache_name"]
                        prompt = (
                            f"{plugin_block}{context_block}"
                            f"User: {text}\n"
                            f"Respond as {agent.name}."
                        )
                    else:
                        history_parts = [t.strip() for t in history.split("\n---\n") if t.strip()]
                        _cache_task = asyncio.ensure_future(self._async_create_cache(
                            session_id=self.session_id,
                            system_instruction=system_prompt,
                            history_texts=history_parts,
                            model=model,
                        ))
                        _cache_task.add_done_callback(_log_task_result)
                if use_cache_name:
                    backend._use_cache = use_cache_name
                else:
                    backend._use_cache = ""

                t_s0 = time.perf_counter()
                if on_token and hasattr(backend, "generate_stream"):
                    response = await backend.generate_stream(
                        model=model, prompt=prompt,
                        system=system_prompt,
                        max_tokens=eff_max_tokens, temperature=temperature,
                        on_token=on_token,
                    )
                else:
                    response = await backend.generate(
                        model=model, prompt=prompt, system=system_prompt,
                        max_tokens=eff_max_tokens, temperature=temperature,
                    )
                    if on_token:
                        on_token(response)
                synthesized = response
                break

        # Truncated-before-answer (or otherwise empty) replies must not surface
        # as a blank bubble. The backend already refuses to leak raw reasoning,
        # so an empty string here means "no answer was produced".
        if not (synthesized or "").strip():
            synthesized = "My reply was cut short before I finished, sir. Try again, or raise the token limit for heavier requests."
            if on_token:
                on_token(synthesized)
        await self.memory.add_turn(self.session_id, "assistant", synthesized, agent_id=agent_id)
        await self._maybe_checkpoint()
        _event_stream = SecurityEvent(
            event_type=SecurityEventType.LLM_CALL,
            timestamp=time.time(),
            findings=[],
            content_preview=synthesized[:100],
            action_taken=f"handle_input_stream({agent_id}) via {channel}",
        )
        await asyncio.to_thread(self.audit.log, _event_stream)
        t_synthesize = int((time.perf_counter() - t_s0) * 1000)
        self._update_cognition(text, intent, plugin_data, synthesized, t_classify, t_route, t_plugin, t_synthesize)
        return synthesized

    def _update_cognition(self, text, intent, plugin_data, synthesized, t_classify, t_route, t_plugin, t_synthesize):
        from core.router import INTENT_RULES
        scoring = []
        for kw in intent.context.get("keywords_found", []):
            if kw in INTENT_RULES:
                agents, surfaces, weight = INTENT_RULES[kw]
                scoring.append({
                    "keyword": kw,
                    "weight": weight,
                    "agents": agents,
                    "category": kw
                })
        
        if not scoring:
            scoring = []

        alternatives = []
        for a, s in intent.context.get("scores", {}).items():
            if a not in (intent.target_agents or ["jarvis"]):
                alternatives.append({"agent": a, "score": s})

        alternatives = sorted(alternatives, key=lambda x: -x["score"])

        decision = {
            "source": intent.context.get("source", "keyword_match"),
            "confidence": intent.confidence,
            "agents_selected": intent.target_agents or ["jarvis"],
            "alternatives": alternatives,
            "timing": {
                "classify": t_classify,
                "route": t_route,
                "total": t_classify + t_route
            }
        }

        trace = [
            {"step": "classify", "duration_ms": t_classify, "result": intent.context.get("source", "keyword_match")},
            {"step": "route", "duration_ms": t_route, "agents": intent.target_agents or ["jarvis"]}
        ]
        if plugin_data:
            trace.append({"step": "plugin_data", "duration_ms": t_plugin, "plugins": list(plugin_data.keys())})
        if synthesized:
            trace.append({"step": "synthesize", "duration_ms": t_synthesize, "tokens": len(synthesized) // 4})

        self.last_cognition = {
            "scoring": scoring,
            "decision": decision,
            "trace": trace
        }

        # H9.2: persist to tracer ring buffer (defensive — never breaks a request)
        try:
            if self.tracer is not None:
                from .observability.tracer import Tracer
                model = ""
                agents_selected = decision.get("agents_selected", [])
                if agents_selected:
                    first_agent = agents_selected[0]
                    agent_obj = self.agents.get(first_agent)
                    if agent_obj:
                        model = agent_obj.config.get("model", "")
                from .llm.tokenizer import estimate_tokens as _et
                tokens_in = _et(text or "")
                tokens_out = _et(synthesized or "")
                # H10.24: estimate $ cost for this trace (local models → $0).
                try:
                    from .llm.cost_estimator import estimate_cost as _ec
                    cost = _ec(model, tokens_in, tokens_out).get("total", 0.0)
                except Exception:
                    cost = 0.0
                trace_dict = {
                    "channel": getattr(self, "_last_channel", "unknown"),
                    "text_preview": (text or "")[:120],
                    "intent": decision.get("source", ""),
                    "route": agents_selected[0] if agents_selected else "",
                    "agents": agents_selected,
                    "model": model,
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "cost": cost,
                    "timings": {
                        "classify": t_classify,
                        "route": t_route,
                        "plugin": t_plugin,
                        "synthesize": t_synthesize,
                        "total_ms": t_classify + t_route + t_plugin + t_synthesize,
                    },
                    "ok": True,
                    "scoring": scoring,
                    "full_trace": trace,
                }
                # H10.23: score the request live and attach it to the trace.
                if getattr(self, "quality", None) is not None:
                    try:
                        trace_id = self.tracer.record(trace_dict)
                        trace_dict["id"] = trace_id
                        q = self.quality.record(trace_dict)
                        trace_dict["quality"] = q
                        # H21.1: anti-sycophancy axis (gated; master OFF = no-op).
                        cog = getattr(self, "cognition", None)
                        if cog is not None and cog.sub_enabled("honesty_enabled"):
                            hm = cog.module("honesty")
                            if hm is not None:
                                _txt = trace_dict.get("text_preview") or trace_dict.get("output_preview") or ""
                                trace_dict["honesty"] = hm.score_response(_txt, trace_id=trace_dict.get("id", ""))
                        # H10.25: auto-flag low-scoring traces for human review.
                        if getattr(self, "review_queue", None) is not None:
                            self.review_queue.auto_flag(trace_dict, q.get("score"), self.quality.threshold)
                    except Exception:
                        logger.debug("quality scoring skipped", exc_info=True)
                else:
                    self.tracer.record(trace_dict)
        except Exception as _te:
            logger.debug(f"tracer.record skipped: {_te}")

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
        return intent.target_agents[0] if intent.target_agents and len(intent.target_agents) > 0 else "jarvis"

    def _any_agent_can(self, plugin: str, intent) -> bool:
        agents = intent.target_agents if intent.target_agents else ["jarvis"]
        return any(self.permission_gate.check_call(plugin, a) for a in agents)

    async def _gather_plugin_data(self, text: str, intent) -> dict:
        data = {}
        keywords = intent.context.get("keywords_found", [])
        text_lower = text.lower()

        if "weather" in keywords or any(w in text_lower for w in ["weather", "vremea", "temperature", "ploaie", "temperatura"]):
            if self._any_agent_can("weather", intent):
                wp = self.plugins.get("weather")
                if wp:
                    location = self._extract_location(text)
                    data["weather"] = await wp.get_weather(location)
            else:
                log_error(logger, E_PLUGIN_BLOCKED, name="weather")

        if "news" in keywords or any(w in text_lower for w in ["news", "stiri", "headlines", "noutati"]):
            if self._any_agent_can("news", intent):
                np = self.plugins.get("news")
                if np:
                    category = "general"
                    if any(w in text_lower for w in ["tech", "technology", "tehnologie"]):
                        category = "technology"
                    elif any(w in text_lower for w in ["business", "afaceri"]):
                        category = "business"
                    data["news"] = await np.summarize(category)
            else:
                log_error(logger, E_PLUGIN_BLOCKED, name="news")

        if "calendar" in keywords or any(w in text_lower for w in ["calendar", "agenda", "program", "sedin", "meeting", "eveniment"]):
            if self._any_agent_can("google-calendar", intent):
                gp = self.plugins.get("google-calendar")
                if gp and gp.access_token:
                    data["calendar"] = await gp.get_today_events()

        if "email" in keywords or any(w in text_lower for w in ["email", "mail", "inbox", "mesaj", "hangup", "prim"]):
            if self._any_agent_can("gmail", intent):
                gp = self.plugins.get("gmail")
                if gp and gp.access_token:
                    data["email"] = await gp.list_messages(max_results=5)

        if "research" in keywords or "search" in keywords or any(w in text_lower for w in ["research", "caut", "search", "find", "gaseste", "investigheaza"]):
            if self._any_agent_can("websearch", intent):
                wp = self.plugins.get("websearch")
                if wp:
                    data["websearch"] = await wp.search(text, max_results=5)

        if "worldview" in keywords or any(w in text_lower for w in [
            "satellite", "satelit", "recon", "overflight", "overpass", "satpass",
            "geospatial", "osint", "hormuz", "strait", "dark vessel",
            "jamming", "bruiaj", "footprint", "overhead pass",
        ]):
            if self._any_agent_can("worldview", intent):
                wv = self.plugins.get("worldview")
                if wv:
                    data["worldview"] = await wv.recon_overview()
            else:
                log_error(logger, E_PLUGIN_BLOCKED, name="worldview")

        return data

    def _extract_location(self, text: str) -> str:
        text_lower = text.lower()
        for kw in ["in ", "la ", "pentru ", "din "]:
            if kw in text_lower:
                idx = text_lower.index(kw) + len(kw)
                rest = text[idx:].strip().rstrip("?.!")
                if rest and not rest.startswith(("the", "a", "an", "my")):
                    return rest
        return ""

    def _format_plugin_data(self, data: dict) -> str:
        if not data:
            return ""
        blocks = []
        for key, value in data.items():
            if value:
                blocks.append(f"[REAL-TIME DATA — {key.upper()}]:\n{value}")
        return "\n\n".join(blocks) + "\n\n" if blocks else ""

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

    def _control_master_enabled(self) -> bool:
        """Master switch for LM Studio lifecycle control (chat + admin API + HUD).
        Off if EITHER the env var or the live ``llm.control_enabled`` setting is
        off, so any single kill signal wins. Both default on."""
        return (_env_flag("JARVIS_LMSTUDIO_CONTROL", True)
                and _as_bool(self.get_setting("llm.control_enabled", True)))

    def _chat_control_enabled(self) -> bool:
        """Whether a natural-language chat message may drive LLM control. Needs the
        master switch plus its own ``JARVIS_LMSTUDIO_CHAT_CONTROL`` env /
        ``llm.chat_control`` setting — lets you mute ambient detection while
        keeping the explicit admin buttons live."""
        return (self._control_master_enabled()
                and _env_flag("JARVIS_LMSTUDIO_CHAT_CONTROL", True)
                and _as_bool(self.get_setting("llm.chat_control", True)))

    def _control_cognition(self, action: str) -> dict:
        return {
            "scoring": [],
            "decision": {"source": "llm-control", "confidence": 1.0,
                         "agents_selected": ["jarvis"], "alternatives": [],
                         "timing": {"classify": 0, "route": 0, "total": 0}},
            "trace": [{"step": "llm_control", "duration_ms": 0, "result": action}],
        }

    async def _run_llm_control(self, action: str, model: Optional[str]) -> Optional[str]:
        """Execute a detected LLM-control action via the controller and narrate
        the real result in Jarvis's voice — it reflects what actually happened,
        not theatre."""
        ctrl = getattr(self, "lmstudio", None)
        if ctrl is None:
            return "LM Studio control is not available, sir."
        router = getattr(self, "llm_router", None)
        backend = getattr(router, "name", None) or "the local backend"

        if action == "status":
            st = await ctrl.status()
            if not st.get("online"):
                return "The language backend is offline, sir. Say 'start LM Studio' and I will bring it up."
            name = st.get("active_model") or getattr(router, "active_model", None) or "an unidentified model"
            return f"I am running {name} on {backend}, sir."

        if action == "start":
            res = await ctrl.start_server()
            if res.get("status") == "ok":
                return "LM Studio is already running, sir." if res.get("already_running") else "LM Studio is up, sir."
            return f"I could not start LM Studio, sir — {res.get('reason') or 'the server did not come up'}."

        if action == "load":
            if not model:
                return "Which model would you like me to load, sir?"
            res = await ctrl.load_model(model)
            status = res.get("status")
            if status == "ok":
                active = getattr(router, "active_model", None) or model
                return f"Loaded and running {active}, sir."
            if status == "rejected":
                return f"That is not a valid model id, sir: {model!r}."
            return f"I could not load {model}, sir — {res.get('reason') or 'the load failed'}."

        if action == "unload":
            res = await ctrl.unload_model(model)
            if res.get("status") == "ok":
                return "Unloaded, sir." if model else "All models unloaded, sir."
            return f"I could not unload, sir — {res.get('reason') or 'the unload failed'}."

        return None

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
        except Exception as e:
            logger.warning(f"recall failed: {e}")
            return ""
        lines = []
        for h in hits or []:
            payload = getattr(h, "payload", {}) or {}
            md = payload.get("metadata") or {}
            # vector hits carry text under metadata; graph hits expose a name
            snippet = payload.get("text") or md.get("text") or payload.get("name")
            if snippet:
                lines.append(f"- {snippet}")
        if not lines:
            return ""
        return "Relevant long-term memory (recall):\n" + "\n".join(lines) + "\n\n"

    async def _call_agents_parallel(
        self, agent_ids: list[str], text: str, context: dict, plugin_data: dict = None
    ) -> dict[str, str]:
        history = await self.memory.get_context(self.session_id, last_n=6)
        plugin_block = self._format_plugin_data(plugin_data or {})
        recall_block = await self._recall_block(text)

        async def _run_agent(agent_id: str) -> tuple[str, str, float]:
            enriched_text = text
            if history:
                enriched_text = f"Context:\n{history}\n\nUser: {text}"
            if plugin_block:
                enriched_text = f"{plugin_block}{enriched_text}"
            if recall_block:
                enriched_text = f"{recall_block}{enriched_text}"
            agent_context = await self.memory.get_agent_context(agent_id)
            if agent_context:
                enriched_text = f"Agent context: {agent_context}\n\n{enriched_text}"
            # H21.2: prepend the persona block (gated; master OFF = no-op). Both
            # prompt builders funnel through here (process() → _call_agents_parallel).
            _cog = getattr(self, "cognition", None)
            if _cog is not None and _cog.sub_enabled("affect_enabled"):
                _pm = _cog.module("persona")
                if _pm is not None:
                    _pb = _pm.prompt_block(agent_id)
                    if _pb:
                        enriched_text = f"{_pb}\n\n{enriched_text}"
            try:
                resp = await asyncio.wait_for(
                    self.agents[agent_id].process(enriched_text, context),
                    timeout=120.0,
                )
                return agent_id, resp, self.agents[agent_id].last_latency
            except asyncio.TimeoutError:
                self.agents[agent_id]._record_failure("timeout")
                log_error(logger, E_LLM_TIMEOUT, timeout=120)
                return agent_id, f"[{agent_id} timeout]", 0.0
            except Exception as e:
                self.agents[agent_id]._record_failure(str(e))
                log_error(logger, E_INTERNAL_UNEXPECTED, component=f"agent:{agent_id}", detail=str(e))
                return agent_id, f"[{agent_id} error: {e}]", 0.0

        valid_ids = [aid for aid in agent_ids if aid in self.agents]
        for aid in agent_ids:
            if aid not in self.agents:
                logger.warning(f"Agent {aid} not loaded")

        coros = [_run_agent(aid) for aid in valid_ids]
        results_list = await asyncio.gather(*coros)

        results = {}
        self._last_latencies = {}
        for agent_id, resp, latency in results_list:
            results[agent_id] = resp
            self._last_latencies[agent_id] = latency
        return results

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

        self.agents[bench_id] = agent

        # Register in router so the agent is wake-word routable.
        if bench_id not in self.router.ROUTING_TABLE:
            self.router.ROUTING_TABLE[bench_id] = [bench_id]
            logger.info(f"promote_bench_agent: added {bench_id} to ROUTING_TABLE")

        logger.info(f"promote_bench_agent: {bench_id} ({name}) is now active")
        return True

    def _record_interactions(self, text: str, responses: dict, synthesized: str, route_name: str = ""):
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
                failed = bool(re.match(rf"^\[{re.escape(agent_id)} (error|timeout)\b", resp))
                success = not failed
                latency = getattr(self, "_last_latencies", {}).get(agent_id, 0.0)
                metadata = {
                    "channel": "web",
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
                    route_name=route_name,
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
                            route=route_name,
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

    async def _async_create_cache(self, session_id: str, system_instruction: str,
                                    history_texts: list[str], model: str):
        if not self.context_cache or not history_texts:
            return
        history = [{"role": "user", "parts": [{"text": t}]} for t in history_texts]
        await self.context_cache.create_or_extend(
            session_id=session_id,
            system_instruction=system_instruction,
            history=history,
            model=model,
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
