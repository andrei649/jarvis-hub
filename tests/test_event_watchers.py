"""
Tests for Proactive Personal Event Watchers (agents/core/autonomy/watchers.py).

Verifies state debouncing, alert transitions, and graceful mocking behavior offline.
"""

from __future__ import annotations

import asyncio
import pytest
from datetime import datetime, timezone, timedelta

from agents.core.autonomy.watchers import (
    EventWatcher, EmailProbe, CalendarProbe, FinanceProbe, HealthProbe
)
from agents.core.autonomy.observer import Signal, Severity, Finding
from agents.core.autonomy import AutonomyWorker, AutonomyPolicy, TaskQueue


class FakeGmailPlugin:
    def __init__(self, messages=None):
        self.messages = messages or []

    async def list_messages(self, max_results=5, query=""):
        return self.messages


class FakeCalendarPlugin:
    def __init__(self, events=None):
        self.events = events or []

    async def get_today_events(self):
        return self.events


class FakeBalancePlugin:
    def __init__(self, balances=None, burn_rate=None):
        self.balances = balances or {}
        self.burn_rate = burn_rate or {}

    async def get_balances(self):
        return self.balances

    async def get_burn_rate(self, days=30):
        return self.burn_rate


class FakeHealthPlugin:
    def __init__(self, summary=None):
        self.summary = summary or {}

    async def get_summary(self, days=1):
        return self.summary


def _worker() -> AutonomyWorker:
    queue = TaskQueue(db_path=":memory:").initialize()
    return AutonomyWorker(queue, policy=AutonomyPolicy())


# ── Debouncing & Transitions ───────────────────────────────────────────
def test_event_watcher_debounce():
    watcher = EventWatcher(None, [])
    broken = Signal("email.urgent.123", healthy=False, severity=Severity.WARN)
    healthy = Signal("email.urgent.123", healthy=True)

    # Transition healthy -> broken: alert
    f1 = watcher.evaluate([broken])
    assert len(f1) == 1
    assert f1[0].transition == "alert"

    # Still broken: no-op (debounced)
    f2 = watcher.evaluate([broken])
    assert len(f2) == 0

    # Transition broken -> healthy: recovery
    f3 = watcher.evaluate([healthy])
    assert len(f3) == 1
    assert f3[0].transition == "recovery"


# ── Email Probe Tests ─────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_email_probe_alerts_on_urgent_keywords():
    messages = [
        {"id": "msg1", "subject": "Hey there", "from": "John", "snippet": "Hello world"},
        {"id": "msg2", "subject": "URGENT: Server Down", "from": "Ops", "snippet": "Please check ASAP"},
        {"id": "msg3", "subject": "Critical issue reported", "from": "Support", "snippet": "A crash occurred"}
    ]
    gmail = FakeGmailPlugin(messages)
    probe = EmailProbe(gmail)

    signals = await probe()
    by_key = {s.key: s for s in signals}
    
    assert by_key["email.urgent.msg1"].healthy is True
    assert by_key["email.urgent.msg2"].healthy is False
    assert by_key["email.urgent.msg2"].severity == Severity.WARN
    assert by_key["email.urgent.msg3"].healthy is False
    assert by_key["email.urgent.msg3"].severity == Severity.CRITICAL


# ── Calendar Probe Tests ──────────────────────────────────────────────
@pytest.mark.asyncio
async def test_calendar_probe_upcoming_meeting():
    now_ts = datetime.now(timezone.utc)
    ts_soon = (now_ts + timedelta(minutes=15)).isoformat()
    ts_far = (now_ts + timedelta(hours=2)).isoformat()

    events = [
        {"id": "ev1", "title": "Coffee", "ts": ts_far, "state": "upcoming"},
        {"id": "ev2", "title": "Standup", "ts": ts_soon, "state": "next"}
    ]
    calendar = FakeCalendarPlugin(events)
    probe = CalendarProbe(calendar)

    signals = await probe()
    by_key = {s.key: s for s in signals}

    assert by_key["calendar.meeting.ev1"].healthy is True
    assert by_key["calendar.meeting.ev2"].healthy is False
    assert "Standup" in by_key["calendar.meeting.ev2"].detail


# ── Finance Probe Tests ───────────────────────────────────────────────
@pytest.mark.asyncio
async def test_finance_probe_balance_and_runway():
    balances = {
        "ing": [{"account": "ING_RO", "balance": 1500.0, "currency": "RON"}],
        "libra": [{"account": "LIB_RO", "balance": 4500.0, "currency": "RON"}],
        "mock": False
    }
    burn_rate = {"runway_months": 2.1}

    balance_plugin = FakeBalancePlugin(balances, burn_rate)
    probe = FinanceProbe(balance_plugin, min_ron=2000.0)

    signals = await probe()
    by_key = {s.key: s for s in signals}

    assert by_key["finance.balance.ING_RO"].healthy is False  # 1500 < 2000 RON
    assert by_key["finance.balance.LIB_RO"].healthy is True   # 4500 >= 2000 RON
    assert by_key["finance.runway"].healthy is False          # 2.1 < 3 months


# ── Health Probe Tests ────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_health_probe_sleep_and_stress():
    summary = {
        "sleep": [{"hours": 4.2}],  # Short sleep
        "hrv": [{"value": 25.0}, {"value": 27.0}],  # Low HRV strain
    }
    health_plugin = FakeHealthPlugin(summary)
    probe = HealthProbe(health_plugin, min_sleep_hrs=5.0, min_hrv_ms=30.0)

    signals = await probe()
    by_key = {s.key: s for s in signals}

    assert by_key["health.sleep"].healthy is False
    assert by_key["health.hrv"].healthy is False
    assert "Short sleep" in by_key["health.sleep"].detail


# ── Full E2E Observe Workflow ───────────────────────────────────────────
@pytest.mark.asyncio
async def test_event_watcher_observe_and_submit():
    w = _worker()
    
    # Setup mock probes that return 1 alert
    sig_alert = Signal("finance.balance.ING_RO", healthy=False, severity=Severity.WARN, detail="Low cash")
    async def mock_probe():
        return [sig_alert]
        
    watcher = EventWatcher(w, [mock_probe])
    
    res = await watcher.observe()
    assert res["sampled"] == 1
    assert res["findings"] == 1
    assert res["submitted"] == 1
    assert res["unhealthy"] == ["finance.balance.ING_RO"]
    
    # Task queue should have a new alert task
    tasks = w.queue.list()
    assert len(tasks) == 1
    assert tasks[0].kind == "monitor.alert"
    assert tasks[0].status == "approved"  # READ_ONLY -> auto-acts
    assert "Low cash" in tasks[0].title
