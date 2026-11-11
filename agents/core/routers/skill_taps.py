"""G20 skills distribution, H025/H335: skill taps (the owner's trusted skill sources).

Adding a tap queues an approval card (``skills.tap_add`` at the irreversible tier) and does
nothing else; refreshing an approved tap reads its index at the pinned commit through the
kernel's egress gate; search ranks every active source by trust; installing from a tap
hands the tap's pin to the same remote import ``POST /skills/import`` runs
(``routers/skills._import_remote``). The logic is ``skills/taps.py``.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from agents.core.app_state import get_orch
from agents.core.web_helpers import nocache_json

from ._deps import user_guard
from .skill_setup import WRITE_GUARDS, _QuietRoute, _setup_view, _skill, _unavailable

logger = logging.getLogger("jarvis.routers.skill_taps")

TAP_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,99}--[a-z0-9][a-z0-9._-]{0,99}$"
#: The only hosts a tap refresh may reach (the tree listing and the raw files).
TAP_HOSTS = frozenset({"api.github.com", "raw.githubusercontent.com"})

router = APIRouter(route_class=_QuietRoute, tags=["skills"])


# ── H025/H335: skill taps ───────────────────────────────────────────────────────

def _tap_refusal(exc) -> JSONResponse:
    status = {"not_found": 404, "skill_not_in_tap": 404, "exists": 409, "builtin": 409, "reserved": 409,
              "not_approved": 409, "changed_during_refresh": 409, "refused_entry": 422,
              "store_unavailable": 503, "approval_queue_unavailable": 503, "approval_queue_refused": 503,
              "unknown_kind": 503, "fetch_failed": 502, "egress_denied": 403, "too_many_taps": 409,
              "refresh_budget": 413, "bad_index": 502}.get(exc.code, 422)
    body = {"error": exc.code}
    if exc.detail:
        body["detail"] = exc.detail
    return nocache_json(body, status_code=status)


@router.get("/api/skills/taps", dependencies=[Depends(user_guard)])
async def taps_list():
    from agents.core.skills import taps

    try:
        return nocache_json(await asyncio.to_thread(taps.listing))
    except taps.TapRefused as exc:
        return _tap_refusal(exc)


class TapAddBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    repo: StrictStr = Field(min_length=3, max_length=201)
    commit: StrictStr = Field(min_length=40, max_length=40)
    path: StrictStr = Field(default="skills", min_length=1, max_length=256)
    trust: StrictStr = Field(default="community", max_length=16)


@router.post("/api/skills/taps", dependencies=WRITE_GUARDS)
async def taps_add(body: TapAddBody):
    """Queue an approval card for a new trusted source; nothing is fetched or trusted yet."""
    from agents.core.skills import taps

    orch = get_orch()
    if not orch:
        return _unavailable()
    try:
        result = await asyncio.to_thread(taps.request_add, orch, repo=body.repo, commit=body.commit,
                                         path=body.path, trust=body.trust)
    except taps.TapRefused as exc:
        return _tap_refusal(exc)
    return nocache_json({"ok": True, "status": "pending_approval", "task_id": result["pending"],
                         "tap": result["tap"]}, status_code=202)


@router.delete("/api/skills/taps/{tap_id}", dependencies=WRITE_GUARDS)
async def taps_remove(tap_id: str = Path(pattern=TAP_PATTERN)):
    from agents.core.skills import taps

    orch = get_orch()
    if not orch:
        return _unavailable()
    try:
        return nocache_json({"ok": True, **await asyncio.to_thread(taps.remove, orch, tap_id)})
    except taps.TapRefused as exc:
        return _tap_refusal(exc)


def _egress_gate(orch, grants: list[int]):
    """The kernel's ``plugin.egress`` decision for every request a refresh makes."""
    from agents.core.action_origin import current_action_origin
    from agents.core.kernel import Action, Verdict
    from agents.core.kernel.binding import make_action_kernel

    def gate(plugin: str, method: str, url: str, host: str) -> str | None:
        if host not in TAP_HOSTS:
            return "host_not_allowed"
        try:
            kernel = make_action_kernel(orch)
            if kernel is None:
                return "governance_unavailable"
            decision = kernel(Action(kind="plugin.egress", agent=plugin,
                                     title=f"skill tap refresh {method} {host}",
                                     payload={"plugin": plugin, "method": method, "host": host,
                                              "url": url, "risk_tier": 2},
                                     origin=current_action_origin()))
            if decision.verdict is Verdict.GRANT:
                grants[0] += 1
                return None
            return decision.reason or "not_granted"
        except Exception:  # noqa: BLE001 — fail closed
            logger.warning("skill tap egress kernel gate failed closed", exc_info=True)
            return "governance_unavailable"

    return gate


@asynccontextmanager
async def _open_fetcher(orch, gate):
    """``fetch(url, limit) -> bytes`` over the governed egress client (no redirects)."""
    from agents.core.http_client import PluginEgressError, RequiredEgressHTTPClient
    from agents.core.skills.taps import TapRefused

    importer = getattr(orch, "skill_importer", None)
    client = RequiredEgressHTTPClient(
        plugin_name="skill-import", authorize_egress=gate,
        resolver=getattr(importer, "_remote_resolver", None),
        transport_factory=getattr(importer, "_remote_transport_factory", None))

    async def fetch(url: str, limit: int) -> bytes:
        if (urlparse(url).hostname or "") not in TAP_HOSTS or not url.startswith("https://"):
            raise TapRefused("egress_denied")
        try:
            async with client.stream("GET", url, follow_redirects=False,
                                     headers={"Accept": "application/vnd.github+json"}) as response:
                if response.status_code != 200:
                    raise TapRefused("fetch_failed")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > limit:
                        raise TapRefused("refresh_budget")
                return bytes(body)
        except TapRefused:
            raise
        except PluginEgressError as exc:
            raise TapRefused("egress_denied") from exc
        except Exception as exc:  # noqa: BLE001 — never upstream text in the answer
            logger.warning("skill tap fetch failed (type=%s)", type(exc).__name__)
            raise TapRefused("fetch_failed") from exc

    async with client:
        yield fetch


@router.post("/api/skills/taps/{tap_id}/refresh", dependencies=WRITE_GUARDS)
async def taps_refresh(tap_id: str = Path(pattern=TAP_PATTERN)):
    """Read an approved tap's index at its pinned commit (every request crosses the kernel)."""
    from agents.core.skills import taps

    orch = get_orch()
    if not orch:
        return _unavailable()
    grants = [0]
    try:
        async with _open_fetcher(orch, _egress_gate(orch, grants)) as fetch:
            row = await taps.refresh(orch, tap_id, fetch)
    except taps.TapRefused as exc:
        return _tap_refusal(exc)
    if grants[0] < 1:
        return nocache_json({"error": "authorization_unavailable"}, status_code=503)
    return nocache_json({"ok": True, "tap": row, "egress_grants": grants[0]})


@router.get("/api/skills/taps/search", dependencies=[Depends(user_guard)])
async def taps_search(q: str = Query("", max_length=100), tap: str = Query("", max_length=210),
                      limit: int = Query(40, ge=1, le=100)):
    from agents.core.skills import taps

    orch = get_orch()
    if not orch:
        return _unavailable()
    importer = getattr(orch, "skill_importer", None)
    imported = await asyncio.to_thread(importer.list_imported) if importer is not None else []
    try:
        return nocache_json(await asyncio.to_thread(taps.search, q, tap=tap, limit=limit, imported=imported))
    except taps.TapRefused as exc:
        return _tap_refusal(exc)


class TapInstallBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    tap: StrictStr = Field(min_length=1, max_length=210)
    skill: StrictStr = Field(min_length=1, max_length=64)


@router.post("/api/skills/taps/install", dependencies=WRITE_GUARDS)
async def taps_install(body: TapInstallBody):
    """Install one skill a tap lists, through ``POST /skills/import``'s own remote import
    (exact pin, ``skill.install`` before and after the fetch, governed egress, quarantine).
    The vendored catalog keeps its own owner route (``POST /api/skills/catalog/install``)."""
    from agents.core.routers.skills import _import_remote
    from agents.core.skills import taps

    orch = get_orch()
    if not orch or getattr(orch, "skill_importer", None) is None:
        return _unavailable()
    if body.tap == taps.BUILTIN_CATALOG:
        return nocache_json({"error": "use_catalog_install",
                             "detail": "the vendored catalog installs through POST /api/skills/catalog/install"},
                            status_code=409)
    if body.tap == taps.BUILTIN_PIN:
        source, request, trust = "hermes", {}, "official"
    else:
        try:
            row, pin = await asyncio.to_thread(taps.install_pin, body.tap, body.skill)
        except taps.TapRefused as exc:
            return _tap_refusal(exc)
        source, request, trust = row["repo"], {"pin": pin}, row["trust"]
    result = await _import_remote(orch, source, body.skill, request)
    if isinstance(result, JSONResponse):
        return result
    answer = {**result, "tap": body.tap, "trust": trust}
    skill = _skill(orch, body.skill)
    if skill is not None:
        # H342 at install time: which declared variables still need a value.
        answer["setup"] = await asyncio.to_thread(_setup_view, skill)
    return nocache_json(answer)
