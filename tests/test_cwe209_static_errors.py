"""CWE-209 — error responses must never echo raw exception text.

CodeQL "Information exposure through an exception" (alert #433) flagged flows
of ``str(exc)`` into response bodies. The rule: full detail goes to the server
log; the client gets a controlled, static message (see
``web_helpers.error_json``). Covers the SecurityBlockError handler in
``agents/web.py`` and the workflow save/update 422/500 paths in
``routers/workflows.py``.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import agents.web as web  # noqa: E402
from agents.core.routers import workflows as wf_router  # noqa: E402
from agents.core.security.guardrails import SecurityBlockError  # noqa: E402

_SECRET = "matched-rule: aws key AKIA... in /home/user/.env"


async def test_security_block_response_is_static():
    resp = await web.security_block_handler(None, SecurityBlockError(_SECRET))
    body = json.loads(resp.body)
    assert resp.status_code == 403
    assert body["code"] == "JARVIS-SECURITY-001"
    assert body["message"] == "Security policy blocked this request"
    assert _SECRET not in json.dumps(body)          # nothing exception-derived


class _RaisingStore:
    def __init__(self, exc):
        self._exc = exc

    def save(self, raw):
        raise self._exc


def _wf_body():
    # minimal valid WorkflowSaveBody payload
    return wf_router.WorkflowSaveBody(id="t", name="t", steps=[])


async def _expect_static_detail(monkeypatch, exc, expected_status, expected_detail):
    monkeypatch.setattr(wf_router, "get_orch", lambda: MagicMock())
    monkeypatch.setattr(web, "_wf_store", lambda: _RaisingStore(exc))
    with pytest.raises(HTTPException) as ei:
        await wf_router.create_workflow(_wf_body())
    assert ei.value.status_code == expected_status
    assert ei.value.detail == expected_detail
    assert _SECRET not in str(ei.value.detail)


async def test_workflow_save_422_detail_is_static(monkeypatch):
    await _expect_static_detail(
        monkeypatch, ValueError(_SECRET), 422, "invalid workflow definition")


async def test_workflow_save_500_detail_is_static(monkeypatch):
    await _expect_static_detail(
        monkeypatch, RuntimeError(_SECRET), 500, "workflow save failed")


async def test_workflow_update_details_are_static(monkeypatch):
    monkeypatch.setattr(wf_router, "get_orch", lambda: MagicMock())
    monkeypatch.setattr(web, "_wf_store", lambda: _RaisingStore(ValueError(_SECRET)))
    with pytest.raises(HTTPException) as ei:
        await wf_router.update_workflow("t", _wf_body())
    assert ei.value.status_code == 422
    assert ei.value.detail == "invalid workflow definition"
    assert _SECRET not in str(ei.value.detail)
