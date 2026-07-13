"""Strict-local, read-first Home Assistant REST/WebSocket adapter (H30.1)."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import ipaddress
import json
import os
import re
import socket
import time
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlparse, urlunparse

from agents.core.env_config import truthy

from .contracts import HouseArea, HouseEntity, HouseEvent, HouseSnapshot

_MAX_ENTITIES = 2_000
_MAX_EVENTS = 1_000
_MAX_FRAME_BYTES = 65_536
_MAX_SEEN = 4_096
_MAX_STATE = 256
_REQUEST_TIMEOUT = 8.0
_SECRET_HANDLE = re.compile(r"\{\{\s*secret:([A-Za-z0-9_.\-]+)\s*\}\}")
_ALLOWED_ENTITY_ATTRIBUTES = ("device_class", "unit_of_measurement")
_LAN_V4 = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
)
_LAN_V6 = (
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


class HAConfigError(ValueError):
    """The owner configuration cannot safely identify one LAN HA origin."""


class _AdapterError(RuntimeError):
    pass


class _AuthError(_AdapterError):
    pass


class _Cancelled(_AdapterError):
    pass


@dataclass(frozen=True)
class HAConfig:
    enabled: bool = False
    ha_enabled: bool = False
    base_url: str = ""
    token_ref: str = ""
    allowed_hosts: tuple[str, ...] = ()


def _setting(settings: Mapping[str, Any], key: str, default: Any = None) -> Any:
    return settings.get(key, default) if isinstance(settings, Mapping) else default


def _env_or_setting(
    env: Mapping[str, Any],
    env_key: str,
    settings: Mapping[str, Any],
    setting_key: str,
    default: Any,
) -> Any:
    if env_key in env:
        return env.get(env_key)
    return _setting(settings, setting_key, default)


def _resolve(host: str, port: int, resolver=None) -> list[str]:
    if resolver is not None:
        values = resolver(host, port)
        return [str(value).split("%", 1)[0] for value in values]
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        return [str(literal)]
    records = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
    return sorted({str(record[4][0]).split("%", 1)[0] for record in records})


def _is_lan_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    networks = _LAN_V4 if isinstance(address, ipaddress.IPv4Address) else _LAN_V6
    return any(address in network for network in networks)


def _validated_origin(
    url: str, *, allowed_hosts: tuple[str, ...], resolver=None
) -> tuple[str, tuple[str, ...]]:
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError as exc:
        raise HAConfigError("Home Assistant URL is invalid") from exc
    if parsed.scheme.lower() not in {"http", "https"}:
        raise HAConfigError("Home Assistant URL must use http(s)")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HAConfigError("Home Assistant URL cannot contain credentials, query, or fragment")
    if parsed.path not in {"", "/"}:
        raise HAConfigError("Home Assistant URL must identify an origin, not a path")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise HAConfigError("Home Assistant URL requires a host")
    if allowed_hosts and host not in allowed_hosts:
        raise HAConfigError("Home Assistant host is not owner-allowlisted")
    if not allowed_hosts and host != "localhost" and not host.endswith(".local"):
        try:
            literal = ipaddress.ip_address(host)
        except ValueError as exc:
            raise HAConfigError("Home Assistant host requires an explicit allowlist") from exc
        if not _is_lan_address(str(literal)):
            raise HAConfigError("Home Assistant host must stay on the LAN")
    try:
        addresses = _resolve(host, port or (443 if parsed.scheme == "https" else 80), resolver)
    except Exception as exc:
        raise HAConfigError("Home Assistant host could not be resolved") from exc
    if not addresses or any(not _is_lan_address(address) for address in addresses):
        raise HAConfigError("Home Assistant origin must resolve only to LAN addresses")
    netloc = parsed.netloc.lower().rstrip(".")
    origin = urlunparse((parsed.scheme.lower(), netloc, "", "", "", "")).rstrip("/")
    return origin, tuple(sorted(set(addresses)))


def _validate_origin(url: str, *, allowed_hosts: tuple[str, ...], resolver=None) -> str:
    origin, _addresses = _validated_origin(url, allowed_hosts=allowed_hosts, resolver=resolver)
    return origin


def load_ha_config(
    *,
    env: Mapping[str, Any] | None = None,
    settings: Mapping[str, Any] | None = None,
    resolver=None,
) -> HAConfig:
    """Load config with explicit env > settings precedence; product posture is ignored."""
    env_values = os.environ if env is None else env
    setting_values = settings or {}
    enabled = truthy(
        _env_or_setting(env_values, "JARVIS_HOUSE_BRAIN", setting_values, "house.enabled", False)
    )
    ha_enabled = truthy(
        _env_or_setting(
            env_values, "JARVIS_HOME_ASSISTANT", setting_values, "house.ha_enabled", False
        )
    )
    if not enabled or not ha_enabled:
        return HAConfig(enabled=enabled, ha_enabled=ha_enabled)
    base_url = str(
        _env_or_setting(env_values, "JARVIS_HA_URL", setting_values, "house.ha_url", "") or ""
    ).strip()
    token_ref = str(
        _env_or_setting(env_values, "JARVIS_HA_TOKEN_REF", setting_values, "house.ha_token_ref", "")
        or ""
    ).strip()
    raw_hosts = _env_or_setting(
        env_values, "JARVIS_HA_ALLOWED_HOSTS", setting_values, "house.ha_allowed_hosts", ""
    )
    if isinstance(raw_hosts, str):
        hosts = tuple(
            sorted(
                {part.strip().lower().rstrip(".") for part in raw_hosts.split(",") if part.strip()}
            )
        )
    elif isinstance(raw_hosts, (tuple, list)):
        hosts = tuple(
            sorted(
                {str(part).strip().lower().rstrip(".") for part in raw_hosts if str(part).strip()}
            )
        )
    else:
        raise HAConfigError("Home Assistant allowlist is invalid")
    if not base_url:
        raise HAConfigError("Home Assistant URL is required")
    if not _SECRET_HANDLE.fullmatch(token_ref):
        raise HAConfigError("Home Assistant credential must be a SecretBroker secret handle")
    normalized_url = _validate_origin(base_url, allowed_hosts=hosts, resolver=resolver)
    return HAConfig(
        enabled=True,
        ha_enabled=True,
        base_url=normalized_url,
        token_ref=token_ref,
        allowed_hosts=hosts,
    )


class _HttpxREST:
    async def request(self, method: str, url: str, **kwargs):  # pragma: no cover - host seam
        import httpx

        async with httpx.AsyncClient(follow_redirects=False, trust_env=False) as client:
            return await client.request(method, url, **kwargs)


class _WebsocketsTransport:
    async def connect(self, url: str, **kwargs):  # pragma: no cover - host seam
        import websockets

        return await websockets.connect(url, **kwargs)


def _timestamp(value: object) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(0.0, float(value))
    if not isinstance(value, str) or not value.strip():
        raise _AdapterError("invalid_timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        timestamp = parsed.timestamp()
    except (OverflowError, ValueError) as exc:
        raise _AdapterError("invalid_timestamp") from exc
    if timestamp < 0:
        raise _AdapterError("invalid_timestamp")
    return timestamp


def _bounded_state(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > _MAX_STATE:
        raise _AdapterError("invalid_state")
    return value.strip()


def _normalize_entity(raw: object) -> tuple[HouseEntity, HouseArea | None]:
    if not isinstance(raw, Mapping):
        raise _AdapterError("invalid_entity")
    entity_id = raw.get("entity_id")
    if not isinstance(entity_id, str) or "." not in entity_id:
        raise _AdapterError("invalid_entity")
    domain = entity_id.split(".", 1)[0]
    state = _bounded_state(raw.get("state"))
    attrs = raw.get("attributes") or {}
    if not isinstance(attrs, Mapping):
        raise _AdapterError("invalid_entity")
    name = attrs.get("friendly_name") or entity_id
    area_id = attrs.get("area_id") or ""
    area_name = attrs.get("area_name") or area_id
    safe_attrs = []
    for key in _ALLOWED_ENTITY_ATTRIBUTES:
        value = attrs.get(key)
        if value is not None and isinstance(value, (str, int, float, bool)):
            safe_attrs.append((key, str(value)[:256]))
    entity = HouseEntity(
        entity_id=entity_id,
        domain=domain,
        name=str(name),
        state=state,
        area_id=str(area_id),
        updated_at=_timestamp(raw.get("last_updated")),
        attributes=tuple(safe_attrs),
    )
    area = HouseArea(area_id=str(area_id), name=str(area_name)) if area_id else None
    return entity, area


class HomeAssistantAdapter:
    def __init__(
        self,
        *,
        env: Mapping[str, Any] | None = None,
        settings: Mapping[str, Any] | None = None,
        resolver=None,
        rest=None,
        websocket=None,
        secret_broker=None,
        clock=None,
        sleep=None,
    ) -> None:
        self._env = os.environ if env is None else env
        self._settings = settings or {}
        self._resolver = resolver
        self._config_error = ""
        try:
            self.config = load_ha_config(
                env=self._env, settings=self._settings, resolver=self._resolver
            )
        except HAConfigError:
            self.config = HAConfig(
                enabled=truthy(
                    _env_or_setting(
                        self._env,
                        "JARVIS_HOUSE_BRAIN",
                        self._settings,
                        "house.enabled",
                        False,
                    )
                ),
                ha_enabled=truthy(
                    _env_or_setting(
                        self._env,
                        "JARVIS_HOME_ASSISTANT",
                        self._settings,
                        "house.ha_enabled",
                        False,
                    )
                ),
            )
            self._config_error = "configuration_invalid"
        self._rest = rest or _HttpxREST()
        self._websocket = websocket or _WebsocketsTransport()
        self._secrets = secret_broker
        self._clock = clock or time.time
        self._sleep = sleep or asyncio.sleep
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._last_entity_time: dict[str, float] = {}
        self._health = {"status": "disabled", "reason": "house_brain_disabled"}

    def _runtime_endpoint(self) -> tuple[str, str, str, int]:
        try:
            origin, addresses = _validated_origin(
                self.config.base_url,
                allowed_hosts=self.config.allowed_hosts,
                resolver=self._resolver,
            )
        except HAConfigError as exc:
            raise _AdapterError("origin_validation_failed") from exc
        parsed = urlparse(origin)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return origin, addresses[0], host, port

    def _token(self) -> str:
        if self._secrets is None:
            raise _AuthError("credential_unavailable")
        try:
            result = self._secrets.inject(self.config.token_ref, approved=True)
        except Exception as exc:
            raise _AuthError("credential_unavailable") from exc
        match = _SECRET_HANDLE.fullmatch(self.config.token_ref)
        if (
            not isinstance(result, Mapping)
            or match is None
            or result.get("blocked")
            or result.get("injected") != [match.group(1)]
        ):
            raise _AuthError("credential_unavailable")
        token = result.get("text")
        if not isinstance(token, str) or not token or len(token) > 8_192:
            raise _AuthError("credential_unavailable")
        return token

    def _snapshot(self, *, status: str, reason: str = "", areas=(), entities=()) -> HouseSnapshot:
        return HouseSnapshot(
            enabled=self.config.enabled and self.config.ha_enabled,
            status=status,
            observed_at=float(self._clock()),
            areas=tuple(areas),
            entities=tuple(entities),
            reason=reason,
        )

    async def snapshot(self) -> HouseSnapshot:
        if not self.config.enabled or not self.config.ha_enabled:
            self._health = {"status": "disabled", "reason": "house_brain_disabled"}
            return self._snapshot(status="disabled", reason="house_brain_disabled")
        if self._config_error:
            self._health = {"status": "degraded", "reason": self._config_error}
            return self._snapshot(status="degraded", reason=self._config_error)
        try:
            origin, pinned_ip, host, port = self._runtime_endpoint()
            parsed_origin = urlparse(origin)
            ip_host = f"[{pinned_ip}]" if ":" in pinned_ip else pinned_ip
            explicit_port = f":{parsed_origin.port}" if parsed_origin.port else ""
            pinned_origin = urlunparse(
                (parsed_origin.scheme, f"{ip_host}{explicit_port}", "", "", "", "")
            )
            host_header = f"{host}:{parsed_origin.port}" if parsed_origin.port else host
            token = self._token()
            response = await self._rest.request(
                "GET",
                f"{pinned_origin}/api/states",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Host": host_header,
                },
                timeout=_REQUEST_TIMEOUT,
                follow_redirects=False,
                extensions={"sni_hostname": host},
            )
            status = int(getattr(response, "status_code", 0))
            if 300 <= status < 400:
                raise _AdapterError("redirect_refused")
            if status != 200:
                raise _AdapterError("rest_http_error")
            final_url = str(getattr(response, "url", "") or "")
            if final_url and (urlparse(final_url).hostname or "").lower().rstrip(".") != pinned_ip:
                raise _AdapterError("cross_host_response_refused")
            payload = response.json()
            if not isinstance(payload, list) or len(payload) > _MAX_ENTITIES:
                raise _AdapterError("invalid_states_payload")
            entities = []
            area_map = {}
            for raw in payload:
                entity, area = _normalize_entity(raw)
                entities.append(entity)
                if area is not None:
                    area_map[area.area_id] = area
            entities.sort(key=lambda item: item.entity_id)
            areas = sorted(area_map.values(), key=lambda item: item.area_id)
            self._health = {"status": "live", "reason": ""}
            return self._snapshot(status="live", areas=areas, entities=entities)
        except TimeoutError:
            reason = "rest_timeout"
        except _AdapterError as exc:
            reason = str(exc)[:256]
        except Exception:
            reason = "rest_unavailable"
        self._health = {"status": "degraded", "reason": reason}
        return self._snapshot(status="degraded", reason=reason)

    async def _recv(self, connection, stop_event: asyncio.Event | None):
        if stop_event is None:
            return await connection.recv()
        if stop_event.is_set():
            raise _Cancelled("cancelled")
        recv_task = asyncio.create_task(connection.recv())
        stop_task = asyncio.create_task(stop_event.wait())
        done, pending = await asyncio.wait(
            {recv_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        if stop_task in done and stop_task.result():
            recv_task.cancel()
            raise _Cancelled("cancelled")
        return recv_task.result()

    async def _frame(self, connection, stop_event: asyncio.Event | None) -> dict:
        raw = await self._recv(connection, stop_event)
        if isinstance(raw, bytes):
            if len(raw) > _MAX_FRAME_BYTES:
                raise _AdapterError("websocket_frame_too_large")
            try:
                raw = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise _AdapterError("websocket_frame_invalid") from exc
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > _MAX_FRAME_BYTES:
            raise _AdapterError("websocket_frame_too_large")
        try:
            frame = json.loads(raw)
        except ValueError as exc:
            raise _AdapterError("websocket_frame_invalid") from exc
        if not isinstance(frame, dict):
            raise _AdapterError("websocket_frame_invalid")
        return frame

    async def _authenticate(self, connection, token: str, stop_event) -> None:
        required = await self._frame(connection, stop_event)
        if required.get("type") != "auth_required":
            raise _AuthError("websocket_auth_protocol_invalid")
        await connection.send(
            json.dumps({"type": "auth", "access_token": token}, separators=(",", ":"))
        )
        auth = await self._frame(connection, stop_event)
        if auth.get("type") != "auth_ok":
            raise _AuthError("websocket_auth_refused")
        await connection.send(
            json.dumps(
                {"id": 1, "type": "subscribe_events", "event_type": "state_changed"},
                separators=(",", ":"),
            )
        )
        subscribed = await self._frame(connection, stop_event)
        if (
            subscribed.get("id") != 1
            or subscribed.get("type") != "result"
            or subscribed.get("success") is not True
        ):
            raise _AuthError("websocket_subscription_refused")

    def _event_from_frame(self, frame: Mapping[str, Any]) -> HouseEvent | None:
        if frame.get("type") != "event" or not isinstance(frame.get("event"), Mapping):
            return None
        event = frame["event"]
        if event.get("event_type") != "state_changed" or not isinstance(event.get("data"), Mapping):
            return None
        data = event["data"]
        entity_id = data.get("entity_id")
        new_state = data.get("new_state")
        old_state = data.get("old_state")
        if not isinstance(entity_id, str) or not isinstance(new_state, Mapping):
            return None
        current = _bounded_state(new_state.get("state"))
        previous = ""
        if isinstance(old_state, Mapping) and old_state.get("state") is not None:
            previous = _bounded_state(old_state.get("state"))
        occurred_at = _timestamp(event.get("time_fired"))
        last = self._last_entity_time.get(entity_id)
        if last is not None and occurred_at <= last:
            return None
        source = f"{entity_id}|{occurred_at:.6f}|{previous}|{current}"
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        dedupe_key = f"ha:{digest[:48]}"
        if dedupe_key in self._seen:
            return None
        self._seen[dedupe_key] = None
        self._seen.move_to_end(dedupe_key)
        while len(self._seen) > _MAX_SEEN:
            self._seen.popitem(last=False)
        self._last_entity_time[entity_id] = occurred_at
        return HouseEvent(
            event_id=f"he-{digest[:24]}",
            source_event_id=digest[:32],
            entity_id=entity_id,
            event_type="state_changed",
            previous_state=previous,
            current_state=current,
            occurred_at=occurred_at,
            observed_at=float(self._clock()),
            dedupe_key=dedupe_key,
        )

    async def collect_events(
        self,
        *,
        limit: int = 100,
        reconnect_attempts: int = 3,
        stop_event: asyncio.Event | None = None,
    ) -> list[HouseEvent]:
        """Collect a bounded batch while exercising HA auth/subscription/reconnect semantics."""
        if (
            not self.config.enabled
            or not self.config.ha_enabled
            or self._config_error
            or (stop_event and stop_event.is_set())
        ):
            return []
        bounded_limit = max(1, min(int(limit), _MAX_EVENTS))
        attempts = max(1, min(int(reconnect_attempts), 8))
        output: list[HouseEvent] = []
        for attempt in range(attempts):
            if stop_event and stop_event.is_set():
                break
            connection = None
            try:
                origin, pinned_ip, _host, port = self._runtime_endpoint()
                parsed = urlparse(origin)
                ws_scheme = "wss" if parsed.scheme == "https" else "ws"
                ws_url = urlunparse((ws_scheme, parsed.netloc, "/api/websocket", "", "", ""))
                connection = await self._websocket.connect(
                    ws_url,
                    host=pinned_ip,
                    port=port,
                    max_size=_MAX_FRAME_BYTES,
                    max_queue=16,
                    open_timeout=_REQUEST_TIMEOUT,
                    close_timeout=5.0,
                    proxy=None,
                )
                await self._authenticate(connection, self._token(), stop_event)
                while len(output) < bounded_limit:
                    frame = await self._frame(connection, stop_event)
                    event = self._event_from_frame(frame)
                    if event is not None:
                        output.append(event)
                self._health = {"status": "live", "reason": ""}
                return output
            except _Cancelled:
                break
            except _AuthError as exc:
                self._health = {"status": "degraded", "reason": str(exc)[:256]}
                break
            except Exception:
                self._health = {"status": "degraded", "reason": "websocket_unavailable"}
            finally:
                if connection is not None:
                    with contextlib.suppress(Exception):
                        await connection.close()
            if attempt + 1 < attempts and not (stop_event and stop_event.is_set()):
                await self._sleep(min(0.25 * (2**attempt), 4.0))
        return output

    def health(self) -> dict:
        return {
            "enabled": self.config.enabled and self.config.ha_enabled,
            "status": str(self._health.get("status", "degraded"))[:32],
            "reason": str(self._health.get("reason", ""))[:256],
            "host": (urlparse(self.config.base_url).hostname or "")[:253],
        }
