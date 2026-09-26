"""A photo stops vanishing.

`TelegramChannel._poll_loop` read `msg["text"]` and did `if not text: continue`,
so a photo, a voice note — even a photo captioned "what is this?" — was dropped
with no reply and nothing the sender could learn. These pin the first half of
H108: recognise what arrived, bound it, say one honest line about it, and carry
the sender's own words into the turn.

Two properties matter more than the rest, and both have mutants behind them:
the kind is taken from the envelope Telegram used and never from the
sender-chosen `mime_type`/`file_name`, and nothing claims a file was read that
was not — `READABLE_KINDS` names only the kinds with a reading path (photos,
via `media_reader`), and a per-message failure still overrides it.

The reading path itself — the local-only gate, the bounded download, the fence —
is pinned in `test_inbound_media_read.py`.

Hermetic: no network, no Telegram client, a recording handler.
"""

from __future__ import annotations

import itertools

import pytest

from agents.core.channels.group_policy import GroupPolicy
from agents.core.channels.inbound_media import (
    DISPLAY,
    MAX_CAPTION_CHARS,
    MAX_DECLARED_BYTES,
    READABLE_KINDS,
    REASON_NO_HANDLE,
    REASON_NOT_READABLE,
    REASON_TOO_LARGE,
    RECOGNISED_KINDS,
    Attachment,
    classify,
    describe,
    display,
    turn_text,
)
from agents.core.channels.telegram import TelegramChannel


@pytest.fixture(autouse=True)
def _one_turn_per_message(monkeypatch):
    """These tests are about each message on its own; H117's batching has its own tests."""
    monkeypatch.setenv("JARVIS_INBOUND_BATCH_MS", "0")


BOT_ID = 999
BOT = "nerva_bot"
GROUP = -1001
_update_ids = itertools.count(1)


# ── what arrived ────────────────────────────────────────────────────────────


def test_a_text_only_message_is_not_an_attachment():
    assert classify({"text": "salut"}) is None
    assert classify({}) is None
    assert classify(None) is None
    assert classify("not a mapping") is None


def test_a_photo_uses_the_largest_variant_telegram_offered():
    att = classify({"photo": [
        {"file_id": "small", "file_size": 100},
        {"file_id": "big", "file_size": 90_000},
        {"file_id": "mid", "file_size": 9_000},
    ]})
    assert att.kind == "photo"
    assert att.file_id == "big"
    assert att.size == 90_000


def test_a_photo_variant_list_with_no_handle_is_named_not_dropped():
    att = classify({"photo": [{"file_size": 5}]})
    assert (att.kind, att.reason) == ("photo", REASON_NO_HANDLE)
    assert att.file_id == ""


def test_an_empty_photo_list_is_simply_nothing_attached():
    assert classify({"photo": []}) is None


@pytest.mark.parametrize("file_name,mime", [
    ("holiday.jpg", "image/jpeg"),
    ("photo.png", "image/png"),
    ("safe.txt", "text/plain"),
    ("../../etc/passwd", "image/jpeg"),
])
def test_the_kind_comes_from_the_envelope_never_from_sender_chosen_strings(file_name, mime):
    """A document named like an image is a document. This is the whole point."""
    att = classify({"document": {
        "file_id": "d", "file_size": 10, "file_name": file_name, "mime_type": mime,
    }})
    assert att.kind == "document"
    assert file_name not in describe(att)
    assert file_name not in str(att.to_dict())


def test_the_most_specific_envelope_wins_when_telegram_sends_several():
    # An animation also carries a document; a video note also a video.
    assert classify({
        "animation": {"file_id": "a"}, "document": {"file_id": "d"},
    }).kind == "animation"
    assert classify({
        "video_note": {"file_id": "vn"}, "video": {"file_id": "v"},
    }).kind == "video_note"


@pytest.mark.parametrize("kind", ["location", "contact"])
def test_a_non_file_item_is_recognised_without_inventing_a_handle(kind):
    att = classify({kind: {"latitude": 44.4, "longitude": 26.1, "phone_number": "x"}})
    assert att.kind == kind
    assert att.file_id == ""
    assert att.reason == REASON_NOT_READABLE


# ── bounds ──────────────────────────────────────────────────────────────────


def test_a_file_past_the_download_ceiling_is_refused_by_name():
    att = classify({"document": {"file_id": "d", "file_size": MAX_DECLARED_BYTES + 1}})
    assert att.reason == REASON_TOO_LARGE
    assert "20 MB" in describe(att)


def test_a_file_exactly_at_the_ceiling_is_not_refused_for_size():
    att = classify({"document": {"file_id": "d", "file_size": MAX_DECLARED_BYTES}})
    assert att.reason != REASON_TOO_LARGE


@pytest.mark.parametrize("raw", [None, "1200", True, False, -5, {"n": 1}])
def test_an_absent_or_malformed_declared_size_reads_as_zero(raw):
    att = classify({"voice": {"file_id": "v", "file_size": raw}})
    assert att.size == 0


def test_a_caption_is_bounded():
    att = classify({"photo": [{"file_id": "p"}], "caption": "x" * (MAX_CAPTION_CHARS * 3)})
    assert len(att.caption) == MAX_CAPTION_CHARS


def test_control_characters_in_a_caption_cannot_forge_a_log_line():
    att = classify({"photo": [{"file_id": "p"}],
                    "caption": "hi\x00\x1b[31m\rFAKE LOG LINE\x07 ok\nreal newline"})
    assert "\x00" not in att.caption
    assert "\x1b" not in att.caption
    assert "\r" not in att.caption
    assert "\x07" not in att.caption
    assert "\nreal newline" in att.caption, "a real newline is content, not a control char"


# ── the handle never leaves the process ─────────────────────────────────────


def test_the_loggable_view_never_carries_the_file_handle():
    att = classify({"photo": [{"file_id": "SECRET-HANDLE", "file_size": 9}], "caption": "hi"})
    payload = att.to_dict()
    assert "SECRET-HANDLE" not in str(payload)
    assert "file_id" not in payload
    assert payload["has_caption"] is True
    assert "hi" not in str(payload), "the caption is sender text, not log material"


def test_the_sentence_sent_back_never_carries_the_handle_or_the_caption():
    att = classify({"voice": {"file_id": "SECRET-HANDLE"}, "caption": "my secret note"})
    line = describe(att)
    assert "SECRET-HANDLE" not in line
    assert "my secret note" not in line


# ── nothing claims the file was read ────────────────────────────────────────


def test_only_kinds_with_a_reading_path_report_readable():
    """Photos and voice notes read; nothing else does, and nothing else may claim to.

    This is the honesty invariant, not a snapshot of today's set: a kind belongs
    in READABLE_KINDS only once code exists that turns it into model input. Voice
    needs a local speech engine, documents need extraction that is not built.
    """
    assert set(READABLE_KINDS) == {"photo", "voice"}
    for kind in RECOGNISED_KINDS:
        att = classify({kind: {"file_id": "x"} if kind not in ("photo",)
                        else [{"file_id": "x"}]})
        assert att is not None
        assert att.readable is (kind in ("photo", "voice")), kind


def test_a_photo_says_it_was_received_rather_than_that_nothing_can_read_it():
    assert describe(classify({"photo": [{"file_id": "p"}]})) == "Got your photo."


def test_a_kind_with_no_reading_path_still_says_so():
    assert "not wired up yet" in describe(classify({"document": {"file_id": "d"}}))


def test_a_read_failure_beats_the_pipeline_answer(monkeypatch):
    """`readable` is about the pipeline; `note` is about *this* message, and wins.

    A photo is readable in general and can still fail to be read here — no local
    vision model, a refused download. Reporting "Got your photo." then answering
    nothing would be the dishonesty the whole module exists to prevent.
    """
    att = classify({"photo": [{"file_id": "p"}]})
    assert att.readable is True
    assert describe(att, note="the local vision model did not answer") == (
        "I can see you sent a photo, but the local vision model did not answer."
    )


# ── how it reads to a person ────────────────────────────────────────────────


@pytest.mark.parametrize("kind,expected", [
    ("audio", "I can see you sent an audio file, but reading audio files is not wired up yet."),
    ("animation", "I can see you sent a GIF, but reading GIFs is not wired up yet."),
    ("video_note", "I can see you sent a video note, but reading video notes is not wired up yet."),
])
def test_each_kind_is_named_the_way_a_person_would_name_it(kind, expected):
    assert describe(classify({kind: {"file_id": "x"}})) == expected


def test_every_recognised_kind_has_a_human_name():
    assert set(DISPLAY) >= set(RECOGNISED_KINDS)
    assert display("brand_new_kind") == "brand_new_kind"
    assert display("brand_new_kind", plural=True) == "brand_new_kinds"


# ── what the turn carries ───────────────────────────────────────────────────


def test_the_turn_carries_the_senders_words_never_the_description():
    att = classify({"photo": [{"file_id": "p"}], "caption": "  ce e asta?  "})
    assert turn_text(att) == "ce e asta?"
    assert "I can see" not in turn_text(att)


def test_explicit_text_wins_over_a_caption():
    att = classify({"photo": [{"file_id": "p"}], "caption": "caption"})
    assert turn_text(att, "typed text") == "typed text"
    assert turn_text(att, "   ") == "caption"


def test_a_bare_file_produces_no_turn_text_rather_than_an_invented_prompt():
    assert turn_text(classify({"voice": {"file_id": "v"}})) == ""


@pytest.mark.parametrize("bad", [None, {"kind": "photo"}, "photo"])
def test_the_helpers_refuse_the_wrong_shape(bad):
    with pytest.raises(TypeError):
        describe(bad)
    with pytest.raises(TypeError):
        turn_text(bad)


def test_an_attachment_is_a_value_not_a_handle_bag():
    att = Attachment("photo", file_id="p", size=1, caption="c")
    assert att.readable is False or att.kind in READABLE_KINDS


# ── the poll loop ───────────────────────────────────────────────────────────


def _update(chat_type="private", chat_id=42, uid=42, **extra):
    return {
        "update_id": next(_update_ids),
        "message": {
            "message_id": 1,
            "from": {"id": uid},
            "chat": {"id": chat_id, "type": chat_type},
            **extra,
        },
    }


async def _drain(channel, updates):
    batches = [updates]

    async def fake_updates():
        if batches:
            return batches.pop(0)
        channel._running = False
        return []

    channel._get_updates = fake_updates
    channel._running = True
    await channel._poll_loop()


def _channel(policy=None):
    turns, sent = [], []

    async def handler(text, channel="telegram", **kwargs):
        turns.append((text, kwargs))
        return "ok"

    ch = TelegramChannel(token="t", handler=handler, group_policy=policy)
    ch._bot_id, ch._bot_username = BOT_ID, BOT

    async def fake_send(message, chat_id=None, **kwargs):
        sent.append((message, chat_id))
        return True

    ch.send = fake_send
    return ch, turns, sent


@pytest.mark.asyncio
async def test_a_bare_photo_gets_an_answer_instead_of_silence():
    ch, turns, sent = _channel()
    await _drain(ch, [_update(photo=[{"file_id": "p", "file_size": 10}])])
    # No local VLM is configured in the test environment, so the read is refused
    # at the gate — before any download — and the sender is told why.
    assert sent == [
        ("I can see you sent a photo, but no local vision model is configured here yet.", 42)
    ]
    assert turns == [], "a bare file nobody could read is not a prompt; do not invent one"


@pytest.mark.asyncio
async def test_a_captioned_photo_both_answers_and_runs_the_caption_as_the_turn():
    ch, turns, sent = _channel()
    await _drain(ch, [_update(photo=[{"file_id": "p"}], caption="ce e asta?")])
    assert len(sent) == 1 and "photo" in sent[0][0]
    assert [t for t, _ in turns] == ["ce e asta?"]


@pytest.mark.asyncio
async def test_an_oversized_file_is_told_about_not_swallowed():
    ch, _turns, sent = _channel()
    await _drain(ch, [_update(document={"file_id": "d", "file_size": 99 * 1024 * 1024})])
    assert "20 MB" in sent[0][0]


@pytest.mark.asyncio
async def test_a_text_only_message_behaves_exactly_as_before():
    ch, turns, sent = _channel()
    await _drain(ch, [_update(text="salut")])
    assert [t for t, _ in turns] == ["salut"]
    assert sent == [], "a text message must not gain a media line"


@pytest.mark.asyncio
async def test_a_bare_photo_in_a_group_is_still_not_addressed_to_the_bot():
    ch, turns, sent = _channel()
    await _drain(ch, [_update(chat_type="supergroup", chat_id=GROUP,
                              photo=[{"file_id": "p"}])])
    assert sent == [] and turns == []


@pytest.mark.asyncio
async def test_a_caption_that_names_the_bot_in_a_group_is_answered():
    ch, turns, sent = _channel()
    await _drain(ch, [_update(
        chat_type="supergroup", chat_id=GROUP,
        photo=[{"file_id": "p"}],
        caption=f"@{BOT} ce e asta?",
    )])
    assert len(sent) == 1
    assert [t for t, _ in turns] == ["ce e asta?"]


@pytest.mark.asyncio
async def test_a_username_less_mention_in_a_caption_still_addresses_the_bot():
    """The regression risk, precisely.

    A plain `@name` is found by regex in the text, so it proves nothing about
    where the entity list came from. Telegram sends a *text_mention* — a mention
    of an account with no public username — only as an entity, and for a caption
    that entity lives in `caption_entities`, not `entities`. Read the wrong key
    and this message stops being addressed to the bot.
    """
    ch, turns, sent = _channel()
    await _drain(ch, [_update(
        chat_type="supergroup", chat_id=GROUP,
        photo=[{"file_id": "p"}],
        caption="ce e asta?",
        caption_entities=[
            {"type": "text_mention", "offset": 0, "length": 2, "user": {"id": BOT_ID}},
        ],
    )])
    assert len(sent) == 1, "the bot was addressed by a text_mention in the caption"
    assert [t for t, _ in turns] == ["ce e asta?"]


@pytest.mark.asyncio
async def test_observe_mode_does_not_forward_an_empty_turn():
    ch, turns, sent = _channel(GroupPolicy(observe_mode=True))
    await _drain(ch, [_update(chat_type="supergroup", chat_id=GROUP,
                              photo=[{"file_id": "p"}])])
    assert turns == [], "a bare file observed in a group is not context text"


@pytest.mark.asyncio
async def test_a_pairing_deeplink_still_never_reaches_the_handler():
    ch, turns, sent = _channel()
    await _drain(ch, [_update(text="/start SOME-TOKEN")])
    assert all("SOME-TOKEN" not in text for text, _ in turns)


def test_the_channel_declares_what_it_now_recognises():
    assert set(TelegramChannel.descriptor.recognises_media) == set(RECOGNISED_KINDS)
    assert "photo" in TelegramChannel.descriptor.recognises_media


def test_the_descriptor_separates_recognising_from_reading():
    d = TelegramChannel.descriptor
    assert d.reads_media == ("photo", "voice")
    assert set(d.reads_media) < set(d.recognises_media)
    assert "document" in d.recognises_media and "document" not in d.reads_media


def test_a_descriptor_cannot_claim_to_read_what_it_never_recognised():
    """The invariant is checked at construction, so the two fields cannot drift."""
    from agents.core.channels.descriptor import ChannelDescriptor

    ChannelDescriptor(recognises_media=("photo",), reads_media=("photo",))
    with pytest.raises(ValueError, match="not recognised"):
        ChannelDescriptor(recognises_media=("voice",), reads_media=("photo",))
    with pytest.raises(ValueError):
        ChannelDescriptor(reads_media="photo")
