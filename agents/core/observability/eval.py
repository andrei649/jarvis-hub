"""
eval.py — H9.3 Offline Eval Harness.

Fully offline-testable: inject a fake async runner in tests, the real
orchestrator.handle_input in production.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger("jarvis.eval")


@dataclass
class EvalCase:
    """A single evaluation case.

    Parameters
    ----------
    name:
        Human-readable case identifier.
    prompt:
        The input text to send to the runner.
    expect_contains:
        If set, the response must contain this substring (case-insensitive) to
        pass.  Takes precedence over *scorer* for the binary pass/fail flag.
    scorer:
        A callable ``(prompt, response) -> float`` in ``[0, 1]``.  Used when
        *expect_contains* is None.  A score >= 0.5 is treated as passing.
    """

    name: str
    prompt: str
    expect_contains: Optional[str] = None
    scorer: Optional[Callable[[str, str], float]] = None
    metadata: dict = field(default_factory=dict)


class EvalHarness:
    """Run a suite of EvalCases against an async runner.

    Parameters
    ----------
    runner:
        ``async (prompt: str) -> str`` callable.  In production pass
        ``orchestrator.handle_input``; in tests pass a simple fake.
    """

    def __init__(self, runner: Callable[[str], Awaitable[str]]) -> None:
        self.runner = runner

    async def run(self, cases: list[EvalCase]) -> dict[str, Any]:
        """Execute all cases and return an aggregate result dict.

        Returns
        -------
        {
            "results": [{"name", "passed", "score", "response"}, ...],
            "passed":  int,
            "total":   int,
            "score":   float,   # mean score across all cases
        }
        """
        results = []
        for case in cases:
            try:
                response = await self.runner(case.prompt)
            except Exception:
                logger.exception("eval runner execution failed")
                response = "[runner error]"

            passed, score = self._evaluate(case, response)
            results.append(
                {
                    "name": case.name,
                    "passed": passed,
                    "score": score,
                    "response": response,
                }
            )

        total = len(results)
        passed_count = sum(1 for r in results if r["passed"])
        mean_score = (
            sum(r["score"] for r in results) / total if total else 0.0
        )
        return {
            "results": results,
            "passed": passed_count,
            "total": total,
            "score": mean_score,
        }

    # ── private ────────────────────────────────────────────────────────────

    @staticmethod
    def _evaluate(case: EvalCase, response: str) -> tuple[bool, float]:
        """Return (passed, score) for a single case."""
        if case.expect_contains is not None:
            passed = case.expect_contains.lower() in response.lower()
            score = 1.0 if passed else 0.0
            return passed, score

        if case.scorer is not None:
            try:
                score = float(case.scorer(case.prompt, response))
                score = max(0.0, min(1.0, score))
            except Exception:
                score = 0.0
            passed = score >= 0.5
            return passed, score

        # No criterion — pass by default (useful as a smoke test).
        return True, 1.0
