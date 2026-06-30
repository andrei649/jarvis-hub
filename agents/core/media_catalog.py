"""media_catalog.py — 0.46: a searchable catalog/timeline of generated media.

``media_gen.py`` *generates* image/thumbnail/video through governed backends but
keeps no record of what was produced — so there's no way to browse, search, or
build a timeline of generated media. This adds that catalog.

Design mirrors the 0.34/0.37 stores: a single **bounded, atomically-written,
corrupt/missing-file-safe** JSON array, and **opt-in / default-off** — nothing in
``media_gen`` records to a catalog unless a caller wires one, so the default
generation path is byte-for-byte unchanged.

Item shape (JSON-safe)::

    {id, kind, prompt, path, backend, cloud, created_at, tags, meta}

``kind`` is validated against ``media_gen.KINDS`` so the catalog can't drift from
what the generator actually produces.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import uuid
from pathlib import Path

from agents.core.media_gen import KINDS
from agents.core.paths import data_path

_DEFAULT_FILE = data_path("media") / "catalog.json"
_DEFAULT_MAX_KEEP = 10_000


class MediaCatalog:
    """Bounded, atomically-written JSON catalog of generated media items."""

    def __init__(self, path: Path | str | None = None, *, max_keep: int = _DEFAULT_MAX_KEEP) -> None:
        self._path = Path(path) if path is not None else _DEFAULT_FILE
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._max_keep = max(1, int(max_keep))

    # ── persistence (mirrors the 0.34/0.37 stores) ────────────────────────────
    def _read(self) -> list[dict]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError, OSError):
            return []
        return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []

    def _write_atomic(self, items: list[dict]) -> None:
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(items, fh, ensure_ascii=False)
            os.replace(tmp, self._path)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    # ── api ────────────────────────────────────────────────────────────────────
    def add(
        self,
        *,
        kind: str,
        prompt: str,
        path: str,
        now: float,
        backend: str = "",
        cloud: bool = False,
        tags: list[str] | None = None,
        meta: dict | None = None,
    ) -> dict:
        """Catalog one generated media item. ``now`` is the caller's clock (kept
        injectable for tests). Raises ``ValueError`` for an unknown ``kind``."""
        if kind not in KINDS:
            raise ValueError(f"unknown media kind: {kind!r} (expected one of {KINDS})")
        item = {
            "id": "md-" + uuid.uuid4().hex[:12],
            "kind": kind,
            "prompt": str(prompt),
            "path": str(path),
            "backend": str(backend),
            "cloud": bool(cloud),
            "created_at": float(now),
            "tags": [str(t) for t in tags] if tags else [],
            "meta": dict(meta) if isinstance(meta, dict) else {},
        }
        items = self._read()
        items.append(item)
        # bound the catalog: evict the oldest first.
        if len(items) > self._max_keep:
            items.sort(key=lambda r: float(r.get("created_at", 0)))
            items = items[-self._max_keep:]
        self._write_atomic(items)
        return dict(item)

    def get(self, item_id: str) -> dict | None:
        for r in self._read():
            if r.get("id") == item_id:
                return dict(r)
        return None

    def remove(self, item_id: str) -> bool:
        """Drop one item from the catalog. True if it existed."""
        items = self._read()
        kept = [r for r in items if r.get("id") != item_id]
        if len(kept) == len(items):
            return False
        self._write_atomic(kept)
        return True

    def all(self) -> list[dict]:
        """Every item, newest-created first (the default gallery order)."""
        items = [dict(r) for r in self._read()]
        items.sort(key=lambda r: float(r.get("created_at", 0)), reverse=True)
        return items

    def timeline(self, *, since: float | None = None, until: float | None = None) -> list[dict]:
        """Items in chronological (oldest-first) order, optionally time-bounded."""
        out = []
        for r in self._read():
            ts = float(r.get("created_at", 0))
            if since is not None and ts < since:
                continue
            if until is not None and ts > until:
                continue
            out.append(dict(r))
        out.sort(key=lambda r: float(r.get("created_at", 0)))
        return out

    def search(
        self,
        query: str | None = None,
        *,
        kind: str | None = None,
        tag: str | None = None,
        since: float | None = None,
        until: float | None = None,
    ) -> list[dict]:
        """Filter the catalog (newest-first). All criteria AND together:

        * ``query`` — case-insensitive substring of the prompt
        * ``kind``  — exact media kind
        * ``tag``   — present in the item's tags
        * ``since``/``until`` — inclusive ``created_at`` bounds
        """
        q = query.lower() if query else None
        out = []
        for r in self._read():
            if q is not None and q not in str(r.get("prompt", "")).lower():
                continue
            if kind is not None and r.get("kind") != kind:
                continue
            if tag is not None and tag not in (r.get("tags") or []):
                continue
            ts = float(r.get("created_at", 0))
            if since is not None and ts < since:
                continue
            if until is not None and ts > until:
                continue
            out.append(dict(r))
        out.sort(key=lambda r: float(r.get("created_at", 0)), reverse=True)
        return out

    def stats(self) -> dict:
        """Total + per-kind counts + how many came from a (paid) cloud backend."""
        items = self._read()
        by_kind: dict[str, int] = {}
        cloud = 0
        for r in items:
            by_kind[r.get("kind", "?")] = by_kind.get(r.get("kind", "?"), 0) + 1
            if r.get("cloud"):
                cloud += 1
        return {"total": len(items), "cloud": cloud, "by_kind": by_kind}


def default_catalog_if_enabled(env=None) -> MediaCatalog | None:
    """Return a default-path :class:`MediaCatalog` when ``JARVIS_MEDIA_CATALOG`` is
    set, else ``None`` — the opt-in switch for cataloging generated media. Prompts
    are sensitive, so recording (and the read surface) stay off unless the owner
    enables it; the generation path is byte-identical when this returns ``None``."""
    e = os.environ if env is None else env
    return MediaCatalog() if e.get("JARVIS_MEDIA_CATALOG") else None
