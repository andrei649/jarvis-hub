"""`nerva rooms` — remote room members (H658) & surviving-host failover/fencing (H657).

Online verbs over the same admin routes the HUD's Remote Members and Rooms panels use.
A bundle carries a one-time invitation code, so `join` reads it from stdin, never from argv.
"""
from __future__ import annotations

import argparse
import json
from urllib.parse import quote

BASE = "/api/room-peers"
ROOMS_BASE = "/api/rooms"


def _tools(text: str) -> list[str]:
    return [t.strip() for t in str(text or "").split(",") if t.strip()]


def _read_json_input(raw_arg: str, ctx, label: str) -> dict:
    raw = (raw_arg or "").strip()
    if not raw:
        raw = ctx.inp.read().strip()
    if not raw:
        raise argparse.ArgumentTypeError(f"{label} JSON object required (--json or stdin)")
    try:
        parsed = json.loads(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{label} must be valid JSON") from None
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError(f"{label} must be a JSON object")
    return parsed


def register_parser(verbs):
    rooms = verbs.add_parser("rooms", help="remote room members and room failover/fencing (admin)")
    ops = rooms.add_subparsers(dest="operation", required=True)
    ops.add_parser("status", help="this hub's key fingerprint, invitations, members and links")
    invite = ops.add_parser("invite", help="invite a member into a room (an approval card on this hub)")
    invite.add_argument("room_id")
    invite.add_argument("member_id")
    invite.add_argument("--tools", required=True, help="comma-separated tools it may call")
    invite.add_argument("--url", required=True, help="this hub's address as the member hub reaches it")
    invite.add_argument("--status-only", action="store_true", help="it may read task status but not dispatch")
    invite.add_argument("--calls-per-hour", type=int, default=60)
    bundle = ops.add_parser("bundle", help="the one-time bundle of an approved invitation")
    bundle.add_argument("invite_id")
    policy = ops.add_parser("policy", help="change a member's tools (its grant must be re-issued)")
    policy.add_argument("membership_id")
    policy.add_argument("--tools", required=True)
    policy.add_argument("--calls-per-hour", type=int, default=60)
    revoke = ops.add_parser("revoke", help="revoke a member: refused from its next call")
    revoke.add_argument("membership_id")
    join = ops.add_parser("join", help="redeem a bundle read from stdin (on the member's hub)")
    join.add_argument("--label", default="")
    call = ops.add_parser("call", help="call a tool on the target hub through a link")
    call.add_argument("link_id")
    call.add_argument("tool")
    call.add_argument("--args", default="{}", help="JSON object of arguments")
    task = ops.add_parser("task", help="status of a task this member queued on the target hub")
    task.add_argument("link_id")
    task.add_argument("task_id", type=int)
    renew = ops.add_parser("renew", help="renew a link's grant")
    renew.add_argument("link_id")
    leave = ops.add_parser("leave", help="forget a link and its grant on this hub")
    leave.add_argument("link_id")

    # H657: room authority replication, failover promotion (epoch+1), and fencing demotion
    rep_state = ops.add_parser("replica-state", help="inspect authority epoch, role, cursor and lineage")
    rep_state.add_argument("room_id")
    log_page = ops.add_parser("log-page", help="export a verbatim hash-chained room log page")
    log_page.add_argument("room_id")
    log_page.add_argument("--after-seq", type=int, default=0)
    log_page.add_argument("--limit", type=int, default=100)
    replicate = ops.add_parser("replicate", help="ingest a verbatim room log page onto a replica")
    replicate.add_argument("room_id")
    replicate.add_argument("--json", dest="page_json", default="", help="log page JSON (or pass via stdin)")
    promote = ops.add_parser("promote", help="promote this replica to authority at epoch+1")
    promote.add_argument("room_id")
    promote.add_argument("--confirm", action="store_true", help="explicitly confirm authority claim")
    promote.add_argument("--host", default="", help="override host id recorded on the epoch claim")
    promote.add_argument("--reason", default="", help="lineage reason recorded on the claim")
    demote = ops.add_parser("demote", help="fence and demote an old host given a newer-epoch proof")
    demote.add_argument("room_id")
    demote.add_argument("--json", dest="proof_json", default="", help="fencing proof JSON (or pass via stdin)")
    return rooms


def run(ns: argparse.Namespace, ctx) -> int:
    op = ns.operation
    method, path, body = "GET", BASE, None
    if op == "invite":
        method, path = "POST", BASE + "/invitations"
        body = {
            "room_id": ns.room_id,
            "member_id": ns.member_id,
            "tools": _tools(ns.tools),
            "target_url": ns.url,
            "max_calls_per_hour": ns.calls_per_hour,
            "permissions": ["status"] if ns.status_only else ["dispatch", "status"],
        }
    elif op == "bundle":
        method, path, body = "POST", f"{BASE}/invitations/{quote(ns.invite_id, safe='')}/bundle", {}
    elif op == "policy":
        method, path = "POST", f"{BASE}/members/{quote(ns.membership_id, safe='')}/policy"
        body = {"tools": _tools(ns.tools), "max_calls_per_hour": ns.calls_per_hour}
    elif op == "revoke":
        method, path = "DELETE", f"{BASE}/members/{quote(ns.membership_id, safe='')}"
    elif op == "join":
        text = ctx.inp.readline().strip()
        if not text:
            raise argparse.ArgumentTypeError("bundle required on stdin")
        method, path, body = "POST", BASE + "/links", {"bundle": text, "label": ns.label}
    elif op in ("call", "task"):
        method, path = "POST", f"{BASE}/links/{quote(ns.link_id, safe='')}/call"
        if op == "call":
            try:
                args = json.loads(ns.args)
            except ValueError:
                raise argparse.ArgumentTypeError("--args must be a JSON object") from None
            if not isinstance(args, dict):
                raise argparse.ArgumentTypeError("--args must be a JSON object")
            body = {"op": "dispatch", "tool": ns.tool, "args": args}
        else:
            body = {"op": "status", "task_id": ns.task_id}
    elif op == "renew":
        method, path, body = "POST", f"{BASE}/links/{quote(ns.link_id, safe='')}/renew", {}
    elif op == "leave":
        method, path = "DELETE", f"{BASE}/links/{quote(ns.link_id, safe='')}"
    elif op == "replica-state":
        rid = quote(ns.room_id, safe="")
        method, path = "GET", f"{ROOMS_BASE}/{rid}/replica-state"
    elif op == "log-page":
        rid = quote(ns.room_id, safe="")
        method = "GET"
        path = f"{ROOMS_BASE}/{rid}/log-page?after_seq={max(0, int(ns.after_seq))}&limit={max(1, int(ns.limit))}"
    elif op == "replicate":
        rid = quote(ns.room_id, safe="")
        page = _read_json_input(ns.page_json, ctx, "log page")
        method, path, body = "POST", f"{ROOMS_BASE}/{rid}/replicate", {"page": page}
    elif op == "promote":
        rid = quote(ns.room_id, safe="")
        method, path = "POST", f"{ROOMS_BASE}/{rid}/promote"
        body = {"confirm": bool(ns.confirm), "new_host": ns.host, "reason": ns.reason}
    elif op == "demote":
        rid = quote(ns.room_id, safe="")
        proof = _read_json_input(ns.proof_json, ctx, "fencing proof")
        method, path, body = "POST", f"{ROOMS_BASE}/{rid}/demote", {"proof": proof}
    elif op != "status":
        raise argparse.ArgumentTypeError("unknown rooms operation")
    ctx.dump(ctx.client().request(method, path, body))
    return 0
