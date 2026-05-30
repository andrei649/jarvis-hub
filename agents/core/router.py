"""
router.py — Intent classifier. Determines which agent(s) should handle input.
"""

import logging
from typing import Optional

logger = logging.getLogger("jarvis.router")


class Intent:
    def __init__(self, target_agents: list[str], is_general: bool, context: dict):
        self.target_agents = target_agents
        self.is_general = is_general
        self.context = context


class IntentRouter:
    """Routes input to the correct agent(s) based on keywords and context."""

    # Simple keyword-based routing for v0.1.0.
    # Will be upgraded to LLM-based classification in v0.2.0.
    ROUTING_TABLE = {
        "jarvis": ["jarvis"],
        "friday": ["friday"],
        "pepper": ["pepper"],
        "jerome": ["jerome"],
        "athena": ["athena"],
        "stark": ["stark"],
        "veronica": ["veronica"],
        "vision": ["vision"],
        "steve": ["steve"],
        "oracle": ["oracle"],
        "ultron": ["ultron"],
        "gecko": ["gecko"],
        "hercules": ["hercules"],
        "hephaestus": ["hephaestus"],
        "frigga": ["frigga"],
        "howard": ["howard"],
    }

    INTENT_KEYWORDS = {
        "weather": ["friday"],
        "news": ["friday"],
        "calendar": ["pepper"],
        "meeting": ["pepper"],
        "schedule": ["pepper"],
        "email": ["pepper", "veronica", "stark"],
        "write": ["veronica"],
        "draft": ["veronica"],
        "linkedin": ["veronica"],
        "instagram": ["veronica"],
        "research": ["vision"],
        "search": ["vision"],
        "kpi": ["stark"],
        "raiffeisen": ["stark"],
        "board": ["stark"],
        "strategy": ["athena"],
        "career": ["athena"],
        "digitaholic": ["athena"],
        "money": ["gecko"],
        "finance": ["gecko"],
        "budget": ["gecko"],
        "sleep": ["hercules"],
        "workout": ["hercules"],
        "fitness": ["hercules"],
        "cosmina": ["hephaestus"],
        "bmw": ["hephaestus"],
        "car": ["hephaestus"],
        "max": ["frigga"],
        "family": ["frigga"],
        "alexandra": ["frigga"],
        "beads": ["frigga", "veronica"],
        "howard": ["howard"],
        "archive": ["howard"],
        "digital twin": ["howard"],
        "what would i": ["howard"],
        "what did i": ["howard"],
        "what have i": ["howard"],
        "what do i": ["howard"],
        "remember": ["howard"],
        "who is": ["howard", "jarvis"],
        "what do you know about": ["howard"],
        "how would i": ["howard"],
        "voice": ["howard"],
        "music": ["jerome"],
        "playlist": ["jerome"],
        "game": ["jerome"],
        "infrastructure": ["steve"],
        "server": ["steve"],
        "backup": ["steve"],
        "security": ["ultron"],
        "automation": ["oracle"],
        "workflow": ["oracle"],
        "route": ["jarvis"],
        "what can you": ["jarvis"],
        "who are you": ["jarvis"],
        "hello": ["jarvis"],
        "morning": ["jarvis"],
        "help": ["jarvis"],
    }

    def __init__(self, config):
        self.config = config

    async def classify(self, text: str, agents: dict) -> Intent:
        """
        Classify input intent. Returns list of target agents + context.
        Two-stage: check wake-word first, then keyword match, then fallback.
        """
        text_lower = text.lower().strip()

        # Stage 1: wake word prefix (e.g. "Jarvis, what's the weather")
        wake_agents = self._check_wake_word(text_lower)
        if wake_agents and len(wake_agents) == 1:
            # Direct agent call
            return Intent(
                target_agents=[wake_agents[0]],
                is_general=False,
                context={"source": "wake_word", "agent": wake_agents[0]}
            )

        # Stage 2: keyword matching
        matched = set()
        for keyword, agent_ids in self.INTENT_KEYWORDS.items():
            if keyword in text_lower:
                matched.update(agent_ids)

        if matched:
            return Intent(
                target_agents=list(matched),
                is_general=False,
                context={"source": "keyword_match", "keywords_found": list(matched)}
            )

        # Stage 3: general chat — goes to Jarvis
        return Intent(
            target_agents=["jarvis"],
            is_general=True,
            context={"source": "general"}
        )

    def _check_wake_word(self, text: str) -> Optional[list[str]]:
        """Check if text starts with an agent wake word."""
        for agent_id in self.ROUTING_TABLE:
            if text.startswith(agent_id) or text.startswith(f"hey {agent_id}"):
                return [agent_id]
        return None
