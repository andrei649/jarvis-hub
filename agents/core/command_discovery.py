"""H079: bounded, caller-filtered discovery of executable slash namespaces."""

from __future__ import annotations

import logging
import re

PAGE_SIZE = 20
_PAGE = re.compile(r"[1-9][0-9]{0,5}\Z")
_SKILL_NAME = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
logger = logging.getLogger("jarvis.commands.discovery")


def reply(ctx) -> str:
    from .commands import ALIASES, CommandRegistry
    from .quick_commands import help_lines, named
    from .slash_access import listed_names

    raw = ctx.args.strip() or "1"
    if not _PAGE.fullmatch(raw):
        return "Usage: /commands [page] — choose a positive page number."
    registry = getattr(ctx.orch, "commands", None)
    if not isinstance(registry, CommandRegistry):
        return "No commands are registered."
    visible = registry.visible(ctx.principal)
    if ctx.principal.admin is not True:
        allowed = listed_names(registry, ctx.principal, orch=ctx.orch)
        visible = [command for command in visible if allowed is None or command.name in allowed]
    rows = [command.summary for command in visible]
    note = ""
    if ctx.principal.admin is True:
        from .skills import bundles, slash_load

        rows.extend(help_lines(registry))
        collisions = 0

        def taken(name):
            return name == "nerva" or name in ALIASES or registry.get(name) is not None or named(name)

        try:
            stored = bundles.list_bundles()
        except OSError:
            # Bundle lookup precedes skills: neither shortcut is usable then.
            stored = None
            note = "Skill and bundle discovery is unavailable."
        if stored is not None:
            rows.extend(f"/bundle {bundle.slug} — bundle ({len(bundle.skills)} skills)" for bundle in stored)
            bundle_names = {bundle.slug for bundle in stored}
            loader = getattr(ctx.orch, "skills", None)
            skills = (getattr(loader, "skills", None) or {}).values()
            shown = set()
            for skill in sorted(skills, key=lambda item: item.name):
                name = bundles.slugify(skill.name)
                label = name.replace('-', '_') if ctx.principal.channel == "telegram" else name
                if not _SKILL_NAME.fullmatch(name) or name in bundle_names or name in shown:
                    continue
                if taken(name) or taken(label):
                    collisions += 1
                    continue
                try:
                    if loader.catalog_gate(skill):
                        continue
                    inv = slash_load.resolve('/' + label, loader, taken=taken)
                    if inv is None or inv.ambiguous or inv.skill_name != skill.name:
                        continue
                except Exception:
                    note = "Some skills could not be checked and are omitted."
                    continue
                shown.add(name)
                # The resolver accepts this Telegram spelling of skill mentions.
                rows.append(f"/{label} — skill")
        if collisions:
            logger.warning("Skill command collision refusals: %d", collisions)
    total = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = int(raw)
    if page > total:
        return f"Usage: /commands [page] — choose a page from 1 to {total}."
    selected = rows[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    footer = f"Next: /commands {page + 1}" if page < total else "End of command list."
    if note:
        footer += " " + note
    return '\n'.join([f"Commands — page {page}/{total} ({len(rows)} entries)", *selected, footer])
