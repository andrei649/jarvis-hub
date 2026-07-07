import pytest

from agents.core.automation_contracts import ContractDecision, ContractTemplate, predicate
from agents.core.channels import manager as manager_mod
from agents.core.channels.manager import ChannelManager


class _FakeTelegram:
    channel_id = "telegram"

    def __init__(self):
        self.sent = []

    async def send(self, message, **kwargs):
        self.sent.append((message, kwargs))
        return True


def _denying_contract(reason: str = "channel_send_blocked") -> ContractTemplate:
    return ContractTemplate(
        kind="channel.send",
        constraints=(predicate("deny", lambda view, now: False, reason=reason),),
    )


@pytest.mark.asyncio
async def test_channel_send_contract_denial_blocks_adapter(monkeypatch):
    monkeypatch.setattr(
        manager_mod,
        "CHANNEL_SEND_CONTRACT",
        _denying_contract(),
        raising=False,
    )
    adapter = _FakeTelegram()
    manager = ChannelManager()
    manager.register(adapter)

    ok = await manager.send("telegram", "private body", chat_id=99)

    assert ok is False
    assert adapter.sent == []


class _CapturingAllowContract:
    def __init__(self):
        self.payloads = []

    def evaluate(self, payload=None, **kwargs):
        self.payloads.append(dict(payload or {}))
        return ContractDecision(
            kind="channel.send",
            admissible=True,
            requires_approval=False,
        )


@pytest.mark.asyncio
async def test_channel_send_contract_payload_is_shape_only(monkeypatch):
    contract = _CapturingAllowContract()
    monkeypatch.setattr(manager_mod, "CHANNEL_SEND_CONTRACT", contract, raising=False)
    adapter = _FakeTelegram()
    manager = ChannelManager()
    manager.register(adapter)

    ok = await manager.send(
        "telegram",
        "private body",
        chat_id=99,
        token="secret-token",
    )

    assert ok is True
    assert adapter.sent == [
        ("private body", {"chat_id": 99, "token": "secret-token"}),
    ]
    assert contract.payloads == [{
        "kind": "channel.send",
        "channel": "telegram",
        "message_len": len("private body"),
        "kwarg_keys": ["chat_id", "token"],
        "kwarg_count": 2,
    }]
    assert "private body" not in repr(contract.payloads[0])
    assert "secret-token" not in repr(contract.payloads[0])
    assert "99" not in repr(contract.payloads[0])
