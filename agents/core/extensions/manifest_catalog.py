"""Private, data-only inventory of extension Python dependency pins.

This is an audit source, not an install, consent, or activation authority. A
missing catalog beside an existing consent store is explicitly incomplete legacy
coverage; a fresh profile with neither file has an empty inventory.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path

from .consent import CONSENT_VERSION, MAX_STORE_BYTES
from .manifest import (
    _NAME,
    _VERSION,
    MAX_DECLARATIONS,
    MAX_EXTENSIONS,
    ExtensionManifest,
    ManifestError,
    _dependencies,
)

CATALOG_VERSION = 1
# The manifest schema permits 128 extensions with 64 pinned distributions each.
# Keep the file bounded while allowing that entire valid vector to fit.
MAX_CATALOG_BYTES = 2 * 1024 * 1024
_HEX_DIGEST = re.compile(r"[0-9a-f]{64}")


def _row(manifest: ExtensionManifest) -> dict:
    if not isinstance(manifest, ExtensionManifest):
        raise ValueError("invalid_manifest")
    if not isinstance(manifest.id, str) or _NAME.fullmatch(manifest.id) is None:
        raise ValueError("invalid_extension_id")
    if not isinstance(manifest.version, str) or _VERSION.fullmatch(manifest.version) is None:
        raise ValueError("invalid_extension_version")
    pins = manifest.python_requires
    if not isinstance(pins, (list, tuple)) or len(pins) > MAX_DECLARATIONS:
        raise ValueError("invalid_dependencies")
    if any(not isinstance(pin, (list, tuple)) or len(pin) != 2 for pin in pins):
        raise ValueError("invalid_dependencies")
    names = [pin[0] for pin in pins]
    try:
        duplicate_names = len(set(names)) != len(names)
    except TypeError:
        raise ValueError("invalid_dependencies") from None
    if duplicate_names:
        raise ValueError("invalid_dependencies")
    try:
        canonical = _dependencies(dict(pins), python=True)
    except (ManifestError, TypeError):
        raise ValueError("invalid_dependencies") from None
    body = {"id": manifest.id, "version": manifest.version,
            "python_requires": [list(pin) for pin in canonical]}
    digest = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":")).encode("utf-8")).hexdigest()
    return {**body, "manifest_digest": digest}


def _validate_rows(value) -> list[dict]:
    if not isinstance(value, dict) or set(value) != {"catalog_version", "rows"}:
        raise ValueError("manifest_catalog_corrupt")
    if type(value["catalog_version"]) is not int or value["catalog_version"] != CATALOG_VERSION:
        raise ValueError("manifest_catalog_corrupt")
    rows = value["rows"]
    if not isinstance(rows, list) or len(rows) > MAX_EXTENSIONS:
        raise ValueError("manifest_catalog_corrupt")
    result, seen = [], set()
    for stored in rows:
        if not isinstance(stored, dict) or set(stored) != {
            "id", "version", "python_requires", "manifest_digest"
        }:
            raise ValueError("manifest_catalog_corrupt")
        digest = stored["manifest_digest"]
        if not isinstance(digest, str) or _HEX_DIGEST.fullmatch(digest) is None:
            raise ValueError("manifest_catalog_corrupt")
        try:
            manifest = ExtensionManifest(stored["id"], stored["version"], (), (), (), (), (),
                                         tuple(tuple(pin) for pin in stored["python_requires"]))
            expected = _row(manifest)
        except (KeyError, TypeError, ValueError):
            raise ValueError("manifest_catalog_corrupt") from None
        if stored != expected or stored["id"] in seen:
            raise ValueError("manifest_catalog_corrupt")
        seen.add(stored["id"])
        result.append(expected)
    if result != sorted(result, key=lambda row: row["id"]):
        raise ValueError("manifest_catalog_corrupt")
    return result


class ExtensionManifestCatalog:
    """Bounded, profile-local metadata for registered extension manifests."""

    def __init__(self, path: Path | str | None = None, *,
                 consent_path: Path | str | None = None) -> None:
        if path is None:
            from ..paths import data_path

            path = data_path("extensions", "manifest_catalog.json")
        self.path = Path(path)
        self.consent_path = (Path(consent_path) if consent_path is not None
                             else self.path.with_name("consent.json"))

    def _read(self) -> list[dict]:
        try:
            mode = self.path.lstat().st_mode
        except FileNotFoundError:
            if self._consented_ids():
                raise ValueError("legacy_manifest_metadata_missing") from None
            return []
        except OSError:
            raise ValueError("manifest_catalog_unreadable") from None
        if not stat.S_ISREG(mode):
            raise ValueError("manifest_catalog_unreadable")
        try:
            with self.path.open("rb") as handle:
                raw = handle.read(MAX_CATALOG_BYTES + 1)
        except FileNotFoundError:
            if self._consented_ids():
                raise ValueError("legacy_manifest_metadata_missing") from None
            return []
        except OSError:
            raise ValueError("manifest_catalog_unreadable") from None
        if len(raw) > MAX_CATALOG_BYTES:
            raise ValueError("manifest_catalog_too_large")
        try:
            value = json.loads(raw)
            return _validate_rows(value)
        except (ValueError, RecursionError):
            raise ValueError("manifest_catalog_corrupt") from None

    def _consented_ids(self) -> set[str]:
        try:
            mode = self.consent_path.lstat().st_mode
        except FileNotFoundError:
            return set()
        except OSError:
            raise ValueError("legacy_consent_unreadable") from None
        if not stat.S_ISREG(mode):
            raise ValueError("legacy_consent_unreadable")
        try:
            with self.consent_path.open("rb") as handle:
                raw = handle.read(MAX_STORE_BYTES + 1)
        except FileNotFoundError:
            return set()
        except OSError:
            raise ValueError("legacy_consent_unreadable") from None
        if len(raw) > MAX_STORE_BYTES:
            raise ValueError("legacy_consent_unreadable")
        try:
            value = json.loads(raw)
            grants = value["grants"]
            if (not isinstance(value, dict) or value.get("consent_version") != CONSENT_VERSION
                    or not isinstance(grants, dict) or len(grants) > MAX_EXTENSIONS
                    or any(not isinstance(name, str) or _NAME.fullmatch(name) is None
                           for name in grants)):
                raise ValueError
        except (KeyError, TypeError, ValueError, RecursionError):
            raise ValueError("legacy_consent_unreadable") from None
        return set(grants)

    def _write(self, rows: list[dict]) -> None:
        payload = json.dumps({"catalog_version": CATALOG_VERSION, "rows": rows},
                             ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode("utf-8")
        if len(payload) > MAX_CATALOG_BYTES:
            raise ValueError("manifest_catalog_too_large")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
            raise

    def record(self, manifest: ExtensionManifest) -> None:
        """Upsert pins from an owner declaration or proved sandbox registration."""
        row = _row(manifest)
        try:
            rows = self._read()
        except ValueError as exc:
            if str(exc) not in {"legacy_manifest_metadata_missing", "legacy_consent_unreadable"}:
                raise
            # A legacy profile gains coverage one re-declared descriptor at a
            # time. Remaining grants without pins stay visibly incomplete.
            rows = []
        by_id = {existing["id"]: existing for existing in rows}
        if len(by_id) >= MAX_EXTENSIONS and row["id"] not in by_id:
            raise ValueError("extension_capacity")
        by_id[row["id"]] = row
        self._write([by_id[name] for name in sorted(by_id)])

    def remove(self, extension_id: str) -> None:
        """Delete metadata only when a caller has actually removed the package."""
        if not isinstance(extension_id, str) or _NAME.fullmatch(extension_id) is None:
            raise ValueError("invalid_extension_id")
        rows = self._read()
        if not any(row["id"] == extension_id for row in rows):
            return
        self._write([row for row in rows if row["id"] != extension_id])

    def snapshot(self) -> tuple[list[dict], list[dict]]:
        """Read-only, no imports or profile creation; bounded reasons on failures."""
        try:
            rows = self._read()
        except ValueError as exc:
            return [], [{"surface": "extension", "reason": str(exc),
                         "coverage_unavailable": True}]
        errors = []
        try:
            if self._consented_ids() - {row["id"] for row in rows}:
                errors.append({"surface": "extension", "reason": "legacy_manifest_metadata_missing",
                               "coverage_unavailable": True})
        except ValueError as exc:
            errors.append({"surface": "extension", "reason": str(exc),
                           "coverage_unavailable": True})
        return ([{"id": row["id"], "version": row["version"],
                  "python_requires": row["python_requires"]} for row in rows], errors)


__all__ = ["ExtensionManifestCatalog"]
