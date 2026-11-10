"""``/worktree`` and ``/delegations`` — the owner's side of G18 (H474, H401).

``/worktree`` (Hermes ``hermes -w`` and ``/worktree``, ``hermes_cli/worktree_ops.py``):

* ``/worktree new [name] [--from <branch>]`` moves this conversation into a git worktree
  of its own: ``<project>/.worktrees/<name>`` on ``nerva/<name>``, branched from the
  project's HEAD (or the named local branch). From the next turn the session reads the
  project from there and its file tools resolve inside it; nothing else moves.
* ``/worktree off`` moves the conversation back; the tree is kept.
* ``/worktree list`` classifies every tree of the project: age, size, verdict and why.
* ``/worktree prune [--apply] [--max-age <hours>]`` shows what a reclaim would remove
  (default) or removes it: only trees that are clean and pushed, never a protected branch,
  a locked tree or one in use; untracked scratch is archived first, never deleted.

The project is ``llm.project_dir``. Every git command runs through the shared hardened
helper (``agents.core.worktrees``): a repository whose config could make git run a program
is refused. Creating, moving and removing are refused while the emergency stop is engaged
and while this conversation is in plan mode.

With ``autonomy.worktree_auto_reclaim`` on, :func:`opportunistic_reclaim` runs the same prune on
the autonomy tick, at most hourly, for trees older than ``autonomy.worktree_reclaim_max_age_hours``
— only when the approval mode is not ``off`` and, with the Action Kernel on, only with a
``file.write`` grant (the reversible tier: clean, pushed, scratch archived).

``/delegations`` lists the durable delegation rows (H401) and ``/delegations collect``
receives the finished results nobody has received yet — each exactly once, whichever
consumer (this command, the model's ``delegate_task`` collect, the HTTP claim) asks first.
"""

from __future__ import annotations

import asyncio
import logging
import shlex
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("jarvis.worktree_commands")

WORKTREE_USAGE = ("Usage: /worktree new [name] [--from <branch>] · /worktree off · /worktree status · "
                  "/worktree list · /worktree prune [--apply] [--max-age <hours>]")
DELEGATIONS_USAGE = "Usage: /delegations [list] · /delegations collect"
RECLAIM_INTERVAL_SECONDS = 3600.0
DEFAULT_RECLAIM_MAX_AGE_HOURS = 72
_last_reclaim = 0.0


def _session(orch: Any) -> str:
    return str(getattr(orch, "session_id", None) or "default")


def _project(orch: Any) -> tuple[Path | None, str]:
    """``(the project's primary checkout, "")`` or ``(None, why not)``."""
    from . import worktrees
    from .file_tools import FileScope

    getter = getattr(orch, "get_setting", None)
    raw = getter("llm.project_dir", "") if callable(getter) else ""
    if not isinstance(raw, str) or not raw.strip():
        return None, "no project folder is set (llm.project_dir)"
    folder = Path(raw).expanduser()
    if not folder.is_dir():
        return None, "the project folder does not exist"
    top = worktrees.repo_root(folder)
    if top is None:
        return None, "the project folder is not a git repository"
    repo = worktrees.main_repo(top) or top
    try:
        if FileScope.from_env().root_for(repo.resolve()) is None:
            return None, "the project is outside the owner's file roots"
    except Exception:  # noqa: BLE001
        return None, "the owner's file roots could not be read"
    return repo, ""


def _age(seconds: Any) -> str:
    if not isinstance(seconds, (int, float)):
        return "?"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    if seconds < 86400:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86400:.1f}d"


def _size(value: Any) -> str:
    if not isinstance(value, int):
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024:
            return f"{value}{unit}"
        value //= 1024
    return f"{value}TB"


def _row(row: dict, repo: Path) -> str:
    try:
        shown = str(Path(row["path"]).relative_to(repo)) or "."
    except ValueError:
        shown = row["path"]
    removed = " — removed" if row.get("removed") else ""
    archive = f" (scratch archived to {row['archive']})" if row.get("archive") else ""
    return (f"- {shown} [{row.get('branch') or 'detached'}] age {_age(row.get('age_seconds'))}, "
            f"{_size(row.get('size_bytes'))}: {row.get('verdict')} ({row.get('reason')}){removed}{archive}")


async def worktree_command(ctx: Any) -> str:
    from . import worktrees

    orch = ctx.orch
    try:
        argv = shlex.split(ctx.args or "")
    except ValueError:
        return WORKTREE_USAGE
    action = argv.pop(0).lower() if argv else "status"
    session = _session(orch)
    if action == "status":
        record = await asyncio.to_thread(worktrees.session_tree_or_none, session)
        if not record:
            return "This conversation works in the project folder itself. /worktree new moves it into its own tree."
        return f"This conversation works in {record['path']} on {record.get('branch')}. /worktree off moves it back."
    repo, why = await asyncio.to_thread(_project, orch)
    if repo is None:
        return f"No worktree: {why}."
    if action == "list":
        try:
            rows = await asyncio.to_thread(worktrees.classify_all, repo)
        except worktrees.WorktreeRefused as exc:
            return str(exc)
        return "\n".join([f"Worktrees of {repo}:", *(_row(r, repo) for r in rows)])
    if action == "off":
        record = await asyncio.to_thread(worktrees.session_tree_or_none, session)
        if not record:
            return "This conversation is not in a worktree."
        await asyncio.to_thread(worktrees.set_session_tree, session, None)
        logger.info("session %s left worktree %s", session[:80], record.get("path"))
        return (f"This conversation is back in the project folder. The tree {record['path']} is kept; "
                "/worktree prune reclaims it once it is clean and pushed.")
    refusal = worktrees.write_refusal(session_id=session)
    if refusal is not None:
        return f"Nothing changed: {refusal}."
    if action == "new":
        return await _new(orch, session, repo, argv)
    if action == "prune":
        apply, max_age = False, 0.0
        while argv:
            word = argv.pop(0)
            if word == "--apply":
                apply = True
            elif word == "--max-age" and argv:
                try:
                    max_age = max(0.0, float(argv.pop(0)))
                except ValueError:
                    return WORKTREE_USAGE
            else:
                return WORKTREE_USAGE
        try:
            report = await asyncio.to_thread(worktrees.prune, repo, min_age_seconds=max_age * 3600,
                                             apply=apply)
        except worktrees.WorktreeRefused as exc:
            return str(exc)
        head = (f"Reclaimed {report['removed']} tree(s):" if apply
                else "What /worktree prune --apply would do (nothing was removed):")
        return "\n".join([head, *(_row(r, repo) for r in report["trees"])])
    return WORKTREE_USAGE


async def _new(orch: Any, session: str, repo: Path, argv: list[str]) -> str:
    from . import worktrees

    name, base = None, "HEAD"
    while argv:
        word = argv.pop(0)
        if word == "--from" and argv:
            base = argv.pop(0)
        elif name is None:
            name = word
        else:
            return WORKTREE_USAGE
    name = name or time.strftime("s-%Y%m%d-%H%M%S")
    if not worktrees.valid_name(name):
        return "A worktree name is letters, digits, dots, dashes and underscores (at most 64)."
    existing = await asyncio.to_thread(worktrees.session_tree_or_none, session)
    if existing:
        return f"This conversation already works in {existing['path']}. /worktree off first."
    path, branch = repo / worktrees.TREES_DIR / name, f"nerva/{name}"
    try:
        tree = await asyncio.to_thread(worktrees.create, repo, path, branch, base=base)
    except (worktrees.WorktreeRefused, ValueError, RuntimeError) as exc:
        return f"No worktree was made: {exc}"
    await asyncio.to_thread(worktrees.set_session_tree, session, {
        "path": tree.path, "repo": str(repo), "branch": branch, "base": tree.head,
        "created_at": time.time()})
    logger.info("session %s moved into worktree %s", session[:80], tree.path)
    return (f"This conversation now works in its own tree: {tree.path} on {branch} "
            f"(from {base}). From the next message its file tools and project context are there. "
            "/worktree off moves it back.")


async def opportunistic_reclaim(orch: Any, *, authorizer: Any = None, now: float | None = None,
                                force: bool = False) -> dict | None:
    """The autonomy tick's reclaim (H474): at most hourly, only with
    ``autonomy.worktree_auto_reclaim`` on, the approval mode not off, no e-stop, and — kernel on —
    a ``file.write`` grant. Returns the prune report, or None when it did not run."""
    global _last_reclaim
    from . import worktrees

    getter = getattr(orch, "get_setting", None)
    if not callable(getter) or getter("autonomy.worktree_auto_reclaim", False) is not True:
        return None
    ts = time.time() if now is None else now
    if not force and ts - _last_reclaim < RECLAIM_INTERVAL_SECONDS:
        return None
    try:
        from .autonomy.mode import describe

        if describe(orch, "jarvis")["effective"] in ("off", "unknown"):
            return None
    except Exception:  # noqa: BLE001
        return None
    _last_reclaim = ts
    repo, _why = await asyncio.to_thread(_project, orch)
    if repo is None:
        return None
    refusal = worktrees.write_refusal(authorizer=authorizer, title="Reclaim clean, pushed git worktrees",
                                      payload={"path": str(repo / worktrees.TREES_DIR), "operation": "reclaim"})
    if refusal is not None:
        logger.info("worktree reclaim skipped: %s", refusal)
        return None
    try:
        hours = float(getter("autonomy.worktree_reclaim_max_age_hours", DEFAULT_RECLAIM_MAX_AGE_HOURS))
    except (TypeError, ValueError):
        hours = float(DEFAULT_RECLAIM_MAX_AGE_HOURS)
    try:
        report = await asyncio.to_thread(worktrees.prune, repo, min_age_seconds=max(1.0, hours) * 3600,
                                         apply=True)
    except Exception:  # noqa: BLE001
        logger.warning("worktree reclaim failed", exc_info=True)
        return None
    if report.get("removed"):
        logger.info("worktree reclaim removed %d tree(s) under %s", report["removed"], repo)
    return report


def _delegation_line(row: dict) -> str:
    goal = " ".join(str(row.get("goal") or "").split())[:90]
    flags = []
    if row.get("stalled_at") and row.get("status") == "running":
        flags.append("stalled")
    if row.get("background"):
        flags.append("background")
    tail = f" [{', '.join(flags)}]" if flags else ""
    return f"- {row.get('spawn_id')} ({row.get('kind')}) {row.get('status')}{tail}: {goal}"


def _delivery(row: dict) -> str:
    result = row.get("result") if isinstance(row.get("result"), dict) else {}
    lines = [f"{row.get('spawn_id')} — {row.get('kind')} — {row.get('status')}: "
             + " ".join(str(row.get("goal") or "").split())[:120]]
    if row.get("status") == "done":
        lines.append(str(result.get("output") or "").strip()[:4000] or "(no text)")
    else:
        lines.append(f"error: {result.get('error') or 'failed'} {str(result.get('detail') or '')[:300]}".strip())
    tree = result.get("worktree") if isinstance(result.get("worktree"), dict) else row.get("worktree")
    if isinstance(tree, dict) and tree.get("branch") and tree.get("kept"):
        files = ", ".join(tree.get("changed_files") or [])[:300]
        lines.append(f"Its work is kept on branch {tree['branch']} ({tree.get('path')})"
                     + (f"; it changed: {files}. Re-read those before relying on earlier copies." if files else "."))
    return "\n".join(lines)


async def delegations_command(ctx: Any) -> str:
    orch = ctx.orch
    manager = getattr(orch, "subagents", None)
    queue = getattr(orch, "autonomy_queue", None)
    action = (ctx.args or "").strip().lower() or "list"
    if action == "list":
        if queue is None or not hasattr(queue, "delegation_list"):
            return "No delegation record on this hub."
        rows = await asyncio.to_thread(queue.delegation_list, limit=15)
        if not rows:
            return "No sub-agent has run yet."
        undelivered = sum(1 for r in rows if r.get("delivered_at") is None and r.get("status") != "running")
        tail = f"\n{undelivered} finished result(s) not received yet: /delegations collect." if undelivered else ""
        return "\n".join(["Recent sub-agents (newest first):", *(_delegation_line(r) for r in rows)]) + tail
    if action == "collect":
        if manager is None:
            return "Sub-agents are not available on this hub."
        rows = await manager.claim_completions("owner:/delegations")
        if not rows:
            return "Nothing new: every finished sub-agent result has been received."
        return ("Sub-agent results (each shown once; their words are their own account):\n\n"
                + "\n\n".join(_delivery(r) for r in rows))
    return DELEGATIONS_USAGE


__all__ = ["DELEGATIONS_USAGE", "WORKTREE_USAGE", "delegations_command", "opportunistic_reclaim",
           "worktree_command"]
