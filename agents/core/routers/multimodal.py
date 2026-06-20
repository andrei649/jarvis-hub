"""Multimodal endpoints — vlm / desktop / media (CLN-3, behavior-frozen).

Extracted from the `agents/web.py` god-object. Covers the user-guarded surface:
- `GET  /api/vlm/status`     — whether a local VLM endpoint is configured
- `POST /api/vlm/describe`   — send image(s)+prompt to the local VLM
- `POST /api/desktop/preview`— dry-run a desktop step plan
- `GET  /api/media`          — supported media kinds + wired backends
- `POST /api/media/generate` — governed media generation

No module-global singleton is owned by these routes. The live orchestrator is
read at REQUEST time via `get_orch()` (the `/api/media/generate` handler needs
`orch.autonomy_queue`), so the test suite's `monkeypatch.setattr(web, "orch", ...)`
rebinds are still observed. Guards resolve lazily via `_deps` — no static import
edge back into `agents.web`.
"""

import os

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agents.core.app_state import get_orch
from agents.core.routers._deps import user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["multimodal"])


class VLMDescribeBody(BaseModel):
    prompt: str = Field(..., max_length=4000)
    images: list[str] = Field(default_factory=list, max_length=8)
    model: str = Field("", max_length=80)


@router.get("/api/vlm/status", dependencies=[Depends(user_guard)])
async def vlm_status():
    """H13.1 — whether a local VLM endpoint is configured (host deployment)."""
    return nocache_json({"configured": bool(os.environ.get("JARVIS_VLM_URL", "")),
                         "default_model": os.environ.get("JARVIS_VLM_MODEL", "qwen2-vl")})


@router.post("/api/vlm/describe", dependencies=[Depends(user_guard)])
async def vlm_describe(body: VLMDescribeBody):
    """H13.1 — send image(s) + a prompt to the local VLM (screen/doc/receipt).

    Requires JARVIS_VLM_URL to point at a local OpenAI-vision server (the model
    + GGUF + GPU are the host deployment seam)."""
    url = os.environ.get("JARVIS_VLM_URL", "")
    if not url:
        return JSONResponse({"error": "VLM not configured — set JARVIS_VLM_URL"}, status_code=503)
    from agents.core.llm.vlm import VLMBackend
    vlm = VLMBackend(base_url=url, api_key=os.environ.get("JARVIS_VLM_KEY", ""))
    try:
        model = body.model or os.environ.get("JARVIS_VLM_MODEL", "qwen2-vl")
        # encode_image_block accepts only data:/http(s) image sources, never file
        # paths — request-supplied images can't read host files.
        out = await vlm.generate_vision(model, body.prompt, images=body.images)
        return nocache_json({"ok": True, "model": model, "response": out})
    finally:
        await vlm.aclose()


class DesktopStepsBody(BaseModel):
    steps: list[dict] = Field(default_factory=list, max_length=100)


@router.post("/api/desktop/preview", dependencies=[Depends(user_guard)])
async def desktop_preview(body: DesktopStepsBody):
    """H15.3 — dry-run a desktop step plan (which steps need approval)."""
    from agents.core.desktop_operator import GovernedDesktop
    return nocache_json(await GovernedDesktop().preview(body.steps))


class MediaGenBody(BaseModel):
    kind: str = Field(..., max_length=20)
    prompt: str = Field(..., max_length=4000)
    cloud: bool = False


@router.get("/api/media", dependencies=[Depends(user_guard)])
async def media_status():
    """H12.24 — supported media kinds + which backends are wired."""
    from agents.core.media_gen import MediaGenManager
    return nocache_json({"kinds": MediaGenManager().kinds()})


@router.post("/api/media/generate", dependencies=[Depends(user_guard)])
async def media_generate(body: MediaGenBody):
    """H12.24 — governed media generation (cloud generation is approval-gated)."""
    orch = get_orch()
    from agents.core.media_gen import MediaGenManager
    q = getattr(orch, "autonomy_queue", None) if orch else None
    m = MediaGenManager(enqueue=q.enqueue if q is not None else None)
    result = await m.generate(body.kind, body.prompt, cloud=body.cloud)
    return nocache_json(result, status_code=200 if result.get("ok") else 422)
