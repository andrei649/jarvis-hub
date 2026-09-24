"""H165 — in-app documentation, served read-only from an allowlist.

Hermes ships its user documentation inside the app. Nerva's user guide, flag table and
privacy notes lived only in the repository, so the HUD had no way to show what a flag
costs or what the camera keeps. These two routes serve a hard-coded slug → file table.

- The slug is only ever a key into ``DOCS``, never joined into a path, so ``../``,
  encoded traversal and unknown slugs are all 404.
- A file is read from the install root, must be a regular file (a symlink is refused)
  and is capped at ``MAX_DOC_CHARS``.
- The body is Markdown text for the HUD's React-only renderer (frontend/src/markdown.tsx),
  which never turns it into HTML.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from fastapi import APIRouter, Depends

from agents.core.routers._deps import user_guard
from agents.core.web_helpers import nocache_json

logger = logging.getLogger("jarvis.help_docs")

router = APIRouter(tags=["help"], dependencies=[Depends(user_guard)])

_ROOT = Path(__file__).resolve().parents[3]
# slug → (title, path under the install root). Order is the order the HUD lists them.
DOCS: dict[str, tuple[str, str]] = {
    "user-guide": ("User guide", "docs/USER_GUIDE.md"),
    "flags": ("Feature flags — what each switch costs", "docs/FLAGS.md"),
    "privacy": ("Privacy", "docs/PRIVACY.md"),
    "camera-privacy": ("Camera privacy", "docs/CAMERA_PRIVACY.md"),
}
MAX_DOC_CHARS = 256_000

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_CODE_SPAN = re.compile(r"`([^`\n]+)`")


def heading_anchor(text: str) -> str:
    """frontend/src/markdown.tsx headingAnchor, character for character."""
    return re.sub(r"[^a-z0-9_.]+", "-", text.replace("`", "").lower()).strip("-")


def sections(markdown: str) -> list[dict]:
    """Each heading's anchor, title and the names its code spans document.

    The HUD links a setting straight to the section that names it (a FLAGS.md
    heading such as `llm.execute_code_sessions` (+ `llm.execute_code_image`, …)
    documents four keys). Headings inside code fences are not headings.
    """
    out: list[dict] = []
    seen: dict[str, int] = {}
    fence = None
    for line in markdown.replace("\r\n", "\n").split("\n"):
        opened = _FENCE.match(line)
        if fence is not None:
            if line.strip().startswith(fence):
                fence = None
            continue
        if opened:
            fence = opened.group(1)
            continue
        match = _HEADING.match(line)
        if not match:
            continue
        base = heading_anchor(match.group(2))
        count = seen.get(base, 0)
        seen[base] = count + 1
        out.append({"anchor": f"{base}-{count + 1}" if count else base, "title": match.group(2).replace("`", ""),
                    "names": _CODE_SPAN.findall(match.group(2))})
    return out


def _doc_path(slug: str) -> Path | None:
    entry = DOCS.get(slug)
    if entry is None:
        return None
    path = _ROOT / entry[1]
    try:
        if path.is_symlink() or not path.is_file():
            return None
    except OSError:
        return None
    return path


def _read(slug: str) -> str | None:
    path = _doc_path(slug)
    if path is None:
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("help doc %s unreadable: %s", slug, exc)
        return None


@router.get("/api/help/docs")
async def help_docs_list():
    docs = []
    for slug, (title, _rel) in DOCS.items():
        text = _read(slug)
        docs.append({"slug": slug, "title": title, "available": text is not None,
                     "sections": sections(text[:MAX_DOC_CHARS]) if text is not None else []})
    return nocache_json({"docs": docs})


@router.get("/api/help/docs/{slug}")
async def help_docs_read(slug: str):
    if slug not in DOCS:
        return nocache_json({"error": "no such document"}, status_code=404)
    text = _read(slug)
    if text is None:
        return nocache_json({"error": "that document is not available in this install"}, status_code=404)
    return nocache_json({"slug": slug, "title": DOCS[slug][0], "markdown": text[:MAX_DOC_CHARS],
                         "truncated": len(text) > MAX_DOC_CHARS})
