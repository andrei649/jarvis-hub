"""Platform controls cross the real command gate and durable audit store."""

import json
from types import SimpleNamespace

import pytest

from agents.core.channels.manager import ChannelManager
from agents.core.commands import Principal, build_default_registry
from agents.core.security.audit import AuditLogger
from tests.test_h083_platform_command import FakeChannel


@pytest.mark.asyncio
async def test_owner_pause_records_durable_outcome_after_real_manager_transition(tmp_path):
    path = tmp_path / "audit.db"
    audit = AuditLogger(str(path))
    manager = ChannelManager()
    channel = FakeChannel()
    manager.register(channel)
    await channel.start()
    channel.health.retrying("network", 10)
    try:
        outcome = await build_default_registry().dispatch(
            "/platform pause telegram",
            orch=SimpleNamespace(channel_manager=manager, audit=audit),
            principal=Principal(channel="web", admin=True))
        assert "paused" in outcome.reply
        assert channel.stops == 1 and not channel._running
    finally:
        audit.close()
        await manager.stop_all()
    reopened = AuditLogger(str(path))
    try:
        rows = [r for r in reopened.query() if r.action_taken == "platform_control"]
        assert len(rows) == 1
        record = json.loads(rows[0].content_preview)
        assert record == {"action": "pause", "actor": "owner", "target": "telegram",
                          "outcome": "paused"}
        assert reopened.verify_chain() == (True, None)
    finally:
        reopened.close()


@pytest.mark.asyncio
async def test_guest_dispatch_keeps_existing_denial_audit_without_control_attempt(tmp_path):
    audit = AuditLogger(str(tmp_path / "audit.db"))
    manager = ChannelManager()
    channel = FakeChannel()
    manager.register(channel)
    try:
        outcome = await build_default_registry().dispatch(
            "/platform pause PRIVATE_UNTRUSTED_ARGUMENT",
            orch=SimpleNamespace(channel_manager=manager, audit=audit),
            principal=Principal(channel="web", admin=False))
        assert outcome.status == "refused"
        assert channel.stops == channel.starts == 0
        rows = audit.query()
        assert [r.action_taken for r in rows] == ["slash_command_denied"]
        assert "PRIVATE_UNTRUSTED_ARGUMENT" not in rows[0].content_preview
        assert audit.verify_chain() == (True, None)
    finally:
        audit.close()
