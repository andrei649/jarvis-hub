"""Output limiting helpers for future execute_code transports."""

import pytest

from agents.core.environments.output_limits import (
    read_capped_stream,
    render_capped,
    truncate_text,
)


class _FakeStream:
    """Minimal asyncio.StreamReader stand-in that yields pre-chunked bytes."""

    def __init__(self, chunks):
        self._chunks = list(chunks)

    async def read(self, n: int = -1) -> bytes:
        if self._chunks:
            return self._chunks.pop(0)
        return b""


def test_short_text_is_returned_unchanged():
    result = truncate_text("hello", max_content_bytes=20)

    assert result.text == "hello"
    assert result.truncated is False
    assert result.original_bytes == 5
    assert result.omitted_bytes == 0


def test_long_text_keeps_head_tail_and_reports_omitted_bytes():
    text = "head-" + ("x" * 100) + "-tail"

    result = truncate_text(text, max_content_bytes=20)

    assert result.truncated is True
    assert result.original_bytes == len(text.encode("utf-8"))
    assert result.omitted_bytes == result.original_bytes - 20
    assert result.text.startswith("head-")
    assert result.text.endswith("-tail")
    assert "OUTPUT TRUNCATED" in result.text


def test_truncation_is_utf8_boundary_safe():
    text = "\u2192" * 40

    result = truncate_text(text, max_content_bytes=21)

    assert result.truncated is True
    assert "\ufffd" not in result.text
    assert result.text.startswith("\u2192")
    assert result.text.endswith("\u2192")


def test_tiny_limits_are_rejected():
    with pytest.raises(ValueError):
        truncate_text("hello", max_content_bytes=7)


# ── streaming capped reader (host-memory-DoS fix) ────────────────────────────

async def test_capped_reader_bounds_peak_memory_on_a_runaway_stream():
    # 1 MB of output at a 20-byte budget: the reader must retain <= budget,
    # never accumulating the whole stream in host memory, while still counting
    # the true total so the truncation notice can't lie.
    chunks = [b"x" * 1024] * 1024  # 1,048,576 bytes
    head, tail, total = await read_capped_stream(
        _FakeStream(chunks), max_content_bytes=20
    )

    assert total == 1024 * 1024
    assert len(head) + len(tail) <= 20  # peak retained bytes are bounded, not 1 MB


async def test_capped_reader_returns_small_output_intact():
    head, tail, total = await read_capped_stream(
        _FakeStream([b"hel", b"lo"]), max_content_bytes=20
    )

    assert total == 5
    assert head + tail == b"hello"  # no overlap/duplication under budget


async def test_capped_reader_keeps_head_and_tail_across_chunks():
    chunks = [b"head-", b"m" * 100, b"-tail"]
    head, tail, total = await read_capped_stream(
        _FakeStream(chunks), max_content_bytes=20
    )

    assert total == 110
    assert head.startswith(b"head-")
    assert tail.endswith(b"-tail")


def test_render_capped_mirrors_truncate_text_notice_with_true_total():
    rendered = render_capped(b"head-", b"-tail", 110, max_content_bytes=20)

    assert rendered.truncated is True
    assert rendered.original_bytes == 110  # the TRUE size, not the retained size
    assert rendered.text.startswith("head-")
    assert rendered.text.endswith("-tail")
    assert "OUTPUT TRUNCATED" in rendered.text
    assert "110" in rendered.text


def test_render_capped_untruncated_passes_content_through():
    rendered = render_capped(b"hel", b"lo", 5, max_content_bytes=20)

    assert rendered.truncated is False
    assert rendered.text == "hello"
    assert rendered.omitted_bytes == 0
