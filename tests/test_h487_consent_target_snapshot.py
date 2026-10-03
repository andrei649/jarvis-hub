"""Consent classifications read declared targets without launching transports."""

from agents.core.environments.targets import TargetRegistry, TerminalTarget


def test_passive_target_snapshot_preserves_declared_identity_without_audit():
    target = TerminalTarget('synthetic', 'local', True, frozenset({'jarvis'}),
                            frozenset({'terminal.exec'}), frozenset({'terminal.exec'}))
    registry = TargetRegistry([target])
    snapshot = getattr(registry, 'snapshot', None)
    assert callable(snapshot), 'consent needs a passive current target snapshot'
    assert snapshot('synthetic') is target
    assert snapshot('missing') is None
    assert registry.audit.verify_chain()
    assert registry.names() == ['synthetic']
