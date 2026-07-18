"""
Tests for the Proactive Technology Scout (agents/core/autonomy/tech_scout.py).

Runs fully offline: `search` is a fake async callable, the worker is a real
AutonomyWorker over an in-memory queue (no notifier/executor), so we assert on
the resulting task rows exactly like test_autonomy_observer.py does for the
resource/service Observer this module is modeled on.
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.autonomy import AutonomyPolicy, AutonomyWorker, TaskQueue  # noqa: E402
from agents.core.autonomy.policy import RiskTier  # noqa: E402
from agents.core.autonomy.tech_scout import TechScout, TechScoutStore  # noqa: E402


def _worker() -> AutonomyWorker:
    queue = TaskQueue(db_path=":memory:").initialize()
    return AutonomyWorker(queue, policy=AutonomyPolicy())


def _fake_search(results_by_query):
    async def search(query, max_results=5):
        return list(results_by_query.get(query, []))[:max_results]
    return search


RESULT_A = {"title": "New Local Inference Engine", "url": "https://example.com/a", "snippet": "fast local LLM runtime"}
RESULT_B = {"title": "Competing Personal AI Launch", "url": "https://example.com/b", "snippet": "a rival assistant"}


async def test_scan_disabled_skips():
    scout = TechScout(_worker(), _fake_search({}), queries=["q"])
    result = await scout.scan(enabled=False)
    assert result == {"skipped": True, "reason": "disabled"}


async def test_scan_without_search_backend_skips():
    scout = TechScout(_worker(), None, queries=["q"])
    result = await scout.scan(enabled=True)
    assert result["skipped"] is True
    assert result["reason"] == "no_search_backend"


async def test_scan_without_queries_skips():
    scout = TechScout(_worker(), _fake_search({}), queries=[])
    result = await scout.scan(enabled=True)
    assert result["skipped"] is True
    assert result["reason"] == "no_queries_configured"


async def test_scan_files_a_read_only_informational_task_per_new_result():
    w = _worker()
    scout = TechScout(w, _fake_search({"q": [RESULT_A, RESULT_B]}), queries=["q"])

    result = await scout.scan(enabled=True)

    assert result["skipped"] is False
    assert result["new_findings"] == 2
    assert result["proposed"] == 2

    tasks = w.queue.list()
    assert len(tasks) == 2
    for task in tasks:
        assert task.kind == "tech_scout.finding"
        assert task.risk_tier == int(RiskTier.READ_ONLY)
        # READ_ONLY auto-acts under the balanced default policy — no approval
        # needed, but nothing executes either (no executor registered for the
        # kind), matching observer.py's "observations inform" plain-alert model.
        assert task.autonomy_level == "act"
        assert task.status == "approved"
        assert task.payload["url"] in (RESULT_A["url"], RESULT_B["url"])


async def test_scan_deduplicates_across_runs_via_the_store():
    w = _worker()
    store = TechScoutStore(None)
    scout = TechScout(w, _fake_search({"q": [RESULT_A]}), queries=["q"], store=store)

    first = await scout.scan(enabled=True, force=True)
    assert first["proposed"] == 1

    second = await scout.scan(enabled=True, force=True)
    assert second["proposed"] == 0
    assert second["new_findings"] == 0
    assert len(w.queue.list()) == 1   # no duplicate task filed


async def test_scan_is_idempotent_per_interval_unless_forced():
    clock = {"now": 1000.0}
    scout = TechScout(w := _worker(), _fake_search({"q": [RESULT_A]}), queries=["q"],
                       clock=lambda: clock["now"])

    await scout.scan(enabled=True, interval_hours=168.0)
    assert len(w.queue.list()) == 1

    clock["now"] += 3600  # one hour later — well inside the 168h weekly window
    skipped = await scout.scan(enabled=True, interval_hours=168.0)
    assert skipped == {"skipped": True, "reason": "interval_not_elapsed",
                        "next_eligible_in_s": 168 * 3600 - 3600}
    assert len(w.queue.list()) == 1   # unchanged — no second pass ran


async def test_scan_caps_new_findings_per_pass():
    many = [
        {"title": f"Result {i}", "url": f"https://example.com/{i}", "snippet": "x"}
        for i in range(10)
    ]
    w = _worker()
    scout = TechScout(w, _fake_search({"q": many}), queries=["q"],
                       max_results_per_query=10, max_new_per_scan=3)

    result = await scout.scan(enabled=True)

    assert result["new_findings"] == 10
    assert result["proposed"] == 3
    assert result["capped"] == 7
    assert len(w.queue.list()) == 3


async def test_status_reports_configuration_and_history():
    scout = TechScout(_worker(), _fake_search({"q": [RESULT_A]}), queries=["q"])
    before = scout.status()
    assert before["configured"] is True
    assert before["last_run"] is None
    assert before["total_seen"] == 0

    await scout.scan(enabled=True)

    after = scout.status()
    assert after["last_run"] is not None
    assert after["total_seen"] == 1
    assert after["queries"] == ["q"]


async def test_store_rotates_at_the_seen_cap():
    store = TechScoutStore(None)
    from agents.core.autonomy.tech_scout import MAX_SEEN
    for i in range(MAX_SEEN + 10):
        store.mark_seen(f"fp-{i}", url=f"https://example.com/{i}", title=str(i), ts=float(i))
    assert store.seen_count() == MAX_SEEN
    # Oldest entries evicted first.
    assert not store.has_seen("fp-0")
    assert store.has_seen(f"fp-{MAX_SEEN + 9}")
