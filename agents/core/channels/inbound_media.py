"""What arrived on a chat message besides text — recognised, bounded, never guessed.

Until this module, `TelegramChannel._poll_loop` read `msg["text"]` and did
`if not text: continue`. A photo, a voice note, a document — even a photo with
the caption "what is this?" — vanished without a reply, without a log line the
owner would look at, and without the sender learning anything. The inventory row
(H108) asks for inbound media; the first honest step is to stop dropping it on
the floor and to say, in one line, what came in and whether Nerva can read it.

Three rules shape everything here:

- **The kind comes from the envelope, never from the payload.** Telegram tells
  us which field carried the file — `photo`, `voice`, `document` — and that is
  what this module trusts. `mime_type` and `file_name` are strings the *sender*
  chose; a document named `holiday.jpg` is still a document. Deriving the kind
  from attacker-controlled text is how "it's just an image" becomes something
  else entirely.
- **Recognising is not reading.** :data:`READABLE_KINDS` is the set Nerva can
  currently turn into something a model sees. It is deliberately empty: the
  download seam and the taint-fenced hand-off into a turn are not built yet, and
  a field that quietly reported otherwise would be the exact dishonesty the
  approval surfaces exist to prevent. Filling this set is the switch that turns
  the capability on, in one reviewable line.
- **Nothing sender-supplied is echoed unescaped, and the handle never is.**
  `file_id` is an opaque capability: anyone holding it and the bot token can
  fetch the bytes, so it stays inside the process and never reaches a chat
  message, a log line or a description.

Pure and offline-testable: no network, no filesystem, no Telegram client.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

KIND_PHOTO = "photo"
KIND_VOICE = "voice"
KIND_AUDIO = "audio"
KIND_DOCUMENT = "document"
KIND_VIDEO = "video"
KIND_VIDEO_NOTE = "video_note"
KIND_ANIMATION = "animation"
KIND_STICKER = "sticker"
KIND_LOCATION = "location"
KIND_CONTACT = "contact"

#: Checked in this order, so the most specific envelope wins when Telegram sends
#: several (an animation also carries a `document`; a video note also a `video`).
_FIELD_ORDER: tuple[str, ...] = (
    KIND_ANIMATION, KIND_VIDEO_NOTE, KIND_STICKER, KIND_PHOTO, KIND_VOICE,
    KIND_AUDIO, KIND_VIDEO, KIND_DOCUMENT, KIND_LOCATION, KIND_CONTACT,
)

#: Every kind this module recognises, in the order it checks them. Public so a
#: channel descriptor can declare what its adapter will no longer silently drop.
RECOGNISED_KINDS: tuple[str, ...] = _FIELD_ORDER

#: Kinds carrying a downloadable file (location and contact do not).
FILE_KINDS: frozenset[str] = frozenset(_FIELD_ORDER) - {KIND_LOCATION, KIND_CONTACT}

#: What Nerva can currently turn into model input. Empty on purpose — see the
#: module docstring. Adding a kind here is how the capability is switched on,
#: once the download seam and the taint-fenced hand-off exist.
READABLE_KINDS: frozenset[str] = frozenset()

#: Telegram's own ceiling for what a bot may download. A declared size above it
#: can never be fetched, so it is refused here rather than at the wire.
MAX_DECLARED_BYTES = 20 * 1024 * 1024

#: Captions are sender text. Bounded before they travel anywhere.
MAX_CAPTION_CHARS = 4096

#: What each kind is called when Nerva talks to a person about it. Telegram's
#: field names are not English nouns ("voice", "video_note"), and a sentence
#: built by appending "s" to them reads like a machine talking to itself.
DISPLAY: Mapping[str, tuple[str, str]] = {
    KIND_PHOTO: ("photo", "photos"),
    KIND_VOICE: ("voice note", "voice notes"),
    KIND_AUDIO: ("audio file", "audio files"),
    KIND_DOCUMENT: ("file", "files"),
    KIND_VIDEO: ("video", "videos"),
    KIND_VIDEO_NOTE: ("video note", "video notes"),
    KIND_ANIMATION: ("GIF", "GIFs"),
    KIND_STICKER: ("sticker", "stickers"),
    KIND_LOCATION: ("location", "locations"),
    KIND_CONTACT: ("contact", "contacts"),
}

REASON_TOO_LARGE = "media_too_large"
REASON_NO_HANDLE = "media_handle_missing"
REASON_NOT_READABLE = "media_pipeline_not_wired"


@dataclass(frozen=True)
class Attachment:
    """One recognised non-text item on a message."""

    kind: str
    file_id: str = ""
    size: int = 0
    caption: str = ""
    reason: str = ""

    @property
    def readable(self) -> bool:
        """Can Nerva actually turn this into something a model sees, today?"""
        return not self.reason and self.kind in READABLE_KINDS

    def to_dict(self) -> dict:
        """A view safe to log or surface. The handle is deliberately absent."""
        return {
            "kind": self.kind,
            "size": self.size,
            "has_caption": bool(self.caption),
            "readable": self.readable,
            "reason": self.reason,
        }


def _clean(value: object, limit: int) -> str:
    """Bound sender text and strip the control characters that forge log lines."""
    text = value if isinstance(value, str) else ""
    text = "".join(ch for ch in text if ch == "\t" or ch == "\n" or ch >= " ")
    return text[:limit]


def _largest_photo(variants: object) -> Mapping | None:
    """Telegram sends a photo as ascending size variants; take the biggest usable one."""
    if not isinstance(variants, (list, tuple)):
        return None
    usable = [v for v in variants if isinstance(v, Mapping) and v.get("file_id")]
    if not usable:
        return None
    return max(usable, key=lambda v: v.get("file_size") if isinstance(
        v.get("file_size"), int) and not isinstance(v.get("file_size"), bool) else 0)


def classify(message: object) -> Attachment | None:
    """Return what is attached to ``message``, or ``None`` for a text-only message.

    A structural problem (no handle, declared size past the ceiling) becomes a
    named ``reason`` on the returned attachment rather than a dropped message:
    the sender gets told, which is the whole point.
    """
    if not isinstance(message, Mapping):
        return None
    caption = _clean(message.get("caption"), MAX_CAPTION_CHARS)

    for kind in _FIELD_ORDER:
        payload = message.get(kind)
        if not payload:
            continue
        if kind == KIND_PHOTO:
            payload = _largest_photo(payload)
            if payload is None:
                return Attachment(KIND_PHOTO, caption=caption, reason=REASON_NO_HANDLE)
        if kind in (KIND_LOCATION, KIND_CONTACT):
            # Not a file: there is nothing to download, and the coordinates or
            # phone number are the owner's data, not something to echo back.
            return Attachment(kind, caption=caption, reason=REASON_NOT_READABLE)
        if not isinstance(payload, Mapping):
            return Attachment(kind, caption=caption, reason=REASON_NO_HANDLE)
        file_id = payload.get("file_id")
        if not isinstance(file_id, str) or not file_id:
            return Attachment(kind, caption=caption, reason=REASON_NO_HANDLE)
        raw_size = payload.get("file_size")
        size = raw_size if isinstance(raw_size, int) and not isinstance(raw_size, bool) else 0
        if size < 0:
            size = 0
        if size > MAX_DECLARED_BYTES:
            return Attachment(kind, file_id=file_id, size=size, caption=caption,
                              reason=REASON_TOO_LARGE)
        reason = "" if kind in READABLE_KINDS else REASON_NOT_READABLE
        return Attachment(kind, file_id=file_id, size=size, caption=caption, reason=reason)
    return None


#: One plain sentence per reason. No paths, no handles, no sender text.
_NOTES: Mapping[str, str] = {
    REASON_TOO_LARGE: "it is larger than the {cap} MB a bot is allowed to download",
    REASON_NO_HANDLE: "it arrived without a usable file reference",
    REASON_NOT_READABLE: "reading {plural} is not wired up yet",
}


def display(kind: str, *, plural: bool = False) -> str:
    """The human name for a kind; falls back to the raw field for a new one."""
    names = DISPLAY.get(kind)
    if names is None:
        return f"{kind}s" if plural else kind
    return names[1] if plural else names[0]


def describe(attachment: Attachment) -> str:
    """The one honest line the sender gets, so nothing arrives into silence."""
    if not isinstance(attachment, Attachment):
        raise TypeError("describe() needs an Attachment")
    one = display(attachment.kind)
    if attachment.readable:
        return f"Got your {one}."
    template = _NOTES.get(attachment.reason, "it cannot be read")
    note = template.format(
        plural=display(attachment.kind, plural=True),
        cap=MAX_DECLARED_BYTES // (1024 * 1024),
    )
    article = "an" if one[0].lower() in "aeiou" else "a"
    return f"I can see you sent {article} {one}, but {note}."


def turn_text(attachment: Attachment, text: str = "") -> str:
    """What the turn should carry: the sender's own words, never the description.

    A caption is the sender asking something about the thing they sent, so it is
    the turn. The description is a reply *to* them, not a line the model should
    read as if Nerva had observed the file — that would be a fabricated
    observation, which is the one thing the honesty rules refuse.
    """
    if not isinstance(attachment, Attachment):
        raise TypeError("turn_text() needs an Attachment")
    spoken = text if isinstance(text, str) and text.strip() else attachment.caption
    return spoken.strip()


__all__ = [
    "DISPLAY",
    "FILE_KINDS",
    "RECOGNISED_KINDS",
    "KIND_ANIMATION",
    "KIND_AUDIO",
    "KIND_CONTACT",
    "KIND_DOCUMENT",
    "KIND_LOCATION",
    "KIND_PHOTO",
    "KIND_STICKER",
    "KIND_VIDEO",
    "KIND_VIDEO_NOTE",
    "KIND_VOICE",
    "MAX_CAPTION_CHARS",
    "MAX_DECLARED_BYTES",
    "READABLE_KINDS",
    "REASON_NOT_READABLE",
    "REASON_NO_HANDLE",
    "REASON_TOO_LARGE",
    "Attachment",
    "classify",
    "describe",
    "display",
    "turn_text",
]
