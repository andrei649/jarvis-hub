"""render.py — outbound text a channel can actually display (Hermes absorption 4a).

A model reply is Markdown-ish. Telegram was sent it verbatim with ``parse_mode=Markdown``:
an odd number of ``*``, an unclosed code fence or a stray ``_`` is an HTTP 400, ``send()``
returned False, and the owner saw nothing — the failure was a log line. A reply over 4,096
characters failed the same way. Rendering and chunking are now one registry keyed by the
channel's declared dialect (:mod:`descriptor`), with one shared plain-text stripper, so a
new channel adds a renderer and nothing else.

Rules that make the output *valid by construction*:

* only balanced markers become markup — an unbalanced ``*`` stays a literal ``*``;
* text is escaped before any tag is added, so nothing in a reply can open a tag;
* chunking happens on the source, at paragraph then line boundaries, never inside a fenced
  code block (a fence that spans chunks is closed and reopened), and a single overlong line
  is hard-split as the last resort; each chunk is rendered on its own, so every chunk is
  well-formed and no chunk exceeds the channel's cap in visible characters.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable

from .descriptor import (
    DIALECT_MARKDOWN,
    DIALECT_PLAIN,
    DIALECT_SLACK_MRKDWN,
    DIALECT_TELEGRAM_HTML,
    ChannelDescriptor,
)

_FENCE_RE = re.compile(r"^\s*```")
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_BOLD_RE = re.compile(r"(?<![\w*])\*\*(?=\S)(.+?)(?<=\S)\*\*(?![\w*])")
_BOLD_UNDERSCORE_RE = re.compile(r"(?<![\w_])__(?=\S)(.+?)(?<=\S)__(?![\w_])")
_ITALIC_RE = re.compile(r"(?<![\w*])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![\w*])")
_ITALIC_UNDERSCORE_RE = re.compile(r"(?<![\w_])_(?=[^\s_])(.+?)(?<=[^\s_])_(?![\w_])")
_LINK_RE = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*$")
_CODE_PLACEHOLDER = "\x00code{}\x00"


def _split_fences(text: str) -> list[tuple[bool, str]]:
    """``(is_code, block)`` segments; a fence line opens or closes a code block."""
    segments: list[tuple[bool, str]] = []
    buffer: list[str] = []
    in_code = False
    for line in text.split("\n"):
        if _FENCE_RE.match(line):
            if buffer or not segments:
                segments.append((in_code, "\n".join(buffer)))
            buffer = []
            in_code = not in_code
            continue
        buffer.append(line)
    segments.append((in_code, "\n".join(buffer)))
    return [(code, block) for code, block in segments if block or code]


def _inline_html(text: str) -> str:
    """One paragraph of escaped prose → Telegram HTML with balanced markers only."""
    codes: list[str] = []

    def _stash(match: re.Match) -> str:
        codes.append(f"<code>{match.group(1)}</code>")
        return _CODE_PLACEHOLDER.format(len(codes) - 1)

    out = _INLINE_CODE_RE.sub(_stash, text)
    out = _LINK_RE.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', out)
    out = _BOLD_RE.sub(r"<b>\1</b>", out)
    out = _BOLD_UNDERSCORE_RE.sub(r"<b>\1</b>", out)
    out = _ITALIC_RE.sub(r"<i>\1</i>", out)
    out = _ITALIC_UNDERSCORE_RE.sub(r"<i>\1</i>", out)
    lines = []
    for line in out.split("\n"):
        heading = _HEADING_RE.match(line)
        lines.append(f"<b>{heading.group(2)}</b>" if heading else line)
    out = "\n".join(lines)
    for index, code in enumerate(codes):
        out = out.replace(_CODE_PLACEHOLDER.format(index), code)
    return out


def to_telegram_html(text: str) -> str:
    """Markdown-ish reply → the HTML subset Telegram's ``parse_mode=HTML`` accepts."""
    parts: list[str] = []
    for is_code, block in _split_fences(str(text or "")):
        escaped = html.escape(block, quote=False)
        if is_code:
            parts.append(f"<pre>{escaped}</pre>")
        else:
            parts.append(_inline_html(escaped))
    return "\n".join(part for part in parts if part)


def to_plain(text: str) -> str:
    """Strip the markers a plain channel would show verbatim; links keep their URL."""
    parts: list[str] = []
    for is_code, block in _split_fences(str(text or "")):
        if is_code:
            parts.append(block)
            continue
        out = _INLINE_CODE_RE.sub(r"\1", block)
        out = _LINK_RE.sub(r"\1 (\2)", out)
        out = _BOLD_RE.sub(r"\1", out)
        out = _BOLD_UNDERSCORE_RE.sub(r"\1", out)
        out = _ITALIC_RE.sub(r"\1", out)
        out = _ITALIC_UNDERSCORE_RE.sub(r"\1", out)
        out = "\n".join(
            (_HEADING_RE.match(line).group(2) if _HEADING_RE.match(line) else line)
            for line in out.split("\n")
        )
        parts.append(out)
    return "\n".join(parts)


def _inline_mrkdwn(text: str) -> str:
    """One paragraph of Slack-escaped prose → mrkdwn with balanced markers only."""
    codes: list[str] = []

    def _stash(match: re.Match) -> str:
        codes.append(f"`{match.group(1)}`")
        return _CODE_PLACEHOLDER.format(len(codes) - 1)

    out = _INLINE_CODE_RE.sub(_stash, text)
    out = _LINK_RE.sub(lambda m: f"<{m.group(2)}|{m.group(1)}>", out)
    # Italic before bold: once ``**b**`` has become ``*b*`` it must not be read as italic.
    out = _ITALIC_RE.sub(r"_\1_", out)
    out = _BOLD_RE.sub(r"*\1*", out)
    out = _BOLD_UNDERSCORE_RE.sub(r"*\1*", out)
    lines = []
    for line in out.split("\n"):
        heading = _HEADING_RE.match(line)
        lines.append(f"*{heading.group(2)}*" if heading else line)
    out = "\n".join(lines)
    for index, code in enumerate(codes):
        out = out.replace(_CODE_PLACEHOLDER.format(index), code)
    return out


def to_slack_mrkdwn(text: str) -> str:
    """Markdown-ish reply → Slack ``mrkdwn`` (``*bold*``, ``_italic_``, ``<url|text>``,
    ``&amp; &lt; &gt;`` escaped in prose and code alike)."""
    parts: list[str] = []
    for is_code, block in _split_fences(str(text or "")):
        escaped = block.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if is_code:
            parts.append("```\n" + escaped + "\n```")
        else:
            parts.append(_inline_mrkdwn(escaped))
    return "\n".join(part for part in parts if part)


def to_markdown(text: str) -> str:
    """A channel that renders Markdown itself (Discord) gets the source as it is."""
    return str(text or "")


RENDERERS: dict[str, Callable[[str], str]] = {
    DIALECT_PLAIN: to_plain,
    DIALECT_TELEGRAM_HTML: to_telegram_html,
    DIALECT_SLACK_MRKDWN: to_slack_mrkdwn,
    DIALECT_MARKDOWN: to_markdown,
}


def render(text: str, dialect: str) -> str:
    renderer = RENDERERS.get(dialect)
    if renderer is None:
        raise ValueError(f"no renderer for dialect {dialect!r}")
    return renderer(text)


# ── chunking (on the source, so every chunk renders on its own) ──────────────

def _hard_split(line: str, limit: int) -> list[str]:
    return [line[i:i + limit] for i in range(0, len(line), limit)] or [""]


def chunk(text: str, limit: int | None) -> list[str]:
    """Split *text* into pieces of at most *limit* characters.

    Paragraph boundaries first, then lines, then a hard split of one overlong line. A
    fenced code block is never split open: a fence that would span two chunks is closed at
    the end of one and reopened at the start of the next, so each chunk renders as valid
    markup on its own. Chunk order is source order; nothing is dropped.
    """
    source = str(text or "")
    if limit is None or len(source) <= limit:
        return [source]
    fence = "```"
    reserve = len(fence) + 1
    chunks: list[str] = []
    current: list[str] = []
    length = 0
    in_code = False

    def _flush() -> None:
        nonlocal current, length
        if not current:
            return
        # A chunk is its own message: the blank line that separated paragraphs at the
        # split point carries nothing across it.
        body = "\n".join(current).strip("\n")
        if in_code:
            body = body + "\n" + fence
        chunks.append(body)
        current = []
        length = 0

    def _push(line: str) -> None:
        nonlocal length
        current.append(line)
        length += len(line) + (1 if len(current) > 1 else 0)

    budget = limit - reserve if limit > reserve * 2 else limit
    for paragraph_index, paragraph in enumerate(source.split("\n\n")):
        lines = paragraph.split("\n")
        if paragraph_index:
            lines = ["", *lines]
        for line in lines:
            pieces = _hard_split(line, budget) if len(line) > budget else [line]
            for piece in pieces:
                extra = len(piece) + (1 if current else 0)
                if current and length + extra > budget:
                    was_code = in_code
                    _flush()
                    if was_code:
                        _push(fence)
                if _FENCE_RE.match(piece):
                    in_code = not in_code
                _push(piece)
    _flush()
    return [c for c in chunks if c.strip()] or [source[:limit]]


def render_outbound(text: str, descriptor: ChannelDescriptor) -> list[str]:
    """Chunk to the channel's cap, then render every chunk in its dialect."""
    return [render(piece, descriptor.dialect) for piece in chunk(text, descriptor.max_message_length)]


__all__ = [
    "RENDERERS", "chunk", "render", "render_outbound", "to_markdown", "to_plain",
    "to_slack_mrkdwn", "to_telegram_html",
]
