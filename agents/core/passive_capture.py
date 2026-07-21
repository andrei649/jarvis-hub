"""
passive_capture.py — H12.7 Passive multi-surface capture (opt-in, local).

Lets the OS layer feed ambient context (clipboard / browser / files) into the
knowledge graph — but only under hard privacy guarantees:

* **STRICT opt-in.** Off unless the master switch (``JARVIS_PASSIVE_CAPTURE``) is
  set *and* the specific surface is enabled. Disabled surfaces capture nothing.
* **Local only.** No network — captures go to the local KG + a bounded, on-disk
  record. Nothing leaves the machine.
* **Secrets redacted before storage.** Every capture is run through the secret
  scanner first, so an API key copied to the clipboard is never persisted.
* **Inspectable & forgettable.** Captures are listable and individually
  deletable (``forget``) — the user can see and erase exactly what was captured.

The OS hooks (clipboard watcher, browser extension, file watcher) are host-side
and call ``ingest``; this module — the gate, redaction, KG ingestion, and the
inspectable store — is pure-Python and offline-testable.
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from pathlib import Path
from typing import Optional

from agents.core.paths import data_path

from .persistence import JsonStore

logger = logging.getLogger("jarvis.capture")

DEFAULT_PATH = data_path("passive_capture.json")
SURFACES = ("clipboard", "browser", "files")
_MAX_RECORDS = 500
_PREVIEW_LEN = 500


def capture_enabled() -> bool:
    """Master kill-switch — off by default (privacy-first)."""
    from agents.core.env_config import env_flag
    return env_flag("JARVIS_PASSIVE_CAPTURE")


class PassiveCapture(JsonStore):
    """Opt-in, redacted, inspectable capture sink feeding the local KG."""

    def __init__(self, path: "str | Path | None" = DEFAULT_PATH,
                 scanner=None, kg_updater=None) -> None:
        if scanner is None:
            try:
                from .security.scanner import SecretScanner
                scanner = SecretScanner()
            except Exception:
                scanner = None
        self._scanner = scanner
        self._kg = kg_updater
        super().__init__(path)

    def _serialize(self):
        return {"surfaces": self._surfaces, "records": self._records}

    def _deserialize(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        self._surfaces = {s: bool(raw.get("surfaces", {}).get(s, False)) for s in SURFACES}
        self._records = raw.get("records", [])

    # ── opt-in surfaces ───────────────────────────────────────────────────────

    def surface_enabled(self, surface: str) -> bool:
        return capture_enabled() and self._surfaces.get(surface, False)

    def set_surfaces(self, mapping: dict) -> dict:
        with self._lock:
            for s, v in (mapping or {}).items():
                if s in SURFACES:
                    self._surfaces[s] = bool(v)
            self._save()
            return dict(self._surfaces)

    def status(self) -> dict:
        return {"enabled": capture_enabled(), "surfaces": dict(self._surfaces),
                "records": len(self._records)}

    # ── ingest (gate → redact → KG → store) ───────────────────────────────────

    def ingest(self, surface: str, content: str, source: str = "") -> dict:
        if surface not in SURFACES:
            raise ValueError(f"unknown surface: {surface}")
        if not self.surface_enabled(surface):
            return {"captured": False, "reason": "disabled"}
        text = (content or "").strip()
        if not text:
            return {"captured": False, "reason": "empty"}

        redacted = self._scanner.redact(text) if self._scanner else text
        was_redacted = redacted != text

        triples = 0
        if self._kg is not None:
            try:
                triples = self._kg.ingest(redacted, source=f"capture:{surface}")
            except Exception:
                logger.warning("capture KG ingest failed", exc_info=True)

        rec = {
            "id": secrets.token_urlsafe(8),
            "surface": surface,
            "source": source[:200],
            "preview": redacted[:_PREVIEW_LEN],
            "redacted": was_redacted,
            "triples": triples,
            "created_at": time.time(),
        }
        with self._lock:
            self._records.append(rec)
            del self._records[:-_MAX_RECORDS]      # bound the store
            self._save()
        return {"captured": True, "id": rec["id"], "redacted": was_redacted, "triples": triples}

    # ── inspect / forget ──────────────────────────────────────────────────────

    def list(self, surface: Optional[str] = None) -> list[dict]:
        items = [dict(r) for r in self._records if surface is None or r.get("surface") == surface]
        return items[::-1]

    def get(self, rec_id: str) -> Optional[dict]:
        for r in self._records:
            if r["id"] == rec_id:
                return dict(r)
        return None

    def forget(self, rec_id: str) -> bool:
        # Do the whole read-modify-write under the lock, or a concurrent ingest
        # can reassign self._records between our read and write and lose data.
        with self._lock:
            before = len(self._records)
            self._records = [r for r in self._records if r["id"] != rec_id]
            if len(self._records) != before:
                self._save()
                return True
            return False

    def clear(self, surface: Optional[str] = None) -> int:
        with self._lock:
            keep = [r for r in self._records if surface is not None and r.get("surface") != surface]
            removed = len(self._records) - len(keep)
            if removed:
                self._records = keep
                self._save()
            return removed

    # ── export (0.26: the data half of "phone export") ────────────────────────

    def export(self, *, surface: Optional[str] = None, now: Optional[float] = None) -> dict:
        """A portable, JSON-safe snapshot of the capture inbox.

        Records carry only **already-redacted** previews + metadata (secrets are
        scrubbed at ``ingest`` time and raw content is never stored), so nothing
        here can leak a secret — it's the same data the inbox already exposes via
        ``list``, packaged for off-device transfer. ``now`` is injectable for tests.
        """
        records = self.list(surface)   # newest-first dict copies
        return {
            "version": 1,
            "exported_at": time.time() if now is None else float(now),
            "surface": surface,
            "count": len(records),
            "surfaces": dict(self._surfaces),
            "records": records,
        }

    def write_export(self, dest: "str | Path", *, surface: Optional[str] = None,
                     now: Optional[float] = None) -> dict:
        """Write :meth:`export` as pretty JSON to *dest*. Returns ``{path, count}``."""
        payload = self.export(surface=surface, now=now)
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"path": str(dest), "count": payload["count"]}
