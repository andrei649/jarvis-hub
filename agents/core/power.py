"""H182 — keep the machine awake while a turn runs, and know when it is on battery.

Hermes holds a power assertion while it works and eases off on battery. Nerva had no
power awareness at all. Here:

- **Keep awake (off by default).** With ``JARVIS_KEEP_AWAKE=1`` a turn holds a power
  assertion from its start to its end — released on the reply, on an error and when the
  hub quits (the lifespan and ``atexit``). The OS mechanism is the platform's own:
  ``caffeinate -i -w <hub pid>`` on macOS, ``systemd-inhibit --what=idle:sleep`` around
  ``tail --pid=<hub pid>`` on Linux (both end with the hub, even a killed one) and
  ``SetThreadExecutionState`` on Windows. It is gated as ``host.control``: the owner's
  ``system-control`` permission, the host-control contract (action ``power.keep_awake``),
  an Action Kernel GRANT and a durable audit row, asked once per process; a refusal
  keeps it off until the next start and says why on ``GET /api/power``. Concurrent turns
  share one assertion; a helper that exits on its own is reported, not trusted.
- **Power state.** ``psutil.sensors_battery()`` (on battery, percent, plugged) and a
  resume from sleep, seen as the wall clock jumping ahead of the monotonic clock
  (:data:`RESUME_GAP_SECONDS`; the monotonic clock stops while Linux and macOS sleep,
  so a resume there is seen within one tick). ``GET /api/power`` answers it and
  ``GET /api/power/stream`` pushes every change to connected clients; the HUD shows it.
- **Battery-aware throttling.** Below ``system.battery_defer_percent`` (50 by default;
  0 never, 100 always) on battery, the heavy background jobs — memory maintenance, the
  tech scout, the learning loop, prompt evolution and the WorldView KG sync — skip their
  run and say ``deferred_on_battery``. Nothing the owner asked for is deferred.
"""
from __future__ import annotations

import atexit
import logging
import os
import shutil
import signal
import subprocess  # nosec B404 - a fixed argv (backend_argv), never a shell
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("jarvis.power")

KEEP_AWAKE_ENV = "JARVIS_KEEP_AWAKE"
CONTRACT_ACTION = "power.keep_awake"
SETTING_DEFER_PERCENT = "system.battery_defer_percent"
DEFAULT_DEFER_PERCENT = 50
RESUME_GAP_SECONDS = 60.0
RESUME_SHOWN_SECONDS = 600.0
_STOP_TIMEOUT = 1.0          # the turn's finally waits at most this long for the helper

# Windows SetThreadExecutionState flags.
_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001


def keep_awake_enabled() -> bool:
    from agents.core.env_config import env_flag

    return env_flag(KEEP_AWAKE_ENV)


def backend_name(platform: str | None = None, which: Callable[[str], Any] = shutil.which) -> str:
    """The mechanism this OS offers: ``caffeinate``, ``systemd-inhibit``, ``windows`` or ``""``."""
    plat = platform or sys.platform
    if plat == "darwin":
        return "caffeinate" if which("caffeinate") else ""
    if plat.startswith("linux"):
        return "systemd-inhibit" if which("systemd-inhibit") else ""
    if plat == "win32":
        return "windows"
    return ""


def backend_argv(name: str, pid: int) -> list[str]:
    if name == "caffeinate":
        return ["caffeinate", "-i", "-w", str(pid)]     # -w: it ends with the hub, whatever happens
    if name == "systemd-inhibit":                       # tail --pid: it ends with the hub, too
        return ["systemd-inhibit", "--what=idle:sleep", "--who=Nerva", "--why=a turn is running",
                "--mode=block", "tail", f"--pid={pid}", "-f", "/dev/null"]
    return []


def authorize_keep_awake(orch: Any, *, kernel: Any = None) -> str | None:
    """A refusal reason, or None once ``host.control`` allows the power assertion.

    Order: the owner's ``system-control`` permission, the host-control contract, an
    Action Kernel GRANT (QUEUE and DENY both refuse), then a durable audit row (no audit
    log, or a refused row, refuses too). The action's origin is fixed: keep-awake is the
    owner's own switch (``JARVIS_KEEP_AWAKE``), whatever turn happens to ask first.
    """
    gate = getattr(orch, "permission_gate", None)
    check_call = getattr(gate, "check_call", None)
    if not callable(check_call):
        return "system-control permission gate is unavailable"
    try:
        if not check_call("system-control", "jarvis"):
            return "Jarvis is not permitted to use system-control"
    except Exception:
        return "system-control permission gate is unavailable"
    from agents.core.automation_contracts import contract_denial
    from agents.core.autonomy.remediation import HOST_CONTROL_CONTRACT, HOST_CONTROL_CONTRACT_KIND

    try:
        decision = HOST_CONTROL_CONTRACT.evaluate({
            "kind": HOST_CONTROL_CONTRACT_KIND, "action": CONTRACT_ACTION, "agent": "jarvis",
            "target": "keep-awake",
        })
    except Exception:
        return "host-control contract is unavailable"
    blocked = contract_denial(decision)
    if blocked:
        return f"host-control contract denied: {blocked}"
    from agents.core.action_origin import DEFAULT_ACTION_ORIGIN
    from agents.core.kernel import Action, Verdict, kernel_enabled
    from agents.core.kernel.binding import make_action_kernel

    if not kernel_enabled():
        return "Action Kernel is required to keep the machine awake"
    kernel = kernel or make_action_kernel(orch)
    if not callable(kernel):
        return "Action Kernel is unavailable"
    try:
        verdict = kernel(Action(
            kind=HOST_CONTROL_CONTRACT_KIND, agent="jarvis", title="keep the machine awake during turns",
            payload={"action": CONTRACT_ACTION, "target": "keep-awake", "risk_tier": 1, "reversible": True},
            origin=DEFAULT_ACTION_ORIGIN,
        ))
    except Exception:
        return "Action Kernel is unavailable"
    if verdict.verdict is Verdict.QUEUE:
        return f"approval required: {verdict.reason or 'the Action Kernel queued it'}"
    if verdict.verdict is not Verdict.GRANT:
        return f"Action Kernel denied it: {verdict.reason or 'denied'}"
    audit = getattr(orch, "audit", None)
    log = getattr(audit, "log", None)
    if not callable(log):
        return "durable audit is unavailable"
    try:
        from agents.core.security.types import SecurityEvent, SecurityEventType

        log(SecurityEvent(event_type=SecurityEventType.AUDIT_LOG, timestamp=time.time(), findings=[],
                          content_preview="power keep-awake", action_taken=f"{CONTRACT_ACTION} authorized"))
    except Exception:
        return "durable audit rejected the authorization row"
    return None


class KeepAwake:
    """One shared power assertion, held while at least one turn runs."""

    def __init__(self, *, enabled: Callable[[], bool] = keep_awake_enabled,
                 spawn: Callable[..., Any] = subprocess.Popen, platform: str | None = None,
                 which: Callable[[str], Any] = shutil.which, set_state: Callable[[int], Any] | None = None,
                 pid: Callable[[], int] = os.getpid, killpg: Callable[[int, int], Any] | None = None) -> None:
        self._enabled = enabled
        self._spawn = spawn
        self._killpg = killpg if killpg is not None else getattr(os, "killpg", None)
        self._platform = platform
        self._which = which
        self._set_state = set_state
        self._pid = pid
        self._lock = threading.Lock()
        self._holders = 0
        self._proc: Any = None
        self._win_held = False
        self._authorized = False
        self._refused: str | None = None
        self._error: str | None = None

    def _backend(self) -> str:
        return backend_name(self._platform, self._which)

    def _start(self) -> None:
        name = self._backend()
        self._error = None
        try:
            if name == "windows":
                (self._set_state or _windows_set_state)(_ES_CONTINUOUS | _ES_SYSTEM_REQUIRED)
                self._win_held = True
            elif name:                                     # its own group, so release reaches its child too
                self._proc = self._spawn(backend_argv(name, self._pid()), stdin=subprocess.DEVNULL,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                         start_new_session=True)
            else:
                self._error = "no keep-awake mechanism on this system"
        except Exception as exc:                            # a missing binary never fails a turn
            self._proc = None
            self._error = f"keep-awake did not start ({type(exc).__name__})"
            logger.warning("keep-awake: %s", self._error)

    def _stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None:
            try:
                if callable(self._killpg) and proc.poll() is None:
                    self._killpg(proc.pid, signal.SIGTERM)  # our child's own group, not yet reaped
                else:
                    proc.terminate()
                proc.wait(timeout=_STOP_TIMEOUT)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    logger.debug("keep-awake child already gone", exc_info=True)
        if self._win_held:
            self._win_held = False
            try:
                (self._set_state or _windows_set_state)(_ES_CONTINUOUS)
            except Exception:
                logger.debug("keep-awake: releasing the execution state failed", exc_info=True)

    def acquire(self, authorize: Callable[[], str | None]) -> bool:
        """Hold the assertion for one more turn; False when it is off or refused."""
        if not self._enabled():
            return False
        with self._lock:
            if self._refused is not None:
                return False
            if not self._authorized:
                reason = authorize()
                if reason:
                    self._refused = reason
                    logger.warning("keep-awake is off: %s", reason)
                    return False
                self._authorized = True
            self._holders += 1
            if self._holders == 1:
                self._start()
            return True

    def release(self) -> None:
        with self._lock:
            if self._holders == 0:
                return
            self._holders -= 1
            if self._holders == 0:
                self._stop()

    def release_all(self) -> None:
        """The hub is quitting: drop every hold."""
        with self._lock:
            self._holders = 0
            self._stop()

    def status(self) -> dict:
        with self._lock:
            error = self._error
            alive = self._win_held
            if self._proc is not None:
                code = self._proc.poll()
                alive = code is None
                if not alive:                             # the OS helper gave up (no permission, gone)
                    error = f"keep-awake helper exited (code {code})"
            return {
                "enabled": bool(self._enabled()),
                "active": alive,                          # the helper only runs while held
                "holders": self._holders,
                "backend": self._backend(),
                "refused": self._refused,
                "error": error,
            }

    def reset(self) -> None:
        """Tests: forget the authorization and the refusal."""
        self.release_all()
        with self._lock:
            self._authorized = False
            self._refused = None
            self._error = None


def _windows_set_state(flags: int) -> None:                 # pragma: no cover - Windows only
    import ctypes

    ctypes.windll.kernel32.SetThreadExecutionState(flags)


def read_battery(sensors: Callable[[], Any] | None = None) -> dict:
    """On battery, percent and plugged-in, from ``psutil.sensors_battery()``."""
    try:
        if sensors is None:
            import psutil

            sensors = psutil.sensors_battery
        raw = sensors()
    except Exception:
        raw = None
    if raw is None:
        return {"battery": False, "on_battery": False, "percent": None, "plugged": None}
    plugged = getattr(raw, "power_plugged", None)
    percent = getattr(raw, "percent", None)
    try:
        percent = round(float(percent), 1) if percent is not None else None
    except (TypeError, ValueError):
        percent = None
    return {"battery": True, "on_battery": plugged is False, "percent": percent,
            "plugged": plugged if isinstance(plugged, bool) else None}


class PowerMonitor:
    """The power state, and the moment the machine last woke from sleep."""

    def __init__(self, *, read: Callable[[], dict] = read_battery, wall: Callable[[], float] = time.time,
                 mono: Callable[[], float] = time.monotonic) -> None:
        self._read = read
        self._wall = wall
        self._mono = mono
        self._lock = threading.Lock()
        self._last: tuple[float, float] | None = None
        self._resumed_at: float | None = None
        self._state: dict = {}
        self._seq = 0

    def tick(self) -> dict:
        """Read the battery, notice a resume, and return the state (``seq`` moves on change)."""
        battery = self._read()
        with self._lock:
            wall, mono = self._wall(), self._mono()
            if self._last is not None:
                gap = (wall - self._last[0]) - (mono - self._last[1])
                if gap > RESUME_GAP_SECONDS:
                    self._resumed_at = wall
                    logger.info("the machine resumed from sleep (%.0f s asleep)", gap)
            self._last = (wall, mono)
            resumed = self._resumed_at is not None and wall - self._resumed_at <= RESUME_SHOWN_SECONDS
            state = {**battery, "resumed_at": self._resumed_at if resumed else None}
            if state != self._state:
                self._state = state
                self._seq += 1
            return {**self._state, "seq": self._seq}

    def snapshot(self) -> dict:
        with self._lock:
            return {**self._state, "seq": self._seq}


def defer_percent(value: Any) -> int:
    """The setting as 0..100; anything else is the default."""
    if isinstance(value, bool):
        return DEFAULT_DEFER_PERCENT
    try:
        pct = int(value)
    except (TypeError, ValueError):
        return DEFAULT_DEFER_PERCENT
    return min(100, max(0, pct))


def should_defer(state: dict, pct: int) -> bool:
    """On battery and below the threshold (an unknown percent on battery defers)."""
    if pct <= 0 or not state.get("on_battery"):
        return False
    percent = state.get("percent")
    return pct >= 100 or percent is None or percent < pct


KEEP_AWAKE = KeepAwake()
MONITOR = PowerMonitor()
atexit.register(KEEP_AWAKE.release_all)


def hold_for_turn(orch: Any) -> bool:
    """A turn starts: hold the assertion when keep-awake is on. Never raises."""
    try:
        return KEEP_AWAKE.acquire(lambda: authorize_keep_awake(orch))
    except Exception:
        logger.warning("keep-awake: the hold failed", exc_info=True)
        return False


def release_for_turn(held: bool) -> None:
    """The turn ended (reply, error or cancel): drop its hold. Never raises."""
    if not held:
        return
    try:
        KEEP_AWAKE.release()
    except Exception:
        logger.warning("keep-awake: the release failed", exc_info=True)


def defer_background(get_setting: Callable[..., Any] | None) -> bool:
    """Whether a heavy background job should skip this run."""
    pct = defer_percent(get_setting(SETTING_DEFER_PERCENT, DEFAULT_DEFER_PERCENT)
                        if callable(get_setting) else DEFAULT_DEFER_PERCENT)
    deferred = should_defer(MONITOR.tick(), pct)
    if deferred:
        logger.info("background job deferred: on battery below %d%%", pct)
    return deferred


def public_state(get_setting: Callable[..., Any] | None = None) -> dict:
    state = MONITOR.tick()
    pct = defer_percent(get_setting(SETTING_DEFER_PERCENT, DEFAULT_DEFER_PERCENT)
                        if callable(get_setting) else DEFAULT_DEFER_PERCENT)
    return {"power": state, "defer_percent": pct, "background_deferred": should_defer(state, pct),
            "keep_awake": KEEP_AWAKE.status()}


__all__ = [
    "CONTRACT_ACTION", "DEFAULT_DEFER_PERCENT", "KEEP_AWAKE", "KEEP_AWAKE_ENV", "KeepAwake", "MONITOR",
    "PowerMonitor", "RESUME_GAP_SECONDS", "SETTING_DEFER_PERCENT", "authorize_keep_awake", "backend_argv",
    "backend_name", "defer_background", "defer_percent", "hold_for_turn", "public_state", "read_battery",
    "release_for_turn", "should_defer",
]
