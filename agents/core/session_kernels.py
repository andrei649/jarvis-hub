"""K2: a resident interpreter per authorized session, and why each cell re-earns it.

K1 gave the model one container per call. That is correct and it is expensive: an
analysis that needs a loaded dataframe re-loads it every single call, and on a local
model that is the difference between a task that finishes and one that spends its
context re-printing setup code. A session kernel keeps the variables, the imports and
the loaded data alive between calls.

**The danger is exactly the thing that makes it useful.** A long-lived interpreter that
was authorized once and then accepts arbitrary later code is a kernel bypass with extra
steps: cell 1 is reviewed, cell 400 is not, and the process in between belongs to
whoever spoke last. So the rule this module is built around is that *state* persists
and *permission* does not:

* **Every cell re-authorizes.** The caller binds a fresh ``SandboxInvocation`` (K0) per
  cell and passes an ``authorize`` callback that must return cleanly before a single
  byte reaches the interpreter. A refusal never touches the kernel — it cannot, because
  the write happens after the callback returns.
* **A retained variable never retains permission.** The record stores the *key*, never
  an invocation. Tool authority for a cell comes from that cell's own invocation, so a
  variable created while a tool was offered is still just a variable once it is not.
* **The key is the host's.** Principal, data scope, session and agent are read off the
  invocation the host resolved; there is no model-supplied kernel id to guess, collide
  with or borrow. Two sessions cannot share a kernel even by asking for the same name.
* **Losing state is said out loud.** Reset, idle expiry, eviction, a crash, a timeout
  and ESTOP all produce a named ``state_lost`` reason on the next cell. Silently
  starting a fresh interpreter under a caller who thinks it still holds their dataframe
  is how a wrong answer gets built on a confident premise.
* **ESTOP kills, it does not queue.** The sentinel is checked before every cell, and an
  engaged stop tears every kernel down rather than leaving processes alive to resume.

Isolation is the backend's. ``PipeKernelBackend`` is the transport — one resident
process, its stdin and stdout held open for the kernel's life — and ``docker_kernel``
supplies the argv that makes that process a pinned, network-less container. Nothing
here relaxes the sandbox profile, and nothing here may run model-written code on the
host: ``code_tools`` refuses the whole call unless the sandbox reports real isolation.

**Not proven in this repository's tests:** that any of this holds against a real Docker
daemon. The tests drive real resident interpreters over the real framing with the real
worker source, so the protocol, the lifecycle and every refusal are exercised — but a
container is the owner's to prove.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import secrets
import shutil
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .environments.file_rpc import FileRPCStore
from .environments.output_limits import MAX_OUTPUT_BYTES

logger = logging.getLogger("jarvis.session_kernels")

DEFAULT_MAX_KERNELS = 4
DEFAULT_IDLE_TTL_SECONDS = 900.0
DEFAULT_CELL_TIMEOUT_SECONDS = 30.0
#: Imported, not redeclared (H298): a kernel cell's stdout is a tool result
#: like any other, and a second literal is how two 50 KB limits drift apart.
DEFAULT_MAX_OUTPUT_BYTES = MAX_OUTPUT_BYTES
MAX_CELL_CHARS = 32_768
#: How many dead keys keep their loss reason. Oldest first out.
_MAX_REMEMBERED_LOSSES = 256
#: Where the per-kernel tool-call mailbox appears *inside* the container. The host
#: side is a real directory under the data root; only this one path is shared, and
#: it carries request/response JSON, never source and never a result payload.
CHILD_RPC_ROOT = "/nerva-rpc"
#: Replies are framed behind a random per-kernel token, so a cell cannot forge one by
#: writing to ``sys.__stdout__``. The worker already redirects the cell's own streams;
#: the token is the second lock on the same door, and it is regenerated per kernel.

#: Refusal reasons. Bounded strings — never a caller's text and never a path.
ESTOP_ENGAGED = "estop_engaged"
AUTHORITY_EXPIRED = "authority_expired"
CELL_REFUSED = "cell_refused"
KERNEL_UNAVAILABLE = "kernel_unavailable"
CELL_TOO_LONG = "cell_too_long"

#: Named state loss. The caller is told which of these happened, every time.
NEW_KERNEL = "new"
CONTINUED = "continued"
RESET = "reset"
EXPIRED = "expired"
EVICTED = "evicted"
CRASHED = "crashed"
TIMED_OUT = "timed_out"
STOPPED = "stopped"

#: The continuity values that mean an interpreter a caller was using is gone.
DESTRUCTIVE = frozenset({RESET, EXPIRED, EVICTED, CRASHED, TIMED_OUT, STOPPED})


class KernelRefused(Exception):
    """A bounded reason. Carries no cell source and no caller text."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


WORKER_SOURCE = r'''
import contextlib, io, json, os, sys, time, traceback

# The reply token arrives over stdin as the first line, never in the environment: an
# env var is readable from `docker inspect` and from /proc/1/environ, and this one is
# the only thing stopping a cell from forging a result. The cell never sees stdin.
_INIT = json.loads(sys.stdin.readline() or "{}")
REPLY = str(_INIT.get("token") or "")
CAP = int(_INIT.get("max_output") or 50000)
RPC_TIMEOUT = float(_INIT.get("rpc_timeout") or 30)
# The cell's namespace. It is created once and never replaced: that persistence is
# the entire feature. `__name__` is set so `if __name__ == "__main__"` behaves the
# way a script author expects.
NS = {"__name__": "__main__", "__builtins__": __builtins__}
# Where THIS cell's tool calls go. The host services exactly this directory, under
# exactly this cell's authority, and points it somewhere new for the next cell. A
# `jarvis_tool_call` captured in a variable ten cells ago therefore still runs under
# the current cell's permission — it cannot address a directory nobody is watching.
CELL = {"dir": "", "calls": 0, "max_calls": 0}
# Hold the real stdout aside before anything can rebind it, and use it only for
# framed replies. The cell never gets a handle to it.
CHANNEL = sys.stdout
sys.stdout = io.StringIO()


def reply(payload):
    body = json.dumps(payload, ensure_ascii=False)
    CHANNEL.write("%s %d\n%s" % (REPLY, len(body.encode("utf-8")), body))
    CHANNEL.flush()


def jarvis_tool_call(tool, args=None):
    """Ask the host for one tool call. Same wire format as the one-shot sandbox."""
    name = str(tool or "")
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return {"ok": False, "reason": "bad_args", "tool": name}
    if not name:
        return {"ok": False, "reason": "tool_not_allowed", "tool": name}
    if not CELL["dir"]:
        return {"ok": False, "reason": "tool_calls_unavailable", "tool": name}
    if CELL["calls"] >= CELL["max_calls"]:
        return {"ok": False, "reason": "tool_call_limit_exceeded", "tool": name}
    CELL["calls"] += 1
    seq = CELL["calls"]
    token = "%06d" % seq
    base = os.path.join(CELL["dir"], "req_" + token + ".json")
    tmp = base + ".tmp"
    res = os.path.join(CELL["dir"], "res_" + token + ".json")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump({"seq": seq, "tool": name, "args": args}, handle, ensure_ascii=False)
        os.replace(tmp, base)
    except OSError:
        return {"ok": False, "reason": "file_rpc_unavailable", "tool": name}
    deadline = time.monotonic() + RPC_TIMEOUT
    while time.monotonic() < deadline:
        if os.path.exists(res):
            try:
                with open(res, encoding="utf-8") as handle:
                    payload = json.load(handle)
                os.unlink(res)
            except Exception:
                return {"ok": False, "reason": "bad_response", "tool": name}
            if isinstance(payload, dict):
                return payload
            return {"ok": False, "reason": "bad_response", "tool": name}
        time.sleep(0.01)
    return {"ok": False, "reason": "file_rpc_timeout", "tool": name}


NS["jarvis_tool_call"] = jarvis_tool_call


def run(source):
    out, err = io.StringIO(), io.StringIO()
    failed = ""
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            exec(compile(source, "<cell>", "exec"), NS)
    except BaseException:
        # A cell that raises must not take the kernel with it: the state a caller
        # built over ten cells is worth more than the eleventh cell's traceback.
        # SystemExit included — `sys.exit()` in a cell ends the cell, not the kernel.
        failed = traceback.format_exc()
    return {
        "stdout": out.getvalue()[-CAP:],
        "stderr": (err.getvalue() + failed)[-CAP:],
        "failed": bool(failed),
    }


for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        request = json.loads(line)
    except Exception:
        reply({"ok": False, "reason": "bad_request"})
        continue
    if request.get("op") == "close":
        break
    CELL["dir"] = str(request.get("rpc_dir") or "")
    CELL["calls"] = 0
    CELL["max_calls"] = int(request.get("max_calls") or 0)
    try:
        result = run(str(request.get("cell") or ""))
        reply({"ok": True, "tool_calls": CELL["calls"], **result})
    except Exception:
        reply({"ok": False, "reason": "worker_error"})
    finally:
        # Close the door behind the cell: between cells there is no directory to
        # write to, so a background thread a cell left running cannot keep calling.
        CELL["dir"] = ""
'''


@dataclass(frozen=True, slots=True)
class KernelKey:
    """Who a kernel belongs to. Built from host state; there is no id to supply."""

    agent: str
    principal: str
    session_id: str
    data_scope: str

    @classmethod
    def from_invocation(cls, invocation) -> KernelKey:
        scope = getattr(invocation, "data_scope", None)
        return cls(
            agent=str(getattr(invocation, "agent", "") or ""),
            principal=str(getattr(invocation, "principal", "") or ""),
            session_id=str(getattr(invocation, "session_id", "") or ""),
            data_scope="*" if scope is None else ",".join(sorted(str(s) for s in scope)),
        )

    @property
    def token(self) -> str:
        """A stable, opaque handle for logs and container names. Not a secret."""
        raw = "\x1f".join((self.agent, self.principal, self.session_id, self.data_scope))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def as_dict(self) -> dict:
        return {"agent": self.agent, "principal": self.principal,
                "session_id": self.session_id, "data_scope": self.data_scope,
                "token": self.token}


@dataclass(slots=True)
class CellOutcome:
    """What one cell did, and what the caller lost on the way in."""

    ok: bool
    stdout: str = ""
    stderr: str = ""
    failed: bool = False
    #: True only when state that *existed* was destroyed. A brand-new kernel has
    #: lost nothing, and saying it did would train a caller to ignore the field.
    state_lost: bool = False
    #: What this cell is continuing, in one word: ``new``, ``continued``, or the
    #: name of what ended the previous interpreter.
    continuity: str = ""
    kernel_token: str = ""
    cells_run: int = 0
    tool_calls: int = 0
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "ok": self.ok, "stdout": self.stdout, "stderr": self.stderr,
            "failed": self.failed, "state_lost": self.state_lost,
            "continuity": self.continuity,
            "kernel_token": self.kernel_token, "cells_run": self.cells_run,
            "tool_calls": self.tool_calls,
            **({"reason": self.reason} if self.reason else {}),
        }


@dataclass(slots=True)
class _Record:
    key: KernelKey
    handle: object
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    created_at: float = 0.0
    last_used: float = 0.0
    cells_run: int = 0
    pending_loss: str = ""


class PipeKernelBackend:
    """One resident process per kernel, its stdin and stdout held open for its life.

    The argv is supplied by the caller, which is what keeps this module honest about
    isolation: the transport is the same whether the process is a container or a bare
    interpreter, and *choosing* the container is the wiring's job, not this class's.
    """

    def __init__(self, argv: Callable[..., Sequence[str]], *,
                 name: str = "pipe", max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
                 child_root: str | None = None,
                 rpc_timeout_seconds: float = 30.0,
                 available: Callable[[], bool] = lambda: True) -> None:
        self._argv = argv
        self.name = name
        # Where the shared mailbox appears to the child. A container sees a mount
        # point; a bare interpreter on the same filesystem sees the host path.
        self._child_root = child_root
        self._max_output_bytes = max(1_024, int(max_output_bytes))
        self._rpc_timeout = max(1.0, float(rpc_timeout_seconds))
        self._available = available

    def child_rpc_dir(self, host_dir: str) -> str:
        return self._child_root or host_dir

    def available(self) -> bool:
        try:
            return bool(self._available())
        except Exception:
            return False

    async def start(self, key: KernelKey, *, rpc_dir: str = "", child_rpc_dir: str = ""):
        if not self.available():
            raise KernelRefused(KERNEL_UNAVAILABLE)
        token = secrets.token_hex(16)
        argv = list(self._argv(key, token, rpc_dir))
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=self._child_env(),
            )
        except (OSError, ValueError):
            logger.warning("session kernel failed to start", exc_info=True)
            raise KernelRefused(KERNEL_UNAVAILABLE) from None
        try:
            process.stdin.write((json.dumps({
                "token": token, "max_output": self._max_output_bytes,
                "rpc_timeout": self._rpc_timeout,
            }) + "\n").encode("utf-8"))
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError, OSError):
            with contextlib.suppress(Exception):
                process.kill()
            raise KernelRefused(KERNEL_UNAVAILABLE) from None
        return _Handle(process=process, token=token, child_rpc_dir=child_rpc_dir)

    def _child_env(self) -> dict:
        """A frozen, minimal environment. Nothing of the host's is inherited.

        The host's environment is where the credentials live. A kernel that never
        receives it cannot leak one, and cannot be talked into printing one. Nothing
        of the *kernel's* own is here either: the token, the caps and the mailbox all
        travel over stdin, which no cell can read.
        """
        return {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            # nosec B108 — the *container's* own writable tmpfs, mounted noexec/nosuid
            # below. No host temp file is named here, and the pipe backend's local mode
            # is a test path that never runs model-written code in production.
            "HOME": "/tmp",  # noqa: S108
            "PYTHONUNBUFFERED": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }

    def alive(self, handle) -> bool:
        return handle is not None and handle.process.returncode is None

    async def run_cell(self, handle, cell: str, *, timeout: float,
                       rpc_dir: str = "", max_tool_calls: int = 0) -> dict:
        process = handle.process
        if process.returncode is not None:
            raise KernelRefused(CRASHED)
        envelope = json.dumps(
            {"cell": cell, "rpc_dir": rpc_dir, "max_calls": int(max_tool_calls)},
            ensure_ascii=False,
        ) + "\n"
        try:
            process.stdin.write(envelope.encode("utf-8"))
            await process.stdin.drain()
            return await asyncio.wait_for(
                self._read_reply(process, handle.token), timeout=max(0.1, float(timeout)))
        except TimeoutError:
            raise KernelRefused(TIMED_OUT) from None
        except (BrokenPipeError, ConnectionResetError, OSError, ValueError):
            raise KernelRefused(CRASHED) from None

    async def _read_reply(self, process, token: str) -> dict:
        """Read one framed reply, ignoring anything that is not ours.

        The worker redirects the cell's streams, so a cell should never reach this
        channel at all. Skipping unframed lines rather than failing on them means a
        cell that finds a way to write one is noise, not a forged result.
        """
        prefix = f"{token} ".encode()
        while True:
            header = await process.stdout.readline()
            if not header:
                raise KernelRefused(CRASHED)
            if not header.startswith(prefix):
                continue
            try:
                size = int(header[len(prefix):].strip())
            except ValueError:
                continue
            if size < 0 or size > 8 * self._max_output_bytes + 4_096:
                raise KernelRefused(CRASHED)
            body = await process.stdout.readexactly(size)
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                raise KernelRefused(CRASHED) from None
            if not isinstance(payload, dict):
                raise KernelRefused(CRASHED)
            return payload

    async def stop(self, handle) -> None:
        process = getattr(handle, "process", None)
        if process is None or process.returncode is not None:
            return
        # Ask, then insist. A timed-out cell is still running inside; the point of
        # kill() is that the whole process goes, not just the cell.
        with contextlib.suppress(Exception):
            process.stdin.write(b'{"op": "close"}\n')
            await process.stdin.drain()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(process.wait(), timeout=2.0)
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError, OSError):
                process.kill()
            with contextlib.suppress(Exception):
                await process.wait()


@dataclass(slots=True)
class _Handle:
    process: object
    token: str
    child_rpc_dir: str = ""


def docker_kernel_argv(image: str, *, memory_mb: int = 256, pids: int = 64):
    """The argv that turns the pipe transport into a pinned, network-less container.

    ``image`` must be pinned by digest by the caller — a moving tag is a different
    program tomorrow, and a kernel that survives an hour deserves the same pin the
    acquisition profile demands.
    """

    def argv(key: KernelKey, token: str, rpc_dir: str = "") -> list[str]:  # noqa: ARG001
        mount = ["-v", f"{rpc_dir}:{CHILD_RPC_ROOT}"] if rpc_dir else []
        return [
            "docker", "run", "--rm", "-i",
            *mount,
            "--name", f"nerva-kernel-{key.token}-{token[:8]}",
            "--network", "none",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--read-only",
            # nosec B108 — a tmpfs mount spec for the container, not a host path: the
            # root filesystem is read-only, so this is the only place a cell may write.
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m",  # noqa: S108
            "--memory", f"{int(memory_mb)}m",
            "--memory-swap", f"{int(memory_mb)}m",
            "--pids-limit", str(int(pids)),
            # No --env carrying the reply token: `docker inspect` would print it.
            "--env", "PYTHONUNBUFFERED=1",
            image, "python", "-c", WORKER_SOURCE,
        ]

    return argv


class SessionKernelManager:
    """Own the kernels: one per key, one cell at a time, and never a stale permission."""

    def __init__(
        self,
        backend,
        *,
        max_kernels: int = DEFAULT_MAX_KERNELS,
        idle_ttl_seconds: float = DEFAULT_IDLE_TTL_SECONDS,
        cell_timeout_seconds: float = DEFAULT_CELL_TIMEOUT_SECONDS,
        estop: Callable[[], bool] | None = None,
        rpc_root: str | None = None,
        max_tool_calls: int = 50,
        poll_interval: float = 0.01,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._backend = backend
        self._rpc_root = None if rpc_root is None else Path(rpc_root)
        self._max_tool_calls = max(0, int(max_tool_calls))
        self._poll_interval = max(0.001, float(poll_interval))
        self._max_kernels = max(1, int(max_kernels))
        self._idle_ttl = max(1.0, float(idle_ttl_seconds))
        self._cell_timeout = max(0.1, float(cell_timeout_seconds))
        self._estop = estop
        self._clock = clock
        self._records: dict[KernelKey, _Record] = {}
        # Why a key's kernel went away, kept until the next cell for that key reads
        # it. Without this, a caller whose kernel was evicted or reaped between calls
        # would be handed a fresh interpreter labelled "new_kernel" — true, and
        # useless: they need to know their state is gone, not that this one is young.
        # Bounded, because a key is a principal x session and both are unbounded.
        self._expiries: dict[KernelKey, str] = {}
        self._guard = asyncio.Lock()

    # ── the cell ─────────────────────────────────────────────────────────────

    async def run(self, invocation, cell: str, *,
                  authorize: Callable[[str], None] | None = None,
                  broker=None) -> CellOutcome:
        """Run one cell in this invocation's kernel, re-earning the right first.

        ``invocation`` is a *fresh* K0 binding for this cell, not the one that started
        the kernel, and ``broker`` is built from that same binding. Nothing about the
        running interpreter is consulted to decide what this cell may do — which is
        what makes a variable that outlives a permission harmless.
        """
        if not isinstance(cell, str) or not cell.strip():
            return CellOutcome(ok=False, reason=CELL_REFUSED)
        if len(cell) > MAX_CELL_CHARS:
            return CellOutcome(ok=False, reason=CELL_TOO_LONG)
        if self._stopped():
            # Engaged means gone, not paused: leaving interpreters alive to resume
            # would make the stop a suggestion.
            await self.shutdown(STOPPED)
            return CellOutcome(ok=False, reason=ESTOP_ENGAGED)
        if self._expired(invocation):
            await self._drop(KernelKey.from_invocation(invocation), EXPIRED)
            return CellOutcome(ok=False, reason=AUTHORITY_EXPIRED)
        if authorize is not None:
            try:
                authorize(cell)
            except KernelRefused:
                raise
            except Exception as exc:
                # The cell never reaches the interpreter: the write is below this.
                return CellOutcome(ok=False, reason=str(getattr(exc, "reason", CELL_REFUSED)))

        key = KernelKey.from_invocation(invocation)
        # Acquire, lock, then re-check: a reset or a crash can land between the two,
        # and holding the *previous* record's lock while running on a new one would
        # let two cells into the same interpreter at once. On a mismatch, drop the
        # lock and try again rather than proceed on a stale record.
        for _attempt in range(3):
            try:
                record = await self._acquire(key)
            except KernelRefused as refusal:
                # A backend that cannot start one, or a pool with nothing free to
                # evict. The caller gets a named refusal: raising out of a tool
                # handler would reach the model as a generic `tool_error` instead.
                return CellOutcome(ok=False, reason=refusal.reason)
            async with record.lock:
                if self._stopped():
                    await self.shutdown(STOPPED)
                    return CellOutcome(ok=False, reason=ESTOP_ENGAGED)
                if self._records.get(key) is not record or not self._backend.alive(record.handle):
                    continue
                return await self._cell(key, record, cell, broker)
        return CellOutcome(ok=False, reason=KERNEL_UNAVAILABLE)

    async def _cell(self, key: KernelKey, record: _Record, cell: str,
                    broker=None) -> CellOutcome:
        """Run one cell on a record whose lock this call holds."""
        continuity, record.pending_loss = record.pending_loss or CONTINUED, ""
        mailbox, child_mailbox = self._cell_mailbox(record, broker)
        try:
            payload = await self._run_serviced(
                record, cell, mailbox, child_mailbox, broker)
        except KernelRefused as refusal:
            # A timeout or a crash takes the whole interpreter down. The next cell is
            # told what it lost rather than quietly being handed a new one.
            await self._drop(key, refusal.reason)
            return CellOutcome(ok=False, reason=refusal.reason, state_lost=True,
                               continuity=refusal.reason, kernel_token=key.token)
        record.cells_run += 1
        record.last_used = self._clock()
        if not payload.get("ok"):
            await self._drop(key, CRASHED)
            return CellOutcome(ok=False, reason=str(payload.get("reason") or CRASHED),
                               state_lost=True, continuity=CRASHED, kernel_token=key.token)
        return CellOutcome(
            ok=not payload.get("failed"),
            stdout=str(payload.get("stdout") or ""),
            stderr=str(payload.get("stderr") or ""),
            failed=bool(payload.get("failed")),
            state_lost=continuity in DESTRUCTIVE, continuity=continuity,
            kernel_token=key.token, cells_run=record.cells_run,
            tool_calls=int(payload.get("tool_calls") or 0),
        )

    # ── the per-cell mailbox ─────────────────────────────────────────────────

    def _cell_mailbox(self, record: _Record, broker) -> tuple[Path | None, str]:
        """A fresh directory for this cell's tool calls, or none if it may make none.

        A new directory per cell is not tidiness: it is the mechanism. The host
        services only the current cell's directory, under only the current cell's
        authority, so a shim captured in an earlier cell writes where nobody reads.
        """
        root = getattr(record.handle, "child_rpc_dir", "")
        if broker is None or self._rpc_root is None or not root:
            return None, ""
        name = f"cell-{record.cells_run + 1:06d}"
        mailbox = self._rpc_root / record.key.token / name
        try:
            mailbox.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.warning("session kernel mailbox unavailable", exc_info=True)
            return None, ""
        return mailbox, f"{root}/{name}"

    async def _run_serviced(self, record: _Record, cell: str, mailbox: Path | None,
                            child_mailbox: str, broker) -> dict:
        """Run the cell, answering its tool calls while it runs."""
        if mailbox is None:
            return await self._backend.run_cell(
                record.handle, cell, timeout=self._cell_timeout)
        store = FileRPCStore(mailbox, max_tool_calls=self._max_tool_calls)
        task = asyncio.ensure_future(self._backend.run_cell(
            record.handle, cell, timeout=self._cell_timeout,
            rpc_dir=child_mailbox, max_tool_calls=self._max_tool_calls))
        served: set[int] = set()
        try:
            while not task.done():
                await self._service(store, served, broker)
                await asyncio.sleep(self._poll_interval)
            await self._service(store, served, broker)
            return await task
        finally:
            if not task.done():
                task.cancel()
            with contextlib.suppress(Exception):
                shutil.rmtree(mailbox)

    async def _service(self, store: FileRPCStore, served: set[int], broker) -> None:
        limit = max(64, self._max_tool_calls * 2)
        for request in store.pending_requests(limit=limit):
            if request.seq in served:
                self._consume(store, request.seq)
                continue
            served.add(request.seq)
            if len(served) > self._max_tool_calls:
                store.write_response(request.seq, {
                    "ok": False, "reason": "tool_call_limit_exceeded",
                    "tool": request.tool})
            else:
                store.write_response(request.seq, await broker.call(request.tool, request.args))
            self._consume(store, request.seq)

    @staticmethod
    def _consume(store: FileRPCStore, seq: int) -> None:
        with contextlib.suppress(OSError):
            store.request_path(seq).unlink(missing_ok=True)

    # ── lifecycle ────────────────────────────────────────────────────────────

    async def reset(self, invocation) -> bool:
        """Destroy this session's kernel. The next cell is told it started over."""
        return await self._drop(KernelKey.from_invocation(invocation), RESET)

    async def close_session(self, session_id: str) -> int:
        keys = [key for key in list(self._records) if key.session_id == str(session_id)]
        for key in keys:
            await self._drop(key, STOPPED)
        return len(keys)

    async def shutdown(self, reason: str = STOPPED) -> int:
        keys = list(self._records)
        for key in keys:
            await self._drop(key, reason)
        return len(keys)

    def status(self) -> list[dict]:
        """An owner-readable projection. Keys and counters, never a cell or a value."""
        now = self._clock()
        return sorted(
            ({**key.as_dict(), "cells_run": record.cells_run,
              "idle_seconds": round(max(0.0, now - record.last_used), 3),
              "alive": self._backend.alive(record.handle),
              "backend": getattr(self._backend, "name", "unknown")}
             for key, record in self._records.items()),
            key=lambda row: row["token"],
        )

    # ── internals ────────────────────────────────────────────────────────────

    def _stopped(self) -> bool:
        if self._estop is None:
            return False
        try:
            return bool(self._estop())
        except Exception:
            return True  # an unreadable stop is an engaged one

    def _expired(self, invocation) -> bool:
        try:
            return bool(invocation.expired())
        except Exception:
            return True

    async def _acquire(self, key: KernelKey, *, lost: str = "") -> _Record:
        async with self._guard:
            await self._reap()
            record = self._records.get(key)
            if record is not None and self._backend.alive(record.handle):
                if lost:
                    record.pending_loss = lost
                return record
            if record is not None:
                await self._stop_record(key, record)
                lost = lost or CRASHED
            while len(self._records) >= self._max_kernels:
                await self._evict()
            handle = await self._backend.start(key, **self._mount(key))
            now = self._clock()
            record = _Record(key=key, handle=handle, created_at=now, last_used=now,
                             pending_loss=lost or self._expiries.pop(key, "") or NEW_KERNEL)
            self._records[key] = record
            return record

    def _mount(self, key: KernelKey) -> dict:
        """The one shared directory a kernel gets, created before it starts."""
        if self._rpc_root is None:
            return {}
        host = self._rpc_root / key.token
        try:
            host.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.warning("session kernel rpc root unavailable", exc_info=True)
            return {}
        return {"rpc_dir": str(host), "child_rpc_dir": self._backend.child_rpc_dir(str(host))}

    async def _reap(self) -> None:
        cutoff = self._clock() - self._idle_ttl
        for key, record in list(self._records.items()):
            if record.last_used < cutoff and not record.lock.locked():
                await self._stop_record(key, record)
                self._records.pop(key, None)
                self._remember(key, EXPIRED)

    async def _evict(self) -> None:
        idle = [(record.last_used, key) for key, record in self._records.items()
                if not record.lock.locked()]
        if not idle:
            # Every kernel is mid-cell. Refusing is better than killing a running
            # cell to make room for a new one.
            raise KernelRefused(KERNEL_UNAVAILABLE)
        _, key = min(idle)
        record = self._records.pop(key)
        await self._stop_record(key, record)
        self._remember(key, EVICTED)

    async def _drop(self, key: KernelKey, reason: str) -> bool:
        record = self._records.pop(key, None)
        self._remember(key, reason)
        if record is None:
            return False
        await self._stop_record(key, record)
        return True

    async def _stop_record(self, key: KernelKey, record: _Record) -> None:
        with contextlib.suppress(Exception):
            await self._backend.stop(record.handle)

    def _remember(self, key: KernelKey, reason: str) -> None:
        """Keep the loss reason for the next cell, without growing without bound."""
        self._expiries[key] = reason
        while len(self._expiries) > _MAX_REMEMBERED_LOSSES:
            self._expiries.pop(next(iter(self._expiries)))


__all__ = [
    "AUTHORITY_EXPIRED", "CELL_REFUSED", "CELL_TOO_LONG", "CRASHED", "CellOutcome",
    "DEFAULT_CELL_TIMEOUT_SECONDS", "DEFAULT_IDLE_TTL_SECONDS", "DEFAULT_MAX_KERNELS",
    "CONTINUED", "DESTRUCTIVE", "ESTOP_ENGAGED", "EVICTED", "EXPIRED", "KERNEL_UNAVAILABLE", "KernelKey",
    "KernelRefused", "MAX_CELL_CHARS", "NEW_KERNEL", "PipeKernelBackend", "RESET",
    "STOPPED", "SessionKernelManager", "TIMED_OUT", "WORKER_SOURCE",
    "docker_kernel_argv",
]
