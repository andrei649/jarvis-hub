import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

import httpx

from .agent_loader import AgentLoader, AgentConfig
from .plugin_manager import PluginManager
from .memory_manager import MemoryManager
from .heartbeat_scheduler import HeartbeatScheduler
from .bridge_responder import BridgeResponder
from .claude_responder import ClaudeResponder

logger = logging.getLogger("orchestrator")


@dataclass
class AgentResponse:
    text: str
    agent_id: str
    escalated_to: Optional[str] = None
    specialized: Optional[str] = None
    error: Optional[str] = None


class Orchestrator:
    def __init__(
        self,
        agents_dir: str = "agents",
        plugins_dir: str = "plugins",
        ollama_host: str = "http://localhost:11434",
        cns_agent_id: str = "jarvis",
        request_timeout: float = 60.0,
        max_retries: int = 2,
    ):
        self.agent_loader = AgentLoader(agents_dir)
        self.plugin_manager = PluginManager(plugins_dir)
        self.memory = MemoryManager()
        self.heartbeat = HeartbeatScheduler(self)
        self.bridge = BridgeResponder()
        self.claude = ClaudeResponder()
        self._agents: dict[str, AgentConfig] = {}
        self._ollama_host = ollama_host.rstrip("/")
        self._cns_agent_id = cns_agent_id
        self._request_timeout = request_timeout
        self._max_retries = max_retries
        self._client: Optional[httpx.AsyncClient] = None
        self._running = False

    async def start(self):
        logger.info("Starting Jarvis Hub orchestrator...")
        self._client = httpx.AsyncClient(timeout=self._request_timeout)
        await self.claude.start()
        await self.plugin_manager.load_all()
        agents = self.agent_loader.discover_all()
        for agent in agents:
            self._agents[agent.id] = agent
            logger.info(f"Registered agent: {agent.id} ({agent.name})")
        self.heartbeat.start()
        self._running = True
        logger.info(f"Orchestrator ready — {len(agents)} agents loaded")

    async def stop(self):
        self._running = False
        self.heartbeat.stop()
        await self.plugin_manager.shutdown_all()
        await self.claude.stop()
        if self._client:
            await self._client.aclose()
        logger.info("Orchestrator stopped")

    async def route(
        self, agent_id: str, message: str, channel: str = "voice", context: Optional[dict] = None
    ) -> AgentResponse:
        agent = self._agents.get(agent_id)
        if not agent:
            return AgentResponse(
                text=f"Agent '{agent_id}' not found.", agent_id=agent_id, error="not_found"
            )
        if not agent.enabled:
            return AgentResponse(
                text=f"Agent '{agent.name}' is disabled.", agent_id=agent_id, error="disabled"
            )

        system_prompt = self.agent_loader.get_system_prompt(agent_id)
        memory_context = await self.memory.get_relevant(agent_id, message)
        full_prompt = self._build_prompt(system_prompt, memory_context, message, context)
        response = await self._call_llm(agent.model, full_prompt, agent_id)

        await self.memory.store(agent_id, message, response)
        logger.info(f"[{agent_id}] → {response[:80]}...")
        return AgentResponse(text=response, agent_id=agent_id)

    async def route_to_cns(
        self, message: str, channel: str = "voice", context: Optional[dict] = None
    ) -> AgentResponse:
        jarvis_resp = await self.route(self._cns_agent_id, message, channel, context)
        if self._needs_escalation(jarvis_resp.text):
            target = self._extract_target(jarvis_resp.text)
            specialized = await self.route(target, message, channel, context)
            return AgentResponse(
                text=jarvis_resp.text,
                agent_id=self._cns_agent_id,
                escalated_to=target,
                specialized=specialized.text,
            )
        return jarvis_resp

    def _needs_escalation(self, response: str) -> bool:
        markers = ["[escalează la:", "[deleg către:", "[route to:", "[[AGENT:"]
        return any(m in response.lower() for m in markers)

    def _extract_target(self, response: str) -> str:
        import re
        for pattern in [
            r"\[escalează la:\s*(\w+)\]",
            r"\[deleg către:\s*(\w+)\]",
            r"\[route to:\s*(\w+)\]",
            r"\[\[AGENT:\s*(\w+)\]\]",
        ]:
            match = re.search(pattern, response, re.IGNORECASE)
            if match:
                return match.group(1).lower()
        return "pepper"

    def _build_prompt(
        self, system_prompt: str, memory_context: str, message: str, context: Optional[dict]
    ) -> str:
        parts = [system_prompt]
        if memory_context:
            parts.append(f"\n[Relevant context from memory]:\n{memory_context}")
        if context:
            ctx_str = "\n".join(f"{k}: {v}" for k, v in context.items())
            parts.append(f"\n[Current context]:\n{ctx_str}")
        parts.append(f"\n[User]: {message}")
        parts.append("\n[You]:")
        return "\n".join(parts)

    async def _call_llm(self, model: str, prompt: str, agent_id: str = "unknown") -> str:
        if self.claude.is_available():
            result = await self.claude.ask(model, prompt, agent_id)
            if result:
                return result

        if self._client:
            last_error = None
            for attempt in range(1 + self._max_retries):
                try:
                    resp = await self._client.post(
                        f"{self._ollama_host}/api/generate",
                        json={"model": model, "prompt": prompt, "stream": False},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    return data.get("response", "")
                except httpx.TimeoutException as e:
                    last_error = f"Request timed out (attempt {attempt + 1}/{1 + self._max_retries})"
                    logger.warning(f"LLM timeout ({model}): {last_error}")
                except httpx.HTTPStatusError as e:
                    last_error = f"HTTP {e.response.status_code}"
                    logger.warning(f"LLM HTTP error ({model}): {last_error}")
                    if attempt < self._max_retries:
                        await asyncio.sleep(2 ** attempt)
                    else:
                        break
                except Exception as e:
                    last_error = str(e)
                    logger.error(f"LLM call failed ({model}): {last_error}")
                    if attempt < self._max_retries:
                        await asyncio.sleep(2 ** attempt)
                    else:
                        break
        else:
            logger.warning("Orchestrator client not started — skipping Ollama")

        logger.info(f"[BRIDGE] Falling back to file bridge for {model}")
        loop = asyncio.get_event_loop()
        answer = await loop.run_in_executor(
            None, self.bridge.ask, model, prompt, agent_id
        )
        return answer

    def get_agent_list(self) -> list[dict]:
        return [
            {
                "id": a.id,
                "name": a.name,
                "model": a.model,
                "channel": a.channel,
                "enabled": a.enabled,
                "has_heartbeat": a.heartbeat_path is not None,
            }
            for a in self._agents.values()
        ]
