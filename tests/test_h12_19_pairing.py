"""H12.19: Inbound sender pairing / approval — opt-in, held-not-run, anti-abuse.

Unknown senders on a channel are held for owner approval (or self-pair with a
code) instead of being silently dropped or reaching the handler. The human-sender
mirror of the H16.2 A2A peer allowlist. Off by default → behavior unchanged.
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.channels.pairing import SenderPairing, ALLOWED, PENDING, BLOCKED, UNKNOWN  # noqa: E402
from core.channels.gateway import Gateway  # noqa: E402
import agents.web as web  # noqa: E402


@pytest.fixture
def reg(tmp_path):
    return SenderPairing(path=str(tmp_path / "pairing.json"))


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("JARVIS_CHANNEL_PAIRING", "1")


# ── store: opt-in gate ────────────────────────────────────────────

def test_disabled_allows_everyone(reg, monkeypatch):
    monkeypatch.delenv("JARVIS_CHANNEL_PAIRING", raising=False)
    assert reg.is_allowed("telegram", "999") is True          # unchanged behavior
    assert reg.status("telegram", "999") == UNKNOWN


def test_enabled_unknown_sender_is_held(reg, enabled):
    assert reg.is_allowed("telegram", "999") is False
    result = reg.request("telegram", "999", name="Mallory")
    assert result == {"status": PENDING, "allowed": False}
    assert reg.status("telegram", "999") == PENDING
    assert len(reg.list_senders(PENDING)) == 1


def test_request_is_idempotent_no_duplicate_pending(reg, enabled):
    reg.request("telegram", "999")
    reg.request("telegram", "999")
    assert len(reg.list_senders(PENDING)) == 1


# ── owner decisions ───────────────────────────────────────────────

def test_approve_then_allowed(reg, enabled):
    reg.request("telegram", "999")
    reg.approve("telegram", "999")
    assert reg.is_allowed("telegram", "999") is True
    # an already-allowed sender short-circuits request()
    assert reg.request("telegram", "999") == {"status": ALLOWED, "allowed": True}


def test_reject_drops_pending_but_does_not_block(reg, enabled):
    reg.request("telegram", "999")
    assert reg.reject("telegram", "999") is True
    assert reg.status("telegram", "999") == UNKNOWN          # may try again
    assert reg.reject("telegram", "999") is False            # nothing pending now


def test_block_is_silent_and_sticky(reg, enabled):
    reg.block("telegram", "spammer")
    assert reg.status("telegram", "spammer") == BLOCKED
    assert reg.request("telegram", "spammer") == {"status": BLOCKED, "allowed": False}
    # gate_inbound returns an empty (silent) message for blocked senders
    assert reg.gate_inbound("telegram", "spammer")["message"] == ""


def test_unpair_revokes(reg, enabled):
    reg.approve("telegram", "999")
    assert reg.unpair("telegram", "999") is True
    assert reg.status("telegram", "999") == UNKNOWN
    assert reg.unpair("telegram", "999") is False


def test_decide_dispatcher(reg, enabled):
    assert reg.decide("telegram", "1", "approve")["status"] == ALLOWED
    assert reg.decide("telegram", "2", "block")["status"] == BLOCKED
    reg.request("telegram", "3")
    assert reg.decide("telegram", "3", "reject") == {"rejected": True}
    with pytest.raises(ValueError):
        reg.decide("telegram", "1", "frobnicate")


# ── pairing code (self-service) ───────────────────────────────────

def test_correct_code_auto_pairs(reg, enabled):
    reg.set_code("hunter2")
    result = reg.request("telegram", "999", code="hunter2")
    assert result["allowed"] is True and result["paired_by"] == "code"
    assert reg.is_allowed("telegram", "999") is True


def test_wrong_code_stays_pending(reg, enabled):
    reg.set_code("hunter2")
    assert reg.request("telegram", "999", code="nope")["status"] == PENDING


def test_clearing_code_disables_self_pair(reg, enabled):
    reg.set_code("hunter2")
    reg.set_code(None)
    assert reg.has_code() is False
    assert reg.request("telegram", "999", code="hunter2")["status"] == PENDING


# ── anti-abuse ────────────────────────────────────────────────────

def test_rate_limited_after_max_attempts(reg, enabled):
    # First _MAX_ATTEMPTS (5) are recorded; the next is rate-limited.
    for _ in range(5):
        reg.request("telegram", "flood")
    assert reg.request("telegram", "flood")["status"] == "rate_limited"


def test_persistence_round_trip(tmp_path, enabled):
    p = str(tmp_path / "p.json")
    SenderPairing(path=p).approve("telegram", "999")
    assert SenderPairing(path=p).is_allowed("telegram", "999") is True


# ── gateway integration ───────────────────────────────────────────

async def test_gateway_holds_unpaired_sender(reg, enabled):
    seen = []

    async def handler(text, channel="web", **kw):
        seen.append(text)
        return "routed"

    gw = Gateway(handler=handler, pairing=reg)
    # unknown sender → held, handler NOT called, friendly hold message
    out = await gw.route("hi", channel="telegram", sender="999")
    assert out and "approval" in out.lower()
    assert seen == []
    # owner approves → now routes through
    reg.approve("telegram", "999")
    out2 = await gw.route("hi again", channel="telegram", sender="999")
    assert out2 == "routed" and seen == ["hi again"]


async def test_gateway_without_sender_routes_normally(reg, enabled):
    async def handler(text, channel="web", **kw):
        return "routed"

    gw = Gateway(handler=handler, pairing=reg)
    # no sender kwarg (e.g. web channel) → pairing is a no-op
    assert await gw.route("hi", channel="web") == "routed"


async def test_gateway_code_auto_pairs(reg, enabled):
    async def handler(text, channel="web", **kw):
        return "routed"

    reg.set_code("open-sesame")
    gw = Gateway(handler=handler, pairing=reg)
    out = await gw.route("hi", channel="telegram", sender="999", pairing_code="open-sesame")
    assert out == "routed"
    assert reg.is_allowed("telegram", "999") is True


# ── endpoints ─────────────────────────────────────────────────────

def _client(monkeypatch, tmp_path):
    monkeypatch.setattr(web, "_sender_pairing",
                        SenderPairing(path=str(tmp_path / "pairing.json")))
    monkeypatch.setattr(web, "orch", None)
    monkeypatch.setattr(web, "ADMIN_TOKEN", "adm")
    return TestClient(web.app), {"X-Admin-Token": "adm"}


def test_request_endpoint_gated_on_enabled(monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)
    monkeypatch.delenv("JARVIS_CHANNEL_PAIRING", raising=False)
    body = {"channel": "telegram", "sender_id": "999"}
    assert client.post("/api/channels/pairing/request", json=body).status_code == 404


def test_request_then_approve_flow(monkeypatch, tmp_path, enabled):
    client, hdr = _client(monkeypatch, tmp_path)
    body = {"channel": "telegram", "sender_id": "999", "name": "Mallory"}
    r = client.post("/api/channels/pairing/request", json=body)
    assert r.status_code == 200 and r.json()["status"] == "pending"

    # admin list requires a token
    assert client.get("/api/channels/pairing").status_code == 401
    listed = client.get("/api/channels/pairing", headers=hdr).json()
    assert listed["summary"]["pending"] == 1
    assert listed["senders"][0]["sender_id"] == "999"

    # owner approves → sender now allowed
    dec = client.post("/api/channels/pairing/decide",
                      json={"channel": "telegram", "sender_id": "999", "action": "approve"},
                      headers=hdr)
    assert dec.status_code == 200 and dec.json()["status"] == "allowed"


def test_code_endpoint_enables_self_pair(monkeypatch, tmp_path, enabled):
    client, hdr = _client(monkeypatch, tmp_path)
    assert client.post("/api/channels/pairing/code", json={"code": "hunter2"},
                       headers=hdr).json()["has_code"] is True
    r = client.post("/api/channels/pairing/request",
                    json={"channel": "telegram", "sender_id": "7", "code": "hunter2"})
    assert r.json()["allowed"] is True


def test_decide_rejects_unknown_action(monkeypatch, tmp_path, enabled):
    client, hdr = _client(monkeypatch, tmp_path)
    r = client.post("/api/channels/pairing/decide",
                    json={"channel": "telegram", "sender_id": "1", "action": "nuke"},
                    headers=hdr)
    assert r.status_code == 400
