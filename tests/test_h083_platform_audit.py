"""Durable, redacted outcomes for the owner platform control command."""

import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest

from agents.core.channels.manager import ChannelManager
from agents.core.commands import CommandContext, Principal
from agents.core.platform_commands import platform_command
from agents.core.security.audit import AuditLogger
from agents.core.security.types import SecurityEventType
from tests.test_h083_platform_command import FakeChannel


def _ctx(manager, audit, args, *, owner=True):
    return CommandContext(SimpleNamespace(channel_manager=manager, audit=audit),
                          Principal(channel="web", admin=owner), "platform", args)


def _rows(audit):
    return audit.query(event_type=SecurityEventType.SETTINGS_CHANGE.value)


@pytest.mark.asyncio
async def test_paused_and_resumed_rows_are_durable_and_chain_verifies(tmp_path):
    audit = AuditLogger(str(tmp_path / "audit.db"))
    manager = ChannelManager()
    channel = FakeChannel()
    manager.register(channel)
    channel.health.retrying("network", 5)
    try:
        assert "paused" in await platform_command(_ctx(manager, audit, "pause telegram"))
        assert "restart attempted" in await platform_command(_ctx(manager, audit, "resume telegram"))
        assert "telegram" in await platform_command(_ctx(manager, audit, "list"))
        rows = list(reversed(_rows(audit)))
        assert [row.event_type for row in rows] == [SecurityEventType.SETTINGS_CHANGE] * 2
        assert [row.action_taken for row in rows] == ["platform_control"] * 2
        assert [json.loads(row.content_preview) for row in rows] == [
            {"action": "pause", "actor": "owner", "target": "telegram", "outcome": "paused"},
            {"action": "resume", "actor": "owner", "target": "telegram", "outcome": "resumed"},
        ]
        assert audit.verify_chain()[0]
    finally:
        audit.close()


@pytest.mark.asyncio
async def test_unknown_custom_and_unrecognized_status_never_store_raw_input(tmp_path):
    audit = AuditLogger(str(tmp_path / "audit.db"))
    secret_name = "private-api-key-canary"

    class Manager:
        channels = {secret_name: object()}

        async def pause_failed(self, target):
            assert target == secret_name
            return {"status": "private-provider-status-canary"}

        async def resume_paused(self, target):
            raise AssertionError("unexpected resume")

        async def platform_snapshot(self):
            return {}

    try:
        manager = Manager()
        assert "Unknown platform" in await platform_command(_ctx(manager, audit, "pause unknown-token-canary"))
        assert "could not be confirmed" in await platform_command(_ctx(manager, audit, f"pause {secret_name}"))
        rows = list(reversed(_rows(audit)))
        assert len(rows) == 2
        unknown, custom = [json.loads(row.content_preview) for row in rows]
        assert unknown == {"action": "pause", "actor": "owner", "target": "unresolved",
                           "outcome": "refused_target"}
        fingerprint = hashlib.sha256(b"platform-control-target\0" + secret_name.encode()).hexdigest()
        shown = "custom:" + ":".join(fingerprint[i:i + 16] for i in range(0, len(fingerprint), 16))
        assert custom == {"action": "pause", "actor": "owner", "target": shown,
                          "outcome": "unknown"}
        assert "canary" not in " ".join(row.content_preview for row in rows)
        assert audit.verify_chain()[0]
    finally:
        audit.close()


@pytest.mark.asyncio
async def test_safe_mode_refusal_and_audit_outage_visible_without_undoing_pause(tmp_path, monkeypatch):
    from agents.core import safe_mode

    audit = AuditLogger(str(tmp_path / "audit.db"))
    manager = ChannelManager()
    channel = FakeChannel()
    manager.register(channel)
    channel.health.retrying("network", 5)
    try:
        original_log = audit.log
        monkeypatch.setattr(audit, "log", lambda event: (_ for _ in ()).throw(OSError("secret")))
        reply = await platform_command(_ctx(manager, audit, "pause telegram"))
        assert "paused" in reply and "Audit record unavailable" in reply
        assert (await manager.platform_snapshot())["telegram"]["pause_state"] == "paused"
        monkeypatch.setattr(audit, "log", original_log)
        monkeypatch.setattr(safe_mode, "enabled", lambda: True)
        assert "Safe mode" in await platform_command(_ctx(manager, audit, "resume telegram"))
        assert json.loads(_rows(audit)[0].content_preview)["outcome"] == "safe_mode"
    finally:
        audit.close()


@pytest.mark.asyncio
async def test_cancelled_or_exceptional_manager_operation_records_only_unknown(tmp_path):
    audit = AuditLogger(str(tmp_path / "audit.db"))
    entered = asyncio.Event()

    class Manager:
        channels = {"telegram": object()}

        async def pause_failed(self, target):
            entered.set()
            await asyncio.Event().wait()
            return {"status": "paused"}

        async def resume_paused(self, target):
            raise RuntimeError("private-exception-canary")

        async def platform_snapshot(self):
            return {}

    try:
        manager = Manager()
        task = asyncio.create_task(platform_command(_ctx(manager, audit, "pause telegram")))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert "could not be confirmed" in await platform_command(_ctx(manager, audit, "resume telegram"))
        assert [json.loads(row.content_preview)["outcome"] for row in _rows(audit)] == ["unknown", "unknown"]
        assert audit.verify_chain()[0]
        assert "canary" not in " ".join(row.content_preview for row in _rows(audit))
    finally:
        audit.close()
