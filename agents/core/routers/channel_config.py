"""The HUD's Channels panel: view and edit each messaging channel's settings (G21 · H151/H160).

Owner/admin only (``admin_guard``) on every route, reads included; writes also need this
origin (``integrations_setup.same_origin_write``). Validation errors are answered without
the request (``_QuietRoute``), so a malformed body can never echo a token. The rules live
in ``agents/core/channel_config.py``:

* ``GET    /api/admin/channels/config`` — every channel: whether it is running, each field's
  state (a plain value, or for a secret only ``set`` and where it was set), and whether a
  change waits for a restart.
* ``PUT    /api/admin/channels/{channel_id}/config`` — plain settings (``{"values": {NAME:
  value | null}}``) into the settings database (``channels.config``).
* ``PUT    /api/admin/channels/{channel_id}/secret`` — one secret (``{"name", "value"}``)
  into the encrypted integration-key store; the answer never carries it.
* ``DELETE /api/admin/channels/{channel_id}/secret/{name}`` — remove a stored secret.

``.env`` wins (409 ``env_managed``); an administrator's pin or managed mode refuses (409
``managed``, audited); an unknown channel or name is 404.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictStr

from agents.core import channel_config as cc
from agents.core.app_state import get_orch
from agents.core.managed_scope import ManagedRefused
from agents.core.routers._deps import admin_guard
from agents.core.routers.integrations_setup import _QuietRoute, same_origin_write
from agents.core.web_helpers import nocache_json

logger = logging.getLogger("jarvis.routers.channel_config")

router = APIRouter(route_class=_QuietRoute, tags=["channels"])

WRITE_GUARDS = [Depends(admin_guard), Depends(same_origin_write)]
CHANNEL_PATTERN = r"^[a-z][a-z0-9-]{0,31}$"
NAME_PATTERN = r"^[A-Z][A-Z0-9_]{0,63}$"


class PlainBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    values: dict[StrictStr, StrictStr | int | bool | None] = Field(min_length=1, max_length=16)


class SecretBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: StrictStr = Field(min_length=1, max_length=64, pattern=NAME_PATTERN)
    value: SecretStr = Field(min_length=1, max_length=4096)


def _running() -> set[str]:
    orch = get_orch()
    channels = getattr(orch, "channels", None) if orch is not None else None
    try:
        return set(channels or {})
    except TypeError:
        return set()


async def _audit(preview: str, action: str) -> None:
    orch = get_orch()
    audit = getattr(orch, "audit", None) if orch is not None else None
    if audit is None:
        return
    from agents.core.security.types import SecurityEvent, SecurityEventType

    try:
        await asyncio.to_thread(audit.log, SecurityEvent(
            event_type=SecurityEventType.SETTINGS_CHANGE, timestamp=time.time(),
            content_preview=preview[:500], action_taken=action))
    except Exception:  # noqa: BLE001 — the write happened; a lost audit row is logged
        logger.warning("a channel settings audit row could not be written (%s)", action)


def _not_found() -> Any:
    return nocache_json({"error": "unknown_channel_setting"}, status_code=404)


def _env_owned(name: str) -> Any:
    return nocache_json({"error": "env_managed", "name": name,
                         "detail": f"{name} is set in .env (or the hub's environment); change it there"},
                        status_code=409)


async def _managed(exc: ManagedRefused, channel_id: str) -> Any:
    await _audit(f"channels: {channel_id} write refused: {exc.names} {exc}", "settings_managed_refused")
    return nocache_json(exc.payload(), status_code=409)


def _row(channel_id: str) -> dict | None:
    body = cc.listing(_running())
    return next((c for c in body["channels"] if c["id"] == channel_id), None)


@router.get("/api/admin/channels/config", dependencies=[Depends(admin_guard)])
async def channels_config():
    """Every channel's settings; a secret only as set / where."""
    return nocache_json(await asyncio.to_thread(cc.listing, _running()))


@router.put("/api/admin/channels/{channel_id}/config", dependencies=WRITE_GUARDS)
async def channel_config_put(body: PlainBody, channel_id: str = Path(..., pattern=CHANNEL_PATTERN)):
    try:
        result = await asyncio.to_thread(cc.set_plain, channel_id, dict(body.values))
    except KeyError:
        return _not_found()
    except cc.InvalidValue as exc:
        return nocache_json({"error": "invalid_value", "field": str(exc)}, status_code=422)
    except cc.EnvOwned as exc:
        return _env_owned(str(exc))
    except ManagedRefused as exc:
        return await _managed(exc, channel_id)
    await _audit(f"channels: {channel_id} settings set: {result['written']}", "channel_config_set")
    return nocache_json({"ok": True, **result, "channel": _row(channel_id)})


@router.put("/api/admin/channels/{channel_id}/secret", dependencies=WRITE_GUARDS)
async def channel_secret_put(body: SecretBody, channel_id: str = Path(..., pattern=CHANNEL_PATTERN)):
    try:
        state = await asyncio.to_thread(cc.set_secret, channel_id, body.name, body.value.get_secret_value())
    except KeyError:
        return _not_found()
    except ValueError:
        return nocache_json({"error": "invalid_value", "field": body.name}, status_code=422)
    except cc.EnvOwned as exc:
        return _env_owned(str(exc))
    except ManagedRefused as exc:
        return await _managed(exc, channel_id)
    await _audit(f"channels: {channel_id} secret {body.name} set", "channel_secret_set")
    return nocache_json({"ok": True, "secret": state, "channel": _row(channel_id)})


@router.delete("/api/admin/channels/{channel_id}/secret/{name}", dependencies=WRITE_GUARDS)
async def channel_secret_delete(channel_id: str = Path(..., pattern=CHANNEL_PATTERN),
                                name: str = Path(..., pattern=NAME_PATTERN)):
    try:
        state = await asyncio.to_thread(cc.clear_secret, channel_id, name)
    except KeyError:
        return _not_found()
    except cc.EnvOwned as exc:
        return _env_owned(str(exc))
    except ManagedRefused as exc:
        return await _managed(exc, channel_id)
    await _audit(f"channels: {channel_id} secret {name} removed", "channel_secret_cleared")
    return nocache_json({"ok": True, "secret": state, "channel": _row(channel_id)})
