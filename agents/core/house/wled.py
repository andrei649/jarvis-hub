"""H30.8 — default-off ambient light bridge (assistant state → LAN WLED strip).

Maps the SAME orb states the HUD renders (``frontend/src/orb.tsx``:
off / idle / listening / transcribing / speaking / error) onto a WLED
controller over its plain local HTTP JSON API, so the strip and the sphere can
never disagree about what the assistant is doing.

Boundaries, all by construction:

- **Off by default.** ``JARVIS_WLED_URL`` unset → every write refuses with
  ``wled_not_configured``; nothing is probed, nothing is sent.
- **Strict-local.** The URL must be a bare http(s) origin whose host is a LAN
  literal, ``localhost``, ``*.local`` or an explicitly allowlisted name, and
  every resolved address must be a LAN address (the Home Assistant rule set,
  reused verbatim). A vendor cloud is unrepresentable here.
- **Every write crosses the Action Kernel** under the existing
  ``house.control`` kind through ``CapabilityActionAPI`` — the same rail
  :class:`~agents.core.house.actuation.HouseActuator` uses to reach its driver.
  ``DENY`` → nothing is sent; ``QUEUE`` → the write waits for the owner; the
  bridge never self-authorizes and there is no second policy layer.
- **Silent when unreachable.** A transport failure returns
  ``wled_unreachable`` and the last-known scene is *not* updated — the bridge
  never guesses the strip's state. Writes ask WLED to echo its state back
  (``"v": true``) and are only recorded as applied when the echo matches.
- **Not noisy.** An unchanged scene is a no-op without a network call; a
  per-minute write budget bounds a flapping voice pipeline.
- **No new dependency.** The default transport lazy-imports ``httpx`` inside
  the call and refuses with ``dependency_unavailable:httpx`` if it is missing.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from types import MappingProxyType
from urllib.parse import urlparse, urlunparse

from agents.core.capability_actions import CapabilityActionAPI, PerformContext
from agents.core.env_config import env_str

from .actuation import HOUSE_CONTROL_KIND
from .home_assistant import _is_lan_address, _resolve

logger = logging.getLogger(__name__)

WLED_URL_ENV = "JARVIS_WLED_URL"
WLED_ENTITY_ID = "light.wled_ambient"
WLED_CONTROL = "ambient"
WLED_ACTION = "scene"
_CONTROL_CAPABILITY = f"action:{HOUSE_CONTROL_KIND}"
_DEFAULT_TIMEOUT = 2.0
_DEFAULT_WRITES_PER_MINUTE = 30
_HOST_SLUG = re.compile(r"[^a-z0-9]+")

# One row per orb state, colours copied from ORB_LOOK in frontend/src/orb.tsx so
# the strip mirrors the sphere. ``fx`` is a WLED effect id (0 = solid,
# 2 = breathe); ``bri`` is 0..255. ``off`` is the only row that turns the strip
# off — everything else is a glow whose intensity follows the orb's ``base``.
WLED_SCENES: Mapping[str, Mapping[str, object]] = MappingProxyType(
    {
        "off": MappingProxyType({"on": False}),
        "idle": MappingProxyType({"on": True, "bri": 24, "col": (127, 214, 255), "fx": 2}),
        "listening": MappingProxyType({"on": True, "bri": 64, "col": (65, 245, 155), "fx": 2}),
        "transcribing": MappingProxyType(
            {"on": True, "bri": 96, "col": (255, 194, 77), "fx": 2}
        ),
        "speaking": MappingProxyType({"on": True, "bri": 120, "col": (143, 224, 255), "fx": 0}),
        "error": MappingProxyType({"on": True, "bri": 40, "col": (255, 90, 82), "fx": 2}),
    }
)


class WLEDConfigError(ValueError):
    """The configured WLED URL is not a strict-local origin."""


def validate_wled_origin(url: str, *, allowed_hosts: tuple[str, ...] = (), resolver=None) -> str:
    """Return the canonical origin for *url* or raise :class:`WLEDConfigError`.

    Same rule set as the Home Assistant adapter: bare origin, http(s), no
    credentials/query/fragment/path, LAN literal or allowlisted host, and every
    resolved address on the LAN.
    """
    if not isinstance(url, str) or not url.strip():
        raise WLEDConfigError("WLED URL is required")
    try:
        parsed = urlparse(url.strip())
        port = parsed.port
    except ValueError as exc:
        raise WLEDConfigError("WLED URL is invalid") from exc
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise WLEDConfigError("WLED URL must use http(s)")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise WLEDConfigError("WLED URL cannot contain credentials, query, or fragment")
    if parsed.path not in {"", "/"}:
        raise WLEDConfigError("WLED URL must identify an origin, not a path")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise WLEDConfigError("WLED URL requires a host")
    allowed = tuple(item.lower() for item in allowed_hosts)
    if allowed and host not in allowed:
        raise WLEDConfigError("WLED host is not owner-allowlisted")
    if not allowed and host != "localhost" and not host.endswith(".local"):
        try:
            literal = ipaddress.ip_address(host)
        except ValueError as exc:
            raise WLEDConfigError("WLED host requires an explicit allowlist") from exc
        if not _is_lan_address(str(literal)):
            raise WLEDConfigError("WLED host must stay on the LAN")
    try:
        addresses = _resolve(host, port or (443 if scheme == "https" else 80), resolver)
    except Exception as exc:
        raise WLEDConfigError("WLED host could not be resolved") from exc
    if not addresses or any(not _is_lan_address(address) for address in addresses):
        raise WLEDConfigError("WLED origin must resolve only to LAN addresses")
    netloc = parsed.netloc.lower().rstrip(".")
    return urlunparse((scheme, netloc, "", "", "", "")).rstrip("/")


def scene_payload(state: str) -> dict:
    """WLED ``/json/state`` body for one orb state (``"v": true`` echoes state back)."""
    scene = WLED_SCENES.get(state)
    if scene is None:
        raise ValueError("unknown ambient scene")
    body: dict = {"on": bool(scene["on"]), "v": True}
    if body["on"]:
        body["bri"] = int(scene["bri"])
        body["seg"] = [{"col": [list(scene["col"])], "fx": int(scene["fx"])}]
    return body


def _echo_matches(body: Mapping, echo: object) -> bool:
    if not isinstance(echo, Mapping):
        return False
    if bool(echo.get("on")) != body["on"]:
        return False
    if not body["on"]:
        return True
    try:
        return abs(int(echo.get("bri", -1)) - body["bri"]) <= 2
    except (TypeError, ValueError):
        return False


class HttpxJSONTransport:
    """Default LAN transport: one POST, no redirects, no proxies, short timeout."""

    def __init__(self, timeout: float = _DEFAULT_TIMEOUT) -> None:
        self._timeout = float(timeout)

    async def __call__(self, url: str, body: Mapping) -> dict:
        try:
            import httpx
        except ImportError:
            return {"ok": False, "reason": "dependency_unavailable:httpx"}
        try:
            async with httpx.AsyncClient(
                follow_redirects=False, trust_env=False, timeout=self._timeout
            ) as client:
                response = await client.post(url, json=dict(body))
        except Exception:
            return {"ok": False, "reason": "wled_unreachable"}
        if response.status_code != 200:
            return {"ok": False, "reason": "wled_unreachable", "status": response.status_code}
        try:
            echo = response.json()
        except ValueError:
            echo = None
        return {"ok": True, "status": 200, "echo": echo}


class WLEDBridge:
    """Ambient scene writer; every ``set_scene`` is a governed ``house.control``."""

    def __init__(
        self,
        *,
        url: str | None = None,
        transport: Callable | None = None,
        authorizer: Callable | None = None,
        allowed_hosts: tuple[str, ...] = (),
        resolver=None,
        clock: Callable[[], float] | None = None,
        agent: str = "hestia",
        writes_per_minute: int = _DEFAULT_WRITES_PER_MINUTE,
    ) -> None:
        raw = env_str(WLED_URL_ENV) if url is None else url
        self._url = raw.strip() if isinstance(raw, str) else ""
        self._transport = transport or HttpxJSONTransport()
        self._allowed_hosts = tuple(allowed_hosts)
        self._resolver = resolver
        self._clock = clock or time.monotonic
        self._agent = agent
        self._budget = max(1, int(writes_per_minute))
        self._writes: deque[float] = deque()
        self._lock = threading.Lock()
        self._origin: str | None = None
        self._origin_error = ""
        self._scene = ""
        self._last_result: dict = {}
        self._actions = CapabilityActionAPI(authorizer=authorizer)
        self._actions.register(_CONTROL_CAPABILITY, self._apply)

    # ── configuration ────────────────────────────────────────────────────────
    @property
    def configured(self) -> bool:
        return bool(self._url)

    def _resolve_origin(self) -> str:
        """Validate once (blocking DNS — callers run it off the loop)."""
        with self._lock:
            if self._origin is not None:
                return self._origin
            if self._origin_error:
                raise WLEDConfigError(self._origin_error)
            try:
                self._origin = validate_wled_origin(
                    self._url, allowed_hosts=self._allowed_hosts, resolver=self._resolver
                )
            except WLEDConfigError as exc:
                self._origin_error = str(exc)
                raise
            return self._origin

    def _host(self) -> str:
        return (urlparse(self._url).hostname or "").lower() if self._url else ""

    def _entity_id(self) -> str:
        slug = _HOST_SLUG.sub("_", self._host()).strip("_")
        return f"light.wled_{slug}"[:128] if slug else WLED_ENTITY_ID

    # ── governed write ───────────────────────────────────────────────────────
    def _within_budget(self) -> bool:
        now = float(self._clock())
        with self._lock:
            while self._writes and now - self._writes[0] > 60.0:
                self._writes.popleft()
            if len(self._writes) >= self._budget:
                return False
            self._writes.append(now)
            return True

    async def _apply(self, payload: dict, _context: PerformContext) -> dict:
        """Kernel-approved handler: the only place a byte leaves for the strip."""
        origin = self._origin
        if origin is None:
            return {"ok": False, "reason": "wled_url_rejected"}
        body = scene_payload(str(payload.get("scene", "")))
        result = self._transport(f"{origin}/json/state", body)
        if asyncio.iscoroutine(result) or hasattr(result, "__await__"):
            result = await result
        if not isinstance(result, Mapping) or not result.get("ok"):
            reason = ""
            if isinstance(result, Mapping):
                reason = str(result.get("reason") or "")
            return {"ok": False, "reason": reason or "wled_unreachable"}
        if not _echo_matches(body, result.get("echo")):
            return {"ok": False, "reason": "wled_verification_failed"}
        return {"ok": True, "verified": True}

    async def set_scene(self, state: str) -> dict:
        """Drive the strip to the scene for *state*; refuses honestly at every seam."""
        if not isinstance(state, str) or state not in WLED_SCENES:
            return self._remember({"ok": False, "reason": "unknown_scene"})
        if not self.configured:
            return self._remember({"ok": False, "reason": "wled_not_configured"})
        try:
            await asyncio.to_thread(self._resolve_origin)
        except WLEDConfigError as exc:
            return self._remember({"ok": False, "reason": "wled_url_rejected", "detail": str(exc)})
        if state == self._scene:
            return self._remember({"ok": True, "scene": state, "unchanged": True})
        if not self._within_budget():
            return self._remember({"ok": False, "reason": "wled_rate_limited", "scene": state})
        payload = {
            "version": 1,
            "control": WLED_CONTROL,
            "entity_id": self._entity_id(),
            "action": WLED_ACTION,
            "scene": state,
            "risk_tier": 1,
            "reversible": True,
            "signal_quality": 1.0,
        }
        perform = await self._actions.perform(
            _CONTROL_CAPABILITY,
            payload,
            PerformContext(
                agent=self._agent,
                title=f"ambient {state} → {payload['entity_id']}",
                capability_name=HOUSE_CONTROL_KIND,
                scope=f"house:{payload['entity_id']}",
            ),
        )
        if perform.status == "queued":
            return self._remember(
                {"ok": False, "reason": "approval_required", "scene": state, "queued": True}
            )
        if perform.status != "completed":
            return self._remember(
                {"ok": False, "reason": perform.reason or "kernel_denied", "scene": state}
            )
        output = perform.output if isinstance(perform.output, Mapping) else {}
        if not output.get("ok"):
            reason = str(output.get("reason") or "wled_unreachable")
            return self._remember({"ok": False, "reason": reason, "scene": state})
        with self._lock:
            self._scene = state
        return self._remember({"ok": True, "scene": state, "verified": True})

    def _remember(self, result: dict) -> dict:
        with self._lock:
            self._last_result = dict(result)
        return result

    def status(self) -> dict:
        with self._lock:
            return {
                "configured": self.configured,
                "host": self._host(),
                "scene": self._scene or None,
                "reason": "" if self.configured else "wled_not_configured",
                "last_result": dict(self._last_result),
            }


__all__ = [
    "WLED_ACTION",
    "WLED_CONTROL",
    "WLED_ENTITY_ID",
    "WLED_SCENES",
    "WLED_URL_ENV",
    "HttpxJSONTransport",
    "WLEDBridge",
    "WLEDConfigError",
    "scene_payload",
    "validate_wled_origin",
]
