"""Optional LAN-only ONVIF discovery for owner-curated Frigate onboarding."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import ipaddress
import math
import re
import socket
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

_DEVICE_KEY_RE = re.compile(r"^[a-f0-9]{24}$")
_CAMERA_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_SECRET_REF_RE = re.compile(r"^\{\{secret:[A-Za-z0-9_.-]+\}\}$")
_MAX_RAW_RESULTS = 128

Resolver = Callable[[str, int], Sequence[str]]
Discoverer = Callable[[], object | Awaitable[object]]


class OnvifDiscoveryError(RuntimeError):
    """Stable policy refusal before discovery starts."""


def _normalize_host(host: str) -> str:
    if not isinstance(host, str):
        raise ValueError("ONVIF device host is invalid")
    normalized = host.strip().lower().rstrip(".")
    try:
        ipaddress.ip_address(normalized)
        valid = "%" not in normalized
    except ValueError:
        labels = normalized.split(".")
        valid = bool(
            labels
            and all(
                re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in labels
            )
        )
    if not valid or len(normalized) > 253:
        raise ValueError("ONVIF device host is invalid")
    return normalized


def onvif_device_key(host: str, port: int) -> str:
    normalized_host = _normalize_host(host)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("ONVIF device port is invalid")
    normalized = f"{normalized_host}:{port}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class OnvifCameraMapping:
    """Owner-curated bridge from one discovered device to an existing Frigate camera id."""

    device_key: str
    frigate_camera_id: str
    credential_ref: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.device_key, str) or _DEVICE_KEY_RE.fullmatch(self.device_key) is None:
            raise ValueError("ONVIF device key is invalid")
        if (
            not isinstance(self.frigate_camera_id, str)
            or _CAMERA_ID_RE.fullmatch(self.frigate_camera_id) is None
        ):
            raise ValueError("Frigate camera id is invalid")
        if self.credential_ref and _SECRET_REF_RE.fullmatch(self.credential_ref) is None:
            raise ValueError("ONVIF credential must be a SecretBroker reference")


@dataclass(frozen=True, slots=True)
class OnvifDiscoveryConfig:
    enabled: bool = False
    mappings: tuple[OnvifCameraMapping, ...] = ()
    max_results: int = 32
    timeout_seconds: float = 2.0

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("ONVIF enabled must be a boolean")
        if not isinstance(self.mappings, (tuple, list)) or len(self.mappings) > 128:
            raise ValueError("ONVIF mappings must be bounded")
        mappings = tuple(self.mappings)
        if any(not isinstance(mapping, OnvifCameraMapping) for mapping in mappings):
            raise ValueError("ONVIF mappings must contain OnvifCameraMapping values")
        keys = [mapping.device_key for mapping in mappings]
        camera_ids = [mapping.frigate_camera_id for mapping in mappings]
        if len(keys) != len(set(keys)) or len(camera_ids) != len(set(camera_ids)):
            raise ValueError("ONVIF mappings must be one-to-one")
        object.__setattr__(self, "mappings", mappings)
        if (
            isinstance(self.max_results, bool)
            or not isinstance(self.max_results, int)
            or not 1 <= self.max_results <= 64
        ):
            raise ValueError("ONVIF max_results must be between 1 and 64")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(float(self.timeout_seconds))
            or not 0.01 <= float(self.timeout_seconds) <= 10.0
        ):
            raise ValueError("ONVIF timeout must be between 0.01 and 10 seconds")


@dataclass(frozen=True, slots=True)
class OnvifDevice:
    device_id: str
    name: str
    host: str
    port: int
    secure: bool
    frigate_camera_id: str | None = None

    def to_public(self) -> dict[str, str | int | bool | None]:
        return {
            "device_id": self.device_id,
            "name": self.name,
            "host": self.host,
            "port": self.port,
            "secure": self.secure,
            "mapped": self.frigate_camera_id is not None,
            "frigate_camera_id": self.frigate_camera_id,
        }


@dataclass(frozen=True, slots=True)
class OnvifDiscoveryResult:
    status: str
    devices: tuple[OnvifDevice, ...]
    reason: str | None = None

    def to_public(self) -> dict[str, object]:
        return {
            "status": self.status,
            "reason": self.reason,
            "devices": [device.to_public() for device in self.devices],
        }


def _default_resolver(host: str, port: int) -> tuple[str, ...]:
    return tuple({entry[4][0] for entry in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})


def _is_lan_address(value: str) -> bool:
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
        and str(address) not in {"100.100.100.200", "169.254.169.254"}
    )


def _resolve_addresses(resolver: Resolver, host: str, port: int) -> tuple[str, ...]:
    try:
        return tuple(str(value) for value in resolver(host, port))
    except Exception:
        return ()


def _safe_name(value: object, device_id: str) -> str:
    if not isinstance(value, str):
        return f"ONVIF camera {device_id[:8]}"
    name = unquote(value).strip()
    if (
        not 1 <= len(name) <= 96
        or any(ord(character) < 32 for character in name)
        or "://" in name
        or "@" in name
    ):
        return f"ONVIF camera {device_id[:8]}"
    return name


class OnvifDiscoveryService:
    """Admin-gated WS-Discovery only; it has no stream/control methods."""

    def __init__(
        self,
        *,
        config: OnvifDiscoveryConfig,
        admin_gate: Callable[[], bool],
        discoverer: Discoverer | None = None,
        resolver: Resolver | None = None,
    ) -> None:
        if not isinstance(config, OnvifDiscoveryConfig):
            raise ValueError("config must be OnvifDiscoveryConfig")
        if not callable(admin_gate):
            raise ValueError("admin_gate must be callable")
        if discoverer is not None and not callable(discoverer):
            raise ValueError("discoverer must be callable")
        self._config = config
        self._admin_gate = admin_gate
        self._discoverer = discoverer
        self._resolver = resolver or _default_resolver
        self._mapping = {mapping.device_key: mapping for mapping in config.mappings}

    async def discover(self) -> OnvifDiscoveryResult:
        if not self._config.enabled:
            raise OnvifDiscoveryError("discovery_disabled")
        try:
            allowed = self._admin_gate()
        except Exception as exc:
            raise OnvifDiscoveryError("admin_required") from exc
        if allowed is not True:
            raise OnvifDiscoveryError("admin_required")

        discoverer = self._discoverer or self._load_default_discoverer()
        if discoverer is None:
            return OnvifDiscoveryResult(
                status="unavailable",
                devices=(),
                reason="onvif_dependency_missing",
            )
        try:
            payload = await asyncio.wait_for(
                self._invoke(discoverer),
                timeout=float(self._config.timeout_seconds),
            )
        except TimeoutError:
            return OnvifDiscoveryResult(status="degraded", devices=(), reason="discovery_timeout")
        except Exception:
            return OnvifDiscoveryResult(status="degraded", devices=(), reason="discovery_failed")

        if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
            return OnvifDiscoveryResult(
                status="degraded",
                devices=(),
                reason="discovery_payload_invalid",
            )
        if len(payload) > _MAX_RAW_RESULTS:
            return OnvifDiscoveryResult(
                status="degraded",
                devices=(),
                reason="discovery_payload_too_large",
            )

        devices: dict[str, OnvifDevice] = {}
        for value in payload:
            device = self._normalize(value)
            if device is None:
                continue
            previous = devices.get(device.device_id)
            if previous is None or device.name < previous.name:
                devices[device.device_id] = device
        ordered = tuple(
            sorted(devices.values(), key=lambda item: (item.host, item.port, item.device_id))[
                : self._config.max_results
            ]
        )
        return OnvifDiscoveryResult(status="online", devices=ordered)

    async def _invoke(self, discoverer: Discoverer) -> object:
        if inspect.iscoroutinefunction(discoverer):
            return await discoverer()
        result = await asyncio.to_thread(discoverer)
        return await result if inspect.isawaitable(result) else result

    def _normalize(self, payload: object) -> OnvifDevice | None:
        if not isinstance(payload, Mapping):
            return None
        xaddrs = payload.get("xaddrs")
        if isinstance(xaddrs, str):
            candidates = (xaddrs,)
        elif isinstance(xaddrs, Sequence) and not isinstance(xaddrs, (str, bytes)):
            candidates = tuple(xaddrs[:8])
        else:
            return None
        for candidate in candidates:
            if not isinstance(candidate, str) or len(candidate) > 512:
                continue
            try:
                parsed = urlsplit(candidate.strip())
                port = parsed.port or (443 if parsed.scheme == "https" else 80)
                host = _normalize_host(parsed.hostname or "")
            except ValueError:
                continue
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
            ):
                continue
            addresses = _resolve_addresses(self._resolver, host, port)
            if not addresses or any(not _is_lan_address(value) for value in addresses):
                continue
            device_id = onvif_device_key(host, port)
            mapping = self._mapping.get(device_id)
            return OnvifDevice(
                device_id=device_id,
                name=_safe_name(payload.get("name"), device_id),
                host=host,
                port=port,
                secure=parsed.scheme == "https",
                frigate_camera_id=(mapping.frigate_camera_id if mapping is not None else None),
            )
        return None

    def _load_default_discoverer(self) -> Discoverer | None:
        try:
            from wsdiscovery.discovery import ThreadedWSDiscovery
        except ImportError:
            return None

        timeout = float(self._config.timeout_seconds)

        def _discover() -> list[dict[str, object]]:
            discovery = ThreadedWSDiscovery()
            discovery.start()
            try:
                services = discovery.searchServices(timeout=timeout)
                results: list[dict[str, object]] = []
                for service in list(services)[:_MAX_RAW_RESULTS]:
                    xaddrs = list(service.getXAddrs() or ())
                    scopes = [str(scope) for scope in list(service.getScopes() or ())[:32]]
                    name = next(
                        (
                            scope.rsplit("/", 1)[-1]
                            for scope in scopes
                            if "/name/" in scope.lower()
                        ),
                        "",
                    )
                    results.append({"xaddrs": xaddrs[:8], "name": name})
                return results
            finally:
                discovery.stop()

        return _discover
