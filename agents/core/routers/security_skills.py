"""Security Skills pack (0.42) — curated defensive-security knowledge endpoints.

Read-only surface over public taxonomies (MITRE ATT&CK / D3FEND / NIST CSF 2.0):

  * `GET  /api/security-skills/frameworks`        — the three frameworks at a glance
  * `GET  /api/security-skills/tactics`           — ATT&CK enterprise tactics (all 14)
  * `GET  /api/security-skills/techniques?tactic=`— curated ATT&CK techniques (filterable)
  * `GET  /api/security-skills/technique/{tid}`   — one technique + its D3FEND/CSF mapping
  * `POST /api/security-skills/map`               — behavior text → candidate techniques
  * `POST /api/security-skills/playbook`          — techniques → defensive playbook

Offline, deterministic, honest (curated subset + disclaimer; never fabricates an ID,
never acts). User-guarded like the other capability packs.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agents.core.routers._deps import user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["security-skills"])


class MapBody(BaseModel):
    behavior: str = Field("", max_length=2000)
    top_k: int = Field(5, ge=1, le=20)


class PlaybookBody(BaseModel):
    techniques: list[str] = Field(default_factory=list, max_length=50)


@router.get("/api/security-skills/frameworks", dependencies=[Depends(user_guard)])
async def security_skills_frameworks():
    """ATT&CK tactics + D3FEND tactics + NIST CSF functions at a glance."""
    from agents.core import security_skills
    return nocache_json(security_skills.frameworks())


@router.get("/api/security-skills/tactics", dependencies=[Depends(user_guard)])
async def security_skills_tactics():
    """ATT&CK enterprise tactics (complete: all 14)."""
    from agents.core import security_skills
    return nocache_json(security_skills.tactics())


@router.get("/api/security-skills/techniques", dependencies=[Depends(user_guard)])
async def security_skills_techniques(tactic: str = ""):
    """Curated ATT&CK techniques, optionally filtered by tactic id (e.g. TA0002)."""
    from agents.core import security_skills
    return nocache_json(security_skills.techniques(tactic or None))


@router.get("/api/security-skills/technique/{tid}", dependencies=[Depends(user_guard)])
async def security_skills_technique(tid: str):
    """One technique's detail + its mapped D3FEND countermeasures and CSF functions."""
    from agents.core import security_skills
    result = security_skills.technique(tid)
    if result is None:
        return JSONResponse({"error": f"unknown technique '{tid}'"}, status_code=404)
    return nocache_json(result)


@router.post("/api/security-skills/map", dependencies=[Depends(user_guard)])
async def security_skills_map(body: MapBody):
    """Map a free-text behavior to candidate ATT&CK techniques (keyword heuristic)."""
    from agents.core import security_skills
    return nocache_json(security_skills.map_behavior(body.behavior, body.top_k))


@router.post("/api/security-skills/playbook", dependencies=[Depends(user_guard)])
async def security_skills_playbook(body: PlaybookBody):
    """Assemble a defensive playbook for a set of ATT&CK technique ids."""
    from agents.core import security_skills
    return nocache_json(security_skills.build_playbook(body.techniques))
