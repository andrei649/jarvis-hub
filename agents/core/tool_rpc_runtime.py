"""Runtime bridge between sandboxed Python code and governed Tool-RPC."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import uuid
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from agents.core.environments.file_rpc import FileRPCStore
from agents.core.sandbox import Sandbox, SandboxResult
from agents.core.tool_rpc import ToolRPCServer

logger = logging.getLogger("jarvis.tool_rpc_runtime")


@dataclass(frozen=True)
class ToolRPCSandboxRun:
    """Result of a sandboxed script plus the host-serviced Tool-RPC count."""

    result: SandboxResult
    tool_calls: int
    timed_out: bool = False


def sandbox_client_source(
    rpc_dir: str,
    *,
    max_tool_calls: int = 50,
    timeout_seconds: float = 30.0,
    poll_interval: float = 0.01,
) -> str:
    """Return the Python client shim injected into sandboxed scripts."""

    return f"""
import json as _jarvis_json
import time as _jarvis_time
from pathlib import Path as _JarvisPath

_JARVIS_RPC_DIR = _JarvisPath({json.dumps(str(rpc_dir))})
_JARVIS_RPC_DIR.mkdir(parents=True, exist_ok=True)
_JARVIS_RPC_SEQ = 0
_JARVIS_RPC_MAX_CALLS = {int(max_tool_calls)}
_JARVIS_RPC_TIMEOUT_SECONDS = {float(timeout_seconds)!r}
_JARVIS_RPC_POLL_INTERVAL = {float(poll_interval)!r}


def _jarvis_rpc_sequence_token(seq):
    return f"{{seq:06d}}"


def jarvis_tool_call(tool, args=None):
    global _JARVIS_RPC_SEQ
    tool_name = str(tool or "")
    if args is None:
        args = {{}}
    if not isinstance(args, dict):
        return {{"ok": False, "reason": "bad_args", "tool": tool_name}}
    if not tool_name:
        return {{"ok": False, "reason": "tool_not_allowed", "tool": tool_name}}
    if _JARVIS_RPC_SEQ >= _JARVIS_RPC_MAX_CALLS:
        return {{
            "ok": False,
            "reason": "tool_call_limit_exceeded",
            "tool": tool_name,
        }}

    _JARVIS_RPC_SEQ += 1
    seq = _JARVIS_RPC_SEQ
    token = _jarvis_rpc_sequence_token(seq)
    req_path = _JARVIS_RPC_DIR / f"req_{{token}}.json"
    tmp_path = _JARVIS_RPC_DIR / f"req_{{token}}.json.tmp"
    res_path = _JARVIS_RPC_DIR / f"res_{{token}}.json"
    tmp_path.write_text(
        _jarvis_json.dumps({{"seq": seq, "tool": tool_name, "args": args}}, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp_path.replace(req_path)

    deadline = _jarvis_time.monotonic() + _JARVIS_RPC_TIMEOUT_SECONDS
    while _jarvis_time.monotonic() < deadline:
        if res_path.exists():
            try:
                payload = _jarvis_json.loads(res_path.read_text(encoding="utf-8"))
            except Exception:
                return {{"ok": False, "reason": "bad_response", "tool": tool_name}}
            try:
                res_path.unlink()
            except OSError:
                pass
            if isinstance(payload, dict):
                return payload
            return {{"ok": False, "reason": "bad_response", "tool": tool_name}}
        _jarvis_time.sleep(_JARVIS_RPC_POLL_INTERVAL)

    return {{"ok": False, "reason": "file_rpc_timeout", "tool": tool_name}}
"""


class ToolRPCSandboxRuntime:
    """Run sandboxed Python while servicing file-RPC tool calls on the host."""

    def __init__(
        self,
        server: ToolRPCServer,
        sandbox: Sandbox,
        *,
        max_tool_calls: int = 50,
        poll_interval: float = 0.01,
        service_timeout: float | None = None,
    ) -> None:
        self.server = server
        self.sandbox = sandbox
        self.max_tool_calls = max(0, int(max_tool_calls))
        self.poll_interval = max(0.001, float(poll_interval))
        self.service_timeout = service_timeout
        # Cap how many request files one poll examines — the RPC dir is written
        # by untrusted sandbox code, so a burst must not make a poll read them all.
        self._pending_read_limit = max(64, self.max_tool_calls * 2)

    async def run_python(
        self,
        code: str,
        filename: str = "script.py",
    ) -> ToolRPCSandboxRun:
        run_id = uuid.uuid4().hex
        rpc_dir = self.sandbox.work_dir / ".jarvis_file_rpc" / run_id
        store = FileRPCStore(rpc_dir, max_tool_calls=self.max_tool_calls)
        child_rpc_dir = self._child_rpc_dir(run_id)
        shim = sandbox_client_source(
            child_rpc_dir,
            max_tool_calls=self.max_tool_calls,
            timeout_seconds=max(1.0, float(self.sandbox.timeout)),
            poll_interval=self.poll_interval,
        )
        script = f"{shim}\n{code}"
        task = asyncio.create_task(
            self.sandbox.execute_python(
                script,
                filename,
                writable_paths=[rpc_dir],
            )
        )

        processed: set[int] = set()
        tool_calls = 0
        timed_out = False
        loop = asyncio.get_running_loop()
        # Never let the outer service loop fire before the sandbox's OWN timeout
        # has had a chance to kill the process — otherwise task.cancel() below
        # could orphan a still-running container/subprocess. Bind the monotonic
        # clock once (rather than re-reading it each iteration).
        service_window = max(
            float(self.service_timeout or 0.0),
            float(self.sandbox.timeout) + 5.0,
        )
        deadline = loop.time() + service_window

        try:
            while not task.done():
                tool_calls = await self._service_pending(store, processed, tool_calls)
                if loop.time() >= deadline:
                    timed_out = True
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
                    return ToolRPCSandboxRun(
                        SandboxResult(
                            stderr="File-RPC runtime timed out",
                            exit_code=-1,
                        ),
                        tool_calls=tool_calls,
                        timed_out=True,
                    )
                await asyncio.sleep(self.poll_interval)

            tool_calls = await self._service_pending(store, processed, tool_calls)
            return ToolRPCSandboxRun(
                result=await task,
                tool_calls=tool_calls,
                timed_out=timed_out,
            )
        finally:
            with suppress(Exception):
                shutil.rmtree(rpc_dir)

    async def _service_pending(
        self,
        store: FileRPCStore,
        processed: set[int],
        tool_calls: int,
    ) -> int:
        for request in store.pending_requests(limit=self._pending_read_limit):
            if request.seq in processed:
                # Already serviced (or a duplicate the sandbox re-wrote): drop the
                # file so it is not re-globbed and re-read on every future poll.
                self._consume_request(store, request.seq)
                continue
            processed.add(request.seq)

            if tool_calls >= self.max_tool_calls:
                store.write_response(request.seq, {
                    "ok": False,
                    "reason": "tool_call_limit_exceeded",
                    "tool": request.tool,
                })
                self._consume_request(store, request.seq)
                continue

            response = await self._handle_request(request.tool, request.args)
            store.write_response(request.seq, response)
            self._consume_request(store, request.seq)
            tool_calls += 1

        return tool_calls

    @staticmethod
    def _consume_request(store: FileRPCStore, seq: int) -> None:
        # Delete a serviced/refused request file so pending_requests() does not
        # re-read and re-glob it forever (host CPU/IO exhaustion). Canonical
        # filenames (enforced by the store) make request_path(seq) exactly this
        # file, so cleanup can never miss it or hit the wrong path.
        with suppress(OSError):
            store.request_path(seq).unlink(missing_ok=True)

    async def _handle_request(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self.server.handle({"tool": tool, "args": args})
        except Exception:
            logger.warning("file-rpc tool request failed: %s", tool, exc_info=True)
            return {"ok": False, "reason": "tool_error", "tool": tool}
        return response if isinstance(response, dict) else {
            "ok": False,
            "reason": "bad_response",
            "tool": tool,
        }

    def _child_rpc_dir(self, run_id: str) -> str:
        if self.sandbox.active_backend() in {"docker", "wasm"}:
            return f"/workspace/.jarvis_file_rpc/{run_id}"
        return str(self.sandbox.work_dir / ".jarvis_file_rpc" / run_id)
