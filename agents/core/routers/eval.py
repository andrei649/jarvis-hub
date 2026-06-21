"""Dataset regression / eval endpoints (H9.3b) — extracted from web.py (CLN-3).

Covers the `/api/eval/datasets*` surface: list versioned eval datasets, recent
runs, run comparison, and running a dataset version through the live orchestrator.

The `_dataset_store` singleton + its accessor move here with the domain (no test
rebinds `web._dataset_store` — grep-confirmed), so this router owns it outright.
The orchestrator is resolved at request time via `get_orch()` (late binding to
`web.orch`), matching the other extracted routers — no static import edge into web.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from agents.core.app_state import get_orch
from agents.core.routers._deps import user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["eval"])

_dataset_store = None


def _get_dataset_store():
    global _dataset_store
    if _dataset_store is None:
        from agents.core.observability.datasets import DatasetStore
        _dataset_store = DatasetStore()
    return _dataset_store


class DatasetRunBody(BaseModel):
    name: str = Field(..., max_length=128)
    version: Optional[int] = None


@router.get("/api/eval/datasets")
async def list_eval_datasets():
    """List versioned eval datasets with their latest score (H9.3b)."""
    return nocache_json({"datasets": _get_dataset_store().list_datasets()})


@router.get("/api/eval/datasets/{name}/runs")
async def list_dataset_runs(name: str, limit: int = Query(20, ge=1, le=200)):
    """Recent run summaries for a dataset (most-recent first)."""
    return nocache_json({"name": name, "runs": _get_dataset_store().runs(name, limit)})


@router.get("/api/eval/datasets/{name}/compare")
async def compare_dataset_runs(name: str, a: str = Query(...), b: str = Query(...)):
    """Diff two runs (a=baseline, b=candidate): regressions + score delta."""
    return nocache_json(_get_dataset_store().compare(name, a, b))


@router.post("/api/eval/datasets/run", dependencies=[Depends(user_guard)])
async def run_eval_dataset(body: DatasetRunBody):
    """Run a dataset version through the live orchestrator and record the run."""
    orch = get_orch()
    if not orch:
        return nocache_json({"error": "not initialized"}, status_code=503)

    async def _runner(prompt: str) -> str:
        return await orch.handle_input(prompt, channel="eval")

    result = await _get_dataset_store().run_dataset(body.name, _runner, body.version)
    status = 404 if result.get("error") else 200
    return nocache_json(result, status_code=status)
