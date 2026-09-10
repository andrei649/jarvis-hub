"""H298: keep a huge tool result out of the context window without losing it.

The loop already refused to let a giant result flood the turn — it truncated to a
head+tail preview and moved on. That protects the context and throws the rest away,
which is the wrong trade twice over:

* **The audit and the model diverge.** A truncated ``file_read``, or a truncated
  governed ``terminal_run`` transcript, means the owner reviewing an approval sees
  less than the tool actually produced. The record of what happened should not be
  the lossy copy.
* **The work is repeatable but not recoverable.** The model's only way back to the
  dropped bytes is to run the tool again — the expensive thing the cap existed to
  avoid — and a non-deterministic tool cannot even do that.

So an oversized result is **spilled**: the full bytes go to a file under the data
root and the model gets a bounded preview whose footer names the path. Nothing is
lost, the context stays small, and the file sits inside the file tools' default root
so ``file_read`` can fetch any part of it without a second tool.

Three things decide how big is too big, in this order:

1. **A per-tool threshold** (:func:`threshold_for`) — pinned, then an owner override,
   then the ``mcp_`` family default, then the tool's own declared maximum, then the
   global default. ``file_read`` is pinned to *no limit* on purpose: it is how a
   spilled result is read back, and spilling the read of a spill is an infinite
   regress with disk writes.
2. **A budget scaled to the model's real context window**
   (:func:`budget_for_context_window`) — 15% of the window for one result and 30%
   for a whole turn, with floors. A constant 50 KB is generous on a 200k-token cloud
   model and ruinous on the 8k local one this product is built around.
3. **What the turn has already spent.** The per-turn budget is the part a single cap
   cannot express: five results at 40% of the limit each still bury a small window.

Retention is part of the contract, not a follow-up: :meth:`ToolResultStore.sweep`
enforces an age limit, a file count and a total size on every write, so the spill
directory cannot grow without bound on a box nobody is watching.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

# The three limits live in one module (H298). They are re-exported here because
# this is the surface the tool loop imports, but they are not redeclared: a second
# literal is how the byte figure ended up meaning three different things.
from .environments.output_limits import (
    MAX_LINE_LENGTH,
    MAX_OUTPUT_BYTES,
    MAX_OUTPUT_LINES,
    cap_lines,
)

logger = logging.getLogger("jarvis.tool_result_store")

#: The global default when nothing more specific applies.
DEFAULT_MAX_RESULT_BYTES = MAX_OUTPUT_BYTES
#: How much of a spilled result the model still sees inline.
PREVIEW_CHARS = 1_500

#: Tools whose results are never spilled, and why it matters that this is *pinned*
#: rather than merely configured: ``file_read`` is how a spilled result is read back.
#: If reading a spill could itself spill, a large file would generate an unbounded
#: chain of files, each one describing the last.
PINNED_THRESHOLDS: dict[str, float] = {"file_read": math.inf}

#: Bridged MCP tools share one default: their sizes are a third party's decision, so
#: they get a tighter allowance than first-party tools rather than the global one.
MCP_PREFIX = "mcp_"
MCP_DEFAULT_BYTES = 20_000

#: Fractions of the model's real context window, and the floors below which scaling
#: stops being useful. A 4k-token model would otherwise get a ~600-byte allowance.
PER_RESULT_FRACTION = 0.15
PER_TURN_FRACTION = 0.30
PER_RESULT_FLOOR_BYTES = 8_000
PER_TURN_FLOOR_BYTES = 16_000
#: Rough bytes per token. Deliberately crude and stated rather than hidden: this
#: converts a window measured in tokens into a byte allowance, and being wrong by a
#: factor of two moves a cap, never a correctness boundary.
BYTES_PER_TOKEN = 4

#: Spill files live inside the file tools' *default* root, so the path in a preview
#: footer is one a `file_read` can actually open without the owner reconfiguring
#: anything. Their own subdirectory keeps them separable from the owner's workspace.
SPILL_DIRNAME = "tool_results"
DEFAULT_RETENTION_SECONDS = 24 * 3600.0
DEFAULT_MAX_FILES = 512
DEFAULT_MAX_TOTAL_BYTES = 256 * 1024 * 1024

_SAFE_NAME = re.compile(r"[^a-z0-9_.-]+")
#: Two shapes live here. A spilled tool *result* is JSON, because that is what the
#: loop encoded. A spilled *stream* — an `execute_code` run's stdout — is text,
#: because that is what it was; wrapping it in JSON would make the model unwrap an
#: envelope to read a log. Nothing else is a reference.
_REFERENCE = re.compile(r"^[a-z0-9_.-]{1,120}\.(?:json|txt)$")
_SPILL_GLOB = ("*.json", "*.txt")


def _safe_tool_name(tool: str) -> str:
    name = _SAFE_NAME.sub("-", str(tool or "tool").lower()).strip("-") or "tool"
    return name[:48]


@dataclass(frozen=True, slots=True)
class Budget:
    """What one result, and one whole turn, may spend on the context window."""

    per_result_bytes: int
    per_turn_bytes: int

    def as_dict(self) -> dict:
        return {"per_result_bytes": self.per_result_bytes,
                "per_turn_bytes": self.per_turn_bytes}


def budget_for_context_window(window_tokens: object,
                              *, bytes_per_token: int = BYTES_PER_TOKEN) -> Budget:
    """Scale the caps to the model actually in use, never below the floors.

    An unreadable or absurd window falls back to the floors rather than to something
    generous: the failure mode of guessing too small is a spill, and the failure mode
    of guessing too large is a turn that will not fit.
    """
    try:
        window = int(window_tokens)
    except (TypeError, ValueError):
        window = 0
    budget_bytes = max(0, window) * max(1, int(bytes_per_token))
    return Budget(
        per_result_bytes=max(PER_RESULT_FLOOR_BYTES, int(budget_bytes * PER_RESULT_FRACTION)),
        per_turn_bytes=max(PER_TURN_FLOOR_BYTES, int(budget_bytes * PER_TURN_FRACTION)),
    )


def threshold_for(
    tool: str,
    *,
    overrides: Mapping[str, object] | None = None,
    declared: object = None,
    default: int = DEFAULT_MAX_RESULT_BYTES,
) -> float:
    """Resolve one tool's byte threshold, most specific rule first.

    pinned → owner override → the ``mcp_`` family → the tool's own declared maximum →
    the default. Returning ``inf`` means "never spill this one".
    """
    name = str(tool or "")
    if name in PINNED_THRESHOLDS:
        return PINNED_THRESHOLDS[name]
    if overrides:
        raw = overrides.get(name)
        if raw is not None:
            value = _positive_int(raw)
            if value is not None:
                return value
    if name.startswith(MCP_PREFIX):
        return MCP_DEFAULT_BYTES
    value = _positive_int(declared)
    if value is not None:
        return value
    return max(1, int(default))


def _positive_int(raw: object) -> int | None:
    """A usable byte count, or None so the next rule down applies.

    ``OverflowError`` is caught alongside the obvious two: ``int(float("inf"))``
    raises it, and an override of ``inf`` reaching this function must fall through
    to the next rule rather than take the whole resolution down with it.
    """
    try:
        value = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return value if value > 0 else None


@dataclass(frozen=True, slots=True)
class SpilledResult:
    """Where the full bytes went, and what the model is told about them."""

    reference: str
    path: str
    original_bytes: int
    sha256: str

    def as_dict(self) -> dict:
        return {"reference": self.reference, "path": self.path,
                "original_bytes": self.original_bytes, "sha256": self.sha256}


class ToolResultStore:
    """Write oversized results to disk, and keep the directory from growing forever."""

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        retention_seconds: float = DEFAULT_RETENTION_SECONDS,
        max_files: int = DEFAULT_MAX_FILES,
        max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._root = Path(root) if root is not None else None
        self._retention = max(60.0, float(retention_seconds))
        self._max_files = max(1, int(max_files))
        self._max_total_bytes = max(1024, int(max_total_bytes))
        self._clock = clock

    @property
    def root(self) -> Path:
        if self._root is None:
            from .paths import data_path

            self._root = data_path("workspace", SPILL_DIRNAME)
        return self._root

    # ── writing ──────────────────────────────────────────────────────────────

    def spill(self, encoded: str, *, tool: str) -> SpilledResult | None:
        """Persist the full result. ``None`` means the caller must truncate instead.

        A spill that fails is not an error the turn should carry: the loop still has
        a correct, bounded answer to give the model. It is a warning and a fall back
        to the old behaviour, never a lost turn.
        """
        body = str(encoded or "")
        raw = body.encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        reference = f"{_safe_tool_name(tool)}-{digest[:16]}.json"
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            target = self.root / reference
            temporary = target.with_suffix(".json.tmp")
            with temporary.open("wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(target)
            # Stamp the file from the store's own clock rather than leaving it to
            # the filesystem. Retention compares against this clock, so letting the
            # two disagree would make the injected clock decorative and the age
            # limit untestable — which is how an unbounded directory ships.
            written = self._clock()
            os.utime(target, (written, written))
        except OSError:
            logger.warning("tool result spill failed; falling back to truncation",
                           exc_info=True)
            return None
        # Sweep after the write, never before: the new file is the one the caller is
        # about to hand to the model, so it must survive its own retention pass.
        self.sweep(keep=reference)
        return SpilledResult(reference=reference, path=str(target),
                             original_bytes=len(raw), sha256=digest)

    def open_stream(self, *, tool: str, suffix: str = "txt") -> StreamSpill | None:
        """A spill written as it arrives, for bytes that must never be buffered whole.

        :meth:`spill` takes a string the caller already holds. A sandboxed child's
        stdout is the opposite case: the reason it is capped at all is that holding
        it in host memory is the hazard (agent-written code decides how much it
        prints). So this hands back a writer the *reader* feeds chunk by chunk —
        peak host memory stays whatever the reader retains, and the file gets
        everything, which is the only version of this feature worth having. A
        truncated copy on disk would be the same loss with an extra step.

        ``None`` means the directory could not be opened; the caller truncates as
        before rather than losing the turn.
        """
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            temporary = self.root / f".{_safe_tool_name(tool)}-{os.getpid()}-{id(self):x}.part"
            handle = temporary.open("wb")
        except OSError:
            logger.warning("tool result stream spill could not be opened; "
                           "falling back to truncation", exc_info=True)
            return None
        return StreamSpill(store=self, handle=handle, temporary=temporary,
                           tool=tool, suffix=suffix)

    # ── reading back ─────────────────────────────────────────────────────────

    def read(self, reference: str, *, max_bytes: int = MAX_OUTPUT_BYTES) -> str | None:
        """Read a spilled result by reference. Refuses anything that is not one.

        The reference is matched against a strict pattern and joined to the root, so
        a caller cannot walk out of the spill directory with `..` or an absolute path.
        """
        name = str(reference or "")
        if not _REFERENCE.fullmatch(name):
            return None
        target = self.root / name
        try:
            resolved = target.resolve()
            if resolved.parent != self.root.resolve() or not resolved.is_file():
                return None
            if resolved.stat().st_size > max(1, int(max_bytes)):
                with resolved.open("rb") as handle:
                    return handle.read(int(max_bytes)).decode("utf-8", errors="ignore")
            return resolved.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None

    # ── retention ────────────────────────────────────────────────────────────

    def sweep(self, *, keep: str = "") -> int:
        """Enforce age, count and total size. Returns how many files were removed.

        This is the row's stated dependency rather than a nicety: a spill directory
        with no retention is a disk-filling bug on a box nobody is watching.
        """
        try:
            entries = [
                (path.stat().st_mtime, path.stat().st_size, path)
                for pattern in _SPILL_GLOB
                for path in self.root.glob(pattern)
            ]
        except OSError:
            return 0
        cutoff = self._clock() - self._retention
        removed = 0
        survivors: list[tuple[float, int, Path]] = []
        for mtime, size, path in sorted(entries):
            if path.name != keep and mtime < cutoff:
                removed += self._unlink(path)
                continue
            survivors.append((mtime, size, path))
        # Oldest first out, until both the count and the byte budget fit.
        total = sum(size for _mtime, size, _path in survivors)
        index = 0
        while index < len(survivors) and (
            len(survivors) - index > self._max_files or total > self._max_total_bytes
        ):
            _mtime, size, path = survivors[index]
            index += 1
            if path.name == keep:
                continue
            removed += self._unlink(path)
            total -= size
        return removed

    @staticmethod
    def _unlink(path: Path) -> int:
        try:
            path.unlink()
            return 1
        except OSError:
            return 0


class StreamSpill:
    """The open half of a streaming spill. Feed it chunks; :meth:`close` names the file.

    The name is content-addressed like a whole-result spill, so the digest is computed
    as the bytes go past rather than by re-reading the finished file — the point of
    this class is that nothing ever holds the whole stream, and that has to include
    the naming.
    """

    __slots__ = ("_store", "_handle", "_temporary", "_tool", "_suffix",
                 "_digest", "_written", "_failed", "_closed")

    def __init__(self, *, store: ToolResultStore, handle, temporary: Path,
                 tool: str, suffix: str) -> None:
        self._store = store
        self._handle = handle
        self._temporary = temporary
        self._tool = tool
        self._suffix = "txt" if str(suffix or "").lower() not in {"json", "txt"} else str(suffix).lower()
        self._digest = hashlib.sha256()
        self._written = 0
        self._failed = False
        self._closed = False

    @property
    def written_bytes(self) -> int:
        return self._written

    def write(self, chunk: bytes) -> None:
        """Take one chunk. A write that fails disables the spill without raising.

        The caller is a stream reader in the middle of draining a child process; an
        exception here would turn a disk problem into a lost run. The failure is
        remembered so :meth:`close` reports it honestly instead of naming a file
        that holds part of the output.

        ``ValueError`` is caught alongside ``OSError`` because a file object that has
        been closed under us raises it, and "the handle went away" is the same
        situation as "the write failed" from here.
        """
        if self._failed or self._closed or not chunk:
            return
        try:
            self._handle.write(chunk)
        except (OSError, ValueError):
            logger.warning("tool result stream spill failed mid-write", exc_info=True)
            self._failed = True
            return
        self._digest.update(chunk)
        self._written += len(chunk)

    def discard(self) -> None:
        """Close and remove, for a stream the model already has in full.

        The spill is opened before the run, because that is the only moment it can
        be; whether it is *worth keeping* is knowable only afterwards. A run whose
        output fitted needs no second copy, and writing one anyway would fill the
        retention budget with files nobody will ever open.
        """
        if self._closed:
            return
        self._closed = True
        try:
            self._handle.close()
        except (OSError, ValueError):
            logger.warning("tool result stream spill failed to close", exc_info=True)
        self._store._unlink(self._temporary)

    def close(self) -> SpilledResult | None:
        """Finalise and name the file, or clean up and return ``None``.

        ``None`` covers three cases the caller treats alike — a failed write, an
        empty stream, and a failed rename — because in all three there is no complete
        copy on disk to point the model at.
        """
        if self._closed:
            return None
        self._closed = True
        try:
            self._handle.flush()
            os.fsync(self._handle.fileno())
            self._handle.close()
        except (OSError, ValueError):
            logger.warning("tool result stream spill failed to close", exc_info=True)
            self._failed = True
        if self._failed or self._written <= 0:
            self._store._unlink(self._temporary)
            return None
        digest = self._digest.hexdigest()
        reference = f"{_safe_tool_name(self._tool)}-{digest[:16]}.{self._suffix}"
        target = self._store.root / reference
        try:
            self._temporary.replace(target)
            written = self._store._clock()
            os.utime(target, (written, written))
        except OSError:
            logger.warning("tool result stream spill failed to land", exc_info=True)
            self._store._unlink(self._temporary)
            return None
        self._store.sweep(keep=reference)
        return SpilledResult(reference=reference, path=str(target),
                             original_bytes=self._written, sha256=digest)


def preview_envelope(
    encoded: str,
    *,
    tool: str,
    ok: bool,
    reason: object,
    spill: SpilledResult,
    preview_chars: int = PREVIEW_CHARS,
) -> str:
    """The bounded thing the model sees, with the footer that names the full copy."""
    body = str(encoded or "")
    kept = max(64, int(preview_chars))
    head = body[: kept // 2]
    tail = body[-(kept - len(head)):] if len(body) > kept else ""
    payload: dict[str, object] = {
        "ok": bool(ok),
        "tool": str(tool or "")[:64],
        "truncated": True,
        "spilled": True,
        "notice": (
            "This result was too large for the context window. The complete result is "
            "on disk at the path below; read it with file_read (whole or in parts) "
            "instead of running the tool again."
        ),
        "original_bytes": spill.original_bytes,
        "preview": {"head": head, "tail": tail},
        "result_file": spill.path,
        "result_reference": spill.reference,
        "sha256": spill.sha256,
    }
    if not ok and isinstance(reason, str):
        payload["reason"] = reason[:120]
    return json.dumps(payload, ensure_ascii=False, allow_nan=False)


__all__ = [
    "BYTES_PER_TOKEN", "Budget", "DEFAULT_MAX_FILES", "DEFAULT_MAX_RESULT_BYTES",
    "DEFAULT_MAX_TOTAL_BYTES", "DEFAULT_RETENTION_SECONDS", "MAX_LINE_LENGTH",
    "MAX_OUTPUT_BYTES", "MAX_OUTPUT_LINES", "MCP_DEFAULT_BYTES", "MCP_PREFIX",
    "PER_RESULT_FLOOR_BYTES", "PER_TURN_FLOOR_BYTES", "PINNED_THRESHOLDS",
    "PREVIEW_CHARS", "SPILL_DIRNAME", "SpilledResult", "StreamSpill",
    "ToolResultStore",
    "budget_for_context_window", "cap_lines", "preview_envelope", "threshold_for",
]
