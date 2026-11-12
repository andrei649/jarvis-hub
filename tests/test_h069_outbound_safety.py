"""H069 — the last gate before text leaves on a chat transport.

What the owner (and an attacker) can observe on a channel:

* a credential that reached a reply by any path — a command reply, a job's output, a card,
  an in-place edit — arrives masked, whether it is a known vendor format or simply the
  value of a credential the hub holds;
* characters that crash a transport (NUL, lone surrogates) and the interruption marker
  never reach it;
* an agent that replies exactly ``[SILENT]`` sends nothing, on a direct send, a streamed
  reply and a scheduled job alike;
* a turn whose model produced nothing, or that raised, is answered with an actionable
  notice instead of disappearing.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402

from agents.core.channels import outbound_safety  # noqa: E402
from agents.core.channels.base import ChannelAdapter  # noqa: E402
from agents.core.channels.ephemeral import EphemeralReply  # noqa: E402
from agents.core.channels.render import chunk, render_outbound  # noqa: E402
from agents.core.channels.session import DeliveryRouter, SessionSource  # noqa: E402
from agents.core.channels.telegram import TelegramChannel, TelegramDraft  # noqa: E402
from agents.core.code_interruptions import MARKER  # noqa: E402
from agents.core.turn_notices import FootedReply  # noqa: E402

ANTHROPIC = "sk-ant-" + "A1b2C3d4" * 4
BOT_TOKEN = "123456789:" + "AbCdEfGhIjKlMnOpQrStUvWxYz012345678"


@pytest.fixture(autouse=True)
def _no_known_redactor():
    outbound_safety.install_known_secret_redactor(None)
    yield
    outbound_safety.install_known_secret_redactor(None)


# ── the sanitizer ────────────────────────────────────────────────────────────────

def test_vendor_key_formats_are_masked():
    out = outbound_safety.sanitize_text(f"use {ANTHROPIC} and {BOT_TOKEN} now")
    assert ANTHROPIC not in out and BOT_TOKEN not in out
    assert "[REDACTED:anthropic_key]" in out and "[REDACTED:telegram_bot_token]" in out


def test_a_credential_value_from_the_environment_is_masked_whatever_its_shape(monkeypatch):
    # No vendor pattern knows this shape; the value is masked because the hub holds it.
    monkeypatch.setenv("ACME_API_KEY", "plainlowercasevalue-x")
    out = outbound_safety.sanitize_text("the key is plainlowercasevalue-x, keep it")
    assert "plainlowercasevalue-x" not in out
    assert "[REDACTED:ACME_API_KEY]" in out


def test_short_and_non_credential_values_are_not_masked(monkeypatch):
    monkeypatch.setenv("ACME_TOKEN", "true")                       # too short to be a secret
    monkeypatch.setenv("JARVIS_BUDGET_MAX_TOKENS", "123456789012")  # a budget, not a token
    monkeypatch.setenv("ACME_HOME", "notasecretvalue12345")         # not credential-named
    text = "true 123456789012 notasecretvalue12345"
    assert outbound_safety.sanitize_text(text) == text


def test_ids_and_hashes_a_status_reply_shows_survive():
    text = ("session 550e8400-e29b-41d4-a716-446655440000 at "
            "3f2a9c1b7e4d6a8f0b2c4e6a8d0f1b3c5e7a9d2f, job ch_telegram_sender_0123456789abcdef0123")
    assert outbound_safety.sanitize_text(text) == text


def test_the_installed_known_secret_redactor_runs():
    outbound_safety.install_known_secret_redactor(lambda t: t.replace("vaultvalue", "[REDACTED:vault]"))
    assert outbound_safety.sanitize_text("a vaultvalue b") == "a [REDACTED:vault] b"


def test_a_failing_redactor_still_masks_key_formats():
    def boom(_text):
        raise RuntimeError("store locked")

    outbound_safety.install_known_secret_redactor(boom)
    out = outbound_safety.sanitize_text(f"x {ANTHROPIC}")
    assert ANTHROPIC not in out


def test_crash_characters_and_the_interruption_marker_are_removed():
    text = f"line one\x00\r\nline two \ud800 tail\x07 ok\U000E0041\n{MARKER}\nend"
    out = outbound_safety.sanitize_text(text)
    for bad in ("\x00", "\r", "\ud800", "\x07", "\U000E0041", MARKER):
        assert bad not in out
    assert out.startswith("line one\nline two ") and out.endswith("\nend")
    out.encode("utf-8")   # a lone surrogate would raise here, and on the transport


def test_sanitize_is_idempotent_and_keeps_an_unchanged_message_identical():
    text = "hello there"
    assert outbound_safety.sanitize_outbound(text) is text
    once = outbound_safety.sanitize_text(f"{ANTHROPIC}\x00")
    assert outbound_safety.sanitize_text(once) == once


def test_typed_replies_keep_their_type_and_attributes():
    eph = EphemeralReply(f"note {ANTHROPIC}", ttl_seconds=30)
    clean = outbound_safety.sanitize_outbound(eph)
    assert type(clean) is EphemeralReply and clean.ttl_seconds == 30 and ANTHROPIC not in clean

    footed = FootedReply(f"answer {ANTHROPIC}", ["ℹ note"])
    clean = outbound_safety.sanitize_outbound(footed)
    assert type(clean) is FootedReply
    assert ANTHROPIC not in clean and ANTHROPIC not in clean.spoken


def test_silence_token():
    assert outbound_safety.is_silence("[SILENT]")
    assert outbound_safety.is_silence("  [silent]\n")
    assert not outbound_safety.is_silence("[SILENT] but here is more")
    assert not outbound_safety.is_silence("")
    assert outbound_safety.may_become_silence("[SIL")
    assert outbound_safety.may_become_silence(" [SILENT] ")
    assert not outbound_safety.may_become_silence("[SILENT] no")
    assert not outbound_safety.may_become_silence("Hello")


# ── every transport seam runs it ─────────────────────────────────────────────────

def test_every_adapter_send_is_wrapped():
    import agents.core.channels.discord  # noqa: F401
    import agents.core.channels.email  # noqa: F401
    import agents.core.channels.ntfy  # noqa: F401
    import agents.core.channels.slack  # noqa: F401
    import agents.core.channels.sms  # noqa: F401
    import agents.core.channels.voice  # noqa: F401
    import agents.core.channels.web  # noqa: F401
    import agents.core.channels.webhook_channels  # noqa: F401

    def walk(cls):
        for sub in cls.__subclasses__():
            yield sub
            yield from walk(sub)

    adapters = [c for c in walk(ChannelAdapter) if c.__module__.startswith("agents.core.channels")]
    assert len(adapters) >= 8
    for cls in adapters:
        assert getattr(cls.send, "__outbound_safe__", False), cls


@pytest.mark.asyncio
async def test_a_direct_adapter_send_is_sanitized_and_silence_is_not_sent():
    sent = []

    class _Probe(ChannelAdapter):
        async def start(self):
            pass

        async def stop(self):
            pass

        async def send(self, message, **kwargs):
            sent.append(message)
            return True

    probe = _Probe("probe")
    assert await probe.send(f"k={ANTHROPIC}") is True
    assert await probe.send("[SILENT]") is True
    assert sent == ["k=[REDACTED:anthropic_key]"]


def test_chunked_transports_never_split_a_secret_past_the_gate():
    text = ("x" * 90) + " " + ANTHROPIC + " tail"
    pieces = chunk(text, 64)
    assert all(ANTHROPIC[:20] not in p for p in pieces)
    from agents.core.channels.discord import DiscordChannel
    assert all(ANTHROPIC not in p for p in render_outbound(text, DiscordChannel.descriptor))


class _Resp:
    status_code = 200
    is_success = True

    def __init__(self, message_id=0):
        self._id = message_id

    def raise_for_status(self):
        pass

    def json(self):
        return {"ok": True, "result": {"message_id": self._id or 1}}


class _Client:
    is_closed = False

    def __init__(self):
        self.posts = []
        self.next_id = 10

    async def post(self, url, json=None, data=None, **kwargs):
        self.posts.append((url.rsplit("/", 1)[-1], dict(json or data or {})))
        self.next_id += 1
        return _Resp(self.next_id)


def _telegram():
    channel = TelegramChannel("tok")
    channel.client = _Client()
    return channel


@pytest.mark.asyncio
async def test_telegram_cards_and_raw_api_texts_pass_the_gate():
    channel = _telegram()
    assert await channel.send_card(5, {"text": f"approve {ANTHROPIC}?", "reply_markup": {}})
    await channel.send_scheduled_text(f"job: {BOT_TOKEN}", chat_id=5)
    texts = [body.get("text", "") for _m, body in channel.client.posts]
    assert texts and all(ANTHROPIC not in t and BOT_TOKEN not in t for t in texts)


@pytest.mark.asyncio
async def test_telegram_stream_masks_frames_and_holds_a_possible_silence():
    channel = _telegram()
    draft = TelegramDraft(channel, 5, interval=0.0)
    await draft.push("[SIL")
    await draft.push("ENT]")
    assert not draft.started and channel.client.posts == []

    draft = TelegramDraft(channel, 5, interval=0.0)
    await draft.push("the key ")
    await draft.push(ANTHROPIC)
    await draft.push(" ok")
    assert await draft.finish()
    texts = [body.get("text", "") for _m, body in channel.client.posts]
    assert texts and all(ANTHROPIC not in t for t in texts)


# ── silence and visible failure on the channel turn ──────────────────────────────

def test_the_router_drops_silence():
    decision = DeliveryRouter().resolve(SessionSource(channel="telegram", sender="1"), text="[SILENT]")
    assert decision.send is False and decision.reason == "agent-silence"


@pytest.mark.asyncio
async def test_the_manager_sends_nothing_for_silence():
    from agents.core.channels.manager import ChannelManager

    sent = []

    class _Fake:
        async def send(self, message, **kwargs):
            sent.append(message)
            return True

    manager = ChannelManager()
    manager.channels["telegram"] = _Fake()
    assert await manager.send("telegram", "[SILENT]", chat_id=1) is True
    assert sent == []


@pytest.mark.asyncio
async def test_job_delivery_leaves_silence_to_the_agent_gate():
    """An agent job's ``[SILENT]`` is suppressed before delivery (``jobs_gates`` →
    ``Suppressed: model_silent``, covered in tests/test_job_gates.py). ``_send`` itself
    keeps the no-agent contract: a script whose output is literally ``[SILENT]`` is
    delivered as written (tests/test_job_gates.py::test_no_agent_silent_token_is_literal_output)."""
    from types import SimpleNamespace

    from agents.core.autonomy.jobs import JobRunner
    from agents.core.autonomy.jobs_gates import is_silent_response

    assert is_silent_response("[SILENT]")

    sent = []

    class _Fake:
        async def send(self, message, **kwargs):
            sent.append(message)
            return True

    runner = JobRunner.__new__(JobRunner)
    runner._orch = SimpleNamespace(channels={"ntfy": _Fake()})
    assert (await runner._send("[SILENT]", "ntfy")) == "delivered to ntfy"
    assert sent == ["[SILENT]"]


@pytest.mark.asyncio
async def test_channel_turn_answers_an_empty_model_reply_and_keeps_silence_bare():
    from contextlib import asynccontextmanager

    from agents.core.orchestrator import Orchestrator

    class _Orch:
        session_id = "s"

        @asynccontextmanager
        async def turn_lease(self):
            yield True

        async def handle_input(self, text, channel):
            return self.reply

        _with_channel_notices = staticmethod(Orchestrator._with_channel_notices)

    orch = _Orch()
    orch.reply = ""
    assert await Orchestrator._channel_turn(orch, "hi", "ntfy", observe_only=False) == \
        outbound_safety.EMPTY_TURN_REPLY
    orch.reply = None
    assert await Orchestrator._channel_turn(orch, "hi", "ntfy", observe_only=False) == \
        outbound_safety.EMPTY_TURN_REPLY
    orch.reply = " [SILENT] "
    assert await Orchestrator._channel_turn(orch, "hi", "ntfy", observe_only=False) == "[SILENT]"


@pytest.mark.asyncio
async def test_a_failed_channel_turn_is_answered_and_a_silent_one_sends_nothing():
    sys.path.insert(0, os.path.dirname(__file__))
    from test_channel_handler_session_wiring import _bare_orchestrator

    orch, cap = _bare_orchestrator()

    async def boom(text, channel="voice", agent_override=None):
        raise RuntimeError("provider exploded with sk-ant-secret-body")

    orch.handle_input = boom
    reply = await orch.channel_handler("salut", channel="telegram", chat_id="123", sender="42")
    assert reply == outbound_safety.FAILED_TURN_REPLY
    assert [m for _c, m, _k in cap["sent"]] == [outbound_safety.FAILED_TURN_REPLY]

    orch, cap = _bare_orchestrator(response="[SILENT]")
    reply = await orch.channel_handler("salut", channel="telegram", chat_id="123", sender="42")
    assert reply == "" and cap["sent"] == []


@pytest.mark.parametrize("raw, expect", [
    ("[Claude API error: Error code: 401 - {'type': 'error', 'error': {'type': 'authentication_error',"
     " 'message': 'invalid x-api-key'}, 'request_id': 'req_011CXabc'}]", "refused the hub's credentials (HTTP 401)"),
    ("[Claude API stream error: Error code: 529 - {'type': 'overloaded_error'}]", "had a server error (HTTP 529)"),
    ("[Claude API error: Error code: 429 - rate]", "is rate limiting requests (HTTP 429)"),
    ("[Gemini error: provider request failed]", "could not answer"),
    ("[OpenRouter error]", "could not answer"),
])
def test_a_raw_provider_error_becomes_one_safe_sentence(raw, expect):
    out = outbound_safety.sanitize_text(raw)
    assert expect in out and out.startswith("The model provider ")
    for leak in ("request_id", "req_011", "x-api-key", "{", "authentication_error"):
        assert leak not in out
    assert outbound_safety.sanitize_text(out) == out


def test_prose_that_mentions_an_error_is_not_rewritten():
    for text in ("The [Claude API error] you saw yesterday is fixed.",
                 "[note] the error was mine", "Fixed the parser error]"):
        assert outbound_safety.sanitize_text(text) == text


# ── security review (2026-11-12): the reviewer's repros, kept ─────────────────────

GHP = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"   # a GitHub token
HELD = "Zq8vN3kLm2Pw7Xr4Ty6Ub1Hc9Js5Dg0F"            # a held credential, no vendor shape


def test_r1_a_fake_provider_marker_cannot_carry_a_secret_out(monkeypatch):
    out = outbound_safety.sanitize_text(f"[{GHP} error]")
    assert GHP not in out
    held = "abcdefghijklmnop-qrstuvwxyz0123456"
    monkeypatch.setenv("JARVIS_ADMIN_TOKEN", held)
    assert held not in outbound_safety.sanitize_text(f"x {held} y")
    assert held not in outbound_safety.sanitize_text(f"[{held} API error: 401]")
    # only a known provider is named; anything else is "the model provider"
    assert outbound_safety.sanitize_text("[Totally Real error: HTTP 500]").startswith("The model provider had")


class _StreamResp:
    status_code = 200
    is_success = True

    def __init__(self, i):
        self._i = i

    def raise_for_status(self):
        pass

    def json(self):
        return {"ok": True, "result": {"message_id": self._i}}


class _StreamClient:
    is_closed = False

    def __init__(self):
        self.posts = []

    async def post(self, url, json=None, data=None, **kwargs):
        self.posts.append(dict(json or data or {}))
        return _StreamResp(len(self.posts) + 10)


@pytest.mark.asyncio
async def test_r2_no_streamed_frame_shows_a_long_prefix_of_a_held_credential(monkeypatch):
    monkeypatch.setenv("ACME_API_KEY", HELD)
    channel = TelegramChannel("tok")
    channel.client = _StreamClient()
    draft = TelegramDraft(channel, 5, interval=0.0)
    await draft.push("Here it is: ")
    for i in range(0, len(HELD), 4):          # the model streams the value in pieces
        await draft.push(HELD[i:i + 4])
    await draft.push(" done")
    await draft.finish()
    frames = [b.get("text", "") for b in channel.client.posts]
    assert frames and not any(HELD[:24] in f for f in frames), frames
    assert not any(HELD[:4] in f for f in frames), frames


@pytest.mark.asyncio
async def test_r2_a_vendor_key_still_arriving_is_not_shown_in_part():
    channel = TelegramChannel("tok")
    channel.client = _StreamClient()
    draft = TelegramDraft(channel, 5, interval=0.0)
    await draft.push("Use this: ")
    for i in range(0, len(GHP), 5):
        await draft.push(GHP[i:i + 5])
        frames = [b.get("text", "") for b in channel.client.posts]
        assert not any("ghp_" in f for f in frames), frames
    await draft.push(" then go")
    assert await draft.finish()
    assert all(GHP not in b.get("text", "") for b in channel.client.posts)


def test_stream_safe_prefix_shows_whole_words_only(monkeypatch):
    assert outbound_safety.stream_safe_prefix("Hello wor") == "Hello"
    assert outbound_safety.stream_safe_prefix("Hello world ") == "Hello world"
    assert outbound_safety.stream_safe_prefix("Hel") == ""
    monkeypatch.setenv("ACME_API_KEY", "x" * 20)          # hold back the last 20 characters
    assert outbound_safety.stream_safe_prefix("one two three four five six ") == "one two"


@pytest.mark.asyncio
async def test_r3_telegram_button_labels_are_masked():
    channel = TelegramChannel("tok")
    channel.client = _StreamClient()
    markup = {"inline_keyboard": [[{"text": f"Use {GHP}", "callback_data": "h067:t:1:c0"}]]}
    await channel._post(channel.api_base + "/sendMessage",
                        json={"chat_id": 5, "text": "Pick one", "reply_markup": markup})
    assert GHP not in repr(channel.client.posts)
    assert channel.client.posts[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "h067:t:1:c0"


def test_r3_slack_button_labels_are_masked():
    from agents.core.channels.slack import SlackChannel

    markup = {"inline_keyboard": [[{"text": f"Use {GHP}", "callback_data": "h067:AbCdEfGhIjKlMnOp:1:c0"}]]}
    blocks = SlackChannel._pending_blocks("Pick one", markup)
    assert blocks is not None and GHP[:40] not in repr(blocks)


def test_r3_card_choices_are_masked_where_the_card_is_built():
    from agents.core.channels.pending_input_cards import NativePromptCards

    card = type("Card", (), {"token": "t", "revision": 1})()
    button = NativePromptCards._button(card, f"Use {GHP}", "c0")
    assert GHP not in button["text"] and button["callback_data"] == "h067:t:1:c0"
    assert outbound_safety.sanitize_label("​") == "…"


@pytest.mark.asyncio
async def test_r4_silence_does_not_swallow_an_owner_notice():
    from contextlib import asynccontextmanager

    from agents.core.commands import Principal
    from agents.core.orchestrator import Orchestrator, bind_turn_principal, reset_turn_principal
    from agents.core.turn_notices import record_turn_notice

    warning = "This turn's text was sent to a cloud provider (data_handling)."

    class _Orch:
        session_id = "s"
        notice = True

        @asynccontextmanager
        async def turn_lease(self):
            yield True

        async def handle_input(self, text, channel):
            if self.notice:
                record_turn_notice("data_handling:cloud", warning)
            return "[SILENT]"

        _with_channel_notices = staticmethod(Orchestrator._with_channel_notices)

    orch = _Orch()
    token = bind_turn_principal(Principal(channel="telegram", sender="1", admin=True, chat="1"))
    try:
        reply = await Orchestrator._channel_turn(orch, "summarise this page", "telegram", observe_only=False)
        assert warning in str(reply) and "[SILENT]" not in str(reply)
        orch.notice = False   # nothing to say: the silence stands
        assert await Orchestrator._channel_turn(orch, "hi", "telegram", observe_only=False) == "[SILENT]"
    finally:
        reset_turn_principal(token)


def test_r5_a_format_character_cannot_split_a_held_value(monkeypatch):
    monkeypatch.setenv("ACME_API_KEY", HELD)
    for joiner in ("​", "⁠", "­", "﻿", "‍"):
        split = HELD[:16] + joiner + HELD[16:]
        out = outbound_safety.sanitize_text(f"key: {split}")
        assert HELD not in out.replace(joiner, ""), (joiner, out)
    assert outbound_safety.sanitize_text("👩‍💻 at work") == "👩‍💻 at work"   # an emoji keeps its joiner


def test_r6_paths_urls_and_settings_named_like_credentials_are_not_masked(monkeypatch):
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY_PATH", "/home/owner/keys/app.pem")
    monkeypatch.setenv("ALIBABA_TOKEN_PLAN_BASE_URL", "https://dashscope-intl.aliyuncs.com/v1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "http.proxyAuthMethod")
    monkeypatch.setenv("JARVIS_KEY_DIR", "/var/lib/nerva/keys")
    text = ("The app key is at /home/owner/keys/app.pem; base https://dashscope-intl.aliyuncs.com/v1; "
            "http.proxyAuthMethod in /var/lib/nerva/keys")
    assert outbound_safety.sanitize_text(text) == text


@pytest.mark.parametrize("code", [
    'password = input("Password: ")', "password=self.password_field", "pwd = getpass.getpass()",
    "password: str", "password = os.environ.get('X')",
])
def test_m2_code_that_mentions_a_password_is_not_mangled(code):
    assert outbound_safety.sanitize_text(code) == code


@pytest.mark.parametrize("secret", ["password: hunter22!", 'pwd="abcd"', "PASSWORD=Tr0ub4dor&3"])
def test_m2_a_password_literal_is_still_masked(secret):
    assert "[REDACTED:password_assignment]" in outbound_safety.sanitize_text(secret)


def test_m4_ntfy_title_is_gated():
    from agents.core.channels.ntfy import title_header

    assert GHP not in title_header(f"CI {GHP}") and title_header(f"CI {GHP}").startswith("CI ")


@pytest.mark.asyncio
async def test_m4_email_subject_is_gated_and_one_line():
    from agents.core.channels.email import EmailChannel

    sent = []
    channel = EmailChannel(smtp_config={"host": "smtp.example"})
    channel._smtp_send = lambda msg, to: sent.append(msg)
    assert await channel.send("body", to="me@example.org", subject=f"key {GHP}\nBcc: x@y")
    subject = sent[0]["Subject"]
    assert GHP not in subject and "\n" not in subject


@pytest.mark.asyncio
async def test_m4_telegram_attachment_names_and_captions_are_gated():
    channel = TelegramChannel("tok")
    seen = []

    class _Client:
        is_closed = False

        async def post(self, url, **kwargs):
            seen.append(kwargs)
            return _StreamResp(1)

    channel.client = _Client()
    await channel._post(channel.api_base + "/sendDocument", data={"chat_id": "5", "caption": f"see {GHP}"},
                        files={"document": (f"{GHP}.txt", b"bytes stay as they are", "text/plain")})
    assert GHP not in repr(seen[0]["data"]) and GHP not in seen[0]["files"]["document"][0]
    assert seen[0]["files"]["document"][1] == b"bytes stay as they are"
