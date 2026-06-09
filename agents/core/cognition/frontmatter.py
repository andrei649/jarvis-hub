"""
frontmatter.py — H21.2 SOUL front-matter parser.

Splits a SOUL.md into a YAML ``meta`` block (between leading ``---`` fences) and
the prose body — so personality/affect config can live in the SOUL header
without polluting the system prompt. No front-matter ⇒ ``({}, full_text)`` (a
no-op for the existing SOULs).
"""

from __future__ import annotations


def parse_frontmatter(text: str) -> "tuple[dict, str]":
    """Return (meta, body). Tolerant: malformed/absent front-matter → ({}, text)."""
    if not text:
        return {}, text or ""
    if not text.lstrip().startswith("---"):
        return {}, text
    stripped = text.lstrip()
    # locate the closing fence after the opening one
    rest = stripped[3:]
    end = rest.find("\n---")
    if end == -1:
        return {}, text
    raw = rest[:end]
    body = rest[end + 4:].lstrip("\n")
    try:
        import yaml
        meta = yaml.safe_load(raw)
        if not isinstance(meta, dict):
            return {}, text
        return meta, body
    except Exception:
        return {}, text
