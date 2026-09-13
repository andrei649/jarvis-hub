"""descriptor.py — what a channel can actually do (Hermes absorption 4a).

The channel contract was a four-method ABC with no capability information at all: the
length cap, the markup dialect, whether a message can be edited — every such fact lived as
a hardcoded constant somewhere else or nowhere. Every per-channel feature (rendering,
chunking, streaming edits, media) blocks on a channel being able to *declare* what it
supports, so the declaration comes first and is deliberately small.

A descriptor is data, not behaviour: the renderer reads ``dialect`` and
``max_message_length``; nothing here sends anything.
"""

from __future__ import annotations

from dataclasses import dataclass

DIALECT_PLAIN = "plain"
DIALECT_TELEGRAM_HTML = "telegram_html"
DIALECT_SLACK_MRKDWN = "slack_mrkdwn"
#: CommonMark-ish markup the channel renders itself (Discord): passed through, only chunked.
DIALECT_MARKDOWN = "markdown"
DIALECTS: tuple[str, ...] = (
    DIALECT_PLAIN, DIALECT_TELEGRAM_HTML, DIALECT_SLACK_MRKDWN, DIALECT_MARKDOWN,
)


@dataclass(frozen=True)
class ChannelDescriptor:
    """Static capabilities of one channel adapter."""

    #: Markup the channel can display; one of :data:`DIALECTS`.
    dialect: str = DIALECT_PLAIN
    #: Longest single message the channel accepts (visible characters); None = no cap.
    max_message_length: int | None = None
    #: Can a sent message be edited in place (streaming replies need it)?
    supports_edit: bool = False
    #: Can the channel carry images / files *outbound*?
    supports_media: bool = False
    #: Kinds of inbound non-text item the adapter recognises — enough to answer
    #: the sender about, never enough to claim it was read.
    #: Empty means the adapter still drops anything that is not text.
    recognises_media: tuple[str, ...] = ()
    #: Kinds the adapter can actually turn into model input. A subset of
    #: `recognises_media`, enforced below, because reading something the adapter
    #: does not even recognise is not a state that can exist. Being listed here
    #: is a statement about the pipeline, not a promise about one message: a
    #: read can still fail (no local vision model, a refused download) and the
    #: sender is told so.
    reads_media: tuple[str, ...] = ()
    #: Does the channel have threads / topics a reply can be addressed to?
    supports_threads: bool = False

    def __post_init__(self) -> None:
        if self.dialect not in DIALECTS:
            raise ValueError(f"unknown channel dialect: {self.dialect!r}")
        cap = self.max_message_length
        if cap is not None and (isinstance(cap, bool) or not isinstance(cap, int) or cap < 16):
            raise ValueError("max_message_length must be an int of at least 16, or None")
        for field in ("recognises_media", "reads_media"):
            kinds = getattr(self, field)
            if isinstance(kinds, (str, bytes)) or not isinstance(kinds, tuple):
                raise ValueError(f"{field} must be a tuple of kind names")
            if any(not isinstance(k, str) or not k for k in kinds):
                raise ValueError(f"{field} entries must be non-empty strings")
        # The honesty invariant, checked at construction so it cannot drift: an
        # adapter cannot declare it reads a kind it never recognised.
        unknown = set(self.reads_media) - set(self.recognises_media)
        if unknown:
            raise ValueError(
                f"reads_media not recognised by this channel: {sorted(unknown)}")


__all__ = [
    "DIALECTS", "DIALECT_MARKDOWN", "DIALECT_PLAIN", "DIALECT_SLACK_MRKDWN",
    "DIALECT_TELEGRAM_HTML", "ChannelDescriptor",
]
