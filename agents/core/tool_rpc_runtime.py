"""Runtime bridge between sandboxed Python code and governed Tool-RPC.

Every inner call carries the run's authority (K0, `sandbox_invocation.py`): the
invoking agent reaches `ToolRPCServer.handle` as the actor, and a tool outside the
outer turn's offered set is refused here, before the server sees it. A runtime built
without an invocation refuses every call rather than falling back to the server's
default identity — that fallback is exactly what K0 exists to remove.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from agents.core.environments.file_rpc import FileRPCStore
from agents.core.sandbox import Sandbox, SandboxResult
from agents.core.sandbox_invocation import (
    AUTHORITY_MISSING,
    InvocationRefused,
    SandboxInvocation,
)
from agents.core.security.recall_taint import mark_turn_recall_tainted
from agents.core.tool_rpc import ToolRPCServer, bind_tool_turn, reset_tool_turn

logger = logging.getLogger("jarvis.tool_rpc_runtime")


class ToolCallBroker:
    """One tool call, authorized then handled. The only copy of that sequence.

    A sandboxed script and a session kernel (K2) both need exactly this: refuse
    against the run's authority *before* the server sees the call, then reach the
    server as the invocation's agent. Writing it twice is how the two copies drift,
    and the one that drifts is a second, weaker authorization system — so both
    callers hold a broker instead.

    A broker is per *authority*, not per process: a session kernel builds a fresh one
    for every cell, which is what stops a variable created in cell 1 from carrying
    cell 1's permissions into cell 400.

    It also carries what the script has read (the H315 second review). A script's tool
    calls never pass through the loop, which raises the turn's taint only once a batch
    returns, so a script could read a page and write it into the plan as clean text.
    It reads an answer as the loop reads a result (H315 third review): once a tool that
    declares ``untrusted_output`` answers ok, an answer says ``tainted``, or the injection
    scanner flags an answer, :attr:`tainted` is set and every later call this broker
    services runs under a raised origin. A refusal or a tool that raised is Nerva's own
    words about a call that did not happen, and taints nothing. The flag lives here, not
    only in the context: a session kernel services each batch of a cell's calls in a task
    of its own.
    """

    __slots__ = ("server", "invocation", "revoked", "tainted")

    def __init__(self, server: ToolRPCServer, invocation: SandboxInvocation | None,
                 *, revoked: Callable[[], bool] | None = None) -> None:
        self.server = server
        self.invocation = invocation
        self.revoked = revoked
        self.tainted = False

    async def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        # Authority first, and entirely before `handle`: a refusal after the call has
        # run is not a refusal, and a gated tool that reaches the server has already
        # put a card in the owner's inbox even though it never executes.
        if self.invocation is None:
            return {"ok": False, "reason": AUTHORITY_MISSING, "tool": tool}
        try:
            self.invocation.authorize(
                tool, registered=self.server.allows, revoked=self.revoked,
            )
        except InvocationRefused as refusal:
            return refusal.as_response()
        if self.tainted:
            mark_turn_recall_tainted()        # an earlier call of this run read untrusted text
        declares = getattr(self.server, "declares_untrusted_output", None)
        untrusted = bool(declares(tool)) if callable(declares) else False
        # A script's call belongs to no model turn: what it writes is not text the model
        # sent in its own transcript, so a tool never treats it as the turn's own words.
        turn = bind_tool_turn(None)
        try:
            response = await self.server.handle(
                {"tool": tool, "args": args}, actor=self.invocation.agent,
            )
        except Exception:
            logger.warning("file-rpc tool request failed: %s", tool, exc_info=True)
            response = {"ok": False, "reason": "tool_error", "tool": tool}
        finally:
            reset_tool_turn(turn)
        # Once the run is tainted a scan can change nothing, so it is skipped: this broker's
        # own flag, or the origin an earlier read raised (the K1 loop builds a broker per
        # request, review-H315f m3). Otherwise it runs off the event loop (review-H315e m2:
        # 50 nested answers of 2 MB held every chat for 16 s), over the whole answer (an
        # injection deep in it counts), in chunks on a thread of its own.
        if self.tainted or _origin_untrusted():
            self.tainted = True
        elif (untrusted and _answered_ok(response)) or _declares_taint(response) or await _scan(response):
            self.tainted = True
            mark_turn_recall_tainted()
        return response if isinstance(response, dict) else {
            "ok": False,
            "reason": "bad_response",
            "tool": tool,
        }


def _answered_ok(response: Any) -> bool:
    """The tool ran and answered: neither the server nor the handler refused."""
    if not isinstance(response, dict) or response.get("ok") is not True:
        return False
    inner = response.get("result")
    return not (isinstance(inner, dict) and inner.get("ok") is False)


#: The scan's own thread: never the loop's default pool, which scans of many concurrent
#: scripts would otherwise fill for every other ``to_thread`` user (review-H315f m3). Only
#: large answers go to it; small ones are scanned inline, so they never queue behind a
#: multi-megabyte scan (review-H315g m2). One thread, not four: the scan holds the GIL,
#: so more scanners bought no throughput and made the loop wait 4-5x longer at p99
#: (review-H315h m2).
_SCAN_WORKERS = 1


def _new_scan_pool() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=_SCAN_WORKERS, thread_name_prefix="tool-rpc-scan")


_SCAN_POOL = _new_scan_pool()


def _rebuild_scan_pool_after_fork() -> None:
    """A forked child inherits the pool without its threads, and its scans would hang
    (review-H315g n3)."""
    global _SCAN_POOL
    _SCAN_POOL = _new_scan_pool()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_rebuild_scan_pool_after_fork)

#: An answer this small is scanned inline, where it costs microseconds: sending it to a
#: thread would only queue it behind other scripts' large scans.
_SCAN_INLINE_BYTES = 16 * 1024


_encode_string = json.encoder.encode_basestring   # the C encoder when there is one


def _small(value: Any, budget: int = _SCAN_INLINE_BYTES) -> bool:
    """Whether ``value`` encodes to under ``budget`` characters, counted until it does not:
    a container wider than what is left is refused before its items are listed, and a
    string longer than it before it is looked at, so the walk costs at most ``budget``
    whatever the answer's size (review-H315h n1). A string that fits is counted as it
    encodes, exactly, so a newline costs two, not the whole string six times over (a
    multi-line log answer queued behind large scans again: review-H315i m1), and a quote
    two, not one (n4). ``bytes`` count as ``str()`` spells them, as the encoder does. A
    value JSON spells through ``str()`` otherwise (a huge int, any object) has a size
    nobody knows until it is spelled, so it is never small."""
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, (str, bytes, bytearray)):
            if len(item) > budget:
                return False
            text = item if isinstance(item, str) else str(item)
            if len(text) > 4 * budget:
                return False
            # What json.dumps(ensure_ascii=False) writes for a string, without its
            # machinery: the size walk runs on the loop for every call (review-H315j n1).
            budget -= len(_encode_string(text))
        elif isinstance(item, dict):
            budget -= 4 * len(item) + 2          # ": " and ", " per pair (review-H315j n2)
            if budget < 0:
                return False
            stack.extend(item.keys())
            stack.extend(item.values())
        elif isinstance(item, (list, tuple)):
            budget -= 2 * len(item) + 2          # ", " per item
            if budget < 0:
                return False
            stack.extend(item)
        elif item is None or isinstance(item, (bool, float)) or (
                isinstance(item, int) and -(2 ** 63) <= item < 2 ** 63):
            budget -= 24
        else:
            return False
        if budget < 0:
            return False
    return True


async def _scan(response: Any) -> bool:
    if _small(response):
        return _flagged(response)
    return await asyncio.get_running_loop().run_in_executor(_SCAN_POOL, _flagged, response)
#: The answer is scanned in slices of this many characters, overlapping by
#: _SCAN_OVERLAP, so no single regex call holds the interpreter lock for a whole 2 MB
#: answer (the loop stalls while it does); the overlap keeps a pattern that straddles two
#: slices whole.
_SCAN_CHUNK = 64 * 1024
_SCAN_OVERLAP = 4 * 1024


def _origin_untrusted() -> bool:
    """This context has already read untrusted text (an earlier call of the run)."""
    try:
        from agents.core.action_origin import current_action_origin
        from agents.core.security.taint import is_untrusted_source

        return bool(is_untrusted_source(current_action_origin()))
    except Exception:
        return False


def _flagged(response: Any) -> bool:
    """The answer is flagged as the loop's fence flags a result: an injection pattern, or
    the fence's own markers spelled out inside it (review-H315e n1)."""
    from agents.core.security.quarantine import FENCE_CLOSE, detect_injection

    try:
        encoded = json.dumps(response, ensure_ascii=False, default=str)
    except RecursionError:
        return True                      # too deep to read is not clean: fail closed (review-H315h)
    except (TypeError, ValueError):
        return False
    if FENCE_CLOSE in encoded or "<<UNTRUSTED" in encoded:
        return True
    for start in range(0, max(1, len(encoded)), _SCAN_CHUNK):
        end = start + _SCAN_CHUNK + _SCAN_OVERLAP
        # A slice never ends inside a word: a pattern's closing \b would match at the cut
        # ("you are now|here"), which the whole answer does not (review-H315g n2).
        stop = min(len(encoded), end + 256)
        while end < stop and (encoded[end].isalnum() or encoded[end] == "_"):
            end += 1
        if detect_injection(encoded[start:end]):
            return True
    return False


def _declares_taint(response: Any) -> bool:
    """A handler's own answer, under ``result``, says its content is tainted."""
    inner = response.get("result") if isinstance(response, dict) else None
    return isinstance(inner, dict) and inner.get("tainted") is True


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
        invocation: SandboxInvocation | None = None,
        revoked: Callable[[], bool] | None = None,
        max_tool_calls: int = 50,
        poll_interval: float = 0.01,
        service_timeout: float | None = None,
    ) -> None:
        self.server = server
        self.sandbox = sandbox
        # No invocation means no authority. The run still executes — plain Python in
        # the sandbox is the caller's own business — but every tool call it attempts
        # is refused, because the alternative is acting as the server's default agent.
        self.invocation = invocation
        self.revoked = revoked
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
        sinks=None,
        before_execute=None,
    ) -> ToolRPCSandboxRun:
        """``sinks`` is handed straight to the sandbox; see ``Sandbox.execute_python``.

        Passed through rather than interpreted here: this runtime services tool calls
        while the child runs and has no business deciding what happens to its output.
        """
        run_id = uuid.uuid4().hex
        # The sandbox makes its run directory right (0700, its lock) before the RPC
        # mailbox inside it would make it again with the umask's mode (review-H667b m2).
        ensure = getattr(self.sandbox, "ensure_work_dir", None)
        if ensure is not None:
            ensure()
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
        async def execute():
            if before_execute is not None:
                before_execute()
            return await self.sandbox.execute_python(
                script, filename, writable_paths=[rpc_dir], sinks=sinks)

        task = asyncio.create_task(execute())

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
        # A broker per request is enough here: this loop services every request of the
        # run in one context, so the origin an untrusted read raised holds for the next.
        return await ToolCallBroker(
            self.server, self.invocation, revoked=self.revoked,
        ).call(tool, args)

    def _child_rpc_dir(self, run_id: str) -> str:
        if self.sandbox.active_backend() in {"docker", "wasm"}:
            return f"/workspace/.jarvis_file_rpc/{run_id}"
        return str(self.sandbox.work_dir / ".jarvis_file_rpc" / run_id)
