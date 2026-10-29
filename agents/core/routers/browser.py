"""Governed browser-use endpoints (H15.1) — extracted from web.py (CLN-3)."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from agents.core.routers._deps import user_guard

from agents.core.web_helpers import nocache_json


class _BrowserValidationRoute(APIRoute):
    """Keep rejected browser inputs out of FastAPI's verbose 422 body."""

    def get_route_handler(self):
        route_handler = super().get_route_handler()

        async def bounded_route_handler(request: Request):
            try:
                return await route_handler(request)
            except RequestValidationError:
                return nocache_json(
                    {"detail": "invalid_browser_request"},
                    status_code=422,
                )

        return bounded_route_handler


router = APIRouter(tags=["browser"], route_class=_BrowserValidationRoute)


@router.get('/api/browser/status', dependencies=[Depends(user_guard)])
async def browser_status():
    """Read-only server execution readiness; the preview allowlist is unrelated."""
    from agents.core.app_state import get_orch
    from agents.core.operator_router import _browser_available

    return nocache_json({'available': _browser_available(get_orch())})


def _session_runtime():
    from agents.core.app_state import get_orch

    server = getattr(get_orch(), 'tool_rpc', None)
    spec = getattr(server, '_tools', {}).get('browser_run') if server is not None else None
    runtime = getattr(spec.get('handler'), '__self__', None) if isinstance(spec, dict) else None
    return runtime if callable(getattr(runtime, 'close_owner_session', None)) else None


@router.get('/api/browser/sessions', dependencies=[Depends(user_guard)])
async def browser_sessions():
    """Authenticated owner projection; no profile paths or page text authority."""
    runtime = _session_runtime()
    if runtime is None:
        return nocache_json({'available': False, 'sessions': []})
    rows = []
    for session in list(runtime.sessions.values())[:4]:
        page = getattr(session.driver, '_page', None)
        url = str(getattr(page, 'url', ''))
        parsed = urlsplit(url)
        origin = f'{parsed.scheme}://{parsed.netloc}' if parsed.scheme in {'http', 'https'} else ''
        rows.append({'id': session.id, 'origin': origin[:253],
                     'generation': session.generation,
                     'refs': [{'ref': key, 'role': value.role[:64], 'name': value.name[:128]}
                              for key, value in list(session.refs.items())[:100]],
                     'active': session.active_task is not None,
                     'expires_in': max(0, int(600 - (__import__('time').monotonic() - session.created)))})
    return nocache_json({'available': runtime.ready(), 'sessions': rows,
                         'cleanup_uncertain': bool(runtime._uncertain_drivers
                                                   or runtime._journal_uncertain)})


@router.get('/api/browser/tasks/{task_id}', dependencies=[Depends(user_guard)])
async def browser_task_status(task_id: int):
    """Show the owner's browser outcome without exposing page text or raw task data."""
    runtime = _session_runtime()
    if runtime is None or runtime.queue is None or task_id < 1:
        return nocache_json({'found': False}, status_code=404)
    task = await asyncio.to_thread(runtime.queue.get, task_id)
    if task is None or task.kind != 'toolrpc.browser_run':
        return nocache_json({'found': False}, status_code=404)
    outcome = task.result.get('result') if type(task.result) is dict else None
    result = {'found': True, 'status': task.status if task.status in {
        'proposed', 'approved', 'running', 'blocked', 'done', 'failed',
        'rejected', 'deferred', 'quarantined', 'expired'} else 'unknown'}
    if type(outcome) is dict and type(outcome.get('ok')) is bool:
        result['ok'] = outcome['ok']
        if type(outcome.get('trace')) is list:
            result['steps'] = min(len(outcome['trace']), 20)
        reason = outcome.get('reason')
        if type(reason) is str and re.fullmatch('[a-z_]{1,64}', reason):
            result['reason'] = reason
    return nocache_json(result)


@router.post('/api/browser/sessions/{session_id}/close', dependencies=[Depends(user_guard)])
async def browser_session_close(session_id: str):
    """An authenticated owner may always stop a fresh-profile browser."""
    runtime = _session_runtime()
    if runtime is None or re.fullmatch('[0-9a-f]{32}', session_id) is None:
        return nocache_json({'closed': False, 'reason': 'browser_session_unavailable'}, status_code=404)
    closed = await runtime.close_owner_session(session_id)
    return nocache_json({'closed': closed, 'reason': '' if closed else 'browser_session_unavailable'},
                        status_code=200 if closed else 409)


class _StrictBrowserBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


BrowserUrl = Annotated[str, Field(max_length=2000, strict=True)]
BrowserDomain = Annotated[str, Field(max_length=253, strict=True)]
BrowserSelector = Annotated[str, Field(max_length=512, strict=True)]
BrowserTypeText = Annotated[str, Field(max_length=4000, strict=True)]


class BrowserNavigateStep(_StrictBrowserBody):
    action: Literal["navigate"]
    url: BrowserUrl


class BrowserExtractStep(_StrictBrowserBody):
    action: Literal["extract"]
    selector: BrowserSelector


class BrowserClickStep(_StrictBrowserBody):
    action: Literal["click"]
    selector: BrowserSelector


class BrowserTypeStep(_StrictBrowserBody):
    action: Literal["type"]
    selector: BrowserSelector
    text: BrowserTypeText


class BrowserSubmitStep(_StrictBrowserBody):
    action: Literal["submit"]
    selector: BrowserSelector


BrowserPlanStep = Annotated[
    BrowserNavigateStep
    | BrowserExtractStep
    | BrowserClickStep
    | BrowserTypeStep
    | BrowserSubmitStep,
    Field(discriminator="action"),
]


class BrowserCheckBody(_StrictBrowserBody):
    url: BrowserUrl
    allowlist: list[BrowserDomain] = Field(default_factory=list, max_length=100)


class BrowserPreviewBody(_StrictBrowserBody):
    plan: list[BrowserPlanStep] = Field(default_factory=list, max_length=200)
    allowlist: list[BrowserDomain] = Field(default_factory=list, max_length=100)


def _bounded_reason(value) -> str:
    return str(value or "")[:240]


def _project_preview(raw) -> dict[str, list[dict]]:
    raw_steps = raw.get("steps", []) if isinstance(raw, Mapping) else []
    if not isinstance(raw_steps, list):
        raw_steps = []
    projected = []
    for fallback_index, raw_step in enumerate(raw_steps[:200]):
        if not isinstance(raw_step, Mapping):
            continue
        projected.append(
            {
                "index": fallback_index,
                "action": str(raw_step.get("action") or "")[:64],
                "kind": str(raw_step.get("kind") or "")[:32],
                "decision": str(raw_step.get("decision") or "")[:32],
                "reason": _bounded_reason(raw_step.get("reason")),
            }
        )
    return {"steps": projected}


@router.post("/api/browser/check", dependencies=[Depends(user_guard)])
async def browser_check(body: BrowserCheckBody):
    """H15.1 — would this URL pass the egress allowlist + SSRF filter?"""
    from agents.core.browser_agent import BrowserPolicy

    def _check() -> tuple[bool, str]:
        return BrowserPolicy(body.allowlist).domain_allowed(body.url)

    # check_ssrf resolves DNS synchronously (socket.getaddrinfo); inline it froze
    # the event loop for a full DNS round-trip per request. Pay it in a worker
    # thread (asyncio.to_thread), same as the other bounded request paths.
    ok, reason = await asyncio.to_thread(_check)
    return nocache_json({"allowed": ok, "reason": _bounded_reason(reason)})


@router.post("/api/browser/plan/preview", dependencies=[Depends(user_guard)])
async def browser_plan_preview(body: BrowserPreviewBody):
    """H15.1 — governance dry-run: per-step run/approve/block (no execution)."""
    from agents.core.browser_agent import GovernedBrowser, BrowserPolicy

    gb = GovernedBrowser(policy=BrowserPolicy(body.allowlist))
    plan = [step.model_dump(mode="python") for step in body.plan]

    def _preview():
        return gb.preview(plan)

    # Each navigate step runs the same blocking SSRF DNS lookup; with up to 200
    # steps that is up to 200 frozen DNS round-trips on the loop. Offload whole.
    return nocache_json(_project_preview(await asyncio.to_thread(_preview)))
