"""
context_compressor.py — H20.3 Runtime context compression.

For long sessions, keep the recent turns verbatim and **intelligently evict**
the older ones — summarizing them (via an injectable summarizer, deferred LLM)
or, offline, keeping the most important older turns as a deterministic digest.
This is the *hot-path* compressor (distinct from the nightly consolidation of
H5.15); it ties into the "sleep-time compute" theme. Pure and offline-testable;
the LLM summarizer is injected.
"""

from __future__ import annotations

import re
from typing import Awaitable, Callable, Optional


class ContextCompressor:
    """Token-budgeted compression: keep recent turns, digest/summarize the rest."""

    def __init__(self, summarizer: Optional[Callable[[str], Awaitable[str]]] = None,
                 max_tokens: int = 2000, keep_recent: int = 4) -> None:
        self._summarize = summarizer
        self.max_tokens = max_tokens
        self.keep_recent = keep_recent

    @staticmethod
    def estimate_tokens(text: str) -> int:
        return max(1, len(text or "") // 4)   # rough chars/4 heuristic

    def _turn_tokens(self, turn: dict) -> int:
        return self.estimate_tokens(turn.get("content", ""))

    def _importance(self, turn: dict) -> float:
        c = turn.get("content", "") or ""
        score = min(1.0, len(c) / 400.0)        # longer = more content
        if "?" in c:
            score += 0.3                          # questions matter
        if turn.get("role") == "user":
            score += 0.1
        return score

    def _fallback_digest(self, older: "list[dict]") -> str:
        """Deterministic digest: the most important older turns, first sentence each."""
        ranked = sorted(older, key=self._importance, reverse=True)[:5]
        lines = []
        for t in ranked:
            first = re.split(r"(?<=[.!?])\s", (t.get("content", "") or "").strip())[0]
            lines.append(f"- {t.get('role', '')}: {first[:160]}")
        return "[summary of earlier conversation]\n" + "\n".join(lines)

    async def compress(self, turns: "list[dict]") -> dict:
        total = sum(self._turn_tokens(t) for t in (turns or []))
        if total <= self.max_tokens or len(turns or []) <= self.keep_recent:
            return {"compressed": False, "kept": list(turns or []),
                    "summary": "", "evicted": 0, "tokens": total}
        recent = turns[-self.keep_recent:]
        older = turns[:-self.keep_recent]
        block = "\n".join(f"{t.get('role', '')}: {t.get('content', '')}" for t in older)
        summary = ""
        if self._summarize is not None:
            try:
                summary = await self._summarize(block)
            except Exception:
                summary = ""
        if not summary:
            summary = self._fallback_digest(older)
        kept_tokens = sum(self._turn_tokens(t) for t in recent) + self.estimate_tokens(summary)
        return {"compressed": True, "kept": recent, "summary": summary,
                "evicted": len(older), "tokens": kept_tokens}
