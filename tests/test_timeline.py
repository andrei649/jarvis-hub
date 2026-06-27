"""Tests for the unified "Today in Jarvis" feed (P1 proof-gap G1).

Pure-offline: the builder is exercised with a tiny fake queue + plain memory-row
dicts (full control over timestamps, no DB), and the endpoint with `web.orch`
rebound + `MemoryStore` monkeypatched — the suite's standard pattern. No async in
the builder, no LLM, no network.
"""
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.memory.timeline import _ts_epoch, build_unified_digest

# ── fixtures / helpers ──────────────────────────────────────────────────────


def _iso(dt: datetime) -> str:
    return dt.isoformat()


class _FakeQueue:
    """Duck-types TaskQueue.list(status=..., limit=...) for done tasks only."""

    def __init__(self, done):
        self._done = done

    def list(self, status=None, limit=500):
        return list(self._done) if status == "done" else []


def _task(tid, title, ts, tier=1, agent="jarvis"):
    return SimpleNamespace(id=tid, title=title, updated_at=ts, risk_tier=tier, agent_id=agent)


def _mem(category, key, value, ts):
    return {"category": category, "key": key, "value": value, "updated_at": ts}


# ── _ts_epoch helper ─────────────────────────────────────────────────────────


def test_ts_epoch_handles_iso_and_sqlite_and_garbage():
    iso = _ts_epoch("2026-06-27T09:00:00+00:00")       # queue: tz-aware ISO
    sqlite = _ts_epoch("2026-06-27 09:00:00")          # memory: naive SQLite → read as UTC
    assert iso is not None and sqlite is not None and iso == sqlite
    assert _ts_epoch("not-a-date") is None
    assert _ts_epoch(None) is None and _ts_epoch("") is None


# ── core fusion ──────────────────────────────────────────────────────────────


def test_fuses_actions_and_learnings_newest_first():
    now = datetime(2026, 6, 27, 12, 0, tzinfo=UTC).timestamp()
    base = datetime(2026, 6, 27, tzinfo=UTC)
    q = _FakeQueue([
        _task(1, "sent digest", _iso(base.replace(hour=2))),       # 02:00 action
        _task(2, "synced calendar", _iso(base.replace(hour=9))),   # 09:00 action
    ])
    mem = [
        _mem("preference", "tone", "concise", _iso(base.replace(hour=7))),   # 07:00 learning
        _mem("fact", "city", "Bucharest", _iso(base.replace(hour=11))),      # 11:00 learning
    ]
    out = build_unified_digest(q, mem, now=now, days=1)

    assert out["counts"] == {"actions": 2, "learnings": 2, "total": 4}
    assert out["period"] == "today" and out["days"] == 1
    # newest first: 11:00 learning, 09:00 action, 07:00 learning, 02:00 action
    assert [it["kind"] for it in out["items"]] == ["learning", "action", "learning", "action"]
    assert out["items"][0]["value"] == "Bucharest"
    assert out["items"][1]["title"] == "synced calendar"


def test_window_excludes_old_items():
    now = datetime(2026, 6, 27, 12, 0, tzinfo=UTC).timestamp()
    old = _iso(datetime(2026, 6, 25, 12, 0, tzinfo=UTC))   # 2 days ago
    fresh = _iso(datetime(2026, 6, 27, 8, 0, tzinfo=UTC))
    q = _FakeQueue([_task(1, "old", old), _task(2, "fresh", fresh)])
    mem = [_mem("fact", "k", "v", old)]
    out = build_unified_digest(q, mem, now=now, days=1)
    assert out["counts"] == {"actions": 1, "learnings": 0, "total": 1}
    assert out["items"][0]["title"] == "fresh"


def test_days_widens_window_and_labels_period():
    now = datetime(2026, 6, 27, 12, 0, tzinfo=UTC).timestamp()
    two_days = _iso(datetime(2026, 6, 25, 18, 0, tzinfo=UTC))
    out = build_unified_digest(_FakeQueue([_task(1, "older", two_days)]), [], now=now, days=7)
    assert out["counts"]["actions"] == 1
    assert out["period"] == "7d" and out["days"] == 7


def test_limit_truncates_items_but_counts_reflect_full_set():
    now = datetime(2026, 6, 27, 23, 0, tzinfo=UTC).timestamp()
    base = datetime(2026, 6, 27, tzinfo=UTC)
    tasks = [_task(i, f"t{i}", _iso(base.replace(hour=i))) for i in range(1, 6)]  # 01:00–05:00
    out = build_unified_digest(_FakeQueue(tasks), [], now=now, days=1, limit=2)
    assert len(out["items"]) == 2
    assert out["counts"]["total"] == 5


def test_none_queue_and_empty_memory_is_honest():
    out = build_unified_digest(None, None, now=1_900_000_000.0, days=1)
    assert out["counts"] == {"actions": 0, "learnings": 0, "total": 0}
    assert out["items"] == []
    assert out["generated_at"].endswith("+00:00")


def test_unparseable_timestamp_kept_at_bottom_never_dropped():
    now = datetime(2026, 6, 27, 12, 0, tzinfo=UTC).timestamp()
    good = _iso(datetime(2026, 6, 27, 9, 0, tzinfo=UTC))
    q = _FakeQueue([_task(1, "good", good), _task(2, "bad", "not-a-date")])
    out = build_unified_digest(q, [], now=now, days=1)
    assert out["counts"]["actions"] == 2          # bad-stamp row is not dropped
    assert out["items"][0]["title"] == "good"     # parseable first
    assert out["items"][-1]["title"] == "bad"     # unparseable sinks to the bottom


# ── endpoint ──────────────────────────────────────────────────────────────────


def test_endpoint_today_fuses_and_clamps(monkeypatch):
    from agents import web
    from agents.core.memory import store as store_mod

    now_iso = datetime.now(UTC).isoformat()
    q = _FakeQueue([_task(1, "did a thing", now_iso)])

    class _FakeStore:
        def __init__(self, *a, **k):
            pass

        async def get_all(self):
            return {"fact": [_mem("fact", "city", "Bucharest", now_iso)]}

    monkeypatch.setattr(store_mod, "MemoryStore", _FakeStore)
    monkeypatch.setattr(web, "orch", SimpleNamespace(autonomy_queue=q))
    client = TestClient(web.app)

    resp = client.get("/api/dashboard/today?days=1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["counts"]["actions"] == 1 and body["counts"]["learnings"] == 1
    assert body["days"] == 1

    # Query bounds (ge=1, le=30)
    assert client.get("/api/dashboard/today?days=0").status_code == 422
    assert client.get("/api/dashboard/today?days=99").status_code == 422


def test_endpoint_503_without_orch(monkeypatch):
    from agents import web

    monkeypatch.setattr(web, "orch", None)
    client = TestClient(web.app)
    assert client.get("/api/dashboard/today").status_code == 503
