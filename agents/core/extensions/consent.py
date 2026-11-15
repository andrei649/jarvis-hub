"""What the owner agreed an extension may declare — and the hash that pins it.

S1 could describe an extension. It could not record that anyone had *agreed* to
one, because nothing could run and there was nothing to agree to. S2 changes that,
and the change this file exists to prevent is the quiet one: an extension the owner
approved at version 1.0.0 shipping 1.1.0 that also declares a command, or an event,
or a tool that was not on the screen when they said yes.

So consent is stored as the SHA-256 of the exact declared set, not as a boolean.
Re-reading a manifest whose declarations moved does not silently pass — it comes
back ``changed``, with the difference, so the owner is asked again about what is
actually different. That is the one mechanism in Hermes' capability model worth
copying verbatim (acp-mcp-dev.plugin-capabilities); the rest of Nerva's enforcement
already lives in plugin_gate.py and is stronger than a consent list.

Three rules hold everywhere below:

* **Default off.** No record means not granted. There is no implicit consent.
* **Fail closed.** An unreadable, oversized or malformed store is *not granted* —
  never "granted because we could not check".
* **Consent is not authority.** A grant says the owner saw these declarations. It
  does not run anything, does not verify a signature and does not admit a package;
  the runtime still requires an isolated registration that matches.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import secrets
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .manifest import MAX_EXTENSIONS, ExtensionManifest
from .store_lock import StoreLockError, locked_store

CONSENT_VERSION = 1
MAX_STORE_BYTES = 256 * 1024
GRANTED = "granted"
NOT_GRANTED = "not_granted"
CHANGED = "changed"
_REVISION_RE = re.compile(r"[0-9a-f]{64}\Z")
_LEGACY_REVISION_DOMAIN = b"nerva-extension-consent-legacy-revision-v1\0"


def declared_digest(manifest: ExtensionManifest) -> str:
    """SHA-256 over exactly what a consent screen would show.

    The version is deliberately *not* in the digest: a bugfix release that declares
    the same tools, commands and events is the same agreement, and re-asking on
    every patch trains an owner to click through. What must never change silently
    is the *surface*, and that is what this covers.
    """
    declaration = {
        "consent_version": CONSENT_VERSION,
        "id": manifest.id,
        "capabilities": list(manifest.capabilities),
        "tools": list(manifest.qualified_tools),
        "commands": list(manifest.commands),
        "events": list(manifest.events),
    }
    if manifest.command_requires_args:
        declaration["command_requires_args"] = list(manifest.command_requires_args)
    canonical = json.dumps(declaration, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ConsentDecision:
    state: str
    digest: str
    granted_digest: str | None = None
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    # Private lifecycle fence. Deliberately omitted from as_dict() so existing
    # HTTP/CLI payloads remain stable.
    grant_revision: str | None = None

    @property
    def allowed(self) -> bool:
        return self.state == GRANTED

    def as_dict(self) -> dict:
        return {"consent": self.state, "declared_digest": self.digest,
                "granted_digest": self.granted_digest,
                "added_declarations": list(self.added),
                "removed_declarations": list(self.removed)}


def _surface(manifest: ExtensionManifest) -> set[str]:
    return ({f"capability:{name}" for name in manifest.capabilities}
            | {f"tool:{name}" for name in manifest.qualified_tools}
            | {f"command:{name}" for name in manifest.commands}
            | {f"command_requires_args:{name}" for name in manifest.command_requires_args}
            | {f"event:{name}" for name in manifest.events})


class ExtensionConsentStore:
    """A bounded JSON record of what the owner agreed each extension may declare."""

    def __init__(self, path: Path | str | None = None, *, clock=None) -> None:
        if path is None:
            from ..paths import data_path
            path = data_path("extensions", "consent.json")
        self._path = Path(path)
        self._clock = clock

    # ── persistence ──────────────────────────────────────────────────────────
    def _read(self) -> dict:
        try:
            if self._path.is_symlink():
                return {}
            with self._path.open("rb") as handle:
                raw = handle.read(MAX_STORE_BYTES + 1)
            if len(raw) > MAX_STORE_BYTES:
                return {}
            value = json.loads(raw)
        except (OSError, ValueError, RecursionError):
            # Fail closed. An unreadable store is not a granted one.
            return {}
        if not isinstance(value, dict) or value.get("consent_version") != CONSENT_VERSION:
            return {}
        grants = value.get("grants")
        if not isinstance(grants, dict) or len(grants) > MAX_EXTENSIONS:
            return {}
        valid = {}
        for name, row in grants.items():
            if (not isinstance(name, str) or not isinstance(row, dict)
                    or not isinstance(row.get("declared_digest"), str)
                    or len(row["declared_digest"]) != 64):
                continue
            # Missing means a legacy row. Presence is explicit: null, uppercase,
            # short, or non-string revisions are malformed and cannot grant.
            if "grant_revision" in row and (
                    not isinstance(row["grant_revision"], str)
                    or _REVISION_RE.fullmatch(row["grant_revision"]) is None):
                continue
            valid[name] = row
        return valid

    @staticmethod
    def _legacy_revision(row: dict) -> str:
        """Stable, domain-separated fence for an unmodified legacy grant row."""
        canonical = json.dumps(row, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(_LEGACY_REVISION_DOMAIN + canonical).hexdigest()

    def _write(self, grants: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"consent_version": CONSENT_VERSION, "grants": grants}
        descriptor, temporary = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
            raise

    # ── api ──────────────────────────────────────────────────────────────────
    def check(self, manifest: ExtensionManifest) -> ConsentDecision:
        """What the owner agreed to, compared with what this manifest declares now."""
        digest = declared_digest(manifest)
        row = self._read().get(manifest.id)
        if row is None:
            return ConsentDecision(NOT_GRANTED, digest)
        if row["declared_digest"] == digest:
            revision = row.get("grant_revision")
            if revision is None:
                revision = self._legacy_revision(row)
            return ConsentDecision(GRANTED, digest, row["declared_digest"],
                                   grant_revision=revision)
        # The owner agreed to something; this is not it. Say what moved rather than
        # re-asking for a blanket yes.
        previous = set(row.get("declarations") or ())
        current = _surface(manifest)
        return ConsentDecision(CHANGED, digest, row["declared_digest"],
                               tuple(sorted(current - previous)),
                               tuple(sorted(previous - current)))

    def grant(self, manifest: ExtensionManifest) -> ConsentDecision:
        """Record consent for exactly these declarations. Idempotent for the same set."""
        # Both owner paths persist pins before consent becomes durable.
        from .manifest_catalog import ExtensionManifestCatalog

        catalog = ExtensionManifestCatalog(self._path.with_name("manifest_catalog.json"),
                                           consent_path=self._path)
        try:
            with locked_store(self._path):
                grants = self._read()
                if len(grants) >= MAX_EXTENSIONS and manifest.id not in grants:
                    raise ValueError("extension_capacity")
                # Both the CLI and HTTP owner paths arrive here. Persist the exact
                # Python pins as an auditable declaration before consent is durable.
                try:
                    catalog.record(manifest)
                except ValueError:
                    raise
                except Exception:
                    raise ValueError("manifest_catalog_unavailable") from None
                digest = declared_digest(manifest)
                row = {"declared_digest": digest, "version": manifest.version,
                       "declarations": sorted(_surface(manifest))}
                previous = grants.get(manifest.id)
                if previous is not None and previous.get("declared_digest") == digest:
                    revision = previous.get("grant_revision")
                    if revision is None:
                        # Explicitly approving a legacy row creates a new durable epoch.
                        revision = secrets.token_hex(32)
                else:
                    revision = secrets.token_hex(32)
                row["grant_revision"] = revision
                if self._clock is not None:
                    row["granted_at"] = float(self._clock())
                grants[manifest.id] = row
                self._write(grants)
                return ConsentDecision(GRANTED, digest, digest, grant_revision=revision)
        except StoreLockError:
            raise ValueError("consent_unavailable") from None

    def revoke(self, extension_id: str) -> bool:
        try:
            with locked_store(self._path):
                grants = self._read()
                if extension_id not in grants:
                    return False
                del grants[extension_id]
                self._write(grants)
                return True
        except StoreLockError:
            raise ValueError("consent_unavailable") from None

    def granted_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._read()))


__all__ = ["CHANGED", "CONSENT_VERSION", "GRANTED", "NOT_GRANTED", "ConsentDecision",
           "ExtensionConsentStore", "declared_digest"]
