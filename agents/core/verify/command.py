"""``/verify`` — the owner's project-verification command (Hermes ``hermes verify``).

    /verify [status] [path]        the project, its verify commands, recipe and evidence
    /verify detect [path]          static detection only (Hermes --detect-only)
    /verify save [path]            write the recipe to <project>/.hermes/environment.json (Hermes --save)
    /verify run [phases] [path]    build and test (or: bootstrap, build, test, all) through terminal_run
    /verify ledger                 recent evidence and the ledger's hash-chain check
    /verify on-stop on|off         the verify-on-stop nudge (off by default)
    /verify coding auto|on|off     the coding posture (brief + workspace snapshot)

The project is the one *path* is in, else the conversation's working folder (the default
project folder ``llm.project_dir`` or the first file root). Only paths inside the owner's
file roots. Owner only. ``save`` and ``run`` change or execute something, so both are
refused in plan mode and under the e-stop; ``run`` queues approval cards like any command.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("jarvis.verify.command")

USAGE = ("Usage: /verify [status|detect|save|run [bootstrap|build|test|all]|ledger] [path] · "
         "/verify on-stop on|off · /verify coding auto|on|off")
_PHASE_WORDS = {"bootstrap": ("bootstrap",), "build": ("build",), "test": ("test",),
                "all": ("bootstrap", "build", "test")}


def _who(ctx: Any) -> str:
    return f"{ctx.principal.channel}:{ctx.principal.sender or 'owner'}"


def _workdir(ctx: Any, scope) -> Path:
    from agents.core import project_context

    getter = getattr(ctx.orch, "get_setting", None)
    configured = getter("llm.project_dir", "") if callable(getter) else ""
    return project_context.start_dir(scope, configured)


def _project(ctx: Any, path: str | None):
    from .project import detect_facts, file_scope, workspace_root

    scope = file_scope()
    start = path if path else str(_workdir(ctx, scope))
    found = workspace_root(start, scope)
    if found is None:
        return None, None
    root, git = found
    return root, detect_facts(root, git=git)


def _recipe_lines(recipe, source: str) -> list[str]:
    if recipe is None:
        return ["Recipe: none detected"]
    lines = [f"Recipe ({source}): {recipe.name} [{recipe.kind}]"]
    for phase in ("bootstrap", "build", "test"):
        commands = getattr(recipe, phase) or []
        if commands:
            lines.append(f"- {phase}: " + "; ".join(f"`{c}`" for c in commands))
    if recipe.start:
        port = f" (port {recipe.port})" if recipe.port else ""
        lines.append(f"- start: `{recipe.start}`{port} — shown only; Nerva does not boot the app")
    return lines


def _status_text(root: Path, facts, recipe, source: str) -> str:
    from . import config, evidence

    lines = [f"Project: {root}" + (" (git)" if facts.git else "")]
    if facts.manifests:
        lines.append("Manifests: " + ", ".join(facts.manifests))
    lines.append("Verify commands: " + ("; ".join(f"`{c}`" for c in facts.verify_commands) or "none detected"))
    lines.extend(_recipe_lines(recipe, source))
    state = evidence.status(str(root))
    last = state.get("evidence") or {}
    summary = state["status"]
    if last:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(last["created_at"])))
        summary += f" — last `{last['canonical']}` {last['status']} (exit {last['exit_code']}, {when})"
    lines.append(f"Evidence: {summary}")
    settings = config.load()
    lines.append(f"Verify-on-stop: {settings['verify_on_stop']} · coding posture: {settings['coding_context']}")
    return "\n".join(lines)


def _ledger_text(ctx: Any) -> str:
    from . import evidence

    audit = getattr(ctx.orch, "intent_log", None)
    rows = evidence.recent(limit=10)
    check = evidence.verify_chain(audit)
    lines = [f"Evidence ledger: {check['n']} row(s); chain {'intact' if check['ok'] else 'BROKEN at row ' + str(check['bad_id']) + ' (' + check['reason'] + ')'}"]
    for row in rows:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(row["created_at"])))
        anchored = "anchored" if row["audit_hash"] else "not anchored"
        lines.append(f"- #{row['id']} {when} {row['status']} {row['kind']}/{row['scope']} `{row['canonical']}` "
                     f"in {row['root']} ({anchored})")
    return "\n".join(lines)


def _blocked(session: str | None) -> str:
    from .runner import preflight

    return preflight(session)


async def verify_command(ctx: Any) -> str:
    from . import config
    from .project import detect_recipe, load_recipe, save_recipe

    if not ctx.principal.admin:
        return "Only the owner can use /verify; nothing changed."
    words = (ctx.args or "").split()
    action = words[0].lower() if words else "status"
    rest = words[1:] if words else []
    session = getattr(ctx.orch, "session_id", None)
    audit = getattr(ctx.orch, "intent_log", None)

    if action in {"on-stop", "onstop", "coding"}:
        key = "verify_on_stop" if action != "coding" else "coding_context"
        if len(rest) != 1 or config.normalize(key, rest[0]) is None:
            return USAGE
        value = config.normalize(key, rest[0])
        await asyncio.to_thread(config.save, key, value, by=_who(ctx), audit=audit)
        label = "Verify-on-stop" if key == "verify_on_stop" else "Coding posture"
        return f"{label} is now {value}."
    if action == "ledger":
        return await asyncio.to_thread(_ledger_text, ctx)
    if action not in {"status", "detect", "save", "run"}:
        # "/verify <path>" reads as status of that path.
        rest, action = words, "status"

    phases: tuple[str, ...] = ()
    paths: list[str] = []
    for word in rest:
        if action == "run" and word.lower() in _PHASE_WORDS:
            phases += _PHASE_WORDS[word.lower()]
        else:
            paths.append(word)
    if len(paths) > 1:
        return USAGE
    root, facts = await asyncio.to_thread(_project, ctx, paths[0] if paths else None)
    if root is None:
        return ("No project found there: a project is a git repository or a folder with a manifest "
                "(package.json, pyproject.toml, go.mod …) inside your file roots.")

    if action == "status":
        recipe, source = await asyncio.to_thread(load_recipe, root)
        return await asyncio.to_thread(_status_text, root, facts, recipe, source)
    if action == "detect":
        recipe = await asyncio.to_thread(detect_recipe, root)
        payload = {"root": str(root), "facts": facts.to_dict(), "recipe": recipe.to_dict() if recipe else None}
        return "\n".join([*_recipe_lines(recipe, "detected"), "", json.dumps(payload, indent=2)])
    if action == "save":
        blocked = _blocked(session)
        if blocked:
            return f"Nothing saved: {blocked}."
        recipe, source = await asyncio.to_thread(load_recipe, root)
        if recipe is None:
            return "Nothing saved: no recipe was detected for this project."
        try:
            written = await asyncio.to_thread(save_recipe, root, recipe)
        except (OSError, PermissionError) as exc:
            return f"Nothing saved: {type(exc).__name__}."
        if audit is not None:
            try:
                audit.record(actor=_who(ctx)[:120], action="verify.manifest_saved",
                             why=f"{root}", metadata={"root": str(root), "path": str(written), "from": source})
            except Exception:  # noqa: BLE001
                logger.debug("verify manifest audit failed", exc_info=True)
        return f"Saved the recipe to {written}. Edit it to change what /verify runs; it wins over detection."

    # run
    from .runner import DEFAULT_PHASES, run

    recipe, source = await asyncio.to_thread(load_recipe, root)
    report = await run(getattr(ctx.orch, "tool_rpc", None), root=root, recipe=recipe, session=session,
                       phases=phases or DEFAULT_PHASES)
    lines = [f"/verify run in {root} ({source} recipe): {report.status}"]
    for step in report.steps:
        extra = f" exit {step['exit_code']}" if "exit_code" in step else ""
        task = f" (task {step['task_id']})" if step.get("task_id") else ""
        lines.append(f"- {step['phase']}: `{step['command']}` {step.get('result', '')}{extra}{task}")
    if report.reason:
        lines.append(report.reason)
    if report.status == "passed":
        lines.append("Each passing command is in the evidence ledger (/verify ledger).")
    return "\n".join(lines)


__all__ = ["USAGE", "verify_command"]
