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
import math
import os
import tempfile
import uuid
from pathlib import Path

from agents.core.env_config import env_flag, truthy
from agents.core.media_gen import KINDS
from agents.core.paths import data_path

_DEFAULT_FILE = data_path("media") / "catalog.json"
_DEFAULT_MAX_KEEP = 10_000
_MAX_SEARCH_LIMIT = 100
_MAX_FILE_BYTES = 10_000_000
_MAX_ITEM_BYTES = 32_768
_MAX_ID_CHARS = 64
_MAX_KIND_CHARS = 32
_MAX_PROMPT_CHARS = 4_096
_MAX_PATH_CHARS = 2_048
_MAX_BACKEND_CHARS = 128
_MAX_TAGS = 32
_MAX_TAG_CHARS = 64
_MAX_META_KEYS = 32
_MAX_META_KEY_CHARS = 64
_MAX_META_BYTES = 16_384


def _created_at(item: dict) -> float:
    try:
        value = float(item.get("created_at", 0))
    except (OverflowError, TypeError, ValueError):
        return 0.0
    return value if math.isfinite(value) else 0.0


class MediaCatalog:
    """Bounded, atomically-written JSON catalog of generated media items."""

    def __init__(self, path: Path | str | None = None, *, max_keep: int = _DEFAULT_MAX_KEEP) -> None:
        self._path = Path(path) if path is not None else _DEFAULT_FILE
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._max_keep = max(1, int(max_keep))

    # ── persistence (mirrors the 0.34/0.37 stores) ────────────────────────────
    @staticmethod
    def _encoded_json(value, *, label: str) -> bytes:
        try:
            encoded = json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} must be finite JSON data") from exc
        return encoded

    def _validated_record(self, item: dict) -> dict:
        if not isinstance(item, dict):
            raise ValueError("catalog invalid record")
        normalized = dict(item)
        for field, limit in (
            ("id", _MAX_ID_CHARS),
            ("kind", _MAX_KIND_CHARS),
            ("prompt", _MAX_PROMPT_CHARS),
            ("path", _MAX_PATH_CHARS),
            ("backend", _MAX_BACKEND_CHARS),
        ):
            if field not in normalized:
                continue
            value = normalized[field]
            if not isinstance(value, str) or len(value) > limit:
                raise ValueError("catalog invalid record")
        if "cloud" in normalized and not isinstance(normalized["cloud"], bool):
            raise ValueError("catalog invalid record")
        tags = normalized.get("tags", [])
        if (
            not isinstance(tags, list)
            or len(tags) > _MAX_TAGS
            or any(not isinstance(tag, str) or len(tag) > _MAX_TAG_CHARS for tag in tags)
        ):
            raise ValueError("catalog invalid record")
        meta = normalized.get("meta", {})
        if not isinstance(meta, dict) or len(meta) > _MAX_META_KEYS:
            raise ValueError("catalog invalid record")
        if any(
            not isinstance(key, str) or len(key) > _MAX_META_KEY_CHARS
            for key in meta
        ):
            raise ValueError("catalog invalid record")
        if len(self._encoded_json(meta, label="meta")) > _MAX_META_BYTES:
            raise ValueError("catalog invalid record")
        normalized["created_at"] = _created_at(normalized)
        if len(self._encoded_json(normalized, label="item")) > _MAX_ITEM_BYTES:
            raise ValueError("catalog invalid record")
        return normalized

    def _read(self, *, strict: bool = False) -> list[dict]:
        try:
            size = self._path.stat().st_size
        except FileNotFoundError:
            return []
        except OSError as exc:
            if strict:
                raise ValueError("catalog store is unreadable") from exc
            return []
        if size > _MAX_FILE_BYTES:
            if strict:
                raise ValueError("catalog size limit exceeded")
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            if strict:
                raise ValueError("catalog store is unreadable") from exc
            return []
        if not isinstance(data, list):
            if strict:
                raise ValueError("catalog store is unreadable")
            return []
        if len(data) > self._max_keep:
            if strict:
                raise ValueError("catalog record limit exceeded")
            data = data[-self._max_keep :]
        items = []
        for row in data:
            try:
                items.append(self._validated_record(row))
            except ValueError as exc:
                if strict:
                    raise ValueError("catalog invalid record") from exc
        return items

    def _write_atomic(self, items: list[dict]) -> None:
        encoded = self._encoded_json(items, label="catalog")
        if len(encoded) > _MAX_FILE_BYTES:
            raise ValueError("catalog size limit exceeded")
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(encoded.decode("utf-8"))
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
        bounded_prompt = str(prompt)
        bounded_path = str(path)
        bounded_backend = str(backend)
        if len(bounded_prompt) > _MAX_PROMPT_CHARS:
            raise ValueError("prompt exceeds its size limit")
        if len(bounded_path) > _MAX_PATH_CHARS:
            raise ValueError("path exceeds its size limit")
        if len(bounded_backend) > _MAX_BACKEND_CHARS:
            raise ValueError("backend exceeds its size limit")
        if tags is not None and not isinstance(tags, list):
            raise ValueError("tags must be a list")
        bounded_tags = [str(tag) for tag in (tags or [])]
        if len(bounded_tags) > _MAX_TAGS:
            raise ValueError("tags exceed their count limit")
        if any(len(tag) > _MAX_TAG_CHARS for tag in bounded_tags):
            raise ValueError("tag exceeds its size limit")
        bounded_meta = dict(meta) if isinstance(meta, dict) else {}
        if meta is not None and not isinstance(meta, dict):
            raise ValueError("meta must be an object")
        if len(bounded_meta) > _MAX_META_KEYS:
            raise ValueError("meta exceeds its key limit")
        if len(self._encoded_json(bounded_meta, label="meta")) > _MAX_META_BYTES:
            raise ValueError("meta exceeds its size limit")
        raw_item = {
            "id": "md-" + uuid.uuid4().hex[:12],
            "kind": kind,
            "prompt": bounded_prompt,
            "path": bounded_path,
            "backend": bounded_backend,
            "cloud": bool(cloud),
            "created_at": _created_at({"created_at": now}),
            "tags": bounded_tags,
            "meta": bounded_meta,
        }
        if len(self._encoded_json(raw_item, label="item")) > _MAX_ITEM_BYTES:
            raise ValueError("item size limit exceeded")
        item = self._validated_record(raw_item)
        items = self._read(strict=True)
        items.append(item)
        # bound the catalog: evict the oldest first.
        if len(items) > self._max_keep:
            items.sort(key=_created_at)
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
        items = self._read(strict=True)
        kept = [r for r in items if r.get("id") != item_id]
        if len(kept) == len(items):
            return False
        self._write_atomic(kept)
        return True

    def all(self) -> list[dict]:
        """Every item, newest-created first (the default gallery order)."""
        items = [dict(r) for r in self._read()]
        items.sort(key=_created_at, reverse=True)
        return items

    def timeline(self, *, since: float | None = None, until: float | None = None) -> list[dict]:
        """Items in chronological (oldest-first) order, optionally time-bounded."""
        out = []
        for r in self._read():
            ts = _created_at(r)
            if since is not None and ts < since:
                continue
            if until is not None and ts > until:
                continue
            row = dict(r)
            row["created_at"] = ts
            out.append(row)
        out.sort(key=_created_at)
        return out

    def search(
        self,
        query: str | None = None,
        *,
        kind: str | None = None,
        tag: str | None = None,
        since: float | None = None,
        until: float | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        """Filter the catalog (newest-first). All criteria AND together:

        * ``query`` — case-insensitive substring of the prompt
        * ``kind``  — exact media kind
        * ``tag``   — present in the item's tags
        * ``since``/``until`` — inclusive ``created_at`` bounds
        """
        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0
        ):
            raise ValueError("search limit must be a positive integer")
        bounded_limit = min(limit, _MAX_SEARCH_LIMIT) if limit is not None else None
        q = query.lower() if query else None
        out = []
        for r in self._read():
            if q is not None and q not in str(r.get("prompt", "")).lower():
                continue
            if kind is not None and r.get("kind") != kind:
                continue
            if tag is not None and tag not in (r.get("tags") or []):
                continue
            ts = _created_at(r)
            if since is not None and ts < since:
                continue
            if until is not None and ts > until:
                continue
            row = dict(r)
            row["created_at"] = ts
            out.append(row)
        out.sort(key=_created_at, reverse=True)
        return out[:bounded_limit] if bounded_limit is not None else out

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
    enabled = (
        env_flag("JARVIS_MEDIA_CATALOG")
        if env is None
        else truthy(env.get("JARVIS_MEDIA_CATALOG"), default=False)
    )
    return MediaCatalog() if enabled else None
