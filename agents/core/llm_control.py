"""llm_control.py — governed natural-language local-model lifecycle control.

Lets a chat message drive LM Studio or Ollama (start / load / unload / status).
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
import time
from typing import Optional

from .action_origin import DEFAULT_ACTION_ORIGIN, current_action_origin
from .automation_contracts import contract_denial
from .autonomy.remediation import HOST_CONTROL_CONTRACT, HOST_CONTROL_CONTRACT_KIND
from .kernel import Action, Verdict, kernel_enabled
from .kernel.binding import make_action_kernel
from .security.types import SecurityEvent, SecurityEventType

_LLM_PREFIX_RE = re.compile(
    r"^\s*(?P<provider>llm|lm[\s\-]?studio|ollama)\b[:\s]+(?P<rest>.+)$",
    re.IGNORECASE,
)
_MODEL_FAMILY_RE = re.compile(
    r"(gemma|qwen|deepseek|llama|mistral|mixtral|phi|gpt|granite|nemotron|smol|yi|command-?r|qwq)",
    re.IGNORECASE,
)
_LOAD_VERB_RE = re.compile(r"\b(load|reload|încarc|incarc|switch|schimb)\w*\b", re.IGNORECASE)
_START_RE = re.compile(r"\b(start|launch|boot|pornes\w*|porneșt\w*)\b", re.IGNORECASE)
_UNLOAD_RE = re.compile(r"\b(unload|descarc)\w*\b", re.IGNORECASE)
_LLM_NOUN_RE = re.compile(
    r"\b(lm[\s\-]?studio|ollama|llm|language model|model|brain|creier|server)\b",
    re.IGNORECASE,
)
_START_TARGET_RE = re.compile(
    r"\b(lm[\s\-]?studio|ollama|llm|language (?:model|server)|the server)\b",
    re.IGNORECASE,
)
_STATUS_RE = re.compile(
    r"\bwhat are you running\b"
    r"|\b(?:what|which|ce)\b[^?.!]{0,40}\b(?:llm|lm[\s\-]?studio|ollama|language model|ai model|brain|creier)\b"
    r"|\b(?:what|which|ce)\b[^?.!]{0,30}\bmodel\b[^?.!]{0,30}\b(?:you|run|running|loaded|using|use|rulez\w*|folos\w*|încărc\w*|incarc\w*|activ)\b"
    r"|\bmodel\b[^?.!]{0,20}\b(?:loaded|running|active|încărcat|incarcat)\b",
    re.IGNORECASE,
)
_MODEL_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/:@\-]{1,199}")
_MODEL_ID_RE = re.compile(r"^[A-Za-z0-9._/:@\-]{1,200}$")
_MODEL_STOPWORDS = {
    "the", "a", "an", "model", "models", "modelul", "modele", "up", "please", "sir",
    "to", "into", "my", "our", "your", "new", "llm", "lm", "studio", "lmstudio",
    "load", "reload", "unload", "switch", "use", "start", "server", "ollama", "and", "test",
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


def _action_for(provider: str, verb: str) -> str:
    """Keep the legacy LM Studio action names while naming Ollama explicitly."""
    return f"ollama.{verb}" if provider.lower() == "ollama" else verb


def _provider_for_text(text: str) -> str:
    return "ollama" if re.search(r"\bollama\b", text, re.IGNORECASE) else "lmstudio"


def detect_llm_control(text: str) -> Optional[tuple[str, Optional[str]]]:
    """Detect a chat request to control the LLM backend.

    Returns ``(action, model)``. Legacy LM Studio actions remain ``status`` /
    ``start`` / ``load`` / ``unload``; explicit Ollama requests use
    ``ollama.<action>``. ``model`` is optional. Returns ``None`` for ordinary
    conversation.
    """
    if not text or not text.strip():
        return None
    t = text.strip()

    # Explicit "llm <sub> [args]" / "lm studio <sub>" command form.
    m = _LLM_PREFIX_RE.match(t)
    if m:
        provider = m.group("provider").lower()
        rest = m.group("rest").strip()
        sub, _, arg = rest.partition(" ")
        sub = sub.lower()
        if sub in ("status", "state", "ps", "info"):
            return (_action_for(provider, "status"), None)
        if sub in ("start", "up", "boot", "launch"):
            return (_action_for(provider, "start"), None)
        if sub in ("unload", "stop"):
            return (_action_for(provider, "unload"), _extract_model(arg))
        if sub in ("load", "use", "switch"):
            return (_action_for(provider, "load"), _extract_model(arg))
        # Unknown sub-command: only act if it names a model ("llm gemma"),
        # otherwise let normal chat handle it (avoids "lm studio is great").
        model = _extract_model(rest)
        return (_action_for(provider, "load"), model) if model else None

    low = t.lower()

    if _UNLOAD_RE.search(low):
        model = _extract_model(low)
        if model or _LLM_NOUN_RE.search(low):
            return (_action_for(_provider_for_text(low), "unload"), model)

    if _START_RE.search(low) and _START_TARGET_RE.search(low):
        return (_action_for(_provider_for_text(low), "start"), None)

    if _LOAD_VERB_RE.search(low):
        model = _extract_model(low)
        if model and (_LLM_NOUN_RE.search(low) or _is_plausible_model(model)):
            return (_action_for(_provider_for_text(low), "load"), model)

    if _STATUS_RE.search(low):
        return (_action_for(_provider_for_text(low), "status"), None)

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


def _decode_action(action: str) -> tuple[str, str]:
    if str(action).startswith("ollama."):
        return "ollama", str(action).split(".", 1)[1]
    return "lmstudio", str(action)


def authorize_local_model_lifecycle(
    orch,
    provider: str,
    verb: str,
    model: Optional[str],
    *,
    channel: str,
    kernel=None,
) -> Optional[str]:
    """Return a refusal reason, or durably authorize one lifecycle effect.

    Enforcement order is identity (for MCP) → permission → host contract →
    Action Kernel explicit GRANT → durable audit preflight.  The controller is
    called only after this function returns ``None``.
    """
    if channel == "mcp":
        try:
            from .mcp.server import current_mcp_agent_request_authorized

            mcp_authorized = current_mcp_agent_request_authorized()
        except Exception:
            mcp_authorized = False
        if not mcp_authorized:
            return "authenticated MCP owner authority is required"

    gate = getattr(orch, "permission_gate", None)
    check_call = getattr(gate, "check_call", None)
    if not callable(check_call):
        return "system-control permission gate is unavailable"
    try:
        if not check_call("system-control", "jarvis"):
            return "Jarvis is not permitted to use system-control"
    except Exception:
        return "system-control permission gate is unavailable"

    contract_action = f"{provider}.{verb}"
    try:
        cdec = HOST_CONTROL_CONTRACT.evaluate({
            "kind": HOST_CONTROL_CONTRACT_KIND,
            "action": contract_action,
            "agent": "jarvis",
            "provider": provider,
            "model": model or "",
            "target": model or provider,
        })
    except Exception:
        return "host-control contract is unavailable"
    blocked = contract_denial(cdec)
    if blocked:
        return f"host-control contract denied: {blocked}"

    # This privileged path is stricter than legacy chat control: disabled,
    # unbound, raising, DENY and QUEUE all stop before the durable audit/effect.
    if not kernel_enabled():
        return "Action Kernel is required for local model lifecycle control"
    kernel = kernel or make_action_kernel(orch)
    if not callable(kernel):
        return "Action Kernel is unavailable for local model lifecycle control"
    origin = DEFAULT_ACTION_ORIGIN if channel == "mcp" else current_action_origin()
    try:
        decision = kernel(Action(
            kind=HOST_CONTROL_CONTRACT_KIND,
            agent="jarvis",
            title=f"{contract_action} {model or ''}".strip(),
            payload={
                "provider": provider,
                "action": contract_action,
                "model": model or "",
                "target": model or provider,
                "risk_tier": 1,
                "reversible": True,
            },
            origin=origin,
        ))
    except Exception:
        return "Action Kernel is unavailable for local model lifecycle control"
    if decision.verdict is Verdict.QUEUE:
        return f"approval required: {decision.reason or 'Action Kernel queued the action'}"
    if decision.verdict is not Verdict.GRANT:
        return f"Action Kernel denied the action: {decision.reason or 'denied'}"

    audit = getattr(orch, "audit", None)
    log = getattr(audit, "log", None)
    if not callable(log):
        return "durable lifecycle audit is unavailable"
    try:
        log(SecurityEvent(
            event_type=SecurityEventType.AUDIT_LOG,
            timestamp=time.time(),
            findings=[],
            content_preview=(
                "local model lifecycle keys=action,model,provider,target"
            ),
            action_taken=f"{contract_action} authorized before effect",
        ))
    except Exception:
        return "durable lifecycle audit rejected the authorization row"
    return None


async def run_llm_control(
    orch,
    action: str,
    model: Optional[str],
    *,
    channel: str = "internal",
) -> Optional[str]:
    """Govern, execute and honestly narrate a local-model lifecycle request."""
    provider, verb = _decode_action(action)
    ctrl = getattr(orch, provider, None)
    display = "Ollama" if provider == "ollama" else "LM Studio"
    if ctrl is None:
        return f"{display} control is not available, sir."
    router = getattr(orch, "llm_router", None)
    backend = getattr(router, "name", None) or "the local backend"

    if verb == "status":
        st = await ctrl.status()
        if not st.get("online"):
            return f"{display} is offline, sir. Say 'start {display}' and I will bring it up."
        if provider == "ollama":
            active = st.get("active_models")
            if active is None:
                reason = st.get("reason") or "active model inventory is unavailable"
                return (
                    "Ollama is online, but I could not verify which models are "
                    f"resident, sir — {reason}."
                )
            names = ", ".join(active) if active else "no model currently resident"
            return f"Ollama is online with {names}, sir."
        # Report the model ACTUALLY loaded now. A model loaded directly in LM Studio
        # (outside Nerva) leaves `router.active_model` at the configured default, so
        # `status()` narrated a stale model in chat while the HUD badge was correct
        # (2026-07-24 QA finding). Re-fetch live residency first; fall back to the
        # cached value only if the refresh is unavailable/fails.
        live = None
        refresh = getattr(router, "refresh_active_model", None)
        if callable(refresh):
            try:
                live = await refresh()
            except Exception:
                live = None
        name = live or st.get("active_model") or getattr(router, "active_model", None) or "an unidentified model"
        return f"I am running {name} on {backend}, sir."

    if verb not in {"start", "load", "unload"}:
        return None
    if verb == "load" and not model:
        return "Which model would you like me to load, sir?"
    if model and not _MODEL_ID_RE.fullmatch(model):
        return f"That is not a valid model id, sir: {model!r}."

    # Ollama exposes unload-all as one intent but implements it as one HTTP effect
    # per resident model.  Inventory must be completely valid before the first
    # mutation, and every target gets fresh live authority immediately before its
    # own effect.  This also makes any partial result explicit instead of claiming
    # an atomic batch that the Ollama API does not provide.
    if provider == "ollama" and verb == "unload" and model is None:
        inventory = getattr(ctrl, "active_models", None)
        if not callable(inventory):
            return "I could not unload Ollama, sir — active model inventory is unavailable."
        try:
            targets = await inventory()
        except Exception:
            return "I could not unload Ollama, sir — active model inventory is unavailable."
        if not targets:
            return "Ollama has no resident models to unload, sir."

        unloaded: list[str] = []
        for target in targets:
            denied = authorize_local_model_lifecycle(
                orch, provider, verb, target, channel=channel
            )
            if denied:
                completed = ", ".join(unloaded) or "none"
                return (
                    f"I unloaded {completed}, but stopped before {target}, sir — "
                    f"{denied}."
                )
            res = await ctrl.unload_model(target, agent="jarvis")
            if res.get("status") != "ok":
                completed = ", ".join(unloaded) or "none"
                reason = res.get("reason") or "the unload failed"
                return (
                    f"I unloaded {completed}, but could not unload {target}, sir — "
                    f"{reason}."
                )
            unloaded.append(target)
        return f"All models unloaded, sir: {', '.join(unloaded)}."

    # Loading an offline provider is a composite request with two distinct host
    # effects. Authorize/audit/start first, then re-run every live gate for load.
    # Controllers refuse to auto-start on their own so no direct call can collapse
    # those effects behind a single kernel decision or audit row.
    if verb == "load":
        try:
            server_state = await ctrl.status()
        except Exception:
            return (
                f"I could not load {model}, sir — {display} server status is unavailable."
            )
        if not server_state.get("online"):
            start_denied = authorize_local_model_lifecycle(
                orch, provider, "start", None, channel=channel
            )
            if start_denied:
                return f"I could not load {model}, sir — {start_denied}."
            started = await ctrl.start_server(agent="jarvis")
            if started.get("status") != "ok":
                reason = started.get("reason") or "the server did not come up"
                return f"I could not load {model}, sir — {reason}."

    denied = authorize_local_model_lifecycle(
        orch, provider, verb, model, channel=channel
    )
    if denied:
        return f"I could not {verb} {display}, sir — {denied}."

    if verb == "start":
        res = await ctrl.start_server(agent="jarvis")
        if res.get("status") == "ok":
            return (f"{display} is already running, sir." if res.get("already_running")
                    else f"{display} is up, sir.")
        return f"I could not start {display}, sir — {res.get('reason') or 'the server did not come up'}."

    if verb == "load":
        res = await ctrl.load_model(model, agent="jarvis")
        status = res.get("status")
        if status == "ok":
            active = (res.get("model") or
                      (getattr(router, "active_model", None) if provider == "lmstudio" else None)
                      or model)
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

    if verb == "unload":
        res = await ctrl.unload_model(model, agent="jarvis")
        if res.get("status") == "ok":
            return "Unloaded, sir." if model else "All models unloaded, sir."
        return f"I could not unload, sir — {res.get('reason') or 'the unload failed'}."

    return None
