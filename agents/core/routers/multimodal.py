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


from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, SkipValidation

from agents.core.app_state import get_orch
from agents.core.env_config import env_flag
from agents.core.routers._deps import user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["multimodal"])


class VLMDescribeBody(BaseModel):
    prompt: str = Field(..., max_length=4000)
    images: list[str] = Field(default_factory=list, max_length=8)
    model: str = Field("", max_length=80)


@router.get("/api/vlm/status", dependencies=[Depends(user_guard)])
async def vlm_status():
    """H13.1 / GAP-9 — resolved VLM deployment truth, never a guess.

    ``configured`` is config truth only; ``reachable`` is deliberately null
    because this route does no network probe — claiming reachability without
    measuring it is exactly the overclaim this surface used to make.
    """
    from agents.core.llm.vlm import VLMNotConfigured, resolve_vlm_config

    try:
        config = resolve_vlm_config()
    except VLMNotConfigured as exc:
        return nocache_json(
            {
                "configured": False,
                "backend": "off",
                "reason": exc.reason,
                "default_model": None,
                "reachable": None,
            }
        )
    return nocache_json(
        {
            "configured": True,
            "backend": config.backend,
            "base_url": config.base_url,
            "default_model": config.model,
            "local": config.is_local,
            "reachable": None,
        }
    )


@router.post("/api/vlm/describe", dependencies=[Depends(user_guard)])
async def vlm_describe(body: VLMDescribeBody):
    """H13.1 — send image(s) + a prompt to the configured VLM.

    LM Studio (`JARVIS_VLM_BACKEND=lmstudio` + `JARVIS_VLM_MODEL`), vLLM and
    llama.cpp (`JARVIS_VLM_BACKEND=custom` + `JARVIS_VLM_URL`) all serve the
    same OpenAI-vision contract; the model + weights + GPU stay the host
    deployment seam."""
    from agents.core.llm.vlm import VLMBackend, VLMNotConfigured, resolve_vlm_config

    try:
        config = resolve_vlm_config()
    except VLMNotConfigured as exc:
        return JSONResponse(
            {"error": "VLM not configured", "reason": exc.reason}, status_code=503
        )
    vlm = VLMBackend(base_url=config.base_url, api_key=config.api_key)
    try:
        model = body.model or config.model
        # encode_image_block accepts only data:/http(s) image sources, never file
        # paths — request-supplied images can't read host files.
        out = await vlm.generate_vision(model, body.prompt, images=body.images)
        return nocache_json({"ok": True, "model": model, "response": out})
    finally:
        await vlm.aclose()


class DesktopStepsBody(BaseModel):
    # Runtime shape/count checks belong to the bounded shared validator below.
    steps: SkipValidation[list[dict]] = Field(
        default_factory=list,
        json_schema_extra={"maxItems": 100},
    )


def desktop_host_enabled() -> bool:
    """Return true only for the explicit isolated-host double opt-in."""
    return env_flag("JARVIS_DESKTOP_HOST") and env_flag("JARVIS_DESKTOP_ISOLATED")


def build_desktop_runtime(orch, *, authorizer=None):
    """Bind a fresh dependency-lazy host driver to the live Action Kernel."""
    from agents.core.desktop_host import WindowsDesktopDriver
    from agents.core.desktop_operator import DesktopActionExecutor, GovernedDesktop
    from agents.core.kernel.binding import make_action_kernel

    driver = WindowsDesktopDriver.from_env()
    executor = DesktopActionExecutor(
        driver,
        authorizer=authorizer if authorizer is not None else make_action_kernel(orch),
    )
    return GovernedDesktop(driver=driver, action_executor=executor)


async def execute_desktop_steps(orch, steps, *, approver=None, authorizer=None):
    """Run a validated plan against a fresh live runtime and always release it."""
    from agents.core.desktop_operator import (
        DesktopProposalError,
        validate_desktop_run_args,
    )

    try:
        proposal = validate_desktop_run_args({"steps": steps})
    except DesktopProposalError as exc:
        return {"ok": False, "reason": exc.reason}
    runtime = build_desktop_runtime(orch, authorizer=authorizer)
    try:
        return await runtime.run_live(proposal["steps"], approver=approver)
    finally:
        await runtime.close()


class OperatorPlanBody(BaseModel):
    goal: str = Field(..., max_length=4000)
    params: dict = Field(default_factory=dict, json_schema_extra={"maxProperties": 32})
    allow_visual_fallback: bool = False


@router.post("/api/operator/plan", dependencies=[Depends(user_guard)])
async def operator_plan(body: OperatorPlanBody):
    """H28.2 / DRA-22 / DRA-42 — pick API → CLI → structured UI for a goal.

    Selection only: the router returns an implementation id and never executes it,
    so the Action Kernel and approval boundaries of the chosen surface stay the
    only way anything runs. Read-only, but user-guarded because the `considered`
    list discloses which operator surfaces this install has enabled.
    """
    from agents.core.operator_router import plan_payload

    orch = get_orch()
    if not orch:
        return nocache_json({"error": "not initialized"}, status_code=503)
    try:
        payload = plan_payload(
            body.goal,
            orch=orch,
            params=body.params,
            allow_visual_fallback=body.allow_visual_fallback,
        )
    except ValueError as exc:
        return nocache_json({"ok": False, "reason": str(exc)}, status_code=400)
    return nocache_json(payload)


@router.post("/api/desktop/preview", dependencies=[Depends(user_guard)])
async def desktop_preview(body: DesktopStepsBody):
    """H15.3 — dry-run a desktop step plan (which steps need approval)."""
    from agents.core.desktop_operator import (
        DesktopProposalError,
        GovernedDesktop,
        validate_desktop_run_args,
    )

    try:
        proposal = validate_desktop_run_args({"steps": body.steps})
    except DesktopProposalError as exc:
        return nocache_json({"ok": False, "reason": exc.reason})
    return nocache_json(await GovernedDesktop().preview(proposal["steps"]))


@router.post("/api/desktop/run", dependencies=[Depends(user_guard)])
async def desktop_run(body: DesktopStepsBody):
    """H28.4 — run isolated host steps through the live Action Kernel binding."""
    from agents.core.desktop_operator import (
        DesktopProposalError,
        GovernedDesktop,
        validate_desktop_run_args,
    )

    try:
        proposal = validate_desktop_run_args({"steps": body.steps})
    except DesktopProposalError as exc:
        return nocache_json({"ok": False, "reason": exc.reason})
    if not desktop_host_enabled():
        return nocache_json({"ok": False, "reason": "desktop_host_disabled"})
    orch = get_orch()
    if any(GovernedDesktop.is_mutating(step["action"]) for step in proposal["steps"]):
        server = getattr(orch, "tool_rpc", None)
        if server is None or not callable(getattr(server, "handle", None)):
            return nocache_json({"ok": False, "reason": "desktop_proposal_unavailable"})
        result = await server.handle(
            {"tool": "desktop_run", "args": proposal},
            actor="jarvis",
        )
        return nocache_json(result)
    return nocache_json(await execute_desktop_steps(orch, proposal["steps"]))


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
    """H12.24 — governed media generation (cloud generation is approval-gated).

    0.62: paused when the active system profile turns heavy features off (e.g. the
    *gaming* profile frees the GPU). Default ``balanced`` leaves them on → unchanged."""
    from agents.core.system_profiles import active_name, heavy_features_enabled
    if not heavy_features_enabled():
        return nocache_json(
            {"ok": False, "paused": True, "profile": active_name(),
             "error": f"media generation paused by the '{active_name()}' system profile "
                      "(heavy_features off — set JARVIS_SYSTEM_PROFILE=balanced to re-enable)"},
            status_code=200,
        )
    orch = get_orch()
    from agents.core.media_catalog import default_catalog_if_enabled
    from agents.core.media_gen import MediaGenManager
    q = getattr(orch, "autonomy_queue", None) if orch else None
    # 0.46 (opt-in): catalog the generation when JARVIS_MEDIA_CATALOG is set; else
    # catalog=None → byte-identical (no prompt history written).
    m = MediaGenManager(enqueue=q.enqueue if q is not None else None,
                        catalog=default_catalog_if_enabled())
    result = await m.generate(body.kind, body.prompt, cloud=body.cloud)
    return nocache_json(result, status_code=200 if result.get("ok") else 422)


@router.get("/api/media/catalog", dependencies=[Depends(user_guard)])
async def media_catalog(q: str | None = None, kind: str | None = None):
    """0.46 read surface: the generated-media catalog (newest-first, optionally
    filtered by prompt substring ``q`` / ``kind``) + stats. Reports
    ``enabled: false`` with empty data when JARVIS_MEDIA_CATALOG is unset."""
    from agents.core.media_catalog import default_catalog_if_enabled
    cat = default_catalog_if_enabled()
    if cat is None:
        return nocache_json({"enabled": False, "items": [],
                             "stats": {"total": 0, "cloud": 0, "by_kind": {}}})
    items = cat.search(q, kind=kind) if (q or kind) else cat.all()
    return nocache_json({"enabled": True, "items": items[:200], "stats": cat.stats()})
