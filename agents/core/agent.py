"""
agent.py — Single agent runtime. Loads SOUL.md, manages model calls,
heartbeat, checkpointing, skill generation, and promotion/demotion tracking.
"""

import logging
import time
from pathlib import Path
from typing import Optional

from .llm.hybrid_router import HybridRouter

logger = logging.getLogger("jarvis.agent")

MAX_FAILURES_BEFORE_DEMOTION = 5
DEMOTION_TIERS = {
    "command": ["business", "tech", "foundation"],
    "business": ["tech", "foundation"],
    "tech": ["foundation"],
    "foundation": [],
}


class _NullCtx:
    """No-op async context manager — used when H22.5 residency tracking is off
    so the generate path stays a plain `async with` either way."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class Agent:
    def __init__(self, agent_id: str, config: dict, llm_router: HybridRouter = None, permission_gate=None):
        self.id = agent_id
        self.name = config.get("name", agent_id)
        self.config = config
        self.soul: dict = {}
        hb_raw = config.get("heartbeat", False)
        self.has_heartbeat = hb_raw is not False and hb_raw != "no"
        self._heartbeat_config: dict = None
        self.llm_router = llm_router
        self.permission_gate = permission_gate
        # Optional guardrails wrapper; set by Orchestrator.load_agents when
        # security is enabled. Default None so process() works without it.
        self.guardrails = None
        self._failures = 0
        self._last_latency = 0.0
        self._checkpoint_manager = None
        self._load_soul()

    def _load_soul(self):
        # Personalization overlay: the repo ships generic SOUL.md templates; the
        # owner's personalized copy lives in SOUL.local.md (gitignored, never
        # committed) and wins when present. See docs/ARCHITECTURE.md §8.
        soul_path = Path(f"agents/{self.id}/SOUL.local.md")
        if not soul_path.exists():
            soul_path = Path(f"agents/{self.id}/SOUL.md")
        if soul_path.exists():
            content = soul_path.read_text(encoding="utf-8")
            # H21.2: split optional YAML front-matter (personality/affect config)
            # from the prose body. No front-matter → ({}, full text) = no-op.
            try:
                from .cognition.frontmatter import parse_frontmatter
                meta, body = parse_frontmatter(content)
            except Exception:
                meta, body = {}, content
            self.soul = {"content": body, "path": soul_path, "meta": meta}
            logger.info(f"Loaded SOUL for {self.id} ({len(content)} chars)")
        else:
            logger.warning(f"SOUL.md not found for {self.id}")

    @property
    def last_latency(self) -> float:
        return self._last_latency

    def set_checkpoint_manager(self, mgr):
        self._checkpoint_manager = mgr

    def _gen_params(self, route_name: str = "") -> tuple[int, float]:
        """Resolve (max_tokens, temperature) from runtime settings.

        The deep reasoning slot gets a much larger budget — a reasoning model
        burns 1–2k tokens on chain-of-thought before the answer, so the normal
        cap truncates it mid-thought. Degrades to sane defaults off-config."""
        try:
            from .settings_db import get_value
            max_tokens = int(get_value("llm", "max_tokens", 2048))
            deep_max = int(get_value("llm", "deep_max_tokens", 8192))
            temperature = float(get_value("llm", "temperature", 0.7))
        except Exception:
            max_tokens, deep_max, temperature = 2048, 8192, 0.7
        return (deep_max if route_name == "local-deep" else max_tokens), temperature

    async def process(self, text: str, context: dict) -> str:
        system_prompt = self.soul.get("content", "")
        model = self.config.get("model", "google/gemma-4-31b-a4b")
        if self.id == "howard" and hasattr(self.llm_router, 'get_howard_model'):
            model = self.llm_router.get_howard_model()

        if not self.llm_router:
            return f"[{self.name} no LLM backend]"

        agent_context = context.get("agent_context", {})
        agent_block = ""
        if agent_context:
            agent_block = f"Agent memory: {agent_context}\n"

        skills = context.get("skills", [])
        skills_block = ""
        if skills:
            skill_descs = "\n".join(f"  - {s['command']}: {s['description']}" for s in skills)
            skills_block = f"Available skills:\n{skill_descs}\n\n"

        rag_block = ""
        if self.id == "howard":
            try:
                from .ingestion.pipeline import IngestionPipeline
                pipeline = IngestionPipeline()
                similar = pipeline.search_similar(text, k=5, only_me=True)
                if similar:
                    shot_lines = [f"- Andrei: \"{m.text}\"" for m in similar]
                    rag_block = "Here are some of your past matching responses from the archive (RAG), mirroring your stylometry, tone, and opinions:\n" + "\n".join(shot_lines) + "\n\n"
                    logger.info(f"Howard RAG: injected {len(similar)} few-shot messages")
            except Exception as e:
                logger.warning(f"Howard RAG lookup failed: {e}")

        prompt = (
            f"{skills_block}{agent_block}{rag_block}"
            f"User said: {text}\n"
            f"Respond as {self.name}.\n\n"
            f"IMPORTANT: If this is a complex multi-step task you solved elegantly, "
            f"end your response with '[learn: task description | step1,step2,step3 | command_name]' "
            f"to save it as a reusable skill. "
            f"You can also hand off to another agent with '[handoff:agent_id]'."
        )

        res = self.llm_router.select_backend(self.id, prompt)
        route_name = ""
        if isinstance(res, tuple) and len(res) == 3:
            backend, routed_model, route_name = res
            if routed_model:
                model = routed_model
        else:
            backend, _ = res
        if self.guardrails:
            backend = self.guardrails

        if self._checkpoint_manager:
            self._checkpoint_manager.save_agent_execution(self.id, context.get("session_id", "unknown"), prompt)

        # H22.5 — best-effort local model residency (LRU swap fast↔deep). Default
        # OFF via JARVIS_MODEL_MANAGER; a no-op for cloud/Claude routes and when
        # no manager is attached. ensure_resident swaps the LRU local model out
        # before loading this one (never raises); `using()` ref-counts the model
        # so a concurrent request can't evict it mid-generate. Both degrade to a
        # no-op when the kill-switch is off, leaving today's behavior unchanged.
        manager = getattr(self.llm_router, "model_manager", None)
        await self._ensure_resident(route_name, model)
        residency = manager.using(model) if (manager is not None and route_name.startswith("local")) else _NullCtx()

        max_tokens, temperature = self._gen_params(route_name)
        start = time.monotonic()
        try:
            async with residency:
                response = await backend.generate(
                    model=model,
                    prompt=prompt,
                    system=system_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            latency = time.monotonic() - start
            self._last_latency = latency

            if self._checkpoint_manager:
                self._checkpoint_manager.record_call(self.id, success=True, latency=latency)
                self._checkpoint_manager.clear_agent_checkpoint(self.id, context.get("session_id", "unknown"))

            self._failures = 0
            return response
        except Exception as e:
            latency = time.monotonic() - start
            self._last_latency = latency
            self._record_failure(str(e))
            if self._checkpoint_manager:
                self._checkpoint_manager.record_call(self.id, success=False, latency=latency, error=str(e))
            raise

    async def _ensure_resident(self, route_name: str, model: str) -> None:
        """H22.5 best-effort residency hook — guarded, no-op when disabled.

        Delegates to the router's ensure_resident (which only acts for local
        routes and when the ModelManager kill-switch is on). Wrapped so a hook
        failure can never break a generate; the manager itself also never
        raises, this is belt-and-braces."""
        router = self.llm_router
        ensure = getattr(router, "ensure_resident", None)
        if ensure is None:
            return
        try:
            await ensure(model, route_name)
        except Exception:
            logger.debug("model residency hook failed for %s/%s", route_name, model, exc_info=True)

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

    async def synthesize(self, responses: dict[str, str], intent, in_character: bool = False) -> str:
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

        model = self.config.get("model", "google/gemma-4-31b-a4b")
        system_prompt = self.soul.get("content", "")

        if in_character:
            directive = (
                "Weave these specialist answers into one coherent reply, but PRESERVE each "
                "specialist's distinct voice and attribute their contributions in character. "
                "Be honest and direct — do not flatter, over-agree, or reverse a correct claim "
                "to please. Use the user's language."
            )
        else:
            directive = "Be concise. Use the user's language. Do not mention internal agent IDs."
        prompt = (
            f"Synthesize the following specialist responses into a single, coherent reply for the user:\n"
            f"{agent_reports}\n\n"
            f"{directive}"
        )

        try:
            res = self.llm_router.select_backend("jarvis", prompt)
            route_name = ""
            if isinstance(res, tuple) and len(res) == 3:
                backend, _, route_name = res
            else:
                backend, _ = res
            if self.guardrails:
                backend = self.guardrails

            # H22.5 — best-effort local model residency, same guarded pattern as
            # process(): default OFF via JARVIS_MODEL_MANAGER, a no-op for
            # cloud/Claude routes and when no manager is attached. ensure_resident
            # swaps the LRU local model before loading this one (never raises);
            # using() ref-counts it so a concurrent request can't evict mid-generate.
            manager = getattr(self.llm_router, "model_manager", None)
            await self._ensure_resident(route_name, model)
            residency = manager.using(model) if (manager is not None and route_name.startswith("local")) else _NullCtx()

            max_tokens, temperature = self._gen_params(route_name)
            async with residency:
                response = await backend.generate(
                    model=model,
                    prompt=prompt,
                    system=system_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
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

    async def run_heartbeat(self, orchestrator=None) -> Optional[str]:
        """Execute the agent's heartbeat checklist."""
        logger.info(f"Heartbeat: {self.id}")
        hb_config = self._heartbeat_config or {}
        checklist = hb_config.get("checklist", [])

        if not checklist:
            return None

        results = []
        for item in checklist:
            try:
                result = await self._execute_heartbeat_item(item, orchestrator)
                results.append(f"[OK] {item}: {result}")
            except Exception as e:
                results.append(f"[FAIL] {item}: {e}")

        summary = f"{self.name} heartbeat: " + "; ".join(results)
        logger.info(summary)
        return summary

    async def _execute_heartbeat_item(self, item: str, orchestrator=None) -> str:
        """Execute a single heartbeat checklist item, routing to the right skill."""
        item_lower = item.lower()

        if "brief" in item_lower or "morning" in item_lower:
            return await self._run_skill(orchestrator, "brief", "")

        if "weather" in item_lower:
            return await self._run_skill(orchestrator, "weather", "")

        if "news" in item_lower:
            return await self._run_skill(orchestrator, "brief", "")

        if "calendar" in item_lower or "agenda" in item_lower:
            return await self._run_skill(orchestrator, "calendar", "today")

        if "health" in item_lower:
            return await self._run_skill(orchestrator, "health", "summary")

        if "email" in item_lower or "inbox" in item_lower or "triage" in item_lower:
            return await self._run_skill(orchestrator, "email_triage", "triage")

        if "system" in item_lower or "status" in item_lower:
            return await self._run_skill(orchestrator, "system_status", "")

        if "security" in item_lower or "scan" in item_lower:
            return await self._run_skill(orchestrator, "security_scan", "")

        return f"checklist item executed: {item}"

    async def _run_skill(self, orchestrator, skill_name: str, args: str = "") -> str:
        """Execute a skill via the orchestrator's skill loader."""
        if not orchestrator:
            return f"skill {skill_name} not available (no orchestrator)"

        try:
            skill = orchestrator.skills.get_skill(skill_name)
            if skill:
                return await skill.execute(skill_name, args, {})
            return f"skill {skill_name} not found"
        except Exception as e:
            logger.error(f"Heartbeat skill {skill_name} failed: {e}")
            return f"skill {skill_name} error: {e}"
