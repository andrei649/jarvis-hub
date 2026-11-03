"""Agents surface — read endpoints for agents, souls, run-history, templates (extracted from web.py, CLN-3).

Covers the agent-facing reads:
- `GET /api/agents` — enriched agent list (HUD).
- `GET /agents` — agent list with per-agent stats + skills.
- `GET /api/agents/{agent_id}/soul` — live SOUL.md (personalized overlay wins).
- `PUT /api/admin/agents/{agent_id}/soul` + `POST /api/admin/agents/{agent_id}/description/draft`
  — H156: make an edited persona live (admin), and have the local model draft a description.
- `GET /api/agents/history` + `GET /api/agents/{agent_id}/history` — H10.17 run-history rollups.
- `GET /api/agent-templates` + `POST /api/agent-templates/instantiate` — H10.29 template catalog/preview.
- `GET /api/admin/agents/roster`, `POST /api/admin/agents`, `POST /api/admin/agents/{agent_id}/rename`,
  `/retire` and `/restore` — H202: the owner's roster (`agent_roster`): create an agent from a template
  or blank, rename one for good, retire it (reversible, nothing deleted) and bring it back. Admin-only,
  each change crossing the Action Kernel (`admin.agent_roster`), versioned in the roster and audited.

State that stays in web.py (read here via `sys.modules`): `_enrich_agents()` and the
`_AGENT_SETTINGS` global it reads are multi-domain (the dashboard/status routers and the
admin per-agent write also use them), so they remain web.py-owned. Everything else is the
orchestrator (via `get_orch()`) or leaf imports. The agent-id regex moved with the domain
(only the soul + history routes use it).
"""

import asyncio
import logging
import re
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

import agents as _agents_pkg
from agents.core import soul_edit
from agents.core.app_state import get_orch
from agents.core.routers._deps import admin_guard, user_guard
from agents.core.web_helpers import nocache_json

logger = logging.getLogger("jarvis.agents_api")

router = APIRouter(tags=["agents"])

# Agent souls live under the `agents/` package dir (agents/<id>/SOUL.md), the same
# anchor web.py used via Path(__file__).parent — resolve it off the package so this
# router's own location doesn't change the path.
_AGENTS_DIR = Path(_agents_pkg.__file__).resolve().parent

# The id becomes a filesystem path segment in /soul + /history — restrict it to the
# agent-id alphabet so traversal is impossible (CodeQL: uncontrolled data in path).
_AGENT_ID_RE = re.compile(r"^[a-z0-9_-]{1,64}$")


def _enrich_agents():
    # Multi-domain helper + the _AGENT_SETTINGS global it reads stay in web.py; resolve
    # at request time so the single shared override dict is the one read/mutated.
    return sys.modules.get("agents.web")._enrich_agents()


@router.get("/api/agents", dependencies=[Depends(user_guard)])
async def api_agents():
    return nocache_json({"agents": _enrich_agents()})


def _soul_guard_verdict(content: str, filename: str) -> dict:
    """What Agent._load_soul would do to *content* — flags/blocked/truncated.

    Runs the same helpers on the same text rather than re-implementing them, so
    the HUD's verdict cannot drift from the guard. Any failure degrades to a
    clean verdict with an ``error`` note: this is a disclosure on a read
    endpoint, never a reason to fail the read.
    """
    try:
        # H156: the same verdict the Apply path refuses a blocked persona on.
        return soul_edit.guard_verdict(content, filename)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("SOUL guard verdict skipped for %s", filename, exc_info=True)
        return {"flags": [], "blocked": False, "truncated": False, "error": str(exc)}


@router.get("/api/agents/{agent_id}/soul", dependencies=[Depends(user_guard)])
async def get_agent_soul(agent_id: str):
    """Read and return the live SOUL.md content for an agent."""
    agent_id = agent_id.strip().lower()
    if not _AGENT_ID_RE.match(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")

    # Resolve the agent dir by matching the validated id against the actual directory
    # listing, so the SOUL.md path is built from a trusted, enumerated entry name —
    # no request value ever reaches a path expression (path-injection defeated at the
    # source; the regex already forbids separators). Works even without orch.
    agent_dir = next(
        (d for d in _AGENTS_DIR.iterdir() if d.is_dir() and d.name == agent_id),
        None,
    )
    if agent_dir is None:
        # H202: an agent the owner created has no shipped folder; its persona folder is
        # found the same enumerated way (``soul_edit.agent_folder``).
        created = soul_edit.agent_folder(agent_id)
        agent_dir = Path(created) if created is not None else None
    soul_path = None
    if agent_dir is not None:
        # Resolved by `Agent.soul_path_for`, the SAME function `Agent._load_soul`
        # uses — not a second copy of the precedence rules. This endpoint used to
        # check only the repo-local pair, so on a packaged install (where the data
        # home's `souls/<id>/SOUL.local.md` wins) it read one file and reported an
        # injection verdict for it while the model was given another: an owner
        # whose overlay had been quarantined saw `blocked: false` for the persona
        # that was in fact dropped — the exact case the verdict exists to prevent.
        # `agent_dir` is still enumerated above so no request value reaches a path
        # expression; the id handed over here is that trusted directory name.
        from agents.core.agent import soul_path_for
        soul_path = soul_path_for(agent_dir.name)

    orch = get_orch()
    if orch and agent_id not in orch.agents:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    if soul_path is None or not soul_path.exists():
        raise HTTPException(status_code=404, detail=f"SOUL.md not found for agent '{agent_id}'")

    try:
        content = soul_path.read_text(encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read SOUL.md: {e}")
    # H387: this is the editor view, so `soul` stays the raw bytes on disk — the
    # owner has to see what they actually wrote. But the model does not
    # necessarily get that text: Agent._load_soul strips invisible Unicode,
    # quarantines injection-flagged lines and caps an oversized body. Report the
    # guard's verdict beside the raw text, so the HUD cannot show a persona the
    # model is not receiving without saying so. Previously the only trace of a
    # quarantined persona was a logger.error nobody watches.
    return {"agent_id": agent_id, "soul": content, "guard": _soul_guard_verdict(content, soul_path.name),
            "description": soul_edit.description_in(content)}


class SoulEditBody(BaseModel):
    content: str
    message: str = Field("", max_length=200)


@router.put("/api/admin/agents/{agent_id}/soul", dependencies=[Depends(admin_guard)])
async def put_agent_soul(agent_id: str, body: SoulEditBody):
    """H156 — make *content* the agent's live persona: refused when the SOUL guard would
    drop it (422), the text on disk kept as v1 on the first edit, written atomically to
    the owner's overlay, versioned, reloaded for the next turn and audited (never the
    text). 409 in safe mode, 413 over 256 KiB, 404 for an agent the hub has not loaded."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    try:
        result = await asyncio.to_thread(soul_edit.apply_soul, orch, agent_id, body.content,
                                         message=body.message)
    except soul_edit.SoulEditError as exc:
        return JSONResponse(exc.body(), status_code=exc.status)
    return nocache_json(result)


# ── H202: the owner's roster — create, rename, retire, restore ───────────────

#: The Action Kernel kind every roster change crosses (registered in kernel/registry.py).
ROSTER_KIND = "admin.agent_roster"


def _roster_kernel_denial(orch, op: str, agent: str, req: Request):
    """Mediate a roster change through the Action Kernel like the other admin escalations
    (``routers.security._admin_kernel_denial``: DENY only, a token minted for the
    already-admin caller, default-off). The payload carries the op and the id, never a
    name or persona text."""
    from agents.core.routers.security import _admin_kernel_denial

    return _admin_kernel_denial(orch, ROSTER_KIND, "admin:agent_roster",
                                {"op": op, "target": str(agent or "").strip().lower()[:64]},
                                req.headers.get("x-capability-token", ""))


async def _roster_change(req: Request, op: str, agent: str, change, *, status_code: int = 200):
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    denied = _roster_kernel_denial(orch, op, agent, req)
    if denied is not None:
        return JSONResponse({"error": "kernel_denied", "detail": f"kernel denied: {denied}"}, status_code=403)
    try:
        result = await asyncio.to_thread(change, orch)
    except soul_edit.SoulEditError as exc:
        return JSONResponse(exc.body(), status_code=exc.status)
    return nocache_json({"ok": True, **result}, status_code=status_code)


class AgentCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=64)
    template: str = Field("", max_length=64)
    agent_id: str = Field("", max_length=64)
    tier: str = Field("", max_length=16)
    soul: str | None = None


class AgentRenameBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=64)


class AgentRetireBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: str = Field("", max_length=64)
    reason: str = Field("", max_length=200)


@router.get("/api/admin/agents/roster", dependencies=[Depends(admin_guard)])
async def agent_roster_view():
    """H202 — every agent the registry knows, active and retired: whether it is live, made
    by the owner (and from which template), protected, and its last roster revisions; with
    the templates and tiers a new agent can take."""
    from agents.core import agent_roster

    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    try:
        body = await asyncio.to_thread(agent_roster.roster, orch)
    except soul_edit.SoulEditError as exc:
        return JSONResponse(exc.body(), status_code=exc.status)
    return nocache_json(body)


@router.post("/api/admin/agents", dependencies=[Depends(admin_guard)])
async def agent_create(body: AgentCreateBody, req: Request):
    """H202 — create an agent from a template (``GET /api/agent-templates``) or blank, and
    keep it: written to the owner's roster (``agent_roster.json``), loaded now and at every
    boot, its persona made live through the SOUL editor's own path (guard-scanned, version
    1, audited). No plugins, heartbeat or model pin are granted. 201; 409 a taken or
    reserved id, too many created agents or safe mode; 404 an unknown template; 413/422 a
    persona the guard refuses or a bad name, id or tier; 503 an unreadable roster."""
    from agents.core import agent_roster

    target = agent_roster.new_agent_id(body.name, body.agent_id)          # what the kernel is told
    return await _roster_change(req, "create", target, lambda orch: agent_roster.create(
        orch, name=body.name, template=body.template, agent_id=body.agent_id, tier=body.tier,
        persona=body.soul), status_code=201)


@router.post("/api/admin/agents/{agent_id}/rename", dependencies=[Depends(admin_guard)])
async def agent_rename(agent_id: str, body: AgentRenameBody, req: Request):
    """H202 — rename an agent for good (its id, the key of its persona and history,
    stays): saved in the roster, applied to the running agent, versioned and audited. The
    in-memory display override of ``PUT /api/admin/agents/{id}`` no longer hides it. 409 a
    name another agent has."""
    from agents.core import agent_roster

    reply = await _roster_change(req, "rename", agent_id,
                                 lambda orch: agent_roster.rename(orch, agent_id, body.name))
    web = sys.modules.get("agents.web")
    if reply.status_code == 200 and web is not None:
        overrides = web._get_agent_settings().get(agent_id.strip().lower())
        if isinstance(overrides, dict):
            overrides.pop("name", None)
    return reply


@router.post("/api/admin/agents/{agent_id}/retire", dependencies=[Depends(admin_guard)])
async def agent_retire(agent_id: str, body: AgentRetireBody, req: Request):
    """H202 — retire an agent: out of the running hub and every later boot, nothing deleted
    (its persona, persona versions, run history and memory stay; ``/restore`` brings it
    back as it was). ``{"confirm": "<agent id>"}`` is required: without it nothing changes
    and the 400 says what would stop and what is kept. Jarvis cannot be retired (409)."""
    from agents.core import agent_roster

    return await _roster_change(req, "retire", agent_id, lambda orch: agent_roster.retire(
        orch, agent_id, confirm=body.confirm, reason=body.reason))


@router.post("/api/admin/agents/{agent_id}/restore", dependencies=[Depends(admin_guard)])
async def agent_restore(agent_id: str, req: Request):
    """H202 — bring a retired agent back, live now and at every boot, with the persona and
    history it had. 409 for an agent that is not retired."""
    from agents.core import agent_roster

    return await _roster_change(req, "restore", agent_id,
                                lambda orch: agent_roster.restore(orch, agent_id))


@router.post("/api/admin/agents/{agent_id}/description/draft", dependencies=[Depends(admin_guard)])
async def draft_agent_description(agent_id: str):
    """H156 — the local model proposes a one-paragraph description from the live persona.
    Nothing is saved: the owner puts it in the front-matter and applies the SOUL."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    try:
        draft = await soul_edit.draft_description(orch, agent_id)
    except soul_edit.SoulEditError as exc:
        return JSONResponse(exc.body(), status_code=exc.status)
    return nocache_json({"agent_id": agent_id.strip().lower(), "draft": draft})


@router.get("/agents")
async def get_agents():
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    result = {}
    for aid, agent in orch.agents.items():
        stats = orch.checkpoints.get_agent_stats(aid)
        skills = [s.name for s in orch.skills.get_skills_for_agent(aid)]
        result[aid] = {
            "name": agent.name,
            "tier": agent.config.get("tier", ""),
            "model": agent.config.get("model", ""),
            "heartbeat": agent.has_heartbeat,
            "stats": stats,
            "skills": skills,
            "description": soul_edit.description_of(agent),   # H156
        }
    return {"agents": result}


@router.get("/api/agents/history", dependencies=[Depends(user_guard)])
async def agents_history():
    """H10.17 — per-agent run-history rollup (runs, last, ok-rate, avg latency)."""
    orch = get_orch()
    if not orch or not getattr(orch, "run_history", None):
        return nocache_json({"agents": []})
    return nocache_json({"agents": orch.run_history.agents()})


@router.get("/api/agents/{agent_id}/history", dependencies=[Depends(user_guard)])
async def agent_history(agent_id: str, limit: int = Query(50, ge=1, le=200)):
    """H10.17 — recent runs for one agent (most-recent first)."""
    agent_id = agent_id.strip().lower()
    if not _AGENT_ID_RE.match(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    orch = get_orch()
    # Consistent with /soul: an unknown agent 404s rather than returning a
    # misleading empty-but-OK run list (a fresh-but-real agent still 200s with []).
    if orch and agent_id not in orch.agents:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    if not orch or not getattr(orch, "run_history", None):
        return nocache_json({"agent_id": agent_id, "runs": []})
    return nocache_json({
        "agent_id": agent_id,
        "runs": orch.run_history.list(agent_id, limit),
    })


@router.get("/api/agent-templates")
async def agent_templates_list():
    """H10.29 — list the pre-configured agent template catalog."""
    from agents.core.agent_templates import list_templates
    return nocache_json({"templates": list_templates()})


@router.post("/api/agent-templates/instantiate", dependencies=[Depends(user_guard)])
async def agent_templates_instantiate(req: Request):
    """H10.29 — render a ready-to-save agent config from a template.

    Body: {"template": "researcher", "name": "Vega", "overrides": {...}}.
    Returns the agents.yaml-shaped config + a SOUL.md skeleton (preview); nothing is
    saved. ``POST /api/admin/agents`` (H202) is the agent-creation flow that keeps one.
    """
    from agents.core.agent_templates import build_agent_config
    try:
        body = await req.json()
    except Exception:
        body = {}
    template = (body or {}).get("template", "")
    try:
        config = build_agent_config(
            template,
            name=(body or {}).get("name"),
            overrides=(body or {}).get("overrides") or {},
        )
    except KeyError:
        return JSONResponse({"error": f"unknown template: {template}"}, status_code=404)
    return nocache_json({"ok": True, "config": config})
