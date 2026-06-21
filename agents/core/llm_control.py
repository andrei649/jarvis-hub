"""llm_control.py — natural-language LLM-backend control detection (CLN-2).

Lets a chat message drive LMStudioController (start / load / unload / status).
Deliberately conservative: a load needs a *plausible* model token, so ordinary
phrases like "load up our friends and test them" never trigger a model load.
Status questions that slip through still get answered truthfully by the normal
chat path (the runtime state block injects the real model), so missing one here
is harmless.

Extracted from orchestrator.py; `detect_llm_control` is re-exported there for
back-compat (tests import it from `core.orchestrator`, and the request lifecycle
calls it).
"""

from __future__ import annotations

import re
from typing import Optional

_LLM_PREFIX_RE = re.compile(r"^\s*(?:llm|lm[\s\-]?studio)\b[:\s]+(.+)$", re.IGNORECASE)
_MODEL_FAMILY_RE = re.compile(
    r"(gemma|qwen|deepseek|llama|mistral|mixtral|phi|gpt|granite|nemotron|smol|yi|command-?r|qwq)",
    re.IGNORECASE,
)
_LOAD_VERB_RE = re.compile(r"\b(load|reload|încarc|incarc|switch|schimb)\w*\b", re.IGNORECASE)
_START_RE = re.compile(r"\b(start|launch|boot|pornes\w*|porneșt\w*)\b", re.IGNORECASE)
_UNLOAD_RE = re.compile(r"\b(unload|descarc)\w*\b", re.IGNORECASE)
_LLM_NOUN_RE = re.compile(r"\b(lm[\s\-]?studio|llm|language model|model|brain|creier|server)\b", re.IGNORECASE)
_START_TARGET_RE = re.compile(r"\b(lm[\s\-]?studio|llm|language (?:model|server)|the server)\b", re.IGNORECASE)
_STATUS_RE = re.compile(
    r"\bwhat are you running\b"
    r"|\b(?:what|which|ce)\b[^?.!]{0,40}\b(?:llm|lm[\s\-]?studio|language model|ai model|brain|creier)\b"
    r"|\b(?:what|which|ce)\b[^?.!]{0,30}\bmodel\b[^?.!]{0,30}\b(?:you|run|running|loaded|using|use|rulez\w*|folos\w*|încărc\w*|incarc\w*|activ)\b"
    r"|\bmodel\b[^?.!]{0,20}\b(?:loaded|running|active|încărcat|incarcat)\b",
    re.IGNORECASE,
)
_MODEL_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/:@\-]{1,199}")
_MODEL_STOPWORDS = {
    "the", "a", "an", "model", "models", "modelul", "modele", "up", "please", "sir",
    "to", "into", "my", "our", "your", "new", "llm", "lm", "studio", "lmstudio",
    "load", "reload", "unload", "switch", "use", "start", "server", "and", "test",
    "them", "on", "with", "running", "loaded", "active", "now", "current", "default",
}


def _is_plausible_model(tok: str) -> bool:
    """A model id either looks structured (digit / path / quant) or names a known family."""
    return bool(re.search(r"[0-9/:@]", tok) or _MODEL_FAMILY_RE.search(tok))


def _extract_model(s: str) -> Optional[str]:
    for tok in _MODEL_TOKEN_RE.findall(s or ""):
        if tok.lower() in _MODEL_STOPWORDS:
            continue
        if _is_plausible_model(tok):
            return tok
    return None


def detect_llm_control(text: str) -> Optional[tuple[str, Optional[str]]]:
    """Detect a chat request to control the LLM backend.

    Returns (action, model) where action ∈ {status, start, load, unload} and
    model is an optional id, or None if the message is not LLM control.
    """
    if not text or not text.strip():
        return None
    t = text.strip()

    # Explicit "llm <sub> [args]" / "lm studio <sub>" command form.
    m = _LLM_PREFIX_RE.match(t)
    if m:
        rest = m.group(1).strip()
        sub, _, arg = rest.partition(" ")
        sub = sub.lower()
        if sub in ("status", "state", "ps", "info"):
            return ("status", None)
        if sub in ("start", "up", "boot", "launch"):
            return ("start", None)
        if sub in ("unload", "stop"):
            return ("unload", _extract_model(arg))
        if sub in ("load", "use", "switch"):
            return ("load", _extract_model(arg))
        # Unknown sub-command: only act if it names a model ("llm gemma"),
        # otherwise let normal chat handle it (avoids "lm studio is great").
        model = _extract_model(rest)
        return ("load", model) if model else None

    low = t.lower()

    if _UNLOAD_RE.search(low):
        model = _extract_model(low)
        if model or _LLM_NOUN_RE.search(low):
            return ("unload", model)

    if _START_RE.search(low) and _START_TARGET_RE.search(low):
        return ("start", None)

    if _LOAD_VERB_RE.search(low):
        model = _extract_model(low)
        if model and (_LLM_NOUN_RE.search(low) or _is_plausible_model(model)):
            return ("load", model)

    if _STATUS_RE.search(low):
        return ("status", None)

    return None


def control_cognition(action: str) -> dict:
    """The cognition trace stamped on `orch.last_cognition` when a turn was served
    by LLM control instead of the normal scoring/routing path (so the HUD shows a
    truthful one-step decision rather than fabricated agent scoring)."""
    return {
        "scoring": [],
        "decision": {"source": "llm-control", "confidence": 1.0,
                     "agents_selected": ["jarvis"], "alternatives": [],
                     "timing": {"classify": 0, "route": 0, "total": 0}},
        "trace": [{"step": "llm_control", "duration_ms": 0, "result": action}],
    }


async def run_llm_control(orch, action: str, model: Optional[str]) -> Optional[str]:
    """Execute a detected LLM-control action via the controller and narrate the
    real result in Jarvis's voice — it reflects what actually happened, not
    theatre. Reads `orch.lmstudio` (the LMStudioController) and `orch.llm_router`.
    """
    ctrl = getattr(orch, "lmstudio", None)
    if ctrl is None:
        return "LM Studio control is not available, sir."
    router = getattr(orch, "llm_router", None)
    backend = getattr(router, "name", None) or "the local backend"

    if action == "status":
        st = await ctrl.status()
        if not st.get("online"):
            return "The language backend is offline, sir. Say 'start LM Studio' and I will bring it up."
        name = st.get("active_model") or getattr(router, "active_model", None) or "an unidentified model"
        return f"I am running {name} on {backend}, sir."

    if action == "start":
        res = await ctrl.start_server()
        if res.get("status") == "ok":
            return "LM Studio is already running, sir." if res.get("already_running") else "LM Studio is up, sir."
        return f"I could not start LM Studio, sir — {res.get('reason') or 'the server did not come up'}."

    if action == "load":
        if not model:
            return "Which model would you like me to load, sir?"
        res = await ctrl.load_model(model)
        status = res.get("status")
        if status == "ok":
            active = getattr(router, "active_model", None) or res.get("model") or model
            if res.get("resolved_from"):
                return f"I matched '{res['resolved_from']}' to {active} and loaded it, sir."
            return f"Loaded and running {active}, sir."
        if status == "ambiguous":
            cands = res.get("candidates") or []
            shown = ", ".join(cands[:6])
            return (f"Several models match '{model}', sir: {shown}. "
                    "Which one shall I load?")
        if status == "rejected":
            return f"That is not a valid model id, sir: {model!r}."
        return f"I could not load {model}, sir — {res.get('reason') or 'the load failed'}."

    if action == "unload":
        res = await ctrl.unload_model(model)
        if res.get("status") == "ok":
            return "Unloaded, sir." if model else "All models unloaded, sir."
        return f"I could not unload, sir — {res.get('reason') or 'the unload failed'}."

    return None
