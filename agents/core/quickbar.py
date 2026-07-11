"""quickbar.py — 0.64 Floating Bar + Global Hotkey (offline command-service core).

The desktop floating bar is two parts: a tiny host overlay (OS-level global hotkey +
always-on-top window — owner-gated, lives in the Tauri host) and the **command service**
that decides what a typed line *means*. This module is that service: pure, synchronous,
offline, deterministic. The host hands it the raw line from the bar and gets back a
**plan** — it never performs the action itself, so nothing here can fire an irreversible
side effect (agent requests still route through the orchestrator + Action Kernel).

Grammar the bar understands, in precedence order:

1. **Slash navigation** — ``/artifacts``, ``/memory``, ``/agents`` … jump straight to a
   real HUD destination. The targets are grounded in the frontend's own grammar
   (``app.tsx`` number-key modes + the center tabs), so a plan can never point at a
   view that doesn't exist.
2. **Verb navigation** — ``open artifacts`` / ``go to memory`` / ``show cognition`` — the
   same destinations via natural phrasing (the bar's ergonomics).
3. **Direct agent summon** — ``@friday …`` or ``friday: …`` addresses one cabinet agent.
   Only names in the router's roster are honored; ``@nobody`` is *unresolved*, never
   guessed into a real agent.
4. **Natural query** — anything else. The bar attaches a lightweight ``route_hint`` (which
   agent will likely answer) computed from the router's shared ``INTENT_RULES`` so there is
   a single source of truth and no duplicated keyword table. The hint is a *preview only*;
   authoritative routing still happens in the orchestrator's ``IntentRouter`` on submit.

Honest by construction: an input that matches no destination, agent, or trigger comes back
as ``unresolved`` (or a hint-less ``query``) — the bar surfaces that rather than inventing a
target. Bounded: input is length-capped and the recall history has a fixed maximum.
"""

from __future__ import annotations

import re
from collections import deque

# Single source of truth for routing — reuse the intent router's data instead of
# duplicating the agent list or the keyword→agent table here.
from agents.core.router import INTENT_RULES, IntentRouter

# Cabinet agents that can be directly summoned (@name / "name:"), roster-order preserved.
AGENTS: tuple[str, ...] = tuple(IntentRouter.ROUTING_TABLE)
_AGENT_ORDER: dict[str, int] = {a: i for i, a in enumerate(AGENTS)}

# HUD destinations, grounded in app.tsx: number-key modes and the center tabs. A navigate
# plan carries `mode` and/or `tab` verbatim so the host sets exactly these.
HUD_MODES: tuple[str, ...] = (
    "cockpit", "agents", "trust", "memory", "autonomy",
    "build", "observe", "interop", "chat", "comms",
)
CENTER_TABS: tuple[str, ...] = ("conversation", "cognition", "artifacts")

# command word → navigate plan fields. Center tabs open in the cockpit; a couple of
# friendly aliases point at the same real destinations.
_NAV: dict[str, dict] = {}
for _m in HUD_MODES:
    _NAV[_m] = {"mode": _m}
for _t in CENTER_TABS:
    _NAV[_t] = {"mode": "cockpit", "tab": _t}
_NAV["artifact"] = {"mode": "cockpit", "tab": "artifacts"}   # singular alias
_NAV["home"] = {"mode": "cockpit"}

_WORD_RE = re.compile(r"[a-z0-9]+")
_VERB_NAV = ("open", "go to", "goto", "show", "jump to", "switch to")
_MAX_LEN = 2000
_MAX_HISTORY = 50


def _route_hint(text: str) -> dict:
    """Lightweight agent hint from the shared ``INTENT_RULES`` (single-token + phrase
    triggers). A *preview* for the bar only — the orchestrator's async ``IntentRouter`` is
    still authoritative on submit. No trigger matched → no hint (honest, never a guess)."""
    low = text.lower()
    tokens = set(_WORD_RE.findall(low))
    scores: dict[str, float] = {}
    matched: dict[str, list[str]] = {}
    for agents, surfaces, weight in INTENT_RULES.values():
        primary = agents[0]
        for surface in surfaces:
            hit = (surface in low) if " " in surface else (surface in tokens)
            if hit:
                scores[primary] = scores.get(primary, 0.0) + weight
                matched.setdefault(primary, []).append(surface)
    if not scores:
        return {"agent": None, "matched": []}
    best = max(scores, key=lambda a: (scores[a], -_AGENT_ORDER.get(a, len(AGENTS))))
    return {"agent": best, "matched": matched[best]}


def _nav_plan(key: str, raw: str) -> dict | None:
    dest = _NAV.get(key)
    if dest is None:
        return None
    return {"kind": "navigate", **dest, "input": raw}


def parse_command(text: str) -> dict:
    """Resolve one bar line into a plan. Never performs the action — returns intent only.

    Plan ``kind`` is one of: ``empty`` · ``help`` · ``navigate`` · ``summon`` · ``query``
    · ``unresolved``. Every plan echoes the (length-capped) ``input``.
    """
    raw = (text or "").strip()[:_MAX_LEN]
    if not raw:
        return {"kind": "empty", "input": ""}
    low = raw.lower()

    # 1 — slash: "/artifacts", "/memory", "/help", "/friday hello"
    if raw.startswith("/"):
        m = _WORD_RE.match(low[1:])
        key = m.group(0) if m else ""
        rest = raw[1 + len(key):].strip()
        if key in ("help", "?", ""):
            return {"kind": "help", "commands": help_commands(), "input": raw}
        nav = _nav_plan(key, raw)
        if nav is not None:
            return nav
        if key in _AGENT_ORDER:                      # "/friday what's up" → summon
            return {"kind": "summon", "agent": key, "text": rest, "input": raw}
        return {"kind": "unresolved", "reason": f"unknown command /{key}", "input": raw}

    # 2 — direct agent summon: "@friday …" or "friday: …"
    m = re.match(r"^@([a-z][a-z0-9_]*)\b[:,]?\s*(.*)$", low, re.S)
    if m:
        name = m.group(1)
        text_after = raw[m.start(2):].strip() if m.group(2) else ""
        if name in _AGENT_ORDER:
            return {"kind": "summon", "agent": name, "text": text_after, "input": raw}
        return {"kind": "unresolved", "reason": f"unknown agent @{name}", "input": raw}
    m = re.match(r"^([a-z][a-z0-9_]*)\s*[:,]\s*(.+)$", low, re.S)
    if m and m.group(1) in _AGENT_ORDER:
        text_after = raw[m.start(2):].strip()
        return {"kind": "summon", "agent": m.group(1), "text": text_after, "input": raw}

    # 3 — verb navigation: "open artifacts", "go to memory", "show cognition"
    for verb in _VERB_NAV:
        if low.startswith(verb + " "):
            target = low[len(verb) + 1:].strip()
            key = (_WORD_RE.match(target).group(0) if _WORD_RE.match(target) else "")
            nav = _nav_plan(key, raw)
            if nav is not None:
                return nav
            break                                    # a verb we know, target we don't

    # 4 — natural query, with a best-effort routing hint
    hint = _route_hint(raw)
    return {"kind": "query", "text": raw, "route_hint": hint["agent"],
            "matched": hint["matched"], "input": raw}


def help_commands() -> list[dict]:
    """The command menu the bar shows for ``/help`` — grounded in the real destinations."""
    nav = [{"command": f"/{k}", "does": f"go to {v.get('tab', v.get('mode'))}"}
           for k, v in _NAV.items() if k in HUD_MODES or k in CENTER_TABS]
    return [
        {"command": "@<agent>: …", "does": f"summon one of {', '.join(AGENTS[:6])}…"},
        {"command": "open <view>", "does": "jump to a HUD destination"},
        {"command": "<anything else>", "does": "ask — routed to the best agent"},
        *nav,
    ]


class CommandBar:
    """Stateful bar helper: resolves lines and keeps a bounded recall history.

    ``resolve`` records only *actionable* lines (navigate/summon/query) into the history
    so the bar's up-arrow recall skips ``/help`` and empty entries. History is capped.
    """

    def __init__(self, *, max_history: int = _MAX_HISTORY) -> None:
        self._history: deque[str] = deque(maxlen=int(max_history))

    def resolve(self, text: str) -> dict:
        plan = parse_command(text)
        if plan["kind"] in ("navigate", "summon", "query"):
            self._history.appendleft(plan["input"])
        return plan

    def history(self) -> list[str]:
        """Most-recent-first, deduped preserving order (bounded by ``max_history``)."""
        seen: set[str] = set()
        out: list[str] = []
        for item in self._history:
            if item not in seen:
                seen.add(item)
                out.append(item)
        return out

    def clear_history(self) -> None:
        self._history.clear()
