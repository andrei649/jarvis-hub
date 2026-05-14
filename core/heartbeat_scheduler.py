import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .orchestrator import Orchestrator

logger = logging.getLogger("heartbeat")


class HeartbeatScheduler:
    def __init__(self, orchestrator: "Orchestrator"):
        self.orchestrator = orchestrator
        self._tasks: dict[str, asyncio.Task] = {}

    def start(self):
        for agent_id, config in self.orchestrator._agents.items():
            interval = config.heartbeat_interval_minutes
            if interval and interval > 0:
                task = asyncio.create_task(self._run_heartbeat(agent_id, interval))
                self._tasks[agent_id] = task
                logger.info(f"Heartbeat scheduled for '{agent_id}' every {interval} min")

    def stop(self):
        for agent_id, task in self._tasks.items():
            task.cancel()
        self._tasks.clear()

    async def _run_heartbeat(self, agent_id: str, interval_minutes: int):
        while True:
            try:
                await asyncio.sleep(interval_minutes * 60)
                hb_prompt = self.orchestrator.agent_loader.get_heartbeat_prompt(agent_id)
                if hb_prompt:
                    logger.info(f"[HEARTBEAT] {agent_id} — checking in")
                    response = await self.orchestrator.route(agent_id, hb_prompt, channel="heartbeat")
                    if "HEARTBEAT_OK" not in response.text:
                        logger.info(f"[HEARTBEAT] {agent_id} reported: {response.text[:100]}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[HEARTBEAT] {agent_id} error: {e}")
