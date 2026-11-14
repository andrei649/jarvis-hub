"""CLI verbs for ``nerva profile``: list, create, delete, rename, describe, alias, unalias, export, import, wrapper (H036)."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agents.core.profiles import (
    create_profile,
    delete_profile,
    describe_profile,
    export_profile,
    import_profile,
    list_profiles,
    remove_profile_alias,
    rename_profile,
    render_profile_wrapper,
    set_profile_alias,
    write_profile_wrapper,
)

from .chat_prompts import card_safe

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


def register_parser(verbs: argparse._SubParsersAction) -> None:
    profile = verbs.add_parser(
        "profile",
        help="list, create, rename, delete, alias, export/import profiles and generate wrapper scripts (offline)",
    )
    sub = profile.add_subparsers(dest="action", required=True, metavar="action")

    p_list = sub.add_parser("list", help="list default and named profiles with roots and aliases")
    p_list.add_argument("--json", action="store_true")

    p_create = sub.add_parser("create", help="create an isolated named profile directory and .env")
    p_create.add_argument("name", help="profile name (1-32 lowercase letters, digits, '-' or '_')")
    p_create.add_argument("--description", default="", help="optional human description")
    p_create.add_argument("--json", action="store_true")

    p_desc = sub.add_parser("describe", help="inspect or update a profile's description")
    p_desc.add_argument("name", help="profile name or alias")
    p_desc.add_argument("description", nargs="?", help="new description text (omit to inspect)")
    p_desc.add_argument("--clear", action="store_true", help="remove the stored description")
    p_desc.add_argument("--json", action="store_true")

    p_rename = sub.add_parser("rename", help="rename an existing profile directory and update its aliases")
    p_rename.add_argument("old_name", help="existing profile name")
    p_rename.add_argument("new_name", help="new profile name")
    p_rename.add_argument("--json", action="store_true")

    p_delete = sub.add_parser("delete", help="permanently remove a named profile directory")
    p_delete.add_argument("name", help="profile name to delete (never 'default')")
    p_delete.add_argument("--confirm", action="store_true", help="confirm destructive deletion")
    p_delete.add_argument("--json", action="store_true")

    p_alias = sub.add_parser("alias", help="bind a short alias to a profile name")
    p_alias.add_argument("alias", help="alias name")
    p_alias.add_argument("target", help="target profile name")
    p_alias.add_argument("--json", action="store_true")

    p_unalias = sub.add_parser("unalias", help="remove a profile alias")
    p_unalias.add_argument("alias", help="alias name to remove")
    p_unalias.add_argument("--json", action="store_true")

    p_export = sub.add_parser("export", help="export a profile into a verified .tar.gz archive")
    p_export.add_argument("name", help="profile name or alias to export")
    p_export.add_argument("--out", required=True, metavar="ARCHIVE", help="destination .tar.gz path")
    p_export.add_argument(
        "--include-secrets",
        action="store_true",
        help="also include .env, secrets.enc and *.key files (omitted by default)",
    )
    p_export.add_argument("--json", action="store_true")

    p_import = sub.add_parser("import", help="import a profile archive into an isolated named profile")
    p_import.add_argument("archive", help="source .tar.gz archive path")
    p_import.add_argument("--as", dest="as_name", metavar="NAME", help="import under this profile name")
    p_import.add_argument("--force", action="store_true", help="replace an existing profile of the same name")
    p_import.add_argument("--json", action="store_true")

    p_wrap = sub.add_parser("wrapper", help="generate a per-profile nerva-<name> launcher script")
    p_wrap.add_argument("name", help="profile name or alias")
    p_wrap.add_argument("--dir", dest="dest_dir", metavar="DIR", help="directory for nerva-<name> script")
    p_wrap.add_argument("--out", dest="out_path", metavar="FILE", help="exact output script path")
    p_wrap.add_argument("--windows", action="store_true", help="emit a Windows .cmd wrapper instead of POSIX sh")
    p_wrap.add_argument("--print", dest="print_only", action="store_true", help="print script to stdout without writing")
    p_wrap.add_argument("--json", action="store_true")


def cmd_profile(ns: argparse.Namespace, ctx: Any) -> int:
    env = ctx.environ
    try:
        if ns.action == "list":
            rows = list_profiles(environ=env)
            if ns.json:
                ctx.dump({"profiles": rows})
                return EXIT_OK
            for row in rows:
                marker = "*" if row["active"] else " "
                aliases = f" (aliases: {', '.join(row['aliases'])})" if row["aliases"] else ""
                desc = f" — {card_safe(row['description'])}" if row["description"] else ""
                ctx.say(f"{marker} {row['name']:16s} {row['root']}{aliases}{desc}")
            return EXIT_OK

        if ns.action == "create":
            res = create_profile(ns.name, description=ns.description, environ=env)
            if ns.json:
                ctx.dump(res)
            else:
                ctx.say(f"created profile {res['name']} at {res['root']}")
            return EXIT_OK

        if ns.action == "describe":
            res = describe_profile(ns.name, ns.description, clear=bool(ns.clear), environ=env)
            if ns.json:
                ctx.dump(res)
            else:
                desc = card_safe(res["description"]) or "(no description)"
                ctx.say(f"{res['name']}: {desc} ({res['root']})")
            return EXIT_OK

        if ns.action == "rename":
            res = rename_profile(ns.old_name, ns.new_name, environ=env)
            if ns.json:
                ctx.dump(res)
            else:
                ctx.say(f"renamed profile {res['old_name']} -> {res['new_name']} ({res['root']})")
            return EXIT_OK

        if ns.action == "delete":
            res = delete_profile(ns.name, confirm=bool(ns.confirm), environ=env)
            if ns.json:
                ctx.dump(res)
            else:
                ctx.say(f"deleted profile {res['deleted']}")
            return EXIT_OK

        if ns.action == "alias":
            res = set_profile_alias(ns.alias, ns.target, environ=env)
            if ns.json:
                ctx.dump(res)
            else:
                ctx.say(f"aliased {res['alias']} -> {res['target']}")
            return EXIT_OK

        if ns.action == "unalias":
            res = remove_profile_alias(ns.alias, environ=env)
            if ns.json:
                ctx.dump(res)
            else:
                ctx.say(f"removed alias {res['unaliased']} (was {res['previous_target']})")
            return EXIT_OK

        if ns.action == "export":
            res = export_profile(
                ns.name,
                Path(ns.out),
                include_secrets=bool(ns.include_secrets),
                environ=env,
            )
            if ns.json:
                ctx.dump(res)
            else:
                ctx.say(f"exported profile {res['name']} -> {res['archive']} ({res['file_count']} files)")
            return EXIT_OK

        if ns.action == "import":
            res = import_profile(
                Path(ns.archive),
                as_name=ns.as_name,
                force=bool(ns.force),
                environ=env,
            )
            if ns.json:
                ctx.dump(res)
            else:
                ctx.say(f"imported profile {res['name']} into {res['root']} ({res['file_count']} files)")
            return EXIT_OK

        if ns.action == "wrapper":
            if ns.print_only:
                resolved, content = render_profile_wrapper(ns.name, windows=bool(ns.windows), environ=env)
                if ns.json:
                    ctx.dump({"ok": True, "name": resolved, "script": content})
                else:
                    ctx.out.write(content)
                return EXIT_OK
            res = write_profile_wrapper(
                ns.name,
                dest_dir=Path(ns.dest_dir) if ns.dest_dir else None,
                out_path=Path(ns.out_path) if ns.out_path else None,
                windows=bool(ns.windows),
                environ=env,
            )
            if ns.json:
                ctx.dump(res)
            else:
                ctx.say(f"wrote wrapper for profile {res['name']}: {res['wrapper']}")
            return EXIT_OK
    except ValueError as exc:
        ctx.err.write(f"{exc}\n")
        return EXIT_USAGE
    except OSError as exc:
        ctx.err.write(f"profile operation failed: {exc}\n")
        return EXIT_FAILED

    return EXIT_USAGE
