"""Regression tests for audit micro-bug fixes (B1, B2, B6)."""
import asyncio
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.autonomy.action_approvals import ActionApprovalQueue
from agents.core.autonomy.escalation import render_escalation


# ── B1: await_decision must not KeyError if the queue is cleared mid-await ────

@pytest.mark.asyncio
async def test_await_decision_survives_concurrent_clear():
    q = ActionApprovalQueue()
    item = q.request({"tool": "deploy"})

    async def clear_soon():
        await asyncio.sleep(0.01)
        q.clear()                       # races the awaiter

    asyncio.create_task(clear_soon())
    # event is never set + item gets cleared → must return gracefully, not raise
    status = await q.await_decision(item["id"], timeout=0.2)
    assert status in ("unknown", "timeout")


@pytest.mark.asyncio
async def test_await_decision_normal_path_still_works():
    q = ActionApprovalQueue()
    item = q.request({"tool": "x"})

    async def approve():
        await asyncio.sleep(0.01)
        q.decide(item["id"], True)

    asyncio.create_task(approve())
    assert await q.await_decision(item["id"], timeout=0.5) == "approved"


# ── B2: render_escalation degrades gracefully even if preview blows up ────────

def test_render_escalation_tolerates_preview_failure(monkeypatch):
    # Force preview_task import path to raise; render must still produce text.
    import agents.core.autonomy.dry_run as dr
    monkeypatch.setattr(dr, "preview_task", lambda t: (_ for _ in ()).throw(RuntimeError("boom")))
    msg = render_escalation({"id": 1, "title": "T", "agent": "a", "kind": "k"})
    assert "#1" in msg and "T" in msg            # core lines present, no crash
