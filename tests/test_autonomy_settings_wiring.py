"""
test_autonomy_settings_wiring.py — Tests dynamic wiring of settings to event watchers.

Ensures that settings modifications in SQLite settings database (e.g. min_ron, min_sleep,
lead_time_min, priority_senders) propagate to the probes and trigger correct signals.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta

from agents.core.autonomy.watchers import (
    EmailProbe, CalendarProbe, FinanceProbe, HealthProbe, EventWatcher
)
from agents.core.autonomy.observer import Signal, Severity
from agents.core.autonomy import AutonomyWorker, AutonomyPolicy, TaskQueue


class FakeGmailPlugin:
    async def list_messages(self, max_results=5, query=""):
        return [
            {"id": "msg1", "subject": "Vorbim mâine", "from": "Mihai", "snippet": "Salut"},
            {"id": "msg2", "subject": "Important update", "from": "Andrei", "snippet": "I need your view"},
        ]


class FakeCalendarPlugin:
    async def get_today_events(self):
        # STANDUP is starting in 15 minutes
        now = datetime.now(timezone.utc)
        ts_soon = (now + timedelta(minutes=15)).isoformat()
        return [
            {"id": "ev1", "title": "Standup", "ts": ts_soon, "state": "upcoming"}
        ]


class FakeBalancePlugin:
    async def get_balances(self):
        return {
            "ing": [{"account": "ING_RON", "balance": 1500.0, "currency": "RON"}]
        }


class FakeHealthPlugin:
    async def get_summary(self, days=1):
        return {
            "sleep": [{"hours": 4.5}],
            "hrv": [{"value": 28.0}]
        }


@pytest.mark.asyncio
async def test_email_probe_dynamic_settings():
    # Setup dynamic mock get_setting
    settings = {"autonomy.priority_senders": ["andrei"]}
    def mock_get_setting(key, default=None):
        return settings.get(key, default)

    gmail = FakeGmailPlugin()
    probe = EmailProbe(gmail_plugin=gmail, priority_senders=["mihai"], get_setting=mock_get_setting)

    # Initial run: priority_senders should return ["andrei"] from get_setting, and not the default ["mihai"]
    assert probe.priority_senders == ["andrei"]
    signals = await probe()
    by_key = {s.key: s for s in signals}
    # msg2 from Andrei is urgent/priority, msg1 from Mihai is healthy
    assert by_key["email.urgent.msg2"].healthy is False
    assert by_key["email.urgent.msg1"].healthy is True

    # Change settings dynamically
    settings["autonomy.priority_senders"] = ["mihai"]
    assert probe.priority_senders == ["mihai"]
    signals = await probe()
    by_key = {s.key: s for s in signals}
    # msg1 from Mihai is now urgent, msg2 from Andrei is healthy
    assert by_key["email.urgent.msg1"].healthy is False
    assert by_key["email.urgent.msg2"].healthy is True


@pytest.mark.asyncio
async def test_calendar_probe_dynamic_settings():
    settings = {"autonomy.calendar_lead_time": 30}
    def mock_get_setting(key, default=None):
        return settings.get(key, default)

    calendar = FakeCalendarPlugin()
    probe = CalendarProbe(calendar_plugin=calendar, lead_time_min=10, get_setting=mock_get_setting)

    # Standup is in 15 minutes. Threshold is 30, so 15 < 30 -> alert (unhealthy)
    assert probe.lead_time_min == 30
    signals = await probe()
    assert signals[0].healthy is False

    # Dynamic change: lead time is now 10 mins. 15 > 10 -> healthy!
    settings["autonomy.calendar_lead_time"] = 10
    assert probe.lead_time_min == 10
    signals = await probe()
    assert signals[0].healthy is True


@pytest.mark.asyncio
async def test_finance_probe_dynamic_settings():
    settings = {
        "autonomy.finance_min_ron": 2000.0,
        "autonomy.finance_min_eur": 400.0
    }
    def mock_get_setting(key, default=None):
        return settings.get(key, default)

    balance = FakeBalancePlugin()
    probe = FinanceProbe(balance_plugin=balance, min_ron=1000.0, get_setting=mock_get_setting)

    # ING balance is 1500 RON. Min threshold in setting is 2000 -> alert (unhealthy)
    assert probe.min_ron == 2000.0
    signals = await probe()
    assert signals[0].healthy is False

    # Dynamic change: threshold is 1000 RON. 1500 > 1000 -> healthy!
    settings["autonomy.finance_min_ron"] = 1000.0
    assert probe.min_ron == 1000.0
    signals = await probe()
    assert signals[0].healthy is True


@pytest.mark.asyncio
async def test_health_probe_dynamic_settings():
    settings = {
        "autonomy.health_min_sleep": 5.0,
        "autonomy.health_min_hrv": 30.0
    }
    def mock_get_setting(key, default=None):
        return settings.get(key, default)

    health = FakeHealthPlugin()
    probe = HealthProbe(health_plugin=health, min_sleep_hrs=6.0, get_setting=mock_get_setting)

    # Sleep logged is 4.5. Threshold is 5.0 -> alert (unhealthy)
    assert probe.min_sleep_hrs == 5.0
    assert probe.min_hrv_ms == 30.0
    signals = await probe()
    by_key = {s.key: s for s in signals}
    assert by_key["health.sleep"].healthy is False
    assert by_key["health.hrv"].healthy is False

    # Dynamic change: sleep threshold is 4.0, hrv is 20 -> healthy!
    settings["autonomy.health_min_sleep"] = 4.0
    settings["autonomy.health_min_hrv"] = 20.0
    assert probe.min_sleep_hrs == 4.0
    assert probe.min_hrv_ms == 20.0
    signals = await probe()
    by_key = {s.key: s for s in signals}
    assert by_key["health.sleep"].healthy is True
    assert by_key["health.hrv"].healthy is True
