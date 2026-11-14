"""CLI `.env` persistence surface guarded by the shared dangerous-env denylist (H499)."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agents.core.security.env_write_guard import (
    EnvWriteRefusedError,
    check_env_persistence_allowed,
    denylist_manifest,
    read_dotenv_summary,
    resolve_default_dotenv_target,
    unset_dotenv_var,
    write_dotenv_var,
)

from .chat_prompts import card_safe

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


def register_parser(verbs: argparse._SubParsersAction) -> None:
    env = verbs.add_parser(
        "env",
        help="inspect or update non-policy .env entries behind the dangerous-env write guard (offline)",
    )
    sub = env.add_subparsers(dest="action", required=True, metavar="action")

    e_list = sub.add_parser("list", help="list variable names in the target .env (values never printed)")
    e_list.add_argument("--file", dest="env_file", metavar="PATH", help="explicit .env file path")
    e_list.add_argument("--json", action="store_true")

    e_set = sub.add_parser("set", help="write NAME=VALUE to .env (refuses security-policy and loader denylist)")
    e_set.add_argument("name", help="environment variable name")
    e_set.add_argument("value", help="environment variable value")
    e_set.add_argument("--file", dest="env_file", metavar="PATH", help="explicit .env file path")
    e_set.add_argument("--json", action="store_true")

    e_unset = sub.add_parser("unset", help="remove NAME from .env (refuses protected security-policy names)")
    e_unset.add_argument("name", help="environment variable name")
    e_unset.add_argument("--file", dest="env_file", metavar="PATH", help="explicit .env file path")
    e_unset.add_argument("--json", action="store_true")

    e_check = sub.add_parser("check", help="check whether NAME is permitted at the .env persistence boundary")
    e_check.add_argument("name", help="environment variable name")
    e_check.add_argument("--json", action="store_true")

    e_deny = sub.add_parser("denylist", help="show the shared dangerous & security-policy environment denylist")
    e_deny.add_argument("--json", action="store_true")


def _target_file(ns: argparse.Namespace, ctx: Any) -> Path:
    explicit = getattr(ns, "env_file", None)
    return Path(explicit).expanduser() if explicit else resolve_default_dotenv_target(ctx.environ)


def cmd_env(ns: argparse.Namespace, ctx: Any) -> int:
    if ns.action == "denylist":
        manifest = denylist_manifest()
        if ns.json:
            ctx.dump(manifest)
            return EXIT_OK
        ctx.say(f"shared environment persistence denylist ({manifest['total_exact_names']} exact names):")
        ctx.say("  prefixes:        " + ", ".join(manifest["control_or_loader_prefixes"]))
        ctx.say("  control/loader:  " + ", ".join(manifest["control_or_loader_names"][:16]) + " …")
        ctx.say("  security policy: " + ", ".join(manifest["security_policy_names"][:16]) + " …")
        return EXIT_OK

    if ns.action == "check":
        allowed, category, reason = check_env_persistence_allowed(ns.name)
        report = {
            "name": str(ns.name).strip(),
            "allowed": allowed,
            "category": category,
            "reason": reason,
        }
        if ns.json:
            ctx.dump(report)
        elif allowed:
            ctx.say(f"{card_safe(ns.name)}: allowed at .env persistence boundary")
        else:
            ctx.err.write(f"{card_safe(ns.name)}: refused ({category}) — {reason}\n")
        return EXIT_OK if allowed else EXIT_FAILED

    target = _target_file(ns, ctx)
    if ns.action == "list":
        rows = read_dotenv_summary(target)
        if ns.json:
            ctx.dump({"path": str(target), "exists": target.is_file(), "variables": rows})
            return EXIT_OK
        if not rows:
            ctx.say(f"no variables defined in {target}")
            return EXIT_OK
        for row in rows:
            tags: list[str] = []
            if row["masked"]:
                tags.append("secret/masked")
            if row["protected_by_denylist"]:
                tags.append(f"protected:{row['denylist_category']}")
            suffix = f" ({', '.join(tags)})" if tags else ""
            ctx.say(f"  {card_safe(row['name'])}{suffix}")
        return EXIT_OK

    try:
        if ns.action == "set":
            res = write_dotenv_var(target, ns.name, ns.value)
            if ns.json:
                ctx.dump(res)
            else:
                ctx.say(f"{res['action']} {card_safe(res['name'])} in {res['path']}")
            return EXIT_OK
        if ns.action == "unset":
            res = unset_dotenv_var(target, ns.name)
            if ns.json:
                ctx.dump(res)
            elif res["removed"]:
                ctx.say(f"removed {card_safe(res['name'])} from {res['path']}")
            else:
                ctx.say(f"{card_safe(res['name'])} was not present in {res['path']}")
            return EXIT_OK
    except EnvWriteRefusedError as exc:
        if getattr(ns, "json", False):
            ctx.dump({
                "ok": False,
                "variable": exc.variable,
                "category": exc.category,
                "reason": exc.reason,
            })
        else:
            ctx.err.write(f"{exc}\n")
        return EXIT_FAILED
    except ValueError as exc:
        ctx.err.write(f"{exc}\n")
        return EXIT_USAGE
    except OSError as exc:
        ctx.err.write(f".env write failed: {exc}\n")
        return EXIT_FAILED

    return EXIT_USAGE
