"""H086 — Identity-scoped remote browser-control broker & one-shot HTTPS artifact store."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agents.core.browser_broker import (
     BrowserBrokerError,
    BrowserControlBroker,
    CallbackBrokerTransport,
)
from agents.core.routers import browser_broker as broker_router
from agents.core.routers._deps import admin_guard, user_guard


@pytest.mark.asyncio
async def test_h086_transport_agnostic_broker_identity_isolation_and_ssrf_guard():
    broker = BrowserControlBroker()

    # 1. Queue transport session owned by principal "alice".
    reg_alice = broker.register_controller(
        principal_id="alice",
        label="alice-remote-chromium",
        capabilities=["navigate", "snapshot"],
    )
    sid = reg_alice["session"]["session_id"]
    ctl_token = reg_alice["controller_token"]

    # Cross-identity caller "bob" cannot see or drive Alice's remote browser.
    assert broker.status(principal_id="bob")["sessions"] == []
    with pytest.raises(BrowserBrokerError) as exc_mismatch:
        await broker.dispatch_step(
            sid,
            principal_id="bob",
            step={"action": "navigate", "url": "https://example.com"},
        )
    assert exc_mismatch.value.reason == "identity_mismatch"
    assert exc_mismatch.value.status == 403

    # Unadvertised capability ("click") is refused even for Alice.
    with pytest.raises(BrowserBrokerError) as exc_cap:
        await broker.dispatch_step(sid, principal_id="alice", step={"action": "click", "selector": "#ok"})
    assert exc_cap.value.reason == "capability_not_granted"

    # SSRF targets (cloud metadata, private IP, file:// scheme) are blocked.
    for bad_url, expected_reason in [
        ("http://169.254.169.254/latest/meta-data/", "ssrf_blocked"),
        ("http://10.1.2.3/internal", "ssrf_blocked"),
        ("http://localhost:8080/admin", "ssrf_blocked"),
        ("file:///etc/passwd", "disallowed_url_scheme"),
    ]:
        with pytest.raises(BrowserBrokerError) as exc_ssrf:
            await broker.dispatch_step(sid, principal_id="alice", step={"action": "navigate", "url": bad_url})
        assert exc_ssrf.value.reason == expected_reason

    # Valid step queues for remote pickup; controller polls and posts completion.
    queued = await broker.dispatch_step(
        sid,
        principal_id="alice",
        step={"action": "navigate", "url": "https://example.com/docs"},
    )
    cmd_id = queued["command_id"]
    assert queued["status"] == "queued"

    with pytest.raises(BrowserBrokerError) as exc_tok:
        broker.poll_commands(sid, controller_token="wrong-token")
    assert exc_tok.value.reason == "invalid_controller_token"

    polled = broker.poll_commands(sid, controller_token=ctl_token)
    assert len(polled["commands"]) == 1
    assert polled["commands"][0]["command_id"] == cmd_id

    broker.submit_result(
        sid,
        cmd_id,
        controller_token=ctl_token,
        ok=True,
        output={"title": "Example Docs", "status": 200},
    )
    done = broker.get_command_status(cmd_id, principal_id="alice")
    assert done["status"] == "completed"
    assert done["output"]["title"] == "Example Docs"

    with pytest.raises(BrowserBrokerError) as exc_cmd_id:
        broker.get_command_status(cmd_id, principal_id="bob")
    assert exc_cmd_id.value.reason == "identity_mismatch"

    # 2. Callback/push transport adapter executes inline through the exact same dispatch_step API.
    seen_push = []
    push_transport = CallbackBrokerTransport(
        lambda s_id, payload: (seen_push.append((s_id, payload["step"]["action"])) or {"dom_nodes": 42}),
        name="websocket-bridge",
    )
    reg_bob = broker.register_controller(
        principal_id="bob",
        label="bob-ws-browser",
        transport=push_transport,
    )
    bob_sid = reg_bob["session"]["session_id"]
    immediate = await broker.dispatch_step(
        bob_sid, principal_id="bob", step={"action": "snapshot"}
    )
    assert immediate["status"] == "completed"
    assert immediate["output"]["dom_nodes"] == 42
    assert seen_push == [(bob_sid, "snapshot")]


def test_h086_one_shot_https_bounded_artifact_upload_and_download():
    # Strict HTTPS check (allow_loopback_http=False proves non-HTTPS rejection everywhere).
    broker = BrowserControlBroker(allow_loopback_http=False)
    reg = broker.register_controller(principal_id="owner", label="remote-cam")
    sid = reg["session"]["session_id"]

    up = broker.mint_upload_ticket(
        sid,
        principal_id="owner",
        filename="page.png",
        mime_type="image/png",
        max_bytes=1024,
    )
    aid = up["artifact_id"]
    up_ticket = up["upload_ticket"]
    payload = b"\x89PNG\r\n\x1a\nfake-screenshot-bytes"

    # Plain HTTP is refused with 403 https_required.
    with pytest.raises(BrowserBrokerError) as exc_http:
        broker.consume_upload(
            aid,
            upload_ticket=up_ticket,
            data=payload,
            content_type="image/png",
            scheme="http",
            client_host="203.0.113.10",
        )
    assert exc_http.value.reason == "https_required"
    assert exc_http.value.status == 403

    # Oversize upload is refused before burning the ticket? Wait: check oversize refusal!
    with pytest.raises(BrowserBrokerError) as exc_big:
        broker.consume_upload(
            aid,
            upload_ticket=up_ticket,
            data=b"x" * 2048,
            content_type="image/png",
            scheme="https",
        )
    assert exc_big.value.reason == "artifact_too_large"
    assert exc_big.value.status == 413

    # Valid HTTPS upload succeeds once.
    stored = broker.consume_upload(
        aid,
        upload_ticket=up_ticket,
        data=payload,
        content_type="image/png",
        scheme="https",
    )
    assert stored["ok"] is True
    assert stored["size_bytes"] == len(payload)

    # Replaying the one-shot upload ticket fails with 410 ticket_already_used.
    with pytest.raises(BrowserBrokerError) as exc_up_replay:
        broker.consume_upload(
            aid,
            upload_ticket=up_ticket,
            data=payload,
            content_type="image/png",
            scheme="https",
        )
    assert exc_up_replay.value.reason == "ticket_already_used"
    assert exc_up_replay.value.status == 410

    # Cross-identity caller cannot mint a download ticket.
    with pytest.raises(BrowserBrokerError) as exc_dl_id:
        broker.mint_download_ticket(aid, principal_id="intruder")
    assert exc_dl_id.value.reason == "identity_mismatch"

    dl = broker.mint_download_ticket(aid, principal_id="owner")
    dl_ticket = dl["download_ticket"]

    # Plain HTTP download is refused.
    with pytest.raises(BrowserBrokerError) as exc_dl_http:
        broker.consume_download(aid, download_ticket=dl_ticket, scheme="http", client_host="198.51.100.7")
    assert exc_dl_http.value.reason == "https_required"

    # Valid HTTPS download returns exact bytes once.
    fetched = broker.consume_download(aid, download_ticket=dl_ticket, scheme="https")
    assert fetched["data"] == payload
    assert fetched["sha256"] == stored["sha256"]

    # Replaying the one-shot download ticket fails with 410 ticket_already_used.
    with pytest.raises(BrowserBrokerError) as exc_dl_replay:
        broker.consume_download(aid, download_ticket=dl_ticket, scheme="https")
    assert exc_dl_replay.value.reason == "ticket_already_used"
    assert exc_dl_replay.value.status == 410


def test_h086_http_router_end_to_end_and_bearer_principal_isolation(monkeypatch):
    from agents import web

    broker = BrowserControlBroker()
    orch = SimpleNamespace(browser_broker=broker)
    monkeypatch.setattr(web, "orch", orch)

    app = FastAPI()
    app.include_router(broker_router.router)
    app.dependency_overrides[user_guard] = lambda: None
    app.dependency_overrides[admin_guard] = lambda: None
    client = TestClient(app)

    alice_hdr = {"Authorization": "Bearer secret-token-alice"}
    bob_hdr = {"Authorization": "Bearer secret-token-bob"}

    reg = client.post(
        "/api/browser/broker/sessions",
        json={"label": "alice-remote"},
        headers=alice_hdr,
    )
    assert reg.status_code == 200
    sid = reg.json()["session"]["session_id"]
    ctl_tok = reg.json()["controller_token"]

    # Bob's bearer scope sees zero sessions and gets 403 on Alice's session.
    assert client.get("/api/browser/broker", headers=bob_hdr).json()["sessions"] == []
    bob_step = client.post(
        f"/api/browser/broker/sessions/{sid}/steps",
        json={"step": {"action": "snapshot"}},
        headers=bob_hdr,
    )
    assert bob_step.status_code == 403
    assert bob_step.json()["error"] == "identity_mismatch"

    # Alice dispatches step; remote controller heartbeats, polls, and posts result.
    alice_step = client.post(
        f"/api/browser/broker/sessions/{sid}/steps",
        json={"step": {"action": "navigate", "url": "https://example.org"}},
        headers=alice_hdr,
    )
    assert alice_step.status_code == 200
    cmd_id = alice_step.json()["command_id"]

    ctl_hdr = {"X-Controller-Token": ctl_tok}
    assert client.post(f"/api/browser/broker/controller/{sid}/heartbeat", headers=ctl_hdr).status_code == 200
    polled = client.post(f"/api/browser/broker/controller/{sid}/poll", json={"limit": 5}, headers=ctl_hdr)
    assert polled.status_code == 200
    assert polled.json()["commands"][0]["command_id"] == cmd_id

    settled = client.post(
        f"/api/browser/broker/controller/{sid}/commands/{cmd_id}/result",
        json={"ok": True, "output": {"url": "https://example.org"}},
        headers=ctl_hdr,
    )
    assert settled.status_code == 200
    cmd_view = client.get(f"/api/browser/broker/commands/{cmd_id}", headers=alice_hdr)
    assert cmd_view.status_code == 200
    assert cmd_view.json()["status"] == "completed"

    # One-shot HTTPS upload & download over HTTP routes.
    up_t = client.post(
        f"/api/browser/broker/sessions/{sid}/artifacts/upload-ticket",
        json={"filename": "dom.json", "mime_type": "application/json", "max_bytes": 4096},
        headers=alice_hdr,
    ).json()
    aid = up_t["artifact_id"]

    raw_json = b'{"title":"Example"}'
    up_res = client.put(
        up_t["upload_path"],
        content=raw_json,
        headers={
            "X-Artifact-Ticket": up_t["upload_ticket"],
            "Content-Type": "application/json",
            "X-Forwarded-Proto": "https",
        },
    )
    assert up_res.status_code == 200

    # Second upload with same ticket -> 410.
    up_replay = client.put(
        up_t["upload_path"],
        content=raw_json,
        headers={
            "X-Artifact-Ticket": up_t["upload_ticket"],
            "Content-Type": "application/json",
            "X-Forwarded-Proto": "https",
        },
    )
    assert up_replay.status_code == 410

    # Bob cannot mint download ticket for Alice's artifact.
    assert (
        client.post(f"/api/browser/broker/artifacts/{aid}/download-ticket", json={}, headers=bob_hdr).status_code
        == 403
    )

    dl_t = client.post(
        f"/api/browser/broker/artifacts/{aid}/download-ticket",
        json={},
        headers=alice_hdr,
    ).json()
    dl_res = client.get(
        dl_t["download_path"],
        headers={"X-Artifact-Ticket": dl_t["download_ticket"], "X-Forwarded-Proto": "https"},
    )
    assert dl_res.status_code == 200
    assert dl_res.content == raw_json

    # Second download with same ticket -> 410.
    dl_replay = client.get(
        dl_t["download_path"],
        headers={"X-Artifact-Ticket": dl_t["download_ticket"], "X-Forwarded-Proto": "https"},
    )
    assert dl_replay.status_code == 410

    # Detach session.
    assert client.delete(f"/api/browser/broker/sessions/{sid}", headers=alice_hdr).status_code == 200
