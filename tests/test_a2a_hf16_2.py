"""H16.2: Agent-to-Agent endpoint — opt-in, allowlisted, signed, approval-gated.

A2A is off by default; a known peer signs each task with its shared secret; a
verified task lands in a pending inbox the owner approves/rejects — nothing
auto-executes. Mirrors the H16.4 signed-source HMAC scheme.
"""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.a2a import A2ARegistry, _hmac  # noqa: E402
import agents.web as web  # noqa: E402


@pytest.fixture
def reg(tmp_path):
    return A2ARegistry(path=str(tmp_path / "a2a.json"), identity_secret="idkey")


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.setenv("JARVIS_A2A_ENABLED", "1")


# ── registry ──────────────────────────────────────────────────────

def test_agent_card_signed_only_with_identity_key(tmp_path):
    signed = A2ARegistry(path=str(tmp_path / "a.json"), identity_secret="k").agent_card()
    assert signed["signature"] and signed["signature"].startswith("sha256=")
    unsigned = A2ARegistry(path=str(tmp_path / "b.json"), identity_secret=None).agent_card()
    assert unsigned["signature"] is None


def test_add_peer_returns_secret_once_then_masks(reg):
    peer = reg.add_peer("alice", name="Alice")
    assert len(peer["secret"]) > 10
    listed = reg.list_peers()
    assert listed[0]["peer_id"] == "alice"
    assert "secret" not in listed[0] and listed[0]["secret_hint"].endswith("…")


def test_receive_task_happy_path(reg):
    peer = reg.add_peer("alice")
    body = json.dumps({"task": {"kind": "summarize"}})
    receipt = reg.receive_task("alice", body, _hmac(peer["secret"], body))
    assert receipt["status"] == "pending" and receipt["accepted"] is True
    assert len(reg.list_inbox("pending")) == 1


def test_receive_task_fails_closed(reg, monkeypatch):
    peer = reg.add_peer("alice")
    body = json.dumps({"task": 1})
    sig = _hmac(peer["secret"], body)
    # unknown peer / bad signature
    with pytest.raises(PermissionError):
        reg.receive_task("mallory", body, sig)
    with pytest.raises(PermissionError):
        reg.receive_task("alice", body, "sha256=bad")
    # disabled service
    monkeypatch.delenv("JARVIS_A2A_ENABLED", raising=False)
    with pytest.raises(PermissionError):
        reg.receive_task("alice", body, sig)


def test_decide_is_terminal_and_does_not_execute(reg):
    peer = reg.add_peer("alice")
    body = json.dumps({"task": "x"})
    rid = reg.receive_task("alice", body, _hmac(peer["secret"], body))["id"]
    assert reg.decide(rid, True)["status"] == "approved"
    with pytest.raises(ValueError):           # already decided
        reg.decide(rid, False)


# ── endpoints ─────────────────────────────────────────────────────

def _client(monkeypatch, tmp_path):
    monkeypatch.setattr(web, "_a2a_registry", A2ARegistry(path=str(tmp_path / "a2a.json"), identity_secret="idk"))
    monkeypatch.setattr(web, "ADMIN_TOKEN", "adm")
    return TestClient(web.app), {"X-Admin-Token": "adm"}


def test_card_endpoint_gated_on_enabled(monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)
    assert client.get("/.well-known/agent-card").status_code == 200
    monkeypatch.delenv("JARVIS_A2A_ENABLED", raising=False)
    assert client.get("/.well-known/agent-card").status_code == 404


def test_task_endpoint_rejects_bad_signature_and_accepts_valid(monkeypatch, tmp_path):
    client, hdr = _client(monkeypatch, tmp_path)
    peer = web._a2a_registry.add_peer("alice")
    body = json.dumps({"task": {"kind": "research"}})
    # bad signature → 401
    bad = client.post("/api/a2a/task", content=body, headers={"X-A2A-Peer": "alice", "X-Signature-256": "sha256=no"})
    assert bad.status_code == 401
    # valid signature → 200 pending, and it shows up in the admin inbox
    good = client.post("/api/a2a/task", content=body,
                       headers={"X-A2A-Peer": "alice", "X-Signature-256": _hmac(peer["secret"], body)})
    assert good.status_code == 200 and good.json()["status"] == "pending"
    inbox = client.get("/api/a2a/inbox", headers=hdr).json()["inbox"]
    assert len(inbox) == 1 and inbox[0]["status"] == "pending"
    # owner approves
    tid = inbox[0]["id"]
    dec = client.post(f"/api/a2a/inbox/{tid}/decide", json={"approve": True}, headers=hdr)
    assert dec.status_code == 200 and dec.json()["status"] == "approved"


def test_admin_peer_endpoints_require_token(monkeypatch, tmp_path):
    client, hdr = _client(monkeypatch, tmp_path)
    assert client.get("/api/a2a/peers").status_code == 401          # no admin token
    assert client.post("/api/a2a/peers", json={"peer_id": "bob"}, headers=hdr).status_code == 200
    assert client.get("/api/a2a/peers", headers=hdr).json()["peers"][0]["peer_id"] == "bob"
