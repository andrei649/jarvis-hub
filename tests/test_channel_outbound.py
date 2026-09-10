"""Sending to a destination the owner configured, with no inbound thread (H018 / H480).

`nerva send` could only propose a reply into a thread Nerva had already received, so a
script had no way to say anything first. The resolution it needed was not missing — it
was inside ``JobRunner._send``, reachable only by a firing job.

What is pinned here is the part that makes the extraction safe rather than convenient:
the reversible tier means no approval queue stands between the call and the transport,
so the audit record is the *only* trace the send happened. Every path through this module
is asserted against the log, including the refusal path, and `audited` is asserted to be
reported rather than assumed — a send that could not be recorded must not claim it was.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.core.channels import outbound
from agents.core.channels.send_rate_limit import reset as reset_rate_limit


class _Adapter:
    descriptor = SimpleNamespace(max_message_length=4096, dialect="plain")

    def __init__(self, *, ok: bool = True, raises: Exception | None = None):
        self.ok = ok
        self.raises = raises
        self.sent: list[tuple[str, dict]] = []

    async def send(self, text, **kwargs):
        if self.raises is not None:
            raise self.raises
        self.sent.append((text, kwargs))
        return self.ok


class _Sink:
    def __init__(self, *, working: bool = True):
        self.records: list[tuple[str, dict]] = []
        self.working = working

    def log(self, event, fields=None):
        self.records.append((event, dict(fields or {})))
        return {"seq": len(self.records)} if self.working else None


def make_orch(*, channels=None, owner="7788", sink=None):
    orch = SimpleNamespace(
        channels=dict(channels or {}),
        get_setting=lambda key, default=None: owner if key == outbound.OWNER_CHAT_SETTING else default,
        action_audit=sink if sink is not None else _Sink(),
        channel_manager=None,
    )
    return orch


@pytest.fixture(autouse=True)
def _clean_rate_limit(monkeypatch):
    monkeypatch.delenv(outbound.OWNER_CHAT_ENV, raising=False)
    reset_rate_limit()
    yield
    reset_rate_limit()


# ── resolving a destination ──────────────────────────────────────────────────

def test_telegram_resolves_to_the_configured_owner_chat():
    orch = make_orch(channels={"telegram": _Adapter()})
    kwargs, reason = outbound.resolve_destination(orch, "telegram")
    assert kwargs == {"chat_id": 7788} and reason == ""


def test_the_environment_overrides_the_stored_owner_chat(monkeypatch):
    monkeypatch.setenv(outbound.OWNER_CHAT_ENV, "999")
    orch = make_orch(channels={"telegram": _Adapter()}, owner="7788")
    assert outbound.resolve_destination(orch, "telegram")[0] == {"chat_id": 999}


def test_a_channel_that_addresses_itself_needs_no_destination():
    orch = make_orch(channels={"ntfy": _Adapter()})
    assert outbound.resolve_destination(orch, "ntfy") == ({}, "")


def test_a_missing_owner_chat_is_refused_by_name_not_generically():
    orch = make_orch(channels={"telegram": _Adapter()}, owner="")
    kwargs, reason = outbound.resolve_destination(orch, "telegram")
    assert kwargs is None
    assert outbound.OWNER_CHAT_SETTING in reason, "the reason must name the missing setting"


def test_a_non_numeric_owner_chat_is_refused_rather_than_crashing():
    orch = make_orch(channels={"telegram": _Adapter()}, owner="not-a-chat")
    assert outbound.resolve_destination(orch, "telegram")[0] is None


def test_an_unconnected_channel_is_refused():
    assert outbound.resolve_destination(make_orch(), "telegram")[0] is None


def test_email_is_not_a_direct_send_channel():
    """Keeping SMTP out of the generic send API is what stops untrusted inbound mail
    from gaining an outbound side effect; this seam must not reopen it."""
    assert "email" not in outbound.DIRECT_SEND_CHANNELS
    orch = make_orch(channels={"email": _Adapter()})
    kwargs, reason = outbound.resolve_destination(orch, "email")
    assert kwargs is None and "direct-send" in reason


# ── listing targets ──────────────────────────────────────────────────────────

def test_targets_list_unready_channels_with_the_reason_rather_than_hiding_them():
    orch = make_orch(channels={"telegram": _Adapter()}, owner="")
    rows = {row["channel"]: row for row in outbound.configured_targets(orch)}
    assert set(rows) == set(outbound.DIRECT_SEND_CHANNELS)
    assert rows["telegram"]["connected"] is True and rows["telegram"]["ready"] is False
    assert outbound.OWNER_CHAT_SETTING in rows["telegram"]["reason"]
    assert rows["ntfy"]["connected"] is False


def test_a_ready_target_carries_the_channels_own_caps():
    orch = make_orch(channels={"telegram": _Adapter()})
    row = next(r for r in outbound.configured_targets(orch) if r["channel"] == "telegram")
    assert row["ready"] is True and row["max_message_length"] == 4096


# ── sending ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_send_reaches_the_adapter_and_is_recorded():
    adapter, sink = _Adapter(), _Sink()
    orch = make_orch(channels={"telegram": adapter}, sink=sink)
    result = await outbound.send_to_target(orch, "telegram", "the roof is leaking")

    assert result == {"ok": True, "channel": "telegram", "audited": True}
    assert adapter.sent == [("the roof is leaking", {"chat_id": 7788})]
    event, fields = sink.records[0]
    assert event == "channel.send"
    assert fields["channel"] == "telegram" and fields["delivered"] is True


@pytest.mark.asyncio
async def test_the_message_body_is_never_written_into_the_audit_record():
    """The log says a send happened, not what it said; the transcript is elsewhere."""
    sink = _Sink()
    orch = make_orch(channels={"telegram": _Adapter()}, sink=sink)
    await outbound.send_to_target(orch, "telegram", "PRIVATE-BODY-TEXT")
    assert "PRIVATE-BODY-TEXT" not in repr(sink.records)
    assert sink.records[0][1]["chars"] == len("PRIVATE-BODY-TEXT")


@pytest.mark.asyncio
async def test_a_refused_delivery_is_still_recorded_as_an_attempt():
    sink = _Sink()
    orch = make_orch(channels={"telegram": _Adapter(ok=False)}, sink=sink)
    result = await outbound.send_to_target(orch, "telegram", "hello")
    assert result["ok"] is False and "refused" in result["reason"]
    assert sink.records and sink.records[0][1]["delivered"] is False, (
        "an attempt that failed must not vanish from the log"
    )


@pytest.mark.asyncio
async def test_a_send_that_could_not_be_recorded_says_so_instead_of_claiming_it_was():
    orch = make_orch(channels={"telegram": _Adapter()}, sink=_Sink(working=False))
    result = await outbound.send_to_target(orch, "telegram", "hello")
    assert result["ok"] is True and result["audited"] is False


@pytest.mark.asyncio
async def test_a_hub_with_no_audit_sink_still_sends_but_reports_it_unaudited():
    adapter = _Adapter()
    orch = make_orch(channels={"telegram": adapter})
    orch.action_audit = None
    result = await outbound.send_to_target(orch, "telegram", "hello")
    assert result["ok"] is True and result["audited"] is False
    assert adapter.sent, "the owner's message is not dropped because logging is absent"


@pytest.mark.asyncio
async def test_an_adapter_that_raises_is_a_named_refusal_not_a_traceback():
    orch = make_orch(channels={"telegram": _Adapter(raises=RuntimeError("boom"))})
    result = await outbound.send_to_target(orch, "telegram", "hello")
    assert result["ok"] is False and "RuntimeError" in result["reason"]


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["", "   ", "x" * (outbound.MAX_TEXT_CHARS + 1)])
async def test_an_empty_or_oversized_message_never_reaches_the_transport(text):
    adapter = _Adapter()
    orch = make_orch(channels={"telegram": adapter})
    result = await outbound.send_to_target(orch, "telegram", text)
    assert result["ok"] is False and adapter.sent == []


@pytest.mark.asyncio
async def test_the_configured_send_rate_limit_applies_to_this_path_too(monkeypatch):
    monkeypatch.setenv("JARVIS_CHANNEL_SEND_RATE", "1")
    reset_rate_limit()
    adapter = _Adapter()
    orch = make_orch(channels={"telegram": adapter})
    assert (await outbound.send_to_target(orch, "telegram", "one"))["ok"] is True
    second = await outbound.send_to_target(orch, "telegram", "two")
    assert second["ok"] is False and "rate" in second["reason"]
    assert len(adapter.sent) == 1


# ── the HTTP surface ─────────────────────────────────────────────────────────

@pytest.fixture()
def hub(monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web

    monkeypatch.setattr(web, "ADMIN_TOKEN", "secret")
    adapter, sink = _Adapter(), _Sink()
    orch = make_orch(channels={"telegram": adapter}, sink=sink)
    with TestClient(web.app) as client:
        real = web.orch
        web.orch = orch
        try:
            yield client, orch, adapter, sink
        finally:
            web.orch = real


ADMIN = {"x-admin-token": "secret"}


def test_both_routes_are_owner_only(hub):
    client, *_ = hub
    assert client.get("/api/channels/targets").status_code == 401
    assert client.post("/api/channels/send", json={"channel": "telegram", "text": "x"}).status_code == 401


def test_targets_route_reports_every_direct_send_channel(hub):
    client, *_ = hub
    rows = client.get("/api/channels/targets", headers=ADMIN).json()["targets"]
    assert [r["channel"] for r in rows] == list(outbound.DIRECT_SEND_CHANNELS)
    assert next(r for r in rows if r["channel"] == "telegram")["ready"] is True


def test_send_route_delivers_and_reports_that_it_was_audited(hub):
    client, _orch, adapter, sink = hub
    body = client.post("/api/channels/send",
                       json={"channel": "telegram", "text": "the roof is leaking"},
                       headers=ADMIN)
    assert body.status_code == 200
    assert body.json() == {"ok": True, "channel": "telegram", "audited": True}
    assert adapter.sent[0][0] == "the roof is leaking"
    assert sink.records[0][0] == "channel.send"


def test_send_route_refuses_with_the_reason_in_the_routers_shape(hub):
    client, _orch, adapter, _sink = hub
    r = client.post("/api/channels/send", json={"channel": "email", "text": "x"}, headers=ADMIN)
    assert r.status_code == 422 and "direct-send" in r.json()["error"]
    r = client.post("/api/channels/send", json={"channel": "telegram", "text": ""}, headers=ADMIN)
    assert r.status_code == 422
    assert adapter.sent == []
