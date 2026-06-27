"""B3 — the strict-egress downgrade (JARVIS_STRICT_EGRESS=0) is no longer silent.

When the escape hatch allows a policy violation, a durable audit sink is invoked. Strict
mode (the default) raises instead, so the sink is never called. The sink is decoupled —
http_client never imports the security types; the orchestrator owns the SecurityEvent.
"""

import pytest

from agents.core import http_client
from agents.core.http_client import PluginEgressError, PluginHTTPClient, set_egress_audit_sink


@pytest.fixture(autouse=True)
def _reset_sink():
    yield
    set_egress_audit_sink(None)


def test_downgrade_invokes_audit_sink(monkeypatch):
    monkeypatch.setenv("JARVIS_STRICT_EGRESS", "0")   # escape hatch on → downgrade, not block
    calls = []
    set_egress_audit_sink(lambda plugin, violation: calls.append((plugin, violation)))
    c = PluginHTTPClient("weather")                   # RESTRICTED → wttr.in only
    c._enforce_egress("https://evil.example/x")        # disallowed host → downgrade
    assert len(calls) == 1
    plugin, violation = calls[0]
    assert plugin == "weather" and "evil.example" in violation


def test_strict_mode_blocks_and_never_audits_a_downgrade(monkeypatch):
    monkeypatch.setenv("JARVIS_STRICT_EGRESS", "1")   # default — block, no downgrade
    calls = []
    set_egress_audit_sink(lambda *a: calls.append(a))
    with pytest.raises(PluginEgressError):
        PluginHTTPClient("weather")._enforce_egress("https://evil.example/x")
    assert calls == []                                # a block is not a downgrade


def test_no_sink_is_a_safe_noop(monkeypatch):
    monkeypatch.setenv("JARVIS_STRICT_EGRESS", "0")
    set_egress_audit_sink(None)
    # must not raise even with no sink installed
    PluginHTTPClient("weather")._enforce_egress("https://evil.example/x")


def test_a_failing_sink_never_breaks_egress(monkeypatch):
    monkeypatch.setenv("JARVIS_STRICT_EGRESS", "0")

    def _boom(plugin, violation):
        raise RuntimeError("audit down")

    set_egress_audit_sink(_boom)
    # the downgrade still succeeds despite the audit sink throwing
    PluginHTTPClient("weather")._enforce_egress("https://evil.example/x")


def test_sink_is_decoupled_from_security_types():
    # http_client must not import the security event types (keeps the low-level module clean)
    import inspect
    src = inspect.getsource(http_client)
    assert "SecurityEvent" not in src
