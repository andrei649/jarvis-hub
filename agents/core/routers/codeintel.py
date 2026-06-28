"""Code Intelligence (0.31) — read-only symbol search over the project source.

  * `GET  /api/codeintel/stats`             — index roll-ups (files, symbols, by-kind)
  * `GET  /api/codeintel/search?q=&kind=`   — substring search over symbol names
  * `POST /api/codeintel/reindex`           — rebuild the cached index (admin)

Returns structure only — symbol names, kinds, relative paths, line numbers, and a
one-line doc — never file contents. The index covers the project's own Python
source, built once and cached.
"""

from fastapi import APIRouter, Depends, Query

from agents.core.routers._deps import admin_guard, user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["codeintel"])


@router.get("/api/codeintel/stats", dependencies=[Depends(user_guard)])
async def codeintel_stats():
    """Index roll-ups: files indexed, symbol count, counts by kind."""
    from agents.core import codeintel
    idx = codeintel.project_index()
    return nocache_json({k: idx[k] for k in ("files_indexed", "symbol_count", "by_kind", "errors")})


@router.get("/api/codeintel/search", dependencies=[Depends(user_guard)])
async def codeintel_search(q: str = "", kind: str = "", limit: int = Query(50, ge=1, le=500)):
    """Substring search over symbol names/qualnames; optional `kind` filter."""
    from agents.core import codeintel
    hits = codeintel.search_symbols(codeintel.project_index(), q, kind=(kind or None), limit=limit)
    return nocache_json({"query": q, "kind": kind or None, "count": len(hits), "results": hits})


@router.post("/api/codeintel/reindex", dependencies=[Depends(admin_guard)])
async def codeintel_reindex():
    """Rebuild the cached project index (admin)."""
    from agents.core import codeintel
    idx = codeintel.reindex()
    return nocache_json({"ok": True, "files_indexed": idx["files_indexed"],
                         "symbol_count": idx["symbol_count"]})
