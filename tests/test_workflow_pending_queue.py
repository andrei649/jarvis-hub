"""0.34 — durable workflow pending-run queue with bounded retry + the engine drain.

Covers: enqueue/persistence, due-filtering by next_at, complete, retry-with-backoff
until the attempt cap then `dead`, bounded pruning (terminal items evicted first),
corrupt/missing-file safety, and the opt-in `WorkflowEngine.drain_pending` (resolve →
run → complete/retry/dead, including a crashing run and an unknown pipeline).
"""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.workflows.pending_queue import WorkflowPendingQueue, _backoff  # noqa: E402


def _q(tmp_path, **kw):
    return WorkflowPendingQueue(tmp_path / "pending.json", **kw)


# ── queue semantics ───────────────────────────────────────────────────────────
def test_enqueue_persists_and_is_runnable_now(tmp_path):
    q = _q(tmp_path)
    item = q.enqueue("brief", "go", now=1000.0)
    assert item["status"] == "pending" and item["attempts"] == 0 and item["next_at"] == 1000.0
    # survives a fresh instance (durable)
    assert [r["id"] for r in _q(tmp_path).due(1000.0)] == [item["id"]]


def test_enqueue_requires_pipeline_id(tmp_path):
    with pytest.raises(ValueError):
        _q(tmp_path).enqueue("  ", now=1.0)


def test_due_respects_next_at(tmp_path):
    q = _q(tmp_path)
    it = q.enqueue("p", now=100.0)
    q.fail(it["id"], "boom", now=100.0)          # reschedules into the future
    assert q.due(100.0) == []                      # not yet due
    later = q.list("pending")[0]["next_at"]
    assert q.due(later)                            # due once the clock reaches next_at


def test_complete_marks_done_and_drops_from_due(tmp_path):
    q = _q(tmp_path)
    it = q.enqueue("p", now=1.0)
    q.complete(it["id"])
    assert q.due(10.0) == []
    assert q.list("done") and q.stats()["done"] == 1


def test_retry_then_dead_at_cap(tmp_path):
    q = _q(tmp_path, backoff_base=10.0)
    it = q.enqueue("p", now=0.0, max_attempts=3)
    r1 = q.fail(it["id"], "e1", now=0.0)
    assert r1["status"] == "pending" and r1["attempts"] == 1 and r1["next_at"] == 10.0   # 10*2^0
    r2 = q.fail(it["id"], "e2", now=r1["next_at"])
    assert r2["status"] == "pending" and r2["attempts"] == 2 and r2["next_at"] == r1["next_at"] + 20.0  # 10*2^1
    r3 = q.fail(it["id"], "e3", now=r2["next_at"])
    assert r3["status"] == "dead" and r3["attempts"] == 3 and r3["last_error"] == "e3"
    assert q.due(1e12) == []                        # a dead item is never runnable again


def test_backoff_is_exponential_and_capped():
    assert _backoff(1, 60.0) == 60.0
    assert _backoff(2, 60.0) == 120.0
    assert _backoff(3, 60.0) == 240.0
    assert _backoff(99, 60.0) == 3600.0             # capped


def test_bounded_prunes_terminal_first(tmp_path):
    q = _q(tmp_path, max_keep=3)
    keep = [q.enqueue("live", now=float(i)) for i in range(3)]   # 3 live pending
    # complete one, then overflow — the done (terminal) one should be evicted, not live work
    q.complete(keep[0]["id"])
    q.enqueue("new", now=99.0)
    ids = {r["id"] for r in q.list()}
    assert keep[1]["id"] in ids and keep[2]["id"] in ids          # live work retained
    assert keep[0]["id"] not in ids                               # the terminal item went


def test_corrupt_file_degrades_to_empty(tmp_path):
    p = tmp_path / "pending.json"
    p.write_text("{not json", encoding="utf-8")
    q = WorkflowPendingQueue(p)
    assert q.list() == [] and q.due(0.0) == []
    q.enqueue("p", now=1.0)                          # still writable after corruption
    assert len(q.list()) == 1


# ── engine drain (opt-in) ──────────────────────────────────────────────────────
class _FakePipeline:
    def __init__(self, pid, ok=True, raises=False):
        self.id = pid
        self.name = pid
        self._ok = ok
        self._raises = raises


def _make_engine(monkeypatch):
    from agents.core.workflows.engine import WorkflowEngine
    eng = WorkflowEngine.__new__(WorkflowEngine)   # bypass heavy __init__
    eng.recent_runs = __import__("collections").deque(maxlen=50)

    async def fake_run(pipeline, initial_input, _depth=0):
        if getattr(pipeline, "_raises", False):
            raise RuntimeError("kaboom")
        return {"_ok": pipeline._ok, "_errors": [] if pipeline._ok else ["step failed"]}
    monkeypatch.setattr(eng, "run", fake_run)
    return eng


@pytest.mark.asyncio
async def test_drain_completes_successful_run(tmp_path, monkeypatch):
    q = _q(tmp_path)
    q.enqueue("good", now=0.0)
    eng = _make_engine(monkeypatch)
    summary = await eng.drain_pending(q, lambda pid: _FakePipeline(pid, ok=True), now=0.0)
    assert summary["ran"] == 1 and summary["done"] == 1
    assert q.stats()["done"] == 1 and q.due(1e9) == []


@pytest.mark.asyncio
async def test_drain_retries_failed_then_dead(tmp_path, monkeypatch):
    q = _q(tmp_path, backoff_base=5.0)
    q.enqueue("bad", now=0.0, max_attempts=2)
    eng = _make_engine(monkeypatch)
    def resolve(pid):
        return _FakePipeline(pid, ok=False)
    s1 = await eng.drain_pending(q, resolve, now=0.0)
    assert s1["retried"] == 1 and q.list("pending")[0]["attempts"] == 1
    # not due until backoff elapses; then the 2nd failure hits the cap → dead
    nxt = q.list("pending")[0]["next_at"]
    s2 = await eng.drain_pending(q, resolve, now=nxt)
    assert s2["dead"] == 1 and q.stats()["dead"] == 1


@pytest.mark.asyncio
async def test_drain_crashing_run_is_retried_not_lost(tmp_path, monkeypatch):
    q = _q(tmp_path)
    q.enqueue("boom", now=0.0)
    eng = _make_engine(monkeypatch)
    summary = await eng.drain_pending(q, lambda pid: _FakePipeline(pid, raises=True), now=0.0)
    assert summary["retried"] == 1
    assert "kaboom" in (q.list("pending")[0]["last_error"] or "")   # error captured, item kept


@pytest.mark.asyncio
async def test_drain_unknown_pipeline_fails_gracefully(tmp_path, monkeypatch):
    q = _q(tmp_path)
    q.enqueue("ghost", now=0.0, max_attempts=1)
    eng = _make_engine(monkeypatch)
    summary = await eng.drain_pending(q, lambda pid: None, now=0.0)   # resolver finds nothing
    assert summary["dead"] == 1 and summary["ran"] == 0
