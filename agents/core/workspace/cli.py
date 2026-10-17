"""Operator recovery commands: ``python -m agents.core.workspace <command>``.

``setup-code``                       print the first-run setup code
``reset-link --email E --base-url U`` print a fresh invite/reset link for a user
``promote --email E``                 make a user an admin (recovery when no admin can sign in)

The CLI loads the hub's ``.env`` files first, exactly as the hub does, so it sees the
same ``NERVA_WORKSPACE`` flag and the same data root — and it refuses to run while the
workspace is disabled. Link and promotion commands are audited with
``actor_email='cli'``: someone with shell access acted, and the trail says so.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from urllib.parse import urlsplit

from agents.core.env_provenance import load_hub_env
from agents.core.workspace import audit, auth, config, db, identity

CLI_ACTOR = "cli"
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_REFUSED = 2


def _fail(message: str, code: int = EXIT_FAILED) -> int:
    print(f"error: {message}", file=sys.stderr)
    return code


def _setup_code() -> int:
    conn = db.connect()
    try:
        if identity.ensure_org(conn) is not None:
            return _fail("the workspace is already set up; use reset-link or promote instead")
    finally:
        conn.close()
    print(config.setup_code())
    return EXIT_OK


def _valid_base_url(value: str) -> bool:
    parts = urlsplit(value)
    return parts.scheme in ("http", "https") and bool(parts.netloc) and not parts.query \
        and not parts.fragment


def _reset_link(email: str, base_url: str) -> int:
    if not _valid_base_url(base_url):
        return _fail("--base-url must be an http(s) URL such as https://nerva.example.com")
    conn = db.connect()
    try:
        with db.tx(conn):
            row = identity.get_user_by_email(conn, email)
            if row is None:
                return _fail(f"no user with email {email}")
            purpose = auth.invite_purpose_for(row["status"])
            if purpose is None:
                return _fail("the user is disabled; enable them first (or use promote)")
            token, expires_at = auth.issue_invite(conn, int(row["id"]), purpose=purpose,
                                                  created_by=None)
            audit.record(conn, actor=None, actor_email=CLI_ACTOR,
                         action="user.invite_issued" if purpose == "invite" else "auth.reset_link_issued",
                         target_type="user", target_id=int(row["id"]),
                         details={"purpose": purpose, "expires_at": expires_at})
    finally:
        conn.close()
    expires = datetime.fromtimestamp(expires_at, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
    print(auth.invite_url(base_url, token))
    print(f"{purpose} link for {email}, single use, valid until {expires}", file=sys.stderr)
    return EXIT_OK


def _promote(email: str) -> int:
    conn = db.connect()
    try:
        with db.tx(conn):
            row = identity.get_user_by_email(conn, email)
            if row is None:
                return _fail(f"no user with email {email}")
            if row["role"] == "admin" and row["status"] == "active":
                print(f"{email} is already an active admin")
                return EXIT_OK
            status = row["status"]
            if status == "disabled":
                status = "active" if row["password_hash"] else "invited"
            conn.execute("UPDATE users SET role = 'admin', status = ? WHERE id = ?",
                         (status, row["id"]))
            auth.revoke_user_sessions(conn, int(row["id"]))
            audit.record(conn, actor=None, actor_email=CLI_ACTOR, action="user.promoted",
                         target_type="user", target_id=int(row["id"]),
                         details={"from_role": row["role"], "from_status": row["status"],
                                  "to_status": status})
    finally:
        conn.close()
    hint = "" if status == "active" else " (no password yet: issue a link with reset-link)"
    print(f"{email} is now an admin{hint}")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    """The ``python -m agents.core.workspace`` argument parser."""
    parser = argparse.ArgumentParser(prog="python -m agents.core.workspace",
                                     description="Nerva Workspace operator commands")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("setup-code", help="print the first-run setup code")
    reset = commands.add_parser("reset-link", help="print a fresh invite or password-reset link")
    reset.add_argument("--email", required=True)
    reset.add_argument("--base-url", required=True,
                       help="the address users open, e.g. https://nerva.example.com")
    promote = commands.add_parser("promote", help="make a user an admin")
    promote.add_argument("--email", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command; returns the process exit code."""
    args = build_parser().parse_args(argv)
    load_hub_env()
    if not config.enabled():
        return _fail("Nerva Workspace is disabled (set NERVA_WORKSPACE=1 first)", EXIT_REFUSED)
    if args.command == "setup-code":
        return _setup_code()
    email = args.email.strip().lower()
    if args.command == "reset-link":
        return _reset_link(email, args.base_url.strip())
    return _promote(email)
