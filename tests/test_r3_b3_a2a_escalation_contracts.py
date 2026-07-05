import json

import pytest

from agents.core import a2a as a2a_mod
from agents.core.a2a import A2ARegistry, _hmac
from agents.core.automation_contracts import ContractTemplate, predicate
from agents.core.autonomy import escalation as escalation_mod
from agents.core.autonomy.escalation import EscalationRouter


def _denying_contract(kind: str, reason: str = "blocked_by_test") -> ContractTemplate:
    return ContractTemplate(
        kind=kind,
        constraints=(predicate("deny", lambda view, now: False, reason=reason),),
    )


def test_a2a_contract_denial_blocks_inbox_write(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_A2A_ENABLED", "1")
    monkeypatch.setattr(
        a2a_mod,
        "A2A_INBOUND_CONTRACT",
        _denying_contract("a2a.inbound", reason="peer_blocked"),
        raising=False,
    )
    reg = A2ARegistry(path=str(tmp_path / "a2a.json"), identity_secret="idkey")
    peer = reg.add_peer("alice")
    body = json.dumps({"task": {"kind": "summarize", "text": "private body"}})

    with pytest.raises(PermissionError, match="contract denied: peer_blocked"):
        reg.receive_task("alice", body, _hmac(peer["secret"], body))

    assert reg.list_inbox("pending") == []


class _FakeChannel:
    def __init__(self):
        self.sent = []

    async def send(self, message, **kwargs):
        self.sent.append(message)
        return True


@pytest.mark.asyncio
async def test_escalation_contract_denial_blocks_channel_sends(monkeypatch):
    monkeypatch.setattr(
        escalation_mod,
        "ESCALATION_CONTRACT",
        _denying_contract("autonomy.escalation", reason="broadcast_blocked"),
        raising=False,
    )
    chans = {"slack": _FakeChannel(), "telegram": _FakeChannel()}
    router = EscalationRouter(chans, allow=["slack", "telegram"])

    out = await router.escalate("decision needed", channels=["telegram", "slack"])

    assert out["delivered"] == []
    assert out["failed"] == ["slack", "telegram"]
    assert out["results"] == {"slack": False, "telegram": False}
    assert out["denied"] == "contract denied: broadcast_blocked"
    assert chans["slack"].sent == []
    assert chans["telegram"].sent == []
