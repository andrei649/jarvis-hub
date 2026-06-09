"""NTH-1 — /api/cognition/stream emits SSE frames on cognition change + heartbeat."""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.cognition.api import _cognition_events


async def _noop_sleep(_):
    return None


async def _collect(gen):
    return [frame async for frame in gen]


@pytest.mark.asyncio
async def test_emits_on_change_only():
    """A new data frame only when the snapshot changes; unchanged ticks stay quiet."""
    snaps = [{"a": 1}, {"a": 1}, {"a": 2}]
    it = iter(snaps)
    frames = await _collect(_cognition_events(
        lambda: next(it), sleep=_noop_sleep, heartbeat_every=0, max_iterations=3,
    ))
    assert len(frames) == 2  # a:1 (first), a:2 (changed) — the repeat a:1 is silent
    assert all(f.startswith("data:") for f in frames)
    assert '"cognition"' in frames[0]
    assert '"a": 2' in frames[1]


@pytest.mark.asyncio
async def test_heartbeat_on_idle():
    """When the snapshot never changes, a keepalive fires every heartbeat_every ticks."""
    frames = await _collect(_cognition_events(
        lambda: {"static": True}, sleep=_noop_sleep, heartbeat_every=2, max_iterations=5,
    ))
    # tick1: change→data; ticks 2-5 idle → keepalive at idle==2 and idle==4.
    assert frames[0].startswith("data:")
    assert frames.count(": keepalive\n\n") == 2


@pytest.mark.asyncio
async def test_none_snapshot_is_safe():
    frames = await _collect(_cognition_events(
        lambda: None, sleep=_noop_sleep, heartbeat_every=0, max_iterations=2,
    ))
    assert frames == []  # nothing to stream, no crash
