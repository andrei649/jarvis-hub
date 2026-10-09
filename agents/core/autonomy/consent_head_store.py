"""Durable, independent latest-head CAS for H487 reusable consent.

The head lives outside the rollbackable consent database. It deliberately uses
a different file from B7 task mediation and contains no signing key or policy.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from agents.core.autonomy.mediation import (
    SCHEMA_VERSION,
    MediationHead,
    MonotonicHeadAnchor,
)
from agents.core.autonomy.mediation_head_store import _lock, _unlock
from agents.core.paths import data_path

logger = logging.getLogger("jarvis.autonomy.consent")

_HEAD_FIELDS = frozenset({
    "version", "last_sequence", "last_event_hash", "event_count", "signature",
})


class FileConsentHeadStore:
    """A locked monotonic CAS whose absent and invalid states remain distinct."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else data_path(
            "security", "h487_consent_head.json"
        )
        self._lock_path = self.path.with_name(self.path.name + ".lock")

    def read(self) -> MediationHead | None:
        """Return a valid head, or unavailable for missing/invalid storage."""
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.keys() != _HEAD_FIELDS:
                return None
            return MediationHead(**raw)
        except FileNotFoundError:
            return None
        except Exception:
            logger.warning("consent head is unreadable; treating as unavailable", exc_info=True)
            return None

    def compare_and_swap(
        self, expected: MediationHead | None, replacement: MediationHead
    ) -> bool:
        """Advance only from the exact stored head; bootstrap only absent files."""
        if not isinstance(replacement, MediationHead) or (
            expected is not None and not isinstance(expected, MediationHead)
        ):
            return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._lock_path, "a+b") as handle:
                _lock(handle)
                try:
                    try:
                        self.path.lstat()
                        exists = True
                    except FileNotFoundError:
                        exists = False
                    current = self.read()
                    if exists and current is None:
                        return False
                    if current != expected or replacement.version != SCHEMA_VERSION:
                        return False
                    if current is None:
                        if replacement.last_sequence != 0:
                            return False
                    elif replacement.last_sequence <= current.last_sequence:
                        return False
                    self._write_locked(replacement)
                    return True
                finally:
                    _unlock(handle)
        except Exception:
            logger.warning("consent head compare-and-swap failed", exc_info=True)
            return False

    def _write_locked(self, head: MediationHead) -> None:
        """Fsync the new file, atomically replace, then fsync its directory."""
        directory = self.path.parent
        fd, tmp = tempfile.mkstemp(
            dir=str(directory), prefix=self.path.name + ".", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(asdict(head), handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
            tmp = None
            try:
                dir_fd = os.open(str(directory), os.O_RDONLY)
            except OSError:
                if os.name == "nt":  # pragma: no cover - Windows has no directory fds
                    return
                raise
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        finally:
            if tmp is not None:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)


def make_consent_head_anchor(path: str | Path | None = None) -> MonotonicHeadAnchor:
    """Create the H487 anchor with its own lazily resolved durable file."""
    store = FileConsentHeadStore(path)
    return MonotonicHeadAnchor(store.read, store.compare_and_swap)
