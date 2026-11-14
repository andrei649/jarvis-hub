"""Complete provider errors never expose their body through chat transports."""

import pytest

from agents.core.channels import outbound_safety
from agents.core.channels.telegram import TelegramDraft
from tests.test_h069_outbound_safety import _telegram
from tests.test_h069_protocol_outbound import (  # noqa: F401
    _auth,
    _chat,
    _chat_text,
    _key,
    client,
    enabled,
    hub,
    settings,
    store,
)


@pytest.fixture(params=["multiline", "oversized", "cancellation_prefix", "cancellation_suffix"])
def provider_error(request, monkeypatch):
    monkeypatch.setattr(outbound_safety, "_known_redactor", None)
    body = "request_id=private-request-7931\npolicy_body=private-policy-4812"
    if request.param == "oversized":
        body = "padding " * 700 + body
    raw = f"[Claude API error: Error code: 401 - {body}]"
    if request.param.startswith("cancellation_"):
        from agents.core.code_interruptions import MARKER

        return MARKER + "\n" + raw if request.param.endswith("prefix") else raw + "\n" + MARKER
    return raw


def _assert_safe(text):
    assert "private-request-7931" not in text
    assert "private-policy-4812" not in text
    assert "padding" not in text
    assert text.startswith("The model provider ")


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_telegram_final_provider_envelope_is_mapped(provider_error, stream):
    channel = _telegram()
    if stream:
        draft = TelegramDraft(channel, 5, interval=0.0)
        for at in range(0, len(provider_error), 11):
            await draft.push(provider_error[at:at + 11])
        assert channel.client.posts == []
        assert await draft.finish()
    else:
        assert await channel.send(provider_error, chat_id=5, plain=True)
    assert channel.client.posts
    for _, body in channel.client.posts:
        _assert_safe(body["text"])


@pytest.mark.parametrize("stream", [False, True])
def test_openai_route_provider_envelope_is_mapped(
        enabled, store, hub, client, provider_error, stream):
    key, _ = _key(store, owner=True)
    hub.reply = provider_error
    reply = client.post("/v1/chat/completions", json=_chat("user input", stream=stream),
                        headers=_auth(key))
    assert reply.status_code == 200
    shown = _chat_text(reply.text) if stream else reply.json()["choices"][0]["message"]["content"]
    _assert_safe(shown)
    assert "private-request-7931" not in reply.text
    assert "private-policy-4812" not in reply.text
