"""Extension declarations shipped in installed Python distributions, read without importing.

Hermes lets a pip-distributed plugin declare its capabilities through a companion
entry-point group that is read from installed metadata without importing the code
(acp-mcp-dev.plugin-capabilities, .plugin-pip-distribution). Nerva does the same with
the ``nerva.extensions`` group:

.. code-block:: toml

    [project.entry-points."nerva.extensions"]
    boats = "nerva_boats:extension"

names the descriptor ``nerva_boats/extension.json`` inside that distribution. This
module reads ``entry_points.txt`` and ``RECORD`` from the distribution's metadata and
then that one JSON file. It **never** calls ``EntryPoint.load()``, never imports the
named module and never executes anything; the descriptor goes through the same
parser as a file the owner names (``manifest.parse_manifest``).

A declaration found here is only a declaration. A pip install does not make an
extension callable: code runs only as a signed acquired package, so an installed
distribution reaches execution only as a signed acquired package, after the
sandbox verification and the ``skill.install`` approval card.
"""

from __future__ import annotations

import json
import logging
import os
import re
import stat
from importlib import metadata
from pathlib import Path, PurePosixPath

from .manifest import (
    MAX_EXTENSIONS,
    MAX_MANIFEST_BYTES,
    ManifestError,
    _unique_object,
    parse_manifest,
)

logger = logging.getLogger("jarvis.extensions.distribution")

ENTRY_POINT_GROUP = "nerva.extensions"
MAX_DISTRIBUTIONS = 4096
_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")
_MODULE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}(?:\.[A-Za-z_][A-Za-z0-9_]{0,63}){0,7}")
_RESOURCE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")


def descriptor_member(value: str) -> PurePosixPath:
    """``pkg.sub:stem`` -> ``pkg/sub/stem.json``; anything else is refused."""
    if not isinstance(value, str) or value.count(":") != 1:
        raise ManifestError("invalid_entry_point")
    module, resource = (part.strip() for part in value.split(":"))
    if _MODULE.fullmatch(module) is None or _RESOURCE.fullmatch(resource) is None:
        raise ManifestError("invalid_entry_point")
    return PurePosixPath(*module.split("."), f"{resource}.json")


def _recorded(dist, member: PurePosixPath) -> bool:
    try:
        files = dist.files or ()
    except Exception:  # noqa: BLE001 - unreadable RECORD means "not shipped"
        return False
    return any(PurePosixPath(str(item)) == member for item in files)


def read_installed_descriptor(dist, member: PurePosixPath):
    """Read one recorded descriptor from an installed distribution, bounded and no-follow."""
    if not _recorded(dist, member):
        raise ManifestError("descriptor_not_recorded")
    try:
        path = Path(dist.locate_file(str(member)))
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ManifestError("manifest_not_regular_file")
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                raw = handle.read(MAX_MANIFEST_BYTES + 1)
        finally:
            os.close(descriptor)
    except ManifestError:
        raise
    except (OSError, TypeError, ValueError):
        raise ManifestError("manifest_unreadable") from None
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ManifestError("manifest_too_large")
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except ManifestError:
        raise
    except (ValueError, RecursionError):
        raise ManifestError("manifest_unreadable") from None
    return parse_manifest(value), path


def installed_declarations(*, distributions=None) -> dict:
    """Every ``nerva.extensions`` declaration in this interpreter, parsed and never imported.

    Returns ``{"extensions": [...], "errors": [...]}``. Each extension row carries the
    parsed manifest, the distribution name and version and the descriptor path; each
    error row a bounded reason. A bad entry is skipped on its own and never hides the
    others.
    """
    rows, errors, seen = [], [], set()
    if distributions is None:
        distributions = metadata.distributions()
    for index, dist in enumerate(distributions):
        if index >= MAX_DISTRIBUTIONS:
            errors.append({"reason": "distribution_capacity"})
            break
        try:
            entry_points = [ep for ep in dist.entry_points if ep.group == ENTRY_POINT_GROUP]
            dist_name = str(dist.metadata["Name"] or "")[:128]
            dist_version = str(dist.version or "")[:64]
        except Exception:  # noqa: BLE001 - one broken distribution never hides the rest
            # Unrelated broken metadata is not an extension error: skip it, visibly in the log.
            logger.debug("skipping a distribution whose metadata cannot be read")
            continue
        for entry in entry_points:
            if len(rows) >= MAX_EXTENSIONS:
                errors.append({"reason": "extension_capacity"})
                return {"extensions": rows, "errors": errors}
            name = entry.name if _NAME.fullmatch(str(entry.name)) else None
            row_error = {"distribution": dist_name, "entry_point": name or "", "reason": ""}
            try:
                if name is None:
                    raise ManifestError("invalid_entry_point")
                member = descriptor_member(entry.value)
                manifest, path = read_installed_descriptor(dist, member)
                if manifest.id != name:
                    raise ManifestError("entry_point_id_mismatch")
                if name in seen:
                    raise ManifestError("extension_collision")
            except ManifestError as exc:
                errors.append({**row_error, "reason": str(exc)})
                continue
            seen.add(name)
            rows.append({"manifest": manifest, "distribution": dist_name, "distribution_version": dist_version,
                         "member": str(member), "path": path, "dist": dist})
    return {"extensions": rows, "errors": errors}


def find_installed(extension_id: str, *, distributions=None) -> dict | None:
    for row in installed_declarations(distributions=distributions)["extensions"]:
        if row["manifest"].id == extension_id:
            return row
    return None


__all__ = ["ENTRY_POINT_GROUP", "descriptor_member", "find_installed", "installed_declarations",
           "read_installed_descriptor"]
