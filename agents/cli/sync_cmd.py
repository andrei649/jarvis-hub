"""`nerva sync` — H040 end-to-end encrypted cross-device configuration & skills sync."""

from __future__ import annotations

import argparse
import json
from urllib.parse import quote

BASE = "/api/sync"


def register_parser(verbs):
    sync = verbs.add_parser("sync", help="E2E encrypted config & skills sync between your devices")
    ops = sync.add_subparsers(dest="operation", required=True)
    ops.add_parser("status", help="device label, encryption backend, skill policies, and peer hubs")

    push = ops.add_parser("push", help="collect config & enabled skills, encrypt, and ship")
    push.add_argument("--no-config", action="store_true", help="omit declared settings")
    push.add_argument("--no-skills", action="store_true", help="omit user skills")

    pull = ops.add_parser("pull", help="fetch encrypted manifests from peers/spool, decrypt, and apply")
    pull.add_argument("--manifest-json", default="", help="optional explicit encrypted manifest JSON")

    ops.add_parser("now", help="bidirectional sync pass (pull remote changes, then push local)")

    label = ops.add_parser("label", help="set human-readable label for this device")
    label.add_argument("device_label")

    skill = ops.add_parser("skill", help="enable or disable cross-device sync for one skill")
    skill.add_argument("skill_name")
    skill_group = skill.add_mutually_exclusive_group(required=True)
    skill_group.add_argument("--enable", action="store_true")
    skill_group.add_argument("--disable", action="store_true")

    p_add = ops.add_parser("peer-add", help="register an owner peer hub URL for ciphertext sync")
    p_add.add_argument("peer_id")
    p_add.add_argument("url")
    p_add.add_argument("--label", default="")

    p_rm = ops.add_parser("peer-rm", help="remove an owner peer hub from cross-device sync")
    p_rm.add_argument("peer_id")
    return sync


def run(ns: argparse.Namespace, ctx) -> int:
    op = ns.operation
    method, path, body = "GET", BASE, None
    if op == "push":
        method, path = "POST", f"{BASE}/push"
        body = {
            "sync_device_state": True,
            "include_config": not bool(ns.no_config),
            "include_skills": not bool(ns.no_skills),
        }
    elif op == "pull":
        method, path = "POST", f"{BASE}/pull"
        manifest = {}
        raw = (ns.manifest_json or "").strip()
        if raw:
            try:
                manifest = json.loads(raw)
            except ValueError:
                raise argparse.ArgumentTypeError("--manifest-json must be valid JSON") from None
            if not isinstance(manifest, dict):
                raise argparse.ArgumentTypeError("--manifest-json must be a JSON object")
        body = {"apply_device_state": True, "manifest": manifest}
    elif op == "now":
        method, path, body = "POST", f"{BASE}/now", {}
    elif op == "label":
        method, path, body = "PUT", f"{BASE}/device", {"label": ns.device_label}
    elif op == "skill":
        slug = quote(ns.skill_name, safe="")
        method, path, body = "PUT", f"{BASE}/skills/{slug}", {"enabled": bool(ns.enable)}
    elif op == "peer-add":
        method, path = "POST", f"{BASE}/peers"
        body = {"peer_id": ns.peer_id, "url": ns.url, "label": ns.label}
    elif op == "peer-rm":
        pid = quote(ns.peer_id, safe="")
        method, path = "DELETE", f"{BASE}/peers/{pid}"
    elif op != "status":
        raise argparse.ArgumentTypeError("unknown sync operation")

    ctx.dump(ctx.client().request(method, path, body))
    return 0
