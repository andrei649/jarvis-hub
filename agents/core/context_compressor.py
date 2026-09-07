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

Compaction policy (2026-09-06): the compressor had a budget but no *policy*, so a
24/7 run on a local 32–128k window died after about twenty screenshots. A policy
is what decides when to act and what to give up first, and every rule here is
chosen against a way of losing something that mattered:

* **Two tiers, not one threshold.** ``soft`` (0.6 of the window) drops what is
  cheap to lose; ``hard`` (0.85) summarises. A single threshold means the first
  compaction is always the aggressive one, which throws away detail that a
  cheaper move would have saved.
* **Images go first, and the accounting says so.** A screenshot is worth
  thousands of tokens and almost nothing after the turn it was taken in — the
  text that described what was seen survives it. Dropping images before touching
  any text is what makes a long operator run possible at all.
* **The head and the tail are never summarised.** The head is the session's
  original ask, and losing it is how a run drifts into doing something adjacent
  to what was requested. The tail is what is actually happening now.
* **Below soft, nothing changes at all.** Not "a cheap pass that usually no-ops"
  — byte-identical, because a compressor that rewrites a transcript it did not
  need to touch is a compressor nobody can debug.
* **A lineage row, or the compaction is unexplainable.** Each compaction emits
  ``{parent_session_id, summary_sha256, …}`` so a later reader can ask what a
  summary replaced. A summary with no provenance is a claim about a conversation
  nobody can check.
* **The tighter of the two bounds wins.** The owner's own token budget
  (``memory.compression_max_tokens``) still applies; a model window can only make
  compaction happen sooner, never later. Letting the window override the budget
  would make a shipped setting inert for anyone who had turned it down on purpose.
* **Per-model windows.** 32k and 200k are different products; one threshold in
  tokens would be wrong for both. The window is looked up per model with a
  conservative default, because guessing high is how a run gets truncated by the
  provider instead of by us — and that truncation takes the *tail*, which is the
  half we most need.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger("jarvis.context_compaction")

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



# Context windows, in tokens, for the models a local install actually runs. The
# default is deliberately the SMALLEST plausible window rather than an average:
# guessing high means the provider truncates instead of us, and a provider
# truncates the tail — which is the half that says what is happening now.
DEFAULT_WINDOW = 32_000
MODEL_WINDOWS: Mapping[str, int] = {
    "llama3": 8_192, "llama3.1": 128_000, "llama3.2": 128_000,
    "qwen2.5": 32_768, "qwen3": 32_768,
    "mistral": 32_768, "mixtral": 32_768,
    "gemma2": 8_192, "gemma3": 128_000,
    "phi3": 128_000, "phi4": 16_384,
    "deepseek-r1": 65_536, "command-r": 128_000,
}

# What an image costs, in the same units the rest of this module counts in. The
# figure is deliberately a floor: undercounting an image is how the accounting
# says a transcript fits when it does not.
IMAGE_TOKEN_COST = 1_500


def window_for(model: str | None) -> int:
    """The context window for a model name, matched on its family prefix.

    Unknown models get ``DEFAULT_WINDOW``, not a large guess: being wrong small
    costs a summarisation nobody needed; being wrong large costs the tail.
    """
    name = str(model or "").strip().lower()
    if not name:
        return DEFAULT_WINDOW
    # Longest prefix wins, so "llama3.1" is not matched by "llama3".
    for family in sorted(MODEL_WINDOWS, key=len, reverse=True):
        if name.startswith(family):
            return MODEL_WINDOWS[family]
    return DEFAULT_WINDOW


@dataclass(frozen=True)
class CompactionPolicy:
    """When to compact, and what to give up first.

    ``soft`` and ``hard`` are fractions of the model's window. Below ``soft``
    nothing happens; between them images are dropped; at or above ``hard`` the
    older text is summarised as well.
    """

    soft: float = 0.6
    hard: float = 0.85
    protect_head: int = 2
    protect_last_n: int = 6
    per_model: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, value in (("soft", self.soft), ("hard", self.hard)):
            if not 0.0 < float(value) <= 1.0:
                raise ValueError(f"{name} must be a fraction in (0, 1]")
        if float(self.soft) > float(self.hard):
            # A soft tier above the hard one would summarise before dropping
            # images — the expensive move before the cheap one, every time.
            raise ValueError("soft must not exceed hard")
        for name, value in (("protect_head", self.protect_head),
                            ("protect_last_n", self.protect_last_n)):
            if int(value) < 0:
                raise ValueError(f"{name} must not be negative")

    def window(self, model: str | None) -> int:
        name = str(model or "").strip().lower()
        for family, size in (self.per_model or {}).items():
            if name.startswith(str(family).lower()):
                return int(size)
        return window_for(name)

    def tier(self, used_tokens: int, model: str | None) -> str:
        """``"none"`` | ``"images"`` | ``"summarize"`` for a token count."""
        window = max(1, self.window(model))
        ratio = float(used_tokens) / float(window)
        if ratio >= float(self.hard):
            return "summarize"
        if ratio >= float(self.soft):
            return "images"
        return "none"


def _has_image(turn: Mapping[str, Any]) -> bool:
    if turn.get("image") or turn.get("image_base64") or turn.get("images"):
        return True
    content = turn.get("content")
    return isinstance(content, str) and content.startswith("data:image/")


def _strip_image(turn: Mapping[str, Any]) -> dict[str, Any]:
    """The same turn without its image, and honest about the hole.

    The placeholder is not decoration: a reader (or a later summariser) that sees
    a turn with no image and no note cannot tell whether one was dropped or never
    existed, and those are different conversations.
    """
    stripped = {k: v for k, v in turn.items() if k not in {"image", "image_base64", "images"}}
    content = stripped.get("content")
    if isinstance(content, str) and content.startswith("data:image/"):
        stripped["content"] = "[image dropped to fit the context window]"
    elif isinstance(content, str) and content:
        stripped["content"] = content + "\n[image dropped to fit the context window]"
    else:
        stripped["content"] = "[image dropped to fit the context window]"
    stripped["image_dropped"] = True
    return stripped


def lineage_row(
    *,
    session_id: str,
    summary: str,
    evicted: int,
    images_dropped: int,
    tier: str,
    model: str | None = None,
) -> dict[str, Any]:
    """What a compaction leaves behind so it can be explained later.

    A summary with no provenance is a claim about a conversation nobody can
    check. The hash is over the summary text, so a stored summary can be matched
    back to the row that recorded it even after the session is gone.
    """
    digest = hashlib.sha256((summary or "").encode("utf-8")).hexdigest()
    return {
        "schema": "nerva.context-compaction.v1",
        "parent_session_id": str(session_id or "")[:128],
        "summary_sha256": digest,
        "summary_chars": len(summary or ""),
        "evicted_turns": int(evicted),
        "images_dropped": int(images_dropped),
        "tier": tier,
        "model": str(model or "")[:64],
    }


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

    def _cost(self, turn: Mapping[str, Any]) -> int:
        """A turn's token cost, images included.

        Counting only the text is how the accounting says a transcript fits when
        it does not — which is the failure that ends a long operator run.
        """
        cost = self.estimate_tokens(str(turn.get("content", "") or ""))
        if _has_image(turn):
            cost += IMAGE_TOKEN_COST
        return cost

    async def compact(
        self,
        turns: "list[dict]",
        *,
        model: str | None = None,
        policy: CompactionPolicy | None = None,
        session_id: str = "",
        prior: Optional[dict] = None,
        sink: Callable[[dict], Any] | None = None,
    ) -> dict:
        """Fit a transcript into a model's window, giving up the cheapest thing first.

        Returns the compressor's own result shape plus ``tier``,
        ``images_dropped`` and ``lineage``, so a caller that only knows
        :meth:`compress` reads the same fields it always did.

        Below the soft threshold this returns the turns **byte-identical**: a
        compressor that rewrites a transcript it did not need to touch is one
        nobody can debug, and "usually a no-op" is not the same promise.
        """
        rows = list(turns or [])
        pol = policy or CompactionPolicy()
        used = sum(self._cost(t) for t in rows)
        tier = pol.tier(used, model)
        # The tighter of the two bounds wins. ``max_tokens`` is the owner's own
        # budget (``memory.compression_max_tokens``) and predates this policy;
        # letting the model's window silently override it would make a shipped
        # setting inert for anyone who had turned it down on purpose. A window
        # can only ever make compaction happen SOONER, never later.
        if self.max_tokens and used > self.max_tokens:
            tier = "summarize"
        if tier == "none" or not rows:
            return {
                "compressed": False, "kept": rows, "kept_first": [], "summary": "",
                "evicted": 0, "tokens": used, "covered": 0,
                "tier": "none", "images_dropped": 0, "lineage": None,
            }

        # ── tier one: images ─────────────────────────────────────────────
        # A screenshot is worth thousands of tokens and almost nothing after the
        # turn it was taken in; the text that described what was seen survives it.
        head = max(0, int(pol.protect_head))
        tail = max(0, int(pol.protect_last_n))
        dropped = 0
        working: list[dict] = []
        for index, turn in enumerate(rows):
            in_tail = index >= len(rows) - tail if tail else False
            if _has_image(turn) and not in_tail:
                # The most recent images are kept: they are what the next step is
                # about. Older ones have already been described in text.
                working.append(_strip_image(turn))
                dropped += 1
            else:
                working.append(dict(turn))
        used_after = sum(self._cost(t) for t in working)

        under_budget = not self.max_tokens or used_after <= self.max_tokens
        if tier == "images" or (under_budget and pol.tier(used_after, model) == "none"):
            row = lineage_row(
                session_id=session_id, summary="", evicted=0,
                images_dropped=dropped, tier="images", model=model,
            ) if dropped else None
            self._emit(sink, row)
            return {
                "compressed": bool(dropped), "kept": working, "kept_first": [],
                "summary": "", "evicted": 0, "tokens": used_after, "covered": 0,
                "tier": "images", "images_dropped": dropped, "lineage": row,
            }

        # ── tier two: summarise the middle ───────────────────────────────
        # The head is the session's original ask — losing it is how a run drifts
        # into doing something adjacent to what was requested — and the tail is
        # what is happening now. Neither is ever summarised.
        # compress() has its own budget check and would refuse a transcript that
        # is over the model's WINDOW but under the owner's token budget — the two
        # bounds disagreeing is how a compaction silently does nothing. So the
        # target for this call is the soft threshold: compact down to the tier
        # where the cheap moves are enough, not merely to the edge of the window.
        target = int(float(pol.soft) * pol.window(model))
        if self.max_tokens:
            target = min(target, self.max_tokens)
        previous = (self.keep_first, self.keep_recent, self.max_tokens)
        self.keep_first, self.keep_recent = head, max(1, tail)
        self.max_tokens = max(1, target)
        try:
            result = await self.compress(working, prior=prior)
        finally:
            self.keep_first, self.keep_recent, self.max_tokens = previous

        row = lineage_row(
            session_id=session_id, summary=result.get("summary", ""),
            evicted=int(result.get("evicted", 0)), images_dropped=dropped,
            tier="summarize", model=model,
        ) if (dropped or result.get("compressed")) else None
        self._emit(sink, row)
        return {**result, "tier": "summarize", "images_dropped": dropped, "lineage": row}

    @staticmethod
    def _emit(sink: Callable[[dict], Any] | None, row: dict | None) -> None:
        """Write the lineage row. A failing sink never fails a compaction: losing
        the record of what happened is bad, and losing the conversation is worse."""
        if sink is None or row is None:
            return
        try:
            sink(row)
        except Exception:
            logger.warning("context compaction lineage sink failed", exc_info=True)

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
        if kept_tokens >= total:
            # Salvage (hermes-agent salvage_grown_transcript, v2026.8.27): a
            # "compression" that grew the transcript — e.g. a rambling summary
            # over few/short evicted turns — must never replace the original.
            return {"compressed": False, "kept": list(turns), "kept_first": [],
                    "summary": "", "evicted": 0, "tokens": total, "covered": 0}
        return {"compressed": True, "kept": recent, "kept_first": first,
                "summary": summary, "evicted": len(older), "tokens": kept_tokens,
                "covered": len(older)}
