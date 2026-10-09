"""An explicit registrar contract can name a producer, never grant a call."""

import asyncio
from contextlib import contextmanager
from contextvars import copy_context
from types import SimpleNamespace

import pytest

from agents.core.approval_outcomes import (
    bind_approval_turn,
    close_approval_turn,
    open_approval_turn,
)
from agents.core.commands import Principal
from agents.core.tool_rpc import ToolRPCServer


async def send(args):
    return args


async def changed_send(args):
    return {"changed": args}


@contextmanager
def owner_turn(*, live=True):
    turn = open_approval_turn(
        session_id="session", session_instance="instance",
        principal=Principal(channel="web", admin=True),
        session_is_live=lambda *_: live,
    )
    token = bind_approval_turn(turn)
    try:
        yield
    finally:
        close_approval_turn(turn, token)


def server(handler=send, *, revision="mail.v1", schema=None, enqueue=None):
    rpc = ToolRPCServer(enqueue=enqueue)
    rpc.register_tool(
        "send_mail", handler, gated=True, consent_revision=revision,
        input_schema=schema or {"type": "object", "properties": {"to": {"type": "string"}}},
    )
    return rpc


def test_explicit_registration_stable_across_instances_and_changes_with_contract():
    first, second = server(), server()
    key = first._tools["send_mail"]["_consent_registration_key"]
    assert isinstance(key, str) and len(key) == 64
    assert key == second._tools["send_mail"]["_consent_registration_key"]
    assert first._tools["send_mail"]["_grouping_epoch"] != second._tools["send_mail"]["_grouping_epoch"]
    assert key != server(revision="mail.v2")._tools["send_mail"]["_consent_registration_key"]
    assert key != server(handler=changed_send)._tools["send_mail"]["_consent_registration_key"]
    assert key != server(schema={"type": "object", "properties": {}})._tools["send_mail"]["_consent_registration_key"]
    assert "_consent_registration_key" not in str(first.tools())


@pytest.mark.parametrize("revision", ["", " spaced ", "bad\nrevision", "a" * 129, 42])
def test_malformed_revision_refused(revision):
    with pytest.raises(ValueError, match="consent_revision"):
        server(revision=revision)


def test_undeclared_opaque_and_malformed_state_refuse_key():
    from agents.core.autonomy.consent_registration import trusted_registration_key

    assert server(revision=None)._tools["send_mail"]["_consent_registration_key"] is None
    opaque = server(handler=len)._tools["send_mail"]
    assert opaque["_consent_registration_key"] is None
    spec = dict(server()._tools["send_mail"])
    spec["input_schema"] = {"type": "object", "properties": {"bad": float("nan")}}
    assert trusted_registration_key("send_mail", spec) is None
    spec = dict(server()._tools["send_mail"])
    spec["handler"] = object()
    assert trusted_registration_key("send_mail", spec) is None
    spec = dict(server()._tools["send_mail"])
    spec["description"] = 42
    assert trusted_registration_key("send_mail", spec) is None
    spec = dict(server()._tools["send_mail"])
    spec["input_schema"] = []
    assert trusted_registration_key("send_mail", spec) is None
    spec = dict(server()._tools["send_mail"])
    spec["unknown_registration_field"] = "unreviewed"
    assert trusted_registration_key("send_mail", spec) is None


def test_unreadable_callback_module_refuses_key(monkeypatch):
    from agents.core.autonomy.consent_registration import trusted_registration_key

    spec = dict(server()._tools["send_mail"])
    def synthetic(args):
        return args
    monkeypatch.setattr(synthetic, "__module__", "h487_missing_module")
    spec["handler"] = synthetic
    assert trusted_registration_key("send_mail", spec) is None


@pytest.mark.asyncio
async def test_only_exact_live_generic_producer_exports_registration_key():
    from agents.core.autonomy.approval_grouping import model_consent_semantics
    observed = []
    rpc = None

    def enqueue(actor, kind, title, *, payload, **_):
        del title
        task = SimpleNamespace(agent=actor, kind=kind, payload=payload)
        from agents.core.autonomy.approval_grouping import current_model_producer

        context = current_model_producer()
        observed.append(model_consent_semantics(context, task))
        changed = SimpleNamespace(agent=actor, kind=kind, payload={**payload, "args": {"to": "other"}})
        observed.append(model_consent_semantics(context, changed))
        observed.append(model_consent_semantics(context, SimpleNamespace(agent="other", kind=kind, payload=payload)))
        observed.append(model_consent_semantics(context, task) if context is None else context)
        return 1

    rpc = server(enqueue=enqueue)
    key = rpc._tools["send_mail"]["_consent_registration_key"]
    with owner_turn():
        result = await rpc.handle({"tool": "send_mail", "args": {"to": "ana"}})
    assert result["reason"] == "approval_required"
    assert observed[0]["registration_key"] == key
    assert observed[1:3] == [None, None]
    context = observed[3]
    exact = SimpleNamespace(agent="jarvis", kind="toolrpc.send_mail", payload={"tool": "send_mail", "target": "send_mail", "args": {"to": "ana"}})
    assert model_consent_semantics(context, exact) is None
    async def copied():
        return model_consent_semantics(context, exact)
    assert await asyncio.create_task(copied(), context=copy_context()) is None


@pytest.mark.asyncio
async def test_undeclared_and_expired_turn_never_export_key():
    from agents.core.autonomy.approval_grouping import model_consent_semantics
    observed = []

    def enqueue(actor, kind, _title, *, payload, **_):
        from agents.core.autonomy.approval_grouping import current_model_producer
        observed.append(model_consent_semantics(current_model_producer(), SimpleNamespace(agent=actor, kind=kind, payload=payload)))
        return 1

    with owner_turn():
        await server(revision=None, enqueue=enqueue).handle({"tool": "send_mail", "args": {"to": "ana"}})
    with owner_turn(live=False):
        await server(enqueue=enqueue).handle({"tool": "send_mail", "args": {"to": "ana"}})
    assert observed == [None, None]


@pytest.mark.asyncio
async def test_mutated_registration_and_model_claims_cannot_export_provenance():
    from agents.core.autonomy.approval_grouping import (
        current_model_producer,
        model_consent_semantics,
    )

    observed = []
    rpc = None

    def enqueue(actor, kind, _title, *, payload, **_):
        context = current_model_producer()
        task = SimpleNamespace(agent=actor, kind=kind, payload=payload)
        if payload["args"].get("to") == "mutate":
            rpc._tools["send_mail"]["description"] = "changed after scope entry"
        observed.append(model_consent_semantics(context, task))
        return 1

    rpc = server(enqueue=enqueue)
    with owner_turn():
        await rpc.handle({"tool": "send_mail", "args": {"to": "mutate"}})
    rpc = server(enqueue=enqueue)
    with owner_turn():
        await rpc.handle({"tool": "send_mail", "args": {"to": "ana", "registration_key": "forged"}})
    assert observed == [None, None]


def test_consent_verifier_failure_preserves_legacy_grouping():
    from agents.core.approval_outcomes import tool_approval_scope
    from agents.core.autonomy.approval_grouping import (
        current_model_producer,
        model_consent_semantics,
        model_group_semantics,
        model_request_scope,
    )

    def broken(_candidate):
        raise RuntimeError("unavailable")

    task = SimpleNamespace(
        agent="jarvis", kind="toolrpc.send_mail",
        payload={"tool": "send_mail", "target": "send_mail", "args": {"to": "ana"}},
    )
    with owner_turn(), tool_approval_scope("send_mail"), model_request_scope(
        actor="jarvis", tool="send_mail", args={"to": "ana"},
        epoch="a" * 32, registration_is_live=lambda: True,
        registration_key="b" * 64, registration_key_is_live=broken,
    ):
        context = current_model_producer()
        assert model_group_semantics(context, task) is not None
        assert model_consent_semantics(context, task) is None
