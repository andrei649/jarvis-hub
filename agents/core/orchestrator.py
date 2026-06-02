"""
orchestrator.py — Main orchestration loop for Jarvis Beta.
Integrates: intent routing, LLM backend, memory, live plugins, streaming, voice, channels,
skills system, checkpointing, agent handoff, promotion/demotion.
"""

import asyncio
import logging
import os
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

logger = logging.getLogger("jarvis.orchestrator")

HANDOFF_PREFIX = "[handoff:"
SKILL_PREFIX = "[learn:"


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
        self.session_id: Optional[str] = None
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
            self.tracer = None

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

        # Autonomy queue — durable self-tasking store (H6.1)
        try:
            self.autonomy_queue.initialize()
            self.autonomy_prefs.initialize()
            self.autonomy.executor = self._build_autonomy_executor().execute
            self.observer = ProactiveObserver(self.autonomy, probes=default_probes())

            # Setup personal event probes using active plugins (Antigravity watchers)
            from .autonomy.watchers import EventWatcher, EmailProbe, CalendarProbe, FinanceProbe, HealthProbe
            gmail = self.plugins.get("gmail")
            calendar = self.plugins.get("google-calendar")
            balance = self.plugins.get("balance")
            health = self.plugins.get("apple-health")

            event_probes = [
                EmailProbe(gmail_plugin=gmail, priority_senders=self.get_setting("autonomy.priority_senders", ["andrei"]), get_setting=self.get_setting),
                CalendarProbe(calendar_plugin=calendar, lead_time_min=int(self.get_setting("autonomy.calendar_lead_time", 30)), get_setting=self.get_setting),
                FinanceProbe(balance_plugin=balance, min_ron=float(self.get_setting("autonomy.finance_min_ron", 2000.0)), min_eur=float(self.get_setting("autonomy.finance_min_eur", 400.0)), get_setting=self.get_setting),
                HealthProbe(health_plugin=health, min_sleep_hrs=float(self.get_setting("autonomy.health_min_sleep", 5.0)), min_hrv_ms=float(self.get_setting("autonomy.health_min_hrv", 30.0)), get_setting=self.get_setting),
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
                max_tier = None
                if self.get_setting("autonomy.night_shift", False):
                    start = int(self.get_setting("autonomy.night_start", 23) or 23)
                    end = int(self.get_setting("autonomy.night_end", 6) or 6)
                    if is_night_window(datetime.now().hour, start, end):
                        max_tier = 1  # reversible/read-only only
                await self.autonomy.tick(max_tier=max_tier)
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
                # Sync error/problem log to BACKLOG.md (Antigravity error backlog logger)
                if self.get_setting("system.error_backlog_sync_enabled", True):
                    from .autonomy.error_logger import sync_problems_to_backlog
                    sync_problems_to_backlog()
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

        return executor

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
        self._wire_autonomy()
        self._schedule_daily_digests()
        self._autonomy_task = asyncio.create_task(self._autonomy_loop())
        if hasattr(self, 'oracle_bridge'):
            self.oracle_bridge.start_watcher()
        logger.info(f"Channels started: {list(self.channels.keys())}")

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
            saved_session = self.session_id
            self.session_id = self._channel_sessions[ck]
            try:
                response = await self.handle_input(text, channel)
            finally:
                self.session_id = saved_session
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

    async def handle_input(self, text: str, channel: str = "voice", agent_override: str = None) -> str:
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

    async def handle_input_stream(self, text: str, channel: str = "voice", on_token: Callable = None, agent_override: str = None) -> str:
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
        max_tokens = self.get_setting("llm.max_tokens", 1024)
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
                prompt = (
                    f"Conversation history:\n{history}\n\n"
                    f"{plugin_block}{context_block}{rag_block}{recall_block}"
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
                    logger.info(f"Routing {agent_id} via {route_name} ({estimate_tokens(prompt)} tokens)")
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
                        asyncio.ensure_future(self._async_create_cache(
                            session_id=self.session_id,
                            system_instruction=system_prompt,
                            history_texts=history_parts,
                            model=model,
                        ))
                if use_cache_name:
                    backend._use_cache = use_cache_name
                else:
                    backend._use_cache = ""

                t_s0 = time.perf_counter()
                if on_token and hasattr(backend, "generate_stream"):
                    response = await backend.generate_stream(
                        model=model, prompt=prompt,
                        system=system_prompt,
                        max_tokens=max_tokens, temperature=temperature,
                        on_token=on_token,
                    )
                else:
                    response = await backend.generate(
                        model=model, prompt=prompt, system=system_prompt,
                        max_tokens=max_tokens, temperature=temperature,
                    )
                    if on_token:
                        on_token(response)
                synthesized = response
                break

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
                trace_dict = {
                    "channel": getattr(self, "_last_channel", "unknown"),
                    "text_preview": (text or "")[:120],
                    "intent": decision.get("source", ""),
                    "route": agents_selected[0] if agents_selected else "",
                    "agents": agents_selected,
                    "model": model,
                    "tokens_in": _et(text or ""),
                    "tokens_out": _et(synthesized or ""),
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
        return await jarvis.synthesize(responses, intent)

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
        for agent_id, resp in responses.items():
            if agent_id in self.agents and resp:
                is_timeout = resp.endswith("timeout]")
                is_error = resp.endswith("error:") or "error:" in resp
                success = not (is_timeout or is_error)
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
        """Graceful shutdown: flush pending checkpoint before process exit."""
        await self._flush_checkpoint()

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
