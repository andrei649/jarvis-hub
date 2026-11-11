"""`nerva acp` (G11): the ACP agent on stdio, backed by the running hub over HTTP.

Nothing here is a second API. Each :class:`HubBackend` method is one route the HUD or
another ``nerva`` verb already uses, with the same credentials (``JARVIS_ADMIN_TOKEN``):

==========================  ===============================================
open/close a session        ``POST``/``DELETE /api/acp/sessions``
a turn                      ``POST /chat/stream`` (``tool_events`` on)
the command catalog         ``GET /api/commands``
the turn's approval cards   ``GET /autonomy/approvals``
decide a card               ``POST /autonomy/tasks/{id}/decision`` / ``/consent``
follow a decided card       ``GET /autonomy/tasks``
answer a clarify question   ``POST /chat/pending/{id}/answer``
an editor's MCP server      ``POST /api/acp/sessions/{id}/mcp``
the plan panel              ``GET /sessions/{id}/todo``
==========================  ===============================================

stdout is the protocol channel: nothing else may be written to it. Diagnostics go to
stderr. Standard library only.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
import sys
import threading
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import quote

from agents.core.acp.jsonrpc import MAX_MESSAGE_BYTES
from agents.core.acp.server import AcpServer, BackendRefused

from .client import HubClient, HubError, HubUnavailable, hub_open

#: The longest a turn may run with nothing on its stream (the hub's clarify window).
STREAM_TIMEOUT_SECONDS = 75 * 60.0


class HubBackend:
    def __init__(self, client: HubClient, *, opener=hub_open) -> None:
        self.client = client
        self._opener = opener

    async def _call(self, method: str, path: str, body: Any = None, *, timeout: float | None = None) -> Any:
        def run():
            if method == "GET":
                return self.client.get(path)
            return self.client.request(method, path, body if body is not None else {}, timeout=timeout)

        try:
            return await asyncio.to_thread(run)
        except HubUnavailable as exc:
            raise BackendRefused(0, "no hub answered") from exc
        except HubError as exc:
            raise BackendRefused(exc.status, exc.reason) from None

    # ── sessions ─────────────────────────────────────────────────────────────

    async def open_session(self, cwd: str) -> str:
        reply = await self._call("POST", "/api/acp/sessions", {"cwd": cwd})
        session_id = reply.get("session_id") if isinstance(reply, dict) else None
        if not isinstance(session_id, str):
            raise BackendRefused(502, "no session id")
        return session_id

    async def close_session(self, session_id: str) -> None:
        await self._call("DELETE", f"/api/acp/sessions/{quote(session_id, safe='')}")

    async def renew(self, session_id: str) -> None:
        await self._call("POST", f"/api/acp/sessions/{quote(session_id, safe='')}/lease")

    async def commands(self) -> list[dict[str, Any]]:
        reply = await self._call("GET", "/api/commands")
        rows = reply.get("commands") if isinstance(reply, dict) else None
        return rows if isinstance(rows, list) else []

    async def add_session_mcp(self, session_id: str, server: dict[str, Any]) -> dict[str, Any]:
        body = {"name": server["name"], "command": server["command"], "args": list(server.get("args") or []),
                "env": dict(server.get("env") or {})}
        reply = await self._call("POST", f"/api/acp/sessions/{quote(session_id, safe='')}/mcp", body,
                                 timeout=60.0)
        return reply if isinstance(reply, dict) else {}

    async def todo(self, session_id: str) -> list[dict[str, Any]]:
        reply = await self._call("GET", f"/sessions/{quote(session_id, safe='')}/todo")
        todos = reply.get("todos") if isinstance(reply, dict) else None
        return todos if isinstance(todos, list) else []

    # ── approvals ────────────────────────────────────────────────────────────

    async def approvals(self) -> list[dict[str, Any]]:
        reply = await self._call("GET", "/autonomy/approvals")
        pending = reply.get("pending") if isinstance(reply, dict) else None
        return [card for card in pending if isinstance(card, dict)] if isinstance(pending, list) else []

    async def decide(self, task_id: int, action: str, reason: str | None) -> str:
        body: dict[str, Any] = {"action": action}
        if reason:
            body["reason"] = reason[:280]
        reply = await self._call("POST", f"/autonomy/tasks/{int(task_id)}/decision", body)
        task = reply.get("task") if isinstance(reply, dict) else None
        return str(task.get("status") or "") if isinstance(task, dict) else ""

    async def consent(self, task_id: int, revision: str, choice: str) -> str:
        reply = await self._call("POST", f"/autonomy/tasks/{int(task_id)}/consent",
                                 {"choice": choice, "revision": revision})
        tasks = reply.get("tasks") if isinstance(reply, dict) else None
        for task in tasks if isinstance(tasks, list) else []:
            if isinstance(task, dict) and task.get("id") == task_id:
                return str(task.get("status") or "")
        return ""

    async def task_status(self, task_id: int) -> str | None:
        reply = await self._call("GET", "/autonomy/tasks?limit=200")
        for task in (reply.get("tasks") if isinstance(reply, dict) else None) or []:
            if isinstance(task, dict) and task.get("id") == task_id:
                return str(task.get("status") or "")
        return None

    async def answer_question(self, prompt_id: str, answer: str | None) -> bool:
        body: dict[str, Any] = {"answer": answer} if answer else {"cancel": True}
        try:
            await self._call("POST", f"/chat/pending/{quote(prompt_id, safe='')}/answer", body)
        except BackendRefused:
            return False
        return True

    # ── the turn ─────────────────────────────────────────────────────────────

    async def stream_turn(self, session_id: str, message: str, on_event, cancel: asyncio.Event, *,
                          attachments=None):
        """``POST /chat/stream`` read event by event on a worker thread. A cancel closes
        the connection; the hub cancels a turn whose stream went away."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        holder: dict[str, Any] = {}
        payload: dict[str, Any] = {"message": message, "session_id": session_id, "tool_events": True}
        if attachments:
            payload["attachments"] = list(attachments)
        body = json.dumps(payload).encode("utf-8")
        headers = self.client._headers()
        headers["Accept"] = "text/event-stream"
        request = urllib.request.Request(f"{self.client.base_url}/chat/stream", data=body, method="POST",
                                         headers=headers)

        def put(item):
            loop.call_soon_threadsafe(queue.put_nowait, item)

        def reader():
            try:
                response = self._opener(request, timeout=STREAM_TIMEOUT_SECONDS)
            except urllib.error.HTTPError as exc:
                put(("refused", exc.code))
                return
            except Exception:  # noqa: BLE001 - the hub is unreachable
                put(("refused", 0))
                return
            holder["response"] = response
            try:
                with response:
                    while True:
                        line = response.readline(MAX_MESSAGE_BYTES)
                        if not line:
                            break
                        if not line.startswith(b"data:"):
                            continue
                        try:
                            event = json.loads(line[5:].strip() or b"null")
                        except ValueError:
                            continue
                        if isinstance(event, dict):
                            put(("event", event))
            except Exception as exc:  # noqa: BLE001 - a closed or broken stream ends the turn
                print(f"nerva acp: the turn's stream ended ({type(exc).__name__})", file=sys.stderr)
            finally:
                put(("eof", None))

        worker = threading.Thread(target=reader, name="nerva-acp-turn", daemon=True)
        worker.start()
        waiter = asyncio.ensure_future(cancel.wait())
        end: dict[str, Any] | None = None
        try:
            while True:
                getter = asyncio.ensure_future(queue.get())
                done, _ = await asyncio.wait({getter, waiter}, return_when=asyncio.FIRST_COMPLETED)
                if getter not in done:
                    getter.cancel()
                    _hang_up(holder.get("response"))
                    return None
                kind, data = getter.result()
                if kind == "refused":
                    raise BackendRefused(int(data), "stream refused")
                if kind == "eof":
                    return end
                if data.get("type") == "end":
                    end = data
                    continue
                await on_event(data)
        finally:
            waiter.cancel()


def _hang_up(response: Any) -> None:
    """Close the turn's connection from outside the reading thread."""
    if response is None:
        return
    with contextlib.suppress(Exception):   # best effort; close() below still runs
        response.fp.raw._sock.shutdown(socket.SHUT_RDWR)  # type: ignore[attr-defined]
    with contextlib.suppress(Exception):
        response.close()


class _StdoutWriter:
    def __init__(self, stream) -> None:
        self._stream = stream

    def write(self, data: bytes) -> None:
        self._stream.write(data)
        self._stream.flush()

    async def drain(self) -> None:
        return None


async def _stdin_reader(stream) -> asyncio.StreamReader:
    """stdin fed into a StreamReader from a thread (works on every platform)."""
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(limit=MAX_MESSAGE_BYTES + 1)
    fd = stream.fileno()

    def pump():
        try:
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                loop.call_soon_threadsafe(reader.feed_data, chunk)
        except OSError:
            pass
        finally:
            loop.call_soon_threadsafe(reader.feed_eof)

    threading.Thread(target=pump, name="nerva-acp-stdin", daemon=True).start()
    return reader


async def serve_stdio(client: HubClient, *, permission_timeout: float, version: str = "") -> None:
    server = AcpServer(HubBackend(client), version=version, permission_timeout=permission_timeout)
    reader = await _stdin_reader(sys.stdin.buffer)
    await server.serve(reader, _StdoutWriter(sys.stdout.buffer))


__all__ = ["HubBackend", "serve_stdio"]
