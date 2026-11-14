"""`nerva import` — H012 CLI tree verb for governed migration & post-migration cleanup."""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import importlib.util
import sys
from pathlib import Path
from typing import Any

from agents.core.paths import data_path
from agents.core.skills.importer import (
    CODEX_MIGRATION_MAPPING,
    MIGRATION_SOURCES,
    DetectedSource,
    detect_sources,
    install_root,
    rescan_imported,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SECTIONS = ("skills", "persona", "memory", "tokens")


def _load_import_module():
    mod = sys.modules.get("_nerva_import_script")
    if mod is not None:
        return mod
    script_path = _REPO_ROOT / "scripts" / "nerva_import.py"
    spec = importlib.util.spec_from_file_location("_nerva_import_script", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {script_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_nerva_import_script"] = mod
    spec.loader.exec_module(mod)
    return mod


def _data_root_for(ctx) -> Path:
    env = getattr(ctx, "environ", None) or {}
    for key in ("NERVA_HOME", "JARVIS_HOME"):
        val = str(env.get(key, "") or "").strip()
        if val:
            return Path(val).expanduser()
    return data_path()


def register_parser(verbs):
    imp = verbs.add_parser(
        "import",
        help="migrate skills, persona, memory and tokens from Hermes, OpenClaw, Claude Code or Codex (offline)",
    )
    ops = imp.add_subparsers(dest="operation", required=True)

    sources_p = ops.add_parser(
        "sources",
        help="detect local Hermes / OpenClaw / Claude Code / Codex installs and show mappings",
    )
    sources_p.add_argument("--home", default=None, help="home directory holding the installs (default ~)")
    sources_p.add_argument("--json", action="store_true")

    plan_p = ops.add_parser("plan", help="dry-run migration plan (writes nothing)")
    plan_p.add_argument("--from", dest="source", default="all", choices=(*MIGRATION_SOURCES, "all"))
    plan_p.add_argument("--home", default=None, help="home directory holding the installs (default ~)")
    plan_p.add_argument("--only", default=",".join(_SECTIONS), help="comma list: skills,persona,memory,tokens")
    plan_p.add_argument("--skills-dir", default=None)
    plan_p.add_argument("--json", action="store_true")

    apply_p = ops.add_parser("apply", help="apply governed migration (quarantined skills, queued memory)")
    apply_p.add_argument("--from", dest="source", default="all", choices=(*MIGRATION_SOURCES, "all"))
    apply_p.add_argument("--home", default=None, help="home directory holding the installs (default ~)")
    apply_p.add_argument("--only", default=",".join(_SECTIONS), help="comma list: skills,persona,memory,tokens")
    apply_p.add_argument("--skills-dir", default=None)
    apply_p.add_argument("--overwrite-tokens", action="store_true")
    apply_p.add_argument("--update", action="store_true", help="re-import changed skills into quarantine")
    apply_p.add_argument("--json", action="store_true")

    cleanup_p = ops.add_parser(
        "cleanup",
        help="post-migration source cleanup (`claw cleanup` analogue, dry-run first by default)",
    )
    cleanup_p.add_argument("--from", dest="source", default="all", choices=(*MIGRATION_SOURCES, "all"))
    cleanup_p.add_argument("--home", default=None, help="home directory holding the installs (default ~)")
    cleanup_p.add_argument("--archive-dir", default=None, help="backup directory before removing source files")
    cleanup_p.add_argument("--apply", action="store_true", help="execute archive & removal (default: dry-run)")
    cleanup_p.add_argument(
        "--confirm", "--yes", dest="confirm", action="store_true",
        help="confirm source file removal after archiving",
    )
    cleanup_p.add_argument("--json", action="store_true")

    return imp


async def _run_migration(ns: argparse.Namespace, ctx, *, apply: bool) -> int:
    ni = _load_import_module()
    sections = tuple(s.strip() for s in ns.only.split(",") if s.strip())
    unknown = set(sections) - set(_SECTIONS)
    if unknown:
        ctx.err.write(f"unknown sections: {', '.join(sorted(unknown))}\n")
        return 2

    home = Path(ns.home) if ns.home else None
    detected = detect_sources(home, None if ns.source == "all" else ns.source)
    data_root = _data_root_for(ctx)
    skills_dir = Path(ns.skills_dir) if ns.skills_dir else (data_root / "skills")
    if "skills" in sections:
        in_scope = MIGRATION_SOURCES if ns.source == "all" else (ns.source,)
        present = {item.source for item in detected}
        for name in in_scope:
            if name not in present and rescan_imported(skills_dir, name, home=home):
                detected.append(DetectedSource(source=name, root=install_root(name, home)))
    if not detected:
        ctx.err.write("no Hermes / OpenClaw / Claude Code / Codex install detected\n")
        return 2

    secret_store = None
    pending_store = None
    revoker = None
    if apply:
        pending_store = ni.PendingMemoryStore(data_root / "imports" / "imports.db")
        if "tokens" in sections:
            from agents.core.secrets import SecretStore

            secret_store = SecretStore(path=data_root / "secrets.enc")
        if getattr(ns, "update", False) and "skills" in sections:
            revoker = ni._approval_revoker()

    reports: list[dict[str, Any]] = []
    for src in detected:
        runner = ni.ImportRunner(
            src,
            authorizer=ni.kernel_import_authorizer(kill_switch_path=data_root / "kill_switch.json"),
            secret_store=secret_store,
            skills_dir=skills_dir,
            pending_store=pending_store,
            preview_dir=(data_root / "imports") if apply else None,
            sections=sections,
            overwrite_tokens=bool(getattr(ns, "overwrite_tokens", False)),
            update_skills=bool(getattr(ns, "update", False)),
            skill_backup_dir=(data_root / "imports" / "skill_backups") if apply else None,
            approval_revoker=revoker,
        )
        reports.append(await (runner.apply() if apply else runner.plan()))

    if getattr(ns, "json", False):
        ctx.dump(reports)
        return 0
    for report in reports:
        mode = "APPLIED" if apply else "DRY RUN"
        ctx.say(f"→ {report['source']['source']} at {report['source']['root']} [{mode}]")
        for section in sections:
            ctx.say(ni._summary_line(section, report["sections"].get(section)))
    if not apply:
        ctx.say("  (nothing written — run `nerva import apply` to execute)")
    return 0


def run(ns: argparse.Namespace, ctx) -> int:
    op = ns.operation

    if op == "sources":
        home = Path(ns.home) if ns.home else None
        detected = detect_sources(home)
        payload = {
            "supported_sources": list(MIGRATION_SOURCES),
            "codex_mapping": CODEX_MIGRATION_MAPPING,
            "detected": [d.as_dict() for d in detected],
        }
        if getattr(ns, "json", False):
            ctx.dump(payload)
            return 0
        ctx.say(f"Supported migration sources: {', '.join(MIGRATION_SOURCES)}")
        if not detected:
            ctx.say("Detected installs: none")
            return 0
        for item in detected:
            ctx.say(
                f"- {item.source} ({item.root}): "
                f"{len(item.skill_dirs)} skills, {len(item.persona_files)} persona, "
                f"{len(item.memory_files)} memory, {len(item.token_files)} token files"
            )
        return 0

    if op in ("plan", "apply"):
        coro = _run_migration(ns, ctx, apply=(op == "apply"))
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()

    if op == "cleanup":
        ni = _load_import_module()
        home = Path(ns.home) if ns.home else None
        detected = detect_sources(home, None if ns.source == "all" else ns.source)
        if not detected:
            ctx.err.write("no Hermes / OpenClaw / Claude Code / Codex install detected\n")
            return 2
        dry = not bool(ns.apply)
        confirmed = bool(ns.confirm)
        data_root = _data_root_for(ctx)
        archive_dir = Path(ns.archive_dir) if ns.archive_dir else (data_root / "imports" / "cleanup_backups")
        reports = [
            ni.cleanup_source(src, dry_run=dry, confirm=confirmed, archive_dir=archive_dir)
            for src in detected
        ]
        if not dry and not confirmed:
            if getattr(ns, "json", False):
                ctx.dump(reports)
            else:
                ctx.err.write(
                    "cleanup with --apply requires --confirm / --yes (run without --apply first to preview)\n"
                )
            return 2
        if getattr(ns, "json", False):
            ctx.dump(reports)
            return 0
        for rep in reports:
            mode = "DRY RUN" if rep["dry_run"] else "CLEANED UP"
            ctx.say(f"→ {rep['source']} at {rep['root']} [{mode}]")
            for item in rep["items"]:
                ctx.say(f"  {item['section']:8s} {item['status']}  {item['path']}")
            if rep.get("archive_dir"):
                ctx.say(f"  archived backup: {rep['archive_dir']}")
        if dry:
            ctx.say("  (dry-run only — re-run with `--apply --confirm` to archive & remove)")
        return 0

    raise argparse.ArgumentTypeError("unknown import operation")
