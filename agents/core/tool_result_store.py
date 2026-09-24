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

**Paging it back (H661).** A spill is only worth writing if the model can get the
dropped part without running the tool again, so every notice carries the exact call —
:func:`page_recipe`, ``file_read(path="…", offset=0, max_bytes=…)`` with the path
filled in, plus the same arguments as data — and ``file_read`` pages from any byte
offset and names the next one. Three things keep that call one ``file_read`` accepts:
the path is the *resolved* one (the file tools compare a path lexically against
resolved roots, so a symlinked data root would otherwise be refused), a spill is never
named like a secret (:func:`_spill_name` — ``file_read`` refuses such names anywhere),
and the owner's ``JARVIS_FILE_ROOTS`` cannot strand a spill outside the scope, because
the coordinator hands ``file_read`` this directory as a read-only door for exact spill
names. And the claim is checked, not assumed: the store's ``read_back`` probe is asked
about the very path the recipe names — is ``file_read`` registered, offered to this
turn, and able to open *this file*? Where it is not, the notice says the file is kept
for the owner and cannot be paged from this turn instead of naming a call that would be
refused. A *stream* spill
(:meth:`ToolResultStore.open_stream`) also has a ceiling —
:data:`DEFAULT_MAX_STREAM_BYTES`, then one explicit ``[... spill capped ...]`` marker
and ``capped=True`` on the result — because agent-written code decides how much it
prints, and without one a runaway child fills the disk until its timeout.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import tempfile
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

#: The tool a spill is read back with, and the one every notice names.
READ_TOOL = "file_read"

#: Tools whose results are never spilled, and why it matters that this is *pinned*
#: rather than merely configured: ``file_read`` is how a spilled result is read back.
#: If reading a spill could itself spill, a large file would generate an unbounded
#: chain of files, each one describing the last.
#: H315 — `todo` answers with the whole plan the model must follow, and its store bounds
#: that answer below the smallest per-result budget (todo_tool.MAX_PLAN_BYTES), so it
#: is never spilled or cut, not even once the turn's own allowance is spent.
PINNED_THRESHOLDS: dict[str, float] = {READ_TOOL: math.inf, "todo": math.inf}

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
#: The most one *streamed* spill keeps (H661, Hermes' own figure). Past it the writer
#: stops, the file ends in one explicit marker and the result says ``capped``. A
#: whole-result spill needs no such ceiling: its bytes are already a string in host
#: memory, bounded by whatever produced them, and cutting JSON would make the file
#: unreadable as what it claims to be.
DEFAULT_MAX_STREAM_BYTES = 5_000_000
#: The page size a notice suggests when the caller has no better figure. The per-result
#: floor on purpose: it is the smallest allowance any model gets, so the first page a
#: notice proposes fits whichever model reads it. The model may ask for more.
DEFAULT_PAGE_BYTES = PER_RESULT_FLOOR_BYTES

_SAFE_NAME = re.compile(r"[^a-z0-9_.-]+")
#: Two shapes live here. A spilled tool *result* is JSON, because that is what the
#: loop encoded. A spilled *stream* — an `execute_code` run's stdout — is text,
#: because that is what it was; wrapping it in JSON would make the model unwrap an
#: envelope to read a log. Nothing else is a reference.
_REFERENCE = re.compile(r"^[a-z0-9_.-]{1,120}\.(?:json|txt)$")
_SPILL_GLOB = ("*.json", "*.txt")


def page_recipe(path: str, *, page_bytes: int = DEFAULT_PAGE_BYTES, offset: int = 0) -> dict:
    """The exact call that reads *path* one page at a time, as data and as text.

    ``arguments`` is what a tool call carries; ``call`` is the same thing written out
    for a notice, with the path JSON-quoted so a Windows path or a quote in a name is
    still one argument when the model copies it. Both name :data:`READ_TOOL`, the tool
    :data:`PINNED_THRESHOLDS` guarantees never spills its own read.
    """
    size = max(1, int(page_bytes))
    start = max(0, int(offset))
    target = str(path)
    return {
        "tool": READ_TOOL,
        "arguments": {"path": target, "offset": start, "max_bytes": size},
        "call": (f"{READ_TOOL}(path={json.dumps(target, ensure_ascii=False)}, "
                 f"offset={start}, max_bytes={size})"),
    }


def default_root() -> Path:
    """Where spills live unless a caller says otherwise: ``<data root>/workspace/tool_results``.

    One function rather than a repeated join, because two parties must agree on it: the
    store that writes here and the ``file_read`` that is handed this directory as a
    read-only door (H661).
    """
    from .paths import data_path

    return data_path("workspace", SPILL_DIRNAME)


def is_reference(name: object) -> bool:
    """True when *name* is shaped like a file this store writes (``<tool>-<hash>.json|txt``)."""
    return isinstance(name, str) and _REFERENCE.fullmatch(name) is not None


#: The prefix a spill falls back to when its tool's name would make it look like a secret.
_NEUTRAL_PREFIX = "result"


def _safe_tool_name(tool: str) -> str:
    name = _SAFE_NAME.sub("-", str(tool or "tool").lower()).strip("-") or "tool"
    return name[:48]


def _spill_name(tool: str, digest: str, suffix: str) -> str:
    """``<tool>-<hash>.<suffix>``, unless that name would look like a secret (H661).

    ``file_read`` refuses a secret-looking *name* anywhere in its scope — a token such as
    KEY, TOKEN, AUTH or WEBHOOK, or a prefix such as ``id_rsa`` — and bridged tools are
    named by third parties (``mcp__stripe__list_webhook_endpoints``). A spill is Nerva's
    own file; naming it after such a tool would lock it away from the very call its
    notice names. The file tools' own predicate decides, so the two cannot drift.
    """
    name = f"{_safe_tool_name(tool)}-{digest[:16]}.{suffix}"
    from .file_tools import looks_secret_name

    if looks_secret_name(name):
        return f"{_NEUTRAL_PREFIX}-{digest[:16]}.{suffix}"
    return name


def _landed_path(target: Path) -> str:
    """The path a notice names: resolved, because that is how the file tools compare.

    ``FileScope`` resolves its roots and then checks a requested path *lexically*, so a
    data root reached through a symlink would be named in a spelling ``file_read``
    refuses as outside its scope. Falls back to the path as written if resolution fails.
    """
    try:
        return str(target.resolve())
    except (OSError, RuntimeError):
        return str(target)


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
    """Where the full bytes went, and what the model is told about them.

    ``original_bytes`` is what the tool produced; ``stored_bytes`` is the file's size,
    and the two differ only when ``capped`` — the stream ran past
    :data:`DEFAULT_MAX_STREAM_BYTES` and the file ends in the marker instead.
    ``kept_bytes`` is how much of the *stream* the file holds (the marker excluded), so
    a notice can say where the stream's bytes stop without counting its own marker as
    output. ``sha256`` is always the digest of the file on disk. ``readable`` says
    whether ``file_read`` can page *this file* from the turn that gets the notice; a
    notice that names a call the model cannot make is the same dead end as no notice.
    ``path`` is resolved (see :func:`_landed_path`).
    """

    reference: str
    path: str
    original_bytes: int
    sha256: str
    stored_bytes: int | None = None
    capped: bool = False
    readable: bool = True
    kept_bytes: int | None = None

    def __post_init__(self) -> None:
        if self.stored_bytes is None:
            object.__setattr__(self, "stored_bytes", self.original_bytes)
        if self.kept_bytes is None:
            object.__setattr__(self, "kept_bytes", self.stored_bytes)

    def as_dict(self) -> dict:
        return {"reference": self.reference, "path": self.path,
                "original_bytes": self.original_bytes, "sha256": self.sha256,
                "stored_bytes": self.stored_bytes, "kept_bytes": self.kept_bytes,
                "capped": self.capped, "readable": self.readable}


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
        max_stream_bytes: int = DEFAULT_MAX_STREAM_BYTES,
        read_back: Callable[[str], bool] | None = None,
    ) -> None:
        self._root = Path(root) if root is not None else None
        self._retention = max(60.0, float(retention_seconds))
        self._max_files = max(1, int(max_files))
        self._max_total_bytes = max(1024, int(max_total_bytes))
        self._clock = clock
        self._max_stream_bytes = max(1, int(max_stream_bytes))
        # H661. Whether `file_read` can page one spilled file, asked with that file's
        # path. None means the caller did not say, which keeps the notice's recipe (the
        # historical claim); the coordinator wires the live registry, the turn's offer
        # and the live file scope, so the claim is checked per file, not assumed.
        self._read_back = read_back

    @property
    def max_stream_bytes(self) -> int:
        return self._max_stream_bytes

    def readable(self, path: str) -> bool:
        """True when the call a notice would name for *path* is one ``file_read`` takes.

        Registered is not reachable: an owner's ``JARVIS_FILE_ROOTS``, a symlinked data
        root or a secret-looking name each make ``file_read`` refuse a file it is
        registered to read, so the probe is asked about this path. A probe that raises
        counts as "no": naming a call on a guess is how a notice sends the model into a
        refusal instead of to the bytes.
        """
        if self._read_back is None:
            return True
        try:
            return bool(self._read_back(str(path)))
        except Exception:
            logger.warning("tool result read-back probe failed; not naming file_read",
                           exc_info=True)
            return False

    @property
    def root(self) -> Path:
        if self._root is None:
            self._root = default_root()
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
        reference = _spill_name(tool, digest, "json")
        temporary = None
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            target = self.root / reference
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=self.root, prefix=f".{_safe_tool_name(tool)}-",
                suffix=".tmp", delete=False,
            ) as handle:
                temporary = Path(handle.name)
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
            if temporary is not None:
                self._unlink(temporary)
            logger.warning("tool result spill failed; falling back to truncation",
                           exc_info=True)
            return None
        # Sweep after the write, never before: the new file is the one the caller is
        # about to hand to the model, so it must survive its own retention pass.
        self.sweep(keep=reference)
        path = _landed_path(target)
        return SpilledResult(reference=reference, path=path,
                             original_bytes=len(raw), sha256=digest,
                             stored_bytes=len(raw), readable=self.readable(path))

    def open_stream(self, *, tool: str, suffix: str = "txt",
                    max_bytes: int | None = None) -> StreamSpill | None:
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

        The file keeps at most ``max_bytes`` (default :attr:`max_stream_bytes`); what
        follows is counted, not written, and :meth:`StreamSpill.close` ends the file
        in one marker that says how much was left out.
        """
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 — StreamSpill owns close/discard.
                mode="wb", dir=self.root, prefix=f".{_safe_tool_name(tool)}-",
                suffix=".part", delete=False,
            )
            temporary = Path(handle.name)
        except OSError:
            logger.warning("tool result stream spill could not be opened; "
                           "falling back to truncation", exc_info=True)
            return None
        cap = self._max_stream_bytes if max_bytes is None else max(1, int(max_bytes))
        return StreamSpill(store=self, handle=handle, temporary=temporary,
                           tool=tool, suffix=suffix, max_bytes=cap)

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
                 "_digest", "_written", "_kept", "_cap", "_capped", "_failed", "_closed")

    def __init__(self, *, store: ToolResultStore, handle, temporary: Path,
                 tool: str, suffix: str, max_bytes: int = DEFAULT_MAX_STREAM_BYTES) -> None:
        self._store = store
        self._handle = handle
        self._temporary = temporary
        self._tool = tool
        self._suffix = "txt" if str(suffix or "").lower() not in {"json", "txt"} else str(suffix).lower()
        self._digest = hashlib.sha256()
        self._written = 0
        self._kept = 0
        self._cap = max(1, int(max_bytes))
        self._capped = False
        self._failed = False
        self._closed = False

    @property
    def written_bytes(self) -> int:
        """Every byte the stream produced, kept or not — its true length.

        This is the figure the caller compares against what the model was shown, so
        it must not stop at the ceiling: a stream past the cap was certainly cut.
        """
        return self._written

    @property
    def capped(self) -> bool:
        return self._capped

    def _marker(self) -> bytes:
        dropped = max(0, self._written - self._kept)
        return (f"\n[... spill capped at {self._cap} bytes: {dropped} more bytes of "
                f"this stream were not kept ...]\n").encode()

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
        self._written += len(chunk)
        room = self._cap - self._kept
        if len(chunk) > room:
            # H661. The ceiling: keep the head of this chunk, count the rest, and let
            # `close` say so once. Writing nothing further is the point — the reader
            # keeps draining the child, the disk stops filling.
            self._capped = True
            chunk = chunk[:room]
            if not chunk:
                return
        try:
            self._handle.write(chunk)
        except (OSError, ValueError):
            logger.warning("tool result stream spill failed mid-write", exc_info=True)
            self._failed = True
            return
        self._digest.update(chunk)
        self._kept += len(chunk)

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
        stored = self._kept
        if self._capped and not self._failed and self._kept > 0:
            marker = self._marker()
            try:
                self._handle.write(marker)
                self._digest.update(marker)
                stored += len(marker)
            except (OSError, ValueError):
                logger.warning("tool result stream spill failed to mark its cap",
                               exc_info=True)
                self._failed = True
        try:
            self._handle.flush()
            os.fsync(self._handle.fileno())
        except (OSError, ValueError):
            logger.warning("tool result stream spill failed to close", exc_info=True)
            self._failed = True
        finally:
            try:
                self._handle.close()
            except (OSError, ValueError):
                logger.warning("tool result stream spill failed to close", exc_info=True)
                self._failed = True
        if self._failed or self._kept <= 0:
            self._store._unlink(self._temporary)
            return None
        digest = self._digest.hexdigest()
        reference = _spill_name(self._tool, digest, self._suffix)
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
        path = _landed_path(target)
        return SpilledResult(reference=reference, path=path,
                             original_bytes=self._written, sha256=digest,
                             stored_bytes=stored, capped=self._capped,
                             readable=self._store.readable(path), kept_bytes=self._kept)


def preview_envelope(
    encoded: str,
    *,
    tool: str,
    ok: bool,
    reason: object,
    spill: SpilledResult,
    preview_chars: int = PREVIEW_CHARS,
    page_bytes: int = DEFAULT_PAGE_BYTES,
) -> str:
    """The bounded thing the model sees, with the footer that names the full copy.

    The footer is an instruction the model can follow verbatim (H661): the exact
    ``file_read`` call, path filled in, as text in ``notice`` and as arguments in
    ``read_with``. When ``file_read`` cannot page this file from this turn — not
    registered, not offered to the turn, or unable to open the path — ``read_with`` is
    left out and the notice says so, so the model is not sent into a refusal.
    """
    body = str(encoded or "")
    kept = max(64, int(preview_chars))
    head = body[: kept // 2]
    tail = body[-(kept - len(head)):] if len(body) > kept else ""
    recipe = page_recipe(spill.path, page_bytes=page_bytes) if spill.readable else None
    if recipe is not None:
        notice = (
            f"This result was too large for the context window. The complete result "
            f"({spill.original_bytes} bytes) is on disk at {spill.path}. Page it with "
            f"{recipe['call']} and pass each page's next_offset back as offset until a "
            f"page has none, instead of running the tool again."
        )
    else:
        notice = (
            f"This result was too large for the context window. The complete result "
            f"({spill.original_bytes} bytes) is on disk at {spill.path} for the owner; "
            f"{READ_TOOL} is not available to this turn for that file, so it cannot be "
            f"paged from here. If the omitted part matters, ask for a narrower result "
            f"rather than repeating the same call."
        )
    payload: dict[str, object] = {
        "ok": bool(ok),
        "tool": str(tool or "")[:64],
        "truncated": True,
        "spilled": True,
        "notice": notice,
        "original_bytes": spill.original_bytes,
        "preview": {"head": head, "tail": tail},
        "result_file": spill.path,
        "result_reference": spill.reference,
        "sha256": spill.sha256,
    }
    if recipe is not None:
        payload["read_with"] = {"tool": recipe["tool"], "arguments": recipe["arguments"]}
    if not ok and isinstance(reason, str):
        payload["reason"] = reason[:120]
    return json.dumps(payload, ensure_ascii=False, allow_nan=False)


__all__ = [
    "BYTES_PER_TOKEN", "Budget", "DEFAULT_MAX_FILES", "DEFAULT_MAX_RESULT_BYTES",
    "DEFAULT_MAX_STREAM_BYTES", "DEFAULT_MAX_TOTAL_BYTES", "DEFAULT_PAGE_BYTES",
    "DEFAULT_RETENTION_SECONDS", "MAX_LINE_LENGTH",
    "MAX_OUTPUT_BYTES", "MAX_OUTPUT_LINES", "MCP_DEFAULT_BYTES", "MCP_PREFIX",
    "PER_RESULT_FLOOR_BYTES", "PER_TURN_FLOOR_BYTES", "PINNED_THRESHOLDS",
    "PREVIEW_CHARS", "READ_TOOL", "SPILL_DIRNAME", "SpilledResult", "StreamSpill",
    "ToolResultStore",
    "budget_for_context_window", "cap_lines", "default_root", "is_reference",
    "page_recipe", "preview_envelope", "threshold_for",
]
