"""OSINT investigator pack (P2, Track P) — governed correlation over untrusted evidence.

`POST /api/osint/correlate` takes a batch of evidence items (gathered however the caller
likes — WorldView/Argus, web, RSS, manual) and returns the evidence-drawer: findings
grouped by indicator, each with a provenance chain, a corroboration-based confidence, and
a **taint flag** (set for any finding backed by an untrusted source). `GET /api/osint/brief`
is the compact top-N "world brief" over the same input.

Honest + offline: this *correlates* the evidence you provide — it does not fetch. Live
collection (SpiderFoot modules, the WorldView REST, news feeds) is owner-gated wiring
(`docs/OWNER_TASKS.md`). Untrusted findings carry taint into any write-back, so the Action
Kernel escalates them to approval — intel from an untrusted source can never auto-execute.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from agents.core.routers._deps import user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["osint"])


class EvidenceItem(BaseModel):
    source: str = Field("", max_length=64)          # untrusted (web/osint/worldview/rss/...) vs operator/manual
    kind: str = Field(..., max_length=32)           # indicator kind: ip | domain | handle | email | alias | ...
    value: str = Field(..., max_length=512)         # the indicator value (correlation key)
    observed_at: str = Field("", max_length=40)
    detail: str = Field("", max_length=2000)
    url: str = Field("", max_length=1024)


class CorrelateBody(BaseModel):
    evidence: list[EvidenceItem] = Field(default_factory=list, max_length=2000)
    top: int = Field(8, ge=1, le=100)               # brief size (only used by the brief view)


@router.post("/api/osint/correlate", dependencies=[Depends(user_guard)])
async def osint_correlate(body: CorrelateBody):
    """Correlate provided evidence into the governed evidence-drawer (findings + taint)."""
    from agents.core.osint import correlate
    items = [e.model_dump() for e in body.evidence]
    return nocache_json(correlate(items))


@router.post("/api/osint/brief", dependencies=[Depends(user_guard)])
async def osint_brief(body: CorrelateBody):
    """The compact top-N world brief over provided evidence (headline + top findings)."""
    from agents.core.osint import build_brief
    items = [e.model_dump() for e in body.evidence]
    return nocache_json(build_brief(items, top=body.top))
