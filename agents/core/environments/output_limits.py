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
