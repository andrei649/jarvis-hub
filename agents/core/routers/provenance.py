"""Ingestion-provenance read surface (0.37) — admin-guarded audit ledger.

The ingestion pipeline can stamp an auditable provenance record per parsed
message (source / origin / phase / content-hash / run), but only when a ledger is
wired — opt-in via ``JARVIS_PROVENANCE`` (the ledger's ``origin`` carries
conversation ids, so recording is off by default). This router exposes the
read side of that ledger so the owner can audit *where ingested memory came
from* from the HUD.

Admin-guarded: a forensic/lineage view of how personal memory was ingested.
Reports ``enabled: false`` with empty data when the flag is unset — no separate
"is it on?" probe needed. No module-global singleton: the ledger is read at
REQUEST time from its default path, matching the other extracted routers.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from agents.core.routers._deps import admin_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["provenance"])

_EMPTY_STATS = {"total": 0, "runs": 0, "by_source": {}}


@router.get("/api/ingestion/provenance", dependencies=[Depends(admin_guard)])
async def ingestion_provenance(run: str | None = None, source: str | None = None):
    """0.37 read surface: the ingestion provenance ledger (newest-first, optionally
    filtered by ``run`` id or ``source`` family) + stats. Reports
    ``enabled: false`` with empty data when JARVIS_PROVENANCE is unset."""
    from agents.core.ingestion.provenance import default_ledger_if_enabled
    led = default_ledger_if_enabled()
    if led is None:
        return nocache_json({"enabled": False, "records": [], "stats": dict(_EMPTY_STATS)})
    if run:
        records = list(reversed(led.by_run(run)))   # by_run is oldest-first; show newest-first
    elif source:
        records = list(reversed(led.by_source(source)))
    else:
        records = led.recent(200)
    return nocache_json({"enabled": True, "records": records[:200], "stats": led.stats()})
