"""Output limiting helpers for future execute_code transports."""

import pytest

from agents.core.environments.output_limits import truncate_text


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
