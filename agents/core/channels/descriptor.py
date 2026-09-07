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
DIALECTS: tuple[str, ...] = (DIALECT_PLAIN, DIALECT_TELEGRAM_HTML)


@dataclass(frozen=True)
class ChannelDescriptor:
    """Static capabilities of one channel adapter."""

    #: Markup the channel can display; one of :data:`DIALECTS`.
    dialect: str = DIALECT_PLAIN
    #: Longest single message the channel accepts (visible characters); None = no cap.
    max_message_length: int | None = None
    #: Can a sent message be edited in place (streaming replies need it)?
    supports_edit: bool = False
    #: Can the channel carry images / files?
    supports_media: bool = False
    #: Does the channel have threads / topics a reply can be addressed to?
    supports_threads: bool = False

    def __post_init__(self) -> None:
        if self.dialect not in DIALECTS:
            raise ValueError(f"unknown channel dialect: {self.dialect!r}")
        cap = self.max_message_length
        if cap is not None and (isinstance(cap, bool) or not isinstance(cap, int) or cap < 16):
            raise ValueError("max_message_length must be an int of at least 16, or None")


__all__ = ["DIALECTS", "DIALECT_PLAIN", "DIALECT_TELEGRAM_HTML", "ChannelDescriptor"]
