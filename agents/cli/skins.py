"""`nerva skin` — H052 + H591 CLI terminal colour skins & chrome theming."""

from __future__ import annotations

import argparse
from pathlib import Path

from agents.core.skins import (
    SkinValidationError,
    format_spinner_done,
    format_spinner_frame,
    format_tool_line,
    get_active_skin,
    get_skin,
    list_skins,
    render_banner,
    reset_active_skin,
    set_active_skin,
    validate_skin_file,
)


def register_parser(verbs):
    skin = verbs.add_parser(
        "skin",
        help="CLI colour skins, spinner faces/verbs, branding, tool prefixes and banners (offline)",
    )
    ops = skin.add_subparsers(dest="operation", required=True)

    list_p = ops.add_parser("list", help="list built-in and user-authored YAML skins")
    list_p.add_argument("--json", action="store_true")

    use_p = ops.add_parser("use", help="activate a skin by name")
    use_p.add_argument("name")
    use_p.add_argument("--json", action="store_true")

    set_p = ops.add_parser("set", help="activate a skin by name (alias for use)")
    set_p.add_argument("name")
    set_p.add_argument("--json", action="store_true")

    show_p = ops.add_parser("show", help="inspect a skin's colours, spinner, branding and tool emojis")
    show_p.add_argument("name", nargs="?", default="", help="skin name (defaults to active)")
    show_p.add_argument("--json", action="store_true")

    render_p = ops.add_parser("render", help="preview banner, spinner, tool line and prompt in terminal")
    render_p.add_argument("name", nargs="?", default="", help="skin name (defaults to active)")

    validate_p = ops.add_parser("validate", help="validate a user-authored YAML skin file")
    validate_p.add_argument("path")
    validate_p.add_argument("--json", action="store_true")

    reset_p = ops.add_parser("reset", help="reset active CLI skin to nerva-obsidian")
    reset_p.add_argument("--json", action="store_true")
    return skin


def _skins_dir_for(ctx) -> Path | None:
    env = getattr(ctx, "environ", None) or {}
    for key in ("NERVA_HOME", "JARVIS_HOME"):
        val = str(env.get(key, "") or "").strip()
        if val:
            return Path(val).expanduser() / "skins"
    return None


def run(ns: argparse.Namespace, ctx) -> int:
    op = ns.operation
    directory = _skins_dir_for(ctx)

    if op == "list":
        report = list_skins(env=ctx.environ, directory=directory)
        if getattr(ns, "json", False):
            ctx.dump(report)
            return 0
        for item in report["skins"]:
            mark = "*" if item["active"] else " "
            ctx.say(
                f"{mark} {item['name']} ({item['source']}) · {item['prompt_symbol']} · {item['description']}"
            )
        for fname, err in sorted(report["errors"].items()):
            ctx.err.write(f"! {fname}: {err}\n")
        return 0

    if op in ("use", "set"):
        try:
            chosen = set_active_skin(ns.name, directory=directory)
        except (KeyError, SkinValidationError) as exc:
            ctx.err.write(f"{exc}\n")
            return 1
        if getattr(ns, "json", False):
            ctx.dump({"ok": True, "active": chosen.name, "skin": chosen.to_dict()})
        else:
            ctx.say(f"Active CLI skin set to {chosen.name} ({chosen.description})")
        return 0

    if op == "reset":
        chosen = reset_active_skin(directory=directory)
        if getattr(ns, "json", False):
            ctx.dump({"ok": True, "active": chosen.name})
        else:
            ctx.say(f"Active CLI skin reset to {chosen.name}")
        return 0

    if op == "show":
        target = (
            get_skin(ns.name, directory=directory)
            if ns.name
            else get_active_skin(env=ctx.environ, directory=directory)
        )
        if target is None:
            ctx.err.write(f"unknown skin: {ns.name}\n")
            return 1
        if getattr(ns, "json", False):
            ctx.dump(target.to_dict())
            return 0
        ctx.say(f"{target.name} ({target.source}) — {target.description}")
        ctx.say(f"  branding: {target.branding['product_name']} · prompt={target.branding['prompt_symbol']}")
        ctx.say(f"  spinner:  {' '.join(target.spinner['faces'])} · {', '.join(target.spinner['verbs'])}")
        ctx.say(f"  tools:    prefix={target.tool_prefix} · {len(target.tool_emojis)} emoji mappings")
        ctx.say(f"  accent:   {target.colors['accent']} · primary={target.colors['primary']}")
        return 0

    if op == "render":
        target = (
            get_skin(ns.name, directory=directory)
            if ns.name
            else get_active_skin(env=ctx.environ, directory=directory)
        )
        if target is None:
            ctx.err.write(f"unknown skin: {ns.name}\n")
            return 1
        ctx.say(render_banner(target, env=ctx.environ))
        ctx.say("  " + format_spinner_frame(target, step=0, detail="resolving tools", env=ctx.environ))
        ctx.say("  " + format_tool_line("delegate_task", "2 children", skin=target, env=ctx.environ))
        ctx.say("  " + format_spinner_done(target, message="turn complete", env=ctx.environ))
        return 0

    if op == "validate":
        try:
            validated = validate_skin_file(ns.path)
        except SkinValidationError as exc:
            if getattr(ns, "json", False):
                ctx.dump({"ok": False, "path": ns.path, "problems": list(exc.problems)})
            else:
                ctx.err.write(f"invalid skin {ns.path}: {exc}\n")
            return 1
        if getattr(ns, "json", False):
            ctx.dump({"ok": True, "skin": validated.to_dict()})
        else:
            ctx.say(f"valid skin: {validated.name} ({len(validated.colors)} colours)")
        return 0

    raise argparse.ArgumentTypeError("unknown skin operation")
