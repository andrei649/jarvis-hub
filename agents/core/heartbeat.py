"""
heartbeat.py — Heartbeat scheduler for agents that need periodic self-triggers.

Reads HEARTBEAT.md from each agent directory for cron expressions, and
agents.yaml for interval-based heartbeats. Schedules agent routines
using APScheduler with jitter and MIN_HEARTBEAT_INTERVAL guardrails.
"""

import logging
import random
from pathlib import Path
from typing import Optional

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.schedulers import SchedulerNotRunningError
except ImportError:
    AsyncIOScheduler = None
    SchedulerNotRunningError = None

logger = logging.getLogger("jarvis.heartbeat")

MIN_HEARTBEAT_INTERVAL = 3600
JITTER_MIN = 15
JITTER_MAX = 30


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
            # Personalization overlay: HEARTBEAT.local.md (gitignored) wins over
            # the shipped template — same convention as SOUL.local.md.
            hb_path = agent_dir / "HEARTBEAT.local.md"
            if not hb_path.exists():
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

    def _cron_fires_per_day(self, parts: list[str]) -> float:
        """Estimate how many times a cron expression fires in a 24h period."""
        minute, hour, day, month, dow = parts
        hour_count = self._field_count(hour, 24)
        minute_count = self._field_count(minute, 60)
        if hour_count == 0 or minute_count == 0:
            return 0
        base = float(hour_count * minute_count)
        if dow != "*":
            base *= max(0.01, self._field_count(dow, 7) / 7)
        if day != "*":
            base *= max(0.01, self._field_count(day, 31) / 31)
        if month != "*":
            base *= max(0.01, self._field_count(month, 12) / 12)
        return base

    def _field_count(self, field: str, max_val: int) -> int:
        """Count distinct values a cron field can match (approximate)."""
        field = field.strip()
        if field == "*":
            return max_val
        if "/" in field:
            if field.startswith("*/"):
                step = int(field[2:])
                return max(1, max_val // step)
            base, step = field.split("/")
            base_count = self._field_count(base, max_val)
            step_val = int(step)
            return max(1, base_count // step_val)
        parts = [p.strip() for p in field.split(",")]
        total = 0
        for p in parts:
            if "-" in p:
                lo, hi = p.split("-")
                total += int(hi) - int(lo) + 1
            else:
                try:
                    int(p)
                    total += 1
                except ValueError:
                    return max_val
        return total

    def load_from_config(self, config):
        """Load heartbeat intervals from JarvisConfig (agents.yaml)."""
        for agent_id, agent_cfg in config.agents.items():
            if agent_cfg.status != "active":
                continue
            if not agent_cfg.has_heartbeat:
                continue
            interval_str = agent_cfg.heartbeat if hasattr(agent_cfg, 'heartbeat') else None
            if not isinstance(interval_str, str) or interval_str == "no":
                continue
            seconds = self._parse_interval(interval_str)
            seconds = self._coerce_interval(seconds)
            self._heartbeat_configs[agent_id] = {
                "agent": agent_id,
                "cadence": f"interval:{seconds}",
                "interval_seconds": seconds,
            }
            logger.info(f"Loaded heartbeat from config: {agent_id} — {interval_str} ({seconds}s)")

    def _parse_interval(self, interval_str: str) -> int:
        """Convert a human-readable interval string to seconds."""
        interval_str = interval_str.strip().lower()
        if interval_str.endswith("h"):
            return int(interval_str[:-1]) * 3600
        elif interval_str.endswith("m"):
            return int(interval_str[:-1]) * 60
        elif interval_str.endswith("s"):
            return int(interval_str[:-1])
        else:
            try:
                return int(interval_str)
            except ValueError:
                logger.warning(f"Unrecognized heartbeat interval: {interval_str}, defaulting to {MIN_HEARTBEAT_INTERVAL}s")
                return MIN_HEARTBEAT_INTERVAL

    def _coerce_interval(self, seconds: int) -> int:
        """Apply MIN_HEARTBEAT_INTERVAL guardrail."""
        if seconds < MIN_HEARTBEAT_INTERVAL:
            logger.warning(
                f"Heartbeat interval {seconds}s is below minimum {MIN_HEARTBEAT_INTERVAL}s, coercing upward"
            )
            return MIN_HEARTBEAT_INTERVAL
        return seconds

    def start(self, orchestrator):
        """Start the APScheduler with all loaded heartbeats (cron + interval)."""
        if AsyncIOScheduler is None:
            logger.warning("APScheduler not installed, heartbeats disabled")
            return

        if self.scheduler is None:
            self.scheduler = AsyncIOScheduler()

        for agent_id, config in self._heartbeat_configs.items():
            cadence = config.get("cadence", "")
            if cadence.startswith("interval:"):
                seconds = int(cadence.split(":")[1])
                jitter = random.randint(JITTER_MIN, JITTER_MAX)
                self.scheduler.add_job(
                    self._run_heartbeat,
                    "interval",
                    seconds=seconds,
                    args=[agent_id, orchestrator],
                    id=f"heartbeat-{agent_id}",
                    replace_existing=True,
                    jitter=jitter,
                )
                hours = seconds // 3600
                minutes = (seconds % 3600) // 60
                logger.info(f"Scheduled heartbeat: {agent_id} @ {hours}h{minutes}m interval (jitter={jitter}s)")
            elif cadence.startswith("cron:"):
                cron_expr = cadence[5:]
                parts = cron_expr.strip().split()
                if len(parts) == 5:
                    fires_per_day = self._cron_fires_per_day(parts)
                    if fires_per_day > 24:
                        avg_interval = 86400 / fires_per_day
                        logger.warning(
                            f"Heartbeat {agent_id} fires ~{fires_per_day:.0f}x/day "
                            f"(avg interval ~{avg_interval:.0f}s, min is {MIN_HEARTBEAT_INTERVAL}s). "
                            f"Cron: {cron_expr}"
                        )
                    jitter = random.randint(JITTER_MIN, JITTER_MAX)
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
                        jitter=jitter,
                    )
                    logger.info(f"Scheduled heartbeat: {agent_id} @ {cron_expr} (jitter={jitter}s)")

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
            try:
                self.scheduler.shutdown()
            except SchedulerNotRunningError:
                pass

    def get_status(self):
        """Return status of all scheduled heartbeats."""
        if not self.scheduler:
            return {"scheduler_running": False, "heartbeats": []}
        
        heartbeats = []
        for job in self.scheduler.get_jobs():
            if job.id.startswith("heartbeat-"):
                agent_id = job.id.replace("heartbeat-", "")
                heartbeats.append({
                    "agent_id": agent_id,
                    "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                    "trigger": str(job.trigger),
                })
        
        return {
            "scheduler_running": self.scheduler.running,
            "heartbeats": heartbeats,
        }

    def start_heartbeat(self, agent_id: str, orchestrator):
        """Start a single heartbeat job."""
        if not self.scheduler or not self.scheduler.running:
            return False
        
        config = self._heartbeat_configs.get(agent_id)
        if not config:
            return False
        
        cadence = config.get("cadence", "")
        if cadence.startswith("interval:"):
            seconds = int(cadence.split(":")[1])
            jitter = random.randint(JITTER_MIN, JITTER_MAX)
            self.scheduler.add_job(
                self._run_heartbeat,
                "interval",
                seconds=seconds,
                args=[agent_id, orchestrator],
                id=f"heartbeat-{agent_id}",
                replace_existing=True,
                jitter=jitter,
            )
            return True
        elif cadence.startswith("cron:"):
            cron_expr = cadence[5:]
            parts = cron_expr.strip().split()
            if len(parts) == 5:
                jitter = random.randint(JITTER_MIN, JITTER_MAX)
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
                    jitter=jitter,
                )
                return True
        return False

    def stop_heartbeat(self, agent_id: str):
        """Stop a single heartbeat job."""
        if not self.scheduler:
            return False
        try:
            self.scheduler.remove_job(f"heartbeat-{agent_id}")
            return True
        except Exception:
            return False

    async def run_now(self, agent_id: str, orchestrator):
        """Run a heartbeat immediately."""
        await self._run_heartbeat(agent_id, orchestrator)
        return True
