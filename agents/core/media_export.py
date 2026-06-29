"""media_export.py — 0.46: export a selection of cataloged media as a bundle.

The `MediaCatalog` (0.46) records *what* was generated; this packages a chosen
subset into a portable **export bundle** — a zip containing the media files plus
a `manifest.json` describing them. The selection is just a list of catalog item
dicts (e.g. from ``catalog.search(...)`` / ``catalog.all()``), so this module is
**decoupled from `MediaCatalog`** (no import → no cycle) and pure apart from the
filesystem reads it must do to package real files.

Honest about gaps: an item whose `path` no longer exists on disk is reported in
``missing`` rather than silently dropped, so a bundle never *looks* complete when
a source file has vanished.
"""

from __future__ import annotations

import json
import os
import zipfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


def _entry(item: Mapping[str, Any]) -> dict:
    """One manifest entry for a catalog item, with on-disk existence + size."""
    path = str(item.get("path") or "")
    exists = bool(path) and os.path.isfile(path)
    size = os.path.getsize(path) if exists else 0
    return {
        "id": item.get("id"),
        "kind": item.get("kind"),
        "prompt": item.get("prompt"),
        "path": path,
        "tags": list(item.get("tags") or []),
        "created_at": item.get("created_at"),
        "exists": exists,
        "bytes": size,
    }


def build_manifest(items: Iterable[Mapping[str, Any]], *, now: float) -> dict:
    """Describe an export selection without writing anything.

    Returns ``{generated_at, count, present, total_bytes, items, missing}`` where
    ``missing`` is the ids whose ``path`` is absent on disk (``count`` counts every
    selected item; ``present`` counts only those with a real file).
    """
    entries = [_entry(it) for it in items]
    missing = [e["id"] for e in entries if not e["exists"]]
    return {
        "generated_at": float(now),
        "count": len(entries),
        "present": sum(1 for e in entries if e["exists"]),
        "total_bytes": sum(e["bytes"] for e in entries),
        "items": entries,
        "missing": missing,
    }


def write_bundle(items: Iterable[Mapping[str, Any]], dest: str | Path, *, now: float) -> dict:
    """Write a ``.zip`` bundle to *dest*: every existing media file under
    ``media/<id>__<filename>`` plus a top-level ``manifest.json``.

    Returns the manifest augmented with ``{bundle, bundled}`` (the bundle path and
    how many files were actually written). Missing-on-disk items are recorded in
    the manifest's ``missing`` and simply skipped in the archive — never faked.
    """
    items = list(items)
    manifest = build_manifest(items, now=now)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    bundled = 0
    seen: set[str] = set()
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for entry in manifest["items"]:
            if not entry["exists"]:
                continue
            # Namespace by id so two items with the same basename can't collide.
            arcname = f"media/{entry['id']}__{Path(entry['path']).name}"
            if arcname in seen:  # defensive: identical id+name selected twice
                continue
            seen.add(arcname)
            zf.write(entry["path"], arcname)
            entry["archived_as"] = arcname
            bundled += 1
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    return {**manifest, "bundle": str(dest), "bundled": bundled}
