"""A command-start observation has one consented, body-free extension payload."""

from __future__ import annotations

import asyncio
import os

import pytest

from agents.core.extensions import events
from agents.core.extensions.consent import CHANGED, GRANTED, ExtensionConsentStore, declared_digest
from agents.core.extensions.manifest import parse_manifest


def _manifest(observed: list[str]):
    return parse_manifest({
        "manifest_version": 1, "api_version": 1, "id": "boats", "version": "1.0.0",
        "capabilities": ["events.observe"], "tools": [], "commands": [],
        "events": observed, "requires": {"extensions": {}, "python": {}},
    })


def test_new_event_is_additive_and_requires_fresh_exact_consent(tmp_path):
    previous_umask = os.umask(0o077)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    try:
        store = ExtensionConsentStore(private / "consent.json")
        old = _manifest(["command.completed"])
        assert declared_digest(old) == (
            "d343e9859c7223c9cb85a8e5f8993836f2128a60b8604cbe6f9693771a538f01")
        assert store.grant(old).state == GRANTED
        assert store.check(_manifest(["command.completed"])).state == GRANTED

        widened = _manifest(["command.completed", "command.started"])
        assert widened.events == ("command.completed", "command.started")
        assert declared_digest(widened) != declared_digest(old)
        changed = store.check(widened)
        assert changed.state == CHANGED and changed.allowed is False
        assert changed.added == ("event:command.started",)
        assert store.grant(widened).state == GRANTED
        assert store.check(widened).allowed is True
    finally:
        os.umask(previous_umask)


@pytest.mark.parametrize("private_field", [
    "args", "raw_text", "principal", "reply", "body", "status",
])
def test_started_payload_refuses_private_or_extra_fields(private_field):
    bus = events.ExtensionEventBus(runtime=None)
    with pytest.raises(ValueError, match="unknown_event_field"):
        bus.emit("command.started", command="status", **{private_field: "private"})


@pytest.mark.asyncio
async def test_started_observation_is_body_free_and_bounded_without_waiting():
    class Runtime:
        def __init__(self):
            self.seen = []
            self.release = asyncio.Event()

        def observers(self, _event):
            return ("boats",)

        async def observe(self, extension_id, event, payload):
            self.seen.append((extension_id, event, payload))
            await self.release.wait()

    runtime = Runtime()
    bus = events.ExtensionEventBus(runtime=runtime, max_pending=1)
    first = bus.emit("command.started", command="status")
    bus.emit("command.started", command="status")
    assert first["delivered"] == ["boats"]
    assert bus.dropped == 1, "the bounded queue drops the second observer task"
    assert runtime.seen == [], "delivery has not run while the emitter returns"
    runtime.release.set()
    await bus.drain(timeout=1)
    assert len(runtime.seen) == 1
    extension_id, name, payload = runtime.seen[0]
    assert (extension_id, name) == ("boats", "command.started")
    assert set(payload) == {"event", "event_id", "occurred_at", "command"}
    assert payload["command"] == "status"


def test_started_event_is_not_forwarded_to_owner_hooks(monkeypatch):
    from agents.core.hooks import runner

    seen = []
    monkeypatch.setattr(runner, "observe", lambda *args, **kwargs: seen.append((args, kwargs)))
    assert "command.started" not in events.OWNER_HOOK_EVENTS
    bound = events._BoundBus()
    assert bound.emit("command.started", command="status") is None
    assert seen == []
