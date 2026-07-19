"""
config.py — Jarvis configuration loader.

Loads agents.yaml and provides typed access to all config values.
Also the single home for storage location + tunable limits (audit Q4).
"""

from pathlib import Path
from typing import Optional

import yaml

from agents.core.paths import data_root  # config.py defines its own data_path() below

# ── storage location + tunable limits (Q4) ───────────────────────────────────
# Root directory for on-disk state (JSON stores, SQLite DBs, logs). Override
# with the JARVIS_MEMORY_DIR env var.
MEMORY_DIR = data_root()

NOTES_MAX_LEN = 20_000             # max chars of a session note (H10.21)
ROOM_HISTORY_CAP = 200             # max messages kept per chat room (H10.20)
RUN_HISTORY_MAX_PER_AGENT = 100    # workflow run-history ring per agent (H10.17)


def data_path(*parts: str) -> Path:
    """Build a path under the memory dir, e.g. ``data_path('widgets.json')``."""
    return MEMORY_DIR.joinpath(*parts)


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
        # H23.2 — optional per-agent approved-model allowlist (model pinning /
        # reproducibility). Empty = unrestricted (today's behavior); when set, the
        # router refuses to run this agent on a model not on the list.
        self.approved_models: list[str] = data.get("approved_models", []) or []

        # Plugin permissions this agent needs
        self.plugins: list[str] = data.get("plugins", [])


class JarvisConfig:
    def __init__(self, path: str = "agents/_system/agents.yaml"):
        # A relative path is anchored on the app root (repo checkout in dev,
        # PyInstaller bundle when frozen) instead of the CWD — identical when
        # running from the repo root, but works from anywhere / as an exe.
        p = Path(path)
        if not p.is_absolute():
            from .paths import app_root
            p = app_root() / p
        self.path = p
        self.agents: dict[str, AgentConfig] = {}
        self.general: dict = {}
        self.plugins: dict = {}
        self.bench: dict = {}
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
        self.bench = data.get("bench", {}) or {}

    def get_promotion_rules(self) -> dict:
        """Derive bench-promotion rules from agents.yaml `bench:` entries that
        declare a machine-readable `triggers_on` source + `threshold`."""
        rules = {}
        for bench_id, entry in self.bench.items():
            if not isinstance(entry, dict):
                continue
            source = entry.get("triggers_on")
            if not source:
                continue
            rules[bench_id] = {
                "source": source,
                "threshold": int(entry.get("threshold", 20)),
                "window_days": int(entry.get("window_days", 30)),
            }
        return rules

    def get_active_agents(self) -> list[AgentConfig]:
        return [a for a in self.agents.values() if a.status == "active"]

    def get_agent(self, agent_id: str) -> Optional[AgentConfig]:
        return self.agents.get(agent_id)
