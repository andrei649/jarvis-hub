"""Onboarding / local-docs endpoints (H12.2) — extracted from web.py (CLN-3).

"Drop a folder → private chat with your docs": index an owner-configured local
folder (selected by key, never a raw request path) into memory, offline.
"""

from fastapi import APIRouter, Depends
from agents.core.routers._deps import user_guard
from pydantic import BaseModel, Field

from agents.core.web_helpers import nocache_json
from agents.core.app_state import get_orch


router = APIRouter(tags=["onboarding"])

_local_docs_last = {"status": "never run"}


class LocalDocsIndexBody(BaseModel):
    # Select a pre-configured folder by key — NOT a raw path. The actual folder
    # path comes from owner configuration (`local_docs.folders`), so no
    # request-supplied value ever reaches a filesystem path expression.
    key: str = Field(..., max_length=128)


def _configured_doc_folders() -> dict:
    """Owner-configured ``{key: folder_path}`` map of indexable folders."""
    orch = get_orch()
    folders = orch.get_setting("local_docs.folders", {}) if orch else {}
    return folders if isinstance(folders, dict) else {}


@router.get("/api/local-docs")
async def local_docs_status():
    """Last indexing summary + the configured folder keys (H12.2)."""
    return nocache_json({**_local_docs_last, "available": sorted(_configured_doc_folders())})


@router.post("/api/local-docs/index", dependencies=[Depends(user_guard)])
async def local_docs_index(body: LocalDocsIndexBody):
    """Index a pre-configured local folder (by key) into memory (offline)."""
    global _local_docs_last
    orch = get_orch()
    if not orch:
        return nocache_json({"error": "not initialized"}, status_code=503)

    folders = _configured_doc_folders()
    folder = folders.get(body.key)
    if not folder:
        return nocache_json(
            {"error": f"unknown folder key '{body.key}'",
             "available": sorted(folders)},
            status_code=404,
        )

    from agents.core.local_docs import LocalDocsIndexer

    async def _remember(text: str, metadata: dict):
        return await orch.memory.remember(text, metadata=metadata)

    summary = await LocalDocsIndexer(_remember).index(folder)
    status = 400 if summary.get("error") else 200
    if not summary.get("error"):
        _local_docs_last = summary
    return nocache_json(summary, status_code=status)
