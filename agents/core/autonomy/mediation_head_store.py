"""Durable latest-head store behind ``MonotonicHeadAnchor`` (B7 / DRA-59).

``agents.core.autonomy.mediation`` deliberately owns no policy, no key and no
storage: it only defines the fail-closed adapter (``MonotonicHeadAnchor``) for a
trusted monotonic latest-head CAS store held *outside* the rollbackable queue
database. This module is that store.

Why a separate file and not a row in ``autonomy.db``: the whole point of the
anchor is that restoring an older SQLite snapshot must not restore execution
authority. A head kept inside the same database rolls back with it. The file
lives under ``<data root>/security/`` beside the transparency log
(``agents/core/security/anchor.py``), following the same convention of a local
append-only/authoritative file standing in for an external service.

Honest limits: this defends against whole-file and signed-prefix rollback of the
queue database, which is the threat the B7 design names. It does *not* defend
against an attacker who can rewrite the entire runtime data directory — that
needs a genuinely external transparency service, which remains future work.

Every failure path is closed: a missing, unreadable, malformed or
schema-invalid head reads as ``None`` (the anchor treats that as unavailable),
and every compare-and-swap failure returns ``False`` rather than raising.
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
from agents.core.paths import data_path

logger = logging.getLogger("jarvis.autonomy.mediation")

MEDIATION_MODES = frozenset({"off", "hold", "enforce"})
_ENV_VAR = "JARVIS_TASK_MEDIATION"


def _lock(handle) -> None:
    try:
        import fcntl
    except ImportError:  # pragma: no cover - Windows
        import msvcrt
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        return
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock(handle) -> None:
    try:
        import fcntl
    except ImportError:  # pragma: no cover - Windows
        import msvcrt
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        return
    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class FileMediationHeadStore:
    """A single-file, lock-guarded, monotonic latest-head CAS store."""

    def __init__(self, path: str | Path | None = None) -> None:
        # Resolved now, not at import: data_path() honors the current
        # JARVIS_HOME, and binding it at import time leaks the live store into
        # temp-home runs (the memory_logs lesson in memory/persistence.py).
        self.path = Path(path) if path is not None else data_path(
            "security", "task_mediation_head.json"
        )
        self._lock_path = self.path.with_name(self.path.name + ".lock")

    # ── read ──────────────────────────────────────────────────────────────

    def read(self) -> MediationHead | None:
        """The stored head, or ``None`` when it is absent or not trustworthy."""
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return None
            # MediationHead.__post_init__ re-validates version, sequence, count
            # and digest shape, so a hand-edited file fails here, not later.
            return MediationHead(
                version=raw["version"],
                last_sequence=raw["last_sequence"],
                last_event_hash=raw["last_event_hash"],
                event_count=raw["event_count"],
                signature=raw["signature"],
            )
        except FileNotFoundError:
            return None
        except Exception:
            logger.warning("mediation head is unreadable; treating as unavailable",
                           exc_info=True)
            return None

    # ── compare-and-swap ──────────────────────────────────────────────────

    def compare_and_swap(
        self, expected: MediationHead | None, replacement: MediationHead
    ) -> bool:
        """Advance the head only from ``expected``, and only forwards."""
        if not isinstance(replacement, MediationHead):
            return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._lock_path, "a+b") as handle:
                _lock(handle)
                try:
                    current = self.read()
                    if current != expected:
                        return False
                    if replacement.version != SCHEMA_VERSION:
                        return False
                    if current is None:
                        # Bootstrap is only ever from an empty chain.
                        if replacement.last_sequence != 0:
                            return False
                    elif replacement.last_sequence <= current.last_sequence:
                        return False
                    self._write_locked(replacement)
                    return True
                finally:
                    _unlock(handle)
        except Exception:
            logger.warning("mediation head compare-and-swap failed", exc_info=True)
            return False

    def _write_locked(self, head: MediationHead) -> None:
        """Durably replace the head file (fsync file, replace, fsync dir).

        The queue commits its SQLite transaction *after* the anchor advances, so
        the head must already be on stable storage when that commit lands.
        """
        directory = self.path.parent
        fd, tmp = tempfile.mkstemp(dir=str(directory), prefix=self.path.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(asdict(head), handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
            tmp = None
            try:
                dir_fd = os.open(str(directory), os.O_RDONLY)
            except OSError:  # pragma: no cover - Windows has no directory fds
                return
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        finally:
            if tmp is not None:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)


def make_task_mediation_anchor(path: str | Path | None = None) -> MonotonicHeadAnchor:
    """The production anchor: a `FileMediationHeadStore` held by closure."""
    store = FileMediationHeadStore(path)
    return MonotonicHeadAnchor(store.read, store.compare_and_swap)


def resolve_task_mediation_mode() -> str:
    """``JARVIS_TASK_MEDIATION`` as a mode TaskQueue accepts — default ``off``.

    TaskQueue raises ValueError on an unknown mode, so a typo in the environment
    would otherwise crash boot. Same default-off gate convention as
    ``JARVIS_SIGNAL_GOVERNANCE`` / ``JARVIS_ACTION_KERNEL``.
    """
    raw = os.environ.get(_ENV_VAR, "")
    mode = str(raw).strip().lower()
    if not mode:
        return "off"
    if mode in MEDIATION_MODES:
        return mode
    logger.warning(
        "%s=%r is not one of off|hold|enforce; task mediation stays off", _ENV_VAR, raw
    )
    return "off"
