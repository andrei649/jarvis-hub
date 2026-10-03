"""Guardian observer text is scanned before truncation and cannot carry authority."""
from __future__ import annotations

import contextvars
import json

import pytest

from agents.core.extensions.events import ExtensionEventBus
from agents.core.extensions.manifest import parse_manifest
from agents.core.log_catalogue import CatalogueScanner
from agents.core.security.scanner import SecretScanner

REQUEST = "approval.smart.requested"
DECIDED = "approval.smart.decided"
RID = "0123456789ab4def8123456789abcdef"


class Runtime:
    def __init__(self, context=None):
        self.seen = []
        self.context = context

    def observers(self, event):
        return ("observer",)

    async def observe(self, extension_id, event, payload):
        self.seen.append((event, payload, self.context.get() if self.context else None))
        return {"decision": "approve", "grant": "injected"}


def fields(**changes):
    return {"request_id": RID, "surface": "smart", "command": "printf hello",
            "description": "Print a greeting", **changes}


def test_new_observer_manifest_has_explicit_consent_scope():
    value = {"manifest_version": 1, "api_version": 1, "id": "observer", "version": "1.0.0",
             "capabilities": ["events.observe"], "tools": [], "commands": [],
             "events": [REQUEST, DECIDED], "requires": {"extensions": {}, "python": {}}}
    parsed = parse_manifest(value)
    assert set(parsed.events) == {REQUEST, DECIDED}


@pytest.mark.asyncio
async def test_forced_redaction_preserves_useful_text_with_log_masking_disabled(monkeypatch):
    from agents.core.security import log_redaction

    monkeypatch.setenv("JARVIS_LOG_REDACTION", "0")
    monkeypatch.setattr(log_redaction, "_ENABLED", False)
    runtime = Runtime()
    bus = ExtensionEventBus(runtime=runtime)
    bus.emit(REQUEST, **fields(command="printf hello password=swordfish",
                               description="Print greeting; api_key='synthetic-sensitive-value'"))
    await bus.drain(timeout=1)
    event, payload, _ = runtime.seen[0]
    assert event == REQUEST
    assert set(payload) == {"event", "event_id", "occurred_at", "request_id", "surface",
                            "command", "description"}
    assert "printf hello" in payload["command"]
    assert "Print greeting" in payload["description"]
    text = json.dumps(payload)
    assert "swordfish" not in text and "synthetic-sensitive-value" not in text
    assert "REDACTED" in payload["command"] and "REDACTED" in payload["description"]


@pytest.mark.asyncio
async def test_redaction_sees_whole_token_crossing_output_truncation():
    runtime = Runtime()
    bus = ExtensionEventBus(runtime=runtime)
    secret = "ghp_" + "Q" * 36
    bus.emit(REQUEST, **fields(command="printf " + "x " * 88 + secret))
    await bus.drain(timeout=1)
    command = runtime.seen[0][1]["command"]
    assert len(command) <= 200
    assert "ghp_" not in command and "Q" * 10 not in command
    assert "REDACTED" in command


@pytest.mark.asyncio
async def test_decided_event_carries_only_fixed_auxiliary_outcome():
    runtime = Runtime()
    bus = ExtensionEventBus(runtime=runtime)
    report = bus.emit(DECIDED, **fields(choice="smart_deny", decided_by="aux_llm"))
    await bus.drain(timeout=1)
    payload = runtime.seen[0][1]
    assert payload["request_id"] == RID and payload["choice"] == "smart_deny"
    assert payload["decided_by"] == "aux_llm"
    assert set(payload) == {"event", "event_id", "occurred_at", "request_id", "surface",
                            "command", "description", "choice", "decided_by"}
    assert "decision" not in report and "grant" not in report


@pytest.mark.parametrize("event,changes", [
    (REQUEST, {"surface": "advisory"}), (REQUEST, {"request_id": "user-private-principal"}),
    (REQUEST, {"command": {"secret": "nested"}}), (REQUEST, {"description": None}),
    (REQUEST, {"command": "x" * 4001}), (REQUEST, {"command": "bad\ud800"}),
    (REQUEST, {"token": "private"}), (DECIDED, {"choice": "smart_escalate", "decided_by": "aux_llm"}),
    (DECIDED, {"choice": "smart_approve", "decided_by": "human"}),
    (DECIDED, {"choice": "smart_approve"}),
])
def test_invalid_observer_fields_never_reach_runtime(event, changes):
    runtime = Runtime()
    bus = ExtensionEventBus(runtime=runtime)
    with pytest.raises((ValueError, UnicodeError)):
        bus.emit(event, **fields(**changes))
    assert runtime.seen == []


@pytest.mark.parametrize("scanner", [SecretScanner, CatalogueScanner])
def test_redactor_failure_refuses_payload_without_delivering_raw_text(monkeypatch, scanner):
    def broken(self, text):
        raise RuntimeError("private-scanner-failure")
    monkeypatch.setattr(scanner, "redact", broken)
    runtime = Runtime()
    bus = ExtensionEventBus(runtime=runtime)
    with pytest.raises(RuntimeError):
        bus.emit(REQUEST, **fields(command="printf private-command"))
    assert runtime.seen == []


@pytest.mark.asyncio
@pytest.mark.parametrize("source,private", [
    ("curl 'https://example.invalid/?token=abc'", "abc"),
    ('printf \'{"client_secret": "tiny"}\'', "tiny"),
    ("curl -H 'Authorization: Bearer short' https://example.invalid", "short"),
])
async def test_named_short_credentials_are_forced_masked(source, private):
    runtime = Runtime()
    bus = ExtensionEventBus(runtime=runtime)
    bus.emit(REQUEST, **fields(command=source))
    await bus.drain(timeout=1)
    command = runtime.seen[0][1]["command"]
    assert private not in command
    assert "REDACTED" in command


@pytest.mark.asyncio
async def test_guardian_delivery_does_not_inherit_request_or_turn_context():
    private = contextvars.ContextVar("private-test-context", default="fresh")
    token = private.set("original-approval-context")
    try:
        runtime = Runtime(context=private)
        bus = ExtensionEventBus(runtime=runtime)
        bus.emit(REQUEST, **fields())
        await bus.drain(timeout=1)
        assert runtime.seen[0][2] == "fresh"
    finally:
        private.reset(token)
