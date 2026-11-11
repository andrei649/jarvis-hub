"""client.py — one language server process speaking LSP (JSON-RPC 2.0 over stdio).

Bounded on every axis the server controls: a frame's header block and body size, the
number of diagnostics kept per document, the number of documents tracked, the time
every request may take. The server is third-party code, so what it may ask of us is
narrow too: every server→client request is answered with an empty result or a
refusal (``workspace/applyEdit`` is always refused — a language server never edits
the owner's files), and diagnostics for a document outside the workspace root are
dropped on arrival.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

logger = logging.getLogger("jarvis.codeintel.lsp")

MAX_HEADER_BYTES = 8 * 1024
MAX_FRAME_BYTES = 8 * 1024 * 1024
MAX_DIAGNOSTICS_PER_DOC = 1000
MAX_TRACKED_DOCS = 2000
#: How long a push without a version must stay quiet before it counts as settled.
SETTLE_SECONDS = 0.35


class LspError(RuntimeError):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


def path_to_uri(path: Path) -> str:
    return path.resolve().as_uri()


def uri_to_path(uri: object) -> Path | None:
    if not isinstance(uri, str):
        return None
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    try:
        return Path(unquote(parsed.path)).resolve()
    except (OSError, ValueError, RuntimeError):
        return None


def encode(message: dict) -> bytes:
    body = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body


async def read_frame(reader: asyncio.StreamReader) -> dict | None:
    """One message, or None at end of stream. A malformed or oversized frame raises."""
    length: int | None = None
    seen = 0
    while True:
        line = await reader.readline()
        if not line:
            return None
        seen += len(line)
        if seen > MAX_HEADER_BYTES:
            raise LspError("frame_header_too_large")
        text = line.decode("ascii", "replace").strip()
        if not text:
            if length is None:
                continue   # stray blank line before a header block
            break
        name, _, value = text.partition(":")
        if name.strip().lower() == "content-length":
            try:
                length = int(value.strip())
            except ValueError:
                raise LspError("bad_content_length") from None
    if length < 0 or length > MAX_FRAME_BYTES:
        raise LspError("frame_too_large")
    body = await reader.readexactly(length)
    message = json.loads(body.decode("utf-8"))
    if not isinstance(message, dict):
        raise LspError("bad_frame")
    return message


class _DocState:
    __slots__ = ("version", "text", "published_version", "diagnostics", "seq", "at")

    def __init__(self) -> None:
        self.version = 0
        self.text: str | None = None
        self.published_version: int | None = None
        self.diagnostics: list[dict] = []
        self.seq = 0
        self.at = 0.0


class LspClient:
    """A started server. Use :meth:`start`, then :meth:`diagnostics`, then :meth:`stop`."""

    def __init__(self, server_id: str, argv: list[str], *, root: Path, env: dict[str, str],
                 isolation: str, preexec: Callable[[], None] | None = None,
                 timeout: float = 10.0, cwd: Path | None = None,
                 init_options: dict | None = None, settings: dict | None = None) -> None:
        self.server_id = server_id
        self.argv = list(argv)
        self.root = root.resolve()
        self.env = env
        self.isolation = isolation
        self._preexec = preexec
        self.timeout = timeout
        #: Where the process runs: its private state directory, not the workspace.
        self.cwd = cwd
        self.init_options = dict(init_options or {})
        self.settings = dict(settings or {})
        self.proc: asyncio.subprocess.Process | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.started_at = 0.0
        self.last_used = 0.0
        self.state = "new"
        self.error = ""
        self.capabilities: dict = {}
        self.served = 0
        self.publishes = 0
        self.timeouts = 0
        self._next_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._docs: dict[str, _DocState] = {}
        self._publish: asyncio.Condition | None = None   # created on start (loop-bound)
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._write_lock: asyncio.Lock | None = None
        self.doc_locks: dict[str, asyncio.Lock] = {}

    # ── lifecycle ────────────────────────────────────────────────────────────

    @property
    def pid(self) -> int | None:
        return self.proc.pid if self.proc is not None else None

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.returncode is None and self.state == "ready"

    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        self._publish = asyncio.Condition()
        self._write_lock = asyncio.Lock()
        self.state = "starting"
        kwargs: dict[str, Any] = {"start_new_session": True} if os.name == "posix" else {}
        if self._preexec is not None:
            kwargs["preexec_fn"] = self._preexec
        try:
            self.proc = await asyncio.create_subprocess_exec(  # nosec B603 — argv list, no shell
                *self.argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, cwd=str(self.cwd or self.root), env=self.env, limit=MAX_HEADER_BYTES,
                **kwargs)
        except OSError as exc:
            self.state, self.error = "broken", f"spawn_failed:{type(exc).__name__}"
            raise LspError("spawn_failed", type(exc).__name__) from None
        self.started_at = self.last_used = time.time()
        self._reader_task = asyncio.create_task(self._read_loop())
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        root_uri = path_to_uri(self.root)
        try:
            result = await self.request("initialize", {
                "processId": os.getpid(),
                "clientInfo": {"name": "nerva"},
                "rootUri": root_uri,
                "rootPath": str(self.root),
                "workspaceFolders": [{"uri": root_uri, "name": self.root.name or "workspace"}],
                "capabilities": {
                    "textDocument": {
                        "synchronization": {"didSave": False, "dynamicRegistration": False},
                        "publishDiagnostics": {"versionSupport": True, "relatedInformation": False},
                    },
                    "workspace": {"workspaceFolders": True, "configuration": True},
                    "window": {"workDoneProgress": False},
                },
                "initializationOptions": self.init_options,
            })
            self.capabilities = dict((result or {}).get("capabilities") or {}) if isinstance(result, dict) else {}
            await self.notify("initialized", {})
            if self.settings:
                await self.notify("workspace/didChangeConfiguration", {"settings": self.settings})
        except BaseException:
            await self.kill()
            self.state = "broken"
            self.error = self.error or "initialize_failed"
            raise
        self.state = "ready"

    async def stop(self) -> None:
        """Polite shutdown (bounded), then the whole process group is killed."""
        if self.proc is not None and self.proc.returncode is None and self.state == "ready":
            with contextlib.suppress(Exception):
                await self.request("shutdown", None, timeout=2.0)
                await self.notify("exit", None)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.proc.wait(), 2.0)
        await self.kill()
        self.state = "stopped"

    async def kill(self) -> None:
        proc = self.proc
        if proc is not None and proc.returncode is None:
            kill_group(proc.pid)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(proc.wait(), 3.0)
        for task in (self._reader_task, self._stderr_task):
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(BaseException):
                    await task
        for future in self._pending.values():
            if not future.done():
                future.set_exception(LspError("server_exited"))
        self._pending.clear()

    # ── wire ─────────────────────────────────────────────────────────────────

    async def _send(self, message: dict) -> None:
        proc = self.proc
        if proc is None or proc.stdin is None or proc.returncode is not None:
            raise LspError("server_exited")
        if self._write_lock is None:
            raise LspError("not_started")
        async with self._write_lock:
            proc.stdin.write(encode(message))
            try:
                await proc.stdin.drain()
            except (ConnectionError, BrokenPipeError):
                raise LspError("server_exited") from None

    async def request(self, method: str, params: Any, *, timeout: float | None = None) -> Any:
        self._next_id += 1
        ident = self._next_id
        future = asyncio.get_running_loop().create_future()
        self._pending[ident] = future
        try:
            await self._send({"jsonrpc": "2.0", "id": ident, "method": method, "params": params})
            return await asyncio.wait_for(future, self.timeout if timeout is None else timeout)
        except TimeoutError:
            raise LspError("timeout", method) from None
        finally:
            self._pending.pop(ident, None)

    async def notify(self, method: str, params: Any) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    async def _drain_stderr(self) -> None:
        stream = self.proc.stderr if self.proc is not None else None
        if stream is None:
            return
        with contextlib.suppress(Exception):
            while await stream.read(65536):
                pass   # discarded: a server's log is neither shown nor stored

    async def _read_loop(self) -> None:
        if self.proc is None or self.proc.stdout is None:
            return
        try:
            while True:
                message = await read_frame(self.proc.stdout)
                if message is None:
                    break
                await self._dispatch(message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — a misbehaving server is cut off, not trusted
            self.error = f"protocol:{getattr(exc, 'reason', type(exc).__name__)}"
            logger.info("language server %s sent a bad frame (%s); stopping it", self.server_id, self.error)
            if self.proc.returncode is None:
                kill_group(self.proc.pid)
        if self.state == "ready":
            self.state = "exited"
        for future in self._pending.values():
            if not future.done():
                future.set_exception(LspError("server_exited"))
        if self._publish is not None:
            async with self._publish:
                self._publish.notify_all()

    async def _dispatch(self, message: dict) -> None:
        method = message.get("method")
        if "id" in message and method is None:
            future = self._pending.get(message.get("id"))  # type: ignore[arg-type]
            if future is not None and not future.done():
                if "error" in message:
                    error = message.get("error") or {}
                    future.set_exception(LspError("server_error", str(error.get("message", ""))[:200]
                                                  if isinstance(error, dict) else ""))
                else:
                    future.set_result(message.get("result"))
            return
        if "id" in message and isinstance(method, str):
            await self._answer(message["id"], method, message.get("params"))
            return
        if method == "textDocument/publishDiagnostics":
            await self._on_diagnostics(message.get("params"))

    async def _answer(self, ident: Any, method: str, params: Any) -> None:
        if method == "workspace/configuration":
            items = params.get("items") if isinstance(params, dict) else None
            result: Any = [self._section(item.get("section") if isinstance(item, dict) else None)
                           for item in (items if isinstance(items, list) else [])]
            reply = {"jsonrpc": "2.0", "id": ident, "result": result}
        elif method in ("client/registerCapability", "client/unregisterCapability",
                        "window/workDoneProgress/create", "window/showMessageRequest",
                        "workspace/workspaceFolders"):
            result = [{"uri": path_to_uri(self.root), "name": self.root.name or "workspace"}] \
                if method == "workspace/workspaceFolders" else None
            reply = {"jsonrpc": "2.0", "id": ident, "result": result}
        else:   # workspace/applyEdit and everything else: refused
            reply = {"jsonrpc": "2.0", "id": ident,
                     "error": {"code": -32601, "message": "not supported by this client"}}
        with contextlib.suppress(LspError):
            await self._send(reply)

    def _section(self, section: object) -> Any:
        """Nerva's own settings for a ``workspace/configuration`` section (dotted), else None."""
        if not isinstance(section, str) or not section:
            return None
        node: Any = self.settings
        for part in section.split("."):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    def _inside_root(self, path: Path | None) -> bool:
        return path is not None and (path == self.root or self.root in path.parents)

    async def _on_diagnostics(self, params: Any) -> None:
        if not isinstance(params, dict):
            return
        uri = params.get("uri")
        if not self._inside_root(uri_to_path(uri)):
            return   # path confinement: nothing outside the workspace is kept
        diagnostics = params.get("diagnostics")
        if not isinstance(diagnostics, list):
            return
        state = self._docs.get(uri)  # type: ignore[arg-type]
        if state is None:
            if len(self._docs) >= MAX_TRACKED_DOCS:
                return
            state = self._docs[uri] = _DocState()  # type: ignore[index]
        version = params.get("version")
        state.published_version = version if isinstance(version, int) and not isinstance(version, bool) else None
        state.diagnostics = [d for d in diagnostics[:MAX_DIAGNOSTICS_PER_DOC] if isinstance(d, dict)]
        state.seq += 1
        state.at = time.monotonic()
        self.publishes += 1
        if self._publish is None:
            return
        async with self._publish:
            self._publish.notify_all()

    # ── documents ────────────────────────────────────────────────────────────

    def doc_lock(self, uri: str) -> asyncio.Lock:
        lock = self.doc_locks.get(uri)
        if lock is None:
            lock = self.doc_locks[uri] = asyncio.Lock()
        return lock

    async def sync(self, path: Path, text: str, language_id: str) -> tuple[str, int, int]:
        """Open or change *path* to *text*; ``(uri, version, publish seq before)``."""
        if not self._inside_root(path.resolve()):
            raise LspError("outside_workspace")
        uri = path_to_uri(path)
        state = self._docs.get(uri)
        if state is None:
            if len(self._docs) >= MAX_TRACKED_DOCS:
                raise LspError("too_many_documents")
            state = self._docs[uri] = _DocState()
        seq = state.seq
        state.version += 1
        self.last_used = time.time()
        if state.text is None:
            await self.notify("textDocument/didOpen", {"textDocument": {
                "uri": uri, "languageId": language_id, "version": state.version, "text": text}})
        else:
            await self.notify("textDocument/didChange", {
                "textDocument": {"uri": uri, "version": state.version},
                "contentChanges": [{"text": text}]})
        state.text = text
        return uri, state.version, seq

    async def wait_diagnostics(self, uri: str, version: int, seq: int, *,
                               timeout: float | None = None) -> list[dict]:
        """The diagnostics the server produced for *version* of *uri* (freshness gate).

        A push that names a version counts only when it is that version. A push without
        one counts when it arrived after the change was sent and then stayed the latest
        for :data:`SETTLE_SECONDS`. Raises ``LspError("timeout")``.
        """
        if self._publish is None:
            raise LspError("not_started")
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        state = self._docs[uri]
        async with self._publish:
            while True:
                if state.seq > seq:
                    if state.published_version == version:
                        break
                    if state.published_version is None:
                        quiet = time.monotonic() - state.at
                        if quiet >= SETTLE_SECONDS:
                            break
                        wait = min(SETTLE_SECONDS - quiet, deadline - time.monotonic())
                    else:
                        wait = deadline - time.monotonic()
                else:
                    wait = deadline - time.monotonic()
                if self.proc is None or self.proc.returncode is not None or self.state != "ready":
                    raise LspError("server_exited")
                if wait <= 0:
                    if state.seq > seq and state.published_version is None:
                        break
                    self.timeouts += 1
                    raise LspError("timeout", "diagnostics")
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._publish.wait(), wait)
        self.last_used = time.time()
        self.served += 1
        return list(state.diagnostics)


def kill_group(pid: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        if os.name == "posix":
            # Started with start_new_session=True: its group id is its pid, never ours.
            os.killpg(pid, signal.SIGKILL)
        else:
            os.kill(pid, signal.SIGTERM)


__all__ = ["LspClient", "LspError", "encode", "kill_group", "path_to_uri", "read_frame", "uri_to_path"]
