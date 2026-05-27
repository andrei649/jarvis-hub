"""
agent.py — Single agent runtime. Loads SOUL.md, manages model calls,
heartbeat, checkpointing, skill generation, and promotion/demotion tracking.
"""

import logging
import time
from pathlib import Path
from typing import Optional

from .llm.router import LLMRouter

logger = logging.getLogger("jarvis.agent")

MAX_FAILURES_BEFORE_DEMOTION = 5
DEMOTION_TIERS = {
    "command": ["business", "tech", "foundation"],
    "business": ["tech", "foundation"],
    "tech": ["foundation"],
    "foundation": [],
}


class Agent:
    def __init__(self, agent_id: str, config: dict, llm_router: LLMRouter = None):
        self.id = agent_id
        self.name = config.get("name", agent_id)
        self.config = config
        self.soul: dict = {}
        self.has_heartbeat = config.get("heartbeat", False)
        self.llm_router = llm_router
        self._failures = 0
        self._checkpoint_manager = None
        self._load_soul()

    def _load_soul(self):
        soul_path = Path(f"agents/{self.id}/SOUL.md")
        if soul_path.exists():
            content = soul_path.read_text(encoding="utf-8")
            self.soul = {"content": content, "path": soul_path}
            logger.info(f"Loaded SOUL for {self.id} ({len(content)} chars)")
        else:
            logger.warning(f"SOUL.md not found for {self.id}")

    def set_checkpoint_manager(self, mgr):
        self._checkpoint_manager = mgr

    async def process(self, text: str, context: dict) -> str:
        system_prompt = self.soul.get("content", "")
        model = self.config.get("model", "google/gemma-4-26b-a4b")

        if not self.llm_router:
            return f"[{self.name} no LLM backend]"

        backend = self.llm_router.backend

        agent_context = context.get("agent_context", {})
        agent_block = ""
        if agent_context:
            agent_block = f"Agent memory: {agent_context}\n"

        skills = context.get("skills", [])
        skills_block = ""
        if skills:
            skill_descs = "\n".join(f"  - {s['command']}: {s['description']}" for s in skills)
            skills_block = f"Available skills:\n{skill_descs}\n\n"

        prompt = (
            f"{skills_block}{agent_block}"
            f"User said: {text}\n"
            f"Respond as {self.name}.\n\n"
            f"IMPORTANT: If this is a complex multi-step task you solved elegantly, "
            f"end your response with '[learn: task description | step1,step2,step3 | command_name]' "
            f"to save it as a reusable skill. "
            f"You can also hand off to another agent with '[handoff:agent_id]'."
        )

        if self._checkpoint_manager:
            self._checkpoint_manager.save_agent_execution(self.id, context.get("session_id", "unknown"), prompt)

        start = time.monotonic()
        try:
            response = await backend.generate(
                model=model,
                prompt=prompt,
                system=system_prompt,
            )
            latency = time.monotonic() - start

            if self._checkpoint_manager:
                self._checkpoint_manager.record_call(self.id, success=True, latency=latency)
                self._checkpoint_manager.clear_agent_checkpoint(self.id, context.get("session_id", "unknown"))

            self._failures = 0
            return response
        except Exception as e:
            latency = time.monotonic() - start
            self._record_failure(str(e))
            if self._checkpoint_manager:
                self._checkpoint_manager.record_call(self.id, success=False, latency=latency, error=str(e))
            raise

    def _record_failure(self, reason: str = "unknown"):
        self._failures += 1
        logger.warning(f"Agent {self.id} failure #{self._failures}/{MAX_FAILURES_BEFORE_DEMOTION}: {reason}")

    @property
    def should_demote(self) -> bool:
        return self._failures >= MAX_FAILURES_BEFORE_DEMOTION

    def get_demotion_target(self) -> Optional[str]:
        current_tier = self.config.get("tier", "foundation")
        available = DEMOTION_TIERS.get(current_tier, [])
        return available[0] if available else None

    async def synthesize(self, responses: dict[str, str], intent) -> str:
        jarvis_only = all(k == "jarvis" for k in responses)
        if jarvis_only:
            return responses.get("jarvis", "Done, sir.")

        agent_reports = ""
        for agent_id, resp in responses.items():
            if agent_id != "jarvis" and resp:
                clean = self._strip_control_tokens(resp)
                agent_reports += f"\n{agent_id}: {clean}"

        if not agent_reports.strip() or not self.llm_router:
            parts = []
            for agent_id, resp in responses.items():
                if agent_id != "jarvis" and resp:
                    parts.append(f"[{agent_id}]: {self._strip_control_tokens(resp)}")
            return " | ".join(parts) if parts else "Done, sir."

        model = self.config.get("model", "google/gemma-4-26b-a4b")
        system_prompt = self.soul.get("content", "")

        prompt = (
            f"Synthesize the following specialist responses into a single, coherent reply for the user:\n"
            f"{agent_reports}\n\n"
            f"Be concise. Use the user's language. Do not mention internal agent IDs."
        )

        try:
            backend = self.llm_router.backend
            response = await backend.generate(
                model=model,
                prompt=prompt,
                system=system_prompt,
            )
            return response
        except RuntimeError:
            parts = []
            for agent_id, resp in responses.items():
                if agent_id != "jarvis" and resp:
                    parts.append(f"[{agent_id}]: {self._strip_control_tokens(resp)}")
            return " | ".join(parts) if parts else "Done, sir."

    def _strip_control_tokens(self, text: str) -> str:
        import re
        text = re.sub(r'\[learn:[^\]]+\]', '', text)
        text = re.sub(r'\[handoff:[^\]]+\]', '', text)
        return text.strip()

    async def run_heartbeat(self) -> Optional[str]:
        logger.info(f"Running heartbeat for {self.id}")
        return f"[{self.id} heartbeat OK]"
