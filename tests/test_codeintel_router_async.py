"""0.31 — codeintel routes keep their blocking index work off the event loop.

`project_index()` / `reindex()` walk the whole repo (rglob + file reads + AST
parse) synchronously. Called directly inside `async def` handlers, a cold cache
or an admin reindex stalls EVERY in-flight request until the scan finishes.
These tests hold the sync seam open and require a sibling coroutine on the same
loop to free it: impossible when the seam squats the loop (pre-fix), instant
once offloaded via asyncio.to_thread. All network/DNS stays mocked — none is
needed; the seam is pure filesystem work.
"""

import asyncio
import json
import threading
import time

import agents.core.codeintel as ci
from agents.core.routers import codeintel as ci_router

# Generous hold so a starved loop can never flakily pass; still well under the
# suite's per-test --timeout=30 backstop, and only paid on RED.
_HOLD_TIMEOUT = 10.0
# Post-fix the whole detour through the worker thread settles in milliseconds;
# anything near the hold timeout means the loop was starved.
_MAX_HEALTHY_SECONDS = 5.0


def _stub_index() -> dict:
    return {"symbols": [], "files_indexed": 0, "symbol_count": 0,
            "by_kind": {}, "errors": []}


async def _run_with_held_seam(monkeypatch, handler_call):
    """Patch ci.build_index into a held-open seam, then run *handler_call*.

    One event pair wires the fake build to a sibling coroutine on the same
    loop: the build signals `entered`, then blocks until that sibling observes
    it and sets `release`. When the build squats the loop (pre-fix) the sibling
    never gets scheduled, so the hold times out and the wall clock shows
    starvation; once offloaded (to_thread) the handoff settles in milliseconds.
    """
    entered = threading.Event()
    release = threading.Event()
    ran_on_loop: list[bool] = []

    def slow_build(root):
        try:
            asyncio.get_running_loop()
            ran_on_loop.append(True)
        except RuntimeError:
            # No running loop in this thread ⇒ we were offloaded (to_thread).
            ran_on_loop.append(False)
        entered.set()
        assert release.wait(timeout=_HOLD_TIMEOUT), (
            "build was never released: it blocked the event loop"
        )
        return _stub_index()

    monkeypatch.setattr(ci, "build_index", slow_build)

    async def releaser():
        while not entered.is_set():
            await asyncio.sleep(0.005)
        release.set()

    started = time.monotonic()
    rel_task = asyncio.create_task(releaser())
    result = await handler_call()
    elapsed = time.monotonic() - started
    await rel_task
    return result, elapsed, ran_on_loop


async def test_stats_cold_start_keeps_index_build_off_the_loop(monkeypatch):
    monkeypatch.setattr(ci, "_CACHE", None)

    async def call():
        return await ci_router.codeintel_stats()

    result, elapsed, ran_on_loop = await _run_with_held_seam(monkeypatch, call)

    # Handlers return nocache_json(...) — decode to assert the unchanged shape.
    payload = json.loads(result.body)
    assert set(payload.keys()) == {"files_indexed", "symbol_count", "by_kind", "errors"}
    assert ran_on_loop == [False], "blocking build ran on the event loop"
    assert elapsed < _MAX_HEALTHY_SECONDS, f"loop starved for {elapsed:.1f}s"


async def test_search_cold_start_keeps_index_build_off_the_loop(monkeypatch):
    monkeypatch.setattr(ci, "_CACHE", None)

    async def call():
        return await ci_router.search_payload(q="anything")

    result, elapsed, ran_on_loop = await _run_with_held_seam(monkeypatch, call)

    assert result == {"query": "anything", "kind": None, "count": 0, "results": []}
    assert ran_on_loop == [False], "blocking build ran on the event loop"
    assert elapsed < _MAX_HEALTHY_SECONDS, f"loop starved for {elapsed:.1f}s"


async def test_reindex_keeps_full_rebuild_off_the_loop(monkeypatch):
    async def call():
        return await ci_router.codeintel_reindex()

    result, elapsed, ran_on_loop = await _run_with_held_seam(monkeypatch, call)

    payload = json.loads(result.body)
    assert payload == {"ok": True, "files_indexed": 0, "symbol_count": 0}
    assert ran_on_loop == [False], "blocking rebuild ran on the event loop"
    assert elapsed < _MAX_HEALTHY_SECONDS, f"loop starved for {elapsed:.1f}s"
