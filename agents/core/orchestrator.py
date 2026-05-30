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
from .llm.router import LLMRouter
from .memory.manager import MemoryManager
from .checkpoint import CheckpointManager
from .plugins.weather import WeatherPlugin
from .plugins.news import NewsPlugin
from .plugins.cloud_llm import CloudLLMPlugin
from .plugins.telegram_bot import TelegramBotPlugin
from .plugins.gmail_plugin import GmailPlugin
from .plugins.whatsapp_bridge import WhatsAppBridgePlugin
from .plugins.spotify_plugin import SpotifyPlugin
from .plugins.google_calendar import GoogleCalendarPlugin
from .plugins.apple_health import AppleHealthPlugin
from .plugins.homebridge import HomebridgePlugin
from .skills.loader import SkillLoader
from .skills.importer import SkillImporter
from .mcp.client import MCPManager
from .learning.loop import LearningLoop
from .sandbox import Sandbox
from .bench import LatencyBenchmark
from .plugin_gate import PermissionGate
from .security.guardrails import GuardrailsEngine
from .security.audit import AuditLogger
from .security.types import RedactionMode, SecurityEvent, SecurityEventType, ThreatLevel
from .channels.base import ChannelAdapter
from .channels.web import WebChannel
from .channels.voice import VoiceChannel
from .channels.telegram import TelegramChannel
from .channels.discord import DiscordChannel
from .channels.email import EmailChannel
from .channels.slack import SlackChannel

logger = logging.getLogger("jarvis.orchestrator")

HANDOFF_PREFIX = "[handoff:"
SKILL_PREFIX = "[learn:"


class Orchestrator:
    def __init__(self, config: JarvisConfig):
        self.config = config
        self.agents: dict[str, Agent] = {}
        self.router = IntentRouter(config)
        self.llm_router = LLMRouter()
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
        self.security: Optional[GuardrailsEngine] = None
        self.permission_gate = PermissionGate()
        self.audit = AuditLogger()
        self.session_id: Optional[str] = None
        self.on_token: Optional[Callable] = None

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
            logger.warning("No LLM backend detected — guardrails disabled")

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
        )
        self.plugins["telegram"] = TelegramBotPlugin(
            token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        )
        self.plugins["gmail"] = GmailPlugin(
            access_token=os.environ.get("GMAIL_ACCESS_TOKEN", ""),
        )
        self.plugins["whatsapp"] = WhatsAppBridgePlugin(
            bridge_url=os.environ.get("WHATSAPP_BRIDGE_URL", "http://192.168.1.100:3000"),
        )
        self.plugins["spotify"] = SpotifyPlugin(
            client_id=os.environ.get("SPOTIFY_CLIENT_ID", ""),
            client_secret=os.environ.get("SPOTIFY_CLIENT_SECRET", ""),
            access_token=os.environ.get("SPOTIFY_ACCESS_TOKEN", ""),
            refresh_token=os.environ.get("SPOTIFY_REFRESH_TOKEN", ""),
        )
        self.plugins["google-calendar"] = GoogleCalendarPlugin(
            access_token=os.environ.get("GOOGLE_CALENDAR_TOKEN", ""),
        )
        self.plugins["apple-health"] = AppleHealthPlugin(
            bridge_url=os.environ.get("APPLE_HEALTH_BRIDGE_URL", "http://192.168.1.100:8081"),
        )
        self.plugins["homebridge"] = HomebridgePlugin(
            bridge_url=os.environ.get("HOMEBRIDGE_URL", "http://192.168.1.100:8581"),
            api_token=os.environ.get("HOMEBRIDGE_TOKEN", ""),
        )

        self.skills.discover()
        logger.info(f"Skills loaded: {list(self.skills.skills.keys())}")

        self.checkpoints.initialize()
        restored = self.checkpoints.restore(self)
        if restored:
            logger.info(f"Restored from checkpoint — session: {self.session_id}")

        if not self.session_id:
            self.session_id = self.memory.conversation.current_session_id or self.memory.new_session()
            logger.info(f"Session: {self.session_id}")

    async def register_channel(self, channel: ChannelAdapter):
        self.channels[channel.channel_id] = channel
        logger.info(f"Channel registered: {channel.channel_id}")

    async def start_channels(self):
        for cid, ch in self.channels.items():
            await ch.start()
        logger.info(f"Channels started: {list(self.channels.keys())}")

    async def stop_channels(self):
        for cid, ch in self.channels.items():
            await ch.stop()
        logger.info("Channels stopped")

    async def channel_handler(self, text: str, channel: str = "voice", **kwargs) -> Optional[str]:
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

        try:
            synthesized = await self._synthesize(responses, intent) if len(responses) > 1 or "jarvis" not in responses else list(responses.values())[0]
        except RuntimeError:
            synthesized = "I'm sorry, sir — my language backend is not available. Please start Ollama or LM Studio and try again."
            logger.warning("Returning friendly message: no LLM backend available during synthesize")
        except Exception as e:
            synthesized = f"I hit an issue processing that: {e}"
            logger.warning(f"Synthesize exception: {e}")

        skill_name = self._detect_skill_learning(responses, synthesized, intent)
        if skill_name:
            logger.info(f"Learned new skill: {skill_name}")

        self.memory.add_turn(self.session_id, "assistant", synthesized, agent_id="jarvis")
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

        try:
            _ = self.llm_router.backend
        except RuntimeError:
            msg = "I'm sorry, sir — my language backend is not available. Please start Ollama or LM Studio and try again."
            if on_token:
                on_token(msg)
            return msg

        backend = self.security if self.security else self.llm_router.backend
        synthesized = ""
        for agent_id in target:
            if agent_id in self.agents:
                agent = self.agents[agent_id]
                history = self.memory.get_context(self.session_id, last_n=6)
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
                model = agent.config.get("model", "qwen/qwen3.5-9b")

                checkpoint = self.checkpoints.load(agent_id, self.session_id)
                if checkpoint:
                    prompt = f"[RESUMED FROM CHECKPOINT]\n{checkpoint['prompt']}\n---\n{prompt}"

                if on_token and hasattr(backend, "generate_stream"):
                    response = await backend.generate_stream(
                        model=model, prompt=prompt,
                        system=system_prompt,
                        on_token=on_token,
                    )
                else:
                    response = await backend.generate(
                        model=model, prompt=prompt, system=system_prompt,
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

    async def _gather_plugin_data(self, text: str, intent) -> dict:
        data = {}
        keywords = intent.context.get("keywords_found", [])
        text_lower = text.lower()
        agent_id = intent.target_agents[0] if intent.target_agents else "jarvis"

        if "weather" in keywords or any(w in text_lower for w in ["weather", "vremea", "temperature", "ploaie", "temperatura"]):
            if self.permission_gate.check_call("weather", agent_id):
                wp = self.plugins.get("weather")
                if wp:
                    location = self._extract_location(text)
                    data["weather"] = await wp.get_weather(location)
            else:
                logger.warning(f"Permission denied: agent {agent_id} cannot use weather plugin")

        if "news" in keywords or any(w in text_lower for w in ["news", "stiri", "headlines", "noutati"]):
            if self.permission_gate.check_call("news", agent_id):
                np = self.plugins.get("news")
                if np:
                    category = "general"
                    if any(w in text_lower for w in ["tech", "technology", "tehnologie"]):
                        category = "technology"
                    elif any(w in text_lower for w in ["business", "afaceri"]):
                        category = "business"
                    data["news"] = await np.summarize(category)
            else:
                logger.warning(f"Permission denied: agent {agent_id} cannot use news plugin")

        if "calendar" in keywords or any(w in text_lower for w in ["calendar", "agenda", "program", "sedin", "meeting", "eveniment"]):
            if self.permission_gate.check_call("google-calendar", agent_id):
                gp = self.plugins.get("google-calendar")
                if gp and gp.access_token:
                    data["calendar"] = await gp.get_today_events()

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
                return agent_id, f"[{agent_id} timeout]", 0.0
            except Exception as e:
                self.agents[agent_id]._record_failure(str(e))
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
