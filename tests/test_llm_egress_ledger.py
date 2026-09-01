"""DRA-23 — model-backend traffic lands in the egress ledger.

The H23.16 ledger records every *plugin* HTTP request, and the HUD network panel plus
the support bundle present ``external_egress_total`` / ``clean`` as proof that this
install is local-first. Every LLM backend dialled its own ``httpx.AsyncClient``, so a
turn served by Anthropic or Gemini left the machine without touching the ledger: the
panel could read "0 external, local-only" while a cloud model answered every question.

Requests here go through ``httpx.MockTransport`` — no socket is opened. The recording
hook runs in ``AsyncClient.send``, before transport dispatch, so it still fires.
"""

import httpx
import pytest

from agents.core.observability.egress_monitor import EGRESS_MONITOR


@pytest.fixture(autouse=True)
def _clean_monitor():
    EGRESS_MONITOR.reset()
    yield
    EGRESS_MONITOR.reset()


def _pin(backend, payload: dict) -> None:
    """Answer every request from *backend*'s client locally, with no network.

    ``_mounts`` is cleared too: when HTTPS_PROXY is set in the environment httpx
    resolves a proxy mount *before* the default transport, and a real request would
    escape the mock.
    """
    backend.client._mounts = {}
    backend.client._transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=payload)
    )


_CLAUDE_BODY = {"content": [{"type": "text", "text": "hello"}]}
_OPENAI_BODY = {"choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}]}


async def _claude_turn():
    from agents.core.llm.anthropic import ClaudeBackend
    backend = ClaudeBackend(api_key="k")
    _pin(backend, _CLAUDE_BODY)
    await backend.generate(model="claude-opus-5", prompt="hi")
    return backend


@pytest.mark.asyncio
async def test_cloud_model_call_lands_in_the_ledger():
    await _claude_turn()
    snap = EGRESS_MONITOR.snapshot()
    assert "llm:anthropic" in snap["plugins"], (
        "a cloud model call left the machine and the ledger never saw it"
    )
    row = snap["plugins"]["llm:anthropic"]
    assert row["external"] == 1
    assert row["last_host"] == "api.anthropic.com"


@pytest.mark.asyncio
async def test_external_egress_total_counts_model_traffic():
    await _claude_turn()
    snap = EGRESS_MONITOR.snapshot()
    assert snap["external_egress_total"] >= 1
    assert snap["model_egress_total"] == 1


@pytest.mark.asyncio
async def test_local_backend_is_recorded_but_not_external():
    from agents.core.llm.base import LMStudioBackend
    backend = LMStudioBackend("http://localhost:1234")
    _pin(backend, _OPENAI_BODY)
    await backend.generate(model="local", prompt="hi")

    snap = EGRESS_MONITOR.snapshot()
    row = snap["plugins"]["llm:lm-studio"]
    assert row["allowed"] == 1
    assert row["external"] == 0, "loopback must never count as egress"
    assert snap["external_egress_total"] == 0
    assert snap["model_egress_total"] == 0


@pytest.mark.asyncio
async def test_model_rows_do_not_fake_a_plugin_violation():
    await _claude_turn()
    snap = EGRESS_MONITOR.snapshot()
    # `llm:` rows are not plugins and have no manifest — they must not be classified
    # against BUILTIN_PLUGINS, or an honest cloud call reads as a kernel breach.
    assert snap["local_only_violations"] == []
    assert snap["clean"] is True


@pytest.mark.asyncio
async def test_support_bundle_reports_model_egress():
    from agents.core import support_bundle
    await _claude_turn()
    egress = support_bundle._egress()
    assert "model_egress_total" in egress, (
        "the support bundle asserts local-first purity from plugin traffic alone"
    )
    assert egress["model_egress_total"] == 1


@pytest.mark.asyncio
async def test_gemini_cache_control_traffic_folds_under_the_gemini_row():
    """The cache API is the same host and credential — not a separate provider."""
    from agents.core.llm.gemini import GeminiBackend
    backend = GeminiBackend(api_key="k")
    _pin(backend, {"candidates": [{"content": {"parts": [{"text": "hi"}]}}]})
    await backend.generate(model="gemini-2.5-flash", prompt="hi")

    snap = EGRESS_MONITOR.snapshot()
    assert snap["plugins"]["llm:gemini"]["external"] == 1
    assert snap["plugins"]["llm:gemini"]["last_host"] == "generativelanguage.googleapis.com"
