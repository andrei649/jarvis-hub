"""The HUD's Integrations panel: one list, keys set in the HUD, a test, and a consented choice.

Owner/admin only (``admin_guard``) on every route, reads included: the list says which
keys are set. A key goes in once and never comes back out: the answers carry "set",
where it was set (``env`` / ``hub``) and at most its last four characters
(``integration_keys``). Validation errors are answered without the rejected input, so a
malformed request cannot echo a key either.

* ``GET  /api/admin/integrations`` — the list (``integrations_catalog.listing``).
* ``PUT  /api/admin/integrations/{entry_id}/key`` — store a key (encrypted secret store)
  and put it in effect now; the LLM router re-detects when the key is one it holds.
* ``DELETE /api/admin/integrations/{entry_id}/key`` — remove it, in effect now.
  A key set in ``.env`` is refused on both (409 ``env_managed``): ``.env`` wins.
* ``POST /api/admin/integrations/{entry_id}/test`` — a model provider: ``provider_probe``
  for that provider only (an adopted one through its pinned client); a search backend:
  one search through the ``websearch`` egress client, that backend only, no rescue.
* ``POST /api/admin/integrations/{entry_id}/use`` — choose it. A model provider goes
  through the same selection guards as the settings write (``admin._guard_selection``:
  ``acknowledge_training`` / ``confirm_expensive``, the consent row written to the audit
  log before the choice is stored); an adopted search backend asks the same two
  acknowledgements and its consent row must land before the choice is stored.
* ``DELETE /api/admin/integrations/search-choice`` — back to ``auto``.
* G19: a **video** provider (adopted from Hermes) is chosen the same way: ``use`` asks the
  data-policy and cost acknowledgements, writes a required ``video_provider_consent`` audit
  row, then stores ``JARVIS_VIDEO_PROVIDER``; ``DELETE /api/admin/integrations/video-choice``
  turns video generation off again. Its test needs no request: a video costs money, so it
  only checks that the key is set (each video is its own approval card with its cost).
"""

from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool, StrictStr

from agents.core.app_state import get_orch
from agents.core.web_helpers import nocache_json

from ._deps import admin_guard

logger = logging.getLogger("jarvis.routers.integrations_setup")

ENTRY_PATTERN = r"^(search|model|video)\.[a-z0-9][a-z0-9._-]{0,127}$"
TEST_QUERY = "Nerva connection test"


class _QuietRoute(APIRoute):
    """A validation error is answered without FastAPI's detail, which repeats the input."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request):
            try:
                return await handler(request)
            except RequestValidationError:
                return nocache_json({"error": "invalid_integration_request"}, status_code=422)

        return guarded


router = APIRouter(route_class=_QuietRoute, tags=["integrations"])


async def same_origin_write(request: Request) -> None:
    """A panel write must come from this origin (H157's rule for settings writes). On a
    default install the admin guard trusts loopback, so a page the owner visits could post
    a body that needs no browser pre-check: a POST must be JSON (which forces the pre-check
    the CORS allow-list decides), and any write a browser marks cross-site is refused."""
    if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        raise HTTPException(status_code=403, detail="an integrations change must come from this origin")
    if request.method == "POST":
        kind = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if kind != "application/json":
            raise HTTPException(status_code=415, detail="expected application/json")


WRITE_GUARDS = [Depends(admin_guard), Depends(same_origin_write)]


class KeyBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    value: SecretStr = Field(min_length=1, max_length=4096)
    #: The owner confirmed this is the same key for the other entries that read its name.
    same_key: StrictBool = False
    #: For a provider used as soon as its key is set (Gemini): its data-policy consent.
    acknowledge_training: StrictBool = False


class UseBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model: StrictStr = Field("", max_length=256)
    confirm_expensive: StrictBool = False
    acknowledge_training: StrictBool = False


def _entry(entry_id: str):
    from agents.core import integrations_catalog

    return integrations_catalog.find(entry_id)


def _not_found() -> JSONResponse:
    return nocache_json({"error": "unknown_integration"}, status_code=404)


def _env_managed(name: str) -> JSONResponse:
    return nocache_json({"error": "env_managed", "name": name,
                         "detail": f"{name} is set in .env (or the hub's environment); change it there"},
                        status_code=409)


async def _audit(preview: str, action: str, *, required: bool = False) -> None:
    from agents.core.security.types import SecurityEvent, SecurityEventType

    orch = get_orch()
    audit = getattr(orch, "audit", None) if orch else None
    try:
        if audit is None:
            raise RuntimeError("no audit log")
        await asyncio.to_thread(audit.log, SecurityEvent(
            event_type=SecurityEventType.SETTINGS_CHANGE, timestamp=time.time(),
            content_preview=preview, action_taken=action))
    except Exception:
        if required:
            raise
        logger.warning("could not audit an integrations change (%s)", action)


async def _redetect_router() -> bool:
    """Rebuild the LLM router's backends from the keys and settings now in effect."""
    from agents.core.env_config import env_str

    orch = get_orch()
    llm = getattr(orch, "llm_router", None) if orch else None
    if llm is None or not callable(getattr(llm, "detect", None)):
        return False
    from .models_llm import _model_switch_lock

    async with _model_switch_lock:
        if hasattr(llm, "gemini_api_key"):
            llm.gemini_api_key = env_str("GEMINI_API_KEY")
        if hasattr(llm, "anthropic_api_key"):
            llm.anthropic_api_key = env_str("ANTHROPIC_API_KEY")
        await llm.detect()
    return True


async def _apply_live(entry) -> str:
    """Bring the running hub to the key now in effect: ``now`` or ``next use``."""
    from agents.core import integrations_catalog
    from agents.core.env_config import env_str

    if entry.kind == integrations_catalog.KIND_SEARCH:
        if entry.name == "tavily":
            orch = get_orch()
            plugin = (getattr(orch, "plugins", {}) or {}).get("websearch") if orch else None
            if plugin is not None:
                plugin.tavily_api_key = env_str("TAVILY_API_KEY")
        return "now"           # the adopted providers read their key on every call
    selected = integrations_catalog._selected_compatible()
    if entry.name in ("gemini", "anthropic") or entry.name == selected:
        try:
            await _redetect_router()
        except Exception:      # noqa: BLE001 — the key is stored; the router keeps its last state
            logger.warning("router re-detect after a key change failed", exc_info=False)
            return "next use"
    return "now"


def _row(entry_id: str) -> dict | None:
    from agents.core import integrations_catalog

    listing = integrations_catalog.listing()
    return next((r for r in listing["integrations"] if r["id"] == entry_id), None)


@router.get("/api/admin/integrations", dependencies=[Depends(admin_guard)])
async def integrations_list():
    from agents.core import integrations_catalog

    return nocache_json(await asyncio.to_thread(integrations_catalog.listing))


@router.put("/api/admin/integrations/{entry_id}/key", dependencies=WRITE_GUARDS)
async def integration_key_put(body: KeyBody, entry_id: str = Path(pattern=ENTRY_PATTERN)):
    from agents.core import integration_keys, integrations_catalog

    entry = _entry(entry_id)
    if entry is None or not entry.keys:
        return _not_found()
    # Always the entry's OWN primary name: never a sibling's name that happens to be set.
    name = entry.keys[0]
    if integration_keys.env_owned(name):
        return _env_managed(name)
    all_entries = integrations_catalog.entries()
    shared = [e for e in all_entries if e.id != entry.id and name in e.keys]
    if shared and not body.same_key:
        names = ", ".join(e.display_name for e in shared)
        return nocache_json({
            "error": "shared_key", "name": name, "shared_with": [e.id for e in shared],
            "detail": f"{name} is also read by {names}. Saving it here gives them the same key "
                      "(each still needs its own consent to be used). Confirm it is the same key "
                      "for all of them."}, status_code=409)
    consent = _key_consent(entry)
    if consent and not body.acknowledge_training:
        return nocache_json({"error": "selection_guard", "detail": consent["message"],
                             "needs": ["acknowledge_training"], "guards": [consent]}, status_code=409)
    if consent:
        try:
            await _audit(f"consent (integrations): {entry.display_name} ({entry.host}) is used as soon as its "
                         f"key is set, knowing {consent['message']}", "model_training_consent", required=True)
        except Exception:
            return nocache_json({"error": "consent_not_recorded",
                                 "detail": "the acknowledgement could not be written to the audit log; "
                                           "nothing was changed"}, status_code=503)
    try:
        await asyncio.to_thread(integration_keys.set_key, name, body.value.get_secret_value(),
                                allowed=integrations_catalog.managed_keys(), owner=entry.id,
                                keep_owners=body.same_key)
    except integration_keys.EnvManaged:
        return _env_managed(name)
    except ValueError:
        return nocache_json({"error": "invalid_key"}, status_code=422)
    for e in [entry, *shared]:
        integrations_catalog.LAST_TEST.pop(e.id, None)
    applied = await _apply_live(entry)
    await _audit(f"integrations: key {name} set for {entry_id}"
                 + (f" (also read by {', '.join(e.id for e in shared)})" if shared else "")
                 + " (stored encrypted; value not logged)", "integration_key_set")
    return nocache_json({"ok": True, "applied": applied, "integration": _row(entry_id)})


def _key_consent(entry) -> dict | None:
    """A provider the router uses as soon as its key is set (Gemini, Anthropic) has no
    "use" step, so its data-policy consent is asked when the key is saved."""
    from agents.core import integrations_catalog

    if entry.kind != integrations_catalog.KIND_MODEL or entry.selectable:
        return None
    if entry.data_policy not in ("unknown", "trains-on-inputs"):
        return None
    knowing = ("the vendor may train on your prompts" if entry.data_policy == "trains-on-inputs"
               else "how it handles your prompts has not been verified")
    return {"guard": "data_policy", "needs": "acknowledge_training", "setting": entry.keys[0],
            "provider": entry.name, "model": "",
            "message": f"{entry.display_name} answers as soon as this key is set; {knowing}"
                       + (f" — {entry.data_policy_note}" if entry.data_policy_note else ""),
            "detail": {"policy": entry.data_policy, "provider": entry.name}}


@router.delete("/api/admin/integrations/{entry_id}/key", dependencies=WRITE_GUARDS)
async def integration_key_delete(entry_id: str = Path(pattern=ENTRY_PATTERN)):
    """Remove what THIS entry set: its claim on each stored key. A key another entry also
    vouched for stays for that one; a ``.env`` key stays in effect (an older stored copy
    of it is purged, so it cannot come back when the ``.env`` line goes)."""
    from agents.core import integration_keys, integrations_catalog

    entry = _entry(entry_id)
    if entry is None or not entry.keys:
        return _not_found()
    mine = [n for n in entry.keys if entry.id in integration_keys.owners(n)]
    if not mine:
        env = next((n for n in entry.keys if integration_keys.env_owned(n)), None)
        if env:
            return _env_managed(env)
        return nocache_json({"ok": True, "removed": [], "kept_for": [], "env_still_set": [],
                             "integration": _row(entry_id)})
    removed, kept, env_set = [], [], []
    for name in mine:
        out = await asyncio.to_thread(integration_keys.release_key, name, entry.id,
                                      allowed=integrations_catalog.managed_keys())
        (removed if out["removed"] else kept).append(name)
        if out["env"]:
            env_set.append(name)
    integrations_catalog.LAST_TEST.pop(entry_id, None)
    applied = await _apply_live(entry)
    await _audit(f"integrations: key removed for {entry_id} (removed {removed}, kept for others {kept})",
                 "integration_key_removed")
    return nocache_json({"ok": True, "applied": applied, "removed": removed, "kept_for": kept,
                         "env_still_set": env_set, "integration": _row(entry_id)})


# ── test ─────────────────────────────────────────────────────────────────────────

_MODEL_SAYS = {
    "ok": "The provider accepted the key.",
    "no_listing": "The provider answered, but has no model list there, so the key was not checked.",
    "auth_failed": "The provider rejected the key. Check that it was copied whole and is still valid.",
    "forbidden": "The provider refused this key access (403). The account may lack a plan or permission.",
    "rate_limited": "The provider is limiting requests right now. Try again in a minute.",
    "error": "The provider answered with an error.",
    "unreachable": "Nerva could not reach the provider (network, DNS or TLS).",
    "refused": "Nerva refused to send the key there (wrong host or protocol).",
    "not_configured": "No key is set yet.",
    "not_cloud": "This provider runs locally and needs no key.",
}

_SEARCH_SAYS = {
    "policy_blocked": "Nerva's egress rules refused the request; nothing was sent.",
    "busy": "Too many searches are running; try again shortly.",
    "timeout": "The search service did not answer in time.",
}


async def _test_model(entry) -> dict:
    from agents.core import integrations_catalog
    from agents.core.llm import provider_probe

    key = integrations_catalog._key_state(entry)
    if not key["set"]:
        return {"ok": False, "verdict": "not_configured", "message": _MODEL_SAYS["not_configured"]}
    if not _may_probe(entry, key):
        others = ", ".join(key["shared_with"]) or "another use"
        return {"ok": False, "verdict": "not_sent",
                "message": f"Not tested: the key in effect ({key['name']}) was not given for {entry.display_name} "
                           f"(it is shared with {others}), so Nerva will not send it to {entry.host or 'this host'}. "
                           "Save a key for this provider here, or choose it with your consent first."}
    # One provider, the one being tested (never probe_all); an adopted provider's probe
    # takes the same destination pin as its backend (provider_probe._send).
    result = await provider_probe.probe(entry.name, force=True)
    verdict = str(result.get("verdict") or "error")
    ok = verdict in provider_probe.WORKING
    message = _MODEL_SAYS.get(verdict, "The provider answered with an error.")
    if verdict == "ok" and result.get("models") is not None:
        message = f"{message} It lists {result['models']} model(s)."
    if result.get("throttled"):
        message = f"{message} (Checked moments ago; showing that result.)"
    return {"ok": ok, "verdict": verdict, "message": message,
            "status_code": result.get("status_code")}


def _may_probe(entry, key: dict) -> bool:
    """``provider_probe``'s rule (a key that belongs to another host is not sent here),
    for one provider: the key in effect was given for this entry (typed for it, or set in
    ``.env`` under a name no other entry reads), or the owner selected this provider, and
    no other profile's base URL claims the key (``_key_for_elsewhere`` for a native one)."""
    from agents.core.llm import provider_probe
    from agents.core.llm.hermes_profiles import is_adopted_profile
    from agents.core.llm.providers import get_profile

    profile = get_profile(entry.name)
    selected = provider_probe._selected_compatible()
    if not key["own"] and selected != entry.name:
        return False
    if is_adopted_profile(profile):
        return True     # its own key (above); the adopted half of the rule is that sharing
    return not provider_probe._key_for_elsewhere(profile, None, selected)


async def _test_search(entry) -> dict:
    from agents.core.plugins import web_providers
    from agents.core.plugins.websearch import WebSearchPlugin

    provider = web_providers.get_search_provider(entry.name)
    if provider is None:
        return {"ok": False, "verdict": "unavailable", "message": "This search service is not loaded in this hub."}
    orch = get_orch()
    plugin = (getattr(orch, "plugins", {}) or {}).get("websearch") if orch else None
    if not isinstance(plugin, WebSearchPlugin):
        from agents.core.env_config import env_str

        plugin = WebSearchPlugin(tavily_api_key=env_str("TAVILY_API_KEY"), backend=entry.name, rescue=False)
    if not web_providers._configured(provider, plugin._view()):
        return {"ok": False, "verdict": "not_configured", "message": "No key is set yet."}
    try:
        # That backend only, through the plugin's ``websearch`` egress client (manifest
        # allowlist, SSRF pinning, kernel egress hook, ledger); no rescue to another.
        rows = await plugin._ask(provider, TEST_QUERY, 1)
    except web_providers.PolicyBlock:
        return {"ok": False, "verdict": "policy_blocked", "message": _SEARCH_SAYS["policy_blocked"]}
    except web_providers.ProviderFailure as exc:
        reason = str(exc) or "provider_failed"
        if reason in ("http_401", "http_403"):
            message = "The search service rejected the key. Check that it was copied whole and is still valid."
        elif reason == "http_429":
            message = "The search service is limiting requests right now. Try again in a minute."
        elif reason == "dns_failed":
            message = "Nerva could not reach the search service (DNS)."
        else:
            message = _SEARCH_SAYS.get(reason, "The search service failed to answer.")
        return {"ok": False, "verdict": "provider_failed", "message": message}
    if not rows:
        return {"ok": True, "verdict": "empty", "message": "The service answered, with no results for the test query."}
    return {"ok": True, "verdict": "ok", "message": f"The search service answered ({len(rows)} result)."}


async def _test_video(entry) -> dict:
    """No request: any video request is billed, so only the key's presence is checked."""
    from agents.core import integrations_catalog

    key = integrations_catalog._key_state(entry)
    if not key["set"]:
        return {"ok": False, "verdict": "not_configured", "message": "No key is set yet."}
    return {"ok": True, "verdict": "not_probed",
            "message": "The key is set. Nerva sends nothing to test it: every video request is billed, "
                       "so the first video's approval card is the test."}


@router.post("/api/admin/integrations/{entry_id}/test", dependencies=WRITE_GUARDS)
async def integration_test(entry_id: str = Path(pattern=ENTRY_PATTERN)):
    from agents.core import integrations_catalog

    entry = _entry(entry_id)
    if entry is None:
        return _not_found()
    try:
        result = await (_test_model(entry) if entry.kind == integrations_catalog.KIND_MODEL
                        else _test_video(entry) if entry.kind == integrations_catalog.KIND_VIDEO
                        else _test_search(entry))
    except Exception as exc:  # noqa: BLE001 — a test failure is a result, never a 500
        logger.warning("integration test for %s failed (type=%s)", entry_id, type(exc).__name__)
        result = {"ok": False, "verdict": "error", "message": "The test could not run."}
    result["at"] = time.time()
    if result.get("verdict") != "not_configured":
        integrations_catalog.LAST_TEST[entry_id] = dict(result)
    return nocache_json({"test": result, "integration": _row(entry_id)})


# ── choose it ────────────────────────────────────────────────────────────────────

def _search_guards(entry) -> list[dict]:
    """The acknowledgements an adopted search backend needs, in the selection-guard shape."""
    from agents.core import integrations_catalog

    if entry.origin != integrations_catalog.ORIGIN_HERMES:
        return []
    base = {"setting": integrations_catalog.WEB_BACKEND, "provider": entry.name, "model": ""}
    return [
        {**base, "guard": "data_policy", "needs": "acknowledge_training",
         "message": f"{entry.display_name} ({entry.host}) receives your search queries; how it handles "
                    "them has not been verified", "detail": {"policy": "unknown", "provider": entry.name}},
        {**base, "guard": "cost", "needs": "confirm_expensive",
         "message": f"{entry.display_name} is a paid service and Nerva has no price for its searches",
         "detail": {"price": "unknown", "provider": entry.name}},
    ]


async def _use_search(entry, body: UseBody):
    from agents.core import integration_keys, integrations_catalog

    if integration_keys.env_owned(integrations_catalog.WEB_BACKEND):
        return _env_managed(integrations_catalog.WEB_BACKEND)
    if not integrations_catalog._key_state(entry)["set"]:
        return nocache_json({"error": "no_key", "detail": f"set a key for {entry.display_name} first"},
                            status_code=409)
    guards = _search_guards(entry)
    given = {"acknowledge_training": body.acknowledge_training is True,
             "confirm_expensive": body.confirm_expensive is True}
    missing = sorted({g["needs"] for g in guards if not given[g["needs"]]})
    if missing:
        return nocache_json({"error": "selection_guard", "detail": "; ".join(g["message"] for g in guards),
                             "needs": missing, "guards": guards}, status_code=409)
    if guards:
        try:
            await _audit(f"consent (integrations): {integrations_catalog.WEB_BACKEND} → {entry.name}, knowing "
                         f"the service's data handling is unverified and it has no known price ({entry.host})",
                         "search_backend_consent", required=True)
        except Exception:
            return nocache_json({"error": "consent_not_recorded",
                                 "detail": "the acknowledgement could not be written to the audit log; "
                                           "nothing was changed"}, status_code=503)
    try:
        await asyncio.to_thread(integration_keys.set_choice, integrations_catalog.WEB_BACKEND, entry.name)
    except integration_keys.EnvManaged:
        return _env_managed(integrations_catalog.WEB_BACKEND)
    if not guards:
        await _audit(f"integrations: {integrations_catalog.WEB_BACKEND} → {entry.name}", "search_backend_chosen")
    return nocache_json({"ok": True, "applied": "now", "integration": _row(entry.id)})


async def _use_model(entry, body: UseBody):
    from . import admin

    if not entry.selectable:
        return nocache_json({"error": "not_selectable",
                             "detail": "this provider is used as soon as its key is set"}, status_code=409)
    model = body.model.strip() or (entry.models[0] if entry.models else "")
    if not model:
        return nocache_json({"error": "model_required", "detail": "name the model to use"}, status_code=422)
    values = {"compatible_provider": entry.name, "compatible_model": model}
    changes = {"llm": values}
    try:
        pair_state = await admin._pair_snapshot(changes)
    except Exception as exc:
        return admin._selection_write_refusal(exc)
    # The same guards, consent rows and refusals as the settings write: this card only
    # collects the acknowledgements; the hub decides.
    guarded = await admin._guard_selection(changes, confirm_expensive=body.confirm_expensive,
                                           acknowledge_training=body.acknowledge_training,
                                           surface="integrations", pair_state=pair_state)
    if isinstance(guarded, JSONResponse):
        return guarded
    from agents.core.settings_db import put_category

    try:
        updated, skipped = await admin._drain_settings_write(
            put_category, "llm", values, expected_pair_revision=pair_state[0] if pair_state else None)
    except Exception as exc:
        return admin._selection_write_refusal(exc)
    if skipped:
        return nocache_json({"error": "not_stored", "skipped": skipped}, status_code=409)
    await admin._audit_settings_change("llm", list(values), values)
    applied = "now"
    try:
        await _redetect_router()
    except Exception:  # noqa: BLE001
        logger.warning("router re-detect after choosing a provider failed", exc_info=False)
        applied = "next use"
    return nocache_json({"ok": True, "applied": applied, "model": model,
                         "guards": [f.as_dict() for f in guarded], "integration": _row(entry.id)})


@router.post("/api/admin/integrations/{entry_id}/use", dependencies=WRITE_GUARDS)
async def integration_use(body: UseBody, entry_id: str = Path(pattern=ENTRY_PATTERN)):
    from agents.core import integrations_catalog

    entry = _entry(entry_id)
    if entry is None:
        return _not_found()
    if entry.kind == integrations_catalog.KIND_SEARCH:
        return await _use_search(entry, body)
    if entry.kind == integrations_catalog.KIND_VIDEO:
        return await _use_video(entry, body)
    return await _use_model(entry, body)


def _video_guards(entry) -> list[dict]:
    from agents.core import integrations_catalog

    base = {"setting": integrations_catalog.VIDEO_CHOICE, "provider": entry.name, "model": ""}
    return [
        {**base, "guard": "data_policy", "needs": "acknowledge_training",
         "message": f"{entry.display_name} ({entry.host}) receives your video prompts and the images you "
                    "animate; how it handles them has not been verified",
         "detail": {"policy": "unknown", "provider": entry.name}},
        {**base, "guard": "cost", "needs": "confirm_expensive",
         "message": f"{entry.display_name} is billed per second of video; each video asks your approval "
                    "with an upper-bound cost first",
         "detail": {"price": "per_second", "provider": entry.name}},
    ]


async def _use_video(entry, body: UseBody):
    from agents.core import integration_keys, integrations_catalog

    if integration_keys.env_owned(integrations_catalog.VIDEO_CHOICE):
        return _env_managed(integrations_catalog.VIDEO_CHOICE)
    if not integrations_catalog._key_state(entry)["set"]:
        return nocache_json({"error": "no_key", "detail": f"set a key for {entry.display_name} first"},
                            status_code=409)
    guards = _video_guards(entry)
    given = {"acknowledge_training": body.acknowledge_training is True,
             "confirm_expensive": body.confirm_expensive is True}
    missing = sorted({g["needs"] for g in guards if not given[g["needs"]]})
    if missing:
        return nocache_json({"error": "selection_guard", "detail": "; ".join(g["message"] for g in guards),
                             "needs": missing, "guards": guards}, status_code=409)
    try:
        await _audit(f"consent (integrations): {integrations_catalog.VIDEO_CHOICE} → {entry.name}, knowing the "
                     f"provider's data handling is unverified and each video is billed ({entry.host})",
                     "video_provider_consent", required=True)
    except Exception:
        return nocache_json({"error": "consent_not_recorded",
                             "detail": "the acknowledgement could not be written to the audit log; "
                                       "nothing was changed"}, status_code=503)
    try:
        await asyncio.to_thread(integration_keys.set_choice, integrations_catalog.VIDEO_CHOICE, entry.name)
    except integration_keys.EnvManaged:
        return _env_managed(integrations_catalog.VIDEO_CHOICE)
    return nocache_json({"ok": True, "applied": "now", "integration": _row(entry.id)})


@router.delete("/api/admin/integrations/video-choice", dependencies=WRITE_GUARDS)
async def integration_video_off():
    """Turn video generation off: no provider is chosen any more."""
    from agents.core import integration_keys, integrations_catalog

    try:
        await asyncio.to_thread(integration_keys.set_choice, integrations_catalog.VIDEO_CHOICE, "")
    except integration_keys.EnvManaged:
        return _env_managed(integrations_catalog.VIDEO_CHOICE)
    await _audit(f"integrations: {integrations_catalog.VIDEO_CHOICE} → off", "video_provider_chosen")
    return nocache_json({"ok": True, "applied": "now"})


@router.delete("/api/admin/integrations/search-choice", dependencies=WRITE_GUARDS)
async def integration_search_auto():
    from agents.core import integration_keys, integrations_catalog

    try:
        await asyncio.to_thread(integration_keys.set_choice, integrations_catalog.WEB_BACKEND, "")
    except integration_keys.EnvManaged:
        return _env_managed(integrations_catalog.WEB_BACKEND)
    await _audit(f"integrations: {integrations_catalog.WEB_BACKEND} → auto", "search_backend_chosen")
    return nocache_json({"ok": True, "applied": "now"})
