"""Hermes absorption 4a — outbound text a channel can actually display.

Telegram was sent the model's Markdown verbatim: an odd `*`, an unclosed fence or a reply
over 4,096 characters was an HTTP 400, `send()` returned False and the owner saw nothing.
Now the channel declares what it can show, the reply is chunked on the source (never inside
a code block), each chunk is rendered with only balanced markers turned into markup, and a
chunk Telegram still rejects is resent as plain text — the words always arrive.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402

from agents.core.channels.base import ChannelAdapter  # noqa: E402
from agents.core.channels.descriptor import (  # noqa: E402
    DIALECT_PLAIN,
    DIALECT_TELEGRAM_HTML,
    ChannelDescriptor,
)
from agents.core.channels.render import (  # noqa: E402
    chunk,
    render,
    render_outbound,
    to_plain,
    to_telegram_html,
)
from agents.core.channels.telegram import TELEGRAM_MAX_MESSAGE_LENGTH, TelegramChannel  # noqa: E402

# ── the descriptor ───────────────────────────────────────────────────────────

def test_descriptor_defaults_are_the_honest_minimum():
    base = ChannelAdapter.descriptor
    assert base == ChannelDescriptor()
    assert base.dialect == DIALECT_PLAIN and base.max_message_length is None
    assert not base.supports_edit and not base.supports_media and not base.supports_threads
    telegram = TelegramChannel.descriptor
    assert telegram.dialect == DIALECT_TELEGRAM_HTML
    assert telegram.max_message_length == TELEGRAM_MAX_MESSAGE_LENGTH == 4096
    assert telegram.supports_edit and telegram.supports_media and telegram.supports_threads


def test_descriptor_refuses_nonsense():
    with pytest.raises(ValueError):
        ChannelDescriptor(dialect="mrkdwn")
    with pytest.raises(ValueError):
        ChannelDescriptor(max_message_length=8)
    with pytest.raises(ValueError):
        ChannelDescriptor(max_message_length=True)
    with pytest.raises(ValueError):
        render("x", "mrkdwn")


# ── rendering ────────────────────────────────────────────────────────────────

def test_balanced_markers_become_markup_and_text_is_escaped():
    assert to_telegram_html("**bold** and *it* and `x<y` & done") == (
        "<b>bold</b> and <i>it</i> and <code>x&lt;y</code> &amp; done"
    )
    assert to_telegram_html("__also bold__ and _also it_") == "<b>also bold</b> and <i>also it</i>"
    assert to_telegram_html("# Title\nbody") == "<b>Title</b>\nbody"
    assert to_telegram_html("[Nerva](https://nerva.example/x?a=1)") == (
        '<a href="https://nerva.example/x?a=1">Nerva</a>'
    )


def test_unbalanced_or_inline_markers_stay_literal():
    assert to_telegram_html("3 * 4 = 12 and 2*3*4") == "3 * 4 = 12 and 2*3*4"
    assert to_telegram_html("**unclosed bold") == "**unclosed bold"
    assert to_telegram_html("my_var_name and a_b") == "my_var_name and a_b"
    assert to_telegram_html("[x](javascript:alert(1))") == "[x](javascript:alert(1))"
    assert to_telegram_html("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"


def test_code_blocks_are_preformatted_and_never_reformatted():
    assert to_telegram_html("```py\nx < 1 and **not bold**\n```") == (
        "<pre>x &lt; 1 and **not bold**</pre>"
    )
    assert to_telegram_html("before\n```\ncode\n```\nafter *it*") == (
        "before\n<pre>code</pre>\nafter <i>it</i>"
    )
    # An unclosed fence still renders — as a code block to the end, not as an error.
    assert to_telegram_html("```\nopen") == "<pre>open</pre>"


def test_plain_strips_markers_and_keeps_urls():
    assert to_plain("# Title\n**b** and `c` and [t](https://u.example) and *i*") == (
        "Title\nb and c and t (https://u.example) and i"
    )
    assert to_plain("```\nkeep **this**\n```") == "keep **this**"
    assert render("**b**", DIALECT_PLAIN) == "b"


# ── chunking ─────────────────────────────────────────────────────────────────

def test_short_text_is_one_chunk_and_no_cap_means_no_split():
    assert chunk("hello", 4096) == ["hello"]
    assert chunk("x" * 10_000, None) == ["x" * 10_000]


def test_chunks_prefer_paragraphs_then_lines_and_keep_order():
    text = "\n\n".join(f"paragraph {i} " + "w" * 30 for i in range(20))
    pieces = chunk(text, 120)
    assert len(pieces) > 1
    assert all(len(p) <= 120 for p in pieces)
    assert all(p.startswith("paragraph") for p in pieces)  # never split inside a paragraph
    assert [p.split()[1] for p in pieces if True] == sorted(
        (p.split()[1] for p in pieces), key=int,
    )
    rejoined = "\n\n".join(pieces)
    assert rejoined.replace("\n", " ").split() == text.replace("\n", " ").split()


def test_a_fenced_block_is_never_split_open():
    block = "\n".join(f"line {i:03d}" for i in range(200))
    text = "intro\n```\n" + block + "\n```\noutro"
    pieces = chunk(text, 300)
    assert len(pieces) > 2
    for piece in pieces:
        assert piece.count("```") % 2 == 0, piece
        assert len(piece) <= 300
    rendered = [to_telegram_html(p) for p in pieces]
    assert rendered[0].startswith("intro\n<pre>")
    assert all(r.count("<pre>") == r.count("</pre>") for r in rendered)
    body = "\n".join(pieces).replace("```", "").split()
    assert body == text.replace("```", "").split()


def test_one_overlong_line_is_hard_split_as_the_last_resort():
    pieces = chunk("x" * 10_000, 4096)
    assert len(pieces) == 3 and all(len(p) <= 4096 for p in pieces)
    assert "".join(pieces) == "x" * 10_000


def test_render_outbound_renders_every_chunk_in_the_dialect():
    descriptor = ChannelDescriptor(dialect=DIALECT_TELEGRAM_HTML, max_message_length=64)
    out = render_outbound("**a**\n\n" + "b " * 60, descriptor)
    assert out[0] == "<b>a</b>" and len(out) >= 2
    assert all(len(o) <= 64 for o in out)


# ── Telegram delivery ────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, status: int) -> None:
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Client:
    def __init__(self, statuses) -> None:
        self.posts: list[tuple[str, dict]] = []
        self.statuses = list(statuses)

    async def post(self, url, json=None, **kwargs):
        self.posts.append((url, dict(json or {})))
        return _Resp(self.statuses.pop(0) if self.statuses else 200)

    async def aclose(self) -> None:
        pass


def _channel(statuses=()):
    channel = TelegramChannel("tok")
    channel.client = _Client(statuses)
    return channel


@pytest.mark.asyncio
async def test_a_long_reply_arrives_as_ordered_html_chunks():
    channel = _channel()
    text = "\n\n".join(f"Part {i}: " + "word " * 300 for i in range(6))
    assert await channel.send(text, chat_id=42) is True
    posts = channel.client.posts
    assert len(posts) >= 2
    for url, body in posts:
        assert url.endswith("/sendMessage")
        assert body["chat_id"] == 42 and body["parse_mode"] == "HTML"
        assert len(body["text"]) <= TELEGRAM_MAX_MESSAGE_LENGTH
    assert posts[0][1]["text"].startswith("Part 0:")
    assert posts[-1][1]["text"].rstrip().endswith("word")


@pytest.mark.asyncio
async def test_markup_telegram_rejects_is_resent_as_plain_text():
    channel = _channel([400, 200])
    assert await channel.send("**bold** and `code`", chat_id=7) is True
    posts = channel.client.posts
    assert len(posts) == 2
    assert posts[0][1] == {"chat_id": 7, "text": "<b>bold</b> and <code>code</code>", "parse_mode": "HTML"}
    assert posts[1][1] == {"chat_id": 7, "text": "bold and code"}


@pytest.mark.asyncio
async def test_other_failures_and_a_missing_chat_are_false():
    channel = _channel([500])
    assert await channel.send("hi", chat_id=7) is False
    assert len(channel.client.posts) == 1
    channel = _channel()
    assert await channel.send("hi") is False
    assert channel.client.posts == []
    # A failed chunk stops the sequence: nothing after it is sent out of order.
    channel = _channel([200, 500, 200])
    text = "\n\n".join("p " * 1500 for _ in range(3))
    assert await channel.send(text, chat_id=7) is False
    assert len(channel.client.posts) == 2


@pytest.mark.asyncio
async def test_decision_cards_are_sent_as_built():
    channel = _channel()
    card = {"text": "*Decide*", "parse_mode": "Markdown", "reply_markup": {"inline_keyboard": []}}
    assert await channel.send_card(9, card) is True
    assert channel.client.posts[0][1] == {"chat_id": 9, **card}
