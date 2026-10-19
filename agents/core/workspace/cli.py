"""Operator recovery commands: ``nerva-run -m agents.core.workspace <command>``.

``nerva-run`` (PILOT_GUIDE §2) is ``python -m`` with the service's environment; every hint
these commands and the workspace's log lines print names that form.

``setup-code``                       print the first-run setup code
``reset-link --email E --base-url U`` print a fresh invite/reset link for a user
``promote --email E``                 make a user an admin (recovery when no admin can sign in)
``check``                             read-only readiness report: data root, database, schema
                                     version, audit key ``ok``/``missing``/``unreadable``/``mismatch``
``audit-rekey [--confirm]``           replace an audit key that is truly lost (audited; the rows
                                     the old key signed can never be verified again)

The CLI loads the hub's ``.env`` files first, exactly as the hub does, so it sees the
same ``NERVA_WORKSPACE`` flag and the same data root — and it refuses to run while the
workspace is disabled. Link and promotion commands are audited with
``actor_email='cli'``: someone with shell access acted, and the trail says so.

It also refuses (exit 2), before it opens or creates anything, when it can tell it does
not run with the service's environment (PILOT_GUIDE §2 ``nerva-run``): a data root that
nobody chose (no ``JARVIS_HOME``) inside the code checkout, a workspace database that does
not exist (``reset-link``/``promote``), or an audit key that is not the one the trail was
written with — a row signed with another key would break the audit chain for good.
``check`` never refuses: it reports those same conditions (exit 1 when one is not right)
and writes nothing — it opens the database read-only and never creates a key or a file.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from urllib.parse import urlsplit

from agents.core import paths
from agents.core.env_config import env_str
from agents.core.env_provenance import load_hub_env
from agents.core.workspace import audit, auth, config, db, identity

CLI_ACTOR = "cli"
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_REFUSED = 2

#: Where the commands must run from (PILOT_GUIDE §2): the service's own environment.
SERVICE_ENV_HINT = ("run the command with the service's environment (PILOT_GUIDE §2: "
                    "nerva-run -m agents.core.workspace …), not from a bare shell")
_EXPLICIT_ROOT_ENV = ("JARVIS_HOME", "JARVIS_MEMORY_DIR")
_KEY_PROBLEMS = {
    "missing": "this environment has no audit key for this workspace (JARVIS_AUDIT_KEY is "
               "unset and {path} does not exist)",
    "unreadable": "the audit key at {path} cannot be read",
    "mismatch": "the audit key differs from the one this workspace was written with (see "
                "`check`; restore the service's key — only a key that is truly lost is "
                "replaced, with `audit-rekey`)",
}
#: What ``check`` prints after a key that is not ``ok``.
_KEY_REMEDY = ("  → restore the service's environment file (JARVIS_AUDIT_KEY) and JARVIS_KEY_DIR "
               "exactly as the service had them; until then the hub refuses every sign-in and "
               "every change (503). Only for a key that is truly lost: audit-rekey (PILOT_GUIDE "
               "§16).")


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


_BASE_URL_HELP = ("--base-url is the hub's address (scheme and host, plus the root path when "
                  "the hub is served under one), e.g. https://nerva.example.com — "
                  "not the /workspace/ page")


def normalized_base_url(value: str) -> str | None:
    """The hub's base URL for :func:`auth.invite_url`, or ``None`` when *value* is not one.

    The address people open (``https://nerva.example.com/workspace/``) is accepted too:
    a trailing ``/workspace`` is the app, not part of the base, so it is dropped —
    otherwise the link would read ``…/workspace/workspace/invite`` and land on the sign-in
    page while the person's previous link was already revoked. Any other path below
    ``/workspace`` is refused; a path above it is a root path and is kept.
    """
    parts = urlsplit(value.strip())
    if (parts.scheme not in ("http", "https") or not parts.netloc or parts.query
            or parts.fragment):
        return None
    path = parts.path.rstrip("/")
    if path == "/workspace" or path.endswith("/workspace"):
        path = path[: -len("/workspace")]
    if "/workspace/" in f"{path}/":
        return None
    return f"{parts.scheme}://{parts.netloc}{path}"


def _reset_link(email: str, base_url: str) -> int:
    base = normalized_base_url(base_url)
    if base is None:
        return _fail(_BASE_URL_HELP)
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
    print(auth.invite_url(base, token))
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


#: The name ``--help`` and usage lines show: the form the pilot guide runs (§2, ``nerva-run``
#: with the service's environment), not a bare ``python -m`` that would miss it.
PROG = "nerva-run -m agents.core.workspace"


def build_parser() -> argparse.ArgumentParser:
    """The operator commands' argument parser (shown as :data:`PROG`)."""
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Nerva Workspace operator commands. Run them with the service's "
                    "environment (PILOT_GUIDE §2: nerva-run), never from a bare shell.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("setup-code", help="print the first-run setup code")
    reset = commands.add_parser("reset-link", help="print a fresh invite or password-reset link")
    reset.add_argument("--email", required=True)
    reset.add_argument("--base-url", required=True,
                       help="the hub's address without /workspace, e.g. "
                            "https://nerva.example.com")
    promote = commands.add_parser("promote", help="make a user an admin")
    promote.add_argument("--email", required=True)
    commands.add_parser("check", help="read-only: is this environment the service's? (data "
                                      "root, database, schema, audit key)")
    rekey = commands.add_parser("audit-rekey",
                                help="replace an audit key that is truly lost (audited)")
    rekey.add_argument("--confirm", action="store_true",
                       help="write the re-key; without it the command only shows what it would do")
    return parser


def _unchosen_data_root() -> str | None:
    """The data root, when nobody chose it and it sits inside the code checkout.

    The service always names its data root (``JARVIS_HOME`` in the systemd environment).
    A shell without it falls back to ``<checkout>/memory_logs``, and a command run there
    would create a second, empty workspace the hub never reads.
    """
    if any(env_str(name, "").strip() for name in _EXPLICIT_ROOT_ENV):
        return None
    root = paths.data_root().resolve()
    try:
        root.relative_to(paths.app_root().resolve())
    except ValueError:
        return None
    return str(root)


def _preflight(command: str) -> int | None:
    """Exit code of a refusal (with its message printed), or ``None`` to go ahead."""
    try:
        unchosen = _unchosen_data_root()
    except RuntimeError as exc:  # a refused JARVIS_PROFILE: the hub does not start either
        return _fail(str(exc), EXIT_REFUSED)
    if unchosen is not None:
        return _fail(f"JARVIS_HOME is not set, so the data root would be {unchosen} inside the "
                     f"code checkout, which the service does not use — {SERVICE_ENV_HINT}",
                     EXIT_REFUSED)
    database = paths.data_path(config.DATA_DIRNAME, db.DB_FILE)
    if not database.exists():
        if command == "setup-code":
            return None  # a fresh install: the code is generated where the hub will read it
        return _fail(f"no Nerva Workspace database at {database} — {SERVICE_ENV_HINT}",
                     EXIT_REFUSED)
    conn = db.connect()
    try:
        problem = audit.key_check(conn)
    finally:
        conn.close()
    if problem == "mismatch" and command == "audit-rekey":
        return None   # the one command whose job a mismatched key is
    if problem != "ok":
        detail = _KEY_PROBLEMS[problem].format(path=audit.key_path())
        return _fail(f"{detail}; nothing was changed — {SERVICE_ENV_HINT}", EXIT_REFUSED)
    return None


# ── check: a read-only readiness report (PILOT_GUIDE §14 restore, §15 upgrade) ────────

def _schema_line(version: int) -> tuple[str, bool]:
    target = db.schema_version()
    if version == target:
        return f"schema {version}, current", True
    if version < target:
        return f"schema {version}; this code migrates it to {target} at the first start", True
    return (f"schema {version}, newer than this code's {target} — run the code it was written "
            f"with (PILOT_GUIDE §15)"), False


def _key_line(state: str, trail_fp: str | None) -> tuple[str, bool]:
    """The ``audit key:`` line for :func:`audit.key_check`'s *state*, and whether it is ok."""
    path = audit.key_path()
    if state == "missing":
        return (f"audit key: missing — {audit.ENV_AUDIT_KEY} is not set and {path} does not "
                f"exist, but the audit trail has rows"), False
    try:
        key = None if state == "unreadable" else audit.existing_key()
    except (OSError, RuntimeError):   # an empty trail does not read the key: do it here
        state = "unreadable"
    if state == "unreadable":
        return f"audit key: unreadable — {path} is empty or cannot be read", False
    if key is None:   # ok with an empty trail and no key yet
        return f"audit key: ok — no audit rows yet; the first start creates {path}", True
    fingerprint = audit.key_fingerprint(key)
    if state == "mismatch":
        return (f"audit key: mismatch — {audit.key_source()} has fingerprint {fingerprint}, but "
                f"the newest audit row was signed with {trail_fp}"), False
    return f"audit key: ok — {audit.key_source()}, fingerprint {fingerprint}", True


def _check() -> int:
    """Print whether this environment is the service's; exit 0 only when every line is ok.

    Opens the database read-only (no migration, no write) and never creates the data
    directory, the database or an audit key.
    """
    ok = config.enabled()
    print(f"workspace: {'on' if ok else 'off (NERVA_WORKSPACE is not on)'}")
    try:
        root = paths.data_root()
        unchosen = _unchosen_data_root()
    except RuntimeError as exc:   # a refused JARVIS_PROFILE: the hub does not start either
        print(f"data root: refused — {exc}")
        return EXIT_FAILED
    if unchosen is not None:
        print(f"data root: {root} — JARVIS_HOME is not set and this is inside the code "
              f"checkout, which the service does not use")
        ok = False
    else:
        print(f"data root: {root}")
    database = db.existing_db_path()
    state, rows, trail_fp = "ok", 0, None
    if not database.exists():
        print(f"database: not created yet ({database}; the first start creates it)")
    else:
        conn = db.connect_read_only(database)
        try:
            schema, schema_ok = _schema_line(int(conn.execute("PRAGMA user_version").fetchone()[0]))
            print(f"database: {database} ({schema})")
            ok = ok and schema_ok
            has_audit = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' "
                                     "AND name = 'audit'").fetchone() is not None
            if has_audit:
                state = audit.key_check(conn)
                rows = int(conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0])
                newest = conn.execute("SELECT key_fp FROM audit ORDER BY id DESC LIMIT 1").fetchone()
                trail_fp = newest["key_fp"] if newest is not None else None
        except sqlite3.DatabaseError as exc:
            print(f"database: {database} cannot be read ({exc})")
            return EXIT_FAILED
        finally:
            conn.close()
    key_text, key_ok = _key_line(state, trail_fp)
    print(key_text)
    if not key_ok:
        print(_KEY_REMEDY)
        ok = False
    if rows:
        print(f"audit trail: {rows} rows, the newest signed with key {trail_fp}")
    print("ready" if ok else "NOT ready — fix the lines above before starting the service")
    return EXIT_OK if ok else EXIT_FAILED


# ── audit-rekey: replace a key that is truly lost, on the record ──────────────────────

def _audit_rekey(confirm: bool) -> int:
    conn = db.connect()
    try:
        plan = audit.rekey_plan(conn)
        if plan["state"] == "ok":
            print("the audit key already matches the audit trail; nothing to do")
            return EXIT_OK
        if plan["broken_at"] is not None:
            return _fail(f"the audit trail is broken at row {plan['broken_at']} for another "
                         f"reason than the key; a re-key cannot repair that — restore a backup "
                         f"(PILOT_GUIDE §14). Nothing was changed.")
        print(f"key in use: {audit.key_source()}, fingerprint {plan['to_key_fp']}")
        print(f"newest audit row signed with: {plan['from_key_fp']}")
        print(f"{plan['unverified']} of the {plan['rows']} audit rows were signed with another "
              f"key; after a re-key they can never be verified again (they stay pinned: a later "
              f"edit or deletion of them is still detected)")
        if not confirm:
            return _fail("nothing was changed. A re-key is only for an audit key that is truly "
                         "lost: if the service's key still exists anywhere, restore it instead. "
                         "To re-key, run the command again with --confirm.", EXIT_REFUSED)
        try:
            row_id = audit.rekey(conn, actor_email=CLI_ACTOR)
        except audit.RekeyRefused as exc:
            return _fail(f"{exc}; nothing was changed", EXIT_REFUSED)
    finally:
        conn.close()
    print(f"re-keyed: audit row {row_id} (audit.rekeyed, actor cli) records it; the hub signs "
          f"with this key from now on")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command; returns the process exit code."""
    args = build_parser().parse_args(argv)
    load_hub_env()
    if args.command == "check":
        return _check()
    if not config.enabled():
        return _fail("Nerva Workspace is disabled in this environment (NERVA_WORKSPACE is not "
                     f"on) — {SERVICE_ENV_HINT}", EXIT_REFUSED)
    refused = _preflight(args.command)
    if refused is not None:
        return refused
    if args.command == "setup-code":
        return _setup_code()
    if args.command == "audit-rekey":
        return _audit_rekey(args.confirm)
    email = args.email.strip().lower()
    if args.command == "reset-link":
        return _reset_link(email, args.base_url.strip())
    return _promote(email)
