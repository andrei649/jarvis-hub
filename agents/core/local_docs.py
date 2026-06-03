"""
local_docs.py — H12.2 Onboarding "drop folder → private chat with your docs".

One low-friction step: point Jarvis at a local folder, it indexes the documents
into memory **locally** (using whatever embedding backend is configured, with the
hash fallback so it works fully offline), and you can then chat with them. No
cloud hop, no config.

Plain-text formats (.md / .markdown / .txt) are read natively. PDF / DOCX are
best-effort: if the optional parser isn't installed the file is skipped (counted,
never fatal). The ``remember`` callable is injected so this is offline-testable.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Awaitable, Callable, Optional

logger = logging.getLogger("jarvis.local_docs")

TEXT_EXTS = {".md", ".markdown", ".txt", ".text", ".rst"}
DOC_EXTS = {".pdf", ".docx"}
SUPPORTED_EXTS = TEXT_EXTS | DOC_EXTS

# remember: ``async (text, metadata) -> Optional[str]``
RememberFn = Callable[[str, dict], Awaitable[Optional[str]]]


def extract_text(path: Path) -> Optional[str]:
    """Return the document's text, or None if unreadable / parser missing."""
    ext = path.suffix.lower()
    if ext in TEXT_EXTS:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            logger.debug("read failed for %s: %s", path, exc)
            return None
    if ext == ".pdf":
        try:
            import pypdf  # type: ignore
            reader = pypdf.PdfReader(str(path))
            return "\n".join((pg.extract_text() or "") for pg in reader.pages)
        except Exception:
            return None  # parser missing or corrupt PDF → skip
    if ext == ".docx":
        try:
            import docx  # type: ignore
            return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)
        except Exception:
            return None
    return None


def chunk_text(text: str, chunk_words: int = 400, overlap: int = 40) -> list[str]:
    """Split text into ~chunk_words word windows with a small overlap."""
    words = text.split()
    if not words:
        return []
    if len(words) <= chunk_words:
        return [" ".join(words)]
    step = max(1, chunk_words - overlap)
    chunks = []
    for start in range(0, len(words), step):
        chunk = words[start:start + chunk_words]
        if chunk:
            chunks.append(" ".join(chunk))
        if start + chunk_words >= len(words):
            break
    return chunks


class LocalDocsIndexer:
    def __init__(self, remember: RememberFn, chunk_words: int = 400) -> None:
        self.remember = remember
        self.chunk_words = chunk_words

    async def index(self, folder: str | Path, allowed_root: str | Path | None = None) -> dict:
        """Index every supported document under *folder* (recursively).

        When *allowed_root* is given, the (resolved) folder must live inside it —
        a containment barrier so an inbound request can't point the indexer at an
        arbitrary location like ``/etc`` or ``~/.ssh``.
        """
        # Normalize the (untrusted) folder to a real path, then require it to be
        # contained in allowed_root. realpath + startswith is the canonical
        # path-traversal barrier (resolves '..' and symlinks before the check).
        root_real = os.path.realpath(os.path.expanduser(str(folder)))
        if allowed_root is not None:
            base_real = os.path.realpath(os.path.expanduser(str(allowed_root)))
            if root_real != base_real and not root_real.startswith(base_real + os.sep):
                return {"error": "path is outside the allowed root"}
        root = Path(root_real)
        if not root.exists() or not root.is_dir():
            return {"error": f"not a folder: {folder}"}

        files_indexed = 0
        files_skipped = 0
        chunks_total = 0
        skipped: list[str] = []

        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTS:
                continue
            text = extract_text(path)
            if not text or not text.strip():
                files_skipped += 1
                skipped.append(path.name)
                continue
            rel = str(path.relative_to(root))
            chunks = chunk_text(text, self.chunk_words)
            for i, chunk in enumerate(chunks):
                await self.remember(
                    chunk,
                    {"source": "local_docs", "file": rel, "chunk": i},
                )
            files_indexed += 1
            chunks_total += len(chunks)

        return {
            "folder": str(root),
            "files_indexed": files_indexed,
            "files_skipped": files_skipped,
            "chunks": chunks_total,
            "skipped": skipped[:50],
        }
