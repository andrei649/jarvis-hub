"""Output truncation helpers for future execute_code transports."""

from __future__ import annotations

from dataclasses import dataclass


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


_STREAM_CHUNK = 65_536


async def read_capped_stream(
    stream,
    *,
    max_content_bytes: int,
    chunk_size: int = _STREAM_CHUNK,
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
