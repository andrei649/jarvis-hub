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

The opt-in Docker isolation suite exercises the detached production transport on a
real daemon. Local interpreter protocol tests do not prove container isolation.
The framing token and cell nonce detect noise/stale replies; they are not a security
boundary against Python code introspecting the worker's own interpreter. Authority
is enforced by the host broker, never by a worker's claims.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .action_origin import current_action_origin
from .environments.output_limits import MAX_OUTPUT_BYTES, render_capped
from .security.taint import is_untrusted_source
from .session_kernel_mailbox import SessionRPCStore

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
#: Replies carry a random per-kernel token and a per-cell nonce to detect stale
#: frames and accidental output on the protocol channel. The host broker, not
#: these worker-readable values, is the authority boundary.

#: Refusal reasons. Bounded strings — never a caller's text and never a path.
ESTOP_ENGAGED = "estop_engaged"
AUTHORITY_EXPIRED = "authority_expired"
CELL_REFUSED = "cell_refused"
KERNEL_UNAVAILABLE = "kernel_unavailable"
TEARDOWN_UNCONFIRMED = "teardown_unconfirmed"
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


class KernelStartupUnavailable(KernelRefused):
    """No cell was dispatched; the governed isolated per-call path is safe."""


_OWNER_DIR = re.compile(r"p(\d{1,10})-[0-9a-f]{8}")
_OWNER_LOCK = ".lock"

try:                                     # POSIX; elsewhere owner directories age out
    import fcntl as _fcntl
except ImportError:                      # pragma: no cover - Windows
    _fcntl = None


def _hold_owner_lock(owner_dir: Path):
    """Take this manager's owner lock and keep it for the process's life: an exclusive
    ``flock`` on ``<owner>/.lock``. The kernel drops it when the process ends, however it
    ends, and it means the same in every pid namespace that shares the data root, where a
    pid does not (review-H315f m1: a hub is PID 1 in every container start).

    The directory is built under a temporary name the sweep never takes for an owner's,
    locked there, and only then renamed into place: another start never sees the owner
    directory with a lock nobody holds, so it can neither take the lock nor remove the
    directory while this one is being made (review-H315g m1)."""
    if _fcntl is None:
        return None
    staging = owner_dir.with_name(f".{owner_dir.name}-{secrets.token_hex(4)}.tmp")
    fd = None
    try:
        staging.mkdir(parents=True, exist_ok=False)
        fd = os.open(staging / _OWNER_LOCK, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        os.rename(staging, owner_dir)
    except OSError:
        if fd is not None:
            os.close(fd)
        shutil.rmtree(staging, ignore_errors=True)
        logger.warning("session kernel owner lock unavailable", exc_info=True)
        return None
    return fd


LOCK_HELD, LOCK_UNKNOWN, LOCK_LOST = "held", "unknown", "lost"


def _lock_state(owner_dir: Path, fd) -> str:
    """Whether the lock this manager holds is still the one at ``<owner>/.lock``.

    A ``.lock`` that is gone or is another file reads as lost, and so does an owner path
    that is no longer a directory (ENOTDIR, a symlink loop) or an fd the manager no longer
    has (review-H315i n1). Any other error (ESTALE, EACCES, ENOMEM) says nothing about the
    lock, which is kept: a manager that gave up an intact lock over its live mounts let
    the next start remove them (review-H315h m1)."""
    if fd is None:
        return LOCK_LOST
    try:
        held = os.fstat(fd)
    except OSError as exc:
        # EBADF: the fd is gone, and so is the lock. Anything else (ENOMEM) says nothing
        # about it, and it is kept (review-H315j m2).
        return LOCK_LOST if exc.errno == errno.EBADF else LOCK_UNKNOWN
    try:
        there = os.stat(owner_dir / _OWNER_LOCK, follow_symlinks=False)
    except (FileNotFoundError, NotADirectoryError):
        return LOCK_LOST
    except OSError as exc:
        return LOCK_LOST if exc.errno == errno.ELOOP else LOCK_UNKNOWN
    return LOCK_HELD if (held.st_ino, held.st_dev) == (there.st_ino, there.st_dev) else LOCK_LOST


def _relock_in_place(owner_dir: Path):
    """Hold ``<owner>/.lock`` again in a directory this manager still owns, whose lock file
    went or was replaced: its live mounts keep a holder, so no other start removes them
    (review-H315h m1). A new lock file is made and locked under a staging name and only
    then renamed over ``.lock``, so the name never holds a file nobody has locked
    (review-H315i m2); a ``.lock`` that is there is held while that happens. None when
    the directory is gone or a link, or someone else holds the file there (a start
    judging the directory, which will remove it)."""
    try:
        if _fcntl is None or owner_dir.is_symlink() or not owner_dir.is_dir():
            return None
    except OSError:                      # a root this user cannot search (review-H315j n3)
        return None
    lock = owner_dir / _OWNER_LOCK
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        old = os.open(lock, os.O_RDWR | nofollow)
    except FileNotFoundError:
        old = None
    except OSError:
        return None
    try:
        if old is not None:
            try:
                _fcntl.flock(old, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
            except OSError:
                return None
        staged = owner_dir / f"{_OWNER_LOCK}.{secrets.token_hex(4)}.tmp"
        try:
            fd = os.open(staged, os.O_RDWR | os.O_CREAT | os.O_EXCL | nofollow, 0o600)
        except OSError:
            return None
        try:
            _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
            os.replace(staged, lock)
            held, there = os.fstat(fd), os.stat(lock, follow_symlinks=False)
            if (held.st_ino, held.st_dev) == (there.st_ino, there.st_dev):
                return fd
        except OSError:
            pass
        os.close(fd)
        with contextlib.suppress(OSError):
            staged.unlink()
        return None
    finally:
        if old is not None:
            os.close(old)


def _owner_alive(owner_dir: Path) -> bool | None:
    """Whether the manager that owns ``owner_dir`` still runs: its lock is held. None when
    that cannot be told (no lock file: a directory from before the lock, or no flock), so
    the caller falls back to the directory's age. An error reads as alive."""
    lock = owner_dir / _OWNER_LOCK
    try:
        if _fcntl is None or lock.is_symlink() or not lock.is_file():
            return None
    except OSError:
        # Another user's directory (umask 077) cannot even be looked into: whatever runs
        # there, it is not this process's to remove (review-H315i m3).
        return True
    try:
        fd = os.open(lock, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return True
    try:
        _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        # The file locked must still be the one at .lock: an owner that relocked in the
        # meantime renamed a new, held file over it, and the file taken here is an orphan
        # that says nothing about the owner (review-H315j m1).
        held, there = os.fstat(fd), os.stat(lock, follow_symlinks=False)
        if (held.st_ino, held.st_dev) != (there.st_ino, there.st_dev):
            return True
    except BlockingIOError:
        return True
    except OSError:
        return True
    finally:
        os.close(fd)                     # closing drops a lock this call took
    return False


class KernelTeardownUnconfirmed(KernelRefused):
    """Keep an unresolved startup handle visible until removal is confirmed."""
    def __init__(self, handle, *, cancelled=False):
        super().__init__(TEARDOWN_UNCONFIRMED)
        self.handle = handle
        self.cancelled = cancelled


WORKER_SOURCE = r'''
import contextlib, io, json, os, sys, time, traceback

# The reply token arrives over stdin as the first line, never in the environment: an
# env var is readable from `docker inspect` and from /proc/1/environ, and this one is
# correlation marker for framed output. It is not a boundary against worker introspection.
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
CELL_ID = ""
CHANNEL = sys.stdout
sys.stdout = open(os.devnull, "w")


def reply(payload):
    body = json.dumps({**payload, "cell_id": CELL_ID}, ensure_ascii=False)
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


class CellStream:
    def __init__(self, label):
        self.label = label
    def write(self, text):
        # Never hold a second full copy of a large write. Each frame is bounded,
        # and transport backpressure bounds queued output on both sides.
        for start in range(0, len(text), 4096):
            reply({"stream": self.label, "text": text[start:start + 4096]})
        return len(text)
    def flush(self):
        pass


def run(source):
    failed = False
    with contextlib.redirect_stdout(CellStream("stdout")), contextlib.redirect_stderr(CellStream("stderr")):
        try:
            exec(compile(source, "<cell>", "exec"), NS)
        except BaseException:
            failed = True
            traceback.print_exc()
    return {"failed": failed}


reply({"ready": True})

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
    CELL_ID = str(request.get("cell_id") or "")
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
    fallback_safe: bool = False
    #: The kernel has held untrusted text by the end of this cell (H315 third review):
    #: the caller declares it in its result, so the loop fences the output and raises
    #: the turn's taint whether the cell succeeded or not.
    tainted: bool = False

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
    quarantined: bool = False
    teardown_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    #: The interpreter has held untrusted text: a cell of it read an untrusted tool, or
    #: ran in a turn that had. Its variables outlive the turn, so every later cell runs
    #: tainted until a reset replaces the record (H315 second review).
    tainted: bool = False
    #: This interpreter's own host directory, shared with it as its mailbox root. It is
    #: new for every interpreter and removed when the interpreter is (H315 third review):
    #: a file a tainted kernel left there cannot reach the clean kernel after it.
    rpc_host: Path | None = None


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
        handle = _Handle(process=process, token=token, child_rpc_dir=child_rpc_dir)
        try:
            ready = await asyncio.wait_for(self._read_reply(process, token), 10)
            if not ready.get("ready"):
                raise KernelRefused(KERNEL_UNAVAILABLE)
        except BaseException:
            await self.stop(handle)
            raise
        return handle

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
                       rpc_dir: str = "", max_tool_calls: int = 0, sinks=None) -> dict:
        process = handle.process
        if process.returncode is not None:
            raise KernelRefused(CRASHED)
        cell_id = secrets.token_hex(16)
        envelope = json.dumps(
            {"cell": cell, "cell_id": cell_id, "rpc_dir": rpc_dir, "max_calls": int(max_tool_calls)},
            ensure_ascii=False,
        ) + "\n"
        try:
            process.stdin.write(envelope.encode("utf-8"))
            await process.stdin.drain()
            return await asyncio.wait_for(
                self._read_reply(process, handle.token, sinks=sinks, cell_id=cell_id), timeout=max(0.1, float(timeout)))
        except TimeoutError:
            raise KernelRefused(TIMED_OUT) from None
        except (BrokenPipeError, ConnectionResetError, OSError, ValueError, asyncio.IncompleteReadError):
            raise KernelRefused(CRASHED) from None

    async def _read_reply(self, process, token: str, *, sinks=None, cell_id="") -> dict:
        """Read one framed reply, ignoring anything that is not ours.

        The worker redirects the cell's streams, so a cell should never reach this
        channel at all. Skipping unframed lines rather than failing on them means a
        cell that finds a way to write one is noise, not a forged result.
        """
        captures = {label: _Capture(self._max_output_bytes, label, getattr(sinks, label, None))
                    for label in ("stdout", "stderr")}
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
            if payload.get("cell_id") != cell_id:
                raise KernelRefused(CRASHED)
            if "stream" in payload:
                label, text = payload.get("stream"), payload.get("text")
                if not isinstance(label, str) or label not in captures or not isinstance(text, str) or len(text) > 4096:
                    raise KernelRefused(CRASHED)
                captures[label].write(text.encode("utf-8"))
                continue
            ready = not cell_id and payload.get("ready") is True
            if not ready and (type(payload.get("ok")) is not bool
                              or type(payload.get("failed", False)) is not bool
                              or type(payload.get("tool_calls", 0)) is not int
                              or payload.get("tool_calls", 0) < 0):
                raise KernelRefused(CRASHED)
            return {**payload, **{label: capture.text() for label, capture in captures.items()}}

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


class _Capture:
    """Bounded preview plus an optional full-stream writer."""
    def __init__(self, cap, label, sink=None):
        self.cap, self.label, self.sink = cap, label, sink
        self.head, self.tail, self.total = b"", b"", 0

    def write(self, raw):
        self.total += len(raw)
        if self.sink is not None:
            self.sink(raw)
        take = max(0, self.cap // 2 - len(self.head))
        self.head += raw[:take]
        self.tail = (self.tail + raw[take:])[-(self.cap - self.cap // 2):]

    def text(self):
        return render_capped(self.head, self.tail, self.total,
                            max_content_bytes=self.cap, label=self.label.upper()).text


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
            # root filesystem is read-only, so a cell writes only here and in its mailbox
            # mount (above), which is this interpreter's own and removed with it.
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
        # This manager's own directory under the root, with a lock it holds while its
        # process runs, so another process's start can tell whose interpreters these are
        # and whether that process is gone (review-H315e m1, review-H315f m1).
        self._owner = f"p{os.getpid()}-{secrets.token_hex(4)}"
        self._owner_fd = None if self._rpc_root is None else _hold_owner_lock(self._rpc_root / self._owner)
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
        self._clear_stale_mounts()

    # ── the cell ─────────────────────────────────────────────────────────────

    async def run(self, invocation, cell: str, *,
                  authorize: Callable[[str], None] | None = None,
                  broker=None, sinks=None) -> CellOutcome:
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
            # Revoke dispatch immediately and attempt teardown. An unconfirmed
            # removal remains visible and quarantined; it must never be reused.
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
                current = self.dispatch_refusal(invocation)
                if current:
                    if current == ESTOP_ENGAGED:
                        await self.shutdown(STOPPED)
                    return CellOutcome(ok=False, reason=current)
                return CellOutcome(ok=False, reason=refusal.reason,
                                   fallback_safe=isinstance(refusal, KernelStartupUnavailable),
                                   state_lost=key in self._expiries,
                                   continuity=self._expiries.get(key, ""))
            async with record.lock:
                if self._stopped():
                    await self.shutdown(STOPPED)
                    return CellOutcome(ok=False, reason=ESTOP_ENGAGED)
                if self._expired(invocation):
                    await self._drop(key, EXPIRED)
                    return CellOutcome(ok=False, reason=AUTHORITY_EXPIRED)
                if record.quarantined:
                    return CellOutcome(ok=False, reason=TEARDOWN_UNCONFIRMED)
                if self._records.get(key) is not record or not self._backend.alive(record.handle):
                    continue
                return await self._cell(key, record, cell, broker, sinks)
        return CellOutcome(ok=False, reason=KERNEL_UNAVAILABLE)

    async def _cell(self, key: KernelKey, record: _Record, cell: str,
                    broker=None, sinks=None) -> CellOutcome:
        """Run one cell on a record whose lock this call holds.

        A kernel that has held untrusted text taints every call its next cell makes, and
        the cell's outcome says so, so the caller declares it and the loop fences the
        output and taints the turn that ran the cell, whether the cell succeeded or not.
        A cell that reads untrusted text, or runs in a turn that did, taints the kernel
        from then on."""
        tainted = record.tainted or is_untrusted_source(current_action_origin())
        if tainted and broker is not None:
            broker.tainted = True
        outcome = None
        try:
            outcome = await self._run_cell(key, record, cell, broker, sinks)
            return outcome
        finally:
            if tainted or getattr(broker, "tainted", False):
                record.tainted = True
                if outcome is not None:
                    outcome.tainted = True

    async def _run_cell(self, key: KernelKey, record: _Record, cell: str,
                        broker=None, sinks=None) -> CellOutcome:
        continuity, record.pending_loss = record.pending_loss or CONTINUED, ""
        mailbox, child_mailbox = self._cell_mailbox(record, broker)
        try:
            payload = await self._run_serviced(
                record, cell, mailbox, child_mailbox, broker, sinks)
        except OSError:
            await self._drop(key, CRASHED, expected=record)
            return self._failed_cell(key, CRASHED, record)
        except asyncio.CancelledError:
            await self._drop(key, STOPPED, expected=record)
            raise
        except KernelRefused as refusal:
            # A timeout or a crash takes the whole interpreter down. The next cell is
            # told what it lost rather than quietly being handed a new one.
            if refusal.reason == STOPPED:
                await self.shutdown(STOPPED)
            else:
                await self._drop(key, refusal.reason, expected=record)
            return self._failed_cell(key, refusal.reason, record)
        record.cells_run += 1
        record.last_used = self._clock()
        if not payload.get("ok"):
            await self._drop(key, CRASHED, expected=record)
            return self._failed_cell(key, CRASHED, record)
        return CellOutcome(
            ok=not payload.get("failed"),
            stdout=str(payload.get("stdout") or ""),
            stderr=str(payload.get("stderr") or ""),
            failed=bool(payload.get("failed")),
            state_lost=continuity in DESTRUCTIVE, continuity=continuity,
            kernel_token=key.token, cells_run=record.cells_run,
            tool_calls=int(payload.get("tool_calls") or 0),
        )

    def _failed_cell(self, key, reason, record):
        unresolved = self._records.get(key) is record and record.quarantined
        return CellOutcome(ok=False,
                           reason=TEARDOWN_UNCONFIRMED if unresolved else reason,
                           state_lost=not unresolved,
                           continuity=TEARDOWN_UNCONFIRMED if unresolved else reason,
                           kernel_token=key.token)

    # ── the per-cell mailbox ─────────────────────────────────────────────────

    def _cell_mailbox(self, record: _Record, broker) -> tuple[Path | None, str]:
        """A fresh directory for this cell's tool calls, or none if it may make none.

        A new directory per cell is not tidiness: it is the mechanism. The host
        services only the current cell's directory, under only the current cell's
        authority, so a shim captured in an earlier cell writes where nobody reads.
        """
        root = getattr(record.handle, "child_rpc_dir", "")
        if broker is None or record.rpc_host is None or not root:
            return None, ""
        name = f"cell-{secrets.token_hex(16)}"
        mailbox = record.rpc_host / name
        try:
            mailbox.mkdir(parents=True, exist_ok=False)
        except OSError:
            logger.warning("session kernel mailbox unavailable", exc_info=True)
            return None, ""
        return mailbox, f"{root}/{name}"

    async def _run_serviced(self, record: _Record, cell: str, mailbox: Path | None,
                            child_mailbox: str, broker, sinks=None) -> dict:
        """Run the cell, answering its tool calls while it runs."""
        store = SessionRPCStore(mailbox, max_tool_calls=self._max_tool_calls) if mailbox else None
        task = asyncio.ensure_future(self._backend.run_cell(
            record.handle, cell, timeout=self._cell_timeout,
            rpc_dir=child_mailbox, max_tool_calls=self._max_tool_calls if store else 0,
            **({"sinks": sinks} if sinks else {})))
        served: set[int] = set()
        active = True
        service = None
        deadline = asyncio.get_running_loop().time() + self._cell_timeout
        try:
            while not task.done():
                if self._stopped():
                    raise KernelRefused(STOPPED)
                if record.quarantined or self._records.get(record.key) is not record:
                    raise KernelRefused(CRASHED)
                if asyncio.get_running_loop().time() >= deadline:
                    raise KernelRefused(TIMED_OUT)
                if service is not None and service.done():
                    await service
                    service = None
                if store is not None and service is None:
                    service = asyncio.create_task(self._service(
                        store, served, broker, active=lambda: active and not record.quarantined))
                await asyncio.sleep(self._poll_interval)
            if record.quarantined or self._records.get(record.key) is not record:
                raise KernelRefused(CRASHED)
            payload = await task
            if isinstance(payload, dict):
                # The calls the host served, not the count the kernel reports: a cell can
                # set its own counter to anything (review-H315g n1). With no mailbox the
                # host served none (review-H315h n2).
                payload = {**payload, "tool_calls": len(served) if store is not None else 0}
            return payload
        finally:
            active = False
            pending = [item for item in (task, service) if item is not None]
            for item in pending:
                if not item.done():
                    item.cancel()
            # A tool that suppresses cancellation cannot hold the kernel hostage.
            # Its eventual response is fenced by active=False before touching I/O.
            if pending:
                done, waiting = await asyncio.wait(pending, timeout=.1)
                for item in done:
                    self._consume_task(item)
                for item in waiting:
                    item.add_done_callback(self._consume_task)
            if store is not None:
                store.close()
            if mailbox is not None:
                with contextlib.suppress(Exception):
                    shutil.rmtree(mailbox)

    @staticmethod
    def _consume_task(task):
        with contextlib.suppress(asyncio.CancelledError, Exception):
            task.result()

    async def _service(self, store: SessionRPCStore, served: set[int], broker,
                       *, active=lambda: True) -> None:
        limit = max(64, self._max_tool_calls * 2)
        for request in store.pending_requests(limit=limit):
            if not active():
                return
            if request.seq in served:
                self._consume(store, request.seq)
                continue
            served.add(request.seq)
            if len(served) > self._max_tool_calls:
                response = {"ok": False, "reason": "tool_call_limit_exceeded",
                            "tool": request.tool}
            else:
                response = await broker.call(request.tool, request.args)
            if not active():
                return
            store.write_response(request.seq, response)
            self._consume(store, request.seq)

    @staticmethod
    def _consume(store: SessionRPCStore, seq: int) -> None:
        store.consume(seq)

    # ── lifecycle ────────────────────────────────────────────────────────────

    async def reset(self, invocation) -> bool:
        """Confirm destruction; on failure retain a quarantined row for retry."""
        return await self._drop(KernelKey.from_invocation(invocation), RESET)

    async def close_session(self, session_id: str) -> int:
        keys = [key for key in list(self._records) if key.session_id == str(session_id)]
        destroyed = 0
        for key in keys:
            destroyed += bool(await self._drop(key, STOPPED))
        return destroyed

    async def shutdown(self, reason: str = STOPPED) -> int:
        keys = list(self._records)
        destroyed = 0
        for key in keys:
            destroyed += bool(await self._drop(key, reason))
        return destroyed

    def status(self) -> list[dict]:
        """Owner projection; quarantined liveness is unknown, never falsely gone."""
        now = self._clock()
        return sorted(
            ({**key.as_dict(), "cells_run": record.cells_run,
              "idle_seconds": round(max(0.0, now - record.last_used), 3),
              "alive": None if record.quarantined else self._backend.alive(record.handle),
              **({"quarantined": True, "reason": TEARDOWN_UNCONFIRMED} if record.quarantined else {}),
              "backend": getattr(self._backend, "name", "unknown")}
             for key, record in self._records.items()),
            key=lambda row: row["token"],
        )

    # ── internals ────────────────────────────────────────────────────────────

    def dispatch_refusal(self, invocation):
        """Current synchronous gate, also checked inside one-shot fallback dispatch."""
        if self._stopped():
            return ESTOP_ENGAGED
        if self._expired(invocation):
            return AUTHORITY_EXPIRED
        record = self._records.get(KernelKey.from_invocation(invocation))
        if record is not None and record.quarantined:
            return TEARDOWN_UNCONFIRMED
        return ""

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
            if record is not None and record.quarantined:
                raise KernelRefused(TEARDOWN_UNCONFIRMED)
            if record is not None and hasattr(self._backend, "probe"):
                await self._backend.probe(record.handle)
            if record is not None and self._backend.alive(record.handle):
                if lost:
                    record.pending_loss = lost
                return record
            if record is not None:
                lost = lost or CRASHED
                if not await self._drop(key, lost):
                    raise KernelRefused(TEARDOWN_UNCONFIRMED)
            while len(self._records) >= self._max_kernels:
                await self._evict()
            mount = self._mount(key)
            try:
                handle = await self._backend.start(key, **mount)
            except KernelTeardownUnconfirmed as refusal:
                now = self._clock()
                # The quarantined row owns the directory, so its teardown removes it
                # (review-H315e n3).
                self._records[key] = _Record(key=key, handle=refusal.handle,
                    created_at=now, last_used=now, quarantined=True,
                    rpc_host=Path(mount["rpc_dir"]) if mount else None)
                if refusal.cancelled:
                    raise asyncio.CancelledError from None
                raise
            except KernelRefused as refusal:
                self._unmount(mount)
                if refusal.reason == KERNEL_UNAVAILABLE:
                    raise KernelStartupUnavailable(KERNEL_UNAVAILABLE) from None
                raise
            except BaseException:
                self._unmount(mount)       # any other failed start leaves nothing behind
                raise
            now = self._clock()
            record = _Record(key=key, handle=handle, created_at=now, last_used=now,
                             pending_loss=lost or self._expiries.pop(key, "") or NEW_KERNEL,
                             rpc_host=Path(mount["rpc_dir"]) if mount else None)
            self._records[key] = record
            return record

    def _mount(self, key: KernelKey) -> dict:
        """The one shared directory a kernel gets, created before it starts: new for
        every interpreter, never one an earlier interpreter of the same key wrote in."""
        if self._rpc_root is None:
            return {}
        if _fcntl is not None:
            owner_dir = self._rpc_root / self._owner
            state = _lock_state(owner_dir, self._owner_fd)
            if state == LOCK_LOST:
                # The old fd locks a file no longer at the path, so it holds nothing up
                # and is closed. Hold the directory's lock again where its mounts live;
                # when that cannot be had, take a new directory, and with no lock at all,
                # give no mount (review-H315g m1, review-H315h m1).
                if self._owner_fd is not None:
                    with contextlib.suppress(OSError):   # an fd already gone (review-H315j m2)
                        os.close(self._owner_fd)
                self._owner_fd = _relock_in_place(owner_dir)
                if self._owner_fd is None:
                    self._owner = f"p{os.getpid()}-{secrets.token_hex(4)}"
                    self._owner_fd = _hold_owner_lock(self._rpc_root / self._owner)
                if self._owner_fd is None:
                    return {}
        host = self._rpc_root / self._owner / f"{key.token}-{secrets.token_hex(8)}"
        try:
            host.mkdir(parents=True, exist_ok=False)
        except OSError:
            logger.warning("session kernel rpc root unavailable", exc_info=True)
            return {}
        return {"rpc_dir": str(host), "child_rpc_dir": self._backend.child_rpc_dir(str(host))}

    @staticmethod
    def _unmount(mount) -> None:
        """Remove an interpreter's directory, with whatever its cells left in it."""
        host = (mount or {}).get("rpc_dir") if isinstance(mount, dict) else mount
        if host:
            shutil.rmtree(host, ignore_errors=True)

    def _clear_stale_mounts(self) -> None:
        """Remove what the interpreters of a process that is gone left under the root.

        Two processes can share one data root (the documented jarvis-hub and
        jarvis-runtime units do), so a start may not sweep the whole root: that deleted the
        other's live mounts (review-H315e m1). Each manager keeps its interpreters under a
        directory of its own (``p<pid>-<token>``) and holds that directory's lock while its
        process runs; a start removes an owner directory whose lock it can take, which is a
        process that has ended, in any pid namespace sharing the root. A pid is not asked:
        in a container the hub is PID 1 on every start (review-H315f m1). A directory with
        no lock (the older layouts, or no flock) is removed once it is older than the idle
        expiry, which no live interpreter's is; an owner directory's age is its newest
        interpreter's."""
        if self._rpc_root is None or not self._rpc_root.is_dir():
            return
        try:
            entries = list(self._rpc_root.iterdir())
        except OSError:
            logger.warning("session kernel rpc root could not be listed", exc_info=True)
            return
        for entry in entries:
            try:
                self._clear_one(entry)
            except OSError:
                # One unreadable entry (another user's) never stops the sweep, let alone
                # the start (review-H315i m3): it is left.
                logger.debug("session kernel mount %s left", entry.name, exc_info=True)

    def _clear_one(self, entry: Path) -> None:
        """Remove one entry under the root if its process is gone (see _clear_stale_mounts)."""
        if not entry.is_dir() or entry.is_symlink() or entry.name == self._owner:
            return
        alive = _owner_alive(entry) if _OWNER_DIR.fullmatch(entry.name) else None
        if alive:
            return
        if alive is None:
            try:
                newest = entry.stat().st_mtime
                if _OWNER_DIR.fullmatch(entry.name):
                    # An owner directory's own time moves only when an interpreter's
                    # directory is made or removed in it; a busy interpreter moves its
                    # own directory's (review-H315g m1).
                    newest = max([newest, *(child.stat().st_mtime for child in entry.iterdir()
                                            if child.is_dir() and not child.is_symlink())])
                age = time.time() - newest
            except OSError:
                return
            if age < self._idle_ttl:
                return
        shutil.rmtree(entry, ignore_errors=True)

    async def _reap(self) -> None:
        cutoff = self._clock() - self._idle_ttl
        for key, record in list(self._records.items()):
            if record.last_used < cutoff and not record.lock.locked() and not record.quarantined:
                await self._drop(key, EXPIRED)

    async def _evict(self) -> None:
        idle = [(record.last_used, key) for key, record in self._records.items()
                if not record.lock.locked() and not record.quarantined]
        if not idle:
            # Every kernel is mid-cell. Refusing is better than killing a running
            # cell to make room for a new one.
            raise KernelRefused(KERNEL_UNAVAILABLE)
        _, key = min(idle)
        if not await self._drop(key, EVICTED):
            raise KernelRefused(TEARDOWN_UNCONFIRMED)

    async def _drop(self, key: KernelKey, reason: str, *, expected=None) -> bool:
        record = self._records.get(key)
        if expected is not None and record is not expected:
            return False
        if record is None:
            self._remember(key, reason)
            return False
        record.quarantined = True
        async with record.teardown_lock:
            if self._records.get(key) is not record:
                return True
            try:
                await self._backend.stop(record.handle)
            except Exception:
                logger.warning("session kernel teardown unconfirmed")
                return False
            self._records.pop(key, None)
            self._unmount(record.rpc_host)    # stopped: nothing writes there any more
            self._remember(key, reason)
            return True

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
