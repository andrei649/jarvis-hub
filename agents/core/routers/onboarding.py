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


# ── H23.20 first-run wizard + activation funnel ───────────────────────────────
_WIZARD_STEPS = [
    {"key": "intro", "title": "Welcome to Jarvis"},
    {"key": "model", "title": "Connect a model"},
    {"key": "test_chat", "title": "Say hello"},
    {"key": "autonomy", "title": "Set your autonomy budget"},
    {"key": "product_posture", "title": "Choose product posture"},
]
_STEP_KEYS = {s["key"] for s in _WIZARD_STEPS}


def _model_ready():
    """Best-effort: is a model backend reachable (local or configured cloud)? None if unknown."""
    orch = get_orch()
    llm_router = getattr(orch, "llm_router", None) if orch else None
    if llm_router is None:
        return None
    return bool(
        getattr(llm_router, "_local_available", False)
        or getattr(llm_router, "_claude_backend", None)
        or getattr(llm_router, "_gemini_backend", None)
    )


def _completed_steps() -> list[str]:
    """Steps finished, derived from recorded funnel events — so onboarding resumes across
    reloads without a wizard-specific store."""
    from agents.core import analytics_store
    counts = analytics_store.event_counts(days=3650)
    return [s["key"] for s in _WIZARD_STEPS if counts.get(f"funnel.{s['key']}.complete")]


@router.get("/api/onboarding/wizard", dependencies=[Depends(user_guard)])
async def onboarding_wizard():
    """First-run wizard state (H23.20): ordered steps + which are complete + cold-start
    guidance. Completion derives from the activation funnel, so the HUD can resume."""
    done = _completed_steps()
    ready = _model_ready()
    hint = None
    if ready is False:
        hint = ("No model backend reachable — start LM Studio or Ollama, or add a cloud "
                "API key in Admin → settings.")
    from agents.core import product_posture
    orch = get_orch()
    posture = product_posture.snapshot(getattr(orch, "_runtime_settings", {}) if orch else {})
    return nocache_json({
        "steps": _WIZARD_STEPS,
        "completed": done,
        "complete": len(done) >= len(_WIZARD_STEPS),
        "model_ready": ready,
        "hint": hint,
        "product_posture": posture,
    })


@router.get("/api/onboarding/command-center", dependencies=[Depends(user_guard)])
async def command_center():
    """0.19 First-Run Command Center — install health + model + first actions, one read.

    The unified first-run screen's single fetch: the /readyz verdict (shared
    ``readiness_snapshot``), the model backend truth, the H23.20 wizard state,
    and honest FIRST ACTIONS whose ``ready`` flags derive from live state — a
    chat action is never presented ready without a model, and the local-docs
    action stays not-ready (with the reason) until the owner configures a
    folder. Read-only; the actions point at existing governed endpoints.
    """
    from agents import __version__
    from agents.core.routers.ops import readiness_snapshot

    install = {**readiness_snapshot(), "version": __version__}

    orch = get_orch()
    llm = getattr(orch, "llm_router", None) if orch else None
    model_ready = _model_ready()
    model = {
        "backend": getattr(llm, "name", "none") if llm is not None else "none",
        "active_model": getattr(llm, "active_model", None) if llm is not None else None,
        "ready": model_ready,
        "cloud_configured": bool(
            getattr(llm, "_claude_backend", None) or getattr(llm, "_gemini_backend", None)
        ) if llm is not None else False,
    }

    done = _completed_steps()
    hint = None
    if model_ready is False:
        hint = ("No model backend reachable — start LM Studio or Ollama, or add a "
                "cloud API key in Admin → settings.")
    wizard = {
        "steps": _WIZARD_STEPS,
        "completed": done,
        "complete": len(done) >= len(_WIZARD_STEPS),
        "hint": hint,
    }

    chat_ready = bool(install["ready"] and model_ready)
    chat_reason = None if chat_ready else (
        "model not reachable" if install["ready"] else "still starting")
    folders = sorted(_configured_doc_folders())
    first_actions = [
        {"key": "say_hello", "title": "Say hello", "kind": "chat",
         "path": "/chat", "ready": chat_ready, "reason": chat_reason},
        {"key": "morning_brief", "title": "Get your morning brief", "kind": "get",
         "path": "/autonomy/brief", "admin": True,
         "ready": bool(install["ready"]),
         "reason": None if install["ready"] else "still starting"},
        {"key": "index_docs", "title": "Chat with a folder of your docs",
         "kind": "post", "path": "/api/local-docs/index",
         "ready": bool(folders), "folders": folders,
         "reason": None if folders else
         "no folder configured — set local_docs.folders in Admin → settings"},
    ]
    return nocache_json({
        "install": install,
        "model": model,
        "wizard": wizard,
        "first_actions": first_actions,
    })


class FunnelBody(BaseModel):
    step: str = Field(..., max_length=64)
    event: str = Field("complete", max_length=32)   # "start" | "complete" | …


@router.post("/api/onboarding/funnel", dependencies=[Depends(user_guard)])
async def onboarding_funnel(body: FunnelBody):
    """Record one activation-funnel event (`funnel.<step>.<event>`) — first-party, local
    (H23.20). Unknown steps are rejected so the funnel namespace stays bounded."""
    if body.step not in _STEP_KEYS:
        return nocache_json(
            {"error": f"unknown step '{body.step}'", "steps": sorted(_STEP_KEYS)},
            status_code=400,
        )
    from agents.core import analytics_store
    name = f"funnel.{body.step}.{body.event}"
    analytics_store.record_event(name, props={"step": body.step, "event": body.event})
    return nocache_json({"ok": True, "recorded": name})
