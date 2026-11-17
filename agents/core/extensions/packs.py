"""H571 — a reproducible set of extensions, pinned by exact content and installed one card each.

Hermes' plugin packs pin every plugin to an exact 40-character commit (tags and branches
refused), may seed non-secret config but never consent, run the per-plugin consent
flow on install (never bulk-granted) and are capped at 1 MiB
(acp-mcp-dev.plugin-packs). Nerva's pack is the same contract over what Nerva installs:

.. code-block:: json

    {"pack_version": 1,
     "extensions": [
       {"id": "boats", "version": "1.0.0", "directory": "boats",
        "declared_digest": "<sha256>", "source_sha256": "<sha256>", "test_sha256": "<sha256>"},
       {"id": "tides", "version": "2.1.0", "distribution": "nerva-tides",
        "declared_digest": "<sha256>", "source_sha256": "<sha256>", "test_sha256": "<sha256>"}
     ]}

* **Exact pins only.** Each entry names one exact version and the sha256 of its
  ``main.py``, its ``test_extension.py`` and its declared surface (the consent digest).
  There is no range, tag or "latest": a pin is 64 lowercase hex characters or the pack
  is refused. Nerva fetches no remote code, so an entry's bytes come from a directory
  beside the pack or an installed distribution, and they must hash to the pins.
* **Nothing but pins.** Consent (``consent``, ``granted_capabilities``,
  ``capabilities_consent``) and config seeds are refused by name: a pack cannot carry an
  agreement, and Nerva extensions have no host configuration to seed.
* **One card each.** Installing a pack verifies every entry first (any mismatch refuses
  the whole pack before anything is submitted), then submits each extension separately
  in dependency order — one ``extensions.install`` card per extension, each accepted on
  its own, and each still needing its own consent and activation afterwards.
* **Bounded.** 1 MiB, at most 64 entries, unique ids, relative directories that stay
  inside the pack's folder and are not symlinks.
"""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath

from .manifest import ManifestError, _unique_object, validate_catalog
from .submission import AuthoredExtension, SubmissionError, read_directory, read_installed

PACK_VERSION = 1
MAX_PACK_BYTES = 1024 * 1024
MAX_PACK_EXTENSIONS = 64
_PIN = re.compile(r"[0-9a-f]{64}")
_PIN_FIELDS = ("declared_digest", "source_sha256", "test_sha256")
_REFUSED_KEYS = frozenset({"consent", "granted_capabilities", "capabilities_consent", "config", "config_seed",
                           "config_seeds", "settings", "secrets", "env"})
_ENTRY_KEYS = frozenset({"id", "version", "directory", "distribution", *_PIN_FIELDS})
_DISTRIBUTION = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9])?")


class PackError(ValueError):
    def __init__(self, reason: str, index: int | None = None):
        super().__init__(reason)
        self.reason = reason
        self.index = index


def _pins(authored: AuthoredExtension) -> dict:
    from .consent import declared_digest

    return {"declared_digest": declared_digest(authored.manifest), "source_sha256": authored.source_sha256,
            "test_sha256": authored.test_sha256}


def parse_pack(raw: bytes) -> list[dict]:
    """Validate a pack's shape. Returns its entries; reads no extension."""
    if len(raw) > MAX_PACK_BYTES:
        raise PackError("pack_too_large")
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except ManifestError:
        raise PackError("duplicate_json_key") from None
    except (ValueError, RecursionError):
        raise PackError("pack_unreadable") from None
    if not isinstance(value, dict):
        raise PackError("pack_unreadable")
    if set(value) & _REFUSED_KEYS:
        raise PackError("pack_carries_consent_or_config")
    if set(value) != {"pack_version", "extensions"}:
        raise PackError("invalid_pack_fields")
    if type(value["pack_version"]) is not int or value["pack_version"] != PACK_VERSION:
        raise PackError("unsupported_pack_version")
    entries = value["extensions"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_PACK_EXTENSIONS:
        raise PackError("pack_capacity")
    seen = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise PackError("invalid_entry", index)
        if set(entry) & _REFUSED_KEYS:
            raise PackError("pack_carries_consent_or_config", index)
        if set(entry) - _ENTRY_KEYS or not {"id", "version", *_PIN_FIELDS} <= set(entry):
            raise PackError("invalid_entry_fields", index)
        if ("directory" in entry) == ("distribution" in entry):
            raise PackError("entry_needs_one_source", index)
        if any(not isinstance(entry[name], str) or _PIN.fullmatch(entry[name]) is None for name in _PIN_FIELDS):
            raise PackError("pin_not_exact", index)
        if not isinstance(entry["id"], str) or not isinstance(entry["version"], str):
            raise PackError("invalid_entry", index)
        if entry["id"] in seen:
            raise PackError("extension_collision", index)
        seen.add(entry["id"])
        if "directory" in entry:
            directory = entry["directory"]
            if (not isinstance(directory, str) or not directory or "\\" in directory
                    or PurePosixPath(directory).is_absolute() or ".." in PurePosixPath(directory).parts):
                raise PackError("directory_outside_pack", index)
        elif not isinstance(entry["distribution"], str) or _DISTRIBUTION.fullmatch(entry["distribution"]) is None:
            raise PackError("invalid_entry", index)
    return entries


def _read_entry(entry: dict, base: Path, index: int, distributions=None) -> AuthoredExtension:
    try:
        if "directory" in entry:
            target = base / PurePosixPath(entry["directory"])
            resolved = target.resolve()
            if (target.is_symlink() or resolved == base.resolve()
                    or base.resolve() not in resolved.parents):
                raise PackError("directory_outside_pack", index)
            authored = read_directory(target)
            authored = AuthoredExtension(authored.manifest, authored.code, authored.test_code, {"kind": "pack"})
        else:
            authored = read_installed(entry["id"], distributions=distributions)
            if re.sub(r"[-_.]+", "-", authored.provenance.get("distribution", "")).lower() != re.sub(
                    r"[-_.]+", "-", entry["distribution"]).lower():
                raise PackError("distribution_mismatch", index)
    except SubmissionError as exc:
        raise PackError(exc.reason, index) from None
    if authored.manifest.id != entry["id"] or authored.manifest.version != entry["version"]:
        raise PackError("version_mismatch", index)
    if _pins(authored) != {name: entry[name] for name in _PIN_FIELDS}:
        raise PackError("pin_mismatch", index)
    return authored


def load_pack(path: str | Path, *, distributions=None) -> list[AuthoredExtension]:
    """Every pinned extension, verified against its pins, in dependency order.

    Any entry that does not match refuses the whole pack: nothing is submitted for a
    pack that is not exactly what it says.
    """
    pack = Path(path)
    if pack.is_symlink() or not pack.is_file():
        raise PackError("pack_unreadable")
    try:
        with pack.open("rb") as handle:
            raw = handle.read(MAX_PACK_BYTES + 1)
    except OSError:
        raise PackError("pack_unreadable") from None
    entries = parse_pack(raw)
    base = pack.parent
    authored = [_read_entry(entry, base, index, distributions) for index, entry in enumerate(entries)]
    try:
        catalog = validate_catalog([item.manifest for item in authored])
    except ManifestError as exc:
        raise PackError(str(exc)) from None
    if catalog["issues"]:
        raise PackError(catalog["issues"][0]["reason"])
    by_id = {item.manifest.id: item for item in authored}
    return [by_id[name] for name in catalog["order"]]


def export_pack(directories, out: str | Path) -> dict:
    """Pin author directories into a pack file next to them (relative paths only)."""
    out = Path(out)
    base = out.parent.resolve()
    entries = []
    for directory in directories:
        target = Path(directory)
        try:
            authored = read_directory(target)
        except SubmissionError as exc:
            raise PackError(exc.reason) from None
        resolved = target.resolve()
        if base not in resolved.parents:
            raise PackError("directory_outside_pack")
        entries.append({"id": authored.manifest.id, "version": authored.manifest.version,
                        "directory": resolved.relative_to(base).as_posix(), **_pins(authored)})
    pack = {"pack_version": PACK_VERSION, "extensions": entries}
    raw = (json.dumps(pack, indent=2, sort_keys=True) + "\n").encode("utf-8")
    parse_pack(raw)
    out.write_bytes(raw)
    return pack


__all__ = ["MAX_PACK_BYTES", "MAX_PACK_EXTENSIONS", "PACK_VERSION", "PackError", "export_pack", "load_pack",
           "parse_pack"]
