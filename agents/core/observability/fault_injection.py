"""
fault_injection.py — T-0.63 failure-injection harness (the AI-buildable half of Burn-In).

Chapter 13 of the test manual asks the operator to *kill LM Studio mid-stream*,
*fill the data volume*, *corrupt a store* and *jump the clock* by hand
(CHA-001…015, CHA-041…047). Those beats stay manual for the soak, but the code
paths they exercise — the degraded-reply mapping in ``llm/base.py``, the
``sqlite3.DatabaseError`` a store must surface honestly, the ENOSPC a write must
refuse without taking the process down, the day-window arithmetic that a clock
rollback must not reset — can be driven from a test without hardware. This
module is that driver: an in-process, reversible, auditable fault injector for
the test lane.

Rules (MOONSHOT §5 production-grade + local-first):

- **Default off, refused when hardened.** ``inject`` raises
  :class:`FaultInjectionRefused` unless ``JARVIS_FAULT_INJECT`` is on, and
  refuses unconditionally under ``JARVIS_HARDENED`` (:func:`boot_problem` gives
  the boot guard a fail-closed sentence for the armed-and-hardened combination).
  The env is read at call time, never cached (AUD-14).
- **Reversible.** Every fault is a context manager that restores what it patched
  in ``finally`` — even when the body raises — and a fault also *expires* on its
  own after ``duration_s`` so a forgotten handle cannot wedge a long test.
- **Bounded blast radius.** ``db_corrupt`` and ``disk_full`` only ever touch
  paths under :func:`agents.core.paths.data_root` (tests redirect that to a
  ``tmp_path`` through ``JARVIS_HOME``); a target outside it is refused by
  name. The harness never spawns a subprocess, never opens a socket, never
  writes outside the data root and never touches the audit chain.
- **Auditable.** Each interception is recorded on the handle
  (:attr:`FaultHandle.events`), the module logger names every arm/disarm with
  the plan's SHA-256 fingerprint, and :func:`active_faults` exposes the live set.
- **Honest scope.** Each fault is documented with what it does *and does not*
  intercept (module-level ``FAULT_SCOPE``) so a passing chaos test is never
  mistaken for a soak result. The manual's CHA-013 stays ⚠️ (simulated), not ✅.

Faults:

``llm_down``
    ``httpx.AsyncClient.send`` / ``httpx.Client.send`` raise
    ``httpx.ConnectError`` for requests whose host contains ``plan.target``
    (``"*"`` = every host). Sits *above* the transport, so it also preempts a
    ``MockTransport`` — the same code path a dead LM Studio / Ollama exercises.
``db_corrupt``
    Overwrites the SQLite header of the file at ``plan.target`` (relative to the
    data root, or absolute *inside* it) after copying the bytes aside; restores
    them on exit. A fresh connection then fails with ``sqlite3.DatabaseError``
    (``file is not a database``). Any ``-wal`` sidecar gets the same treatment so
    the WAL cannot mask the corrupt page 1. Aim it at a store with **no live
    connection** in this process — an open connection keeps its page cache.
``disk_full``
    ``open()`` (``builtins`` and ``io``) in a write/append/create mode on a path
    under the scope (``plan.target`` dir, ``"*"`` = data root) raises
    ``OSError(ENOSPC)``; ``sqlite3.connect`` on a file under the scope returns a
    connection whose write statements and ``commit`` raise
    ``sqlite3.OperationalError('database or disk is full')`` while reads pass.
    Connections and file objects opened *before* the fault are not affected.
``clock_skew``
    ``time.time`` / ``time.time_ns`` are offset by ``plan.skew_s``. Code that
    bound ``time.time`` at import (``from time import time``, a default argument)
    keeps the real clock; pass :meth:`FaultHandle.clock` where a component
    accepts an injectable clock (``AttentionLedger(clock=...)``).
"""

from __future__ import annotations

import builtins
import contextlib
import errno
import hashlib
import io
import json
import logging
import math
import os
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx

from agents.core.env_config import env_flag
from agents.core.paths import data_root

logger = logging.getLogger("jarvis.observability.fault_injection")

FLAG = "JARVIS_FAULT_INJECT"
HARDENED_FLAG = "JARVIS_HARDENED"

FAULT_KINDS = ("llm_down", "db_corrupt", "disk_full", "clock_skew")
MAX_DURATION_S = 3600.0
MAX_SKEW_S = 10 * 366 * 86400.0
MAX_EVENTS = 200

REASON_DISABLED = "fault_injection_disabled"
REASON_HARDENED = "fault_injection_refused:hardened"
REASON_ALREADY_ACTIVE = "fault_already_active"
REASON_OUTSIDE_ROOT = "fault_target_outside_data_root"
REASON_TARGET_MISSING = "fault_target_missing"

BOOT_PROBLEM = (
    "JARVIS_FAULT_INJECT=1 cannot be combined with JARVIS_HARDENED=1: the "
    "failure-injection harness is a test-lane tool and must never be armed on a "
    "hardened box. Unset JARVIS_FAULT_INJECT or unset JARVIS_HARDENED."
)

FAULT_SCOPE: dict[str, dict[str, tuple[str, ...]]] = {
    "llm_down": {
        "intercepts": ("httpx.AsyncClient.send", "httpx.Client.send"),
        "not_intercepted": ("raw sockets", "aiohttp", "urllib", "subprocess"),
    },
    "db_corrupt": {
        "intercepts": ("SQLite file header on disk", "-wal sidecar header"),
        "not_intercepted": ("connections already open on the target",),
    },
    "disk_full": {
        "intercepts": ("builtins.open / io.open write modes under scope",
                       "sqlite3.connect under scope: write statements + commit"),
        "not_intercepted": ("os.open / os.write / tempfile", "file objects opened before the fault",
                            "connections opened before the fault", "from sqlite3 import connect"),
    },
    "clock_skew": {
        "intercepts": ("time.time", "time.time_ns", "FaultHandle.clock"),
        "not_intercepted": ("datetime.now", "time.monotonic", "names bound at import time"),
    },
}

# The originals, captured at import so the harness's own bookkeeping I/O and its
# expiry clock are immune to the faults it installs (a db_corrupt restore inside a
# disk_full window must still write; expiry must not follow a skewed clock).
_REAL_OPEN = builtins.open
_REAL_MONOTONIC = time.monotonic
_WRITE_MODE_CHARS = frozenset("wax+")
_WRITE_VERBS = frozenset({
    "INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER", "VACUUM", "REINDEX",
})
_SQLITE_MAGIC = b"SQLite format 3\x00"
_CORRUPT_HEADER = (b"NERVA-FAULT-INJECT:db_corrupt " * 4)[:100]
_BACKUP_SUFFIX = ".fault-backup"


def _monotonic() -> float:
    """Expiry clock — indirected so tests can fast-forward it without sleeping."""
    return _REAL_MONOTONIC()


class FaultInjectionRefused(RuntimeError):
    """The harness refused to arm; ``reason`` is a stable, grep-able token."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        super().__init__(reason if not detail else f"{reason}: {detail}")


# ── posture ───────────────────────────────────────────────────────────────────

def is_armed() -> bool:
    """``JARVIS_FAULT_INJECT`` is on (read at call time)."""
    return env_flag(FLAG)


def refusal_reason() -> str | None:
    """Why :func:`inject` would refuse right now, or ``None`` when it may arm.

    Hardened wins over armed: a hardened box never injects, whatever the flag says.
    """
    if env_flag(HARDENED_FLAG):
        return REASON_HARDENED
    if not env_flag(FLAG):
        return REASON_DISABLED
    return None


def is_enabled() -> bool:
    return refusal_reason() is None


def boot_problem() -> str | None:
    """Fail-closed sentence for the boot guard when the harness is armed on a
    hardened box; ``None`` otherwise. Meant to be appended to the problems list
    ``boot_guards.assert_hardened_posture`` refuses on."""
    if env_flag(FLAG) and env_flag(HARDENED_FLAG):
        return BOOT_PROBLEM
    return None


# ── plan ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FaultPlan:
    """One fault to inject. Immutable, validated, fingerprinted.

    ``target`` — ``llm_down``: host substring (``"*"`` = all); ``db_corrupt``: the
    SQLite file (required; relative to the data root or absolute inside it);
    ``disk_full``: scope directory (``"*"`` = the data root); ``clock_skew``: unused.
    ``skew_s`` — ``clock_skew`` only; seconds added to ``time.time`` (negative = rollback).
    """

    kind: str
    duration_s: float = 30.0
    target: str = "*"
    skew_s: float = 0.0
    note: str = ""

    def __post_init__(self):
        if self.kind not in FAULT_KINDS:
            raise ValueError(f"unknown fault kind {self.kind!r}; expected one of {FAULT_KINDS}")
        if isinstance(self.duration_s, bool) or not isinstance(self.duration_s, (int, float)):
            raise ValueError("duration_s must be a number of seconds")
        if not math.isfinite(self.duration_s) or self.duration_s <= 0 or self.duration_s > MAX_DURATION_S:
            raise ValueError(f"duration_s must be in (0, {MAX_DURATION_S:g}] seconds")
        if not isinstance(self.target, str) or not self.target.strip():
            raise ValueError("target must be a non-empty string ('*' for the default scope)")
        if isinstance(self.skew_s, bool) or not isinstance(self.skew_s, (int, float)) or not math.isfinite(self.skew_s):
            raise ValueError("skew_s must be a finite number of seconds")
        if self.kind == "clock_skew":
            if self.skew_s == 0:
                raise ValueError("clock_skew needs a non-zero skew_s")
            if abs(self.skew_s) > MAX_SKEW_S:
                raise ValueError("clock_skew skew_s exceeds the ten-year bound")
        elif self.skew_s != 0:
            raise ValueError(f"skew_s is only meaningful for clock_skew, not {self.kind}")
        if self.kind == "db_corrupt" and self.target == "*":
            raise ValueError("db_corrupt needs an explicit target store path")
        if not isinstance(self.note, str) or len(self.note) > 200:
            raise ValueError("note must be a string of at most 200 characters")

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "duration_s": float(self.duration_s),
            "target": self.target,
            "skew_s": float(self.skew_s),
            "note": self.note,
        }

    def fingerprint(self) -> str:
        canonical = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── handle ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FaultEvent:
    at_monotonic: float
    detail: str


@dataclass
class FaultHandle:
    """Live view of one injected fault. ``active`` flips off at expiry or release."""

    plan: FaultPlan
    started_monotonic: float = field(default_factory=lambda: _monotonic())
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    events: list[FaultEvent] = field(default_factory=list)
    dropped_events: int = 0
    released: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def elapsed_s(self) -> float:
        return _monotonic() - self.started_monotonic

    @property
    def remaining_s(self) -> float:
        return max(0.0, self.plan.duration_s - self.elapsed_s)

    @property
    def active(self) -> bool:
        return not self.released and self.elapsed_s < self.plan.duration_s

    @property
    def expired(self) -> bool:
        return not self.released and not self.active

    def record(self, detail: str) -> None:
        with self._lock:
            if len(self.events) >= MAX_EVENTS:
                self.dropped_events += 1
                return
            self.events.append(FaultEvent(at_monotonic=_monotonic(), detail=detail))

    def release(self) -> None:
        self.released = True

    def clock(self) -> float:
        """Wall clock as the process sees it under the fault (skewed for clock_skew)."""
        return time.time()

    def snapshot(self) -> dict:
        with self._lock:
            events = [e.detail for e in self.events[-20:]]
            count = len(self.events)
        return {
            "kind": self.plan.kind,
            "fingerprint": self.plan.fingerprint(),
            "plan": self.plan.to_dict(),
            "started_at": self.started_at,
            "active": self.active,
            "released": self.released,
            "remaining_s": round(self.remaining_s, 3),
            "event_count": count,
            "dropped_events": self.dropped_events,
            "last_events": events,
        }


_REGISTRY: dict[str, FaultHandle] = {}
_REGISTRY_LOCK = threading.Lock()


def active_faults() -> list[dict]:
    """Snapshots of every armed fault (expired-but-unreleased ones included, flagged)."""
    with _REGISTRY_LOCK:
        handles = list(_REGISTRY.values())
    return [h.snapshot() for h in handles]


# ── path guards ───────────────────────────────────────────────────────────────

def _data_root_resolved() -> Path:
    return data_root().expanduser().resolve()


def _resolve_under_root(target: str) -> Path:
    """Absolute path for *target*, refused unless it lives under the data root."""
    root = _data_root_resolved()
    raw = Path(target).expanduser()
    path = (raw if raw.is_absolute() else root / raw).resolve()
    if path != root and not path.is_relative_to(root):
        raise FaultInjectionRefused(REASON_OUTSIDE_ROOT, str(raw))
    return path


def _path_in_scope(file: object, scope: Path) -> bool:
    if isinstance(file, int):
        return False
    try:
        raw = Path(os.fsdecode(os.fspath(file))).expanduser()
    except (TypeError, ValueError):
        return False
    try:
        path = raw.resolve() if raw.is_absolute() else (Path.cwd() / raw).resolve()
    except (OSError, RuntimeError):
        return False
    return path == scope or path.is_relative_to(scope)


def _read_bytes(path: Path) -> bytes:
    with _REAL_OPEN(path, "rb") as fh:
        return fh.read()


def _write_bytes(path: Path, data: bytes) -> None:
    with _REAL_OPEN(path, "wb") as fh:
        fh.write(data)


def _overwrite_head(path: Path, head: bytes) -> None:
    with _REAL_OPEN(path, "r+b") as fh:
        fh.seek(0)
        fh.write(head)


# ── appliers (each returns its restore callable) ──────────────────────────────

def _apply_llm_down(handle: FaultHandle) -> Callable[[], None]:
    target = handle.plan.target
    orig_async = httpx.AsyncClient.send
    orig_sync = httpx.Client.send

    def _matches(request: httpx.Request) -> bool:
        host = request.url.host or ""
        return target == "*" or target in host

    def _refuse(request: httpx.Request) -> None:
        handle.record(f"llm_down:{request.method} {request.url.host}")
        raise httpx.ConnectError("fault_injection:llm_down", request=request)

    async def fake_async_send(self, request, *args, **kwargs):
        if handle.active and _matches(request):
            _refuse(request)
        return await orig_async(self, request, *args, **kwargs)

    def fake_sync_send(self, request, *args, **kwargs):
        if handle.active and _matches(request):
            _refuse(request)
        return orig_sync(self, request, *args, **kwargs)

    httpx.AsyncClient.send = fake_async_send
    httpx.Client.send = fake_sync_send

    def restore() -> None:
        httpx.AsyncClient.send = orig_async
        httpx.Client.send = orig_sync

    return restore


def _apply_db_corrupt(handle: FaultHandle) -> Callable[[], None]:
    path = _resolve_under_root(handle.plan.target)
    if not path.is_file():
        raise FaultInjectionRefused(REASON_TARGET_MISSING, handle.plan.target)
    originals: dict[Path, bytes] = {path: _read_bytes(path)}
    wal = path.with_name(path.name + "-wal")
    if wal.is_file():
        originals[wal] = _read_bytes(wal)
    # Keep an on-disk copy too, so a crash between arm and restore is recoverable by hand.
    for p, data in originals.items():
        _write_bytes(p.with_name(p.name + _BACKUP_SUFFIX), data)
    for p in originals:
        _overwrite_head(p, _CORRUPT_HEADER)
    handle.record(f"db_corrupt:{path.name}" + (" +wal" if wal in originals else ""))

    def restore() -> None:
        for p, data in originals.items():
            _write_bytes(p, data)
            backup = p.with_name(p.name + _BACKUP_SUFFIX)
            with contextlib.suppress(OSError):
                backup.unlink()

    return restore


def _is_write_sql(sql: object) -> bool:
    if not isinstance(sql, str):
        return False
    for statement in sql.split(";"):
        words = statement.strip().upper().split(None, 2)
        if not words:
            continue
        verb = words[0]
        if verb in _WRITE_VERBS:
            return True
        if verb == "WITH" and any(v in statement.upper() for v in ("INSERT", "UPDATE", "DELETE")):
            return True
    return False


def _apply_disk_full(handle: FaultHandle) -> Callable[[], None]:
    scope = _data_root_resolved() if handle.plan.target == "*" else _resolve_under_root(handle.plan.target)
    orig_open = builtins.open
    orig_io_open = io.open
    orig_connect = sqlite3.connect

    def _enospc(what: str, path: object) -> None:
        handle.record(f"disk_full:{what}:{Path(os.fsdecode(os.fspath(path))).name}")
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC), os.fsdecode(os.fspath(path)))

    def fake_open(file, mode="r", *args, **kwargs):
        if (handle.active and isinstance(mode, str) and _WRITE_MODE_CHARS.intersection(mode)
                and _path_in_scope(file, scope)):
            _enospc("open", file)
        return orig_open(file, mode, *args, **kwargs)

    def _guard(sql: object) -> None:
        if handle.active and _is_write_sql(sql):
            handle.record("disk_full:sqlite")
            raise sqlite3.OperationalError("database or disk is full")

    class DiskFullCursor(sqlite3.Cursor):
        def execute(self, sql, *args):
            _guard(sql)
            return super().execute(sql, *args)

        def executemany(self, sql, *args):
            _guard(sql)
            return super().executemany(sql, *args)

        def executescript(self, sql):
            _guard(sql)
            return super().executescript(sql)

    class DiskFullConnection(sqlite3.Connection):
        def cursor(self, factory=DiskFullCursor):
            return super().cursor(factory)

        def execute(self, sql, *args):
            _guard(sql)
            return super().execute(sql, *args)

        def executemany(self, sql, *args):
            _guard(sql)
            return super().executemany(sql, *args)

        def executescript(self, sql):
            _guard(sql)
            return super().executescript(sql)

        def commit(self):
            if handle.active and self.in_transaction:
                handle.record("disk_full:sqlite-commit")
                raise sqlite3.OperationalError("database or disk is full")
            return super().commit()

    def fake_connect(database, *args, **kwargs):
        if (handle.active and "factory" not in kwargs and not isinstance(database, int)
                and os.fsdecode(os.fspath(database)) != ":memory:"
                and not os.fsdecode(os.fspath(database)).startswith("file:")
                and _path_in_scope(database, scope)):
            kwargs["factory"] = DiskFullConnection
        return orig_connect(database, *args, **kwargs)

    builtins.open = fake_open
    io.open = fake_open
    sqlite3.connect = fake_connect

    def restore() -> None:
        builtins.open = orig_open
        io.open = orig_io_open
        sqlite3.connect = orig_connect

    return restore


def _apply_clock_skew(handle: FaultHandle) -> Callable[[], None]:
    skew = float(handle.plan.skew_s)
    skew_ns = int(skew * 1_000_000_000)
    orig_time = time.time
    orig_time_ns = time.time_ns

    def fake_time() -> float:
        return orig_time() + (skew if handle.active else 0.0)

    def fake_time_ns() -> int:
        return orig_time_ns() + (skew_ns if handle.active else 0)

    time.time = fake_time
    time.time_ns = fake_time_ns
    handle.record(f"clock_skew:{skew:+g}s")

    def restore() -> None:
        time.time = orig_time
        time.time_ns = orig_time_ns

    return restore


_APPLIERS: dict[str, Callable[[FaultHandle], Callable[[], None]]] = {
    "llm_down": _apply_llm_down,
    "db_corrupt": _apply_db_corrupt,
    "disk_full": _apply_disk_full,
    "clock_skew": _apply_clock_skew,
}


# ── entry point ───────────────────────────────────────────────────────────────

@contextlib.contextmanager
def inject(plan: FaultPlan) -> Iterator[FaultHandle]:
    """Arm *plan* for the duration of the ``with`` block (or ``plan.duration_s``,
    whichever ends first) and restore everything on exit.

    Raises :class:`FaultInjectionRefused` (``reason`` is one of the ``REASON_*``
    tokens) when the flag is off, the box is hardened, the same kind is already
    armed, or a path target is missing / outside the data root. Never partially
    arms: a refused plan leaves no patch behind.
    """
    if not isinstance(plan, FaultPlan):
        raise TypeError("inject() takes a FaultPlan")
    reason = refusal_reason()
    if reason is not None:
        raise FaultInjectionRefused(reason)
    handle = FaultHandle(plan)
    with _REGISTRY_LOCK:
        if plan.kind in _REGISTRY:
            raise FaultInjectionRefused(REASON_ALREADY_ACTIVE, plan.kind)
        _REGISTRY[plan.kind] = handle
    try:
        restore = _APPLIERS[plan.kind](handle)
    except BaseException:
        with _REGISTRY_LOCK:
            _REGISTRY.pop(plan.kind, None)
        raise
    logger.info("fault armed kind=%s fingerprint=%s duration_s=%g",
                plan.kind, plan.fingerprint()[:16], plan.duration_s)
    try:
        yield handle
    finally:
        handle.release()
        try:
            restore()
        finally:
            with _REGISTRY_LOCK:
                if _REGISTRY.get(plan.kind) is handle:
                    del _REGISTRY[plan.kind]
            logger.info("fault disarmed kind=%s fingerprint=%s events=%d",
                        plan.kind, plan.fingerprint()[:16], len(handle.events))


__all__ = [
    "FLAG",
    "FAULT_KINDS",
    "FAULT_SCOPE",
    "BOOT_PROBLEM",
    "REASON_DISABLED",
    "REASON_HARDENED",
    "REASON_ALREADY_ACTIVE",
    "REASON_OUTSIDE_ROOT",
    "REASON_TARGET_MISSING",
    "FaultInjectionRefused",
    "FaultPlan",
    "FaultEvent",
    "FaultHandle",
    "active_faults",
    "boot_problem",
    "inject",
    "is_armed",
    "is_enabled",
    "refusal_reason",
]
