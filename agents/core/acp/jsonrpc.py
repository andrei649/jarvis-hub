"""Newline-delimited JSON-RPC 2.0 over a pair of byte streams (G11, ACP transport).

The editor is a local process the owner launched, and its messages are still treated as
untrusted input:

* one message is one line of at most :data:`MAX_MESSAGE_BYTES`; a longer line ends the
  connection (it is never buffered without bound);
* a line that is not a JSON object answers ``-32700``/``-32600`` and the connection goes on;
* a handler's exception becomes ``-32603`` with a fixed message — exception text never
  crosses to the peer;
* when the stream ends, every request the agent is still waiting on fails with
  :class:`ConnectionClosed`, so a permission the editor never answered resolves as a
  denial instead of hanging.

Only the standard library is used.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger("nerva.acp.jsonrpc")

#: One JSON-RPC message, bytes on the wire. Prompts are bounded far below this by the
#: server; the bound here keeps a hostile peer from making the reader buffer forever.
MAX_MESSAGE_BYTES = 4 * 1024 * 1024
#: Requests the agent may have in flight to the editor at once.
MAX_PENDING_REQUESTS = 64

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class RpcError(Exception):
    """An error to answer the peer with (code, fixed message, optional data)."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            out["data"] = self.data
        return out


class ConnectionClosed(Exception):
    """The peer went away before answering."""


Handler = Callable[[str, Any], Awaitable[Any]]
NotificationHandler = Callable[[str, Any], Awaitable[None]]


class Writer:
    """What the connection writes to: ``write(bytes)`` and an awaitable ``drain()``."""

    def write(self, data: bytes) -> None:  # pragma: no cover - protocol
        raise NotImplementedError

    async def drain(self) -> None:  # pragma: no cover - protocol
        raise NotImplementedError


class JsonRpcConnection:
    """One peer. ``serve()`` reads until EOF; ``request``/``notify`` write to the peer."""

    def __init__(self, reader: Any, writer: Any, *, on_request: Handler,
                 on_notification: NotificationHandler,
                 max_message_bytes: int = MAX_MESSAGE_BYTES) -> None:
        self._reader = reader
        self._writer = writer
        self._on_request = on_request
        self._on_notification = on_notification
        self._max = int(max_message_bytes)
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._write_lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()
        self.closed = False

    # ── writing ──────────────────────────────────────────────────────────────

    async def _send(self, message: dict[str, Any]) -> None:
        if self.closed:
            raise ConnectionClosed()
        data = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        async with self._write_lock:
            try:
                self._writer.write(data)
                await self._writer.drain()
            except (ConnectionError, OSError, RuntimeError) as exc:
                self._close()
                raise ConnectionClosed() from exc

    async def notify(self, method: str, params: Any) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    async def request(self, method: str, params: Any, *, timeout: float | None = None) -> Any:
        """Ask the peer and wait for its answer. Raises :class:`RpcError` for an error
        answer, :class:`ConnectionClosed` when the peer goes away, ``TimeoutError``."""
        if self.closed:
            raise ConnectionClosed()
        if len(self._pending) >= MAX_PENDING_REQUESTS:
            raise RpcError(INTERNAL_ERROR, "too many requests in flight")
        request_id = next(self._ids)
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            if timeout is None:
                return await future
            return await asyncio.wait_for(future, timeout)
        finally:
            self._pending.pop(request_id, None)

    # ── reading ──────────────────────────────────────────────────────────────

    async def _readline(self) -> bytes | None:
        try:
            line = await self._reader.readline()
        except (asyncio.LimitOverrunError, ValueError):
            logger.warning("ACP peer sent a message over the size bound; closing")
            return None
        except (ConnectionError, OSError):
            return None
        if not line:
            return None
        if len(line) > self._max:
            logger.warning("ACP peer sent a message over the size bound; closing")
            return None
        return line

    async def serve(self) -> None:
        """Read and dispatch until the peer closes the stream (or breaks the framing)."""
        try:
            while True:
                line = await self._readline()
                if line is None:
                    break
                if not line.strip():
                    continue
                await self._dispatch(line)
        finally:
            self._close()
            for task in list(self._tasks):
                task.cancel()
            for task in list(self._tasks):
                with contextlib.suppress(asyncio.CancelledError, Exception):  # teardown
                    await task

    async def _dispatch(self, line: bytes) -> None:
        try:
            message = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            await self._safe_send({"jsonrpc": "2.0", "id": None,
                                   "error": RpcError(PARSE_ERROR, "parse error").to_dict()})
            return
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            await self._safe_send({"jsonrpc": "2.0", "id": None,
                                   "error": RpcError(INVALID_REQUEST, "invalid request").to_dict()})
            return
        method = message.get("method")
        has_id = "id" in message
        if method is None and has_id:
            self._resolve(message)
            return
        if not isinstance(method, str) or not method or len(method) > 128:
            await self._safe_send({"jsonrpc": "2.0", "id": message.get("id") if has_id else None,
                                   "error": RpcError(INVALID_REQUEST, "invalid request").to_dict()})
            return
        params = message.get("params")
        if has_id:
            request_id = message.get("id")
            if not isinstance(request_id, (int, str)) or isinstance(request_id, bool):
                await self._safe_send({"jsonrpc": "2.0", "id": None,
                                       "error": RpcError(INVALID_REQUEST, "invalid id").to_dict()})
                return
            self._spawn(self._answer(request_id, method, params))
        else:
            self._spawn(self._notified(method, params))

    def _spawn(self, coro) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _answer(self, request_id: Any, method: str, params: Any) -> None:
        try:
            result = await self._on_request(method, params)
            reply = {"jsonrpc": "2.0", "id": request_id, "result": result}
        except RpcError as exc:
            reply = {"jsonrpc": "2.0", "id": request_id, "error": exc.to_dict()}
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - never leak exception text to the peer
            logger.exception("ACP handler for %s failed", method)
            reply = {"jsonrpc": "2.0", "id": request_id,
                     "error": RpcError(INTERNAL_ERROR, "internal error").to_dict()}
        await self._safe_send(reply)

    async def _notified(self, method: str, params: Any) -> None:
        try:
            await self._on_notification(method, params)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a notification has no answer to carry an error
            logger.exception("ACP notification %s failed", method)

    def _resolve(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        future = self._pending.get(request_id) if isinstance(request_id, int) else None
        if future is None or future.done():
            return
        if isinstance(message.get("error"), dict):
            error = message["error"]
            code = error.get("code") if isinstance(error.get("code"), int) else INTERNAL_ERROR
            text = error.get("message") if isinstance(error.get("message"), str) else "error"
            future.set_exception(RpcError(code, text[:500]))
        else:
            future.set_result(message.get("result"))

    async def _safe_send(self, message: dict[str, Any]) -> None:
        with contextlib.suppress(ConnectionClosed):
            await self._send(message)

    def _close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(ConnectionClosed())
        self._pending.clear()


__all__ = [
    "ConnectionClosed", "INTERNAL_ERROR", "INVALID_PARAMS", "INVALID_REQUEST", "JsonRpcConnection",
    "MAX_MESSAGE_BYTES", "METHOD_NOT_FOUND", "PARSE_ERROR", "RpcError", "Writer",
]
