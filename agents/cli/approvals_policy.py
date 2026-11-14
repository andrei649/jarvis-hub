"""Offline terminal approval dry-run, allowlist management, and history rule suggestion (H020, H482, H483)."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agents.core.autonomy.command_allowlist import (
    CommandAllowlistStore,
    explain_command_policy,
    suggest_allowlist_rules,
)

from .chat_prompts import card_safe

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2

POLICY_ACTIONS = frozenset({"check", "allowlist", "suggest"})


def configure_approvals_policy(approvals_verbs: argparse._SubParsersAction) -> None:
    """Register ``check``, ``allowlist``, and ``suggest`` under ``nerva approvals``."""
    check = approvals_verbs.add_parser(
        "check",
        help="dry-run shell policy, normalized variants, consent categories and allowlist on a command (offline)",
    )
    check.add_argument("command", help="shell command string to inspect without executing")
    check.add_argument("--mode", choices=("auto", "ask", "off"), help="override autonomy mode for what-if check")
    check.add_argument("--json", action="store_true")

    allowlist = approvals_verbs.add_parser(
        "allowlist",
        help="manage literal/glob safe terminal command allowlist entries (offline)",
    )
    al_verbs = allowlist.add_subparsers(dest="allowlist_action", required=True, metavar="subcommand")
    al_list = al_verbs.add_parser("list", help="list active command allowlist patterns")
    al_list.add_argument("--json", action="store_true")

    al_add = al_verbs.add_parser("add", help="add one validated literal or narrow glob pattern (e.g. 'cargo *')")
    al_add.add_argument("pattern", help="command pattern to allowlist")
    al_add.add_argument("--json", action="store_true")

    al_rm = al_verbs.add_parser("remove", help="remove one pattern from the allowlist")
    al_rm.add_argument("pattern", help="command pattern to remove")
    al_rm.add_argument("--json", action="store_true")

    al_clear = al_verbs.add_parser("clear", help="remove all patterns from the allowlist")
    al_clear.add_argument("--json", action="store_true")

    suggest = approvals_verbs.add_parser(
        "suggest",
        help="propose narrow allowlist globs from approved command history (dry-run unless --apply)",
    )
    suggest.add_argument("--min-count", type=int, default=2, metavar="N", help="minimum safe occurrences (default 2)")
    suggest.add_argument("--from-file", metavar="PATH", help="optional newline-delimited command history file")
    suggest.add_argument("--apply", action="store_true", help="write proposed narrow rules to the allowlist store")
    suggest.add_argument("--json", action="store_true")


def run_approvals_policy(ns: argparse.Namespace, ctx: Any) -> int:
    store = CommandAllowlistStore()
    if ns.action == "check":
        report = explain_command_policy(
            ns.command,
            environ=ctx.environ,
            store=store,
            autonomy_mode=getattr(ns, "mode", None),
        )
        if ns.json:
            ctx.dump(report)
            return EXIT_OK
        ctx.say(f"approvals check: {card_safe(ns.command)[:240]}")
        for step in report["gates"]:
            ctx.say(f"  {step['gate']:14s} {card_safe(step['result'])[:200]}")
        if len(report["normalized_variants"]) > 1:
            ctx.say("  variants:")
            for variant in report["normalized_variants"]:
                ctx.say(f"    - {card_safe(variant)[:200]}")
        if report["consent_categories"]:
            ctx.say("  consent:")
            for cat in report["consent_categories"]:
                scope = "always|session" if cat["permanent"] else "session-only"
                ctx.say(f"    - {card_safe(cat['description'])} ({scope})")
        ctx.say(f"  -> {report['verdict'].upper()} ({', '.join(report['reasons'])})")
        return EXIT_OK

    if ns.action == "allowlist":
        sub = ns.allowlist_action
        if sub == "list":
            patterns = store.list_patterns()
            if ns.json:
                ctx.dump({"patterns": patterns, "path": str(store.path)})
                return EXIT_OK
            if not patterns:
                ctx.say("no command allowlist patterns configured")
                return EXIT_OK
            for item in patterns:
                ctx.say(f"  {card_safe(item)}")
            return EXIT_OK
        if sub == "add":
            try:
                patterns = store.add(ns.pattern)
            except ValueError as exc:
                ctx.err.write(f"refused allowlist pattern: {exc}\n")
                return EXIT_USAGE
            if ns.json:
                ctx.dump({"ok": True, "added": ns.pattern, "patterns": patterns, "path": str(store.path)})
            else:
                ctx.say(f"added allowlist pattern: {card_safe(ns.pattern)} ({len(patterns)} total)")
            return EXIT_OK
        if sub == "remove":
            removed, patterns = store.remove(ns.pattern)
            if ns.json:
                ctx.dump({"ok": removed, "removed": ns.pattern if removed else None, "patterns": patterns})
            elif removed:
                ctx.say(f"removed allowlist pattern: {card_safe(ns.pattern)}")
            else:
                ctx.err.write(f"pattern not in allowlist: {card_safe(ns.pattern)}\n")
                return EXIT_FAILED
            return EXIT_OK
        if sub == "clear":
            store.clear()
            if ns.json:
                ctx.dump({"ok": True, "patterns": []})
            else:
                ctx.say("cleared command allowlist")
            return EXIT_OK

    if ns.action == "suggest":
        if ns.min_count < 1:
            ctx.err.write("--min-count must be >= 1\n")
            return EXIT_USAGE
        commands: list[str] | None = None
        if ns.from_file:
            src = Path(ns.from_file)
            if not src.is_file() or src.is_symlink():
                ctx.err.write(f"history file is unreadable or a symlink: {ns.from_file}\n")
                return EXIT_USAGE
            try:
                commands = [line for line in src.read_text(encoding="utf-8").splitlines() if line.strip()]
            except OSError as exc:
                ctx.err.write(f"could not read history file: {exc}\n")
                return EXIT_FAILED
        report = suggest_allowlist_rules(
            commands,
            min_count=ns.min_count,
            apply=bool(ns.apply),
            store=store,
        )
        if ns.json:
            ctx.dump(report)
            return EXIT_OK
        proposals = report["proposals"]
        if not proposals:
            ctx.say(f"no new narrow allowlist rules met min_count={report['min_count']} (scanned {report['scanned']})")
            return EXIT_OK
        header = "applied allowlist suggestions:" if report["applied"] else "proposed allowlist rules (dry-run; pass --apply to write):"
        ctx.say(header)
        for row in proposals:
            ctx.say(f"  {card_safe(row['pattern']):24s}  seen {row['count']}x")
        return EXIT_OK

    return EXIT_USAGE
