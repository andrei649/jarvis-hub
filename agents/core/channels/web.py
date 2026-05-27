"""
web.py — Web channel adapter (SSE-based).

Manages connected web clients via Server-Sent Events.
Each client gets a streaming session for real-time responses.
"""

import asyncio
import json
import logging
import time
from typing import Any, Callable, Optional
from uuid import uuid4

from .base import ChannelAdapter

logger = logging.getLogger("jarvis.channels.web")


class WebClient:
    def __init__(self, client_id: str):
        self.id = client_id
        self.queue: asyncio.Queue = asyncio.Queue()
        self.connected_at = time.time()
        self.last_activity = time.time()


class WebChannel(ChannelAdapter):
    def __init__(self, handler: Optional[Callable] = None):
        super().__init__("web", handler)
        self.clients: dict[str, WebClient] = {}
        self._cleanup_task: Optional[asyncio.Task] = None

    async def start(self):
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Web channel started")

    async def stop(self):
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
        for cid in list(self.clients):
            await self.disconnect(cid)
        logger.info("Web channel stopped")

    def connect(self) -> str:
        cid = str(uuid4())[:8]
        self.clients[cid] = WebClient(cid)
        logger.info(f"Web client connected: {cid}")
        return cid

    async def disconnect(self, client_id: str):
        self.clients.pop(client_id, None)
        logger.info(f"Web client disconnected: {client_id}")

    async def send(self, message: str, client_id: str = None, **kwargs) -> bool:
        if client_id:
            client = self.clients.get(client_id)
            if client:
                await client.queue.put({"type": "message", "content": message})
                return True
            return False

        for cid in list(self.clients):
            await self.clients[cid].queue.put({"type": "message", "content": message})
        return bool(self.clients)

    async def send_token(self, token: str, client_id: str):
        client = self.clients.get(client_id)
        if client:
            await client.queue.put({"type": "token", "content": token})

    async def send_done(self, full: str, client_id: str):
        client = self.clients.get(client_id)
        if client:
            await client.queue.put({"type": "done", "content": full})

    async def send_dashboard(self, data: dict):
        payload = {"type": "dashboard", "content": data}
        for cid in list(self.clients):
            await self.clients[cid].queue.put(payload)

    async def receive(self, text: str, client_id: str = None, **kwargs) -> Any:
        logger.info(f"Web input from {client_id}: {text[:40]}")
        return await super().receive(text, client_id=client_id, **kwargs)

    async def event_stream(self, client_id: str):
        client = self.clients.get(client_id)
        if not client:
            return

        try:
            while self._running:
                try:
                    msg = await asyncio.wait_for(client.queue.get(), timeout=30.0)
                    client.last_activity = time.time()
                    yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'ping'})}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            await self.disconnect(client_id)

    async def _cleanup_loop(self):
        while self._running:
            now = time.time()
            stale = [
                cid for cid, c in self.clients.items()
                if now - c.last_activity > 600
            ]
            for cid in stale:
                logger.info(f"Cleaning up stale client: {cid}")
                await self.disconnect(cid)
            await asyncio.sleep(60)
