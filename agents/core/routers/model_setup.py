"""Model setup endpoints (model-setup slice) — the zero-key first-value surface.

``GET /api/onboarding/model-plan`` reads what the box is and which local model
the tier table suggests (spec-based, never benchmarked), whether a loopback
Ollama is present and whether the pick is already installed.

``POST /api/onboarding/model-pull`` is the only mutating route and it is
default-off: it refuses ``model_pull_disabled`` until ``JARVIS_MODEL_PULL`` is
set, and when it is on the pull crosses the O27 unified action facade
(``action:model.pull``) with the Action Kernel as its authorizer — the router
holds no authority of its own. Kernel refusals answer 403 so the HUD's failure
sink records them; a QUEUE answers 202 with the approval card.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from agents.core.routers._deps import user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["onboarding"])

_service = None


def _ollama_url() -> str:
    from agents.core import settings_db
    from agents.core.llm.model_setup import DEFAULT_OLLAMA_URL

    value = settings_db.get_value("llm", "ollama_url", DEFAULT_OLLAMA_URL)
    return str(value or "").strip() or DEFAULT_OLLAMA_URL


def _max_gb() -> float:
    from agents.core import settings_db
    from agents.core.llm.model_setup import MODEL_PULL_MAX_GB_DEFAULT

    return settings_db.get_value("llm", "model_pull_max_gb", MODEL_PULL_MAX_GB_DEFAULT)


def _get_service():
    global _service
    if _service is None:
        from agents.core.llm.model_setup import ModelSetupService

        _service = ModelSetupService(ollama_url=_ollama_url, max_gb=_max_gb)
    return _service


def _enabled() -> bool:
    from agents.core.env_config import env_flag
    from agents.core.llm.model_setup import MODEL_PULL_ENV

    return env_flag(MODEL_PULL_ENV)


def _build_api(service):
    """Request-scoped facade: the kernel hook is the authorizer, never the router."""
    from agents.core.app_state import get_orch
    from agents.core.capability_actions import CapabilityActionAPI
    from agents.core.capability_manifests import ACTION_CAPABILITY_MANIFESTS
    from agents.core.kernel.binding import make_action_kernel
    from agents.core.llm.model_setup import MODEL_PULL_CAPABILITY_ID

    orch = get_orch()
    api = CapabilityActionAPI(
        authorizer=make_action_kernel(orch) if orch else None,
        manifests=list(ACTION_CAPABILITY_MANIFESTS.values()),
    )
    api.register(MODEL_PULL_CAPABILITY_ID, service.handle_pull)
    return api


class ModelPullBody(BaseModel):
    # Empty → the recommendation for this box. Validated again by the contract.
    model: str | None = Field(None, max_length=200)


@router.get("/api/onboarding/model-plan", dependencies=[Depends(user_guard)])
async def model_plan():
    """Hardware → tier → model, Ollama presence, and the current pull job."""
    service = _get_service()
    return nocache_json(await service.plan(enabled=_enabled()))


@router.post("/api/onboarding/model-pull", dependencies=[Depends(user_guard)])
async def model_pull(body: ModelPullBody):
    """Pull the recommended (or a named) model through the governed facade."""
    from agents.core.capability_actions import PerformContext
    from agents.core.llm.model_setup import (
        MODEL_PULL_CAPABILITY_ID,
        MODEL_PULL_ENV,
        recommend_model,
        valid_model_tag,
    )

    service = _get_service()
    if not _enabled():
        return nocache_json({
            "ok": False, "enabled": False, "status": "disabled",
            "reason": "model_pull_disabled",
            "hint": f"set {MODEL_PULL_ENV}=1 to allow governed local-model pulls",
        })
    model = (body.model or "").strip() or recommend_model(service.hardware())["model"]
    if not valid_model_tag(model):
        return nocache_json({"ok": False, "enabled": True, "status": "refused",
                             "reason": "invalid_model_tag"}, status_code=422)
    api = _build_api(service)
    result = await api.perform(
        MODEL_PULL_CAPABILITY_ID,
        {"model": model, "url": service.ollama_url(), "max_bytes": service.max_bytes()},
        PerformContext(agent="jarvis", title=f"pull local model {model}", origin="user"),
    )
    output = result.output if isinstance(result.output, dict) else None
    payload = {
        "ok": result.status == "completed" and bool(output and output.get("ok")),
        "enabled": True,
        "status": result.status,
        "reason": result.reason or (output or {}).get("reason", ""),
        "model": model,
        "output": output,
    }
    if result.card is not None:
        payload["card"] = result.card
    if result.status == "refused":
        code = 403
    elif result.status == "queued":
        code = 202
    elif result.status in ("disabled", "completed"):
        code = 200
    else:
        code = 500
    return nocache_json(payload, status_code=code)
