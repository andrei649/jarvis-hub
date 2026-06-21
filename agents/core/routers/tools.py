"""Agentic-tools endpoints — extracted from web.py (CLN-3).

Covers three non-contiguous routes: `POST /api/context/compress` (H20.3 context
compression), `POST /api/digest/run` (H12.23 multi-source digest), and
`POST /api/schedule/parse` (H10.27 NL→cron). Behavior-frozen move: paths,
methods, guards and bodies are byte-identical to the originals.

The orchestrator is resolved at request time via `get_orch()`. No web.py-owned
singleton is referenced by these handlers, so nothing stays behind in web.py
beyond the route surface.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agents.core.app_state import get_orch
from agents.core.routers._deps import user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["tools"])


class ContextCompressBody(BaseModel):
    turns: list[dict] = Field(default_factory=list)
    max_tokens: int = Field(2000, ge=100, le=100000)
    keep_recent: int = Field(4, ge=1, le=50)


@router.post("/api/context/compress", dependencies=[Depends(user_guard)])
async def context_compress(body: ContextCompressBody):
    """H20.3 — compress a long turn history (keep recent, digest/summarize older)."""
    orch = get_orch()
    from agents.core.context_compressor import ContextCompressor
    summarizer = None
    if orch is not None:
        async def summarizer(text):  # noqa: E731 — wire the LLM summarizer
            return await orch.process(f"Summarize this conversation concisely:\n{text}",
                                      channel="compress")
    cc = ContextCompressor(summarizer=summarizer, max_tokens=body.max_tokens,
                           keep_recent=body.keep_recent)
    return nocache_json(await cc.compress(body.turns))


class DigestRunBody(BaseModel):
    topic: str = Field("", max_length=200)
    sources: Optional[list[str]] = Field(None, max_length=10)
    limit: int = Field(10, ge=1, le=50)
    weights: Optional[dict] = None


@router.post("/api/digest/run", dependencies=[Depends(user_guard)])
async def digest_run(body: DigestRunBody):
    """H12.23 — composable multi-source digest ranked by weight × idea-reality."""
    from agents.core.digest import build_default_aggregator
    from agents.core.http_client import PluginHTTPClient
    client = PluginHTTPClient.for_plugin("digest")

    async def _fetch(url: str) -> str:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text

    agg = build_default_aggregator(_fetch, weights=body.weights, names=body.sources)
    return nocache_json(await agg.run(body.topic, limit=body.limit))


@router.post("/api/schedule/parse", dependencies=[Depends(user_guard)])
async def schedule_parse(req: Request):
    """H10.27 — parse a natural-language schedule into a cron expression."""
    from agents.core.autonomy.nl_schedule import parse_schedule
    try:
        body = await req.json()
    except Exception:
        body = {}
    text = (body or {}).get("text", "")
    if not text:
        return JSONResponse({"error": "text required"}, status_code=400)
    result = parse_schedule(text)
    return nocache_json(result, status_code=200 if result.get("ok") else 422)
