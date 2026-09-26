"""Onboarding / local-docs endpoints (H12.2) — extracted from web.py (CLN-3).

"Drop a folder → private chat with your docs": index an owner-configured local
folder (selected by key, never a raw request path) into memory, offline.
"""

from fastapi import APIRouter, Depends
from agents.core.routers._deps import user_guard
from pydantic import BaseModel, Field

from agents.core.llm.local_model_inventory import get_local_model_inventory
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
            {"error": f"unknown folder key '{body.key}'", "available": sorted(folders)},
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
_CHAT_ROUTING_PROBE = "Hello Jarvis — first-run check."
_CLOUD_ROUTE_PROVIDERS = {
    "claude": "claude",
    "cloud": "gemini",
    "cloud-fallback": "gemini",
    "cloud-flash": "gemini",
    "cloud-pro": "gemini",
}
_LOCAL_ROUTES = {"local", "local-deep", "local-fallback"}
#: ``HybridRouter.select_backend`` rewrites every ``cloud*`` route to this one when the
#: owner configured ``llm.compatible_provider`` (xai / openai-responses / openrouter /
#: openai-compatible) — a Jarvis turn then runs on ``router._compatible_backend``.
_COMPATIBLE_ROUTE = "cloud-compatible"


def _clean_string(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _clean_model_id(value) -> str | None:
    model_id = _clean_string(value)
    return None if model_id is None or model_id.lower() == "none" else model_id


def _canonical_provider(value) -> str | None:
    provider = _clean_string(value)
    if provider is None:
        return None
    aliases = {
        "lmstudio": "lm-studio",
        "lm_studio": "lm-studio",
        "ollama-howard": "ollama",
    }
    return aliases.get(provider.lower(), provider.lower())


def _fallback_backend(llm_router) -> str:
    backend = _canonical_provider(getattr(llm_router, "_backend_name", None))
    if backend and backend != "none":
        return backend
    name = _clean_string(getattr(llm_router, "name", None))
    return name or "none"


def _selected_provider(llm_router, selected_backend, route: str) -> str | None:
    if route in _CLOUD_ROUTE_PROVIDERS:
        attr = "_claude_backend" if route == "claude" else "_gemini_backend"
        expected = getattr(llm_router, attr, None)
        return (
            _CLOUD_ROUTE_PROVIDERS[route]
            if expected is not None and expected is selected_backend
            else None
        )
    if route in _LOCAL_ROUTES:
        expected = getattr(llm_router, "_backend", None)
        if expected is not None and expected is selected_backend:
            return _canonical_provider(getattr(llm_router, "_backend_name", None))
        return None
    if route == "ollama-howard":
        expected = getattr(llm_router, "_ollama_backend", None)
        return "ollama" if expected is not None and expected is selected_backend else None
    if route == _COMPATIBLE_ROUTE:
        expected = getattr(llm_router, "_compatible_backend", None)
        if expected is None or expected is not selected_backend:
            return None
        # The adapter's own provider id (the one job_selection matches a pin against).
        return _canonical_provider(getattr(getattr(expected, "profile", None), "id", None)) or (
            _COMPATIBLE_ROUTE
        )
    return None


def _resident_truth(inventory: dict) -> tuple[list[dict[str, str]], set[tuple[str, str]]]:
    residents: list[dict[str, str]] = []
    pairs: set[tuple[str, str]] = set()
    raw = inventory.get("resident_models")
    if not isinstance(raw, list):
        return residents, pairs
    for row in raw:
        if not isinstance(row, dict):
            continue
        provider = _canonical_provider(row.get("provider"))
        model_id = _clean_model_id(row.get("id"))
        if provider is None or model_id is None:
            continue
        residents.append({"provider": provider, "id": model_id})
        pairs.add((provider, model_id))
    return residents, pairs


def _provider_residency_state(inventory: dict, provider: str | None) -> str:
    for row in inventory.get("providers") or []:
        if not isinstance(row, dict):
            continue
        if _canonical_provider(row.get("name")) != provider:
            continue
        state = _clean_string(row.get("residency_state"))
        if state in {"known", "unknown", "offline"}:
            return state
    aggregate = _clean_string(inventory.get("residency_state"))
    return aggregate if aggregate in {"known", "unknown", "offline"} else "unknown"


#: Why ``_model_snapshot`` reached its verdict — one named reason per outcome, so a
#: terminal check (``scripts/doctor.py`` ``runtime_resolves``, ``nerva status``'s
#: ``runnable:`` line) reports the same cause the HUD acts on, without re-deriving it.
#: ready=True: ``resident`` (local pair proven resident) · ``cloud_selected`` (the
#: router chose a cloud route — Gemini, Claude or the owner's ``cloud-compatible``
#: adapter — and handed back the very backend that route names).
#: ready=False: ``route_unselected`` · ``provider_unresolved`` (the router handed back
#: a backend that is not the one its route names, or a route this check does not know —
#: an indirect fallback) · ``provider_offline`` · ``configured_not_resident``.
#: ready=None: ``router_unavailable`` · ``inventory_unavailable`` · ``residency_unknown``.
#: H380 — a selected cloud route whose provider did not accept its key.
CLOUD_PROBE_REASONS = frozenset({
    "cloud_auth_failed", "cloud_forbidden", "cloud_rate_limited", "cloud_error",
    "cloud_unreachable", "cloud_refused", "cloud_not_configured",
})
MODEL_READINESS_REASONS = frozenset({
    "resident", "cloud_selected", *CLOUD_PROBE_REASONS,
    "route_unselected", "provider_unresolved", "provider_offline", "configured_not_resident",
    "router_unavailable", "inventory_unavailable", "residency_unknown",
})


#: The route's provider name (``_selected_provider``) → the provider profile it uses.
_PROBE_PROFILES = {"claude": "anthropic", "gemini": "gemini"}


async def _cloud_probe(llm_router, provider: str) -> dict | None:
    """H380: the provider's own verdict on the key this route would use (cached and
    rate-limited in ``provider_probe``), or None when no profile names it."""
    from agents.core.llm import provider_probe

    profile_id = _PROBE_PROFILES.get(provider, provider)
    pool = {"anthropic": "_anthropic_pool", "gemini": "_gemini_pool"}.get(profile_id)
    key = None
    try:
        key = getattr(getattr(llm_router, pool, None), "current_key", lambda: None)() if pool else None
    except Exception:
        key = None
    try:
        return await provider_probe.probe(profile_id, key=key or None)
    except KeyError:
        return None


async def _model_snapshot() -> dict:
    """Return the model truth for the exact route used by a short Jarvis chat.

    Catalog residency is observability, not routing: a model resident on some
    other provider must never unlock ``Say hello``.  Selection is performed
    without generation; a local route is ready only when that provider/model
    pair is proven resident, while a selected cloud route is ready by the
    router's own availability decision.

    This is Nerva's ``setup.runtime_check`` (Hermes, H242): the same
    ``select_backend`` call a Jarvis turn makes, not "some runtime answers" or
    "some credential exists".  ``reason`` names the verdict (see
    ``MODEL_READINESS_REASONS``); ``selected_provider``/``selected_model`` name
    what the route asked for even when it is not runnable, while
    ``active_provider``/``active_model`` stay None unless it is.  Read-only.
    """
    orch = get_orch()
    llm_router = getattr(orch, "llm_router", None) if orch else None
    if llm_router is None:
        return {
            "backend": "none",
            "active_model": None,
            "configured_model": None,
            "resident_models": [],
            "residency_state": "offline",
            "active_provider": None,
            "route": None,
            "ready": None,
            "reason": "router_unavailable",
            "selected_provider": None,
            "selected_model": None,
            "cloud_configured": False,
            "cloud_probe": None,
        }

    cloud_configured = bool(
        getattr(llm_router, "_claude_backend", None)
        or getattr(llm_router, "_gemini_backend", None)
        or getattr(llm_router, "_compatible_backend", None)
    )
    try:
        selected_backend, selected_model, route = llm_router.select_backend(
            "jarvis", _CHAT_ROUTING_PROBE
        )
        selected_model = _clean_model_id(selected_model)
        route = _clean_string(route)
        route_selected = selected_model is not None and route is not None
    except Exception:
        selected_model = None
        route = None
        route_selected = False

    try:
        inventory = await get_local_model_inventory(router=llm_router)
        inventory_available = True
    except Exception:
        inventory = {
            "backend": _fallback_backend(llm_router),
            "configured_model": getattr(llm_router, "active_model", None),
            "resident_models": [],
            "residency_state": "unknown",
            "providers": [],
        }
        inventory_available = False

    residents, resident_pairs = _resident_truth(inventory)
    configured_model = _clean_model_id(inventory.get("configured_model"))
    provider = _selected_provider(llm_router, selected_backend, route) if route_selected else None
    residency_state = _provider_residency_state(inventory, provider)
    backend = (
        provider or _canonical_provider(inventory.get("backend")) or _fallback_backend(llm_router)
    )

    ready: bool | None
    probe = None
    if not route_selected:
        ready, reason = False, "route_unselected"
    elif provider is None:
        ready, reason = False, "provider_unresolved"
    elif route in _CLOUD_ROUTE_PROVIDERS or route == _COMPATIBLE_ROUTE:
        # The router itself chose this cloud backend (policy, spend cap and fallback
        # mode already applied) and handed back the very object its route names. H380:
        # it is runnable only when the provider accepts the key it would use.
        probe = await _cloud_probe(llm_router, provider)
        verdict = (probe or {}).get("verdict")
        if probe is None or verdict in ("ok", "no_listing"):
            ready, reason = True, "cloud_selected"
        else:
            ready, reason = False, f"cloud_{verdict}"
    elif not inventory_available:
        ready, reason = None, "inventory_unavailable"
    elif (provider, selected_model) in resident_pairs:
        ready, reason = True, "resident"
    elif residency_state == "unknown":
        ready, reason = None, "residency_unknown"
    elif residency_state == "offline":
        ready, reason = False, "provider_offline"
    else:
        ready, reason = False, "configured_not_resident"

    return {
        "backend": backend,
        "active_model": selected_model if ready is True else None,
        "active_provider": provider if ready is True else None,
        "configured_model": configured_model,
        "resident_models": residents,
        "residency_state": residency_state,
        "route": route,
        "ready": ready,
        "reason": reason,
        "selected_provider": provider,
        "selected_model": selected_model if route_selected else None,
        "cloud_configured": cloud_configured,
        # H380: what the provider said about the key (no key, no body).
        "cloud_probe": None if probe is None else {
            k: probe.get(k) for k in ("provider", "verdict", "status_code", "checked_at", "cached")},
    }


def _completed_steps() -> list[str]:
    """Steps finished, derived from recorded funnel events — so onboarding resumes across
    reloads without a wizard-specific store."""
    from agents.core import analytics_store

    counts = analytics_store.event_counts(days=3650)
    return [s["key"] for s in _WIZARD_STEPS if counts.get(f"funnel.{s['key']}.complete")]


def _starter_outcomes(
    *, model_ready: bool | None, model_route: str | None, folders: list[str]
) -> list[dict]:
    """Project runtime truth into three bounded, consumer-facing first outcomes.

    A manifest only proves that a plugin exists.  ``live`` requires the canonical
    capability registry's runtime honesty verdict, so an unloaded or unconfigured
    plugin is always shown as ``needs_setup``.  No credential values are read or
    returned here.
    """
    from agents.core.observability.capability_registry import build_records

    orch = get_orch()
    records = build_records(orch)
    plugin_live = {
        record.id.removeprefix("plugin:"): (
            record.detail.get("honesty", {}).get("status") == "live"
            and not record.detail.get("degraded", False)
        )
        for record in records
        if record.kind == "plugin"
    }

    def outcome(
        key: str,
        title: str,
        *,
        ready: bool,
        setup: str,
        privacy: str,
        changes: str,
    ) -> dict:
        return {
            "key": key,
            "title": title,
            "status": "live" if ready else "needs_setup",
            "reason": "Ready to use." if ready else setup,
            "setup": None if ready else setup,
            "privacy": privacy,
            "changes": changes,
        }

    model_setup = (
        "Start a local model, or connect an API account. ChatGPT Plus and Claude Pro "
        "subscriptions do not include API access."
    )
    google_ready = plugin_live.get("gmail", False) and plugin_live.get(
        "google-calendar", False
    )
    plan_setup = model_setup if model_ready is not True else "Connect Google in Settings."
    docs_setup = model_setup if model_ready is not True else "Choose a local folder in Settings."
    research_setup = model_setup if model_ready is not True else "Enable web research in Settings."
    documents_privacy = (
        "local_only" if model_route in _LOCAL_ROUTES else "local_storage_cloud_model"
    )
    connected_account_privacy = (
        "third_party_account"
        if model_route in _LOCAL_ROUTES
        else "third_party_account_cloud_model"
    )

    return [
        outcome(
            "plan_my_day",
            "Plan my day",
            ready=model_ready is True and google_ready,
            setup=plan_setup,
            privacy=connected_account_privacy,
            changes="none",
        ),
        outcome(
            "private_documents",
            "Use my private documents",
            ready=model_ready is True and bool(folders),
            setup=docs_setup,
            privacy=documents_privacy,
            changes="none",
        ),
        outcome(
            "research_web",
            "Research the web",
            ready=model_ready is True and plugin_live.get("websearch", False),
            setup=research_setup,
            privacy="public_web",
            changes="none",
        ),
    ]


@router.get("/api/onboarding/wizard", dependencies=[Depends(user_guard)])
async def onboarding_wizard():
    """First-run wizard state (H23.20): ordered steps + which are complete + cold-start
    guidance. Completion derives from the activation funnel, so the HUD can resume."""
    done = _completed_steps()
    ready = (await _model_snapshot())["ready"]
    hint = None
    if ready is False:
        hint = (
            "No conversational model is loaded — load one in LM Studio or Ollama, "
            "or add a cloud API key in Admin → settings."
        )
    elif ready is None:
        hint = "Model readiness could not be verified — check the model server and refresh."
    from agents.core import product_posture

    orch = get_orch()
    posture = product_posture.snapshot(getattr(orch, "_runtime_settings", {}) if orch else {})
    return nocache_json(
        {
            "steps": _WIZARD_STEPS,
            "completed": done,
            "complete": len(done) >= len(_WIZARD_STEPS),
            "model_ready": ready,
            "hint": hint,
            "product_posture": posture,
        }
    )


@router.get("/api/onboarding/command-center", dependencies=[Depends(user_guard)])
async def command_center():
    """0.19 First-Run Command Center — install health + model + first actions, one read.

    The unified first-run screen's single fetch: the /readyz verdict (shared
    ``readiness_snapshot``), the model backend truth, the H23.20 wizard state,
    honest FIRST ACTIONS whose ``ready`` flags derive from live state, and three
    bounded consumer outcomes with setup/privacy/effect truth — a
    chat action is never presented ready without a model, and the local-docs
    action stays not-ready (with the reason) until the owner configures a
    folder. Read-only; the actions point at existing governed endpoints and the
    outcome projection never reads or returns credential values.
    """
    from agents import __version__
    from agents.core.routers.ops import readiness_snapshot

    install = {**readiness_snapshot(), "version": __version__}

    model = await _model_snapshot()
    model_ready = model["ready"]

    done = _completed_steps()
    hint = None
    if model_ready is False:
        hint = (
            "No conversational model is loaded — load one in LM Studio or Ollama, "
            "or add a cloud API key in Admin → settings."
        )
    elif model_ready is None:
        hint = "Model readiness could not be verified — check the model server and refresh."
    wizard = {
        "steps": _WIZARD_STEPS,
        "completed": done,
        "complete": len(done) >= len(_WIZARD_STEPS),
        "hint": hint,
    }

    chat_ready = bool(install["ready"] and model_ready)
    if chat_ready:
        chat_reason = None
    elif not install["ready"]:
        chat_reason = "still starting"
    elif model_ready is None:
        chat_reason = "model readiness unknown"
    else:
        chat_reason = "model not loaded"
    folders = sorted(_configured_doc_folders())
    first_actions = [
        {
            "key": "say_hello",
            "title": "Say hello",
            "kind": "chat",
            "path": "/chat",
            "ready": chat_ready,
            "reason": chat_reason,
        },
        {
            "key": "morning_brief",
            "title": "Get your morning brief",
            "kind": "get",
            "path": "/autonomy/brief",
            "admin": True,
            "ready": bool(install["ready"]),
            "reason": None if install["ready"] else "still starting",
        },
        {
            "key": "index_docs",
            "title": "Chat with a folder of your docs",
            "kind": "post",
            "path": "/api/local-docs/index",
            "ready": bool(folders),
            "folders": folders,
            "reason": None
            if folders
            else "no folder configured — set local_docs.folders in Admin → settings",
        },
    ]
    starter_outcomes = _starter_outcomes(
        model_ready=model_ready,
        model_route=model.get("route"),
        folders=folders,
    )
    return nocache_json(
        {
            "install": install,
            "model": model,
            "wizard": wizard,
            "first_actions": first_actions,
            "starter_outcomes": starter_outcomes,
        }
    )


class FunnelBody(BaseModel):
    step: str = Field(..., max_length=64)
    event: str = Field("complete", max_length=32)  # "start" | "complete" | …


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
