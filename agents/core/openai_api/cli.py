"""Issue, list and revoke the keys of the OpenAI-compatible API, on the box.

    python -m agents.core.openai_api keys issue NAME [--owner]
    python -m agents.core.openai_api keys list
    python -m agents.core.openai_api keys revoke KEY_ID

A key is printed once, when it is issued; only its hash is kept. ``--owner`` makes the key
speak as the owner (trusted, like the HUD); without it, every turn the key starts is inbound
and each mutating action it proposes waits for the owner's approval. Under the managed-mode
marker (G1) issuing and revoking are refused like every other configuration write.
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import TextIO

from agents.core.openai_api import policy
from agents.core.openai_api.store import get_store


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m agents.core.openai_api",
                                     description="Keys of Nerva's OpenAI-compatible API.")
    groups = parser.add_subparsers(dest="group", required=True)
    keys = groups.add_parser("keys", help="issue, list or revoke API keys")
    verbs = keys.add_subparsers(dest="verb", required=True)
    issue = verbs.add_parser("issue", help="issue a key (printed once)")
    issue.add_argument("name", help="what the key is for, e.g. 'open-webui on the laptop'")
    issue.add_argument("--owner", action="store_true",
                       help="the key speaks as the owner (trusted); default: a guest whose actions need approval")
    verbs.add_parser("list", help="list keys (never the keys themselves)")
    revoke = verbs.add_parser("revoke", help="revoke a key at once")
    revoke.add_argument("key_id")
    return parser


def main(argv: Sequence[str] | None = None, *, out: TextIO | None = None, err: TextIO | None = None) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    args = _parser().parse_args(argv)
    store = get_store()
    if args.verb in ("issue", "revoke"):
        from agents.core import managed_scope

        try:
            managed_scope.check_writable()
        except managed_scope.ManagedRefused as exc:
            print(str(exc), file=err)
            return 1
    if args.verb == "issue":
        try:
            key, record = store.issue(args.name, owner=args.owner)
        except ValueError as exc:
            print(str(exc), file=err)
            return 1
        print(f"id:    {record.key_id}", file=out)
        print(f"name:  {record.name}", file=out)
        print(f"speaks as: {'the owner (trusted)' if record.owner else 'a guest (actions need your approval)'}",
              file=out)
        print(f"key:   {key}", file=out)
        print("Copy the key now: it is not shown again.", file=out)
        if not policy.enabled():
            print("The API is still off: turn on openai_api.enabled in Settings.", file=out)
        return 0
    if args.verb == "list":
        rows = store.list_keys()
        if not rows:
            print("no keys", file=out)
        for row in rows:
            state = "revoked" if row.revoked_at else "live"
            role = "owner" if row.owner else "guest"
            print(f"{row.key_id}  {state:7}  {role:5}  {row.name}", file=out)
        return 0
    if store.revoke(args.key_id):
        print(f"revoked {args.key_id}", file=out)
        return 0
    print(f"no live key {args.key_id}", file=err)
    return 1
