"""H658 — a room member on another machine, under a capability the target issued and can revoke.

Two hubs run in one process: each is its own FastAPI app with the real room-peers router
and its own :class:`RoomPeerService`; the member hub reaches the target hub over an
in-process HTTP transport (httpx's ASGI transport), so every request and response goes
through the real peer routes, their signatures and the grant scheme.
"""

from __future__ import annotations

import functools
import json
import secrets
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from agents.core import room_peers as rp
from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.kernel import authorize as kernel_authorize
from agents.core.room_peers import RoomPeerError, RoomPeerService
from agents.core.routers.room_peers import router as room_peers_router
from agents.core.security.capability import CapabilityBroker, KillSwitch
from agents.core.tool_rpc import ToolRPCServer

HUB_T = "a" * 32
HUB_M = "b" * 32
TARGET_URL = "http://127.0.0.1:8701"


class Clock:
    def __init__(self) -> None:
        self.t = 1_800_000_000.0

    def __call__(self) -> float:
        return self.t


class Audit:
    def __init__(self) -> None:
        self.rows = []

    def record(self, actor, action, why, metadata=None):
        self.rows.append({"actor": actor, "action": action, "why": why, "metadata": metadata or {}})

    def actions(self):
        return [r["action"] for r in self.rows]


class Rooms:
    def __init__(self) -> None:
        self.rooms = {"room1": {"id": "room1", "name": "Kitchen project"}}

    def get(self, room_id):
        return self.rooms.get(room_id)


class Queue:
    """Stands in for the governed intake: records every card, hands out ids."""

    def __init__(self) -> None:
        self.tasks = {}

    def enqueue(self, agent, kind, title, payload=None, risk_tier=2, autonomy_level="ask",
                origin="generated"):
        task_id = len(self.tasks) + 1
        self.tasks[task_id] = SimpleNamespace(id=task_id, agent=agent, kind=kind, title=title,
                                              payload=payload or {}, risk_tier=risk_tier,
                                              autonomy_level=autonomy_level, origin=origin,
                                              status="blocked", result=None)
        return task_id

    def get(self, task_id):
        return self.tasks.get(task_id)


class AsgiTransport:
    """The member hub's transport: real HTTP requests into the target hub's app."""

    def __init__(self, apps: dict) -> None:
        self.apps = apps
        self.sent = []

    async def post(self, url, headers, body):
        origin = url.split("/api/")[0]
        app = self.apps[origin]
        self.sent.append({"url": url, "headers": dict(headers), "body": body})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
            resp = await client.post(url[len(origin):], content=body, headers=headers)
        return resp.status_code, dict(resp.headers), resp.content


def _tools(calls):
    server = ToolRPCServer(agent="jarvis")

    async def room_read(args):
        calls.append(("room_read", dict(args)))
        return {"text": f"read {args.get('what', '')}"}

    async def room_write(args):
        calls.append(("room_write", dict(args)))
        return {"written": args.get("text", "")}

    async def local_shell(args):  # pragma: no cover - never reached remotely
        return {}

    server.register_tool("room_read", room_read, gated=False)
    server.register_tool("room_write", room_write, gated=True)
    server.register_tool("local_shell", local_shell, gated=True, trusted_execution=True)
    return server


def _hub(tmp_path, name, hub_id, clock, transport, *, kernel=True, enabled=True):
    calls, audit, queue = [], Audit(), Queue()
    broker = CapabilityBroker()
    kill = KillSwitch(tmp_path / f"{name}_kill.json")
    policy = AutonomyPolicy()
    tools = _tools(calls)
    bound = functools.partial(kernel_authorize, kill_switch=kill, capabilities=broker,
                              policy=policy, audit=audit) if kernel else None
    rooms = Rooms()
    flag = {"on": enabled}
    svc = RoomPeerService(
        state_path=tmp_path / f"{name}_state.json", key_path=tmp_path / f"{name}_keys.json",
        hub_id=hub_id, rooms=lambda: rooms, tool_rpc=lambda: tools, kernel=lambda: bound,
        capability_broker=broker, kill_switch=kill, enqueue=queue.enqueue, task_reader=queue.get,
        audit=audit, transport=transport, clock=clock, enabled=lambda: flag["on"])
    app = FastAPI()
    app.include_router(room_peers_router)
    app.state.room_peers = svc
    return SimpleNamespace(svc=svc, app=app, calls=calls, audit=audit, queue=queue, broker=broker,
                           kill=kill, policy=policy, rooms=rooms, tools=tools, flag=flag)


@pytest.fixture()
def pair(tmp_path):
    clock = Clock()
    apps = {}
    transport = AsgiTransport(apps)
    target = _hub(tmp_path, "t", HUB_T, clock, transport)
    member = _hub(tmp_path, "m", HUB_M, clock, transport)
    apps[TARGET_URL] = target.app
    return SimpleNamespace(t=target, m=member, clock=clock, transport=transport, tmp=tmp_path)


async def _approve_invite(t, invite):
    task = t.queue.get(invite["task_id"])
    assert task.kind == rp.INVITE_KIND and task.autonomy_level == "ask"
    assert (await t.svc.execute(task))["status"] == "ok"


async def _join(pair, tools=("room_read", "room_write"), member_id="ana", permissions=None):
    out = pair.t.svc.invite("room1", member_id, list(tools), target_url=TARGET_URL,
                            permissions=permissions)
    await _approve_invite(pair.t, out)
    bundle = pair.t.svc.issue_bundle(out["invitation"]["id"])["bundle"]
    link = await pair.m.svc.join(bundle, label="laptop")
    return out, link


# ── issue / accept ──────────────────────────────────────────────────────────

async def test_invitation_needs_owner_approval_card_before_a_bundle(pair):
    out = pair.t.svc.invite("room1", "ana", ["room_read"], target_url=TARGET_URL)
    task = pair.t.queue.get(out["task_id"])
    assert task.kind == "roompeer.invite" and task.autonomy_level == "ask" and task.risk_tier == 3
    assert "ana" in task.title and "room_read" in task.title
    with pytest.raises(RoomPeerError) as exc:
        pair.t.svc.issue_bundle(out["invitation"]["id"])
    assert exc.value.reason == "invitation_pending_approval"
    # an approval for different terms does not approve this invitation
    forged = SimpleNamespace(id=99, kind=rp.INVITE_KIND, payload={**task.payload, "terms": "0" * 64})
    assert (await pair.t.svc.execute(forged))["reason"] == "terms_changed"
    await _approve_invite(pair.t, out)
    assert pair.t.svc.issue_bundle(out["invitation"]["id"])["bundle"].startswith("nrb1.")


async def test_accept_pins_keys_and_issues_scoped_grant(pair):
    out, link = await _join(pair)
    assert link["status"] == "active" and link["target_hub"] == HUB_T
    t_status = pair.t.svc.status()
    (member,) = t_status["members"]
    assert member["member_hub"] == HUB_M and member["status"] == "active"
    assert member["principal"] == f"roommember:room1:ana@{HUB_M}"
    assert member["key_fingerprint"] == rp.fingerprint(pair.m.svc.public_key)
    # the grant itself is scoped to room, epoch, member and target, with the policy digest
    grant = pair.m.svc._keys.data["link_grants"][link["id"]]
    claims = json.loads(rp._b64d(grant.split(".")[1]))
    assert claims["room"] == "room1" and claims["member"] == "ana" and claims["target"] == HUB_T
    assert claims["epoch"] == t_status["epochs"]["room1"] and claims["pd"] == link["policy_digest"]
    assert claims["exp"] - claims["iat"] == pytest.approx(rp.DISPATCH_TTL)
    # credentials never appear in any serializer
    dumped = json.dumps(pair.m.svc.status()) + json.dumps(t_status)
    assert grant not in dumped and "code_key" not in dumped
    assert pair.m.svc._keys.data["identity"] not in dumped
    # the invitation is single use
    bundle_again = pair.t.svc.status()["invitations"][0]
    assert bundle_again["status"] == "accepted"
    assert "roompeer.accepted" in pair.t.audit.actions() and "roompeer.joined" in pair.m.audit.actions()


async def test_bundle_code_and_member_signature_both_required(pair):
    out = pair.t.svc.invite("room1", "ana", ["room_read"], target_url=TARGET_URL)
    await _approve_invite(pair.t, out)
    bundle = rp.decode_bundle(pair.t.svc.issue_bundle(out["invitation"]["id"])["bundle"])
    wrong = rp.encode_bundle({**bundle, "code": "x" * 32})
    with pytest.raises(RoomPeerError):
        await pair.m.svc.join(wrong)
    # a replaced code invalidates the earlier bundle
    first = rp.encode_bundle(bundle)
    pair.t.svc.issue_bundle(out["invitation"]["id"])
    with pytest.raises(RoomPeerError):
        await pair.m.svc.join(first)


async def test_bundle_with_a_substituted_target_key_is_refused(pair):
    out = pair.t.svc.invite("room1", "ana", ["room_read"], target_url=TARGET_URL)
    await _approve_invite(pair.t, out)
    bundle = rp.decode_bundle(pair.t.svc.issue_bundle(out["invitation"]["id"])["bundle"])
    # a man in the middle hands the member a key of its own: the target's signed answer
    # does not verify against it, so nothing is stored
    bogus = rp.encode_bundle({**bundle, "target_key": pair.m.svc.public_key})
    with pytest.raises(RoomPeerError) as exc:
        await pair.m.svc.join(bogus)
    assert exc.value.reason == "response_unverified"
    assert pair.m.svc.status()["links"] == []


async def test_trusted_execution_tool_is_never_offerable(pair):
    with pytest.raises(RoomPeerError) as exc:
        pair.t.svc.invite("room1", "ana", ["local_shell"], target_url=TARGET_URL)
    assert exc.value.reason == "tool_not_offerable"
    with pytest.raises(RoomPeerError):
        pair.t.svc.invite("room1", "ana", ["no_such_tool"], target_url=TARGET_URL)
    with pytest.raises(RoomPeerError):
        pair.t.svc.invite("nope", "ana", ["room_read"], target_url=TARGET_URL)


# ── remote actions run as the member principal under the target's kernel ──

async def test_read_only_tool_runs_inline_as_member_principal(pair):
    _out, link = await _join(pair)
    answer = await pair.m.svc.remote_call(link["id"], "room_read", {"what": "menu"})
    assert answer["ok"] is True and answer["result"]["text"] == "read menu"
    assert pair.t.calls == [("room_read", {"what": "menu"})]
    kernel_rows = [r for r in pair.t.audit.rows if r["actor"] == "kernel"]
    assert kernel_rows[-1]["action"] == "authorize:room.remote_call"
    assert kernel_rows[-1]["metadata"]["agent"] == f"roommember:room1:ana@{HUB_M}"
    assert kernel_rows[-1]["metadata"]["scope"] == "room:room1"
    # audited on both sides
    assert "roompeer.call" in pair.t.audit.actions()
    assert "roompeer.remote_call" in pair.m.audit.actions()


async def test_gated_tool_becomes_an_approval_card_and_runs_after_approval(pair):
    _out, link = await _join(pair)
    answer = await pair.m.svc.remote_call(link["id"], "room_write", {"text": "hello"})
    assert answer["reason"] == "approval_required" and answer["status_code"] == 202
    task = pair.t.queue.get(answer["task_id"])
    assert task.kind == "roompeer.call" and task.agent == f"roommember:room1:ana@{HUB_M}"
    assert task.agent != "jarvis" and task.autonomy_level == "ask"
    assert pair.t.calls == []
    # the member may read its own task's status
    status = await pair.m.svc.remote_call(link["id"], "", op="status", task_id=answer["task_id"])
    assert status["ok"] is True and status["status"] == "blocked"
    result = await pair.t.svc.execute(task)
    assert result["status"] == "ok" and result["result"] == {"written": "hello"}
    assert pair.t.calls == [("room_write", {"text": "hello"})]


async def test_status_of_another_principals_task_is_refused(pair):
    _out, link = await _join(pair)
    owner_task = pair.t.queue.enqueue("jarvis", "toolrpc.x", "owner's own")
    status = await pair.m.svc.remote_call(link["id"], "", op="status", task_id=owner_task)
    assert status["ok"] is False and status["reason"] == "unknown_task"


async def test_kernel_kill_switch_scope_and_owner_policy_apply(pair):
    _out, link = await _join(pair)
    pair.t.kill.engage("room:room1", "pause the room")
    answer = await pair.m.svc.remote_call(link["id"], "room_read", {})
    assert answer["reason"] == "kernel_denied" and "kill-switch" in answer["detail"]
    pair.t.kill.disengage("room:room1")
    # the owner can put this member's principal in ASK: even a read then queues
    pair.t.policy.agent_modes[f"roommember:room1:ana@{HUB_M}"] = "off"
    queued = await pair.m.svc.remote_call(link["id"], "room_read", {"what": "x"})
    assert queued["reason"] == "approval_required"
    assert pair.t.calls == []


async def test_tool_outside_the_grant_is_refused(pair):
    _out, link = await _join(pair, tools=("room_read",))
    answer = await pair.m.svc.remote_call(link["id"], "room_write", {"text": "x"})
    assert answer["reason"] == "tool_not_granted"
    assert pair.t.queue.tasks.keys() == {1}   # only the invitation card


async def test_target_without_a_kernel_refuses(tmp_path):
    clock = Clock()
    apps = {}
    transport = AsgiTransport(apps)
    target = _hub(tmp_path, "t", HUB_T, clock, transport, kernel=False)
    member = _hub(tmp_path, "m", HUB_M, clock, transport)
    apps[TARGET_URL] = target.app
    link = (await _join(SimpleNamespace(t=target, m=member)))[1]
    answer = await member.svc.remote_call(link["id"], "room_read", {})
    assert answer["reason"] == "kernel_unavailable" and target.calls == []


async def test_call_budget(pair):
    out = pair.t.svc.invite("room1", "ana", ["room_read"], target_url=TARGET_URL,
                            max_calls_per_hour=2)
    await _approve_invite(pair.t, out)
    link = await pair.m.svc.join(pair.t.svc.issue_bundle(out["invitation"]["id"])["bundle"])
    for _ in range(2):
        assert (await pair.m.svc.remote_call(link["id"], "room_read", {}))["ok"] is True
    answer = await pair.m.svc.remote_call(link["id"], "room_read", {})
    assert answer["reason"] == "call_budget_exhausted" and answer["status_code"] == 429
    pair.clock.t += 3_601
    assert (await pair.m.svc.remote_call(link["id"], "room_read", {}))["ok"] is True


# ── expiry, revocation, epoch, policy digest ────────────────────────────────

async def test_dispatch_expiry_renews_automatically_but_status_ttl_is_the_limit(pair):
    _out, link = await _join(pair)
    pair.clock.t += rp.DISPATCH_TTL + 5
    answer = await pair.m.svc.remote_call(link["id"], "room_read", {"what": "a"})
    assert answer["ok"] is True   # grant_expired → renewed → retried
    assert "roompeer.renewed" in pair.t.audit.actions()
    pair.clock.t += rp.STATUS_TTL + 5
    answer = await pair.m.svc.remote_call(link["id"], "room_read", {"what": "b"})
    assert answer["ok"] is False and answer["reason"] == "grant_expired"


async def test_renewed_grant_retires_the_old_one(pair):
    _out, link = await _join(pair)
    old = pair.m.svc._keys.data["link_grants"][link["id"]]
    assert (await pair.m.svc.renew(link["id"]))["ok"] is True
    pair.m.svc._keys.data["link_grants"][link["id"]] = old
    answer = await pair.m.svc.remote_call(link["id"], "room_read", {})
    assert answer["reason"] == "grant_revoked"


async def test_revocation_takes_effect_on_the_next_call(pair):
    _out, link = await _join(pair)
    assert (await pair.m.svc.remote_call(link["id"], "room_read", {}))["ok"] is True
    epoch_before = pair.t.svc.status()["epochs"]["room1"]
    pair.t.svc.revoke_member(link["membership_id"])
    assert pair.t.svc.status()["epochs"]["room1"] == epoch_before + 1
    answer = await pair.m.svc.remote_call(link["id"], "room_read", {})
    assert answer["reason"] == "membership_revoked"
    assert pair.m.svc.status()["links"][0]["status"] == "revoked"
    assert len(pair.t.calls) == 1
    # the broker token is gone too
    assert pair.t.broker.list() == []


async def test_approved_card_of_a_revoked_member_does_not_run(pair):
    _out, link = await _join(pair)
    answer = await pair.m.svc.remote_call(link["id"], "room_write", {"text": "x"})
    pair.t.svc.revoke_member(link["membership_id"])
    result = await pair.t.svc.execute(pair.t.queue.get(answer["task_id"]))
    assert result["status"] == "failed" and result["reason"] == "membership_revoked"
    assert pair.t.calls == []


async def test_epoch_bump_on_membership_change_needs_renewal(pair):
    _out, link_a = await _join(pair, member_id="ana")
    # a second member joining moves the room's epoch
    out_b = pair.t.svc.invite("room1", "bob", ["room_read"], target_url=TARGET_URL)
    await _approve_invite(pair.t, out_b)
    await pair.m.svc.join(pair.t.svc.issue_bundle(out_b["invitation"]["id"])["bundle"])
    grant = pair.m.svc._keys.data["link_grants"][link_a["id"]]
    claims = json.loads(rp._b64d(grant.split(".")[1]))
    assert claims["epoch"] < pair.t.svc.status()["epochs"]["room1"]
    answer = await pair.m.svc.remote_call(link_a["id"], "room_read", {"what": "e"})
    assert answer["ok"] is True   # room_epoch_stale → renewed at the current epoch
    assert pair.m.svc.status()["links"][0]["epoch"] == pair.t.svc.status()["epochs"]["room1"]


async def test_policy_digest_mismatch_refuses_renewal(pair):
    _out, link = await _join(pair)
    pair.t.svc.set_policy(link["membership_id"], ["room_read"])   # narrowed
    renewed = await pair.m.svc.renew(link["id"])
    assert renewed == {"ok": False, "reason": "room_reauthorization_required"}
    assert pair.m.svc.status()["links"][0]["status"] == "needs_invitation"


async def test_tool_gating_change_moves_the_digest(pair):
    _out, link = await _join(pair, tools=("room_read",))
    pair.t.tools._tools["room_read"]["gated"] = True
    answer = await pair.m.svc.remote_call(link["id"], "room_read", {})
    assert answer["reason"] == "room_reauthorization_required"


async def test_approved_card_after_policy_change_does_not_run(pair):
    _out, link = await _join(pair)
    answer = await pair.m.svc.remote_call(link["id"], "room_write", {"text": "x"})
    pair.t.svc.set_policy(link["membership_id"], ["room_read", "room_write"], max_calls_per_hour=5)
    result = await pair.t.svc.execute(pair.t.queue.get(answer["task_id"]))
    assert result["reason"] == "room_reauthorization_required" and pair.t.calls == []


# ── forged and replayed messages ────────────────────────────────────────────

async def _raw_post(pair, path, headers, body):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=pair.t.app),
                                 base_url=TARGET_URL) as client:
        return await client.post(path, content=body, headers=headers)


async def test_replayed_request_is_refused(pair):
    _out, link = await _join(pair)
    await pair.m.svc.remote_call(link["id"], "room_read", {"what": "once"})
    sent = pair.transport.sent[-1]
    resp = await _raw_post(pair, rp.PATH_CALL, sent["headers"], sent["body"])
    assert resp.status_code == 401 and resp.json() == {"error": "rejected"}
    assert pair.t.calls == [("room_read", {"what": "once"})]


async def test_forged_messages_are_refused(pair):
    _out, link = await _join(pair)
    grant = pair.m.svc._keys.data["link_grants"][link["id"]]
    body = rp._canonical({"v": 1, "op": "dispatch", "tool": "room_read", "args": {}})

    def headers(signer, grant_text, raw=body, ts=None):
        nonce = secrets.token_urlsafe(18)
        ts = ts or f"{pair.clock():.3f}"
        base = rp.signing_base("POST", rp.PATH_CALL, ts, nonce, raw, grant_text)
        return {"authorization": f"NervaRoom {grant_text}", rp.H_NONCE: nonce, rp.H_TS: ts,
                rp.H_SIG: rp._b64e(signer._private.sign(base)), "content-type": "application/json"}

    # 1) a stolen grant signed by another key (the target's own) is refused
    assert (await _raw_post(pair, rp.PATH_CALL, headers(pair.t.svc, grant), body)).status_code == 401
    # 2) a grant with edited claims (wider tools / another member) fails its MAC
    parts = grant.split(".")
    claims = json.loads(rp._b64d(parts[1]))
    claims["member"] = "mallory"
    forged = f"{parts[0]}.{rp._b64e(rp._canonical(claims))}.{parts[2]}"
    assert (await _raw_post(pair, rp.PATH_CALL, headers(pair.m.svc, forged), body)).status_code == 401
    # 3) a body changed after signing
    h = headers(pair.m.svc, grant)
    tampered = rp._canonical({"v": 1, "op": "dispatch", "tool": "room_write", "args": {}})
    assert (await _raw_post(pair, rp.PATH_CALL, h, tampered)).status_code == 401
    # 4) a stale timestamp
    old = f"{pair.clock() - 600:.3f}"
    assert (await _raw_post(pair, rp.PATH_CALL, headers(pair.m.svc, grant, ts=old), body)).status_code == 401
    # 5) the install's admin token scheme is not a room credential
    h = headers(pair.m.svc, grant)
    h["authorization"] = f"Bearer {grant}"
    assert (await _raw_post(pair, rp.PATH_CALL, h, body)).status_code == 401
    # 6) a valid request still works
    ok = await _raw_post(pair, rp.PATH_CALL, headers(pair.m.svc, grant), body)
    assert ok.status_code == 200 and ok.json()["ok"] is True
    assert pair.t.calls == [("room_read", {})]


async def test_forged_response_is_refused_by_the_member_host(pair):
    _out, link = await _join(pair)
    real_post = pair.transport.post

    async def tampering_post(url, headers, body):
        status, resp_headers, raw = await real_post(url, headers, body)
        return status, resp_headers, raw.replace(b"read ", b"evil ")

    pair.transport.post = tampering_post
    answer = await pair.m.svc.remote_call(link["id"], "room_read", {"what": "x"})
    assert answer["reason"] == "response_unverified"


async def test_peer_routes_are_404_while_off(pair):
    pair.t.flag["on"] = False
    resp = await _raw_post(pair, rp.PATH_CALL, {}, b"{}")
    assert resp.status_code == 404
    with pytest.raises(RoomPeerError):
        pair.t.svc.invite("room1", "ana", ["room_read"], target_url=TARGET_URL)


async def test_accept_replay_and_same_install_refused(pair):
    out = pair.t.svc.invite("room1", "ana", ["room_read"], target_url=TARGET_URL)
    await _approve_invite(pair.t, out)
    bundle = pair.t.svc.issue_bundle(out["invitation"]["id"])["bundle"]
    await pair.m.svc.join(bundle)
    accept = next(s for s in pair.transport.sent if s["url"].endswith(rp.PATH_ACCEPT))
    resp = await _raw_post(pair, rp.PATH_ACCEPT, accept["headers"], accept["body"])
    assert resp.status_code == 401
    assert len(pair.t.svc.status()["members"]) == 1
    with pytest.raises(RoomPeerError) as exc:
        await pair.t.svc.join(bundle)
    assert exc.value.reason == "same_install"


def test_state_files_are_owner_only_and_keys_survive_restart(pair):
    import os
    import stat

    for name in ("t_keys.json",):
        path = pair.tmp / name
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    again = RoomPeerService(state_path=pair.tmp / "t_state.json", key_path=pair.tmp / "t_keys.json",
                            hub_id=HUB_T, enabled=lambda: True)
    assert again.public_key == pair.t.svc.public_key


# ── owner CLI: `nerva rooms` ────────────────────────────────────────────────

class _CliClient:
    def __init__(self) -> None:
        self.calls = []

    def request(self, method, path, body=None, **_kw):
        self.calls.append((method, path, body))
        return {"ok": True}


def _nerva(argv, stdin=""):
    import io

    from agents.cli.nerva import Context, main

    client = _CliClient()
    ctx = Context(environ={}, out=io.StringIO(), err=io.StringIO(), inp=io.StringIO(stdin),
                  client_factory=lambda env: client)
    return main(argv, context=ctx), client.calls


def test_cli_invite_bundle_revoke_and_join():
    code, calls = _nerva(["rooms", "invite", "room1", "ana", "--tools", "room_read, room_write",
                          "--url", TARGET_URL])
    assert code == 0 and calls == [("POST", "/api/room-peers/invitations", {
        "room_id": "room1", "member_id": "ana", "tools": ["room_read", "room_write"],
        "target_url": TARGET_URL, "max_calls_per_hour": 60, "permissions": ["dispatch", "status"]})]
    assert _nerva(["rooms", "bundle", "inv1"])[1] == [("POST", "/api/room-peers/invitations/inv1/bundle", {})]
    assert _nerva(["rooms", "revoke", "m1"])[1] == [("DELETE", "/api/room-peers/members/m1", None)]
    assert _nerva(["rooms", "status"])[1] == [("GET", "/api/room-peers", None)]
    # the bundle carries a one-time code: read from stdin, never argv
    code, calls = _nerva(["rooms", "join", "--label", "laptop"], stdin="nrb1.abc\n")
    assert code == 0 and calls == [("POST", "/api/room-peers/links", {"bundle": "nrb1.abc", "label": "laptop"})]
    assert _nerva(["rooms", "join"], stdin="")[0] != 0
    code, calls = _nerva(["rooms", "call", "l1", "room_read", "--args", '{"what": "menu"}'])
    assert calls == [("POST", "/api/room-peers/links/l1/call",
                      {"op": "dispatch", "tool": "room_read", "args": {"what": "menu"}})]
    assert _nerva(["rooms", "task", "l1", "7"])[1] == [
        ("POST", "/api/room-peers/links/l1/call", {"op": "status", "task_id": 7})]
