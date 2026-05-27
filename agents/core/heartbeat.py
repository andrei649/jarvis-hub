"""
heartbeat.py — Heartbeat scheduler for agents that need periodic self-triggers.

Reads HEARTBEAT.md from each agent directory, parses the cron expression,
and schedules the agent's heartbeat routine using APScheduler.
"""

import logging
from pathlib import Path
from typing import Optional

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
except ImportError:
    AsyncIOScheduler = None

logger = logging.getLogger("jarvis.heartbeat")


class HeartbeatScheduler:
    def __init__(self, agents_dir: str = "agents"):
        self.agents_dir = Path(agents_dir)
        self.scheduler: Optional[AsyncIOScheduler] = None
        self._heartbeat_configs: dict[str, dict] = {}

    def load_all(self):
        """Scan all agent directories for HEARTBEAT.md files."""
        if not self.agents_dir.exists():
            logger.warning(f"Agents directory not found: {self.agents_dir}")
            return
        for agent_dir in self.agents_dir.iterdir():
            if not agent_dir.is_dir():
                continue
            hb_path = agent_dir / "HEARTBEAT.md"
            if hb_path.exists():
                config = self._parse_heartbeat(hb_path)
                if config:
                    self._heartbeat_configs[config["agent"]] = config
                    logger.info(f"Loaded heartbeat: {config['agent']} — {config.get('cadence', 'unknown')}")

    def _parse_heartbeat(self, path: Path) -> Optional[dict]:
        """Parse the YAML frontmatter from a HEARTBEAT.md file."""
        content = path.read_text(encoding="utf-8")
        if not content.startswith("---"):
            return None

        _, frontmatter, _ = content.split("---", 2)
        import yaml
        try:
            return yaml.safe_load(frontmatter)
        except yaml.YAMLError as e:
            logger.error(f"Failed to parse {path}: {e}")
            return None

    def start(self, orchestrator):
        """Start the APScheduler with all loaded heartbeats."""
        if AsyncIOScheduler is None:
            logger.warning("APScheduler not installed, heartbeats disabled")
            return

        self.scheduler = AsyncIOScheduler()

        for agent_id, config in self._heartbeat_configs.items():
            cadence = config.get("cadence", "")
            if cadence.startswith("cron:"):
                cron_expr = cadence[5:]
                parts = cron_expr.strip().split()
                if len(parts) == 5:
                    self.scheduler.add_job(
                        self._run_heartbeat,
                        "cron",
                        minute=parts[0],
                        hour=parts[1],
                        day=parts[2],
                        month=parts[3],
                        day_of_week=parts[4],
                        args=[agent_id, orchestrator],
                        id=f"heartbeat-{agent_id}",
                        replace_existing=True,
                    )
                    logger.info(f"Scheduled heartbeat: {agent_id} @ {cron_expr}")

        self.scheduler.start()
        logger.info("Heartbeat scheduler started")

    async def _run_heartbeat(self, agent_id: str, orchestrator):
        """Execute a single agent's heartbeat."""
        try:
            result = await orchestrator.run_heartbeat(agent_id)
            if result:
                logger.info(f"Heartbeat {agent_id}: {result[:100]}")
        except Exception as e:
            logger.error(f"Heartbeat failed for {agent_id}: {e}")

    def stop(self):
        if self.scheduler:
            self.scheduler.shutdown()
