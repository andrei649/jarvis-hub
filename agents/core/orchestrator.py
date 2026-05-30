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
from .llm.tokenizer import estimate_tokens
from .memory.manager import MemoryManager
from .checkpoint import CheckpointManager
from .heartbeat import HeartbeatScheduler
from .learning.loop import LearningLoop
from .skills.loader import SkillLoader
from .skills.importer import SkillImporter
from .mcp.client import MCPManager
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
from .plugins.oracle_bridge import OracleBridgePlugin

logger = logging.getLogger("jarvis.orchestrator")

HANDOFF_PREFIX = "[handoff:"
SKILL_PREFIX = "[learn:"


class Orchestrator:
    def __init__(self, config: JarvisConfig):
        self.config = config
        self.agents: dict[str, Agent] = {}
        self.router = IntentRouter(config)
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        self.llm_router = HybridRouter(gemini_api_key=gemini_key)
        self.memory = MemoryManager()
        self.plugins: dict = {}
        self.skills = SkillLoader()
        self.skill_importer = SkillImporter()
        self.mcp = MCPManager()
        self.channels: dict[str, ChannelAdapter] = {}
        self.checkpoints = CheckpointManager()
        self.learning = LearningLoop()
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
        self._settings_watcher_task: Optional[asyncio.Task] = None

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

        self.plugins["oracle-bridge"] = OracleBridgePlugin(
            github_token=os.environ.get("GITHUB_TOKEN", ""),
        )
        self.oracle_bridge = self.plugins["oracle-bridge"]

        self.skills.discover()
        logger.info(f"Skills loaded: {list(self.skills.skills.keys())}")

        self.checkpoints.initialize()
        restored = self.checkpoints.restore(self)
        if restored:
            logger.info(f"Restored from checkpoint — session: {self.session_id}")

        if not self.session_id:
            self.session_id = self.memory.conversation.current_session_id or self.memory.new_session()
            logger.info(f"Session: {self.session_id}")

        self.load_runtime_settings()
        self.heartbeat_scheduler.load_all()
        self.heartbeat_scheduler.load_from_config(self.config)

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
        if hasattr(self, 'oracle_bridge'):
            self.oracle_bridge.start_watcher()
        logger.info(f"Channels started: {list(self.channels.keys())}")

    async def stop_channels(self):
        for cid, ch in self.channels.items():
            await ch.stop()
        self.heartbeat_scheduler.stop()
        if self._settings_watcher_task:
            self._settings_watcher_task.cancel()
        logger.info("Channels stopped")

    async def channel_handler(self, text: str, channel: str = "voice", **kwargs) -> Optional[str]:
        chat_id = kwargs.get("chat_id")
        if channel == "telegram" and chat_id:
            ck = f"tg:{chat_id}"
            if ck not in self._channel_sessions:
                self._channel_sessions[ck] = self.memory.new_session()
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
        self.memory.add_turn(self.session_id, "user", text)

        skill_cmd = self.skills.parse_command(text)
        if skill_cmd:
            skill_name, command, args = skill_cmd
            skill = self.skills.get_skill(skill_name)
            if skill:
                result = await skill.execute(command, args, {"channel": channel})
                if result:
                    self.memory.add_turn(self.session_id, "assistant", result, agent_id=skill_name)
                    return result

        if agent_override and agent_override in self.agents:
            intent = await self.router.classify(text, self.agents)
            plugin_data = await self._gather_plugin_data(text, intent)
            responses = await self._call_agents_parallel(
                [agent_override], text, intent.context, plugin_data
            )
            synthesized = list(responses.values())[0] if responses else ""
            self.memory.add_turn(self.session_id, "assistant", synthesized, agent_id=agent_override)
            self.checkpoints.save(self)
            self._log_session(text, intent, responses, synthesized)
            self._record_interactions(text, responses, synthesized)
            self.audit.log(SecurityEvent(
                event_type=SecurityEventType.LLM_CALL,
                timestamp=time.time(),
                findings=[],
                content_preview=synthesized[:100],
                action_taken=f"handle_input(agent_override={agent_override}) via {channel}",
            ))
            return synthesized

        intent = await self.router.classify(text, self.agents)
        plugin_data = await self._gather_plugin_data(text, intent)

        if intent.target_agents:
            responses = await self._call_agents_parallel(
                intent.target_agents, text, intent.context, plugin_data
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

        skill_name = self._detect_skill_learning(responses, synthesized, intent)
        if skill_name:
            logger.info(f"Learned new skill: {skill_name}")

        self.memory.add_turn(self.session_id, "assistant", synthesized, agent_id=responder_id)
        self.checkpoints.save(self)
        self._log_session(text, intent, responses, synthesized)

        self._record_interactions(text, responses, synthesized)

        self.audit.log(SecurityEvent(
            event_type=SecurityEventType.LLM_CALL,
            timestamp=time.time(),
            findings=[],
            content_preview=synthesized[:100],
            action_taken=f"handle_input via {channel}",
        ))

        return synthesized

    async def handle_input_stream(self, text: str, channel: str = "voice", on_token: Callable = None, agent_override: str = None) -> str:
        self.memory.add_turn(self.session_id, "user", text)

        skill_cmd = self.skills.parse_command(text)
        if skill_cmd:
            skill_name, command, args = skill_cmd
            skill = self.skills.get_skill(skill_name)
            if skill:
                result = await skill.execute(command, args, {"channel": channel})
                if result:
                    self.memory.add_turn(self.session_id, "assistant", result, agent_id=skill_name)
                    if on_token:
                        on_token(result)
                    return result

        intent = await self.router.classify(text, self.agents)
        plugin_data = await self._gather_plugin_data(text, intent)
        if agent_override and agent_override in self.agents:
            target = [agent_override]
        else:
            target = intent.target_agents if intent.target_agents else ["jarvis"]

        temperature = self.get_setting("llm.temperature", 0.7)
        max_tokens = self.get_setting("llm.max_tokens", 1024)
        context_window = self.get_setting("memory.context_window", 6)
        synthesized = ""
        for agent_id in target:
            if agent_id in self.agents:
                agent = self.agents[agent_id]
                history = self.memory.get_context(self.session_id, last_n=context_window)
                system_prompt = agent.soul.get("content", "")
                plugin_block = self._format_plugin_data(plugin_data)
                agent_context = self.memory.get_agent_context(agent_id)
                context_block = ""
                if agent_context:
                    context_block = f"Agent context: {agent_context}\n"
                prompt = (
                    f"Conversation history:\n{history}\n\n"
                    f"{plugin_block}{context_block}"
                    f"User: {text}\n"
                    f"Respond as {agent.name}."
                )
                model = self.get_setting("llm.default_model") or agent.config.get("model", "qwen/qwen3.5-9b")

                checkpoint = self.checkpoints.load(agent_id, self.session_id)
                if checkpoint:
                    prompt = f"[RESUMED FROM CHECKPOINT]\n{checkpoint['prompt']}\n---\n{prompt}"

                try:
                    backend, route_name = self.llm_router.select_backend(agent_id, prompt)
                    if self.security:
                        backend = self.security
                    logger.info(f"Routing {agent_id} via {route_name} ({estimate_tokens(prompt)} tokens)")
                except RuntimeError:
                    msg = "I'm sorry, sir — my language backend is not available. Please start Ollama or LM Studio and try again."
                    log_error(logger, E_LLM_BACKEND_MISSING, backend="stream")
                    if on_token:
                        on_token(msg)
                    return msg

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

        self.memory.add_turn(self.session_id, "assistant", synthesized, agent_id=agent_id)
        self.checkpoints.save(self)
        self.audit.log(SecurityEvent(
            event_type=SecurityEventType.LLM_CALL,
            timestamp=time.time(),
            findings=[],
            content_preview=synthesized[:100],
            action_taken=f"handle_input_stream({agent_id}) via {channel}",
        ))
        return synthesized

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

    async def _call_agents_parallel(
        self, agent_ids: list[str], text: str, context: dict, plugin_data: dict = None
    ) -> dict[str, str]:
        history = self.memory.get_context(self.session_id, last_n=6)
        plugin_block = self._format_plugin_data(plugin_data or {})

        async def _run_agent(agent_id: str) -> tuple[str, str, float]:
            enriched_text = text
            if history:
                enriched_text = f"Context:\n{history}\n\nUser: {text}"
            if plugin_block:
                enriched_text = f"{plugin_block}{enriched_text}"
            agent_context = self.memory.get_agent_context(agent_id)
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
            return await agent.run_heartbeat()
        return None

    def _record_interactions(self, text: str, responses: dict, synthesized: str):
        for agent_id, resp in responses.items():
            if agent_id in self.agents and resp:
                is_timeout = resp.endswith("timeout]")
                is_error = resp.endswith("error:") or "error:" in resp
                success = not (is_timeout or is_error)
                latency = getattr(self, "_last_latencies", {}).get(agent_id, 0.0)
                self.learning.record(
                    agent_id=agent_id,
                    task=text[:200],
                    response=resp[:500],
                    success=success,
                    latency=latency,
                    error=resp if not success else None,
                    metadata={"channel": "web"},
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

    def _log_session(self, text, intent, responses, synthesized):
        logger.info(f"[{(self.session_id or 'none')[:20]}]: {text[:40]}... -> {synthesized[:40]}...")

    async def get_status(self) -> dict:
        return {
            "llm_backend": self.llm_router.name,
            "agents": list(self.agents.keys()),
            "session": self.session_id,
            "memory": self.memory.get_session_stats(),
            "skills": list(self.skills.skills.keys()),
            "checkpoint": self.checkpoints.info(),
            "learning": self.learning.get_stats(),
            "bench": self.bench.get_summary(),
            "security": self.security is not None,
            "sandbox_available": self.sandbox._has_docker,
        }
