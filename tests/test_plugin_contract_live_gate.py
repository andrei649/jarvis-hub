"""0.45 — live plugin permission gate uses an automation contract."""

from agents.core.automation_contracts import ContractDecision
from agents.core.plugin_gate import PermissionGate


class _FakePluginContract:
    def __init__(self, reason: str | None) -> None:
        self.reason = reason
        self.calls = []

    def evaluate(self, payload=None, **kwargs):
        payload = payload or {}
        self.calls.append((payload, kwargs))
        return ContractDecision(
            kind="plugin_call",
            admissible=self.reason is None,
            requires_approval=False,
            reason=self.reason,
            checked=("fake",),
        )


def test_permission_gate_obeys_live_contract_decision(monkeypatch):
    import agents.core.plugin_gate as plugin_gate

    contract = _FakePluginContract("contract_denied")
    monkeypatch.setattr(plugin_gate, "PLUGIN_CALL_CONTRACT", contract)

    gate = PermissionGate(least_privilege=False)

    assert gate.check_call("weather", "frigga", "wttr.in") is False
    assert contract.calls
    payload, kwargs = contract.calls[-1]
    assert payload["plugin_id"] == "weather"
    assert payload["agent_id"] == "frigga"
    assert payload["target_domain"] == "wttr.in"
    assert payload["manifest"].id == "weather"
    assert payload["gate"] is gate
    assert "now" in kwargs
