"""taint.py — H23.6: a minimal taint flag for content from untrusted external sources.

The first slice of cross-channel / indirect-injection defense (TASK-3). Content ingested
from an untrusted source (web fetch, OSINT, RSS, an inbound channel message) is *tainted*;
the action kernel then refuses to let a tainted action **auto-execute** — it escalates a
grant to approval. This is the **flag + enforcement mechanism**; full data-flow
*propagation* (carrying taint through derived content) is deliberately deferred.
"""

from __future__ import annotations

TAINT_KEY = "tainted"

# Source labels whose content is untrusted by default (substring match, case-insensitive).
UNTRUSTED_SOURCES = frozenset({
    "web", "websearch", "rss", "news", "osint", "worldview", "inbound", "external", "channel",
})


def is_untrusted_source(source: str | None) -> bool:
    """True if *source* names an untrusted external origin."""
    s = (source or "").strip().lower()
    return bool(s) and any(u in s for u in UNTRUSTED_SOURCES)


def mark(metadata: dict | None, source: str | None = None) -> dict:
    """Return a copy of *metadata* with the taint flag set (and the source recorded)."""
    meta = dict(metadata or {})
    meta[TAINT_KEY] = True
    if source:
        meta.setdefault("taint_source", source)
    return meta


def mark_if_untrusted(metadata: dict | None, source: str | None) -> dict:
    """Taint *metadata* only when *source* is untrusted; otherwise return it unchanged (copied)."""
    meta = dict(metadata or {})
    return mark(meta, source) if is_untrusted_source(source) else meta


def is_tainted(obj) -> bool:
    """True if *obj* (a metadata/payload dict) carries the taint flag."""
    return bool(isinstance(obj, dict) and obj.get(TAINT_KEY))
