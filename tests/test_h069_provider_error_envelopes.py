"""Whole provider error envelopes are safe without consuming adjacent prose.
"""

import httpx
import pytest

from agents.core.channels.outbound_safety import (
    install_known_secret_redactor,
    safe_stream_prefix,
    sanitize_text,
)
from agents.core.llm.anthropic import ClaudeBackend

PRIVATE = "req_private_marker"
POLICY = "private refusal policy body"


@pytest.mark.parametrize("detail", [
    f"Error code: 401 - {{\n  'request_id': '{PRIVATE}',\n  'policy': '{POLICY}'\n}}",
    "Error code: 401 - " + ("ordinary provider body " * 210) +
    f" request_id={PRIVATE} policy={POLICY}",
])
def test_complete_provider_error_envelope_never_releases_body(detail):
    raw = f"[Claude API error: {detail}]"
    assert safe_stream_prefix(raw) == ""  # the provisional stream stays withheld
    shown = sanitize_text(raw)
    assert shown.startswith("The model provider Claude ")
    assert PRIVATE not in shown and POLICY not in shown
    assert "request_id" not in shown and "ordinary provider body" not in shown


@pytest.mark.asyncio
async def test_anthropic_native_post_exception_reaches_same_envelope():
    backend = ClaudeBackend("fixture-key")
    original = backend.client
    await original.aclose()

    async def transport(_request):
        raise RuntimeError(f"Error code: 401 - {{\n'request_id': '{PRIVATE}', "
                           f"'policy': '{POLICY}'\n}}")

    backend.client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    try:
        data, raw, status = await backend._post_messages({"model": "claude-sonnet-4-5"})
    finally:
        await backend.client.aclose()
    assert data is None and status is None
    # A future producer-safe marker must not have to echo the exception text.
    assert raw.startswith("[Claude API error: ")
    assert safe_stream_prefix(raw) == ""
    shown = sanitize_text(raw)
    assert shown.startswith("The model provider Claude ")
    assert PRIVATE not in shown and POLICY not in shown


def test_unknown_provider_name_is_not_echoed_and_prose_is_preserved():
    for raw in (
        "[UntrustedVendor API error: HTTP 403 - request_id=req_private_marker]",
        "[UntrustedVendor API error: HTTP 403\nrequest_id=req_private_marker]",
        "[UntrustedVendor API error: " + ("ordinary body " * 400) +
        "request_id=req_private_marker]",
    ):
        shown = sanitize_text(raw)
        assert shown.startswith("The model provider ")
        assert "UntrustedVendor" not in shown and PRIVATE not in shown
    for prose in (
        "The [Claude API error] you saw yesterday is fixed.",
        "[Claude API error] The old incident is fixed.",
        "[Claude API error: Error code: 401] This paragraph is not a marker.",
        "A quoted [Claude API error: HTTP 401] is ordinary prose.",
    ):
        assert sanitize_text(prose) == prose


def test_incomplete_envelope_is_withheld_while_streaming_and_not_reclassified():
    partial = "[Claude API error: HTTP 401 - still arriving"
    assert safe_stream_prefix(partial) == ""
    assert sanitize_text(partial) == partial


@pytest.mark.parametrize("prose", [
    "[Claude API error: 401]\n[Here is the completed answer]",
    "[Claude API error: " + ("provider detail " * 290) + "]\nprose [done]",
])
def test_a_completed_marker_followed_by_prose_is_not_a_whole_error(prose):
    assert safe_stream_prefix(prose) == ""
    assert sanitize_text(prose) == prose


@pytest.mark.parametrize("detail", [
    'Error code: 401 - {"errors":[{"message":"literal ] and [ in a quote"}]}',
    'Error code: 401 - {"errors":[{"message":"escaped \\" ] still quoted"}]}',
    "Error code: 401 - {'errors': [{'message': 'literal ] and [ in a quote'}]}",
    "Error code: 401 - user's list [first, second] was refused",
])
def test_balanced_nested_arrays_and_quoted_brackets_still_map(detail):
    raw = f"[Claude API error: {detail} request_id={PRIVATE}]"
    shown = sanitize_text(raw)
    assert shown.startswith("The model provider Claude ")
    assert "refused the hub's credentials (HTTP 401)" in shown
    assert PRIVATE not in shown


def test_failed_known_secret_redactor_withholds_multiline_marker():
    def broken(_text):
        raise RuntimeError("private redactor failure")

    install_known_secret_redactor(broken)
    try:
        shown = sanitize_text(f"[Claude API error: HTTP 401\nrequest_id={PRIVATE}]")
    finally:
        install_known_secret_redactor(None)
    assert shown == "A reply could not be checked before sending, so it was withheld."
    assert PRIVATE not in shown


@pytest.mark.parametrize("before", [True, False])
def test_cancellation_metadata_does_not_hide_a_provider_error(before):
    from agents.core.code_interruptions import MARKER

    marker = "[Claude API error: HTTP 401 request_id=req_private_marker]"
    raw = MARKER + "\n" + marker if before else marker + "\n" + MARKER
    shown = sanitize_text(raw)
    assert shown.startswith("The model provider Claude ")
    assert PRIVATE not in shown and MARKER not in shown
