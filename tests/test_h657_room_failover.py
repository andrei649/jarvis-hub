"""H657 — Surviving-host room replica ingestion, epoch+1 promotion, and fencing demotion."""

from __future__ import annotations

import copy
import json
import sys
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agents.cli.nerva import Context, main
from agents.core.rooms import RoomAuthorityError, RoomStore
from agents.core.routers import rooms as rooms_router


def test_h657_full_two_host_failover_promotion_and_old_owner_fencing(tmp_path):
    """Primary Host A replicates verbatim log pages to Standby Host B; Host A dies;
    Host B promotes at epoch+1; Host A returns and is fenced."""
    secret = "shared-cluster-fencing-secret"
    host_a = RoomStore(tmp_path / "host_a_rooms.json", host_id="host-alpha", signing_secret=secret)
    host_b = RoomStore(tmp_path / "host_b_rooms.json", host_id="host-beta", signing_secret=secret)

    created = host_a.create("ops-war-room", description="incident channel", agents=["jarvis", "sec"])
    room_id = created["id"]
    assert created["authority_epoch"] == 1
    assert created["authority_role"] == "owner"
    assert created["authority_host"] == "host-alpha"

    m1 = host_a.add_message(room_id, "user", "status check @sec")
    m2 = host_a.add_message(room_id, "assistant", "all green", agent="sec")
    assert m1["seq"] == 1 and m1["epoch"] == 1
    assert m2["seq"] == 2 and m2["epoch"] == 1

    page1 = host_a.export_log_page(room_id, after_seq=0, limit=50)
    assert page1 is not None
    assert len(page1["entries"]) == 2

    # Standby Host B ingests the verbatim log page.
    rep1 = host_b.replicate(room_id, page1)
    assert rep1["ok"] is True
    assert rep1["created_replica"] is True
    assert rep1["applied"] == 2
    assert rep1["skipped_duplicates"] == 0
    assert rep1["authority_role"] == "replica"
    assert rep1["authority_epoch"] == 1

    # Re-ingesting the identical page is strictly idempotent.
    rep_dup = host_b.replicate(room_id, page1)
    assert rep_dup["applied"] == 0
    assert rep_dup["skipped_duplicates"] == 2
    assert len(host_b.history(room_id)) == 2

    # Unpromoted standby replica refuses direct message writes.
    with pytest.raises(RoomAuthorityError) as exc_unpromoted:
        host_b.add_message(room_id, "user", "illegal write before promote")
    assert exc_unpromoted.value.reason == "room_not_authority"

    # Promotion requires explicit confirm=True.
    with pytest.raises(RoomAuthorityError) as exc_confirm:
        host_b.promote(room_id, confirm=False)
    assert exc_confirm.value.reason == "confirm_required"

    # Host A dies; Host B promotes at epoch + 1 and records authority_claimed lineage.
    promoted = host_b.promote(room_id, confirm=True, reason="host-alpha heartbeat lost")
    assert promoted is not None
    assert promoted["authority_epoch"] == 2
    assert promoted["prev_epoch"] == 1
    assert promoted["authority_role"] == "owner"
    assert promoted["authority_host"] == "host-beta"
    assert promoted["lineage_event"]["event"] == "authority_claimed"

    # Host B now serves live room turns at epoch 2.
    m3 = host_b.add_message(room_id, "user", "continuing on surviving host-beta")
    assert m3["seq"] == 4  # seq 3 is the authority_claimed lineage event
    assert m3["epoch"] == 2

    # Old Host A comes back: any stale epoch-1 page from Host A is rejected by Host B.
    host_a.add_message(room_id, "user", "split-brain attempt on host-alpha")
    stale_page = host_a.export_log_page(room_id, after_seq=2)
    with pytest.raises(RoomAuthorityError) as exc_reg:
        host_b.replicate(room_id, stale_page)
    assert exc_reg.value.reason == "epoch_regression"

    # Host A receives Host B's fencing proof and demotes to fenced.
    demoted = host_a.demote(room_id, proof=promoted["fencing_proof"])
    assert demoted is not None
    assert demoted["authority_role"] == "fenced"
    assert demoted["authority_epoch"] == 2
    assert demoted["authority_host"] == "host-beta"

    # Fenced Host A refuses any further room writes.
    with pytest.raises(RoomAuthorityError) as exc_fenced:
        host_a.add_message(room_id, "user", "post-fence write")
    assert exc_fenced.value.reason == "room_fenced"

    state_a = host_a.replica_state(room_id)
    assert state_a["authority_role"] == "fenced"
    assert state_a["fenced_by"]["host"] == "host-beta"
    assert state_a["fenced_by"]["epoch"] == 2


def test_h657_replicate_refuses_sequence_gaps_divergence_and_forged_proofs(tmp_path):
    primary = RoomStore(tmp_path / "p.json", host_id="primary", signing_secret="key-1")
    replica = RoomStore(tmp_path / "r.json", host_id="replica", signing_secret="key-1")

    room = primary.create("design")
    rid = room["id"]
    primary.add_message(rid, "user", "turn 1")
    primary.add_message(rid, "assistant", "turn 2", agent="jarvis")
    primary.add_message(rid, "user", "turn 3")

    # Sequence gap: skipping seq=1..2 and sending only seq=3 must fail.
    gap_page = primary.export_log_page(rid, after_seq=2)
    with pytest.raises(RoomAuthorityError) as exc_gap:
        replica.replicate(rid, gap_page)
    assert exc_gap.value.reason == "sequence_gap"

    # Tampered text on seq=1 must fail digest verification.
    tampered_page = copy.deepcopy(primary.export_log_page(rid, after_seq=0))
    tampered_page["entries"][0]["text"] = "forged turn 1"
    with pytest.raises(RoomAuthorityError) as exc_div:
        replica.replicate(rid, tampered_page)
    assert exc_div.value.reason == "log_divergence"

    # Valid full page succeeds.
    valid_page = primary.export_log_page(rid, after_seq=0)
    assert replica.replicate(rid, valid_page)["applied"] == 3

    # Forged HMAC signature on fencing proof is rejected with 403 invalid_proof.
    promoted = replica.promote(rid, confirm=True)
    bad_proof = copy.deepcopy(promoted["fencing_proof"])
    bad_proof["signature"] = "0" * 64
    with pytest.raises(RoomAuthorityError) as exc_sig:
        primary.demote(rid, proof=bad_proof)
    assert exc_sig.value.reason == "invalid_proof"
    assert exc_sig.value.status == 403

    # Demoting with an older/equal epoch is rejected.
    assert primary.demote(rid, proof=promoted["fencing_proof"])["authority_role"] == "fenced"
    with pytest.raises(RoomAuthorityError) as exc_not_newer:
        primary.demote(rid, proof=promoted["fencing_proof"])
    assert exc_not_newer.value.reason == "not_newer_epoch"


def test_h657_http_router_and_cli_round_trip(tmp_path, monkeypatch):
    primary_store = RoomStore(tmp_path / "http_primary.json", host_id="hub-1")
    replica_store = RoomStore(tmp_path / "http_replica.json", host_id="hub-2")

    async def _fake_handle_input(prompt: str, channel: str = "room", agent_override=None):
        return f"ack:{agent_override or 'jarvis'}"

    from agents import web
    from agents.core.routers._deps import admin_guard, user_guard

    orch = SimpleNamespace(rooms=primary_store, agents={"jarvis": object()}, handle_input=_fake_handle_input)
    monkeypatch.setattr(web, "orch", orch)

    app = FastAPI()
    app.include_router(rooms_router.router)
    app.dependency_overrides[user_guard] = lambda: None
    app.dependency_overrides[admin_guard] = lambda: None
    client = TestClient(app)

    created = client.post("/api/rooms", json={"name": "ops"}).json()["room"]
    rid = created["id"]
    msg_res = client.post(f"/api/rooms/{rid}/message", json={"message": "hello room"})
    assert msg_res.status_code == 200

    page_res = client.get(f"/api/rooms/{rid}/log-page?after_seq=0&limit=20")
    assert page_res.status_code == 200
    page = page_res.json()
    assert len(page["entries"]) == 2

    # Switch app to standby replica hub-2 and test HTTP replicate + promote.
    orch.rooms = replica_store
    rep_res = client.post(f"/api/rooms/{rid}/replicate", json={"page": page})
    assert rep_res.status_code == 200
    assert rep_res.json()["applied"] == 2

    blocked_msg = client.post(f"/api/rooms/{rid}/message", json={"message": "before promote"})
    assert blocked_msg.status_code == 409
    assert blocked_msg.json()["error"] == "room_not_authority"

    no_confirm = client.post(f"/api/rooms/{rid}/promote", json={"confirm": False})
    assert no_confirm.status_code == 409
    assert no_confirm.json()["error"] == "confirm_required"

    prom_res = client.post(f"/api/rooms/{rid}/promote", json={"confirm": True, "reason": "failover"})
    assert prom_res.status_code == 200
    proof = prom_res.json()["fencing_proof"]

    # Switch back to hub-1 and fence via HTTP demote.
    orch.rooms = primary_store
    dem_res = client.post(f"/api/rooms/{rid}/demote", json={"proof": proof})
    assert dem_res.status_code == 200
    assert dem_res.json()["authority_role"] == "fenced"

    fenced_msg = client.post(f"/api/rooms/{rid}/message", json={"message": "after fence"})
    assert fenced_msg.status_code == 409
    assert fenced_msg.json()["error"] == "room_fenced"

    state_res = client.get(f"/api/rooms/{rid}/replica-state")
    assert state_res.status_code == 200
    assert state_res.json()["authority_role"] == "fenced"

    # Verify CLI dispatch shapes for all 5 H657 subcommands.
    calls = []

    class _RecordingClient:
        def request(self, method, path, body=None):
            calls.append((method, path, body))
            return {"ok": True}

    import io

    for argv, stdin_text in [
        (["rooms", "replica-state", rid], ""),
        (["rooms", "log-page", rid, "--after-seq", "2", "--limit", "25"], ""),
        (["rooms", "replicate", rid], json.dumps(page)),
        (["rooms", "promote", rid, "--confirm", "--host", "hub-2", "--reason", "drill"], ""),
        (["rooms", "demote", rid], json.dumps(proof)),
    ]:
        ctx = Context(
            environ={},
            out=io.StringIO(),
            err=io.StringIO(),
            inp=io.StringIO(stdin_text),
            client_factory=lambda _env: _RecordingClient(),
        )
        assert main(argv, context=ctx) == 0

    assert [c[1] for c in calls] == [
        f"/api/rooms/{rid}/replica-state",
        f"/api/rooms/{rid}/log-page?after_seq=2&limit=25",
        f"/api/rooms/{rid}/replicate",
        f"/api/rooms/{rid}/promote",
        f"/api/rooms/{rid}/demote",
    ]
