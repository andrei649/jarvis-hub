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
import logging
import math
import threading
import time
from collections.abc import Mapping
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
_MAX_STORE_BYTES = 1_000_000
_MAX_CONTENT_VALUE = 2_048
_MAX_QUERY_VALUE = 256
_MAX_CATALOG_CANDIDATES = 5
_MAX_POLICY_REASON = 256

logger = logging.getLogger(__name__)


def media_director_enabled() -> bool:
    return env_flag(MEDIA_DIRECTOR_ENV, default=False)


class MediaError(Exception):
    """Refused media operation (unknown device, unresolvable content, no driver)."""

    def __init__(self, reason: str, *, detail: dict | None = None) -> None:
        self.reason = str(reason)[:_MAX_POLICY_REASON]
        self.detail = dict(detail) if isinstance(detail, dict) else None
        super().__init__(self.reason)


# ── content resolution (pure; never fetches) ────────────────────────────────


def _catalog_target(item: dict) -> dict:
    value = item.get("path")
    if not isinstance(value, str) or not value.strip():
        raise MediaError("catalog_item_invalid")
    value = value.strip()
    ctype = "url" if urlparse(value).scheme.lower() in {"http", "https"} else "local"
    return {"type": ctype, "value": value}


def _candidate_metadata(items: list[dict]) -> list[dict]:
    candidates = []
    for item in items[:_MAX_CATALOG_CANDIDATES]:
        created_at = item.get("created_at")
        if isinstance(created_at, bool):
            created_at = 0.0
        try:
            created_at = float(created_at)
        except (OverflowError, TypeError, ValueError):
            created_at = 0.0
        if not math.isfinite(created_at):
            created_at = 0.0
        candidates.append(
            {
                "id": str(item.get("id", ""))[:64],
                "kind": str(item.get("kind", ""))[:32],
                "created_at": created_at,
            }
        )
    return candidates


def _canonical_navigation_preview(preview: Any) -> tuple[bool, str]:
    if not isinstance(preview, Mapping):
        return False, "governed browser preview is malformed"
    steps = preview.get("steps")
    if not isinstance(steps, list) or len(steps) != 1 or not isinstance(steps[0], Mapping):
        return False, "governed browser preview is malformed"
    step = steps[0]
    reason = step.get("reason")
    canonical = (
        type(step.get("i")) is int
        and step.get("i") == 0
        and step.get("action") == "navigate"
        and step.get("kind") == "read"
        and step.get("decision") == "run"
        and reason == ""
        and type(preview.get("blocked")) is int
        and preview.get("blocked") == 0
        and type(preview.get("needs_approval")) is int
        and preview.get("needs_approval") == 0
    )
    return canonical, str(reason or "governed browser preview is malformed")[:_MAX_POLICY_REASON]


def resolve_content(
    content: Any,
    *,
    local_roots: tuple[Path, ...] = (),
    catalog=None,
    browser=None,
    _provenance: str = "direct",
    _catalog_id: str = "",
) -> dict:
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
    value_limit = _MAX_QUERY_VALUE if ctype == "query" else _MAX_CONTENT_VALUE
    if len(value) > value_limit:
        raise MediaError("content value exceeds its size limit")
    if ctype == "catalog":
        if catalog is None:
            raise MediaError("media_catalog_disabled")
        item = catalog.get(value)
        if not isinstance(item, dict):
            raise MediaError("catalog_item_missing")
        return resolve_content(
            _catalog_target(item),
            local_roots=local_roots,
            catalog=catalog,
            browser=browser,
            _provenance="catalog",
            _catalog_id=str(item.get("id", ""))[:64],
        )
    if ctype == "query":
        if catalog is None:
            raise MediaError("media_catalog_disabled")
        matches = catalog.search(value, limit=_MAX_CATALOG_CANDIDATES + 1)
        if not matches:
            raise MediaError(
                "catalog_query_missing",
                detail={"candidates": []},
            )
        if len(matches) != 1:
            raise MediaError(
                "catalog_query_ambiguous",
                detail={"candidates": _candidate_metadata(matches)},
            )
        item = matches[0]
        return resolve_content(
            _catalog_target(item),
            local_roots=local_roots,
            catalog=catalog,
            browser=browser,
            _provenance="catalog_query",
            _catalog_id=str(item.get("id", ""))[:64],
        )
    if ctype == "url":
        scheme = urlparse(value).scheme.lower()
        if scheme not in ("http", "https"):
            raise MediaError(f"refusing non-http(s) url scheme: {scheme!r}")
        try:
            preview = browser.preview([{"action": "navigate", "url": value}])
            allowed, policy_reason = _canonical_navigation_preview(preview)
        except Exception:
            allowed, policy_reason = False, "governed browser unavailable"
        if not allowed:
            raise MediaError(
                "url_refused",
                detail={"policy_reason": policy_reason},
            )
    elif ctype == "local":
        if not local_roots:
            raise MediaError("no media.roots configured — local content is disabled")
        candidate = Path(value)
        if not candidate.is_absolute():
            raise MediaError("local content must be an absolute path")
        resolved = candidate.resolve()
        if not any(resolved.is_relative_to(root.resolve()) for root in local_roots):
            raise MediaError("local content escapes the configured media roots")
        if not resolved.is_file():
            raise MediaError("local content must be an existing regular file")
        value = str(resolved)
    resolved_content = {"type": ctype, "value": value, "provenance": _provenance}
    if _catalog_id:
        resolved_content["catalog_id"] = _catalog_id
    return resolved_content


# ── devices ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MediaDevice:
    id: str
    name: str
    kind: str
    room: str = ""
    supports: tuple[str, ...] = ("play",)

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) for value in (self.id, self.name, self.kind, self.room)):
            raise MediaError("device id, name, kind and room must be strings")
        if not self.id or not self.name:
            raise MediaError("device id and name are required")
        if len(self.id) > 64 or len(self.name) > 120 or len(self.room) > 64:
            raise MediaError("device identity fields exceed their size limits")
        if self.kind not in DEVICE_KINDS:
            raise MediaError(f"unsupported device kind: {self.kind!r}")
        if isinstance(self.supports, (str, bytes)) or not isinstance(
            self.supports, (tuple, list, frozenset)
        ):
            raise MediaError("device supports must be a collection")
        supports = tuple(self.supports)
        if not supports:
            raise MediaError("device must support at least one operation")
        if not all(isinstance(operation, str) for operation in supports):
            raise MediaError("device supports must contain operation strings")
        unsupported = sorted(set(supports) - MODES)
        if unsupported:
            raise MediaError(f"unsupported device operation: {unsupported[0]!r}")
        object.__setattr__(self, "supports", supports)


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
            if self._path.stat().st_size > _MAX_STORE_BYTES:
                return []
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
        self._lock = threading.RLock()
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
        with self._lock:
            if len(self._devices) >= _MAX_DEVICES and device.id not in self._devices:
                raise MediaError(f"device registry cap reached ({_MAX_DEVICES})")
            self._devices[device.id] = device
            self._persist()
            return device

    def remove(self, device_id: str) -> bool:
        with self._lock:
            removed = self._devices.pop(device_id, None) is not None
            if removed:
                self._persist()
            return removed

    def get(self, device_id: str) -> MediaDevice | None:
        with self._lock:
            return self._devices.get(device_id)

    def list(self) -> list[dict]:
        with self._lock:
            return [asdict(d) for d in sorted(self._devices.values(), key=lambda d: d.id)]

    def resolve_target(self, target: str) -> MediaDevice:
        """A target is a device id, or a room name (unique match required)."""
        with self._lock:
            device = self._devices.get(target)
            if device is not None:
                return device
            in_room = [d for d in self._devices.values() if d.room and d.room == target]
            if len(in_room) == 1:
                return in_room[0]
            if len(in_room) > 1:
                raise MediaError(
                    f"ambiguous target {target!r}: {len(in_room)} devices in that room"
                )
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

    def __post_init__(self) -> None:
        if not isinstance(self.device_id, str) or not self.device_id or len(self.device_id) > 64:
            raise MediaError("session device_id is invalid")
        if not isinstance(self.content, dict):
            raise MediaError("session content is invalid")
        if self.content.get("type") not in CONTENT_TYPES or not isinstance(
            self.content.get("value"), str
        ):
            raise MediaError("session content is invalid")
        if self.mode not in MODES or self.privacy not in PRIVACY_LEVELS:
            raise MediaError("session mode or privacy is invalid")
        if (
            isinstance(self.started_at, bool)
            or not isinstance(self.started_at, (int, float))
            or not math.isfinite(float(self.started_at))
        ):
            raise MediaError("session started_at is invalid")
        if self.state not in {"playing", "paused", "idle"}:
            raise MediaError("session state is invalid")
        if self.previous is not None and not isinstance(self.previous, dict):
            raise MediaError("session previous snapshot is invalid")

    def to_dict(self) -> dict:
        return asdict(self)


class SessionBoard:
    """What is playing where — the state `may_interrupt` reasons over."""

    def __init__(self, path: Path | None = None) -> None:
        self._store = _BoundedJsonStore(path, _MAX_SESSIONS)
        self._lock = threading.RLock()
        self._sessions: dict[str, MediaSession] = {}
        for item in self._store.load():
            try:
                session = MediaSession(**item)
            except (MediaError, TypeError):
                continue
            self._sessions[session.device_id] = session

    def get(self, device_id: str) -> MediaSession | None:
        with self._lock:
            return self._sessions.get(device_id)

    def set(self, session: MediaSession) -> None:
        with self._lock:
            self._sessions[session.device_id] = session
            self._persist()

    def clear(self, device_id: str) -> None:
        with self._lock:
            if self._sessions.pop(device_id, None) is not None:
                self._persist()

    def list(self) -> list[dict]:
        with self._lock:
            return [
                s.to_dict() for s in sorted(self._sessions.values(), key=lambda s: s.device_id)
            ]

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
    RESTORE_KIND = "media.restore"

    def __init__(
        self,
        *,
        registry: DeviceRegistry | None = None,
        sessions: SessionBoard | None = None,
        drivers: dict[str, MediaDriver] | None = None,
        local_roots: tuple[Path, ...] = (),
        catalog=None,
        browser=None,
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
        self._catalog = catalog
        self._browser = browser
        self._clock = clock or time.time

    def driver_for(self, device: MediaDevice) -> MediaDriver:
        return self._drivers.get(device.kind, self._null)

    @staticmethod
    def _drive(driver: MediaDriver, operation: str, device: MediaDevice, *args) -> dict | None:
        """Call an untrusted host seam without leaking transport details.

        ``None`` means the driver raised or returned a malformed response.  Callers
        decide whether that is a refused actuation or an unverified status probe.
        """
        try:
            outcome = getattr(driver, operation)(device, *args)
        except Exception:
            logger.warning(
                "media driver operation failed: operation=%s kind=%s device=%s",
                operation,
                device.kind,
                device.id,
            )
            return None
        if not isinstance(outcome, dict):
            logger.warning(
                "media driver returned invalid outcome: operation=%s kind=%s device=%s",
                operation,
                device.kind,
                device.id,
            )
            return None
        return outcome

    def present(self, payload: dict) -> dict:
        """Contract → resolve → etiquette → drive → verify → record.

        Never raises for a refusable reason — returns ``{ok: False, reason}`` so
        the facade/approval card carries an honest denial instead of a traceback.
        """
        denial = contract_denial(MEDIA_PRESENT_CONTRACT.evaluate(payload))
        if denial is not None:
            return {"ok": False, "reason": denial}
        try:
            content = resolve_content(
                payload["content"],
                local_roots=self._local_roots,
                catalog=self._catalog,
                browser=self._browser,
            )
            device = self.registry.resolve_target(str(payload["target"]))
        except MediaError as exc:
            refusal = {"ok": False, "reason": exc.reason}
            if exc.detail is not None:
                refusal["detail"] = exc.detail
            return refusal

        mode = payload.get("mode", "play")
        if mode not in device.supports:
            return {"ok": False, "reason": "unsupported_mode"}

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
        if previous is not None:
            previous["previous"] = None
        outcome = self._drive(driver, "play", device, content)
        if outcome is None:
            return {"ok": False, "reason": "driver_error", "state": "unavailable"}
        if not outcome.get("ok"):
            return {
                "ok": False,
                "reason": outcome.get("reason", "driver_refused"),
                "state": outcome.get("state"),
            }

        status = self._drive(driver, "status", device) or {}
        verified = bool(
            status.get("ok")
            and status.get("state") == "playing"
            and status.get("content", {}).get("value") == content["value"]
        )
        self.sessions.set(
            MediaSession(
                device_id=device.id,
                content=content,
                mode=mode,
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
            outcome = self._drive(driver, "stop", device)
            if outcome is None:
                return {"ok": False, "reason": "driver_error"}
            if outcome.get("ok"):
                self.sessions.clear(device_id)
            return {
                "ok": bool(outcome.get("ok")),
                "restored": "idle",
                "reason": outcome.get("reason", ""),
            }
        try:
            previous = MediaSession(**session.previous)
        except (MediaError, TypeError):
            return {"ok": False, "reason": "corrupt_session_snapshot"}
        outcome = self._drive(driver, "play", device, previous.content)
        if outcome is None:
            return {"ok": False, "reason": "driver_error"}
        if outcome.get("ok"):
            self.sessions.set(previous)
            return {"ok": True, "restored": "previous_session"}
        return {"ok": False, "reason": outcome.get("reason", "driver_refused")}

    # ── O27 facade binding ───────────────────────────────────────────────────

    def handle_perform(self, payload: dict, ctx) -> dict:
        """The ``action:media.present`` handler for ``CapabilityActionAPI``."""
        return self.present(dict(payload))

    def handle_restore(self, payload: dict, ctx) -> dict:
        """The separately mediated ``action:media.restore`` handler."""
        return self.restore(str(payload["device_id"]))


def register_media_capability(api, director: MediaDirector):
    """Bind present + restore onto the unified action facade (kernel-mediated)."""
    api.register(f"action:{MediaDirector.KIND}", director.handle_perform)
    return api.register(f"action:{MediaDirector.RESTORE_KIND}", director.handle_restore)
