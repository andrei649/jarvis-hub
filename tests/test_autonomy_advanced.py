"""Tests for executor / digest / preferences / night-shift (H6.4–H6.6)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import pytest
from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.autonomy.executor import TaskExecutor
from agents.core.autonomy.digest import build_morning_brief, build_evening_retro
from agents.core.autonomy.preferences import PreferenceStore
from agents.core.autonomy.worker import is_night_window, AutonomyWorker
from agents.core.autonomy.policy import AutonomyPolicy


@pytest.fixture
def q(tmp_path):
    queue = TaskQueue(db_path=str(tmp_path / "autonomy.db")).initialize()
    yield queue
    queue.close()


class _FakeTask:
    def __init__(self, kind):
        self.kind = kind
        self.id = 1
        self.payload = {}


# ── executor ──────────────────────────────────────────────────────
class TestExecutor:
    async def test_dispatch_by_prefix(self):
        hits = []

        async def h_research(task):
            hits.append("research")
            return {"status": "ok"}

        ex = TaskExecutor().register("research", h_research)
        await ex.execute(_FakeTask("research_market"))
        assert hits == ["research"]

    async def test_longest_prefix_wins(self):
        async def generic(task):
            return {"who": "generic"}

        async def specific(task):
            return {"who": "specific"}

        ex = TaskExecutor().register("draft", generic).register("draft_email", specific)
        res = await ex.execute(_FakeTask("draft_email_reply"))
        assert res["who"] == "specific"

    async def test_fallback_used(self):
        async def fb(task):
            return {"who": "fallback"}

        ex = TaskExecutor(fallback=fb)
        assert (await ex.execute(_FakeTask("unknown_kind")))["who"] == "fallback"

    async def test_noop_when_no_handler(self):
        ex = TaskExecutor()
        assert (await ex.execute(_FakeTask("unknown")))["status"] == "noop"

    async def test_string_result_wrapped(self):
        async def h(task):
            return "plain text"

        ex = TaskExecutor(fallback=h)
        res = await ex.execute(_FakeTask("x"))
        assert res == {"status": "ok", "output": "plain text"}

    async def test_executor_drives_worker(self, q):
        async def h(task):
            return {"status": "ok", "did": task.title}

        ex = TaskExecutor(fallback=h)
        w = AutonomyWorker(q, policy=AutonomyPolicy(), executor=ex.execute)
        task = await w.submit("jarvis", "research_market", "Research CEE")
        await w.tick()
        assert q.get(task.id).status == "done"
        assert q.get(task.id).result["did"] == "Research CEE"


# ── digest ────────────────────────────────────────────────────────
class TestDigest:
    def test_morning_brief_sections(self, q):
        d = q.enqueue("jarvis", "draft_email", "Done task")
        q.transition(d, TaskStatus.APPROVED); q.transition(d, TaskStatus.RUNNING)
        q.transition(d, TaskStatus.DONE)
        q.enqueue("jarvis", "research", "Proposed task")
        text = build_morning_brief(q)
        assert "Morning brief" in text
        assert "Done task" in text
        assert "Proposed task" in text

    def test_evening_retro_lists_pending(self, q):
        b = q.enqueue("jarvis", "delete_file", "Risky thing", risk_tier=3)
        q.transition(b, TaskStatus.BLOCKED)
        text = build_evening_retro(q)
        assert "Evening retro" in text
        assert "Risky thing" in text
        assert "Batch approve" in text

    def test_evening_retro_empty_decisions(self, q):
        text = build_evening_retro(q)
        assert "Nicio decizie" in text


# ── preferences ───────────────────────────────────────────────────
class TestPreferences:
    @pytest.fixture
    def store(self, tmp_path):
        s = PreferenceStore(db_path=str(tmp_path / "autonomy.db"),
                            journal_path=str(tmp_path / "journal.jsonl")).initialize()
        yield s
        s.close()

    def test_record_and_approval_rate(self, store):
        for _ in range(4):
            store.record(_pref_task("jarvis", "draft_email", 1), "accept")
        store.record(_pref_task("jarvis", "draft_email", 1), "reject")
        rate = store.approval_rate("jarvis", "draft_email", 1)
        assert rate == pytest.approx(0.8)

    def test_suggest_raise_for_consistent_approvals(self, store):
        for _ in range(5):
            store.record(_pref_task("jarvis", "draft_email", 1), "accept")
        sugg = store.suggest_autonomy_raise()
        assert any(s["kind"] == "draft_email" for s in sugg)

    def test_no_suggestion_below_threshold(self, store):
        for _ in range(5):
            store.record(_pref_task("jarvis", "send_email", 2), "reject")
        assert store.suggest_autonomy_raise() == []

    def test_money_tier_never_suggested(self, store):
        for _ in range(10):
            store.record(_pref_task("gecko", "pay_invoice", 3), "accept")
        assert store.suggest_autonomy_raise() == []

    def test_journal_appended(self, store, tmp_path):
        store.record(_pref_task("jarvis", "draft_email", 1), "accept", decided_by="andrei")
        journal = (tmp_path / "journal.jsonl").read_text()
        assert "andrei" in journal and "draft_email" in journal

    async def test_worker_records_preference(self, q, tmp_path):
        store = PreferenceStore(db_path=str(tmp_path / "p.db"),
                               journal_path=str(tmp_path / "j.jsonl")).initialize()
        w = AutonomyWorker(q, policy=AutonomyPolicy(), prefs=store)
        task = await w.submit("jarvis", "delete_file", "Delete")  # blocked
        await w.apply_decision(task.id, "accept", decided_by="andrei")
        assert store.approval_rate("jarvis", "delete_file", 3) == 1.0
        store.close()


# ── night shift ───────────────────────────────────────────────────
class TestNightWindow:
    def test_wraps_midnight(self):
        assert is_night_window(23, 23, 6)
        assert is_night_window(2, 23, 6)
        assert is_night_window(5, 23, 6)
        assert not is_night_window(6, 23, 6)
        assert not is_night_window(12, 23, 6)

    def test_same_day_window(self):
        assert is_night_window(3, 1, 5)
        assert not is_night_window(6, 1, 5)

    def test_empty_window(self):
        assert not is_night_window(3, 5, 5)

    async def test_tick_max_tier_filters(self, q):
        async def h(task):
            return {"ok": True}

        w = AutonomyWorker(q, policy=AutonomyPolicy(), executor=h)
        rev = await w.submit("jarvis", "draft_email", "reversible")     # tier 1, auto-approved
        # an external task that we approve manually → tier 2
        ext = await w.submit("jarvis", "send_email", "external")        # notify → approved
        await w.tick(max_tier=1)
        assert q.get(rev.id).status == "done"
        assert q.get(ext.id).status == "approved"  # tier 2 skipped during night


def _pref_task(agent, kind, tier):
    t = _FakeTask(kind)
    t.agent = agent
    t.risk_tier = tier
    t.title = kind
    return t
