"""provenance.py — 0.37: auditable provenance for ingested memory.

The ingestion pipeline turns raw exports (Facebook/WhatsApp/…) into normalized
messages, then entities/decisions/relationships, then embeddings. Today a
``NormalizedMessage`` carries only ``source`` + free-form ``metadata`` — there's
no structured record of **where a memory came from and how it was produced**:
which source file, which pipeline phase, which run, and a content fingerprint to
prove it hasn't been altered. This module adds that ledger.

Design mirrors the 0.34 stores (``run_store`` / ``pending_queue``): a single
**bounded, atomically-written, corrupt/missing-file-safe** JSON array, and
**opt-in / default-off** — nothing in the pipeline writes provenance unless a
caller wires a ledger, so the default ingestion path is byte-for-byte unchanged.

Record shape (JSON-safe)::

    {id, run_id, source, origin, phase, content_hash, produced_at, parent_id, meta}

* ``source``   — the data source family (e.g. ``"facebook"``).
* ``origin``   — the concrete origin within it (a file path, conversation id, …).
* ``phase``    — the pipeline phase that produced the artifact (``"parse"``,
  ``"normalize"``, ``"knowledge"``, ``"embed"``, …).
* ``content_hash`` — SHA-256 of the artifact's content → **tamper-evidence**
  (``verify``) and dedup, without storing the content itself.
* ``parent_id`` — links a derived artifact to the one it came from, so a chain
  (embedding ← message ← file) can be walked with ``lineage``.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
import uuid
from pathlib import Path

from .lifecycle import default_archive_root

_DEFAULT_MAX_KEEP = 50_000
_MAX_LINEAGE_HOPS = 1000   # cycle/runaway guard for lineage walks


def content_fingerprint(content: str | bytes) -> str:
    """Stable SHA-256 hex of an artifact's content (utf-8 for ``str``)."""
    data = content if isinstance(content, bytes) else str(content).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


class ProvenanceLedger:
    """Bounded, atomically-written JSON ledger of ingestion provenance records."""

    def __init__(self, path: Path | str | None = None, *, max_keep: int = _DEFAULT_MAX_KEEP) -> None:
        self._path = Path(path) if path is not None else default_archive_root() / "provenance.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._max_keep = max(1, int(max_keep))

    # ── persistence (mirrors the 0.34 stores) ─────────────────────────────────
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
    def record(
        self,
        *,
        source: str,
        origin: str,
        phase: str,
        content: str | bytes,
        run_id: str,
        now: float,
        parent_id: str | None = None,
        meta: dict | None = None,
    ) -> dict:
        """Append a provenance record for one ingested artifact. ``now`` is the
        caller's clock (kept injectable for tests). Returns the stored record."""
        if not str(source).strip():
            raise ValueError("source is required")
        if not str(run_id).strip():
            raise ValueError("run_id is required")
        item = {
            "id": "pv-" + uuid.uuid4().hex[:12],
            "run_id": str(run_id),
            "source": str(source),
            "origin": str(origin),
            "phase": str(phase),
            "content_hash": content_fingerprint(content),
            "produced_at": float(now),
            "parent_id": str(parent_id) if parent_id else None,
            "meta": dict(meta) if isinstance(meta, dict) else {},
        }
        items = self._read()
        items.append(item)
        # bound the ledger: it's an append-only audit log, so evict the oldest first.
        if len(items) > self._max_keep:
            items.sort(key=lambda r: float(r.get("produced_at", 0)))
            items = items[-self._max_keep:]
        self._write_atomic(items)
        return dict(item)

    def get(self, record_id: str) -> dict | None:
        for r in self._read():
            if r.get("id") == record_id:
                return dict(r)
        return None

    def by_run(self, run_id: str) -> list[dict]:
        """All records from one ingestion run, oldest-produced first."""
        items = [dict(r) for r in self._read() if r.get("run_id") == run_id]
        items.sort(key=lambda r: float(r.get("produced_at", 0)))
        return items

    def by_source(self, source: str) -> list[dict]:
        """All records from one source family, oldest-produced first."""
        items = [dict(r) for r in self._read() if r.get("source") == source]
        items.sort(key=lambda r: float(r.get("produced_at", 0)))
        return items

    def lineage(self, record_id: str) -> list[dict]:
        """Walk the ``parent_id`` chain from *record_id* up to its root.

        Returns ``[record, parent, …, root]``. Empty if the id is unknown.
        Bounded by ``_MAX_LINEAGE_HOPS`` and a visited-set so a malformed cycle
        can never loop forever.
        """
        by_id = {r.get("id"): r for r in self._read()}
        chain: list[dict] = []
        seen: set[str] = set()
        cur = record_id
        hops = 0
        while cur and cur in by_id and cur not in seen and hops < _MAX_LINEAGE_HOPS:
            rec = by_id[cur]
            chain.append(dict(rec))
            seen.add(cur)
            cur = rec.get("parent_id")
            hops += 1
        return chain

    def verify(self, record_id: str, content: str | bytes) -> bool:
        """True iff *content* still hashes to the record's stored fingerprint.

        Tamper-evidence: if the persisted memory was altered after ingestion, its
        recomputed hash won't match. Returns False for an unknown id."""
        rec = self.get(record_id)
        if rec is None:
            return False
        return content_fingerprint(content) == rec.get("content_hash")

    def stats(self) -> dict:
        """Counts by source + total, for an at-a-glance ingestion audit view."""
        items = self._read()
        by_source: dict[str, int] = {}
        runs: set[str] = set()
        for r in items:
            by_source[r.get("source", "?")] = by_source.get(r.get("source", "?"), 0) + 1
            if r.get("run_id"):
                runs.add(r["run_id"])
        return {"total": len(items), "runs": len(runs), "by_source": by_source}

    def recent(self, limit: int = 200) -> list[dict]:
        """The most recently produced records, newest-first (the default audit view)."""
        items = [dict(r) for r in self._read()]
        items.sort(key=lambda r: float(r.get("produced_at", 0)), reverse=True)
        return items[: max(0, int(limit))]


def default_ledger_if_enabled(env=None) -> ProvenanceLedger | None:
    """Return a default-path :class:`ProvenanceLedger` when ``JARVIS_PROVENANCE`` is
    set, else ``None`` — the opt-in switch for recording ingestion provenance. The
    ledger's ``origin`` carries conversation ids, so recording (and the read
    surface) stay off unless the owner enables it; the ingestion path is
    byte-identical when this returns ``None``."""
    e = os.environ if env is None else env
    return ProvenanceLedger() if e.get("JARVIS_PROVENANCE") else None
