"""Output limiting helpers — the one place that says how much a tool may return."""

import pytest

from agents.core.environments.output_limits import (
    MAX_LINE_LENGTH,
    MAX_OUTPUT_BYTES,
    MAX_OUTPUT_LINES,
    StreamSinks,
    cap_lines,
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


# ── the shape a byte budget cannot see (H298) ────────────────────────────────

def test_the_three_limits_live_here_and_nowhere_else():
    """One source, and the modules that used to hold copies now import it.

    The byte figure was declared three times before H298 — here, in `code_tools`
    and in `session_kernels` — which is how three "50 KB" limits become three
    different numbers after one of them is tuned.
    """
    from agents.core import code_tools, session_kernels, tool_result_store

    assert (MAX_OUTPUT_BYTES, MAX_OUTPUT_LINES, MAX_LINE_LENGTH) == (50_000, 2_000, 2_000)
    assert code_tools.MAX_OUTPUT_BYTES is MAX_OUTPUT_BYTES
    assert session_kernels.DEFAULT_MAX_OUTPUT_BYTES is MAX_OUTPUT_BYTES
    assert tool_result_store.MAX_OUTPUT_BYTES is MAX_OUTPUT_BYTES
    assert tool_result_store.MAX_OUTPUT_LINES is MAX_OUTPUT_LINES
    assert tool_result_store.MAX_LINE_LENGTH is MAX_LINE_LENGTH


def test_output_that_fits_both_limits_is_returned_unchanged():
    capped = cap_lines("one\ntwo\nthree")

    assert capped.text == "one\ntwo\nthree"
    assert capped.capped is False
    assert (capped.lines_omitted, capped.lines_shortened) == (0, 0)


def test_one_enormous_line_keeps_both_ends_and_says_how_much_went():
    capped = cap_lines("A" * 40 + "B" * 9_000 + "C" * 40, max_line_length=100)

    assert capped.lines_shortened == 1 and capped.lines_omitted == 0
    assert capped.text.startswith("A" * 40)
    assert capped.text.endswith("C" * 40)
    assert "8,980 chars omitted" in capped.text
    # The notice sits outside the content budget, exactly as truncate_text's does.
    assert len(capped.text.replace(capped.text[50:-50], "")) <= 100


def test_too_many_lines_lose_the_middle_and_never_the_tail():
    """The end of a build log or a traceback is the half that says what happened."""
    capped = cap_lines("\n".join(f"line-{i}" for i in range(500)), max_lines=10)

    lines = capped.text.split("\n")
    assert capped.lines_omitted == 490
    assert len(lines) == 11  # ten kept plus the notice
    assert lines[0] == "line-0"
    assert lines[-1] == "line-499", "the tail must survive"
    assert "490 lines omitted out of 500 total" in capped.text


def test_both_limits_apply_to_the_same_output():
    capped = cap_lines(
        "\n".join("x" * 5_000 for _ in range(50)), max_lines=6, max_line_length=100,
    )

    assert capped.lines_omitted == 44
    assert capped.lines_shortened == 50
    assert len(capped.text.encode("utf-8")) < 50 * 5_000


def test_an_earlier_layers_truncation_notice_is_never_elided():
    """The shape cap must not erase the record that bytes went missing.

    `truncate_text` puts its notice between the head and the tail — precisely the
    part `cap_lines` cuts. Without this the two composed into a silent truncation:
    output that had lost 200 KB came back looking whole, which is the exact
    audit-versus-model divergence the spill exists to end.
    """
    byte_capped = truncate_text("\n".join(f"line-{i}" for i in range(4_000)),
                                max_content_bytes=200, label="STDOUT")
    assert byte_capped.truncated is True

    capped = cap_lines(byte_capped.text, max_lines=10)

    assert "STDOUT TRUNCATED" in capped.text, "the byte notice survived the line cap"
    assert "bytes omitted" in capped.text
    assert "lines omitted out of" in capped.text
    assert capped.text.split("\n")[-1] == byte_capped.text.split("\n")[-1]


def test_a_kept_notice_is_not_counted_as_an_omitted_line():
    capped = cap_lines(
        "\n".join(["a"] * 20 + ["... [OUTPUT TRUNCATED - 9 bytes omitted out of 99 total] ..."]
                  + ["b"] * 20),
        max_lines=10,
    )

    kept = [line for line in capped.text.split("\n") if "lines omitted out of" not in line]
    assert capped.lines_omitted == 41 - len(kept)


@pytest.mark.parametrize("absurd", [0, 1, -5])
def test_an_absurd_limit_is_floored_rather_than_crashing(absurd):
    capped = cap_lines("a\nb\nc\nd", max_lines=absurd, max_line_length=absurd)

    assert capped.text  # a floor, not a ZeroDivisionError or an empty result


# ── spooling the middle instead of dropping it (H305/H595) ───────────────────

@pytest.mark.asyncio
async def test_the_sink_sees_every_byte_while_the_reader_still_keeps_only_the_ends():
    """The two halves of the bargain, in one assertion each.

    The reader's whole reason to exist is that agent-written code decides how much
    it prints, so the host must not hold it. The sink does not weaken that: it is
    handed each chunk on the way past, and what this function *retains* is
    unchanged. Break either half and the feature is pointless — buffering to spill
    reintroduces the hazard, spooling the truncation keeps the loss.
    """
    chunks = [b"A" * 1_000 for _ in range(40)]
    spooled = bytearray()
    stream = _FakeStream(list(chunks))

    head, tail, total = await read_capped_stream(
        stream, max_content_bytes=100, chunk_size=1_000, sink=spooled.extend,
    )

    assert total == 40_000
    assert bytes(spooled) == b"".join(chunks), "the sink got the middle the reader dropped"
    assert len(head) + len(tail) == 100, "the reader still retains only the budget"


@pytest.mark.asyncio
async def test_no_sink_leaves_the_reader_exactly_as_it_was():
    stream = _FakeStream([b"one", b"two"])

    assert await read_capped_stream(stream, max_content_bytes=64) == (b"onetwo", b"", 6)


def test_stream_sinks_default_to_spooling_nothing():
    sinks = StreamSinks()

    assert (sinks.stdout, sinks.stderr) == (None, None)
