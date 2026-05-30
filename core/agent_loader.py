from functools import lru_cache
from pathlib import Path
from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator
import yaml


class AgentConfig(BaseModel):
    id: str
    name: str
    model: str = "qwen2.5:7b"
    channel: str = "voice"
    enabled: bool = True
    local_only: bool = False
    heartbeat_interval_minutes: Optional[int] = None
    soul_path: Path
    heartbeat_path: Optional[Path] = None
    dependencies: list[str] = []
    tools: list[str] = []
    plugins: list[str] = []

    @field_validator("enabled", "local_only", mode="before")
    @classmethod
    def coerce_enabled(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.lower() in ("true", "yes", "1")
        return bool(v)

    @field_validator("heartbeat_interval_minutes", mode="before")
    @classmethod
    def coerce_heartbeat(cls, v: Any) -> Optional[int]:
        if v is None:
            return None
        return int(v)


class AgentLoader:
    def __init__(self, agents_dir: str = "agents"):
        self.agents_dir = Path(agents_dir)
        self._cache: dict[str, AgentConfig] = {}
        self._prompt_cache: dict[str, str] = {}

    def discover_all(self) -> list[AgentConfig]:
        agents = []
        for agent_dir in sorted(self.agents_dir.iterdir()):
            if not agent_dir.is_dir() or agent_dir.name.startswith("_"):
                continue
            soul_file = agent_dir / "SOUL.md"
            if not soul_file.exists():
                continue
            config = self._parse_agent_dir(agent_dir)
            agents.append(config)
            self._cache[config.id] = config
        return agents

    def _parse_agent_dir(self, path: Path) -> AgentConfig:
        soul_file = path / "SOUL.md"
        raw = soul_file.read_text()
        frontmatter = self._parse_frontmatter(raw)
        try:
            return AgentConfig(
                id=path.name,
                name=frontmatter.get("name", path.name.title()),
                model=frontmatter.get("model", "qwen2.5:7b"),
                channel=frontmatter.get("channel", "voice"),
                enabled=frontmatter.get("enabled", True),
                local_only=frontmatter.get("local_only", False),
                heartbeat_interval_minutes=frontmatter.get("heartbeat_interval_minutes"),
                soul_path=soul_file,
                heartbeat_path=path / "HEARTBEAT.md" if (path / "HEARTBEAT.md").exists() else None,
                dependencies=frontmatter.get("dependencies", []),
                tools=frontmatter.get("tools", []),
                plugins=frontmatter.get("plugins", []),
            )
        except Exception as e:
            raise ValueError(f"Invalid frontmatter in {soul_file}: {e}") from e

    def _parse_frontmatter(self, raw: str) -> dict:
        import re
        match = re.match(r"^---\n(.*?)\n---", raw, re.DOTALL)
        if not match:
            return {}
        try:
            result = yaml.safe_load(match.group(1))
            return result if isinstance(result, dict) else {}
        except yaml.YAMLError as e:
            raise ValueError(f"YAML parse error in frontmatter: {e}") from e

    def get(self, agent_id: str) -> Optional[AgentConfig]:
        if agent_id in self._cache:
            return self._cache[agent_id]
        path = self.agents_dir / agent_id
        if path.exists() and (path / "SOUL.md").exists():
            return self._parse_agent_dir(path)
        return None

    def get_system_prompt(self, agent_id: str) -> str:
        if agent_id in self._prompt_cache:
            return self._prompt_cache[agent_id]
        config = self.get(agent_id)
        if not config:
            return ""
        raw = config.soul_path.read_text()
        parts = raw.split("---", 2)
        prompt = parts[2].strip() if len(parts) >= 3 else raw.strip()
        self._prompt_cache[agent_id] = prompt
        return prompt

    def get_heartbeat_prompt(self, agent_id: str) -> Optional[str]:
        config = self.get(agent_id)
        if not config or not config.heartbeat_path:
            return None
        return config.heartbeat_path.read_text().strip()

    def invalidate_cache(self, agent_id: Optional[str] = None):
        if agent_id:
            self._cache.pop(agent_id, None)
            self._prompt_cache.pop(agent_id, None)
        else:
            self._cache.clear()
            self._prompt_cache.clear()
