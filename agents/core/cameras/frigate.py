"""Read-only, LAN-pinned Frigate event adapter for H31."""

from __future__ import annotations

import asyncio
import base64
import inspect
import ipaddress
import json
import math
import re
import socket
import threading
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx

from agents.core.security.secret_broker import SecretBroker

from .models import CameraEvent, MaskedFrame, PrivacyLease, PrivacyPollingGrant
from .privacy import CameraPrivacyPolicy
from .source import CameraEventPage, CameraSourceError, CameraSourceHealth

__all__ = ["FrigateConfig", "FrigateEventSource"]

_SECRET_REF_RE = re.compile(r"^\{\{secret:[A-Za-z0-9_.-]+\}\}$")
_EVENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CAMERA_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_CURSOR_RE = re.compile(r"^[A-Za-z0-9_-]{1,256}$")
_MAX_EVENTS = 100
_MAX_SOURCE_ITEMS = 200
_MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024
_BLOCKED_HOSTS = frozenset(
    {
        "100.100.100.200",
        "169.254.169.254",
        "metadata.google.com",
        "metadata.google.internal",
    }
)
_LABEL_MAP = {
    "animal": "animal",
    "bicycle": "vehicle",
    "bird": "animal",
    "bus": "vehicle",
    "car": "vehicle",
    "cat": "animal",
    "dog": "animal",
    "motorcycle": "vehicle",
    "package": "package",
    "person": "person",
    "truck": "vehicle",
    "vehicle": "vehicle",
}

Resolver = Callable[[str, int], Sequence[str]]
PollGate = Callable[[], PrivacyPollingGrant]
Sleeper = Callable[[float], Awaitable[None] | None]


@dataclass(frozen=True, slots=True)
class FrigateConfig:
    """Owner-curated exact Frigate origin; disabled unless explicitly enabled."""

    origin: str
    credential_ref: str = ""
    enabled: bool = False
    connect_timeout_seconds: float = 2.0
    read_timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not isinstance(self.origin, str) or len(self.origin) > 512:
            raise ValueError("Frigate origin must be a bounded URL")
        parsed = urlsplit(self.origin.strip())
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Frigate origin must be an exact http(s) origin")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("Frigate origin has an invalid port") from exc
        if port is not None and not 1 <= port <= 65535:
            raise ValueError("Frigate origin has an invalid port")
        host = parsed.hostname.lower().rstrip(".")
        try:
            ipaddress.ip_address(host)
            valid_host = True
        except ValueError:
            labels = host.split(".")
            valid_host = bool(
                labels
                and all(
                    re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                    for label in labels
                )
            )
        if (
            len(host) > 253
            or host in _BLOCKED_HOSTS
            or "%" in host
            or not valid_host
        ):
            raise ValueError("Frigate origin host is forbidden")
        default_port = 443 if parsed.scheme == "https" else 80
        normalized_port = port or default_port
        display_host = f"[{host}]" if ":" in host else host
        normalized = f"{parsed.scheme}://{display_host}"
        if normalized_port != default_port or port is not None:
            normalized += f":{normalized_port}"
        object.__setattr__(self, "origin", normalized)
        if self.credential_ref and _SECRET_REF_RE.fullmatch(self.credential_ref) is None:
            raise ValueError("Frigate credential must be a SecretBroker reference")
        if not isinstance(self.enabled, bool):
            raise ValueError("Frigate enabled must be a boolean")
        for field_name in ("connect_timeout_seconds", "read_timeout_seconds"):
            value = getattr(self, field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or not 0.1 <= float(value) <= 30.0
            ):
                raise ValueError(f"Frigate {field_name} must be between 0.1 and 30 seconds")


def _default_resolver(host: str, port: int) -> tuple[str, ...]:
    return tuple({entry[4][0] for entry in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})


def _is_allowed_lan_ip(value: str) -> bool:
    if "%" in value:
        return False
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return bool(
        (address.is_private or address.is_loopback or address.is_link_local)
        and not address.is_unspecified
        and not address.is_multicast
        and str(address) not in _BLOCKED_HOSTS
    )


def _cursor_encode(event: CameraEvent) -> str:
    payload = json.dumps(
        [event.occurred_at, event.event_id],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _cursor_decode(value: str | None) -> tuple[float, str] | None:
    if value is None:
        return None
    if not isinstance(value, str) or _CURSOR_RE.fullmatch(value) is None:
        raise CameraSourceError("cursor_invalid")
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.b64decode(padded, altchars=b"-_", validate=True))
        if not isinstance(payload, list) or len(payload) != 2:
            raise ValueError
        occurred_at = float(payload[0])
        event_id = payload[1]
        if (
            not math.isfinite(occurred_at)
            or occurred_at < 0
            or not isinstance(event_id, str)
            or _EVENT_ID_RE.fullmatch(event_id) is None
        ):
            raise ValueError
        return occurred_at, event_id
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CameraSourceError("cursor_invalid") from exc


class _FrigateHTTP:
    """Private byte transport. It is not an orchestrator, tool, route, or capability surface."""

    def __init__(
        self,
        *,
        config: FrigateConfig,
        secret_broker: SecretBroker,
        kill_switch: Any,
        transport: httpx.AsyncBaseTransport | None,
        resolver: Resolver | None,
        sleep: Sleeper | None,
        max_attempts: int,
    ) -> None:
        if not isinstance(secret_broker, SecretBroker):
            raise ValueError("Frigate requires SecretBroker")
        if not callable(getattr(kill_switch, "is_halted", None)):
            raise ValueError("Frigate requires a kill switch")
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 3:
            raise ValueError("Frigate max_attempts must be between 1 and 3")
        self.config = config
        self._secret_broker = secret_broker
        self._kill_switch = kill_switch
        self._transport = transport
        self._resolver = resolver or _default_resolver
        self._sleep = sleep or asyncio.sleep
        self._max_attempts = max_attempts

    def _preflight(self) -> None:
        if not self.config.enabled:
            raise CameraSourceError("source_disabled")
        try:
            halted = self._kill_switch.is_halted("camera-source")
        except Exception as exc:
            raise CameraSourceError("source_halt_state_unavailable") from exc
        if halted:
            raise CameraSourceError("source_halted")

    async def _resolve_pinned(self) -> tuple[str, str, str, int]:
        parsed = urlsplit(self.config.origin)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if host in _BLOCKED_HOSTS:
            raise CameraSourceError("lan_origin_required")
        try:
            # The default resolver is socket.getaddrinfo; inline it put a blocking
            # DNS lookup on the loop for every request attempt. Offload it.
            resolved = await asyncio.to_thread(self._resolver, host, port)
            addresses = tuple(dict.fromkeys(str(value) for value in resolved))
        except Exception as exc:
            raise CameraSourceError("source_offline") from exc
        if not addresses or any(not _is_allowed_lan_ip(value) for value in addresses):
            raise CameraSourceError("lan_origin_required")
        pinned = min(addresses, key=lambda value: (ipaddress.ip_address(value).version, value))
        return parsed.scheme, host, pinned, port

    def _authorization_header(self) -> str | None:
        if not self.config.credential_ref:
            return None
        result = self._secret_broker.inject(self.config.credential_ref, approved=True)
        if result["blocked"] or result["injected"] == []:
            raise CameraSourceError("credential_unavailable")
        value = result["text"]
        if not isinstance(value, str) or not value or "\r" in value or "\n" in value:
            raise CameraSourceError("credential_unavailable")
        return f"Bearer {value}"

    async def request_bytes(
        self,
        path: str,
        *,
        params: Mapping[str, str | int | float] | None,
        max_bytes: int,
    ) -> bytes:
        if (
            not isinstance(path, str)
            or not path.startswith("/api/")
            or ".." in path
            or not re.fullmatch(r"/[A-Za-z0-9_./:-]+", path)
        ):
            raise CameraSourceError("source_path_invalid")
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
            raise ValueError("max_bytes must be positive")

        last_transport_error: httpx.TransportError | None = None
        for attempt in range(self._max_attempts):
            self._preflight()
            try:
                scheme, host, pinned, port = await self._resolve_pinned()
            except CameraSourceError as exc:
                if str(exc) == "source_offline" and attempt + 1 < self._max_attempts:
                    await self._pause(0.1 * (2**attempt))
                    continue
                raise
            ip_host = f"[{pinned}]" if ":" in pinned else pinned
            query = urlencode(params or {}, doseq=False)
            url = urlunsplit((scheme, f"{ip_host}:{port}", path, query, ""))
            host_header = f"{host}:{port}"
            headers = {
                "Accept": "application/json, image/jpeg, image/png",
                "Accept-Encoding": "identity",
                "Host": host_header,
            }
            authorization = self._authorization_header()
            if authorization is not None:
                headers["Authorization"] = authorization
            timeout = httpx.Timeout(
                connect=float(self.config.connect_timeout_seconds),
                read=float(self.config.read_timeout_seconds),
                write=float(self.config.connect_timeout_seconds),
                pool=float(self.config.connect_timeout_seconds),
            )
            try:
                async with httpx.AsyncClient(
                    follow_redirects=False,
                    timeout=timeout,
                    transport=self._transport,
                ) as client, client.stream(
                        "GET",
                        url,
                        headers=headers,
                        extensions={"sni_hostname": host},
                ) as response:
                    if response.is_redirect:
                        raise CameraSourceError("redirect_refused")
                    encoding = response.headers.get("content-encoding", "identity").lower()
                    if encoding not in {"", "identity"}:
                        raise CameraSourceError("content_encoding_refused")
                    if response.status_code != 200:
                        raise CameraSourceError(f"source_http_{response.status_code}")
                    declared = response.headers.get("content-length")
                    if declared is not None:
                        try:
                            declared_bytes = int(declared)
                        except ValueError as exc:
                            raise CameraSourceError("response_length_invalid") from exc
                        if declared_bytes < 0 or declared_bytes > max_bytes:
                            raise CameraSourceError("response_too_large")
                    chunks: list[bytes] = []
                    received = 0
                    if response.is_stream_consumed:
                        # Mock/in-process transports may legally return a preloaded response.
                        # Apply the same post-read bound; live transports take the streaming path.
                        received = len(response.content)
                        if received > max_bytes:
                            raise CameraSourceError("response_too_large")
                        chunks.append(bytes(response.content))
                    else:
                        async for chunk in response.aiter_raw():
                            received += len(chunk)
                            if received > max_bytes:
                                raise CameraSourceError("response_too_large")
                            chunks.append(bytes(chunk))
                    return b"".join(chunks)
            except CameraSourceError:
                raise
            except httpx.TransportError as exc:
                last_transport_error = exc
                if attempt + 1 < self._max_attempts:
                    await self._pause(0.1 * (2**attempt))

        raise CameraSourceError("source_offline") from last_transport_error

    async def _pause(self, seconds: float) -> None:
        pause = self._sleep(seconds)
        if inspect.isawaitable(pause):
            await pause


class FrigateEventSource:
    """Read-only Frigate metadata source. Snapshot bytes are deliberately absent."""

    def __init__(
        self,
        *,
        config: FrigateConfig,
        secret_broker: SecretBroker,
        poll_gate: PollGate | None,
        kill_switch: Any,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: Resolver | None = None,
        sleep: Sleeper | None = None,
        max_event_bytes: int = 1024 * 1024,
        max_attempts: int = 2,
    ) -> None:
        if not isinstance(config, FrigateConfig):
            raise ValueError("config must be FrigateConfig")
        if poll_gate is not None and not callable(poll_gate):
            raise ValueError("poll_gate must be callable")
        if (
            isinstance(max_event_bytes, bool)
            or not isinstance(max_event_bytes, int)
            or not 1 <= max_event_bytes <= 8 * 1024 * 1024
        ):
            raise ValueError("max_event_bytes must be between 1 byte and 8 MiB")
        self._poll_gate = poll_gate
        self._max_event_bytes = max_event_bytes
        self._http = _FrigateHTTP(
            config=config,
            secret_broker=secret_broker,
            kill_switch=kill_switch,
            transport=transport,
            resolver=resolver,
            sleep=sleep,
            max_attempts=max_attempts,
        )
        self._health_lock = threading.Lock()
        self._health = CameraSourceHealth(status="disabled", camera_count=0)

    async def list_events(self, after: str | None, limit: int) -> CameraEventPage:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= _MAX_EVENTS:
            raise ValueError("camera event limit must be between 1 and 100")
        self._http._preflight()
        if self._poll_gate is None:
            raise CameraSourceError("poll_gate_required")
        permission, cameras = self._poll_permission(initial=True)
        cursor = _cursor_decode(after)
        params: dict[str, str | int | float] = {
            "cameras": ",".join(cameras),
            "limit": min(_MAX_SOURCE_ITEMS, max(limit * 2, limit)),
        }
        if cursor is not None:
            params["after"] = cursor[0]
        try:
            encoded = await self._http.request_bytes(
                "/api/events",
                params=params,
                max_bytes=self._max_event_bytes,
            )
            self._http._preflight()
            current_permission, current_cameras = self._poll_permission(initial=False)
            if current_permission != permission or current_cameras != cameras:
                raise CameraSourceError("stale_consent_generation")
            payload = json.loads(encoded)
            if not isinstance(payload, list) or len(payload) > _MAX_SOURCE_ITEMS:
                raise CameraSourceError("event_payload_invalid")
            events: dict[str, CameraEvent] = {}
            for item in payload:
                event = _normalize_event(item, allowed_cameras=frozenset(cameras))
                if event is None:
                    continue
                if cursor is not None and (event.occurred_at, event.event_id) <= cursor:
                    continue
                events[event.event_id] = event
            ordered = tuple(
                sorted(events.values(), key=lambda event: (event.occurred_at, event.event_id))[:limit]
            )
            next_cursor = _cursor_encode(ordered[-1]) if ordered else after
            self._set_health("online", len(cameras), last_error=None, succeeded=True)
            return CameraEventPage(events=ordered, next_cursor=next_cursor)
        except CameraSourceError as exc:
            status = "offline" if str(exc) == "source_offline" else "degraded"
            self._set_health(status, len(cameras), last_error=str(exc), succeeded=False)
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            self._set_health("degraded", len(cameras), last_error="event_payload_invalid", succeeded=False)
            raise CameraSourceError("event_payload_invalid") from exc

    def _poll_permission(
        self,
        *,
        initial: bool,
    ) -> tuple[PrivacyPollingGrant, tuple[str, ...]]:
        if self._poll_gate is None:
            raise CameraSourceError("poll_gate_required")
        try:
            value = self._poll_gate()
        except Exception as exc:
            reason = "consent_required" if initial else "stale_consent_generation"
            raise CameraSourceError(reason) from exc
        if not isinstance(value, PrivacyPollingGrant):
            reason = "consent_required" if initial else "stale_consent_generation"
            raise CameraSourceError(reason)
        permission = value
        cameras = value.camera_ids
        if (
            not cameras
            or len(cameras) > 128
            or any(_CAMERA_ID_RE.fullmatch(item) is None for item in cameras)
        ):
            reason = "consent_required" if initial else "stale_consent_generation"
            raise CameraSourceError(reason)
        return permission, cameras

    def health(self) -> CameraSourceHealth:
        with self._health_lock:
            return self._health

    def _set_health(
        self,
        status: str,
        camera_count: int,
        *,
        last_error: str | None,
        succeeded: bool,
    ) -> None:
        with self._health_lock:
            self._health = CameraSourceHealth(
                status=status,
                camera_count=camera_count,
                last_success_at=time.time() if succeeded else self._health.last_success_at,
                last_error=last_error,
            )


def _normalize_event(
    payload: object,
    *,
    allowed_cameras: frozenset[str],
) -> CameraEvent | None:
    if not isinstance(payload, Mapping):
        return None
    camera_id = payload.get("camera")
    if not isinstance(camera_id, str) or camera_id not in allowed_cameras:
        return None
    label_value = payload.get("label")
    if not isinstance(label_value, str):
        return None
    label = _LABEL_MAP.get(label_value.strip().lower())
    if label is None:
        return None
    data = payload.get("data")
    safe_data = data if isinstance(data, Mapping) else {}
    zones = safe_data.get("zones") or safe_data.get("current_zones") or safe_data.get("entered_zones")
    zone: str | None = None
    if isinstance(zones, list):
        safe_zones = sorted(
            {
                value.strip()
                for value in zones[:32]
                if isinstance(value, str) and 0 < len(value.strip()) <= 64
            }
        )
        zone = safe_zones[0] if safe_zones else None
    confidence = safe_data.get("top_score", safe_data.get("score", 0.0))
    event_payload = {
        "event_id": payload.get("id"),
        "camera_id": camera_id,
        "label": label,
        "occurred_at": payload.get("start_time"),
        "confidence": confidence,
        "zone": zone,
    }
    try:
        return CameraEvent.from_payload(event_payload)
    except ValueError:
        return None


class _FrigateSnapshotSource:
    """Private raw-byte seam owned only by the consent-bound privacy pipeline."""

    def __init__(self, *, http: _FrigateHTTP, privacy_policy: CameraPrivacyPolicy) -> None:
        if not isinstance(http, _FrigateHTTP) or not isinstance(privacy_policy, CameraPrivacyPolicy):
            raise ValueError("snapshot source requires private Frigate HTTP and privacy policy")
        self._http = http
        self._privacy_policy = privacy_policy

    async def fetch_masked(self, lease: PrivacyLease, event_id: str) -> MaskedFrame:
        if not isinstance(event_id, str) or _EVENT_ID_RE.fullmatch(event_id) is None:
            raise CameraSourceError("event_id_invalid")
        self._privacy_policy.recheck(lease, "fetch")
        raw = await self._http.request_bytes(
            f"/api/events/{event_id}/snapshot.jpg",
            params=None,
            max_bytes=_MAX_SNAPSHOT_BYTES,
        )
        return self._privacy_policy.mask_frame(lease, raw)
