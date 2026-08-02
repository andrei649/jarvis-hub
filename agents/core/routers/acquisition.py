"""H32.6 governed capability-acquisition status, audit, and lifecycle controls."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, Field

from agents.core.acquisition.package_store import PackageStoreError
from agents.core.acquisition.promotion import PromotionError
from agents.core.app_state import get_orch
from agents.core.routers._deps import admin_guard, user_guard
from agents.core.web_helpers import nocache_json

logger = logging.getLogger("jarvis.web")

router = APIRouter(tags=["acquisition"])


class AcquisitionPurgeBody(BaseModel):
    model_config = {"extra": "forbid"}

    confirm: str = Field(..., min_length=1, max_length=64)


def _get_runtime():
    orch = get_orch()
    return getattr(orch, "acquisition", None) if orch is not None else None


def _unavailable():
    return nocache_json(
        {"status": "refused", "reason": "acquisition_unavailable"},
        status_code=409,
    )


@router.get("/api/acquisition/status", dependencies=[Depends(user_guard)])
async def acquisition_status():
    runtime = _get_runtime()
    if runtime is None:
        return nocache_json(
            {
                "enabled": False,
                "status": "unavailable",
                "reason": "acquisition_runtime_unavailable",
                "states": {},
                "reuse": {
                    "reused": 0,
                    "generated": 0,
                    "blocked": 0,
                    "abandoned": 0,
                    "reuse_rate": 0.0,
                },
                "packages": [],
                "audit": {
                    "status": "unavailable",
                    "events": 0,
                    "summarized_events": 0,
                    "chain_valid": False,
                },
            }
        )
    return nocache_json(runtime.status_snapshot())


@router.get("/api/acquisition/events", dependencies=[Depends(user_guard)])
async def acquisition_events(
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
):
    runtime = _get_runtime()
    if runtime is None:
        return nocache_json(
            {"enabled": False, "status": "unavailable", "events": []}
        )
    snapshot = runtime.status_snapshot()
    return nocache_json(
        {
            "enabled": bool(snapshot.get("enabled")),
            "status": str(snapshot.get("status", "unavailable")),
            "events": runtime.list_audit_events(limit=limit),
        }
    )


@router.get("/api/acquisition/ledger/export", dependencies=[Depends(admin_guard)])
async def acquisition_export():
    runtime = _get_runtime()
    if runtime is None:
        return _unavailable()
    return nocache_json(runtime.export_audit())


@router.post("/api/acquisition/ledger/purge", dependencies=[Depends(admin_guard)])
async def acquisition_purge(body: AcquisitionPurgeBody):
    if body.confirm != "PURGE ACQUISITION DETAIL":
        return nocache_json(
            {"status": "refused", "reason": "exact_owner_confirmation_required"},
            status_code=409,
        )
    runtime = _get_runtime()
    if runtime is None:
        return _unavailable()
    result = runtime.purge_audit(actor="owner")
    return nocache_json({"status": "purged", **result})


_SkillName = Annotated[
    str,
    Path(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]{0,63}$"),
]


@router.post("/api/acquisition/{name}/revoke", dependencies=[Depends(admin_guard)])
async def acquisition_revoke(name: _SkillName):
    runtime = _get_runtime()
    if runtime is None:
        return _unavailable()
    try:
        return nocache_json(await runtime.revoke(name))
    except (PromotionError, PackageStoreError, KeyError, ValueError):
        return nocache_json(
            {"status": "refused", "reason": "revocation_refused"},
            status_code=409,
        )


@router.post("/api/acquisition/{name}/rollback", dependencies=[Depends(admin_guard)])
async def acquisition_rollback(name: _SkillName):
    runtime = _get_runtime()
    if runtime is None:
        return _unavailable()
    try:
        return nocache_json(await runtime.rollback(name))
    except (PromotionError, PackageStoreError, KeyError, ValueError):
        return nocache_json(
            {"status": "refused", "reason": "rollback_refused"},
            status_code=409,
        )


# ── A8-i: the production trigger for the governed acquisition loop ─────────────
# `AcquisitionRuntime.synthesize_and_propose` had no caller outside tests and the
# hermetic reality pack, so the H32 loop could only be driven from a Python shell
# and owner gate A8's §N walkthrough was unrunnable. This admin route drives
# gap → reuse-check → research → strict-local generate → sandbox verify →
# propose; every downstream rail (AST allowlist, grounding gate, sandbox,
# permanent owner approval, kernel gate) is unchanged and still holds.

_RequestId = Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")]


class AcquisitionCaseBody(BaseModel):
    model_config = {"extra": "forbid"}

    input: Any
    expected: Any


class AcquisitionDriveBody(BaseModel):
    model_config = {"extra": "forbid"}

    entrypoint: str = Field("run", pattern=r"^[a-z_][a-z0-9_]{0,63}$")
    cases: list[AcquisitionCaseBody] = Field(..., min_length=1, max_length=16)


def _sandbox_runner():
    """Sandbox command runner override — ``None`` selects the real Docker runner.
    Module-level so hermetic tests inject a fake sequence the way the H32 suite
    already does for ``synthesize_and_propose``'s ``runner=`` parameter."""
    return None


def _drive_seams():
    """Build the production research/generate seams, or an honest degraded 409.

    Returns ``(research, generate, None)`` on success, else ``(None, None,
    JSONResponse)``. Module-level so tests inject fakes the way they already do
    for ``_get_runtime``. The research path is constructed FRESH from
    ``SEARXNG_URL`` — never from the live websearch plugin, whose Tavily key
    would make the strict-local research backend refuse (cloud is forbidden on
    this path by design)."""
    import os

    from agents.core.acquisition.llm_synth import draft_plan, generate_capability
    from agents.core.acquisition.research import GovernedResearch, ResearchError
    from agents.core.plugins.degradation import degraded

    orch = get_orch()
    llm_router = getattr(orch, "llm_router", None) if orch is not None else None
    try:
        if llm_router is None:
            raise RuntimeError("no llm router")
        llm_router.local_backend  # noqa: B018 — probes the strict-local backend
    except RuntimeError:
        return None, None, nocache_json(
            degraded(
                {"status": "refused"},
                reason="local_llm_required",
                needs=["a running LM Studio or Ollama local backend"],
            ),
            status_code=409,
        )

    try:
        research = GovernedResearch.from_websearch(
            searxng_url=os.environ.get("SEARXNG_URL", "").strip(),
            enabled=True,
            network_consent=True,
            draft=lambda goal, references: draft_plan(goal, references, router=llm_router),
        )
    except ResearchError:
        return None, None, nocache_json(
            degraded(
                {"status": "refused"},
                reason="searxng_backend_required",
                needs=["SEARXNG_URL"],
            ),
            status_code=409,
        )

    async def _generate(prompt: dict) -> dict:
        return await generate_capability(prompt, router=llm_router)

    return research, _generate, None


@router.post("/api/acquisition/{request_id}/drive", dependencies=[Depends(admin_guard)])
async def acquisition_drive(request_id: _RequestId, body: AcquisitionDriveBody):
    """Drive the governed acquisition loop for a captured capability gap."""
    from agents.core.plugins.degradation import degraded

    runtime = _get_runtime()
    if runtime is None:
        return _unavailable()
    if not runtime.is_enabled():
        return nocache_json(
            degraded(
                {"status": "refused"},
                reason="acquisition_disabled",
                needs=["settings: acquisition.enabled"],
            ),
            status_code=409,
        )
    store = getattr(runtime, "request_store", None)
    request = store.get(request_id) if store is not None else None
    if request is None:
        return nocache_json(
            {"status": "refused", "reason": "capability_request_not_found"},
            status_code=404,
        )

    # Reuse-before-generate: an available install/reuse candidate outranks synthesis.
    # A resolver failure degrades to synthesis (still fully governed), never a 500.
    try:
        decision = runtime.resolve_gap(request_id, get_orch())
    except Exception:
        logger.warning("acquisition reuse resolution failed; proceeding", exc_info=True)
        decision = None
    if decision is not None and decision.outcome != "no_reuse":
        return nocache_json(
            {
                "status": "refused",
                "reason": "reuse_available",
                "outcome": decision.outcome,
                "candidate": getattr(decision, "candidate_id", None),
            },
            status_code=409,
        )

    from agents.core.acquisition.generator import CapabilityContract, ContractCase

    try:
        # The contract is system-owned: the goal comes from the captured request,
        # never from the caller — only entrypoint/cases are caller-supplied.
        contract = CapabilityContract(
            goal=request.goal,
            entrypoint=body.entrypoint,
            cases=tuple(
                ContractCase(input=case.input, expected=case.expected) for case in body.cases
            ),
        )
    except (TypeError, ValueError) as exc:
        return nocache_json(
            {"status": "refused", "reason": "invalid_contract", "detail": str(exc)[:200]},
            status_code=400,
        )

    if runtime.ensure_promotion() is None:
        return nocache_json(
            degraded(
                {"status": "refused"},
                reason="promotion_unavailable",
                needs=[
                    "JARVIS_ACQUISITION_SANDBOX_IMAGE (digest-pinned)",
                    "bound tool_rpc + marketplace (autonomy_coordinator wiring)",
                ],
            ),
            status_code=409,
        )

    research, generate, degrade_response = _drive_seams()
    if degrade_response is not None:
        return degrade_response

    try:
        proposal = await runtime.synthesize_and_propose(
            request_id,
            contract=contract,
            research=research,
            generate=generate,
            runner=_sandbox_runner(),
        )
    except Exception:  # SynthesisError is a RuntimeError, not GenerationError
        logger.warning("acquisition drive failed", exc_info=True)
        proposal = None
    if proposal is None:
        updated = store.get(request_id)
        return nocache_json(
            {
                "status": "refused",
                "reason": "synthesis_failed",
                "request_status": updated.status.value if updated is not None else "unknown",
            },
            status_code=409,
        )
    return nocache_json(
        {
            "status": "proposed",
            "proposal_id": proposal.proposal_id,
            "name": proposal.name,
            "request_status": "approval_pending",
        }
    )


__all__ = ["AcquisitionCaseBody", "AcquisitionDriveBody", "AcquisitionPurgeBody", "router"]
