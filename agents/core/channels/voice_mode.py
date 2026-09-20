"""Per-chat voice mode: whether a chat channel answers in speech, and when.

The spoken half of H071. Hermes has ``/voice`` with three settings per chat —
off, reply with voice to a voice note, or speak every reply — and that is the
shape kept here, because the person choosing it is the one who will hear it:
a voice note sent from the road wants a voice note back; a chat read at a desk
does not want every reply narrated.

Three decisions are deliberate:

* **Off by default, per chat, set by the chat.** Speaking a reply sends its text
  to whatever text-to-speech backend the host has, and the default one
  (edge-tts) is a cloud service. Nothing here turns that on for anyone; the
  chat that wants it says so, and ``/voice`` names the backend that will speak.
* **The mode decides *whether*, never *what*.** The text reply is always sent
  and the voice note follows it; the delivery router's decision to answer at
  all is upstream and untouched. A chat cannot use voice mode to receive
  something the router would have withheld as text.
* **The store is the only state.** Keyed by ``channel:chat``, one string each,
  so an unknown chat is simply ``off`` and a corrupt value reads as ``off``
  rather than as anything louder.
"""

from __future__ import annotations

import threading
from pathlib import Path

from agents.core.paths import data_path

from ..persistence import JsonStore

OFF = "off"
#: Reply with a voice note when the message answered was itself a voice note.
VOICE = "voice"
#: Speak every reply delivered to the chat.
ALWAYS = "always"
MODES: tuple[str, ...] = (OFF, VOICE, ALWAYS)
DEFAULT_MODE = OFF

DESCRIPTIONS: dict[str, str] = {
    OFF: "text only",
    VOICE: "a voice note back when you send a voice note",
    ALWAYS: "a voice note with every reply",
}

DEFAULT_PATH = data_path("voice_modes.json")
_MAX_KEY_CHARS = 128


def wants_voice(mode: str, *, inbound_voice: bool) -> bool:
    """Whether a reply in this chat gets a voice note, given what it answers."""
    if mode == ALWAYS:
        return True
    if mode == VOICE:
        return bool(inbound_voice)
    return False


def _key(channel: str, chat: object) -> str:
    if not isinstance(channel, str) or not channel.strip():
        raise ValueError("channel must be a non-empty string")
    chat_text = "" if chat is None else str(chat).strip()
    if not chat_text:
        raise ValueError("chat must identify one conversation")
    key = f"{channel.strip().lower()}:{chat_text}"
    if len(key) > _MAX_KEY_CHARS:
        raise ValueError("chat identifier too long")
    return key


class VoiceModeStore(JsonStore):
    """``{"telegram:42": "voice"}`` on disk; anything unreadable is ``off``."""

    def __init__(self, path: str | Path | None = DEFAULT_PATH) -> None:
        self._modes: dict[str, str] = {}
        super().__init__(path)

    def _serialize(self):
        return dict(self._modes)

    def _deserialize(self, raw) -> None:
        self._modes = {}
        if not isinstance(raw, dict):
            return
        for key, value in raw.items():
            if isinstance(key, str) and value in MODES and value != OFF:
                self._modes[key] = value

    def get(self, channel: str, chat: object) -> str:
        try:
            key = _key(channel, chat)
        except ValueError:
            return DEFAULT_MODE
        with self._lock:
            return self._modes.get(key, DEFAULT_MODE)

    def set(self, channel: str, chat: object, mode: str) -> str:
        """Record *mode* for one chat; ``off`` forgets the chat. Returns the mode."""
        if mode not in MODES:
            raise ValueError(f"unknown voice mode {mode!r}")
        key = _key(channel, chat)
        with self._lock:
            if mode == OFF:
                self._modes.pop(key, None)
            else:
                self._modes[key] = mode
            self._save()
        return mode


_default: VoiceModeStore | None = None
_default_lock = threading.Lock()


def default_store() -> VoiceModeStore:
    """The process-wide store, built on first use from the data root."""
    global _default
    if _default is None:
        with _default_lock:
            if _default is None:
                _default = VoiceModeStore()
    return _default


def use_store(store: VoiceModeStore | None) -> None:
    """Swap the process-wide store (tests; ``None`` rebuilds it on next use)."""
    global _default
    with _default_lock:
        _default = store


__all__ = [
    "ALWAYS",
    "DEFAULT_MODE",
    "DESCRIPTIONS",
    "MODES",
    "OFF",
    "VOICE",
    "VoiceModeStore",
    "default_store",
    "use_store",
    "wants_voice",
]
