"""llm_synth.py — strict-local LLM callables for H32 capability synthesis.

``StrictLocalGenerator`` (generator.py) and ``GovernedResearch`` (research.py)
take an injected ``generate``/``draft`` callable by design — the strict-local
LLM call is deliberately kept OUT of those modules so the validation boundary
(AST/allowlist checks, the ``ground_plan()`` citation gate) stays independent
of any specific model. This module is the concrete strict-local implementation
of those two seams: it prompts ``LLMRouter.local_backend`` (never a cloud
fallback — fail-closed, matching the "strict-local" route both callers
require) and parses its JSON reply into the exact shape downstream expects.

It adds NO new trust. Every constraint the validators already enforce still
applies to whatever the model returns — a malformed or unsafe reply is simply
rejected downstream (``GenerationError`` / ``ResearchError``), same as the
hand-written fixtures these callables replace.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger("jarvis.acquisition.llm_synth")

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_MAX_ATTEMPTS = 2


class SynthesisError(RuntimeError):
    """The strict-local model failed to produce a usable JSON reply."""


def _extract_json(text: str) -> Any:
    """Best-effort JSON extraction: the raw reply, then its first fenced block."""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass
    match = _JSON_FENCE.search(text)
    if match:
        return json.loads(match.group(1).strip())
    raise ValueError("no JSON found in model output")


def _model_name(router) -> str:
    return getattr(router, "active_model", None) or "local"


async def generate_capability(prompt: dict, *, router) -> dict:
    """``StrictLocalGenerator``'s ``generate`` callable — strict-local, JSON-only.

    ``prompt`` is StrictLocalGenerator's own system-built prompt dict (goal,
    entrypoint, contract_hash, plan_hash, requirements) — never model-authored.
    The system prompt restates the constraints the AST validator enforces so
    the model is steered toward passing on the first try; ``StrictLocalGenerator``
    re-validates everything regardless (stdlib-only imports, forbidden calls,
    no placeholder body, secret/PII scan), so nothing here is trusted on its own.
    """
    backend = router.local_backend
    model = _model_name(router)
    requirements = "; ".join(str(item) for item in (prompt.get("requirements") or []))
    system = (
        "You write a single Python capability package for a sandboxed, "
        "stdlib-only execution environment. Reply with ONLY a JSON object "
        '(no prose, no markdown fences) with exactly these keys: "name" (a '
        'short lowercase_with_underscores identifier), "entrypoint" (must be '
        f'exactly "{prompt.get("entrypoint")}"), "code" (the implementation '
        'module source, defining the entrypoint function), "test" (a unittest '
        "module that imports the entrypoint from `main` and asserts real "
        f"behavior on concrete inputs). Hard requirements: {requirements}. "
        "The entrypoint function body must be a genuine implementation — "
        "never just `pass` or `raise NotImplementedError`."
    )
    user = json.dumps(prompt, ensure_ascii=False, sort_keys=True)

    last_error: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        raw = await backend.generate(
            model, user, system=system, max_tokens=2048,
            temperature=0.2 if attempt == 0 else 0.0,
        )
        try:
            parsed = _extract_json(raw)
        except ValueError as exc:
            last_error = exc
            logger.warning("capability synthesis: model reply was not JSON (attempt %d)", attempt + 1)
            continue
        if not isinstance(parsed, dict):
            last_error = ValueError("model reply was not a JSON object")
            continue
        return parsed
    raise SynthesisError(f"strict-local capability generation failed: {last_error}")


async def draft_plan(goal: str, references: list[dict], *, router) -> list[dict]:
    """``GovernedResearch``'s ``draft`` callable — strict-local, JSON-only.

    ``references`` are the already-fetched, injection-scanned, PII/secret-redacted
    sources ``GovernedResearch`` collected (research.py) — the model only ever
    sees what already passed those checks. Its output steps are re-validated by
    ``ground_plan()`` regardless: an invented reference id is surfaced as an
    unknown citation, never silently trusted.
    """
    backend = router.local_backend
    model = _model_name(router)
    catalog = [
        {"id": ref.get("id"), "title": ref.get("title"), "url": ref.get("url")}
        for ref in references
    ]
    system = (
        "You draft an implementation plan grounded ONLY in the numbered "
        "references you are given. Reply with ONLY a JSON array (no prose, "
        "no markdown fences) of step objects, each with a \"text\" field (one "
        'concrete step) and a "cites" field (a list of reference ids from the '
        "catalog that support that step). Every step must cite at least one "
        "reference id from the catalog; never invent an id that is not in it."
    )
    user = json.dumps({"goal": goal, "references": catalog}, ensure_ascii=False, sort_keys=True)

    last_error: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        raw = await backend.generate(
            model, user, system=system, max_tokens=1024,
            temperature=0.2 if attempt == 0 else 0.0,
        )
        try:
            parsed = _extract_json(raw)
        except ValueError as exc:
            last_error = exc
            logger.warning("research draft: model reply was not JSON (attempt %d)", attempt + 1)
            continue
        if not isinstance(parsed, list):
            last_error = ValueError("model reply was not a JSON array")
            continue
        return parsed
    raise SynthesisError(f"strict-local research draft failed: {last_error}")


__all__ = ["SynthesisError", "generate_capability", "draft_plan"]
