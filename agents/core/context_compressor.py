"""
context_compressor.py — H20.3 Runtime context compression (+ hermes Phase 2).

For long sessions, keep the recent turns verbatim and **intelligently evict**
the older ones — summarizing them (via an injectable summarizer, deferred LLM)
or, offline, keeping the most important older turns as a deterministic digest.
This is the *hot-path* compressor (distinct from the nightly consolidation of
H5.15); it ties into the "sleep-time compute" theme. Pure and offline-testable;
the LLM summarizer is injected.

Phase 2 (hermes migration, 2026-07-07 — all opt-in, defaults byte-identical):
``keep_first`` protects the leading turns verbatim (the session's original ask
survives every eviction); ``structured=True`` wraps the evicted transcript in
hermes's Historical context / Pending asks / Remaining work summary template
before calling the summarizer; ``compress(..., prior=...)`` merges a previous
compression's summary so the summarizer only reads turns it hasn't seen yet
(iterative summary-merge). A summarizer failure always degrades to the
deterministic digest over the FULL older window — nothing is silently lost.
"""

from __future__ import annotations

import re
from typing import Awaitable, Callable, Optional

# Hermes's structured carry-over template (background: agent/context_compressor.py
# in hermes-agent, MIT). The three sections keep a merged summary stable across
# repeated compressions instead of drifting into free prose.
SUMMARY_PROMPT = """Summarize the earlier conversation so it can be carried forward as context.
Structure the summary EXACTLY as three short sections:
Historical context: <what was discussed / established>
Pending asks: <questions or requests not yet answered>
Remaining work: <tasks agreed but not yet done>
Do not invent details. Keep it under 150 words total.
{prior_block}Conversation to fold in:
{block}"""


class ContextCompressor:
    """Token-budgeted compression: keep recent turns, digest/summarize the rest."""

    def __init__(self, summarizer: Optional[Callable[[str], Awaitable[str]]] = None,
                 max_tokens: int = 2000, keep_recent: int = 4,
                 keep_first: int = 0, structured: bool = False) -> None:
        self._summarize = summarizer
        self.max_tokens = max_tokens
        self.keep_recent = keep_recent
        self.keep_first = max(0, int(keep_first))
        self.structured = structured

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

    @staticmethod
    def _block(turns: "list[dict]") -> str:
        return "\n".join(f"{t.get('role', '')}: {t.get('content', '')}" for t in turns)

    def _summarizer_input(self, new_older: "list[dict]", prior_summary: str) -> str:
        block = self._block(new_older)
        if self.structured:
            prior_block = (f"Previous summary (fold it in, do not repeat verbatim):\n"
                           f"{prior_summary}\n" if prior_summary else "")
            return SUMMARY_PROMPT.format(prior_block=prior_block, block=block)
        if prior_summary:
            return f"[previous summary]\n{prior_summary}\n{block}"
        return block

    async def compress(self, turns: "list[dict]", prior: Optional[dict] = None) -> dict:
        total = sum(self._turn_tokens(t) for t in (turns or []))
        protected = self.keep_first + self.keep_recent
        if total <= self.max_tokens or len(turns or []) <= protected:
            return {"compressed": False, "kept": list(turns or []), "kept_first": [],
                    "summary": "", "evicted": 0, "tokens": total, "covered": 0}
        first = turns[:self.keep_first]
        recent = turns[-self.keep_recent:]
        older = turns[self.keep_first:-self.keep_recent]

        # Iterative merge: a valid prior summary lets the summarizer read only
        # the older turns it hasn't folded in yet. A stale prior (history was
        # cleared/shrank so `covered` overshoots) is discarded, not trusted.
        prior_summary, covered = "", 0
        if isinstance(prior, dict):
            c = int(prior.get("covered", 0) or 0)
            s = str(prior.get("summary", "") or "")
            if s and 0 < c <= len(older):
                prior_summary, covered = s, c
        new_older = older[covered:]

        summary = ""
        if self._summarize is not None:
            try:
                summary = await self._summarize(
                    self._summarizer_input(new_older, prior_summary))
            except Exception:
                summary = ""
        if not summary:
            # Fallback covers ALL older turns: the prior (possibly LLM-written)
            # summary can't be merged deterministically, so recompute from scratch.
            summary = self._fallback_digest(older)
        kept_tokens = (sum(self._turn_tokens(t) for t in first)
                       + sum(self._turn_tokens(t) for t in recent)
                       + self.estimate_tokens(summary))
        return {"compressed": True, "kept": recent, "kept_first": first,
                "summary": summary, "evicted": len(older), "tokens": kept_tokens,
                "covered": len(older)}
