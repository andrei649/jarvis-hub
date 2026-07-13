"""Encrypted, retention-mandatory camera event storage built on the core Vault."""

from __future__ import annotations

import io
import json
import math
import re
import threading
import time
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from agents.core.security.secret_broker import SecretBroker
from agents.core.vault import Vault, VaultError

from .models import CameraConfig, CameraEvent, MaskedFrame
from .privacy import CameraPrivacyError, apply_masks

_DEFAULT_KEY_REF = "{{secret:camera.vault_key}}"
_EVENT_KIND = "camera-event-v1"
_SNAPSHOT_KIND = "camera-snapshot-v1"
_SCHEMA = 1
_MAX_RECORD_BYTES = 16 * 1024
_DEFAULT_MAX_ITEMS = 5000
_DEFAULT_MAX_TOTAL_BYTES = 128 * 1024 * 1024
_DEFAULT_MAX_ITEM_BYTES = 5 * 1024 * 1024
_KEY_REF_RE = re.compile(r"^\{\{\s*secret:[A-Za-z0-9_.-]+\s*\}\}$")
_FORBIDDEN_DESCRIPTION = re.compile(
    r"\b(?:biometric|face(?:[ _-]?id)?|identit(?:y|ies)|identified person|"
    r"license[ _-]?plate|plate[ _-]?(?:number|id)|person[ _-]?(?:id|name)|"
    r"sub[ _-]?label|named person)\b",
    re.IGNORECASE,
)
_LIKELY_NAME_START = re.compile(r"^[A-Z][a-z]{1,31}\b")
_SAFE_DESCRIPTION_STARTS = frozenset({"a", "an", "anonymous", "someone", "the"})
_MAX_FRAME_BYTES = 5 * 1024 * 1024
_MAX_FRAME_DIMENSION = 4096
_MAX_FRAME_PIXELS = 12_000_000


class CameraVaultError(RuntimeError):
    """Stable, path-free failure at the camera persistence boundary."""


@dataclass(frozen=True, slots=True)
class CameraStoreReceipt:
    stored: bool
    snapshot_stored: bool


@dataclass(frozen=True, slots=True)
class CameraSweepReport:
    removed_metadata: int
    removed_snapshots: int
    removed_orphans: int


@dataclass(frozen=True, slots=True)
class CameraPurgeReport:
    removed: int


@dataclass(frozen=True, slots=True)
class _StoredRecord:
    vault_id: str
    event: CameraEvent
    metadata_expires_at: float
    snapshot_ref: str | None
    snapshot_expires_at: float | None
    snapshot_format: str | None
    snapshot_width: int | None
    snapshot_height: int | None


def _timestamp(value: Any, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CameraVaultError(f"{field_name}_invalid")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise CameraVaultError(f"{field_name}_invalid")
    return result


def _json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON value")


def _managed_key(secret_broker: SecretBroker, key_ref: str) -> str:
    if not isinstance(secret_broker, SecretBroker):
        raise ValueError("camera vault requires SecretBroker")
    if not isinstance(key_ref, str) or _KEY_REF_RE.fullmatch(key_ref) is None:
        raise ValueError("camera vault key must be a SecretBroker reference")
    result = secret_broker.inject(key_ref, approved=True)
    if result["blocked"] or len(result["injected"]) != 1 or result["text"] == key_ref:
        raise CameraVaultError("vault_key_unavailable")
    secret = result["text"]
    if not isinstance(secret, str) or len(secret) < 32:
        raise CameraVaultError("vault_key_unavailable")
    return secret


def _event_payload(event: CameraEvent) -> dict[str, Any]:
    payload = {
        "event_id": event.event_id,
        "camera_id": event.camera_id,
        "label": event.label,
        "occurred_at": event.occurred_at,
        "confidence": event.confidence,
    }
    for name in ("zone", "room_id", "description", "description_provenance"):
        value = getattr(event, name)
        if value is not None:
            payload[name] = value
    return payload


def _verify_event_description(event: CameraEvent) -> None:
    description = event.description
    provenance = event.description_provenance
    if description is None:
        if provenance is not None:
            raise CameraVaultError("camera_event_unsafe")
        return
    if provenance != "local_vlm_on_demand" or _FORBIDDEN_DESCRIPTION.search(description):
        raise CameraVaultError("camera_event_unsafe")
    first_word = description.split(maxsplit=1)[0].lower().rstrip(".,:;!?")
    if _LIKELY_NAME_START.match(description) and first_word not in _SAFE_DESCRIPTION_STARTS:
        raise CameraVaultError("camera_event_unsafe")


def _verified_masked_frame(frame: MaskedFrame) -> None:
    if (
        not isinstance(frame, MaskedFrame)
        or frame.format != "PNG"
        or not isinstance(frame.data, bytes)
        or not frame.data
        or len(frame.data) > _MAX_FRAME_BYTES
        or frame.width < 1
        or frame.height < 1
        or frame.width > _MAX_FRAME_DIMENSION
        or frame.height > _MAX_FRAME_DIMENSION
        or frame.width * frame.height > _MAX_FRAME_PIXELS
    ):
        raise CameraVaultError("masked_snapshot_invalid")
    try:
        with Image.open(io.BytesIO(frame.data)) as probe:
            if (
                probe.format != "PNG"
                or probe.mode != "RGB"
                or probe.size != (frame.width, frame.height)
                or int(getattr(probe, "n_frames", 1)) != 1
            ):
                raise CameraVaultError("masked_snapshot_invalid")
            probe.verify()
        with Image.open(io.BytesIO(frame.data)) as decoded:
            decoded.load()
            if decoded.info or decoded.getexif():
                raise CameraVaultError("masked_snapshot_invalid")
    except CameraVaultError:
        raise
    except (OSError, RuntimeError, SyntaxError, UnidentifiedImageError, ValueError) as exc:
        raise CameraVaultError("masked_snapshot_invalid") from exc


class CameraEventVault:
    """Camera-domain projection over Vault; no internal id appears in public results."""

    def __init__(
        self,
        root: str | Path,
        *,
        configs: Sequence[CameraConfig],
        secret_broker: SecretBroker,
        key_ref: str = _DEFAULT_KEY_REF,
        clock: Callable[[], float] = time.time,
        max_items: int = _DEFAULT_MAX_ITEMS,
        max_total_bytes: int = _DEFAULT_MAX_TOTAL_BYTES,
        max_item_bytes: int = _DEFAULT_MAX_ITEM_BYTES,
    ) -> None:
        if not isinstance(configs, Sequence) or not configs or len(configs) > 128:
            raise ValueError("camera vault configs must be a non-empty bounded collection")
        config_map: dict[str, CameraConfig] = {}
        for config in configs:
            if not isinstance(config, CameraConfig):
                raise ValueError("camera vault configs must contain CameraConfig values")
            if not config.masks:
                raise ValueError("camera vault configs require privacy masks")
            if config.camera_id in config_map:
                raise ValueError("camera vault camera ids must be unique")
            config_map[config.camera_id] = config
        if not callable(clock):
            raise ValueError("camera vault clock must be callable")
        key = _managed_key(secret_broker, key_ref)
        self._configs = config_map
        self._clock = clock
        self._lock = threading.RLock()
        try:
            self._vault = Vault(
                root,
                key=key,
                max_items=max_items,
                max_total_bytes=max_total_bytes,
                max_item_bytes=max_item_bytes,
            )
        except VaultError as exc:
            raise CameraVaultError("vault_unavailable") from exc
        finally:
            key = ""
        self.root = self._vault.root
        self._last_sweep_at: float | None = None
        self.sweep(now=self._now())

    def _now(self) -> float:
        return _timestamp(self._clock(), field_name="clock")

    def store(
        self,
        event: CameraEvent,
        *,
        frame: MaskedFrame | None = None,
        now: float | None = None,
    ) -> CameraStoreReceipt:
        if not isinstance(event, CameraEvent):
            raise ValueError("camera vault stores CameraEvent values")
        current = self._now() if now is None else _timestamp(now, field_name="now")
        config = self._configs.get(event.camera_id)
        if config is None:
            raise CameraVaultError("camera_unknown")
        if not config.enabled:
            raise CameraVaultError("camera_disabled")
        _verify_event_description(event)
        stored_frame: MaskedFrame | None = None
        if frame is not None:
            _verified_masked_frame(frame)
            try:
                stored_frame = apply_masks(frame.data, config.masks)
            except CameraPrivacyError as exc:
                raise CameraVaultError("masked_snapshot_invalid") from exc
            _verified_masked_frame(stored_frame)

        with self._lock:
            self.sweep(now=current)
            if self._find_record(event.camera_id, event.event_id) is not None:
                return CameraStoreReceipt(stored=False, snapshot_stored=False)
            metadata_expiry = event.occurred_at + config.metadata_ttl_seconds
            if metadata_expiry <= current:
                raise CameraVaultError("event_expired")
            snapshot_expiry = min(
                event.occurred_at + config.snapshot_ttl_seconds,
                metadata_expiry,
            )
            snapshot_entry: dict[str, Any] | None = None
            snapshot_stored = stored_frame is not None and snapshot_expiry > current
            try:
                if snapshot_stored and stored_frame is not None:
                    snapshot_entry = self._vault.put(
                        stored_frame.data,
                        name="camera-snapshot",
                        kind=_SNAPSHOT_KIND,
                        now=current,
                        expires_at=snapshot_expiry,
                    )
                record = {
                    "schema": _SCHEMA,
                    "event": _event_payload(event),
                    "metadata_expires_at": metadata_expiry,
                    "snapshot": (
                        {
                            "ref": snapshot_entry["id"],
                            "expires_at": snapshot_expiry,
                            "format": stored_frame.format,
                            "width": stored_frame.width,
                            "height": stored_frame.height,
                        }
                        if snapshot_entry is not None and stored_frame is not None
                        else None
                    ),
                }
                encoded = json.dumps(
                    record,
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                if len(encoded) > _MAX_RECORD_BYTES:
                    raise CameraVaultError("event_record_too_large")
                self._vault.put(
                    encoded,
                    name="camera-event",
                    kind=_EVENT_KIND,
                    now=current,
                    expires_at=metadata_expiry,
                )
            except (CameraVaultError, OSError, ValueError, VaultError) as exc:
                if snapshot_entry is not None:
                    with suppress(VaultError):
                        self._vault.remove(snapshot_entry["id"])
                if isinstance(exc, CameraVaultError) and str(exc) == "event_record_too_large":
                    raise
                raise CameraVaultError("store_failed") from exc
            return CameraStoreReceipt(stored=True, snapshot_stored=snapshot_stored)

    def list_events(
        self,
        *,
        now: float | None = None,
        limit: int = 100,
    ) -> tuple[CameraEvent, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("camera event limit must be between 1 and 1000")
        current = self._now() if now is None else _timestamp(now, field_name="now")
        with self._lock:
            self.sweep(now=current)
            records = self._records()
            records.sort(key=lambda item: (-item.event.occurred_at, item.event.event_id))
            return tuple(record.event for record in records[:limit])

    def _load_masked_snapshot(
        self,
        camera_id: str,
        event_id: str,
        *,
        now: float | None = None,
    ) -> MaskedFrame | None:
        current = self._now() if now is None else _timestamp(now, field_name="now")
        with self._lock:
            self.sweep(now=current)
            record = self._find_record(camera_id, event_id)
            if record is None or record.snapshot_ref is None:
                return None
            if record.snapshot_expires_at is None or record.snapshot_expires_at <= current:
                return None
            try:
                entries = {entry["id"] for entry in self._vault.list()}
                if record.snapshot_ref not in entries:
                    return None
                data = self._vault.get(record.snapshot_ref)
            except VaultError as exc:
                raise CameraVaultError("vault_unavailable") from exc
            frame = MaskedFrame(
                data=data,
                format=record.snapshot_format or "",
                width=record.snapshot_width or 0,
                height=record.snapshot_height or 0,
            )
            _verified_masked_frame(frame)
            return frame

    def sweep(self, *, now: float | None = None) -> CameraSweepReport:
        current = self._now() if now is None else _timestamp(now, field_name="now")
        with self._lock:
            try:
                before = {entry["id"]: entry["kind"] for entry in self._vault.list()}
                expired = self._vault.sweep(current)["removed"]
                removed_metadata = sum(before.get(item) == _EVENT_KIND for item in expired)
                removed_snapshots = sum(before.get(item) == _SNAPSHOT_KIND for item in expired)
                records = self._records()
                referenced = {
                    record.snapshot_ref for record in records if record.snapshot_ref is not None
                }
                orphans = [
                    entry["id"]
                    for entry in self._vault.list()
                    if entry["kind"] == _SNAPSHOT_KIND and entry["id"] not in referenced
                ]
                for vault_id in orphans:
                    self._vault.remove(vault_id)
            except (OSError, ValueError, VaultError) as exc:
                raise CameraVaultError("vault_unavailable") from exc
            self._last_sweep_at = current
            return CameraSweepReport(
                removed_metadata=removed_metadata,
                removed_snapshots=removed_snapshots,
                removed_orphans=len(orphans),
            )

    def purge(self) -> CameraPurgeReport:
        with self._lock:
            try:
                removed = self._vault.purge()
            except VaultError as exc:
                raise CameraVaultError("purge_incomplete") from exc
            return CameraPurgeReport(removed=removed)

    def health(self) -> dict[str, int | float | str | None]:
        try:
            stats = self._vault.stats()
        except (OSError, VaultError):
            return {
                "status": "unavailable",
                "items": 0,
                "bytes": 0,
                "last_sweep_at": self._last_sweep_at,
            }
        return {
            "status": "ready",
            "items": stats["items"],
            "bytes": stats["bytes"],
            "last_sweep_at": self._last_sweep_at,
        }

    def _find_record(self, camera_id: str, event_id: str) -> _StoredRecord | None:
        for record in self._records():
            if record.event.camera_id == camera_id and record.event.event_id == event_id:
                return record
        return None

    def _records(self) -> list[_StoredRecord]:
        try:
            entries = self._vault.list()
            records: list[_StoredRecord] = []
            for entry in entries:
                if entry["kind"] == _SNAPSHOT_KIND:
                    continue
                if entry["kind"] != _EVENT_KIND:
                    raise CameraVaultError("vault_record_invalid")
                raw = self._vault.get(entry["id"])
                if len(raw) > _MAX_RECORD_BYTES:
                    raise CameraVaultError("vault_record_invalid")
                payload = json.loads(
                    raw.decode("utf-8"),
                    parse_constant=_json_constant,
                )
                records.append(self._parse_record(entry["id"], payload))
            return records
        except CameraVaultError:
            raise
        except (OSError, UnicodeError, ValueError, VaultError) as exc:
            raise CameraVaultError("vault_unavailable") from exc

    @staticmethod
    def _parse_record(vault_id: str, payload: Any) -> _StoredRecord:
        if not isinstance(payload, dict) or set(payload) != {
            "schema",
            "event",
            "metadata_expires_at",
            "snapshot",
        }:
            raise CameraVaultError("vault_record_invalid")
        if payload["schema"] != _SCHEMA or not isinstance(payload["event"], dict):
            raise CameraVaultError("vault_record_invalid")
        try:
            event = CameraEvent.from_payload(payload["event"])
            metadata_expiry = _timestamp(
                payload["metadata_expires_at"],
                field_name="metadata_expiry",
            )
        except (CameraVaultError, TypeError, ValueError) as exc:
            raise CameraVaultError("vault_record_invalid") from exc
        snapshot = payload["snapshot"]
        if snapshot is None:
            return _StoredRecord(vault_id, event, metadata_expiry, None, None, None, None, None)
        if not isinstance(snapshot, dict) or set(snapshot) != {
            "ref",
            "expires_at",
            "format",
            "width",
            "height",
        }:
            raise CameraVaultError("vault_record_invalid")
        if (
            not isinstance(snapshot["ref"], str)
            or snapshot["format"] != "PNG"
            or isinstance(snapshot["width"], bool)
            or not isinstance(snapshot["width"], int)
            or isinstance(snapshot["height"], bool)
            or not isinstance(snapshot["height"], int)
            or snapshot["width"] < 1
            or snapshot["height"] < 1
        ):
            raise CameraVaultError("vault_record_invalid")
        try:
            snapshot_expiry = _timestamp(snapshot["expires_at"], field_name="snapshot_expiry")
        except CameraVaultError as exc:
            raise CameraVaultError("vault_record_invalid") from exc
        if snapshot_expiry > metadata_expiry:
            raise CameraVaultError("vault_record_invalid")
        return _StoredRecord(
            vault_id,
            event,
            metadata_expiry,
            snapshot["ref"],
            snapshot_expiry,
            snapshot["format"],
            snapshot["width"],
            snapshot["height"],
        )


__all__ = [
    "CameraEventVault",
    "CameraPurgeReport",
    "CameraStoreReceipt",
    "CameraSweepReport",
    "CameraVaultError",
]
