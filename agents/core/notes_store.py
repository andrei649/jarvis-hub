"""
notes_store.py — block-tree document store for notes / memory (BACKLOG H22.10).

Lineage: AppFlowy's local-first data model (see
``docs/research/2026-06-20-oss-adoption-perf-velocity.md`` → AppFlowy section).
A document is a tree of **typed blocks** — each block carries a stable string
``id``, a ``type`` (paragraph/heading/list_item/todo/…), a nullable
``parent_id``, an ``ordering`` key that sorts it among its siblings, an
``attrs_json`` bag, and inline ``text``. Stable block ids are the point: they
become durable memory references that survive edits and reordering.

This is a clean, offline, dependency-free STORE LIBRARY (stdlib ``sqlite3`` +
``json`` only). It is a *new* capability — it does not touch or rewire the
existing memory subsystem. Other code can adopt it later.

House style (matches ``agents/core/autonomy/queue.py``): a single connection
opened with ``check_same_thread=False``, every operation serialised by a
``threading.Lock``, WAL journal + ``synchronous=NORMAL`` for cheap commits, and
JSON stored as TEXT columns. Pass ``":memory:"`` for tests.

Ordering / fractional index
---------------------------
Siblings are ordered by a **fractional index**: a short, lexicographically
sortable string (base-62). To place a block *after* sibling A (and before A's
current successor B) we mint a key strictly between ``A.ordering`` and
``B.ordering``. Inserting in the middle therefore mints ONE new key and touches
ONE row — existing siblings are never renumbered or reordered. This is the same
trick used by AppFlowy / Figma / many CRDT-free editors; it trades a tiny risk
of key growth (keys lengthen as you repeatedly insert in the same gap) for
renumber-free inserts.

Delta / formatted text
----------------------
``text`` holds plain inline text today. For formatted text, ``attrs`` may carry
a ``"delta"`` key with a simple Delta op-list (``[{"insert": "...",
"attributes": {...}}, …]``) — a documented forward path to full Delta without a
schema change. Round-tripping rich Delta and rendering it is deferred.

Caveats (honest)
----------------
- Single-writer, single-process: the lock serialises in-process access; this is
  not a multi-device / concurrent-editor store. Conflict resolution and CRDT
  sync are explicitly deferred (the research says full ``yrs`` CRDTs are
  overkill for single-user — adopt only the data model).
- Delta is stored-but-not-interpreted; no rich-text rendering helper yet.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from agents.core.paths import data_path

DEFAULT_DB = data_path("notes.db")

# ── fractional index (base-62 "between" keys) ─────────────────────────
# Digits ordered so that plain string comparison == numeric order.
_DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_BASE = len(_DIGITS)
_RANK = {c: i for i, c in enumerate(_DIGITS)}
_MID = _DIGITS[_BASE // 2]     # midpoint digit, used to descend a level


def _key_between(lo: Optional[str], hi: Optional[str]) -> str:
    """Return a key ``k`` with ``lo < k < hi`` under lexicographic ordering.

    ``lo``/``hi`` are existing ordering keys (base-62, drawn from ``_DIGITS``);
    ``None`` means "unbounded" (start/end of the list). The result never equals
    an endpoint.
    """
    if lo is not None and hi is not None and lo >= hi:
        raise ValueError(f"ordering keys out of order: {lo!r} >= {hi!r}")

    out: list[str] = []
    i = 0
    while True:
        d_lo = _RANK[lo[i]] if lo is not None and i < len(lo) else 0
        # Once we've consumed past hi's length, hi no longer constrains the
        # suffix — treat the upper bound as the open top of the digit range.
        d_hi = _RANK[hi[i]] if hi is not None and i < len(hi) else _BASE
        if d_lo + 1 < d_hi:
            # Room for a digit strictly between them at this position.
            out.append(_DIGITS[(d_lo + d_hi) // 2])
            return "".join(out)
        # No gap here: copy lo's digit (its implicit 0 once lo is exhausted) and
        # descend. Keeping the prefix == lo guarantees the result stays > lo.
        out.append(_DIGITS[d_lo])
        i += 1
        # When both bounds are exhausted at this depth we can safely append a
        # mid digit and stop: it lands strictly above the copied lo-prefix and,
        # since hi shares that prefix, strictly below hi.
        lo_done = lo is None or i >= len(lo)
        hi_done = hi is None or i >= len(hi)
        if lo_done and hi_done:
            out.append(_MID)
            return "".join(out)


# ``docs.updated_at`` is the sole ORDER BY key of ``list_docs`` (ties break on a
# random UUID), so two writes inside one clock tick used to come back in random
# order — a ~50% flake on Windows, whose pre-3.13 wall clock ticks at ~15.6 ms.
# ``_now`` is therefore strictly monotonic within the process: when the wall
# clock has not advanced past the last stamp handed out, bump by 1 µs instead.
# The column keeps its ISO-8601 UTC text shape (always with microseconds) so
# rows written before this change still compare correctly as TEXT.
_NOW_LOCK = threading.Lock()
_LAST_NOW: Optional[datetime] = None


def _wall_clock() -> datetime:
    """The raw UTC wall clock — a seam so tests can freeze it."""
    return datetime.now(timezone.utc)


def _now() -> str:
    global _LAST_NOW
    with _NOW_LOCK:
        current = _wall_clock()
        if _LAST_NOW is not None and current <= _LAST_NOW:
            current = _LAST_NOW + timedelta(microseconds=1)
        _LAST_NOW = current
    return current.isoformat(timespec="microseconds")


def _new_id() -> str:
    return uuid.uuid4().hex


class NotesStoreError(Exception):
    """Raised on invalid block-tree operations (missing/cyclic/mismatched)."""


class NotesStore:
    """A block-tree document store. Call :meth:`initialize` before use."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            DEFAULT_DB.parent.mkdir(parents=True, exist_ok=True)
            db_path = str(DEFAULT_DB)
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()

    # ── lifecycle ─────────────────────────────────────────────────
    def initialize(self) -> "NotesStore":
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS docs (
                id         TEXT PRIMARY KEY,
                title      TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS blocks (
                id         TEXT PRIMARY KEY,
                doc_id     TEXT NOT NULL REFERENCES docs(id) ON DELETE CASCADE,
                type       TEXT NOT NULL,
                parent_id  TEXT REFERENCES blocks(id) ON DELETE CASCADE,
                ordering   TEXT NOT NULL,
                attrs_json TEXT NOT NULL DEFAULT '{}',
                text       TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        # Sibling reads (children / render_tree / ordering lookups) all filter by
        # (doc_id, parent_id) and sort by ordering — index that path so it stays
        # O(log n) as documents grow.
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_blocks_siblings "
            "ON blocks(doc_id, parent_id, ordering)"
        )
        self._conn.commit()
        return self

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "NotesStore":
        return self.initialize()

    def __exit__(self, *exc) -> None:
        self.close()

    # ── docs ──────────────────────────────────────────────────────
    def create_doc(self, title: str = "") -> str:
        """Create an empty document and return its id."""
        doc_id = _new_id()
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO docs (id, title, created_at, updated_at) VALUES (?,?,?,?)",
                (doc_id, title, now, now),
            )
            self._conn.commit()
        return doc_id

    def get_doc(self, doc_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM docs WHERE id=?", (doc_id,)).fetchone()
        return dict(row) if row else None

    def list_docs(self, limit: int = 50) -> list[dict]:
        """Document summaries, most recently updated first.

        A *summary* on purpose — id/title/timestamps, never the block tree: the
        listing is what a client uses to find a doc again, and rendering every
        tree to draw a list would read the whole store per request.
        """
        limit = max(1, int(limit))
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, title, created_at, updated_at FROM docs "
                "ORDER BY updated_at DESC, id ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_doc(self, doc_id: str) -> int:
        """Delete a document and every block in it. Returns blocks deleted.

        The blocks are deleted explicitly rather than left to ``ON DELETE
        CASCADE`` — same reasoning as :meth:`delete_block`: the cascade depends
        on the SQLite build honouring ``PRAGMA foreign_keys``, and a doc whose
        rows outlive it would be invisible garbage.
        """
        with self._lock:
            if self._conn.execute("SELECT 1 FROM docs WHERE id=?", (doc_id,)).fetchone() is None:
                raise NotesStoreError(f"doc {doc_id!r} not found")
            n = self._conn.execute(
                "SELECT COUNT(*) AS n FROM blocks WHERE doc_id=?", (doc_id,)
            ).fetchone()["n"]
            self._conn.execute("DELETE FROM blocks WHERE doc_id=?", (doc_id,))
            self._conn.execute("DELETE FROM docs WHERE id=?", (doc_id,))
            self._conn.commit()
        return int(n)

    # ── blocks ────────────────────────────────────────────────────
    def add_block(
        self,
        doc_id: str,
        type: str,
        text: str = "",
        *,
        parent_id: Optional[str] = None,
        after: Optional[str] = None,
        attrs: Optional[dict] = None,
    ) -> str:
        """Insert a new block and return its id.

        ``parent_id`` — the new block's parent (``None`` = top level of the doc).
        ``after``      — a sibling id to place this block *immediately after*;
                         ``None`` appends to the end of the sibling list.
        """
        now = _now()
        block_id = _new_id()
        with self._lock:
            if self._conn.execute("SELECT 1 FROM docs WHERE id=?", (doc_id,)).fetchone() is None:
                raise NotesStoreError(f"doc {doc_id!r} not found")
            if parent_id is not None:
                prow = self._conn.execute(
                    "SELECT doc_id FROM blocks WHERE id=?", (parent_id,)
                ).fetchone()
                if prow is None:
                    raise NotesStoreError(f"parent block {parent_id!r} not found")
                if prow["doc_id"] != doc_id:
                    raise NotesStoreError("parent_id belongs to a different doc")
            ordering = self._ordering_for(doc_id, parent_id, after)
            self._conn.execute(
                """INSERT INTO blocks
                       (id, doc_id, type, parent_id, ordering, attrs_json, text,
                        created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (block_id, doc_id, type, parent_id, ordering,
                 json.dumps(attrs or {}, ensure_ascii=False), text, now, now),
            )
            self._conn.execute(
                "UPDATE docs SET updated_at=? WHERE id=?", (now, doc_id)
            )
            self._conn.commit()
        return block_id

    def update_block(
        self,
        block_id: str,
        *,
        text: Optional[str] = None,
        attrs: Optional[dict] = None,
        type: Optional[str] = None,
    ) -> dict:
        """Update a block's text / attrs / type in place. Returns the new row."""
        if text is None and attrs is None and type is None:
            existing = self.get_block(block_id)
            if existing is None:
                raise NotesStoreError(f"block {block_id!r} not found")
            return existing
        now = _now()
        sets, params = ["updated_at=?"], [now]
        if text is not None:
            sets.append("text=?"); params.append(text)
        if attrs is not None:
            sets.append("attrs_json=?"); params.append(json.dumps(attrs, ensure_ascii=False))
        if type is not None:
            sets.append("type=?"); params.append(type)
        params.append(block_id)
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE blocks SET {', '.join(sets)} WHERE id=?", params
            )
            if cur.rowcount == 0:
                raise NotesStoreError(f"block {block_id!r} not found")
            row = self._conn.execute("SELECT doc_id FROM blocks WHERE id=?", (block_id,)).fetchone()
            self._conn.execute("UPDATE docs SET updated_at=? WHERE id=?", (now, row["doc_id"]))
            self._conn.commit()
        return self.get_block(block_id)  # type: ignore[return-value]

    def move_block(
        self,
        block_id: str,
        *,
        new_parent: Optional[str] = None,
        after: Optional[str] = None,
    ) -> dict:
        """Reparent and/or reorder a block. Returns the moved row.

        ``new_parent=None`` moves the block to the document's top level.
        ``after`` is a sibling (under the resolved parent) to place it after;
        ``None`` appends to the end.
        """
        now = _now()
        with self._lock:
            row = self._conn.execute("SELECT * FROM blocks WHERE id=?", (block_id,)).fetchone()
            if row is None:
                raise NotesStoreError(f"block {block_id!r} not found")
            doc_id = row["doc_id"]
            if new_parent is not None:
                prow = self._conn.execute(
                    "SELECT doc_id FROM blocks WHERE id=?", (new_parent,)
                ).fetchone()
                if prow is None:
                    raise NotesStoreError(f"new_parent {new_parent!r} not found")
                if prow["doc_id"] != doc_id:
                    raise NotesStoreError("new_parent belongs to a different doc")
                if new_parent == block_id or self._is_descendant(new_parent, block_id):
                    raise NotesStoreError("cannot move a block under itself or its descendant")
            ordering = self._ordering_for(doc_id, new_parent, after, moving_id=block_id)
            self._conn.execute(
                "UPDATE blocks SET parent_id=?, ordering=?, updated_at=? WHERE id=?",
                (new_parent, ordering, now, block_id),
            )
            self._conn.execute("UPDATE docs SET updated_at=? WHERE id=?", (now, doc_id))
            self._conn.commit()
        return self.get_block(block_id)  # type: ignore[return-value]

    def delete_block(self, block_id: str) -> int:
        """Delete a block and all its descendants. Returns rows deleted.

        Cascade is done explicitly (the recursive subtree is collected and
        deleted in one statement) so it works regardless of the SQLite build's
        ``foreign_keys`` / ``ON DELETE CASCADE`` support.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT doc_id FROM blocks WHERE id=?", (block_id,)
            ).fetchone()
            if row is None:
                raise NotesStoreError(f"block {block_id!r} not found")
            ids = self._subtree_ids(block_id)
            placeholders = ",".join("?" * len(ids))
            # Deleting the whole subtree in one statement (rather than just the
            # root) is correct whether or not the FK ON DELETE CASCADE fires:
            # with FKs on, deleting the root also removes descendants, so the
            # IN-list re-targets already-gone rows harmlessly. We report the
            # collected subtree size, which is the true count regardless.
            self._conn.execute(
                f"DELETE FROM blocks WHERE id IN ({placeholders})", ids
            )
            self._conn.execute("UPDATE docs SET updated_at=? WHERE id=?", (_now(), row["doc_id"]))
            self._conn.commit()
            return len(ids)

    # ── reads ─────────────────────────────────────────────────────
    def get_block(self, block_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM blocks WHERE id=?", (block_id,)).fetchone()
        return self._row_to_block(row) if row else None

    def children(self, parent_id: Optional[str], doc_id: Optional[str] = None) -> list[dict]:
        """Direct children of ``parent_id`` in sibling order.

        For top-level blocks (``parent_id=None``) pass ``doc_id`` to scope the
        query to one document.
        """
        with self._lock:
            if parent_id is None:
                if doc_id is None:
                    raise NotesStoreError("children(None) requires doc_id")
                rows = self._conn.execute(
                    "SELECT * FROM blocks WHERE doc_id=? AND parent_id IS NULL "
                    "ORDER BY ordering ASC",
                    (doc_id,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM blocks WHERE parent_id=? ORDER BY ordering ASC",
                    (parent_id,),
                ).fetchall()
        return [self._row_to_block(r) for r in rows]

    def render_tree(self, doc_id: str) -> dict:
        """Return the whole document as a nested dict tree, in sibling order.

        Shape::

            {"id", "title", "created_at", "updated_at",
             "children": [ {block fields…, "children": [...] }, … ]}
        """
        with self._lock:
            doc = self._conn.execute("SELECT * FROM docs WHERE id=?", (doc_id,)).fetchone()
            if doc is None:
                raise NotesStoreError(f"doc {doc_id!r} not found")
            rows = self._conn.execute(
                "SELECT * FROM blocks WHERE doc_id=? ORDER BY ordering ASC", (doc_id,)
            ).fetchall()
        # Bucket children by parent, preserving the ordering-sorted sequence.
        by_parent: dict[Optional[str], list[dict]] = {}
        for r in rows:
            by_parent.setdefault(r["parent_id"], []).append(self._row_to_block(r))

        def build(parent_id: Optional[str]) -> list[dict]:
            out = []
            for blk in by_parent.get(parent_id, []):
                node = dict(blk)
                node["children"] = build(blk["id"])
                out.append(node)
            return out

        return {
            "id": doc["id"],
            "title": doc["title"],
            "created_at": doc["created_at"],
            "updated_at": doc["updated_at"],
            "children": build(None),
        }

    # ── internals ─────────────────────────────────────────────────
    def _ordering_for(
        self,
        doc_id: str,
        parent_id: Optional[str],
        after: Optional[str],
        moving_id: Optional[str] = None,
    ) -> str:
        """Compute a fractional-index key placing a block among its siblings.

        ``after=None``  → append after the current last sibling.
        ``after=<id>``  → between ``after`` and its current successor.
        ``moving_id``   → the block being moved (excluded from sibling scans so
                          it isn't compared against its own old key).
        Caller holds ``self._lock``.
        """
        # Resolve the lower bound (key of `after`) and the upper bound (key of
        # `after`'s successor, or None when appending).
        if after is not None:
            arow = self._conn.execute(
                "SELECT doc_id, parent_id, ordering FROM blocks WHERE id=?", (after,)
            ).fetchone()
            if arow is None:
                raise NotesStoreError(f"after-block {after!r} not found")
            if arow["doc_id"] != doc_id or arow["parent_id"] != parent_id:
                raise NotesStoreError("after-block is not a sibling under the target parent")
            lo = arow["ordering"]
            hi = self._next_ordering(doc_id, parent_id, lo, moving_id)
            return _key_between(lo, hi)
        # Append: mint a key after the current maximum sibling key.
        last = self._max_ordering(doc_id, parent_id, moving_id)
        return _key_between(last, None)

    def _max_ordering(self, doc_id: str, parent_id: Optional[str], moving_id: Optional[str]) -> Optional[str]:
        if parent_id is None:
            q = "SELECT MAX(ordering) AS m FROM blocks WHERE doc_id=? AND parent_id IS NULL"
            params: list = [doc_id]
        else:
            q = "SELECT MAX(ordering) AS m FROM blocks WHERE parent_id=?"
            params = [parent_id]
        if moving_id is not None:
            q += " AND id<>?"; params.append(moving_id)
        return self._conn.execute(q, params).fetchone()["m"]

    def _next_ordering(
        self, doc_id: str, parent_id: Optional[str], lo: str, moving_id: Optional[str]
    ) -> Optional[str]:
        """Smallest sibling ordering strictly greater than ``lo`` (or None)."""
        if parent_id is None:
            q = ("SELECT MIN(ordering) AS m FROM blocks "
                 "WHERE doc_id=? AND parent_id IS NULL AND ordering>?")
            params: list = [doc_id, lo]
        else:
            q = "SELECT MIN(ordering) AS m FROM blocks WHERE parent_id=? AND ordering>?"
            params = [parent_id, lo]
        if moving_id is not None:
            q += " AND id<>?"; params.append(moving_id)
        return self._conn.execute(q, params).fetchone()["m"]

    def _subtree_ids(self, root_id: str) -> list[str]:
        """All block ids in the subtree rooted at ``root_id`` (incl. root). Caller holds lock."""
        ids = [root_id]
        frontier = [root_id]
        while frontier:
            placeholders = ",".join("?" * len(frontier))
            rows = self._conn.execute(
                f"SELECT id FROM blocks WHERE parent_id IN ({placeholders})", frontier
            ).fetchall()
            frontier = [r["id"] for r in rows]
            ids.extend(frontier)
        return ids

    def _is_descendant(self, candidate: str, ancestor: str) -> bool:
        """True if ``candidate`` is in the subtree rooted at ``ancestor``. Caller holds lock."""
        node: Optional[str] = candidate
        seen: set[str] = set()
        while node is not None:
            if node == ancestor:
                return True
            if node in seen:  # defensive against a malformed cycle
                return False
            seen.add(node)
            row = self._conn.execute("SELECT parent_id FROM blocks WHERE id=?", (node,)).fetchone()
            node = row["parent_id"] if row else None
        return False

    @staticmethod
    def _row_to_block(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "doc_id": row["doc_id"],
            "type": row["type"],
            "parent_id": row["parent_id"],
            "ordering": row["ordering"],
            "attrs": json.loads(row["attrs_json"] or "{}"),
            "text": row["text"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


# ── process singleton (DRA-53: adoption behind /api/notes/docs) ───────
# House pattern from agents/core/feedback_store.py: a lazily-opened, cached
# instance so the router does not reopen SQLite per request. The path is
# resolved at CALL time (not from the import-time DEFAULT_DB constant) so a
# test process' JARVIS_HOME — assigned in tests/conftest.py before any Jarvis
# import — is honoured.
_docs_store: Optional[NotesStore] = None
_docs_lock = threading.Lock()


def get_note_docs_store() -> NotesStore:
    """The shared block-tree store for the notes-docs routes."""
    global _docs_store
    with _docs_lock:
        if _docs_store is None:
            path = data_path("notes.db")
            path.parent.mkdir(parents=True, exist_ok=True)
            _docs_store = NotesStore(str(path)).initialize()
        return _docs_store


def reset_note_docs_store(store: Optional[NotesStore] = None) -> Optional[NotesStore]:
    """Close and drop the cached store (tests). Optionally install *store*."""
    global _docs_store
    with _docs_lock:
        if _docs_store is not None and _docs_store is not store:
            # A store whose file already vanished must not break teardown.
            with contextlib.suppress(Exception):
                _docs_store.close()
        _docs_store = store
        return _docs_store
