"""Agents surface — read endpoints for agents, souls, run-history, templates (extracted from web.py, CLN-3).

Covers the agent-facing reads:
- `GET /api/agents` — enriched agent list (HUD).
- `GET /agents` — agent list with per-agent stats + skills.
- `GET /api/agents/{agent_id}/soul` — live SOUL.md (personalized overlay wins).
- `GET /api/agents/history` + `GET /api/agents/{agent_id}/history` — H10.17 run-history rollups.
- `GET /api/agent-templates` + `POST /api/agent-templates/instantiate` — H10.29 template catalog/preview.

State that stays in web.py (read here via `sys.modules`): `_enrich_agents()` and the
`_AGENT_SETTINGS` global it reads are multi-domain (the dashboard/status routers and the
admin per-agent write also use them), so they remain web.py-owned. Everything else is the
orchestrator (via `get_orch()`) or leaf imports. The agent-id regex moved with the domain
(only the soul + history routes use it).
"""

import re
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

import agents as _agents_pkg
from agents.core.app_state import get_orch
from agents.core.routers._deps import user_guard
from agents.core.web_helpers import nocache_json

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


@router.get("/api/agents/{agent_id}/soul")
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
    soul_path = None
    if agent_dir is not None:
        # The personalized overlay (SOUL.local.md, gitignored) wins when present —
        # same resolution as Agent._load_soul.
        soul_path = agent_dir / "SOUL.local.md"
        if not soul_path.exists():
            soul_path = agent_dir / "SOUL.md"

    orch = get_orch()
    if orch and agent_id not in orch.agents:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    if soul_path is None or not soul_path.exists():
        raise HTTPException(status_code=404, detail=f"SOUL.md not found for agent '{agent_id}'")

    try:
        content = soul_path.read_text(encoding="utf-8")
        return {"agent_id": agent_id, "soul": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read SOUL.md: {e}")


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
        }
    return {"agents": result}


@router.get("/api/agents/history")
async def agents_history():
    """H10.17 — per-agent run-history rollup (runs, last, ok-rate, avg latency)."""
    orch = get_orch()
    if not orch or not getattr(orch, "run_history", None):
        return nocache_json({"agents": []})
    return nocache_json({"agents": orch.run_history.agents()})


@router.get("/api/agents/{agent_id}/history")
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
    Returns the agents.yaml-shaped config + a SOUL.md skeleton (preview); the
    caller persists it via the normal agent-creation flow.
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
