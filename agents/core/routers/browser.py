"""Governed browser-use endpoints (H15.1) — extracted from web.py (CLN-3)."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Mapping
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from agents.core.routers._deps import owner_web_principal, user_guard

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

_OBSERVATION_BYTES = 16_000


def _safe_origin(value) -> bool:
    if type(value) is not str or len(value) > 253:
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme in {'http', 'https'} and bool(parsed.hostname)
                and parsed.username is None and parsed.password is None
                and (parsed.port is None or 1 <= parsed.port <= 65_535)
                and not parsed.path and not parsed.query and not parsed.fragment
                and not any(ord(char) <= 32 or ord(char) == 127 for char in value))
    except ValueError:
        return False


def _safe_image_url(value) -> bool:
    if type(value) is not str or len(value) > 512:
        return False
    if not value:
        return True
    try:
        parsed = urlsplit(value)
        return (parsed.scheme in {'http', 'https'} and bool(parsed.hostname)
                and parsed.username is None and parsed.password is None
                and (parsed.port is None or 1 <= parsed.port <= 65_535)
                and not parsed.fragment
                and not any(ord(char) <= 32 or ord(char) == 127 for char in value))
    except ValueError:
        return False


def _project_browser_observations(trace) -> tuple[list[dict], bool]:
    """Only expected typed browser observations reach the owner HUD."""
    if type(trace) is not list:
        return [], False
    output: list[dict] = []
    truncated = False
    for step in trace[:20]:
        if type(step) is not dict or step.get('status') != 'done':
            continue
        action, raw = step.get('action'), step.get('result')
        if type(raw) is not dict or action not in {'console', 'get_images'}:
            continue
        if action == 'console' and raw.get('observation') == 'console':
            records = []
            for item in raw.get('records', [])[:32] if type(raw.get('records')) is list else []:
                if (type(item) is dict and item.get('level') in {
                        'log', 'info', 'warning', 'error', 'debug', 'other'}
                        and type(item.get('text')) is str and len(item['text']) <= 512
                        and (item.get('source_origin') == ''
                             or _safe_origin(item.get('source_origin')))
                        and type(item.get('document_epoch')) is int
                        and item['document_epoch'] >= 0):
                    records.append({key: item[key] for key in
                                    ('level', 'text', 'source_origin', 'document_epoch')})
            projected = {'action': 'console', 'records': records}
        elif action == 'get_images' and raw.get('observation') == 'images':
            images = []
            for item in raw.get('images', [])[:24] if type(raw.get('images')) is list else []:
                if (type(item) is dict and _safe_image_url(item.get('source_url'))
                        and type(item.get('alt')) is str and len(item['alt']) <= 128
                        and type(item.get('width')) is int and 0 <= item['width'] <= 100_000
                        and type(item.get('height')) is int and 0 <= item['height'] <= 100_000
                        and type(item.get('fetchable')) is bool
                        and (not item['fetchable'] or bool(item['source_url']))
                        and _safe_origin(item.get('frame_origin'))
                        and type(item.get('document_epoch')) is int
                        and item['document_epoch'] >= 0):
                    row = {key: item[key] for key in ('source_url', 'alt', 'width', 'height',
                                                       'fetchable', 'frame_origin', 'document_epoch')}
                    ref = item.get('ref')
                    if type(ref) is str and re.fullmatch(r'@e[1-9][0-9]{0,5}', ref):
                        row['ref'] = ref
                    images.append(row)
            projected = {'action': 'get_images', 'images': images}
        else:
            continue
        dropped = raw.get('dropped')
        if type(dropped) is int and 0 <= dropped <= 1_000_000:
            projected['dropped'] = dropped
        if type(raw.get('truncated')) is bool:
            projected['truncated'] = raw['truncated']
        if len(json.dumps([*output, projected], ensure_ascii=False).encode()) > _OBSERVATION_BYTES:
            truncated = True
            break
        output.append(projected)
    return output, truncated


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


@router.get('/api/browser/sessions', dependencies=[Depends(owner_web_principal)])
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


@router.get('/api/browser/tasks/{task_id}', dependencies=[Depends(owner_web_principal)])
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
            observations, truncated = _project_browser_observations(outcome['trace'])
            if observations or truncated:
                result['observations'] = observations
                result['observations_truncated'] = truncated
        reason = outcome.get('reason')
        if type(reason) is str and re.fullmatch('[a-z_]{1,64}', reason):
            result['reason'] = reason
    return nocache_json(result)


@router.post('/api/browser/sessions/{session_id}/close', dependencies=[Depends(owner_web_principal)])
async def browser_session_close(session_id: str):
    """An authenticated owner may always stop a fresh-profile browser."""
    runtime = _session_runtime()
    if runtime is None or re.fullmatch('[0-9a-f]{32}', session_id) is None:
        return nocache_json({'closed': False, 'reason': 'browser_session_unavailable'}, status_code=404)
    closed = await runtime.close_owner_session(session_id)
    return nocache_json({'closed': closed, 'reason': '' if closed else 'browser_session_unavailable'},
                        status_code=200 if closed else 409)


class BrowserDialogProposalBody(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    dialog_id: str = Field(min_length=32, max_length=32)
    choice: Literal['accept', 'dismiss']
    prompt_text: str | None = Field(default=None, max_length=1024)
    prompt_ref: str | None = Field(default=None, min_length=32, max_length=32)


class BrowserDialogTextBody(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    dialog_id: str = Field(min_length=32, max_length=32)
    prompt_text: str = Field(max_length=1024)


@router.get('/api/browser/dialogs/tasks/{task_id}/card',
            dependencies=[Depends(owner_web_principal)])
async def browser_dialog_card(task_id: int):
    """Exact private choice/value for the authenticated owner's decision card."""
    runtime = _session_runtime()
    if runtime is None or task_id <= 0:
        return nocache_json({'found': False}, status_code=404)
    card = await runtime.owner_dialog_card('admin', task_id)
    return nocache_json({'found': card is not None, **(card or {})},
                        status_code=200 if card is not None else 404)


@router.get('/api/browser/dialogs/{opener_task_id}',
            dependencies=[Depends(owner_web_principal)])
async def browser_dialog_pending(opener_task_id: int):
    runtime = _session_runtime()
    if runtime is None or opener_task_id <= 0:
        return nocache_json({'status': 'unavailable'}, status_code=404)
    return nocache_json(await runtime.owner_dialog_pending('admin', opener_task_id))


@router.post('/api/browser/dialogs/{opener_task_id}/text',
             dependencies=[Depends(owner_web_principal)])
async def browser_dialog_stage_text(opener_task_id: int, body: BrowserDialogTextBody):
    """Keep owner-entered text process-local before any model or generic queue path."""
    runtime = _session_runtime()
    if runtime is None or opener_task_id <= 0:
        return nocache_json({'ok': False, 'reason': 'dialog_unavailable'}, status_code=404)
    try:
        ref = runtime.owner_stage_dialog_text(
            'admin', opener_task_id, body.dialog_id, body.prompt_text)
    except ValueError:
        return nocache_json({'ok': False, 'reason': 'dialog_unavailable'}, status_code=409)
    return nocache_json({'ok': True, 'prompt_ref': ref})


@router.post('/api/browser/dialogs/{opener_task_id}/proposals',
             dependencies=[Depends(owner_web_principal)])
async def browser_dialog_owner_propose(opener_task_id: int,
                                       body: BrowserDialogProposalBody):
    runtime = _session_runtime()
    if runtime is None or opener_task_id <= 0:
        return nocache_json({'ok': False, 'reason': 'dialog_unavailable'}, status_code=404)
    raw = {'opener_task_id': opener_task_id, 'dialog_id': body.dialog_id,
           'choice': body.choice}
    if 'prompt_text' in body.model_fields_set:
        raw['prompt_text'] = body.prompt_text
    if 'prompt_ref' in body.model_fields_set:
        raw['prompt_ref'] = body.prompt_ref
    try:
        task_id = await runtime.owner_dialog_propose('admin', opener_task_id, raw)
    except Exception:
        return nocache_json({'ok': False, 'reason': 'dialog_unavailable'}, status_code=409)
    return nocache_json({'ok': False, 'reason': 'approval_required', 'task_id': task_id},
                        status_code=202)


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
