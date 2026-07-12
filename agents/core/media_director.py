"""media_director.py — ORIZONT 29 wave 1: the `present()` fabric (H29.1–H29.4).

The Nerva Media Director core: a device registry, a driver seam, content
resolvers, media-session state with interruption etiquette, and the governed
``present(content, target, mode, privacy, urgency, duration)`` capability —
registered on the O27 action plane as the kernel-mediated kind ``media.present``.

Design rules (repo discipline):

* **Default-off** — nothing constructs unless ``JARVIS_MEDIA_DIRECTOR`` is set;
  the router answers ``enabled: false`` honestly.
* **Drivers are host seams** — like H15's browser/desktop drivers, the real
  Chromecast/Spotify-Connect actuation is injectable; :class:`NullMediaDriver`
  is the default and *refuses honestly* instead of pretending to play.
* **Contract before enqueue** — ``MEDIA_PRESENT_CONTRACT`` validates every
  request (0.45 pattern) before the kernel sees it.
* **Verified, not asserted** — a present() only reports ``verified: true`` when
  the driver's own ``status()`` confirms the content is active on the target.
* **Rollback = restore** — the session snapshot taken before a present() is the
  machine-readable undo; ``restore()`` replays it through the same driver seam.
* Stores are bounded, atomically written and corrupt-safe (the 0.34/0.37 shape).
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from agents.core.automation_contracts import (
    ContractTemplate,
    contract_denial,
    field_present,
    one_of,
    predicate,
)
from agents.core.env_config import env_flag
from agents.core.paths import data_path

MEDIA_DIRECTOR_ENV = "JARVIS_MEDIA_DIRECTOR"

DEVICE_KINDS = frozenset({"chromecast", "spotify_connect", "browser_tab", "local", "speaker", "tv"})
CONTENT_TYPES = frozenset({"url", "local", "catalog", "query"})
MODES = frozenset({"play", "show", "announce"})
PRIVACY_LEVELS = frozenset({"ambient", "household", "private"})
URGENCIES = frozenset({"low", "normal", "high"})

_MAX_DEVICES = 200
_MAX_SESSIONS = 200


def media_director_enabled() -> bool:
    return env_flag(MEDIA_DIRECTOR_ENV, default=False)


class MediaError(Exception):
    """Refused media operation (unknown device, unresolvable content, no driver)."""


# ── content resolution (pure; never fetches) ────────────────────────────────


def resolve_content(content: Any, *, local_roots: tuple[Path, ...] = ()) -> dict:
    """Validate + normalize a content reference. Resolution never fetches —
    it only proves the reference is a shape we are willing to hand to a device.

    ``local`` paths must live under an owner-configured root (no path escapes);
    ``url`` must be http(s). Anything else is refused with a reason, never guessed.
    """
    if not isinstance(content, dict):
        raise MediaError("content must be an object {type, value}")
    ctype = content.get("type")
    value = content.get("value")
    if ctype not in CONTENT_TYPES:
        raise MediaError(f"unsupported content type: {ctype!r}")
    if not isinstance(value, str) or not value.strip():
        raise MediaError("content value is required")
    value = value.strip()
    if ctype == "url":
        scheme = urlparse(value).scheme.lower()
        if scheme not in ("http", "https"):
            raise MediaError(f"refusing non-http(s) url scheme: {scheme!r}")
    elif ctype == "local":
        if not local_roots:
            raise MediaError("no media.roots configured — local content is disabled")
        candidate = Path(value)
        if not candidate.is_absolute():
            raise MediaError("local content must be an absolute path")
        resolved = candidate.resolve()
        if not any(resolved.is_relative_to(root.resolve()) for root in local_roots):
            raise MediaError("local content escapes the configured media roots")
        value = str(resolved)
    # "catalog" ids and "query" strings are opaque here: the driver (or the
    # media catalog, when attached) decides whether it can serve them.
    return {"type": ctype, "value": value}


# ── devices ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MediaDevice:
    id: str
    name: str
    kind: str
    room: str = ""
    supports: tuple[str, ...] = ("play",)

    def __post_init__(self) -> None:
        if not self.id or not self.name:
            raise MediaError("device id and name are required")
        if self.kind not in DEVICE_KINDS:
            raise MediaError(f"unsupported device kind: {self.kind!r}")
        if not self.supports:
            raise MediaError("device must support at least one operation")


class _BoundedJsonStore:
    """Atomic, corrupt-safe JSON array persistence (the 0.34 store discipline)."""

    def __init__(self, path: Path | None, max_keep: int) -> None:
        self._path = path
        self._max_keep = max_keep
        self._lock = threading.Lock()

    def load(self) -> list[dict]:
        if self._path is None or not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []
        except (ValueError, OSError):
            return []  # corrupt/missing degrades to empty, never crashes

    def save(self, items: list[dict]) -> None:
        if self._path is None:
            return
        with self._lock:
            pruned = items[-self._max_keep :]
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(pruned, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self._path)


class DeviceRegistry:
    """The owner-curated inventory of output devices (H29.1).

    Discovery is a *seam*: ``discover(discoverers)`` merges whatever injectable
    callables report (a pychromecast/host scanner is owner-wired, never in-repo).
    """

    def __init__(self, path: Path | None = None) -> None:
        self._store = _BoundedJsonStore(path, _MAX_DEVICES)
        self._devices: dict[str, MediaDevice] = {}
        for item in self._store.load():
            try:
                device = MediaDevice(
                    **{k: (tuple(v) if k == "supports" else v) for k, v in item.items()}
                )
            except (MediaError, TypeError):
                continue
            self._devices[device.id] = device

    def register(self, device: MediaDevice) -> MediaDevice:
        if len(self._devices) >= _MAX_DEVICES and device.id not in self._devices:
            raise MediaError(f"device registry cap reached ({_MAX_DEVICES})")
        self._devices[device.id] = device
        self._persist()
        return device

    def remove(self, device_id: str) -> bool:
        removed = self._devices.pop(device_id, None) is not None
        if removed:
            self._persist()
        return removed

    def get(self, device_id: str) -> MediaDevice | None:
        return self._devices.get(device_id)

    def list(self) -> list[dict]:
        return [asdict(d) for d in sorted(self._devices.values(), key=lambda d: d.id)]

    def resolve_target(self, target: str) -> MediaDevice:
        """A target is a device id, or a room name (unique match required)."""
        device = self._devices.get(target)
        if device is not None:
            return device
        in_room = [d for d in self._devices.values() if d.room and d.room == target]
        if len(in_room) == 1:
            return in_room[0]
        if len(in_room) > 1:
            raise MediaError(f"ambiguous target {target!r}: {len(in_room)} devices in that room")
        raise MediaError(f"unknown target: {target!r}")

    def discover(self, discoverers: list) -> int:
        """Merge devices reported by injectable discoverer callables. A broken
        discoverer is skipped (host seams must not take the registry down)."""
        added = 0
        for discoverer in discoverers:
            try:
                found = discoverer() or []
            except Exception:
                # A broken host-seam discoverer must not take the registry down.
                found = []
            for item in found:
                try:
                    device = item if isinstance(item, MediaDevice) else MediaDevice(**item)
                except (MediaError, TypeError):
                    continue
                if device.id not in self._devices:
                    self.register(device)
                    added += 1
        return added

    def _persist(self) -> None:
        self._store.save(self.list())


# ── drivers (host seams) ─────────────────────────────────────────────────────


class MediaDriver(Protocol):  # pragma: no cover - protocol definition
    def play(self, device: MediaDevice, content: dict) -> dict: ...
    def pause(self, device: MediaDevice) -> dict: ...
    def resume(self, device: MediaDevice) -> dict: ...
    def stop(self, device: MediaDevice) -> dict: ...
    def status(self, device: MediaDevice) -> dict: ...


class NullMediaDriver:
    """The default driver: refuses honestly. Real actuation (pychromecast,
    Spotify Connect, a kiosk tab) is an owner-wired host seam — mirroring the
    H15 Null browser/desktop drivers, governance is testable without hardware."""

    reason = "no media driver wired for this device (host seam — see NERVA_VISION §4-P5)"

    def play(self, device: MediaDevice, content: dict) -> dict:
        return {"ok": False, "state": "no_driver", "reason": self.reason}

    def pause(self, device: MediaDevice) -> dict:
        return {"ok": False, "state": "no_driver", "reason": self.reason}

    def resume(self, device: MediaDevice) -> dict:
        return {"ok": False, "state": "no_driver", "reason": self.reason}

    def stop(self, device: MediaDevice) -> dict:
        return {"ok": False, "state": "no_driver", "reason": self.reason}

    def status(self, device: MediaDevice) -> dict:
        return {"ok": False, "state": "no_driver", "reason": self.reason}


# ── the present() contract (0.45 discipline: validate before the kernel) ────

MEDIA_PRESENT_CONTRACT = ContractTemplate(
    kind="media.present",
    constraints=(
        field_present("content", "target"),
        one_of("mode", MODES),
        one_of("privacy", PRIVACY_LEVELS),
        one_of("urgency", URGENCIES),
        predicate(
            "bounded_duration",
            lambda view, _now: (
                view.get("duration_seconds") is None
                or (
                    isinstance(view.get("duration_seconds"), (int, float))
                    and not isinstance(view.get("duration_seconds"), bool)
                    and 0 < float(view["duration_seconds"]) <= 24 * 3600
                )
            ),
            reason="duration_out_of_bounds",
        ),
    ),
)


# ── session state + interruption etiquette (H29.4) ──────────────────────────


@dataclass
class MediaSession:
    device_id: str
    content: dict
    mode: str
    privacy: str
    started_at: float
    state: str = "playing"
    previous: dict | None = None  # snapshot for the restore() rollback

    def to_dict(self) -> dict:
        return asdict(self)


class SessionBoard:
    """What is playing where — the state `may_interrupt` reasons over."""

    def __init__(self, path: Path | None = None) -> None:
        self._store = _BoundedJsonStore(path, _MAX_SESSIONS)
        self._sessions: dict[str, MediaSession] = {}
        for item in self._store.load():
            try:
                session = MediaSession(**item)
            except TypeError:
                continue
            self._sessions[session.device_id] = session

    def get(self, device_id: str) -> MediaSession | None:
        return self._sessions.get(device_id)

    def set(self, session: MediaSession) -> None:
        self._sessions[session.device_id] = session
        self._persist()

    def clear(self, device_id: str) -> None:
        if self._sessions.pop(device_id, None) is not None:
            self._persist()

    def list(self) -> list[dict]:
        return [s.to_dict() for s in sorted(self._sessions.values(), key=lambda s: s.device_id)]

    def _persist(self) -> None:
        self._store.save(self.list())


def may_interrupt(session: MediaSession | None, *, urgency: str) -> bool:
    """Media etiquette (MOONSHOT §5.4 in the living room): an active playback
    session is only interrupted by a *high*-urgency present; everything else
    must pick another device or wait. No session → free."""
    if session is None or session.state not in ("playing", "paused"):
        return True
    return urgency == "high"


# ── the director ─────────────────────────────────────────────────────────────


class MediaDirector:
    """The `present()` capability owner (H29.2), bound to the O27 action plane.

    ``KIND`` enrolls it in the action-auth registry enumeration; the kernel
    mediates every present through ``CapabilityActionAPI`` (facade mediation).
    """

    KIND = "media.present"

    def __init__(
        self,
        *,
        registry: DeviceRegistry | None = None,
        sessions: SessionBoard | None = None,
        drivers: dict[str, MediaDriver] | None = None,
        local_roots: tuple[Path, ...] = (),
        clock=None,
    ) -> None:
        self.registry = (
            registry
            if registry is not None
            else DeviceRegistry(data_path("media") / "devices.json")
        )
        self.sessions = (
            sessions if sessions is not None else SessionBoard(data_path("media") / "sessions.json")
        )
        self._drivers = drivers or {}
        self._null = NullMediaDriver()
        self._local_roots = local_roots
        self._clock = clock or (lambda: 0.0)

    def driver_for(self, device: MediaDevice) -> MediaDriver:
        return self._drivers.get(device.kind, self._null)

    def present(self, payload: dict) -> dict:
        """Contract → resolve → etiquette → drive → verify → record.

        Never raises for a refusable reason — returns ``{ok: False, reason}`` so
        the facade/approval card carries an honest denial instead of a traceback.
        """
        denial = contract_denial(MEDIA_PRESENT_CONTRACT.evaluate(payload))
        if denial is not None:
            return {"ok": False, "reason": denial}
        try:
            content = resolve_content(payload["content"], local_roots=self._local_roots)
            device = self.registry.resolve_target(str(payload["target"]))
        except MediaError as exc:
            return {"ok": False, "reason": str(exc)}

        urgency = payload.get("urgency", "normal")
        current = self.sessions.get(device.id)
        if not may_interrupt(current, urgency=urgency):
            return {
                "ok": False,
                "reason": "session_etiquette",
                "detail": f"{device.id} is {current.state} and urgency={urgency} does not "
                "override an active session (only high does)",
            }

        driver = self.driver_for(device)
        previous = current.to_dict() if current else None
        outcome = driver.play(device, content)
        if not outcome.get("ok"):
            return {
                "ok": False,
                "reason": outcome.get("reason", "driver_refused"),
                "state": outcome.get("state"),
            }

        status = driver.status(device)
        verified = bool(
            status.get("ok")
            and status.get("state") == "playing"
            and status.get("content", {}).get("value") == content["value"]
        )
        self.sessions.set(
            MediaSession(
                device_id=device.id,
                content=content,
                mode=payload.get("mode", "play"),
                privacy=payload.get("privacy", "household"),
                started_at=float(self._clock()),
                state="playing",
                previous=previous,
            )
        )
        return {
            "ok": True,
            "device": device.id,
            "content": content,
            "verified": verified,
            "verification": "driver-status-match" if verified else "unverified-driver-status",
        }

    def restore(self, device_id: str) -> dict:
        """The machine-readable rollback: replay the pre-present snapshot."""
        session = self.sessions.get(device_id)
        if session is None:
            return {"ok": False, "reason": f"no session on {device_id!r}"}
        device = self.registry.get(device_id)
        if device is None:
            return {"ok": False, "reason": f"unknown device: {device_id!r}"}
        driver = self.driver_for(device)
        if session.previous is None:
            outcome = driver.stop(device)
            if outcome.get("ok"):
                self.sessions.clear(device_id)
            return {
                "ok": bool(outcome.get("ok")),
                "restored": "idle",
                "reason": outcome.get("reason", ""),
            }
        previous = MediaSession(**session.previous)
        outcome = driver.play(device, previous.content)
        if outcome.get("ok"):
            self.sessions.set(previous)
            return {"ok": True, "restored": "previous_session"}
        return {"ok": False, "reason": outcome.get("reason", "driver_refused")}

    # ── O27 facade binding ───────────────────────────────────────────────────

    def handle_perform(self, payload: dict, ctx) -> dict:
        """The ``action:media.present`` handler for ``CapabilityActionAPI``."""
        return self.present(dict(payload))


def register_media_capability(api, director: MediaDirector):
    """Bind the director onto the unified action facade (kernel-mediated)."""
    return api.register(f"action:{MediaDirector.KIND}", director.handle_perform)
