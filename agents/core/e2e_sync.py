"""
e2e_sync.py — H12.13 + H040 Opt-in end-to-end encrypted device sync (config & skills).

The home GPU ↔ laptop ↔ phone (and any other device the owner controls) can sync
declared configuration and skills, while the transport/relay only ever sees
**ciphertext**: records are encrypted on the source device with authenticated
Fernet (AES-128-CBC + HMAC-SHA256) and decrypted only on a destination device
holding the shared secret.

Security invariants (Nerva > Hermes/OpenClaw):
  - **Honest crypto, fail-closed**: PBKDF2-HMAC-SHA256 (390k iterations) or raw
    32-byte Fernet key; off unless ``JARVIS_E2E_SYNC`` is enabled and a key is set.
  - **Secret-free config sync**: uses ``settings_db.export_settings()`` and
    ``plan_import()`` / ``apply_import()`` so secrets, credentials, ``ROUTE_ONLY``
    switches, and ``managed_scope`` pins are never exported or overwritten.
  - **Per-skill sync controls & injection quarantine**: per-skill enable/disable
    policy plus ``detect_injection_normalized`` scan on ``pull`` before any synced
    ``SKILL.md`` reaches disk.
  - **Real cross-device transports**: shared spool directory
    (:class:`DirectorySyncTransport`) and hub-to-hub ciphertext mailbox
    (:class:`HttpPeerSyncTransport` over ``PluginHTTPClient`` / injected client).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import stat
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Optional, Protocol

from agents.core.paths import data_path

logger = logging.getLogger("jarvis.e2e_sync")

# Fixed app salt: cross-device key derivation must be deterministic so two
# devices with the same passphrase land on the same key. Security comes from the
# passphrase, not the salt.
_SALT = b"jarvis-e2e-sync-v1"
_ENV_FLAG = "JARVIS_E2E_SYNC"
_ENV_KEY = "JARVIS_E2E_SYNC_KEY"
_ENV_SPOOL = "JARVIS_E2E_SYNC_DIR"
_SKILL_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_DEVICE_ID_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_SKILL_MD_BYTES = 256 * 1024
_MAX_MAILBOX_ITEMS = 32
_MAX_MAILBOX_JSON_BYTES = 2 * 1024 * 1024


class E2ESyncError(Exception):
    """Raised when a record cannot be decrypted or a sync invariant is violated."""


def _crypto():
    """Return the Fernet class, or None if cryptography is unavailable."""
    try:
        from cryptography.fernet import Fernet

        return Fernet
    except Exception:  # pragma: no cover - exercised only without cryptography
        return None


def _looks_like_fernet_key(s: str) -> bool:
    try:
        return len(base64.urlsafe_b64decode(s.encode())) == 32
    except Exception:
        return False


def _derive_key(passphrase: str) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=_SALT, iterations=390_000)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def sync_enabled() -> bool:
    from agents.core.env_config import env_flag

    return env_flag(_ENV_FLAG)


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".sync_", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise


class SyncTransport(Protocol):
    """Transport moving encrypted E2E manifests between owner devices."""

    name: str

    def send_manifest(self, manifest: dict[str, Any]) -> dict[str, Any]: ...

    def fetch_manifests(self, *, exclude_device: str = "") -> list[dict[str, Any]]: ...


class DirectorySyncTransport:
    """Shared-folder / Syncthing / iCloud / Tailscale-drive ciphertext spool transport."""

    name = "directory"

    def __init__(self, spool_dir: str | Path) -> None:
        self.spool_dir = Path(spool_dir)

    def send_manifest(self, manifest: dict[str, Any]) -> dict[str, Any]:
        safe_dev = _DEVICE_ID_SAFE_RE.sub("_", str(manifest.get("device") or "device"))[:64] or "device"
        target = self.spool_dir / f"manifest_{safe_dev}.json"
        _write_private_json(target, manifest)
        return {"ok": True, "transport": self.name, "path": str(target)}

    def fetch_manifests(self, *, exclude_device: str = "") -> list[dict[str, Any]]:
        if not self.spool_dir.is_dir():
            return []
        out: list[dict[str, Any]] = []
        for candidate in sorted(self.spool_dir.glob("manifest_*.json")):
            try:
                raw = candidate.read_bytes()
                if len(raw) > _MAX_MAILBOX_JSON_BYTES:
                    continue
                doc = json.loads(raw.decode("utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(doc, dict):
                continue
            if exclude_device and doc.get("device") == exclude_device:
                continue
            out.append(doc)
        return out


class HttpPeerSyncTransport:
    """Ciphertext-only peer hub transport over ``/api/sync/peer/mailbox``."""

    name = "peer-http"
    plugin = "e2e-sync"

    def __init__(
        self,
        *,
        peers_provider: Callable[[], list[dict[str, Any]]],
        requester: Optional[Callable[[str, str, Optional[dict[str, Any]]], dict[str, Any]]] = None,
    ) -> None:
        self._peers_provider = peers_provider
        self._requester = requester

    def _default_request(
        self, method: str, url: str, body: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        import asyncio

        from agents.core.http_client import PluginHTTPClient
        from agents.core.plugin_gate import register_dynamic_domain

        register_dynamic_domain(self.plugin, url)
        client = PluginHTTPClient.for_plugin(self.plugin)

        async def _call() -> dict[str, Any]:
            if method == "POST":
                resp = await client.post(url, json=body or {})
            else:
                resp = await client.get(url)
            if resp.status_code >= 400:
                return {"ok": False, "status": resp.status_code}
            return resp.json()

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(_call())
        # When invoked inside a running event loop, run in a worker thread cleanly.
        result_holder: dict[str, Any] = {}
        err_holder: list[BaseException] = []

        def _worker() -> None:
            try:
                result_holder["data"] = asyncio.run(_call())
            except BaseException as exc:  # pragma: no cover
                err_holder.append(exc)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        t.join(timeout=15.0)
        if err_holder:
            raise err_holder[0]
        return result_holder.get("data", {"ok": False})

    def _call(self, method: str, url: str, body: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        fn = self._requester or self._default_request
        return fn(method, url, body)

    def send_manifest(self, manifest: dict[str, Any]) -> dict[str, Any]:
        peers = self._peers_provider()
        delivered = 0
        errors: list[str] = []
        for peer in peers:
            base = str(peer.get("url") or "").rstrip("/")
            if not base:
                continue
            try:
                res = self._call("POST", f"{base}/api/sync/peer/mailbox", {"manifest": manifest})
                if res.get("ok"):
                    delivered += 1
                else:
                    errors.append(f"{peer.get('peer_id', base)}: refused")
            except Exception as exc:
                errors.append(f"{peer.get('peer_id', base)}: {type(exc).__name__}")
        return {"ok": True, "transport": self.name, "delivered_peers": delivered, "errors": errors}

    def fetch_manifests(self, *, exclude_device: str = "") -> list[dict[str, Any]]:
        peers = self._peers_provider()
        manifests: list[dict[str, Any]] = []
        for peer in peers:
            base = str(peer.get("url") or "").rstrip("/")
            if not base:
                continue
            try:
                res = self._call("GET", f"{base}/api/sync/peer/mailbox", None)
                for item in res.get("manifests") or []:
                    if isinstance(item, dict) and item.get("device") != exclude_device:
                        manifests.append(item)
            except Exception:
                logger.debug("peer sync fetch failed for %s", base, exc_info=True)
        return manifests


class E2ESync:
    """End-to-end encrypted cross-device sync envelope, artefact collector, and transport coordinator."""

    def __init__(
        self,
        key: Optional[str] = None,
        passphrase: Optional[str] = None,
        device_id: str = "",
        *,
        device_label: str = "",
        state_path: Optional[str | Path] = None,
        skills_dir: Optional[str | Path] = None,
        transport: Optional[SyncTransport] = None,
        peer_requester: Optional[Callable[[str, str, Optional[dict[str, Any]]], dict[str, Any]]] = None,
    ) -> None:
        self.device_id = device_id or os.environ.get("JARVIS_DEVICE_ID", "") or "device"
        self._lock = threading.Lock()
        self._state_path = Path(state_path) if state_path is not None else None
        self._skills_dir = Path(skills_dir) if skills_dir is not None else None
        self._device_label = (device_label or os.environ.get("JARVIS_DEVICE_LABEL", "")).strip()[:80]
        self._skill_policies: dict[str, bool] = {}
        self._peers: dict[str, dict[str, Any]] = {}
        self._mailbox: dict[str, dict[str, Any]] = {}
        self._last_push_at: Optional[float] = None
        self._last_pull_at: Optional[float] = None
        self._custom_transport = transport
        self._peer_transport = HttpPeerSyncTransport(
            peers_provider=self.list_peers, requester=peer_requester
        )
        if self._state_path is not None and self._state_path.is_file():
            self._load_state()

        self._fernet = None
        Fernet = _crypto()
        if Fernet is None:
            return
        secret = key or os.environ.get(_ENV_KEY, "")
        try:
            if secret and _looks_like_fernet_key(secret):
                self._fernet = Fernet(secret.encode())
            elif passphrase:
                self._fernet = Fernet(_derive_key(passphrase))
            elif secret:  # treat any other configured secret as a passphrase
                self._fernet = Fernet(_derive_key(secret))
        except Exception:
            logger.warning("E2E sync key setup failed — sync disabled", exc_info=True)
            self._fernet = None

    # ── local metadata persistence ───────────────────────────────────────────

    def _resolved_state_path(self) -> Path:
        return self._state_path if self._state_path is not None else data_path("e2e_sync_state.json")

    def _resolved_skills_dir(self) -> Path:
        return self._skills_dir if self._skills_dir is not None else data_path("synced_skills")

    def _load_state(self) -> None:
        path = self._resolved_state_path()
        if not path.is_file():
            return
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(doc, dict):
            return
        if doc.get("device_label") and not self._device_label:
            self._device_label = str(doc["device_label"])[:80]
        if isinstance(doc.get("skill_policies"), dict):
            self._skill_policies = {
                str(k).strip().lower(): bool(v)
                for k, v in doc["skill_policies"].items()
                if str(k).strip()
            }
        if isinstance(doc.get("peers"), dict):
            self._peers = {
                str(k): dict(v)
                for k, v in doc["peers"].items()
                if isinstance(v, dict)
            }
        if isinstance(doc.get("last_push_at"), (int, float)):
            self._last_push_at = float(doc["last_push_at"])
        if isinstance(doc.get("last_pull_at"), (int, float)):
            self._last_pull_at = float(doc["last_pull_at"])

    def _save_state(self) -> None:
        path = self._resolved_state_path()
        payload = {
            "device_id": self.device_id,
            "device_label": self._device_label,
            "skill_policies": dict(self._skill_policies),
            "peers": dict(self._peers),
            "last_push_at": self._last_push_at,
            "last_pull_at": self._last_pull_at,
        }
        try:
            _write_private_json(path, payload)
        except OSError:
            logger.debug("could not persist e2e_sync_state.json", exc_info=True)

    def _active_transports(self) -> list[SyncTransport]:
        transports: list[SyncTransport] = []
        if self._custom_transport is not None:
            transports.append(self._custom_transport)
        spool_env = os.environ.get(_ENV_SPOOL, "").strip()
        if spool_env:
            transports.append(DirectorySyncTransport(spool_env))
        if self._peers:
            transports.append(self._peer_transport)
        return transports

    # ── status & owner controls ──────────────────────────────────────────────

    @property
    def available(self) -> bool:
        """Crypto present AND a shared secret configured."""
        return self._fernet is not None

    @property
    def backend(self) -> str:
        if _crypto() is None:
            return "unavailable"
        return "fernet" if self._fernet is not None else "no-key"

    @property
    def device_label(self) -> str:
        return self._device_label or self.device_id

    def enabled(self) -> bool:
        return sync_enabled() and self.available

    def status(self) -> dict[str, Any]:
        transports = [getattr(t, "name", "custom") for t in self._active_transports()]
        return {
            "enabled": self.enabled(),
            "available": self.available,
            "backend": self.backend,
            "device_id": self.device_id,
            "device_label": self.device_label,
            "skill_policies": dict(self._skill_policies),
            "peers": self.list_peers(),
            "transports": transports,
            "mailbox_count": len(self._mailbox),
            "last_push_at": self._last_push_at,
            "last_pull_at": self._last_pull_at,
        }

    def set_device_label(self, label: str) -> dict[str, Any]:
        cleaned = (label or "").strip()[:80]
        if not cleaned:
            raise E2ESyncError("device label must not be empty")
        with self._lock:
            self._device_label = cleaned
            self._save_state()
        return {"ok": True, "device_id": self.device_id, "device_label": self._device_label}

    def set_skill_sync(self, skill_name: str, enabled: bool) -> dict[str, Any]:
        slug = (skill_name or "").strip().lower()
        if not _SKILL_SLUG_RE.fullmatch(slug):
            raise E2ESyncError(f"invalid skill name {skill_name!r}")
        with self._lock:
            self._skill_policies[slug] = bool(enabled)
            self._save_state()
        return {"ok": True, "skill": slug, "sync_enabled": bool(enabled)}

    def is_skill_sync_enabled(self, skill_name: str) -> bool:
        slug = (skill_name or "").strip().lower()
        return self._skill_policies.get(slug, True)

    def add_peer(self, peer_id: str, url: str, label: str = "") -> dict[str, Any]:
        pid = (peer_id or "").strip()[:64]
        clean_url = (url or "").strip().rstrip("/")
        if not pid or not clean_url.startswith(("http://", "https://")):
            raise E2ESyncError("valid peer_id and http(s) url required")
        entry = {"peer_id": pid, "url": clean_url, "label": (label or pid).strip()[:80]}
        with self._lock:
            self._peers[pid] = entry
            self._save_state()
        return {"ok": True, "peer": dict(entry)}

    def remove_peer(self, peer_id: str) -> bool:
        pid = (peer_id or "").strip()
        with self._lock:
            removed = self._peers.pop(pid, None) is not None
            if removed:
                self._save_state()
            return removed

    def list_peers(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(v) for v in self._peers.values()]

    # ── ciphertext-only peer mailbox ─────────────────────────────────────────

    def accept_peer_manifest(self, manifest: dict[str, Any]) -> dict[str, Any]:
        """Store an inbound encrypted manifest from another device (ciphertext only)."""
        if not isinstance(manifest, dict):
            raise E2ESyncError("manifest must be a JSON object")
        device = str(manifest.get("device") or "").strip()[:80]
        entries = manifest.get("entries")
        if not device or not isinstance(entries, list):
            raise E2ESyncError("manifest requires device and entries list")
        raw_len = len(json.dumps(manifest))
        if raw_len > _MAX_MAILBOX_JSON_BYTES:
            raise E2ESyncError("manifest exceeds size bound")
        for env in entries:
            if not isinstance(env, dict) or not isinstance(env.get("ct"), str):
                raise E2ESyncError("manifest entries must contain ciphertext envelopes only")
            if set(env) - {"v", "device", "ct", "ts"}:
                raise E2ESyncError("plaintext fields are forbidden in ciphertext envelopes")
        with self._lock:
            if len(self._mailbox) >= _MAX_MAILBOX_ITEMS and device not in self._mailbox:
                oldest = next(iter(self._mailbox))
                self._mailbox.pop(oldest, None)
            self._mailbox[device] = dict(manifest)
        return {"ok": True, "device": device, "count": len(entries)}

    def list_peer_manifests(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(m) for m in self._mailbox.values()]

    # ── envelope ─────────────────────────────────────────────────────────────

    def encrypt_record(self, record: dict) -> dict:
        if self._fernet is None:
            raise E2ESyncError("E2E sync unavailable (no crypto / no shared secret)")
        plaintext = json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8")
        token = self._fernet.encrypt(plaintext).decode("ascii")
        return {"v": 1, "device": self.device_id, "ct": token, "ts": time.time()}

    def decrypt_record(self, envelope: dict) -> dict:
        if self._fernet is None:
            raise E2ESyncError("E2E sync unavailable (no crypto / no shared secret)")
        ct = (envelope or {}).get("ct")
        if not ct:
            raise E2ESyncError("envelope has no ciphertext")
        try:
            plaintext = self._fernet.decrypt(ct.encode("ascii"))
        except Exception as e:
            raise E2ESyncError("decryption failed (tamper / wrong key)") from e
        return json.loads(plaintext.decode("utf-8"))

    # ── manifest ─────────────────────────────────────────────────────────────

    def build_push(self, records: "list[dict]", kind: str = "memory") -> dict:
        if not self.enabled():
            return {"enabled": False, "kind": kind, "count": 0, "entries": []}
        entries = [self.encrypt_record(r) for r in (records or [])]
        digest = hashlib.sha256("".join(e["ct"] for e in entries).encode("ascii")).hexdigest()
        return {
            "enabled": True,
            "device": self.device_id,
            "kind": kind,
            "count": len(entries),
            "entries": entries,
            "digest": digest,
        }

    def apply_pull(self, manifest: dict) -> "list[dict]":
        """Decrypt a manifest from another device. Skips own-device and any
        entry that fails authentication (never silently trusts bad ciphertext)."""
        if not self.enabled() or not manifest or not manifest.get("entries"):
            return []
        out: list[dict] = []
        for env in manifest["entries"]:
            if not isinstance(env, dict):
                continue
            if env.get("device") == self.device_id:
                continue  # don't re-ingest our own push
            try:
                out.append(self.decrypt_record(env))
            except E2ESyncError:
                logger.warning("E2E sync: dropping unverifiable entry", exc_info=True)
        return out

    # ── H040 config + skills artefact collection & application ───────────────

    def collect_sync_artefacts(
        self,
        *,
        include_config: bool = True,
        include_skills: bool = True,
    ) -> list[dict[str, Any]]:
        """Collect secret-free declared settings and enabled user skills for sync."""
        artefacts: list[dict[str, Any]] = []
        if include_config:
            from agents.core import settings_db

            exported = settings_db.export_settings()
            artefacts.append(
                {
                    "artefact_type": "config",
                    "device_id": self.device_id,
                    "device_label": self.device_label,
                    "document": {
                        "format": exported["format"],
                        "exported_at": exported["exported_at"],
                        "settings": exported["settings"],
                    },
                }
            )
        if include_skills:
            sdir = self._resolved_skills_dir()
            if sdir.is_dir():
                for child in sorted(sdir.iterdir()):
                    if not child.is_dir():
                        continue
                    slug = child.name.strip().lower()
                    if not _SKILL_SLUG_RE.fullmatch(slug):
                        continue
                    if not self.is_skill_sync_enabled(slug):
                        continue
                    skill_md_path = child / "SKILL.md"
                    if not skill_md_path.is_file():
                        continue
                    try:
                        raw_md = skill_md_path.read_bytes()
                        if len(raw_md) > _MAX_SKILL_MD_BYTES:
                            continue
                        md_text = raw_md.decode("utf-8")
                    except (OSError, UnicodeDecodeError):
                        continue
                    manifest_meta: dict[str, Any] = {}
                    sidecar = child / "manifest.json"
                    if sidecar.is_file():
                        try:
                            parsed = json.loads(sidecar.read_text(encoding="utf-8"))
                            if isinstance(parsed, dict):
                                manifest_meta = parsed
                        except (OSError, ValueError):
                            pass
                    artefacts.append(
                        {
                            "artefact_type": "skill",
                            "slug": slug,
                            "skill_md": md_text,
                            "manifest": manifest_meta,
                            "sha256": hashlib.sha256(raw_md).hexdigest(),
                            "device_id": self.device_id,
                            "device_label": self.device_label,
                        }
                    )
        return artefacts

    def apply_synced_artefacts(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        """Apply decrypted config and skill artefacts from peer owner devices."""
        from agents.core import settings_db
        from agents.core.security.quarantine import detect_injection_normalized

        config_applied = 0
        config_errors: list[str] = []
        skills_applied: list[str] = []
        skills_skipped_disabled: list[str] = []
        skills_quarantined: list[dict[str, Any]] = []
        source_devices: list[str] = []

        sdir = self._resolved_skills_dir()
        for rec in records:
            if not isinstance(rec, dict):
                continue
            src_label = str(rec.get("device_label") or rec.get("device_id") or "")
            if src_label and src_label not in source_devices:
                source_devices.append(src_label)

            kind = rec.get("artefact_type")
            if kind == "config":
                doc = rec.get("document")
                changes, errs = settings_db.plan_import(doc)
                if errs:
                    config_errors.extend(errs)
                    continue
                if changes:
                    try:
                        config_applied += int(settings_db.apply_import(changes))
                    except Exception as exc:
                        config_errors.append(str(exc)[:200])
            elif kind == "skill":
                slug = str(rec.get("slug") or "").strip().lower()
                if not _SKILL_SLUG_RE.fullmatch(slug):
                    continue
                if not self.is_skill_sync_enabled(slug):
                    skills_skipped_disabled.append(slug)
                    continue
                md_text = rec.get("skill_md")
                if not isinstance(md_text, str) or not md_text.strip():
                    continue
                raw_md = md_text.encode("utf-8")
                if len(raw_md) > _MAX_SKILL_MD_BYTES:
                    continue
                expected_sha = str(rec.get("sha256") or "")
                if expected_sha and hashlib.sha256(raw_md).hexdigest() != expected_sha:
                    continue
                findings = detect_injection_normalized(md_text)
                if findings:
                    skills_quarantined.append({"slug": slug, "findings": findings[:5]})
                    continue

                target_dir = sdir / slug
                target_dir.mkdir(parents=True, exist_ok=True)
                (target_dir / "SKILL.md").write_text(md_text, encoding="utf-8")
                meta = rec.get("manifest") if isinstance(rec.get("manifest"), dict) else {}
                synced_meta = {
                    **meta,
                    "synced_from_device": rec.get("device_id", ""),
                    "synced_from_label": rec.get("device_label", ""),
                    "synced_at": time.time(),
                    "sha256": hashlib.sha256(raw_md).hexdigest(),
                }
                (target_dir / "manifest.json").write_text(
                    json.dumps(synced_meta, indent=2, sort_keys=True), encoding="utf-8"
                )
                skills_applied.append(slug)

        return {
            "config_applied": config_applied,
            "config_errors": config_errors,
            "skills_applied": skills_applied,
            "skills_skipped_disabled": skills_skipped_disabled,
            "skills_quarantined": skills_quarantined,
            "source_devices": source_devices,
        }

    def push_state(
        self,
        *,
        include_config: bool = True,
        include_skills: bool = True,
    ) -> dict[str, Any]:
        """Collect config + enabled skills, encrypt into an E2E manifest, and ship via transports."""
        if not self.enabled():
            return {
                "ok": False,
                "enabled": False,
                "reason": "sync_disabled",
                "manifest": {"enabled": False, "kind": "device_state", "count": 0, "entries": []},
            }
        artefacts = self.collect_sync_artefacts(
            include_config=include_config, include_skills=include_skills
        )
        manifest = self.build_push(artefacts, kind="device_state")
        deliveries = [t.send_manifest(manifest) for t in self._active_transports()]
        with self._lock:
            self._last_push_at = time.time()
            self._save_state()
        return {
            "ok": True,
            "enabled": True,
            "device_id": self.device_id,
            "device_label": self.device_label,
            "artefact_count": len(artefacts),
            "deliveries": deliveries,
            "manifest": manifest,
        }

    def pull_state(self, *, manifest: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Fetch inbound manifests from explicit payload, mailbox, and active transports, then apply."""
        if not self.enabled():
            return {"ok": False, "enabled": False, "reason": "sync_disabled", "records_decrypted": 0}

        manifests: list[dict[str, Any]] = []
        if isinstance(manifest, dict) and manifest.get("entries"):
            manifests.append(manifest)
        for mb in self.list_peer_manifests():
            if mb.get("device") != self.device_id:
                manifests.append(mb)
        for t in self._active_transports():
            manifests.extend(t.fetch_manifests(exclude_device=self.device_id))

        decrypted: list[dict[str, Any]] = []
        seen_digests: set[str] = set()
        for m in manifests:
            d = str(m.get("digest") or "")
            if d and d in seen_digests:
                continue
            if d:
                seen_digests.add(d)
            decrypted.extend(self.apply_pull(m))

        applied = self.apply_synced_artefacts(decrypted)
        with self._lock:
            self._last_pull_at = time.time()
            self._save_state()
        return {
            "ok": True,
            "enabled": True,
            "device_id": self.device_id,
            "device_label": self.device_label,
            "manifests_processed": len(manifests),
            "records_decrypted": len(decrypted),
            **applied,
        }

    def sync_now(self) -> dict[str, Any]:
        """Bidirectional sync pass: pull remote changes first, then push local config & skills."""
        if not self.enabled():
            return {"ok": False, "enabled": False, "reason": "sync_disabled"}
        pulled = self.pull_state()
        pushed = self.push_state()
        return {
            "ok": True,
            "enabled": True,
            "device_id": self.device_id,
            "device_label": self.device_label,
            "pull": pulled,
            "push": {k: v for k, v in pushed.items() if k != "manifest"},
        }
