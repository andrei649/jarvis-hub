"""One private upstream connection, correlated replies and bounded event fanout."""

from __future__ import annotations

import asyncio
import json
import secrets
from contextlib import suppress
from urllib.parse import urlencode, urlsplit

from websockets.asyncio.client import connect

from .policy import RuntimeDenied


class RuntimeUnavailable(RuntimeError):
    def __init__(self, reason="Hermes runtime is unavailable"):
        self.reason = reason
        super().__init__(reason)


class HermesRPCClient:
    def __init__(self, url: str, token: str, generation: str):
        parsed = urlsplit(url)
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port or parsed.path or parsed.query or parsed.username:
            raise ValueError("private Hermes endpoint required")
        self._url = f"ws://127.0.0.1:{parsed.port}/api/ws?{urlencode({'token': token})}"
        self.generation = generation
        self._socket = self._reader = None
        self._pending, self._requests, self._subscribers = {}, {}, set()
        self._lock = asyncio.Lock()
        self._disconnect_type = None

    @property
    def connected(self):
        return self._socket is not None and self._reader is not None and not self._reader.done()

    async def open(self):
        async with self._lock:
            if self.connected:
                return
            try:
                self._socket = await connect(self._url, proxy=None, max_size=1024 * 1024,
                    max_queue=64, open_timeout=10, close_timeout=3)
            except Exception as exc:
                raise RuntimeUnavailable() from exc
            self._reader = asyncio.create_task(self._read())

    async def _read(self):
        try:
            async for raw in self._socket:
                frame = json.loads(raw)
                if not isinstance(frame, dict):
                    raise ValueError("invalid RPC frame")
                rid = frame.get("id")
                if "method" not in frame and rid in self._pending:
                    future = self._pending.pop(rid)
                    if not future.done():
                        future.set_result(frame)
                    continue
                if "method" in frame and rid is not None:
                    if len(self._requests) >= 128:
                        raise ValueError("too many interactive requests")
                    self._requests[rid] = frame
                if "method" in frame:
                    event = {**frame, "generation": self.generation}
                    for queue in tuple(self._subscribers):
                        if queue.full():
                            # A slow UI must reconnect and read authoritative session
                            # history. Never silently drop a server request.
                            self._subscribers.remove(queue)
                            while not queue.empty():
                                queue.get_nowait()
                            queue.put_nowait(None)
                        else:
                            queue.put_nowait(event)
        except Exception as exc:
            self._disconnect_type = type(exc).__name__
        finally:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(RuntimeUnavailable("Hermes disconnected; operation outcome is unknown"))
            self._pending.clear()
            self._requests.clear()
            for queue in self._subscribers:
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(None)
            self._subscribers.clear()

    async def rpc(self, method: str, params: dict):
        await self.open()  # a new request may reconnect; an accepted request never retries
        rid = secrets.token_hex(16)
        future = asyncio.get_running_loop().create_future()
        self._pending[rid] = future
        try:
            await self._socket.send(json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}, allow_nan=False))
            frame = await asyncio.wait_for(future, timeout=120)
            if "error" in frame:
                error = frame["error"]
                data = error.get("data", {}) if isinstance(error, dict) else {}
                if data.get("jarvis_verdict") in {"deny", "queue"}:
                    raise RuntimeDenied(error.get("message", "Hermes refused operation"), verdict=data["jarvis_verdict"])
                raise RuntimeUnavailable(error.get("message", "Hermes request failed") if isinstance(error, dict) else "Hermes request failed")
            return frame.get("result")
        except (TimeoutError, ConnectionError) as exc:
            raise RuntimeUnavailable("Hermes response lost; operation outcome is unknown") from exc
        finally:
            self._pending.pop(rid, None)

    async def reply(self, frame: dict):
        if (not self.connected or not isinstance(frame, dict) or set(frame) - {"id", "jsonrpc", "result", "error", "generation"}
                or ("result" in frame) == ("error" in frame) or frame.get("generation") != self.generation):
            raise RuntimeUnavailable("invalid interactive response")
        rid = frame.get("id")
        request = self._requests.pop(rid, None)
        if request is None:
            raise RuntimeUnavailable("unknown or already answered Hermes request")
        await self._socket.send(json.dumps({k: v for k, v in frame.items() if k != "generation"}, allow_nan=False))
        return {"ok": True}

    async def events(self):
        await self.open()
        queue = asyncio.Queue(maxsize=256)
        self._subscribers.add(queue)
        # Interactive requests remain answerable if the UI connected after arrival.
        for frame in tuple(self._requests.values()):
            queue.put_nowait({**frame, "generation": self.generation})
        try:
            while (frame := await queue.get()) is not None:
                yield frame
        finally:
            self._subscribers.discard(queue)

    async def close(self):
        if self._socket:
            await self._socket.close()
        if self._reader:
            self._reader.cancel()
            with suppress(asyncio.CancelledError):
                await self._reader
        self._socket = self._reader = None
