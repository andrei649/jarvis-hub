"""
config.py — Jarvis configuration loader.

Loads agents.yaml and provides typed access to all config values.
"""

import yaml
from pathlib import Path
from typing import Optional


class AgentConfig:
    def __init__(self, data: dict):
        self.id: str = data.get("id", "")
        self.name: str = data.get("name", self.id)
        self.status: str = data.get("status", "active")
        self.model: str = data.get("model", "google/gemma-4-31b-a4b")

        channel_val = data.get("channel", "")
        if isinstance(channel_val, str):
            self.channel = channel_val
        else:
            self.channel = channel_val.get("primary", "voice")
        hb_raw = data.get("heartbeat", False)
        self.heartbeat = hb_raw
        self.has_heartbeat: bool = hb_raw is not False and hb_raw != "no"
        self.tier: str = data.get("tier", "foundation")
        self.llm_policy: str = data.get("llm_policy", "auto")

        # Plugin permissions this agent needs
        self.plugins: list[str] = data.get("plugins", [])


class JarvisConfig:
    def __init__(self, path: str = "agents/_system/agents.yaml"):
        self.path = Path(path)
        self.agents: dict[str, AgentConfig] = {}
        self.general: dict = {}
        self.plugins: dict = {}
        self._load()

    def _load(self):
        if not self.path.exists():
            raise FileNotFoundError(f"Config not found: {self.path}")

        with open(self.path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        for agent_id, agent_data in data.get("agents", {}).items():
            agent_data["id"] = agent_id
            self.agents[agent_id] = AgentConfig(agent_data)

        self.general = data.get("general", {})
        self.plugins = data.get("plugins", {})

    def get_active_agents(self) -> list[AgentConfig]:
        return [a for a in self.agents.values() if a.status == "active"]

    def get_agent(self, agent_id: str) -> Optional[AgentConfig]:
        return self.agents.get(agent_id)
