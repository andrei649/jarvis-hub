"""
json_store.py — shared base for JSON-file-backed stores (audit A3/Q1).

Captures the load / atomic-save / lock boilerplate that ~13 stores re-implemented.
Subclasses keep their own in-memory attribute(s) and override two tiny hooks:

    class WidgetStore(JsonStore):
        def _serialize(self) -> Any:        return self._widgets
        def _deserialize(self, raw) -> None: self._widgets = raw if isinstance(raw, dict) else {}

The base provides ``self.path`` and ``self._lock`` (a ``threading.Lock`` — these
stores are touched from sync code and async handlers alike) and atomic writes via
a temp file + ``replace``. Corrupt/missing files deserialize from ``{}`` so a bad
file never crashes startup.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any


def atomic_write_json(
    path: "str | Path",
    data: Any,
    *,
    indent: int = 2,
    ensure_ascii: bool = False,
) -> None:
    """Write ``data`` as JSON to ``path`` atomically (serialize → tmp → replace).

    Module-level twin of ``JsonStore._save`` for the writers that are not stores
    (the per-turn memory snapshot, the ingestion watcher state, the Oracle
    session file). Serialization happens BEFORE the target is touched, and the
    payload lands on a sibling tmp that is ``replace``d over the target, so a
    raising serializer, a full disk or a kill mid-write leaves the previous good
    file intact instead of a truncated one. On any failure the tmp is removed so
    no stale ``*.tmp`` accumulates next to the store.

    No fsync: this matches ``JsonStore._save`` and closes the truncation window
    the audit (Q6) describes. Full durability (fsync of tmp + parent dir) would
    change behaviour for every migrated store and belongs in its own change.

    The file lands **owner-only (0600)**. These stores hold personal state and, in
    the sender-pairing store's case, pairing credentials; ``write_text`` creates
    with ``0o666 & ~umask`` — 0644 on a default umask — so without this every
    JSON store was world-readable.

    The tmp is **created** 0600 rather than chmod'd afterwards. A first cut wrote
    the payload with ``write_text`` and chmod'd the tmp before the ``replace``,
    reasoning that ``replace`` moves the tmp's inode over the target so the mode
    must be right first. That ordering is the better of the two but it does not
    close the window it claims to: ``write_text`` creates the tmp at
    ``0o666 & ~umask`` and the whole payload is written before the ``chmod`` runs,
    so the secret sits in a world-readable file for the length of the write.
    ``os.open`` with an explicit mode is what actually closes it — the descriptor
    never exists in any other mode. (H497)
    """
    path = Path(path)
    payload = json.dumps(data, ensure_ascii=ensure_ascii, indent=indent)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
        except BaseException:
            os.close(fd)   # only reachable if fdopen itself failed to take the fd
            raise
        # A tmp left over from an older release (or an interrupted run) keeps its
        # own mode through O_CREAT, so the mode is asserted rather than assumed.
        os.chmod(tmp, 0o600)
        tmp.replace(path)  # atomic
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


class JsonStore:
    def __init__(self, path: "str | Path | None") -> None:
        # path=None → in-memory only (load/save become no-ops); useful for stores
        # whose persistence is opt-in (e.g. tests, ephemeral runtime state).
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self._load()

    # ── hooks (override in subclasses) ────────────────────────────────────────

    def _serialize(self) -> Any:
        """Return the JSON-serializable snapshot to persist."""
        return getattr(self, "_data", {})

    def _deserialize(self, raw: Any) -> None:
        """Populate in-memory state from parsed JSON (``{}`` if file missing/corrupt)."""
        self._data = raw if isinstance(raw, dict) else {}

    # ── persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        raw: Any = {}
        if self.path is not None and self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                raw = {}
        self._deserialize(raw)

    def _save(self) -> None:
        if self.path is None:
            return  # in-memory mode
        atomic_write_json(self.path, self._serialize())
