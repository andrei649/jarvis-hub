"""Tests for O26-P3.5 persona rail + caring follow-ups."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from agents.core.autonomy.digest import build_morning_brief
from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.memory.timeline import build_unified_digest
from agents.core.observability.quality import (
    QualityMonitor,
    persona_profile_from_soul,
    score_trace,
)


def _iso(hour: int) -> str:
    return datetime(2026, 7, 4, hour, 0, tzinfo=UTC).isoformat()


def _mem(category: str, key: str, value: str, ts: str) -> dict:
    return {"category": category, "key": key, "value": value, "updated_at": ts}


def _task(tid: int, title: str, status: str, ts: str):
    return SimpleNamespace(
        id=tid,
        title=title,
        status=status,
        updated_at=ts,
        risk_tier=1,
        agent_id="jarvis",
        agent="jarvis",
    )


class _FollowupQueue:
    def __init__(self, *tasks):
        self._tasks = list(tasks)

    def list(self, status=None, limit=500):
        rows = [t for t in self._tasks if status is None or t.status == status]
        return rows[:limit]

    def pending_decisions(self, limit=100, only_unpushed=False):
        return [t for t in self._tasks if t.status in {"blocked", "proposed"}][:limit]


def test_persona_profile_from_soul_extracts_forbidden_patterns():
    soul = """
    ## Voice & Tone
    **Forbidden patterns:**
    - No preambles ("Sure!", "Of course!", "Happy to help!")
    - No AI disclaimers ("As an AI...")
    **Required patterns:**
    - Direct response in the first sentence
    """

    profile = persona_profile_from_soul(soul, version=4)

    assert profile["version"] == 4
    assert {"sure", "of course", "happy to help", "as an ai"} <= set(profile["forbidden"])


def test_persona_score_uses_assistant_reply_not_user_prompt():
    trace = {
        "id": "persona-1",
        "text_preview": "sir, please be direct and concise",
        "output_preview": "Sure, maybe I can help with that.",
        "ok": True,
        "timings": {"total_ms": 100},
        "persona_profile": {
            "version": "soul-v7",
            "required_any": ["sir"],
            "forbidden": ["sure", "maybe"],
        },
    }

    result = score_trace(trace)

    assert result["persona"]["version"] == "soul-v7"
    assert result["signals"]["persona"] < 0.5


def test_quality_monitor_exposes_persona_drift_alert():
    monitor = QualityMonitor(window=3, threshold=0.2, persona_threshold=0.7)
    profile = {
        "version": "soul-v2",
        "required_any": ["sir"],
        "forbidden": ["sure", "maybe"],
    }

    for idx in range(3):
        monitor.record({
            "id": f"trace-{idx}",
            "route": "jarvis",
            "output_preview": "Sure, maybe later.",
            "ok": True,
            "timings": {"total_ms": 100},
            "persona_profile": profile,
        })

    stats = monitor.stats()
    alert = monitor.check_alert()
    recent = monitor.recent(1)[0]

    assert stats["persona"]["avg_score"] < 0.7
    assert stats["persona"]["alerting"] is True
    assert alert["persona_alerting"] is True
    assert recent["persona_score"] < 0.7
    assert recent["soul_version"] == "soul-v2"


def test_cognition_trace_passes_versioned_soul_profile_to_quality():
    from agents.core.cognition_trace import update_cognition

    soul = '- No preambles ("Sure!")\n- No AI disclaimers ("As an AI...")'

    class _Tracer:
        def record(self, trace):
            self.trace = trace
            return "trace-id"

    class _Quality:
        threshold = 0.6

        def record(self, trace):
            self.trace = trace
            return {"score": 0.5}

    class _SoulVersions:
        def current(self, agent_id):
            assert agent_id == "jarvis"
            return {"version": 2, "hash": "abc123", "content": soul}

    orch = SimpleNamespace(
        tracer=_Tracer(),
        quality=_Quality(),
        agents={"jarvis": SimpleNamespace(config={"model": "local-model"}, soul={"content": soul})},
        soul_versions=_SoulVersions(),
        cognition=None,
        review_queue=None,
        _last_channel="web",
        last_cognition={},
    )
    intent = SimpleNamespace(
        context={"keywords_found": [], "scores": {}, "source": "test"},
        target_agents=["jarvis"],
        confidence=1.0,
    )

    update_cognition(orch, "hello", intent, {}, "Sure, here it is.", 1, 1, 0, 1)

    trace = orch.quality.trace
    assert trace["soul_version"] == 2
    assert trace["soul_hash"] == "abc123"
    assert "sure" in trace["persona_profile"]["forbidden"]


def test_morning_brief_adds_caring_followups_from_existing_rows(tmp_path):
    queue = TaskQueue(db_path=str(tmp_path / "autonomy.db")).initialize()
    try:
        failed = queue.enqueue("jarvis", "deploy", "Failed deployment", risk_tier=1)
        queue.transition(failed, TaskStatus.APPROVED)
        queue.transition(failed, TaskStatus.RUNNING)
        queue.transition(failed, TaskStatus.FAILED)
        blocked = queue.enqueue("pepper", "calendar", "Blocked calendar hold", risk_tier=2)
        queue.transition(blocked, TaskStatus.BLOCKED)
        memory_entries = [
            _mem("open_concern", "launch_anxiety", "Owner is worried about the launch", _iso(9)),
            _mem("kg_date", "dentist", "Dentist appointment tomorrow at 10:00", _iso(10)),
        ]

        text = build_morning_brief(queue, memory_entries=memory_entries, now=datetime(2026, 7, 4, 12, 0, tzinfo=UTC).timestamp())

        assert "Follow-ups" in text
        assert "Failed deployment" in text
        assert "Blocked calendar hold" in text
        assert "worried about the launch" in text
        assert "Dentist appointment" in text
    finally:
        queue.close()


def test_unified_digest_includes_caring_followups():
    queue = _FollowupQueue(
        _task(1, "Done action", "done", _iso(8)),
        _task(2, "Failed sync", "failed", _iso(9)),
        _task(3, "Blocked approval", "blocked", _iso(10)),
    )
    memory_entries = [
        _mem("fact", "city", "Bucharest", _iso(7)),
        _mem("open_concern", "presentation", "Check in on the presentation", _iso(11)),
        _mem("kg_date", "tax_deadline", "Tax deadline tomorrow", _iso(12)),
    ]

    out = build_unified_digest(
        queue,
        memory_entries,
        now=datetime(2026, 7, 4, 13, 0, tzinfo=UTC).timestamp(),
        days=1,
    )

    assert out["counts"]["actions"] == 1
    assert out["counts"]["learnings"] == 3
    assert out["counts"]["followups"] == 4
    assert any(it["kind"] == "followup" and it["title"] == "Failed sync" for it in out["items"])
    assert any(it["kind"] == "followup" and "Tax deadline" in it["detail"] for it in out["items"])
