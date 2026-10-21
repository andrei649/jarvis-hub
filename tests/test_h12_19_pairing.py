"""H12.19: Inbound sender pairing / approval — held-not-run, anti-abuse.

Unknown senders on a channel are held for owner approval (or self-pair with a
code) instead of being silently dropped or reaching the handler. The human-sender
mirror of the H16.2 A2A peer allowlist. On by default since Hermes absorption 5b
(``tests/test_default_deny_front_door.py``); the "disabled" cases here set
``JARVIS_CHANNEL_PAIRING=0`` explicitly.
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


# ── store: the gate, switched off explicitly ──────────────────────

def test_disabled_allows_everyone(reg, monkeypatch):
    monkeypatch.setenv("JARVIS_CHANNEL_PAIRING", "0")
    assert reg.is_allowed("telegram", "999") is True          # off means open
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
    import agents.core.routers.pairing as _pairing_mod
    monkeypatch.setattr(_pairing_mod, "_sender_pairing",
                        SenderPairing(path=str(tmp_path / "pairing.json")))
    monkeypatch.setattr(web, "orch", None)
    monkeypatch.setattr(web, "ADMIN_TOKEN", "adm")
    return TestClient(web.app), {"X-Admin-Token": "adm"}


def test_request_endpoint_gated_on_enabled(monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)
    monkeypatch.setenv("JARVIS_CHANNEL_PAIRING", "0")
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


# ── H154: bulk "clear pending" (owner action, audited) ─────────────

def test_clear_pending_drops_only_pending_and_persists(tmp_path, enabled):
    path = str(tmp_path / "pairing.json")
    reg = SenderPairing(path=path)
    reg.request("telegram", "1")
    reg.request("discord", "2")
    reg.approve("telegram", "3")
    reg.block("telegram", "4")
    assert reg.clear_pending() == 2
    assert reg.status("telegram", "1") == UNKNOWN
    assert reg.status("discord", "2") == UNKNOWN
    assert reg.status("telegram", "3") == ALLOWED       # approved senders survive
    assert reg.status("telegram", "4") == BLOCKED       # a block is never undone by this
    assert reg.summary()[PENDING] == 0
    fresh = SenderPairing(path=path)
    assert fresh.status("telegram", "1") == UNKNOWN and fresh.status("telegram", "3") == ALLOWED
    assert reg.clear_pending() == 0                     # nothing left: a no-op, not an error


def test_clear_pending_is_not_a_block(reg, enabled):
    reg.request("telegram", "1")
    reg.clear_pending()
    assert reg.request("telegram", "1")["status"] == PENDING   # may ask again


def _audited_client(monkeypatch, tmp_path):
    from types import SimpleNamespace
    client, hdr = _client(monkeypatch, tmp_path)
    events = []
    monkeypatch.setattr(web, "orch", SimpleNamespace(
        audit=SimpleNamespace(log=events.append), sender_pairing=None))
    return client, hdr, events


def _pairing_rows(events):
    return [ev for ev in events if str(getattr(ev, "action_taken", "")).startswith("pairing_")]


def test_clear_pending_endpoint_is_admin_only(monkeypatch, tmp_path, enabled):
    import agents.core.routers.pairing as _pairing_mod
    client, _hdr, events = _audited_client(monkeypatch, tmp_path)
    client.post("/api/channels/pairing/request", json={"channel": "telegram", "sender_id": "9"})
    assert client.post("/api/channels/pairing/clear-pending").status_code in (401, 403)
    assert _pairing_mod._sender_pairing.status("telegram", "9") == PENDING
    assert _pairing_rows(events) == []
    from tests.test_route_auth_matrix import _runtime_guards
    assert _runtime_guards()["POST /api/channels/pairing/clear-pending"] == "admin"


def test_clear_pending_endpoint_clears_and_audits(monkeypatch, tmp_path, enabled):
    client, hdr, events = _audited_client(monkeypatch, tmp_path)
    for sid in ("alice-7", "bob-8"):
        client.post("/api/channels/pairing/request", json={"channel": "telegram", "sender_id": sid})
    client.post("/api/channels/pairing/decide",
                json={"channel": "telegram", "sender_id": "carol-9", "action": "approve"}, headers=hdr)
    r = client.post("/api/channels/pairing/clear-pending", headers=hdr)
    assert r.status_code == 200 and r.json() == {"ok": True, "cleared": 2}
    summary = client.get("/api/channels/pairing", headers=hdr).json()["summary"]
    assert summary["pending"] == 0 and summary["allowed"] == 1
    rows = _pairing_rows(events)
    assert len(rows) == 1
    assert rows[0].action_taken == "pairing_clear_pending"
    assert rows[0].event_type.value == "settings_change"
    assert "cleared=2" in rows[0].content_preview
    # A count is enough: the row does not copy who was waiting.
    assert "alice-7" not in rows[0].content_preview and "bob-8" not in rows[0].content_preview


def test_clear_pending_endpoint_survives_a_broken_audit_log(monkeypatch, tmp_path, enabled):
    from types import SimpleNamespace
    client, hdr = _client(monkeypatch, tmp_path)

    def boom(_event):
        raise RuntimeError("disk full")

    monkeypatch.setattr(web, "orch", SimpleNamespace(audit=SimpleNamespace(log=boom),
                                                     sender_pairing=None))
    client.post("/api/channels/pairing/request", json={"channel": "telegram", "sender_id": "1"})
    r = client.post("/api/channels/pairing/clear-pending", headers=hdr)
    assert r.status_code == 200 and r.json()["cleared"] == 1
