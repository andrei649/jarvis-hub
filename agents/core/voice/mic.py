"""H247 — who holds the microphone: one lease per device, armed only with the owner's consent.

Before this, nothing recorded which surface held the microphone. The hub's own
wake-word pipeline and a HUD hands-free loop in a browser on the same machine could
both open it; no call said who held it; nothing checked consent before arming; the
host pipeline started at boot with no check at all.

- **Surfaces.** A surface is ``<kind>:<client>``: ``host:hub`` (the hub's own
  pipeline), ``hud:<tab id>`` (a browser's hands-free or push-to-talk loop),
  ``mobile:<device id>``. A Wyoming satellite has its own microphone and is not armed
  here (H222 shows it).
- **Devices.** A lease is for one device's microphone: ``host`` (the machine the hub
  runs on — its own pipeline, and a browser the route sees on loopback),
  ``remote:hud:<tab>`` (a browser elsewhere), ``mobile:<device>``. One surface at a time
  holds a device; a second is refused and told who holds it (:class:`MicRefused`
  ``mic_busy``), or takes it over explicitly, which pauses the holder and tells it
  (:meth:`MicArbiter.on_change`).
- **Consent.** A kind arms only if the owner allowed it: ``voice.mic_surfaces``,
  ``["hud", "mobile"]`` by default — a surface someone uses on purpose. The host's
  always-on wake-word listener needs ``host`` added there; until then the pipeline
  does not open the microphone. Consent withdrawn ends a lease at its next renewal.
- **Leases.** A browser's or a phone's lease lapses after :data:`LEASE_SECONDS`
  unless it arms again (a renewal, not a new arm); the host pipeline's does not.
  Pause frees the device, resume asks again; stop releases it.
- **Audit.** Every arm, take-over, stop and refusal is one audit row naming the
  surface and the device. A renewal is not.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("jarvis.voice.mic")

#: The kinds that arm here, and the ones the owner allows by default.
ARMABLE = ("host", "hud", "mobile")
DEFAULT_ALLOWED = ["hud", "mobile"]
SETTING = "voice.mic_surfaces"
LEASE_SECONDS = 45.0
MAX_LEASES = 32
MAX_CLIENT_LEN = 64
MAX_DEVICE_LEN = 96
HOST_DEVICE = "host"


class MicRefused(Exception):
    """Arming refused: ``not_consented``, ``mic_busy`` (with the holder) or ``too_many``."""

    def __init__(self, code: str, message: str, holder: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.holder = holder


def allowed_kinds() -> list[str]:
    """The kinds the owner allows to arm (``voice.mic_surfaces``); the default if unreadable."""
    try:
        from agents.core import settings_db

        value = settings_db.get_value("voice", "mic_surfaces", DEFAULT_ALLOWED)
    except Exception:  # noqa: BLE001
        value = DEFAULT_ALLOWED
    if not isinstance(value, list):
        return list(DEFAULT_ALLOWED)
    return [k for k in value if isinstance(k, str) and k in ARMABLE]


def _valid_name(name: Any, limit: int = MAX_CLIENT_LEN) -> bool:
    return (isinstance(name, str) and 0 < len(name) <= limit
            and all(ch.isprintable() and not ch.isspace() for ch in name))


def _audit_row(action: str, preview: str) -> None:
    from agents.core.app_state import get_orch

    orch = get_orch()
    log = getattr(getattr(orch, "audit", None), "log", None) if orch else None
    if not callable(log):
        return
    try:
        from agents.core.security.types import SecurityEvent, SecurityEventType

        log(SecurityEvent(event_type=SecurityEventType.AUDIT_LOG, timestamp=time.time(), findings=[],
                          content_preview=preview, action_taken=action))
    except Exception:  # noqa: BLE001
        logger.warning("could not audit a microphone lease change (%s)", action)


class MicArbiter:
    """The lease table. Thread-safe: the host pipeline runs off the event loop."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic,
                 allowed: Callable[[], list[str]] = allowed_kinds,
                 audit: Callable[[str, str], None] = _audit_row) -> None:
        self._clock = clock
        self._allowed = allowed
        self._audit = audit
        self._lock = threading.Lock()
        self._leases: dict[str, dict] = {}
        self._listeners: dict[str, Callable[[str], None]] = {}

    # ── reading ────────────────────────────────────────────────────────────────

    def _expire_locked(self) -> None:
        now = self._clock()
        for surface, lease in list(self._leases.items()):
            if lease["kind"] != "host" and now - lease["renewed"] > LEASE_SECONDS:
                del self._leases[surface]
                self._listeners.pop(surface, None)

    def _holder_locked(self, device: str) -> dict | None:
        return next((dict(lease) for lease in self._leases.values()
                     if lease["device"] == device and lease["state"] == "armed"), None)

    def holder(self, device: str) -> dict | None:
        """The surface holding *device*'s microphone now, or None."""
        with self._lock:
            self._expire_locked()
            return self._holder_locked(device)

    def lease(self, surface: str) -> dict | None:
        with self._lock:
            self._expire_locked()
            found = self._leases.get(surface)
            return dict(found) if found else None

    def status(self) -> dict:
        """Every device with a holder, every paused lease, and the kinds allowed to arm."""
        with self._lock:
            self._expire_locked()
            leases = [dict(lease) for lease in self._leases.values()]
        devices = sorted({lease["device"] for lease in leases if lease["state"] == "armed"})
        return {
            "devices": [{"device": d, "holder": next(le for le in leases if le["device"] == d and le["state"] == "armed")}
                        for d in devices],
            "paused": sorted((le for le in leases if le["state"] == "paused"), key=lambda le: le["surface"]),
            "allowed": list(self._allowed()),
        }

    def on_change(self, surface: str, listener: Callable[[str], None]) -> None:
        """Call ``listener(state)`` when *surface* is paused or armed again by someone else."""
        with self._lock:
            self._listeners[surface] = listener

    def _tell(self, surface: str, state: str) -> None:
        listener = self._listeners.get(surface)
        if listener is None:
            return
        try:
            listener(state)
        except Exception:  # noqa: BLE001
            logger.warning("a microphone lease listener failed for %s", surface, exc_info=True)

    # ── arming ─────────────────────────────────────────────────────────────────

    def arm(self, kind: str, client: str, *, device: str, take_over: bool = False) -> dict:
        """Arm *kind*:*client* on *device* (or renew its lease). Raises :class:`MicRefused`."""
        if kind not in ARMABLE:
            raise ValueError(f"{kind!r} does not arm a microphone here")
        if not _valid_name(client) or not _valid_name(device, MAX_DEVICE_LEN):
            raise ValueError("a client id is 1-64 printable characters with no spaces")
        surface = f"{kind}:{client}"
        if kind not in self._allowed():
            with self._lock:
                self._leases.pop(surface, None)
            self._audit("mic_refused", f"{surface} was refused the microphone of {device}: not allowed by {SETTING}")
            raise MicRefused("not_consented", f"{kind} may not arm a microphone: the owner has not allowed it ({SETTING})")
        taken_from = None
        with self._lock:
            self._expire_locked()
            mine = self._leases.get(surface)
            if mine and mine["device"] == device and mine["state"] == "armed":
                mine["renewed"] = self._clock()
                return dict(mine)
            holder = self._holder_locked(device)
            if holder:                         # never this surface: its own armed lease renewed above
                if not take_over:
                    raise MicRefused("mic_busy", f"the microphone of {device} is held by {holder['surface']}", holder)
                self._leases[holder["surface"]].update(state="paused", paused_by=surface)
                taken_from = holder["surface"]
            if mine is None and len(self._leases) >= MAX_LEASES:
                raise MicRefused("too_many", f"at most {MAX_LEASES} microphone leases")
            now = self._clock()
            self._leases[surface] = {"surface": surface, "kind": kind, "client": client, "device": device,
                                     "state": "armed", "since": mine["since"] if mine else now,
                                     "renewed": now, "paused_by": None}
            lease = dict(self._leases[surface])
        if taken_from:
            self._audit("mic_take_over", f"{surface} took the microphone of {device} from {taken_from}")
            self._tell(taken_from, "paused")
        else:
            self._audit("mic_arm", f"{surface} armed the microphone of {device}")
        return lease

    def pause(self, surface: str) -> dict | None:
        """Close *surface*'s microphone but keep its lease; frees the device."""
        with self._lock:
            self._expire_locked()
            lease = self._leases.get(surface)
            if lease is None:
                return None
            lease.update(state="paused", paused_by=None, renewed=self._clock())
            out = dict(lease)
        self._audit("mic_pause", f"{surface} paused the microphone of {out['device']}")
        self._tell(surface, "paused")
        return out

    def resume(self, surface: str, *, take_over: bool = False) -> dict | None:
        """Arm a paused lease again (consent and the device's holder are asked again)."""
        found = self.lease(surface)
        if found is None:
            return None
        lease = self.arm(found["kind"], found["client"], device=found["device"], take_over=take_over)
        self._tell(surface, "armed")
        return lease

    def stop(self, surface: str) -> bool:
        with self._lock:
            lease = self._leases.pop(surface, None)
            self._listeners.pop(surface, None)
        if lease is None:
            return False
        self._audit("mic_stop", f"{surface} released the microphone of {lease['device']}")
        return True


#: The process-wide table every voice path and the routes use.
ARBITER = MicArbiter()
