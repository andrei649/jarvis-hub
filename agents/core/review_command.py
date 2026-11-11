"""``/review`` — an independent, read-only reviewer of the work in this conversation (H404).

Hermes's ``/review`` (``agent/review_engine.py``) spawns a fresh-context reviewer
sub-agent over what the recent conversation presented. Nerva adopts that module for its
**text** — the reviewer goal, the conversation snapshot and the briefing
(``snapshot_recent_messages``, ``build_review_task``; vendored byte-for-byte, imports
rewritten) — and does the dispatch itself, differently in one essential way:

**The reviewer is read-only.** Hermes's reviewer is a full-privilege child. Nerva's is
spawned through the one spawn gate (:meth:`SubAgentManager.spawn`) with ``read_only``:

* its tools are the child's allowlist (the blocked capabilities already removed:
  no delegation, memory write, channel send, skill authoring or clarify) narrowed to
  the tools that declared themselves ``read_only`` — no write, no send, no terminal;
* it runs under the kernel's read-only floor (``kernel.plan_mode.read_only_floor``):
  the Action Kernel denies every non-read action kind, and the tool front door refuses
  every gated tool and every tool not declared read-only, before preflight or intake —
  so even a tool that reached it some other way is refused;
* its tools are at most ``file_read`` / ``file_list`` / ``file_search``, confined to the
  checkout it reviews (no folder, no tools): nothing networked, no session or memory
  search, so nothing it reads — private code, untrusted text — has a way out;
* it gets no worktree (it writes nothing); the diff and every message of the snapshot are
  handed to it as fenced data with fence delimiters defanged, collected by the hub with
  hardened git (``agents.core.worktrees``).

What it reviews: the last exchanges of this conversation (Hermes's snapshot), plus the
project's diff — the working tree against HEAD by default, ``--branch <name>`` for that
branch against its merge base with HEAD. The project is the session's own worktree
(``/worktree new``) when it has one, else ``llm.project_dir``.

Gates: owner only (``tier=ADMIN``); refused while the emergency stop is engaged, the
kill switch is halted or spawning is paused (the spawn gate), and while the approval
mode is ``off``. Allowed in plan mode — the reviewer only reads. By default it runs in
the background and its findings are delivered once (``/delegations``); ``--wait`` waits
for them, within the sub-agent time limit.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shlex
from pathlib import Path
from typing import Any

logger = logging.getLogger("jarvis.review_command")

USAGE = ("Usage: /review [focus] — review this conversation's work and the project's uncommitted diff; "
         "/review --branch <name> [focus] — review a branch against HEAD; add --wait to wait for the findings")
DIFF_MAX_CHARS = 40_000
RUNTIME_NOTE = (
    "Runtime note (Nerva): you are a read-only reviewer. Tools that write, send, run commands "
    "or change anything are refused here; use the read tools to open files, and rely on the diff "
    "below, which the hub collected for you. Do not try to run tests: say what should be run and "
    "what you could only read. Report findings as a numbered list (severity, file:line, the "
    "problem, the fix), then a one-line verdict."
)


def project_root(orch: Any) -> Path | None:
    """The session's own worktree when it has one, else ``llm.project_dir``."""
    from . import worktrees

    session = getattr(orch, "session_id", None) or "default"
    record = worktrees.session_tree_or_none(session)
    if record and record.get("path") and Path(record["path"]).is_dir():
        return Path(record["path"])
    getter = getattr(orch, "get_setting", None)
    raw = getter("llm.project_dir", "") if callable(getter) else ""
    return Path(raw) if isinstance(raw, str) and raw.strip() and Path(raw).is_dir() else None


def review_folder(root: Path | None) -> Path | None:
    """The checkout the reviewer may read (its file tools are confined to it), or None."""
    from . import worktrees

    return worktrees.repo_root(root) if root is not None else None


def collect_diff(root: Path | None, branch: str | None = None) -> tuple[str, str]:
    """``(label, diff text)`` for the review, read with hardened git; ``("", reason)``
    when there is none to give. Blocking."""
    from . import worktrees

    if root is None:
        return "", "no project folder is set (llm.project_dir), so only the conversation is reviewed"
    top = worktrees.repo_root(root)
    if top is None:
        return "", "the project folder is not a git repository, so only the conversation is reviewed"
    try:
        worktrees.require_plain(worktrees.main_repo(top) or top)
    except worktrees.WorktreeRefused as exc:
        return "", str(exc)
    common = ("--no-color", "--no-textconv", "--no-ext-diff", "--ignore-submodules=all")
    if branch:
        worktrees.check_branch(branch)
        if worktrees.run_git(top, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").returncode:
            return "", f"there is no local branch {branch}"
        label = f"branch {branch} against its merge base with HEAD"
        result = worktrees.run_git(top, "diff", *common, f"HEAD...refs/heads/{branch}", limit=DIFF_MAX_CHARS * 4)
    else:
        label = "uncommitted changes against HEAD"
        result = worktrees.run_git(top, "diff", *common, "HEAD", limit=DIFF_MAX_CHARS * 4)
    text = result.stdout if result.returncode == 0 else ""
    if not text.strip():
        return "", f"there are no {label}"
    if len(text) > DIFF_MAX_CHARS:
        text = text[:DIFF_MAX_CHARS] + f"\n[... diff cut at {DIFF_MAX_CHARS} characters ...]"
    return label, text


_FENCE_MARKER = re.compile(r"<<\s*(END\s+)?UNTRUSTED", re.IGNORECASE)
#: Hermes's brief says the review is delivered back into the conversation; in Nerva it is
#: delivered once through /delegations (or straight to the owner with --wait). The
#: vendored bytes stay as they are: the sentence is replaced here, in the composed brief.
_UPSTREAM_DELIVERY = ("Your review is delivered back into that conversation, addressed to "
                      "the primary agent and its user.")
NERVA_DELIVERY = ("Your review is delivered to the owner once, through /delegations collect (or "
                  "directly, when they asked to wait for it).")


def neutralise(text: str) -> str:
    """*text* with every fence delimiter defanged (``<<UNTRUSTED``, ``<<END UNTRUSTED>>``,
    in any case or spacing), so data can never close the fence it is put in."""
    return _FENCE_MARKER.sub(lambda m: "< <" + m.group(0)[2:].lstrip(), str(text or ""))


def fenced(text: str, source: str) -> str:
    from .security.quarantine import fence_text

    return fence_text(neutralise(text), source=source)


def build_task(messages: list, focus: str, diff_label: str, diff: str) -> tuple[str, str]:
    """``(goal, the reviewer's whole brief)`` from Hermes's text plus Nerva's note and diff.
    Every message of the snapshot and the diff go in as fenced data, delimiters defanged."""
    from types import SimpleNamespace

    from agents.vendor.hermes.agent import review_engine

    snapshot = [{"role": item["role"], "text": fenced(item["text"], "conversation")}
                for item in review_engine.snapshot_recent_messages(messages)]
    skills = review_engine.collect_parent_loaded_skills(SimpleNamespace(), messages)
    goal, context = review_engine.build_review_task(snapshot, focus, skills)
    context = context.replace(_UPSTREAM_DELIVERY, NERVA_DELIVERY)
    parts = [context, "", RUNTIME_NOTE]
    if diff_label and diff:
        parts += ["", f"The diff under review ({diff_label}), as data:", fenced(diff, "git_diff")]
    return goal, "\n".join(parts)


def _approval_mode_off(orch: Any) -> bool:
    try:
        from .autonomy.mode import describe

        return describe(orch, "jarvis")["effective"] in ("off", "unknown")
    except Exception:  # noqa: BLE001 — unreadable is not "on"
        return True


async def review_command(ctx: Any) -> str:
    orch = ctx.orch
    try:
        argv = shlex.split(ctx.args or "")
    except ValueError:
        return USAGE
    branch, wait, words = None, False, []
    while argv:
        word = argv.pop(0)
        if word == "--branch" and argv:
            branch = argv.pop(0)
        elif word == "--wait":
            wait = True
        elif word in ("-h", "--help", "help"):
            return USAGE
        else:
            words.append(word)
    focus = " ".join(words)[:500]
    manager = getattr(orch, "subagents", None)
    if manager is None:
        return "The reviewer is not available on this hub (sub-agents are off)."
    if _approval_mode_off(orch):
        return "The approval mode is off: nothing a machine decides runs, so no reviewer was started."
    memory = getattr(orch, "memory", None)
    session = getattr(orch, "session_id", None)
    messages: list = []
    if memory is not None and session:
        try:
            messages = list(await memory.get_history(session))
        except Exception:  # noqa: BLE001
            messages = []
    if messages and messages[-1].get("role") == "user" and str(messages[-1].get("content", "")).lstrip().startswith("/review"):
        messages = messages[:-1]
    try:
        label, diff = await asyncio.to_thread(collect_diff, project_root(orch), branch)
    except ValueError:
        return "That is not a valid branch name; nothing was reviewed."
    except Exception:  # noqa: BLE001
        logger.warning("/review: the diff could not be read", exc_info=True)
        label, diff = "", "the diff could not be read"
    if not label and not any(m.get("role") in ("user", "assistant") for m in messages if isinstance(m, dict)):
        return f"Nothing to review yet: the conversation is empty and {diff}."
    goal, task = build_task(messages, focus, label, diff if label else "")
    folder = await asyncio.to_thread(review_folder, project_root(orch))
    kwargs = {"agent": "jarvis", "parent": "review", "read_only": True, "kind": "review",
              "confine": str(folder) if folder is not None else None}
    note = "" if label else f" ({diff})"
    if wait:
        out = await manager.spawn(task, **kwargs)
        return format_findings(out, note)
    out = await manager.spawn_background(task, **kwargs)
    if out.get("status") != "running":
        return format_findings(out, note)
    return (f"{goal}: a read-only reviewer started ({out['id']}){note}. Its findings arrive once — "
            "read them with /delegations.")


def format_findings(out: dict, note: str = "") -> str:
    if "status" not in out:
        reason = out.get("reason") or "refused"
        detail = out.get("detail") or ""
        return f"No reviewer was started: {reason}{(' — ' + detail) if detail else ''}."
    result = out.get("result") if isinstance(out.get("result"), dict) else {}
    if out.get("status") != "done":
        return (f"The reviewer did not finish ({out.get('status')}: {result.get('error') or 'failed'})"
                f"{note}.")
    text = str(result.get("output") or "").strip()
    return f"Review findings{note} (the reviewer's own account; verify what matters):\n{text[:12000]}"


__all__ = ["DIFF_MAX_CHARS", "RUNTIME_NOTE", "USAGE", "build_task", "collect_diff", "format_findings",
           "project_root", "review_command"]
