"""The coding posture's workspace snapshot: a read-only look at the project's git state.

Hermes puts a snapshot of the repository into the coding agent's system prompt at the
start of a session (``coding_context.build_coding_workspace_block``): root, branch and
upstream with ahead/behind, linked worktree, dirty counts, recent commits and the
project's verify loop. This is Nerva's version.

**Read-only, and hardened like the hub's other internal git reads** (``kanban/workspaces``):
a fixed executable and argv, no shell, no system or global git config, no terminal
prompt, no optional locks (``status`` does not refresh the index), hooks and fsmonitor
off, submodules ignored, ``--no-textconv --no-ext-diff``, a 3 s deadline and a bounded
output. A repository can still name a *filter* (``.gitattributes`` + ``filter.<x>.clean``
in ``.git/config``) that ``git status`` would run on a re-timestamped file; so the
repository's own config is read first, every filter it names gets an empty command, and
a config that includes another file (``include.path`` / ``includeIf``) withholds the
status and diff lines instead of running them half-hardened (Hermes does the same).
These are fixed reads of the owner's project, never a command the model or the project
chose, so they are not ``terminal.exec``; nothing runs while the e-stop is engaged.

**Data, not instructions.** Branch names are shown only when they are plain
(``[A-Za-z0-9._/@+-]``); a commit subject is shown only when the prompt-injection scanner
passes it, cut to 72 printable characters; the block sits in the untrusted-data fence.

**Pinned per session**, as in Hermes: probed once for a session and project, then replayed
on every later prompt build, so the stable prompt tier stays cached. The header tells the
model to re-check with git before relying on it.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess  # nosec B404 - fixed read-only git argv, see module doc
import threading
from collections import OrderedDict
from pathlib import Path

logger = logging.getLogger("jarvis.verify.workspace")

GIT_TIMEOUT = 3.0
MAX_OUTPUT = 64_000
MAX_SESSIONS = 256
RECENT_COMMITS = 3
HEADER = "Workspace (snapshot at session start; re-check with git before acting on it):"
_SAFE_REF = re.compile(r"[A-Za-z0-9._/@+-]{1,120}")
_cache: OrderedDict[tuple[str, str], str] = OrderedDict()
_lock = threading.Lock()


def _env() -> dict[str, str]:
    return {
        "PATH": os.defpath + os.pathsep + "/usr/local/bin",
        "LC_ALL": "C",
        "HOME": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PAGER": "cat",
    }


_BASE = ("-c", f"core.hooksPath={os.devnull}", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
         "-c", "diff.external=", "--no-pager")


def git(root: Path, *args: str, extra: tuple[str, ...] = ()) -> str | None:
    """Run one fixed read-only git command in *root*; stdout, or None on any failure."""
    argv = ["git", *_BASE, *extra, *args]
    try:
        proc = subprocess.run(argv, cwd=str(root), env=_env(), stdin=subprocess.DEVNULL,  # nosec B603 - fixed argv, no shell
                              capture_output=True, timeout=GIT_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout[:MAX_OUTPUT].decode("utf-8", errors="replace")


def filter_overrides(root: Path) -> tuple[str, ...] | None:
    """``-c`` overrides that empty every filter the repository's config names, or None when
    the config includes another file (then status is not run)."""
    out = git(root, "config", "--local", "--name-only", "--get-regexp", r"^(filter|include|includeif)\.")
    if out is None:
        # ``git config --get-regexp`` exits 1 when nothing matches: no filters, no includes.
        listed = git(root, "config", "--local", "--name-only", "--list")
        if listed is None:
            return None
        out = ""
    overrides: list[str] = []
    for key in out.splitlines():
        key = key.strip().lower()
        if key.startswith(("include.", "includeif.")):
            return None
        if key.startswith("filter."):
            name = key[len("filter."):].rsplit(".", 1)[0]
            for part in ("clean", "smudge", "process"):
                overrides += ["-c", f"filter.{name}.{part}="]
            overrides += ["-c", f"filter.{name}.required=false"]
    return tuple(overrides)


def _ref(value: str) -> str:
    return value if _SAFE_REF.fullmatch(value or "") else "(name withheld)"


def _subject(text: str) -> str | None:
    from agents.core.security.quarantine import detect_injection_normalized, strip_invisible

    clean = "".join(ch for ch in strip_invisible(text) if ch.isprintable()).strip()[:72]
    if not clean or detect_injection_normalized(clean):
        return None
    return clean


def parse_status(porcelain: str) -> tuple[dict[str, str], dict[str, int]]:
    """``git status --porcelain=v2 --branch`` → branch facts and counts (Hermes ``_parse_status``)."""
    branch: dict[str, str] = {}
    counts = {"staged": 0, "modified": 0, "untracked": 0, "conflicts": 0}
    for line in porcelain.splitlines():
        if line.startswith(("# branch.head", "# branch.upstream")):
            parts = line.split(maxsplit=2)
            if len(parts) == 3:
                branch[parts[1].removeprefix("branch.")] = parts[2]
        elif line.startswith("# branch.ab"):
            parts = line.split()
            if len(parts) == 4:
                branch["ahead"], branch["behind"] = parts[2].lstrip("+"), parts[3].lstrip("-")
        elif line.startswith(("1 ", "2 ")):
            xy = line.split(maxsplit=2)[1]
            counts["staged"] += xy[0] != "."
            counts["modified"] += xy[1] != "."
        elif line.startswith(("u ", "? ")):
            counts["conflicts" if line[0] == "u" else "untracked"] += 1
    return branch, counts


def git_lines(root: Path) -> list[str]:
    """The git part of the snapshot ([] outside a repository or when git is unavailable)."""
    from agents.core import estop

    if estop.is_engaged():
        return ["- Git: not read while the emergency stop is engaged"]
    lines: list[str] = []
    overrides = filter_overrides(root)
    if overrides is None:
        lines.append("- Status: not read (the repository's git config includes another file)")
    else:
        status = git(root, "status", "--porcelain=v2", "--branch", "--ignore-submodules=all",
                     "--untracked-files=normal", "--no-renames", extra=overrides)
        if status is not None:
            branch, counts = parse_status(status)
            head = branch.get("head", "")
            if head == "(detached)":
                lines.append("- Branch: (detached HEAD)")
            elif head:
                upstream = f" -> {_ref(branch['upstream'])}" if branch.get("upstream") else ""
                ahead, behind = branch.get("ahead", "0"), branch.get("behind", "0")
                ab = f" (ahead {int(ahead)}, behind {int(behind)})" if (
                    upstream and ahead.isdigit() and behind.isdigit() and (ahead, behind) != ("0", "0")) else ""
                lines.append(f"- Branch: {_ref(head)}{upstream}{ab}")
            dirty = [f"{n} {label}" for label, n in counts.items() if n]
            lines.append(f"- Status: {', '.join(dirty) if dirty else 'clean'}")
            stat = git(root, "diff", "HEAD", "--shortstat", "--no-textconv", "--no-ext-diff",
                       "--ignore-submodules=all", extra=overrides)
            if stat and stat.strip():
                lines.append(f"- Uncommitted diff: {' '.join(stat.split())[:160]}")
    git_dir = git(root, "rev-parse", "--path-format=absolute", "--git-dir")
    common = git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if git_dir and common and Path(git_dir.strip()).resolve() != Path(common.strip()).resolve():
        lines.append("- Worktree: linked (git state is shared with the primary checkout; changes here do "
                     "not touch it)")
    recent = git(root, "log", f"-{RECENT_COMMITS}", "--no-color", "--pretty=%h %s")
    if recent:
        shown = []
        for row in recent.splitlines():
            short, _, subject = row.partition(" ")
            if not re.fullmatch(r"[0-9a-f]{4,40}", short):
                continue
            safe = _subject(subject)
            shown.append(f"    {short} {safe}" if safe else f"    {short} (subject withheld)")
        if shown:
            lines.extend(["- Recent commits:", *shown])
    return lines


def snapshot(root: Path, *, git_repo: bool, facts=None, recipe=None, evidence_status: str | None = None) -> str:
    """The snapshot block for *root* (not fenced; :func:`session_block` fences it)."""
    lines = [HEADER, f"- Root: {root}"]
    if git_repo:
        lines.extend(git_lines(root))
    if facts is not None:
        if facts.manifests:
            managers = f" ({'/'.join(facts.package_managers)})" if facts.package_managers else ""
            lines.append(f"- Project: {', '.join(facts.manifests[:6])}{managers}")
        if facts.verify_commands:
            lines.append(f"- Verify: {'; '.join(facts.verify_commands)}")
        if facts.context_files:
            lines.append(f"- Context files: {', '.join(facts.context_files)}")
    if recipe is not None:
        start = f"; start `{recipe.start}` (shown, never run by /verify)" if getattr(recipe, "start", None) else ""
        lines.append(f"- Run recipe: {recipe.name}{start}")
    if evidence_status:
        lines.append(f"- Verification at session start: {evidence_status}")
    return "\n".join(lines)


def session_block(session: str, root: Path, builder) -> str:
    """The pinned snapshot for (*session*, *root*): built once by *builder()*, replayed after."""
    key = (str(session or ""), str(root))
    with _lock:
        cached = _cache.get(key)
        if cached is not None:
            _cache.move_to_end(key)
            return cached
    block = builder()
    with _lock:
        _cache[key] = block
        while len(_cache) > MAX_SESSIONS:
            _cache.popitem(last=False)
    return block


def cached(session: str, root: Path) -> str | None:
    with _lock:
        return _cache.get((str(session or ""), str(root)))


def forget(session: str | None = None) -> None:
    with _lock:
        if session is None:
            _cache.clear()
        else:
            for key in [k for k in _cache if k[0] == session]:
                del _cache[key]


__all__ = ["HEADER", "cached", "filter_overrides", "forget", "git", "git_lines", "parse_status", "session_block", "snapshot"]
