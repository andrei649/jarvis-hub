"""Per-chat voice mode (H071, the spoken half): the store and the `/voice` command.

Off by default, set by the chat, for the chat. What is pinned: an unknown chat
is off, a corrupt or foreign value on disk is off, `off` forgets the chat
rather than storing a third state, the three modes decide *whether* a reply is
spoken given what it answers, and `/voice` refuses to act where there is no
chat to act on while naming the engine that would speak.

Hermetic: a temp-file store, no Telegram, no speech stack (the engine probe is
pinned).
"""

from __future__ import annotations

import json

import pytest

from agents.core import commands as commands_module
from agents.core.channels import voice_mode
from agents.core.channels.spoken_reply import SpokenReply
from agents.core.channels.voice_mode import (
    ALWAYS,
    DEFAULT_MODE,
    MODES,
    OFF,
    VOICE,
    VoiceModeStore,
    wants_voice,
)
from agents.core.commands import Principal, build_default_registry

# ── the decision ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "mode, inbound_voice, spoken",
    [
        (OFF, False, False),
        (OFF, True, False),
        (VOICE, False, False),
        (VOICE, True, True),
        (ALWAYS, False, True),
        (ALWAYS, True, True),
    ],
)
def test_the_mode_decides_whether_a_reply_is_spoken_given_what_it_answers(mode, inbound_voice, spoken):
    assert wants_voice(mode, inbound_voice=inbound_voice) is spoken


def test_an_unknown_mode_never_speaks():
    assert wants_voice("loud", inbound_voice=True) is False
    assert wants_voice("", inbound_voice=True) is False


def test_the_default_is_off_and_the_modes_are_exactly_three():
    assert DEFAULT_MODE == OFF
    assert MODES == (OFF, VOICE, ALWAYS)


# ── the store ───────────────────────────────────────────────────────────────


def test_an_unknown_chat_is_off():
    store = VoiceModeStore(None)
    assert store.get("telegram", 42) == OFF
    assert store.get("telegram", "42") == OFF


def test_set_then_get_and_the_chat_key_is_channel_plus_chat(tmp_path):
    store = VoiceModeStore(tmp_path / "modes.json")
    assert store.set("telegram", 42, VOICE) == VOICE
    assert store.get("telegram", 42) == VOICE
    assert store.get("telegram", "42") == VOICE, "an int and its string name the same chat"
    assert store.get("Telegram", 42) == VOICE, "the channel name is case-insensitive"
    assert store.get("telegram", 43) == OFF
    assert store.get("discord", 42) == OFF, "another channel's chat 42 is another chat"


def test_the_mode_survives_a_restart(tmp_path):
    path = tmp_path / "modes.json"
    VoiceModeStore(path).set("telegram", 42, ALWAYS)
    assert VoiceModeStore(path).get("telegram", 42) == ALWAYS


def test_off_forgets_the_chat_instead_of_storing_a_third_state(tmp_path):
    path = tmp_path / "modes.json"
    store = VoiceModeStore(path)
    store.set("telegram", 42, VOICE)
    store.set("telegram", 42, OFF)
    assert json.loads(path.read_text(encoding="utf-8")) == {}
    assert store.get("telegram", 42) == OFF


def test_an_unknown_mode_is_refused_not_stored(tmp_path):
    store = VoiceModeStore(tmp_path / "modes.json")
    with pytest.raises(ValueError):
        store.set("telegram", 42, "loud")
    assert store.get("telegram", 42) == OFF


@pytest.mark.parametrize("chat", ["", "   ", None])
def test_a_chat_that_names_nothing_is_refused(tmp_path, chat):
    store = VoiceModeStore(tmp_path / "modes.json")
    with pytest.raises(ValueError):
        store.set("telegram", chat, VOICE)
    assert store.get("telegram", chat) == OFF


def test_a_corrupt_or_foreign_file_reads_as_off(tmp_path):
    path = tmp_path / "modes.json"
    path.write_text("not json", encoding="utf-8")
    assert VoiceModeStore(path).get("telegram", 42) == OFF
    path.write_text(json.dumps({"telegram:42": "loud", "telegram:43": 7, "telegram:44": "voice"}),
                    encoding="utf-8")
    store = VoiceModeStore(path)
    assert store.get("telegram", 42) == OFF
    assert store.get("telegram", 43) == OFF
    assert store.get("telegram", 44) == VOICE


# ── /voice ──────────────────────────────────────────────────────────────────


@pytest.fixture
def modes(tmp_path):
    store = VoiceModeStore(tmp_path / "modes.json")
    voice_mode.use_store(store)
    yield store
    voice_mode.use_store(None)


@pytest.fixture
def cloud_tts(monkeypatch):
    monkeypatch.setattr(SpokenReply, "_engines", staticmethod(lambda: (True, False)))


CHAT = Principal(channel="telegram", sender="7", admin=False, chat="42")
NO_CHAT = Principal(channel="web", sender=None, admin=True)


async def _voice(args="", principal=CHAT):
    outcome = await build_default_registry().dispatch(
        f"/voice {args}".strip(), orch=object(), principal=principal,
    )
    return outcome


@pytest.mark.asyncio
async def test_voice_shows_the_mode_and_names_the_engine_that_would_speak(modes, cloud_tts):
    outcome = await _voice()
    assert outcome.status == "answered"
    assert "off" in outcome.reply and "text only" in outcome.reply
    assert "edge-tts (Microsoft, cloud)" in outcome.reply, "cloud is called cloud before anyone turns it on"


@pytest.mark.asyncio
async def test_voice_sets_the_mode_for_this_chat_only(modes, cloud_tts):
    outcome = await _voice("voice")
    assert outcome.status == "answered" and "now voice" in outcome.reply
    assert modes.get("telegram", "42") == VOICE
    assert modes.get("telegram", "43") == OFF
    assert (await _voice("ALWAYS")).reply.startswith("Voice mode here is now always")
    assert modes.get("telegram", "42") == ALWAYS
    assert (await _voice("off")).reply == "Voice mode here is now off — text only."
    assert modes.get("telegram", "42") == OFF


@pytest.mark.asyncio
async def test_voice_refuses_an_unknown_mode_and_changes_nothing(modes, cloud_tts):
    outcome = await _voice("loud")
    assert outcome.status == "answered" and "Unknown voice mode" in outcome.reply
    assert "Usage: /voice off | voice | always." in outcome.reply
    assert modes.get("telegram", "42") == OFF


@pytest.mark.asyncio
async def test_voice_says_so_when_there_is_no_chat_to_set_it_for(modes, cloud_tts):
    outcome = await _voice("always", principal=NO_CHAT)
    assert outcome.status == "answered"
    assert "no chat here" in outcome.reply
    assert modes.get("web", "") == OFF


@pytest.mark.asyncio
async def test_voice_is_honest_about_a_host_with_no_speech_engine(modes, monkeypatch):
    monkeypatch.setattr(SpokenReply, "_engines", staticmethod(lambda: (False, False)))
    outcome = await _voice("voice")
    assert modes.get("telegram", "42") == VOICE, "the wish is recorded"
    assert "No text-to-speech engine is installed" in outcome.reply


def test_voice_is_a_user_command_not_an_owner_one():
    command = build_default_registry().get("voice")
    assert command is not None and command.tier == commands_module.USER
    assert command.usage == "[off|voice|always]"
