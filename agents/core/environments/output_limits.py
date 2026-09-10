"""The one place that says how much output a tool may return.

H298 made this module the single source for the three limits Hermes keeps in
``tools/tool_output_limits.py``. Before that the byte figure was copied into
``code_tools`` and ``session_kernels`` — three literals that could drift apart —
and the two line limits did not exist at all, so a single 5 MB line and a
50,000-line wall of output both passed every check the loop had. Bytes are not a
proxy for either: one enormous line is unreadable to a model and murder on a
terminal, and neither shape is what a byte cap is measuring.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

#: The byte ceiling on a single tool's output. Import it; do not re-declare it.
MAX_OUTPUT_BYTES = 50_000
#: How many lines survive. The middle goes, not the tail — the end of a build log
#: or a traceback is the half that says what happened.
MAX_OUTPUT_LINES = 2_000
#: How long one line may be before its middle is elided.
MAX_LINE_LENGTH = 2_000
#: The signature every truncation notice in this module carries. A line containing it
#: is the audit record of an earlier layer's cut, and :func:`cap_lines` will not drop
#: it: byte truncation puts its notice in the *middle*, which is precisely the part a
#: line cap elides, so without this a shape pass silently erases the evidence that
#: bytes went missing at all.
NOTICE_MARK = "TRUNCATED - "


@dataclass(frozen=True)
class TruncatedText:
    """Byte-accounted output limiting result."""

    text: str
    truncated: bool
    original_bytes: int
    omitted_bytes: int


def truncate_text(
    text: str,
    *,
    max_content_bytes: int,
    label: str = "OUTPUT",
) -> TruncatedText:
    """Keep head and tail content under a byte budget.

    The inserted notice is intentionally outside the content budget. The budget
    controls how much original output is retained; callers can still surface a
    human-readable truncation notice without hiding that truncation happened.
    """

    if max_content_bytes < 8:
        raise ValueError("max_content_bytes must be at least 8")

    raw = str(text or "").encode("utf-8")
    original_bytes = len(raw)
    if original_bytes <= max_content_bytes:
        return TruncatedText(
            text=str(text or ""),
            truncated=False,
            original_bytes=original_bytes,
            omitted_bytes=0,
        )

    head_budget = max_content_bytes // 2
    tail_budget = max_content_bytes - head_budget
    head = raw[:head_budget].decode("utf-8", errors="ignore")
    tail = raw[-tail_budget:].decode("utf-8", errors="ignore")
    omitted = original_bytes - max_content_bytes
    notice = (
        f"\n\n... [{label} TRUNCATED - {omitted:,} bytes omitted "
        f"out of {original_bytes:,} total] ...\n\n"
    )
    return TruncatedText(
        text=head + notice + tail,
        truncated=True,
        original_bytes=original_bytes,
        omitted_bytes=omitted,
    )


@dataclass(frozen=True, slots=True)
class StreamSinks:
    """Where a child's two streams are spooled, when anyone wants them kept.

    Threaded through the sandbox as one value rather than two parameters, and
    optional at every level: a run nobody asked to spool passes ``None`` and the
    reader behaves exactly as it did before.
    """

    stdout: Callable[[bytes], None] | None = None
    stderr: Callable[[bytes], None] | None = None


_STREAM_CHUNK = 65_536


async def read_capped_stream(
    stream,
    *,
    max_content_bytes: int,
    chunk_size: int = _STREAM_CHUNK,
    sink: Callable[[bytes], None] | None = None,
) -> tuple[bytes, bytes, int]:
    """Drain an asyncio stream while bounding peak host memory to ~budget.

    ``truncate_text`` only bounds what is *returned* — a caller that first does
    ``proc.communicate()`` still accumulates the child's entire output in host
    memory before truncating, so a runaway/hostile child (the sandbox runs
    agent-generated code) can balloon host RSS for the whole timeout window.

    This reader keeps only the first ``head_budget`` bytes and a rolling last
    ``tail_budget`` bytes, discarding the middle as it streams, so peak retained
    memory is ~``max_content_bytes`` (+ one chunk) regardless of stream size. It
    still counts the *true* total so the truncation notice can't understate.
    Returns ``(head, tail, total_bytes)``; when ``total_bytes <=
    max_content_bytes`` the head and tail concatenate to the full output with no
    overlap.

    ``sink``, when given, is called with every chunk as it arrives — before any of
    it is discarded. That is how the middle of a long stream survives without ever
    being held: the caller can spool it to disk while this reader keeps retaining
    only the ends. The sink must not raise; a sink that cannot write is expected to
    remember its own failure and stay quiet, because this function is draining a
    live child process and an exception here loses the run.
    """
    if max_content_bytes < 8:
        raise ValueError("max_content_bytes must be at least 8")

    head_budget = max_content_bytes // 2
    tail_budget = max_content_bytes - head_budget
    head = bytearray()
    tail = bytearray()
    total = 0

    while True:
        chunk = await stream.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if sink is not None:
            sink(chunk)
        take = head_budget - len(head)
        if take > 0:
            head += chunk[:take]
            rest = chunk[take:]
        else:
            rest = chunk
        if rest:
            tail += rest
            if len(tail) > tail_budget:
                del tail[: len(tail) - tail_budget]

    return bytes(head), bytes(tail), total


def render_capped(
    head: bytes,
    tail: bytes,
    total_bytes: int,
    *,
    max_content_bytes: int,
    label: str = "OUTPUT",
) -> TruncatedText:
    """Render a :func:`read_capped_stream` result, mirroring ``truncate_text``.

    Uses the true ``total_bytes`` for the omitted-bytes notice, so the
    memory-bounded read reports the same honest truncation as a full-buffer read
    would have.
    """
    if total_bytes <= max_content_bytes:
        text = (bytes(head) + bytes(tail)).decode("utf-8", errors="ignore")
        return TruncatedText(
            text=text,
            truncated=False,
            original_bytes=total_bytes,
            omitted_bytes=0,
        )

    omitted = total_bytes - (len(head) + len(tail))
    notice = (
        f"\n\n... [{label} TRUNCATED - {omitted:,} bytes omitted "
        f"out of {total_bytes:,} total] ...\n\n"
    )
    return TruncatedText(
        text=head.decode("utf-8", errors="ignore")
        + notice
        + tail.decode("utf-8", errors="ignore"),
        truncated=True,
        original_bytes=total_bytes,
        omitted_bytes=omitted,
    )


@dataclass(frozen=True)
class CappedLines:
    """What :func:`cap_lines` did, so a caller can say so honestly."""

    text: str
    lines_omitted: int
    lines_shortened: int

    @property
    def capped(self) -> bool:
        return bool(self.lines_omitted or self.lines_shortened)


def cap_lines(
    text: str,
    *,
    max_lines: int = MAX_OUTPUT_LINES,
    max_line_length: int = MAX_LINE_LENGTH,
) -> CappedLines:
    """Bound the *shape* of output, which a byte budget cannot see.

    Long lines lose their middle and keep both ends; too many lines lose the
    middle of the run and keep the head and the tail, because the last lines of a
    build log or a traceback are the ones that say what happened. Both notices are
    inline and count what was dropped — a silent elision here would be the same
    audit-versus-model divergence the spill exists to end.

    A line already carrying an earlier layer's truncation notice is never dropped,
    wherever it sits: that line is the only record that bytes went missing, and a
    byte cap always leaves it in the middle, where this function cuts.
    """
    body = str(text or "")
    limit_lines = max(2, int(max_lines))
    limit_length = max(16, int(max_line_length))
    shortened = 0
    lines = body.split("\n")
    trimmed: list[str] = []
    for line in lines:
        if len(line) <= limit_length:
            trimmed.append(line)
            continue
        shortened += 1
        keep = limit_length // 2
        dropped = len(line) - (keep + (limit_length - keep))
        trimmed.append(
            line[:keep]
            + f" ... [{dropped:,} chars omitted] ... "
            + line[-(limit_length - keep):]
        )
    omitted = 0
    if len(trimmed) > limit_lines:
        head = limit_lines // 2
        keep = set(range(head)) | set(range(len(trimmed) - (limit_lines - head), len(trimmed)))
        keep |= {index for index, line in enumerate(trimmed) if NOTICE_MARK in line}
        omitted = len(trimmed) - len(keep)
        marker = f"... [{omitted:,} lines omitted out of {len(trimmed):,} total] ..."
        rebuilt: list[str] = []
        previous = -1
        for index in sorted(keep):
            if index != previous + 1 and marker not in rebuilt:
                rebuilt.append(marker)
            rebuilt.append(trimmed[index])
            previous = index
        trimmed = rebuilt
    return CappedLines(text="\n".join(trimmed), lines_omitted=omitted,
                       lines_shortened=shortened)


__all__ = [
    "MAX_LINE_LENGTH", "MAX_OUTPUT_BYTES", "MAX_OUTPUT_LINES", "NOTICE_MARK",
    "CappedLines", "StreamSinks",
    "TruncatedText", "cap_lines", "read_capped_stream", "render_capped",
    "truncate_text",
]
