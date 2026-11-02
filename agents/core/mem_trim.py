"""H448 — return freed heap pages to the OS (Hermes ``context.memory_trim``).

A long-lived hub frees a lot after a turn (prompts, model replies, tool results, a
compacted history), but glibc keeps the freed pages mapped, so the process's resident
size only ratchets up. ``malloc_trim(0)`` hands the free pages at the top of each arena
back to the kernel. This is process RAM, not the memory store: the setting lives under
``context.`` (as in Hermes) so it is not mistaken for a ``memory.*`` setting.

- **Where it runs.** Two triggers share one rate limit, as Hermes' turn-completion and
  gateway-housekeeping trims do. :func:`after_turn` is called from the end of every turn
  entry point (``Orchestrator.handle_input``, ``handle_input_stream`` and
  ``process_detailed``) — on a reply, an error and a cancel alike. :func:`housekeeping`
  is the hub scheduler's ``memory-trim`` job, every minute
  (``SchedulerService.run_memory_trim_tick``): it trims an idle hub, the turn that ended
  inside the cooldown (a compaction that freed a large history is not left resident
  overnight) and what non-turn work freed (the lifecycle sweep, ingestion, scheduled
  jobs). Both decide on the event loop (a dictionary lookup and a clock read) and, when
  a trim is due, run the call on the loop's default executor, so neither a reply nor
  other requests wait for the allocator.
- **Rate limit.** At most one trim every ``cooldown_seconds`` (60 by default; 0 = after
  every turn), and never two at once: a trigger that fires while one runs skips. The
  cooldown is stamped when a trim is claimed, so a trim that fails waits it out too.
- **One-time probe.** The first due attempt checks, once per process: a Linux host
  (``sys.platform``), glibc (``os.confstr("CS_GNU_LIBC_VERSION")``, which musl does not
  answer), no other allocator preloaded (jemalloc, tcmalloc, mimalloc… in
  ``LD_PRELOAD`` — glibc's arenas are not the heap there), and the ``malloc_trim``
  symbol in the process's own libc through ``ctypes``. Any other answer — macOS,
  Windows, musl, a preloaded allocator, a missing symbol, a probe that raised — makes
  every later attempt a no-op that touches nothing; :data:`probe_reason` says which.
- **Settings without a copy.** Hermes reads its config through the *no-deepcopy* loader
  because this runs on every attempt, before the cooldown check, and a full-config copy
  per attempt is exactly the garbage the trim exists to release. Here the turn's
  orchestrator answers ``get_setting("context.memory_trim")`` — one lookup in the
  runtime settings snapshot the settings watcher refreshes every 30 s, returning the
  stored object itself; its fields are read in place. No settings store read, no
  ``get_all``, no copy. Every read fails open: a missing, malformed or unreadable value
  is the shipped default (``enabled`` true), field by field, so a broken setting never
  breaks a turn.
- **Logging.** As in Hermes, a trim that released pages (``malloc_trim`` returned 1)
  logs at INFO when it is the ``log_every_n``-th completed trim and the resident size
  moved, either way, by at least ``info_log_min_delta_mb`` (or could not be read); with
  the defaults (1 and 0.0) that is every trim that released pages. Every other trim —
  nothing released, a skipped count, a smaller change — logs the same line at DEBUG.

Governance: read-only. The call changes nothing outside this process's own heap — no
file, no host state, nothing a user or operator can see but a smaller RSS — so it does
not cross the Action Kernel; the owner switches it off with
``context.memory_trim.enabled`` (the HUD's settings, or ``nerva config set``).
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
import sys
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any, NamedTuple

logger = logging.getLogger("jarvis.mem_trim")

#: The runtime settings key (``category.key``); the value is an object with the four fields.
SETTING = "context.memory_trim"

_DEFAULT_ENABLED = True
_DEFAULT_COOLDOWN_SECONDS = 60.0
_DEFAULT_LOG_EVERY_N = 1
_DEFAULT_INFO_LOG_MIN_DELTA_MB = 0.0

#: The shipped value of ``context.memory_trim`` (``settings_db.DEFAULTS`` declares it).
DEFAULT_SETTINGS: dict[str, Any] = {
    "enabled": _DEFAULT_ENABLED,
    "cooldown_seconds": _DEFAULT_COOLDOWN_SECONDS,
    "log_every_n": _DEFAULT_LOG_EVERY_N,
    "info_log_min_delta_mb": _DEFAULT_INFO_LOG_MIN_DELTA_MB,
}

#: Field bounds, enforced on a write (:func:`settings_problem`) and on a read.
MAX_COOLDOWN_SECONDS = 86_400.0
MAX_LOG_EVERY_N = 1_000_000
MAX_INFO_LOG_MIN_DELTA_MB = 1_048_576.0

#: Allocators that replace glibc's malloc when preloaded; malloc_trim would trim nothing.
_FOREIGN_ALLOCATORS = ("jemalloc", "tcmalloc", "mimalloc", "hoard", "snmalloc", "rpmalloc", "scudo")


class TrimSettings(NamedTuple):
    enabled: bool
    cooldown_seconds: float
    log_every_n: int
    info_log_min_delta_mb: float


_DEFAULTS = TrimSettings(_DEFAULT_ENABLED, _DEFAULT_COOLDOWN_SECONDS,
                         _DEFAULT_LOG_EVERY_N, _DEFAULT_INFO_LOG_MIN_DELTA_MB)

# Process state, all guarded by _trim_lock (held only for these few reads and writes,
# never across the allocator call, so the event loop never waits on a running trim).
_trim_lock = threading.Lock()
_last_trim_monotonic: float | None = None
_trim_running = False
_trim_call_count = 0
_probe_done = False
_trim_fn: Callable[[int], int] | None = None
probe_reason = "not probed"


def _number(value: Any, default: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    value = float(value)
    return value if math.isfinite(value) and 0.0 <= value <= high else default


def read_settings(get_setting: Callable[..., Any] | None) -> TrimSettings:
    """``context.memory_trim`` as the trim uses it, read in place and failing open.

    *get_setting* is the orchestrator's runtime-snapshot lookup; it is asked for the one
    key, and the object it returns is read field by field without being copied. A reader
    that raises, a value that is not an object, or a field out of its bounds is the
    shipped default for that field.
    """
    if get_setting is None:
        return _DEFAULTS
    try:
        raw = get_setting(SETTING, None)
        if not isinstance(raw, Mapping):
            return _DEFAULTS
        enabled = raw.get("enabled", _DEFAULT_ENABLED)
        every = raw.get("log_every_n", _DEFAULT_LOG_EVERY_N)
        return TrimSettings(
            enabled if type(enabled) is bool else _DEFAULT_ENABLED,
            _number(raw.get("cooldown_seconds", _DEFAULT_COOLDOWN_SECONDS),
                    _DEFAULT_COOLDOWN_SECONDS, MAX_COOLDOWN_SECONDS),
            every if type(every) is int and 1 <= every <= MAX_LOG_EVERY_N else _DEFAULT_LOG_EVERY_N,
            _number(raw.get("info_log_min_delta_mb", _DEFAULT_INFO_LOG_MIN_DELTA_MB),
                    _DEFAULT_INFO_LOG_MIN_DELTA_MB, MAX_INFO_LOG_MIN_DELTA_MB),
        )
    except Exception:  # a broken setting must never break a turn (Hermes: fail open)
        return _DEFAULTS


def settings_problem(value: Any) -> str | None:
    """Why *value* cannot be stored as ``context.memory_trim`` (None = it can).

    Fields may be left out (each then reads as its default); an unknown field, a wrong
    type or an out-of-range number is refused, so a typo is never silently ignored.
    """
    if not isinstance(value, dict):
        return ("memory_trim: expected an object with enabled, cooldown_seconds, "
                "log_every_n and info_log_min_delta_mb")
    unknown = sorted(str(key) for key in value if key not in DEFAULT_SETTINGS)
    if unknown:
        return f"memory_trim: unknown field(s) {', '.join(unknown)}"
    if "enabled" in value and type(value["enabled"]) is not bool:
        return "memory_trim.enabled: expected true or false"
    for field, high in (("cooldown_seconds", MAX_COOLDOWN_SECONDS),
                        ("info_log_min_delta_mb", MAX_INFO_LOG_MIN_DELTA_MB)):
        if field in value and _number(value[field], -1.0, high) < 0:
            return f"memory_trim.{field}: expected a number between 0 and {high:g}"
    every = value.get("log_every_n", _DEFAULT_LOG_EVERY_N)
    if type(every) is not int or not 1 <= every <= MAX_LOG_EVERY_N:
        return f"memory_trim.log_every_n: expected a whole number between 1 and {MAX_LOG_EVERY_N}"
    return None


def _libc() -> Any:
    """The C library this process links (the main program's symbol namespace)."""
    import ctypes

    return ctypes.CDLL(None)


def _probe_locked() -> Callable[[int], int] | None:
    """``malloc_trim`` when this process can use it, else None; decided once per process."""
    global _probe_done, _trim_fn, probe_reason
    if _probe_done:
        return _trim_fn
    _probe_done = True
    try:
        if not sys.platform.startswith("linux"):
            probe_reason = f"unsupported platform {sys.platform}"
        else:
            try:
                libc = os.confstr("CS_GNU_LIBC_VERSION") or ""
            except (ValueError, OSError):
                libc = ""
            preload = os.environ.get("LD_PRELOAD", "").lower()
            foreign = next((name for name in _FOREIGN_ALLOCATORS if name in preload), None)
            if not libc.startswith("glibc"):
                probe_reason = "not glibc (musl or another C library)"
            elif foreign:
                probe_reason = f"{foreign} is preloaded; glibc's heap is not the allocator"
            else:
                import ctypes

                fn = getattr(_libc(), "malloc_trim", None)
                if fn is None:
                    probe_reason = f"{libc} has no malloc_trim"
                else:
                    fn.argtypes = [ctypes.c_size_t]
                    fn.restype = ctypes.c_int
                    _trim_fn = fn
                    probe_reason = f"{libc} malloc_trim"
    except Exception as exc:  # never let the probe break a turn
        _trim_fn = None
        probe_reason = f"probe failed: {type(exc).__name__}"
    logger.info("heap trim: %s", "enabled, " + probe_reason if _trim_fn else "off — " + probe_reason)
    return _trim_fn


def _claim(settings: TrimSettings) -> Callable[[int], int] | None:
    """Take the next trim when one is due and the host supports it; the call to make."""
    global _last_trim_monotonic, _trim_running
    if not settings.enabled:
        return None
    with _trim_lock:
        now = time.monotonic()
        if _trim_running or (_last_trim_monotonic is not None
                             and now - _last_trim_monotonic < settings.cooldown_seconds):
            return None
        fn = _probe_locked()
        if fn is None:
            return None
        _trim_running = True
        _last_trim_monotonic = now
        return fn


def _rss_bytes() -> int | None:
    """This process's resident size (Linux ``/proc/self/statm``), or None."""
    try:
        with open("/proc/self/statm", "rb") as handle:
            return int(handle.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        return None


def _loud(released: bool, number: int, change_mb: float | None, settings: TrimSettings) -> bool:
    """Hermes' ``_should_log_trim``: INFO only for a trim that released pages, on every
    ``log_every_n``-th trim, when the resident size moved by the threshold either way
    (an unreadable size counts as moved)."""
    if not released or number % settings.log_every_n:
        return False
    return change_mb is None or abs(change_mb) >= settings.info_log_min_delta_mb


def _run(fn: Callable[[int], int], settings: TrimSettings, reason: str) -> bool:
    """Make the claimed call and log it; releases the claim. Never raises."""
    global _trim_running, _trim_call_count
    number = 0
    try:
        before = _rss_bytes()
        released = bool(fn(0))
        after = _rss_bytes()
        with _trim_lock:
            _trim_call_count += 1                    # Hermes counts completed trims
            number = _trim_call_count
    except Exception:
        logger.debug("heap trim after %s failed", reason, exc_info=True)
        return False
    finally:
        with _trim_lock:
            _trim_running = False
    try:
        if before is not None and after is not None:
            change_mb: float | None = (after - before) / 1_048_576
            sizes = f"RSS {before / 1_048_576:.1f} -> {after / 1_048_576:.1f} MB ({change_mb:+.1f} MB)"
        else:
            change_mb, sizes = None, "RSS unknown"
        loud = _loud(released, number, change_mb, settings)
        logger.log(logging.INFO if loud else logging.DEBUG,
                   "heap trim #%d after %s: %s, %s", number, reason, sizes,
                   "pages released" if released else "nothing to release")
    except Exception:
        pass
    return True


def maybe_trim(reason: str = "turn", *, get_setting: Callable[..., Any] | None = None,
               settings: TrimSettings | None = None) -> bool:
    """Trim now, in this thread, if enabled, supported and out of cooldown. Never raises.

    The synchronous form, for a caller with no event loop to keep free (:func:`after_turn`
    falls back to it). True when ``malloc_trim`` was called and returned.
    """
    try:
        if settings is None:
            settings = read_settings(get_setting)
        fn = _claim(settings)
    except Exception:
        return False
    if fn is None:
        return False
    return _run(fn, settings, reason)


def request_trim(orch: Any, reason: str) -> asyncio.Future | None:
    """When a trim is due, start it off the event loop; the shared body of both triggers.

    Reads the setting from *orch*'s runtime snapshot (a stand-in without
    ``get_setting`` is not the hub and is never trimmed for). Returns the executor
    future of a started trim, else None. Never raises.
    """
    try:
        get_setting = getattr(orch, "get_setting", None)
        if not callable(get_setting):
            return None
        settings = read_settings(get_setting)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            maybe_trim(reason, settings=settings)
            return None
        fn = _claim(settings)
        if fn is None:
            return None
        try:
            return loop.run_in_executor(None, _run, fn, settings, reason)
        except Exception:
            # A loop shutting down refuses new work: give the claim back, nothing ran.
            _release_unrun()
            return None
    except Exception:
        logger.debug("heap trim: the %s hook failed", reason, exc_info=True)
        return None


def after_turn(orch: Any, reason: str = "turn") -> asyncio.Future | None:
    """The turn-end hook: start a due trim off the loop and return at once (the turn
    does not wait; tests may await the returned future). Never raises."""
    return request_trim(orch, reason)


async def housekeeping(orch: Any) -> bool:
    """The minute housekeeping tick (the hub scheduler's ``memory-trim`` job): trim when
    the cooldown has passed since the last trim, whatever the turns did — the Hermes
    gateway-housekeeping counterpart of :func:`after_turn`. True when a trim ran and
    returned. Never raises."""
    future = request_trim(orch, "housekeeping")
    if future is None:
        return False
    try:
        return bool(await future)
    except Exception:
        return False


def _release_unrun() -> None:
    global _trim_running
    with _trim_lock:
        _trim_running = False


def _reset_for_tests() -> None:
    """Forget the probe, the cooldown and the count (tests only)."""
    global _last_trim_monotonic, _trim_running, _trim_call_count, _probe_done, _trim_fn, probe_reason
    with _trim_lock:
        _last_trim_monotonic = None
        _trim_running = False
        _trim_call_count = 0
        _probe_done = False
        _trim_fn = None
        probe_reason = "not probed"


__all__ = ["DEFAULT_SETTINGS", "SETTING", "TrimSettings", "after_turn", "housekeeping", "maybe_trim",
           "read_settings", "request_trim", "settings_problem"]
