"""H227 — "what can it do right now": one read-only answer for an agent and a principal.

Hermes shows it as a status line plus a session panel: the model and its state, the tools
the turn is offered, the skills the prompt names, the resolved system prompt and the MCP
servers. Nerva had the pieces apart — the raw ToolRPC registry, the MCP admin list,
``nerva prompt-size`` over files on disk — and nothing that answered *for this agent, on
this surface, for this principal*. :func:`build_inspector` does, from the code a turn runs:

- **status** — version, the backend and model the router serves, the local model's state
  (``project_llm_status``), the transcript budget ``llm.tool_loop_context_tokens``, whether
  the tool loop is on, safe mode;
- **tools** — the offer the tool runtime resolves for the agent under the view's principal
  (job toolset, posture, the agent's ``tools:`` list, the shared-session rule), not the
  registry; each row says whether it is gated and whether its output is fenced as
  untrusted. With the loop off the model is offered none of them: the rows are what the
  posture would offer once it is on, and ``loop_enabled`` says which is the case;
- **skills** — the rows ``prompt_catalog`` gives the prompt under that principal and that
  offer (a skill that needs a tool the turn lacks is not named);
- **mcp** — each server's transport, trust tier, transport-aware liveness and visible
  tools (no endpoint, no command line: those can carry credentials);
- **system_prompt** — the agent's system prompt and the user part ``Agent.build_prompt``
  would send for an empty user turn: persona, agent context, the core-memory block, the
  runtime/language/grounding rails, the skills block. Per-turn material (history, plugin
  data, recall, a checkpoint) is not there, because there is no turn; ``tokens`` estimates
  what that fixed part costs every turn. Secrets are masked by the log redactor (nothing is
  shown if it cannot load) and the two texts together are capped at
  :data:`PROMPT_CAP_BYTES`.

**Views** name the five postures of ``tool_profiles``: the owner on the HUD (``owner``), a
guest on the HUD (``guest``), the owner and a stranger on an external channel
(``inbound-owner``, ``inbound`` — Telegram stands for every external channel) and no human
at all (``internal``: a job, a heartbeat).

**No side effects.** The work runs in a task of its own, so the principal and origin it
binds — and the turn offer the runtime notes — end with it. The core-memory block is shown
without being frozen: it is rendered once per session and day and then kept for the prompt
cache, and a look must not be what fixes the day's snapshot.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from agents.core.action_origin import (
    DEFAULT_ACTION_ORIGIN,
    INBOUND_ACTION_ORIGIN,
    bind_action_origin,
)
from agents.core.commands import Principal

logger = logging.getLogger("jarvis.inspector")

#: view → (the principal bound for the look, the action origin), in tool_profiles' order.
VIEWS: dict[str, tuple[Principal, str]] = {
    "owner": (Principal(channel="web", admin=True), DEFAULT_ACTION_ORIGIN),
    "guest": (Principal(channel="web", admin=False), DEFAULT_ACTION_ORIGIN),
    "inbound-owner": (Principal(channel="telegram", admin=True), INBOUND_ACTION_ORIGIN),
    "inbound": (Principal(channel="telegram", admin=False), INBOUND_ACTION_ORIGIN),
    "internal": (Principal(), DEFAULT_ACTION_ORIGIN),
}
SECTIONS = ("status", "tools", "skills", "mcp", "system_prompt")
PROMPT_CAP_BYTES = 64 * 1024
DESCRIPTION_CHARS = 160
MAX_MCP_TOOL_NAMES = 50

Inventory = Callable[[], Awaitable[dict]]

_REDACTOR: Any = None


def _redactor():
    """The log redactor, loaded once; None when it cannot load (then no prompt is shown)."""
    global _REDACTOR
    if _REDACTOR is None:
        try:
            from agents.core.security.log_redaction import SecretRedactionFilter

            _REDACTOR = SecretRedactionFilter()
        except Exception:
            logger.warning("the secret redactor could not be loaded; the inspector shows no prompt",
                           exc_info=True)
            return None
    return _REDACTOR


def _wanted(sections: Iterable[str] | None) -> tuple[str, ...]:
    if sections is None:
        return SECTIONS
    asked = list(sections)
    unknown = [s for s in asked if s not in SECTIONS]
    if unknown:
        raise ValueError(f"unknown section: {', '.join(map(str, unknown))}")
    return tuple(s for s in SECTIONS if s in asked)


def _setting(orch, key: str, default: Any) -> Any:
    getter = getattr(orch, "get_setting", None)
    if not callable(getter):
        return default
    try:
        return getter(key, default)
    except Exception:
        return default


async def build_inspector(orch, agent_id: str, *, view: str = "owner",
                          sections: Iterable[str] | None = None,
                          inventory: Inventory | None = None) -> dict:
    """The inspector payload for *agent_id* as *view* sees it.

    Raises ``ValueError`` for an unknown view or section and ``LookupError`` for an agent
    the orchestrator does not have. *inventory* is the local-model inventory reader; the
    status section says ``unknown`` without one.
    """
    if view not in VIEWS:
        raise ValueError(f"unknown view: {view}")
    wanted = _wanted(sections)
    agents = getattr(orch, "agents", None) or {}
    if agent_id not in agents:
        raise LookupError(agent_id)
    # A task of its own: what the look binds, and what the runtime notes while resolving the
    # offer, stay in the task's copy of the context.
    return await asyncio.create_task(_inspect(orch, agent_id, agents[agent_id], view, wanted, inventory))


async def _inspect(orch, agent_id, agent, view, wanted, inventory) -> dict:
    """Runs as its own task (see build_inspector): the bindings end with it."""
    from agents.core.orchestrator import bind_turn_principal
    from agents.core.tool_profiles import classify_turn

    principal, origin = VIEWS[view]
    bind_turn_principal(principal)
    bind_action_origin(origin)          # what a real turn from that door binds
    out: dict[str, Any] = {"agent": agent_id, "view": view,
                           "posture": classify_turn(principal, origin).key}
    for name in wanted:
        if name == "status":
            out[name] = await _status(orch, inventory)
        elif name == "tools":
            out[name] = _tools(orch, agent_id)
        elif name == "skills":
            out[name] = _skills(orch, agent)
        elif name == "mcp":
            out[name] = _mcp(orch)
        else:
            out[name] = await _prompt(orch, agent_id, agent)
    return out


# ── the sections ─────────────────────────────────────────────────────────────


async def _status(orch, inventory: Inventory | None) -> dict:
    from agents import __version__
    from agents.core import safe_mode
    from agents.core.llm.local_model_inventory import project_llm_status

    router = getattr(orch, "llm_router", None)
    state: dict[str, Any] = {"model_state": "unknown", "loaded_model": None}
    if inventory is not None:
        try:
            projected = project_llm_status(await inventory())
            state = {"model_state": projected.get("model_state") or "unknown",
                     "loaded_model": projected.get("loaded_model")}
        except Exception:
            logger.debug("local model inventory unavailable for the inspector", exc_info=True)
    try:
        context_tokens = max(0, int(_setting(orch, "llm.tool_loop_context_tokens", 0) or 0))
    except (TypeError, ValueError):
        context_tokens = 0
    return {
        "version": __version__,
        "backend": getattr(router, "name", None) or "none",
        "model": getattr(router, "active_model", None),
        **state,
        "context_tokens": context_tokens,
        "tool_loop": _setting(orch, "llm.tool_loop_enabled", False) is True,
        "safe_mode": bool(safe_mode.enabled()),
    }


def _tool_row(tool: dict) -> dict:
    description = " ".join(str(tool.get("description") or "").split())
    return {
        "name": str(tool.get("name") or ""),
        "gated": bool(tool.get("gated")),
        "untrusted_output": tool.get("untrusted_output") is True,
        "description": description[:DESCRIPTION_CHARS],
    }


def _tools(orch, agent_id: str) -> dict:
    enabled = _setting(orch, "llm.tool_loop_enabled", False) is True
    server = getattr(orch, "tool_rpc", None)
    runtime = getattr(orch, "agent_tool_runtime", None)
    if server is None or runtime is None:
        return {"loop_enabled": enabled, "wired": False, "offered": [], "withheld": [], "registry": 0}
    registry = [str(t.get("name") or "") for t in server.tools()]
    out: dict[str, Any] = {"loop_enabled": enabled, "wired": True}
    try:
        # The runtime's own resolution: registry (or the capability registry's view of it),
        # job toolset, then the profile under the bound principal. Fails closed.
        offered = [_tool_row(t) for t in runtime._resolve_offer(agent_id)]
    except Exception:
        logger.warning("the inspector could not resolve the tool offer", exc_info=True)
        offered = []
        out["error"] = "unavailable"
    names = {row["name"] for row in offered}
    out.update(offered=offered, withheld=[n for n in registry if n not in names], registry=len(registry))
    return out


def _skills(orch, agent) -> dict:
    if not _setting(orch, "llm.skills_in_prompt", True):
        return {"in_prompt": False, "count": 0, "rows": []}
    context = getattr(orch, "_prompt_context", None)
    rows = list((context(agent, {}) if callable(context) else {}).get("skills") or [])
    rows = [{"skill": str(r.get("skill") or ""), "command": str(r.get("command") or ""),
             "description": str(r.get("description") or "")} for r in rows]
    return {"in_prompt": True, "count": len(rows), "rows": rows}


def _mcp(orch) -> dict:
    manager = getattr(orch, "mcp", None)
    servers = getattr(manager, "servers", None) or {}
    rows = []
    for name, srv in sorted(servers.items()):
        try:
            connected = srv.is_connected() is True
        except Exception:
            connected = False
        tools = list(getattr(srv, "tools", None) or [])
        rows.append({
            "name": str(name),
            "transport": str(getattr(srv, "transport", "") or ""),
            "trust": str(getattr(srv, "trust", "") or ""),
            "connected": connected,
            "tools": len(tools),
            "tool_names": [str(getattr(t, "name", "") or "") for t in tools[:MAX_MCP_TOOL_NAMES]],
        })
    return {"servers": rows, "connected": sum(1 for r in rows if r["connected"])}


def _cap(text: str, budget: int) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= budget:
        return text
    return raw[:max(0, budget)].decode("utf-8", "ignore")


async def _prompt(orch, agent_id: str, agent) -> dict:
    from agents.core.llm.tokenizer import estimate_tokens
    from agents.core.orchestrator import _system_prompt_of

    redactor = _redactor()
    if redactor is None:
        return {"system": "", "turn": "", "bytes": 0, "tokens": 0, "cap": PROMPT_CAP_BYTES,
                "truncated": False, "withheld": True}
    system = _system_prompt_of(agent) or ""
    rails = orch._runtime_state_block() + orch._language_block() + orch._data_grounding_block({})
    text = await orch._build_agent_turn_text(agent_id, "", runtime_block=rails, freeze_core=False)
    turn = orch._build_agent_prompt(agent, text, {})
    # What every turn pays before history, the user's words and the tool schemas.
    tokens = estimate_tokens(system) + estimate_tokens(turn)
    system, turn = redactor.redact_text(system), redactor.redact_text(turn)
    total = len(system.encode("utf-8")) + len(turn.encode("utf-8"))
    shown_system = _cap(system, PROMPT_CAP_BYTES)
    shown_turn = _cap(turn, PROMPT_CAP_BYTES - len(shown_system.encode("utf-8")))
    return {"system": shown_system, "turn": shown_turn, "bytes": total, "tokens": tokens,
            "cap": PROMPT_CAP_BYTES, "truncated": total > PROMPT_CAP_BYTES, "withheld": False}


__all__ = ["DESCRIPTION_CHARS", "PROMPT_CAP_BYTES", "SECTIONS", "VIEWS", "build_inspector"]
