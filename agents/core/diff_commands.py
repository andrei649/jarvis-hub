"""Owner-only, local working-tree diff for the H084 /diff command."""

from __future__ import annotations

import asyncio
import re
import shlex

from . import review_command, worktrees
from .channels.outbound_safety import sanitize_text
from .diff_paths import validate_paths

CAPTURE_BYTES = 192_000
SESSION_CAPTURE_BYTES = 65_536
DISPLAY_CHARS = 3_000
DISPLAY_LINES = 60
UNTRACKED_NAMES = 15
_WITHHELD = "A reply could not be checked before sending, so it was withheld."
_FENCE_RUNS = re.compile(r"`+|~+")
USAGE = "Usage: /diff [staged|all|session] [--stat] [--] path... (paths optional)."
_MODES = {"staged": "staged", "--staged": "staged", "cached": "staged",
          "--cached": "staged", "all": "all", "--all": "all", "head": "all",
          "session": "session"}
_STAT_OPTIONS = frozenset({"--stat", "stat"})
_OPTIONS = frozenset(_MODES) | _STAT_OPTIONS


def _options(args: str) -> tuple[str, bool, tuple[str, ...]] | None:
    """Parse only a bounded option prefix, then literal project-relative paths."""
    if not isinstance(args, str):
        return None
    try:
        if len(args.encode("utf-8")) > 2048:
            return None
    except UnicodeEncodeError:
        return None
    # Reject these before shlex can turn a backslash into an escape or conceal a
    # control character inside a quoted token.
    if "\\" in args or any(ord(char) < 32 or ord(char) == 127 for char in args):
        return None
    try:
        words = shlex.split(args)
    except ValueError:
        return None
    mode, stat_only, literal, saw_separator = "working", False, False, False
    paths: list[str] = []
    for word in words:
        option = word.casefold()
        if not literal and word == "--":
            if paths:
                return None
            literal = saw_separator = True
            continue
        if not literal and option in _OPTIONS:
            if paths:
                return None
            if option in _STAT_OPTIONS:
                stat_only = True
            elif mode != "working" and mode != _MODES[option]:
                return None
            else:
                mode = _MODES[option]
            continue
        if not literal and word.startswith("-"):
            return None
        paths.append(word)
    if saw_separator and not paths:
        return None
    validated = validate_paths(tuple(paths))
    return (mode, stat_only, validated) if validated is not None else None


def _fenced(text: str) -> str:
    """Keep diff source inside the fence used by both Markdown and media_delivery."""
    # The media directive parser treats *any* fence-like line as a toggle, even
    # when Markdown would leave it inside a longer fence. Escape these lines.
    lines = [("\\" + line if line.lstrip().startswith(("```", "~~~")) else line)
             for line in text.split("\n")]
    body = "\n".join(lines)
    runs = {"`": 0, "~": 0}
    for match in _FENCE_RUNS.finditer(body):
        marker = match.group()[0]
        runs[marker] = max(runs[marker], len(match.group()))
    marker = min(runs, key=lambda mark: (runs[mark], mark))
    # Escaping all content lines that look like a closer makes a bounded fence
    # safe even if the diff contains a very long run of either marker.
    fence = marker * max(3, min(8, runs[marker] + 1))
    return f"{fence}diff\n{body}\n{fence}"


def _display(text: str) -> str:
    lines = text.splitlines()
    clipped = "\n".join(lines[:DISPLAY_LINES])
    truncated = len(lines) > DISPLAY_LINES or len(clipped) > DISPLAY_CHARS
    clipped = clipped[:DISPLAY_CHARS]
    if truncated:
        clipped += "\n[diff display truncated; use /diff --stat for a summary]"
    return _fenced(clipped)


def _untracked(top, pathspecs: tuple[str, ...] = ()) -> str:
    args = ["ls-files", "--others", "--exclude-standard", "-z"]
    if pathspecs:
        args.extend(("--", *pathspecs))
    result = worktrees.run_git(top, *args, limit=CAPTURE_BYTES)
    if result.stderr == "git output exceeded its bound":
        return "Untracked names omitted: the listing exceeded its safety bound."
    if result.returncode:
        return "Untracked names unavailable: local Git listing failed."
    names = [name for name in result.stdout.split("\x00") if name]
    if not names:
        return "No untracked files."
    shown = []
    for raw in names[:UNTRACKED_NAMES]:
        clean = sanitize_text(raw)
        if clean == _WITHHELD:
            return _WITHHELD
        # Git -z protects name boundaries; make embedded newlines visible as
        # characters, so a filename cannot create another reply line.
        clean = clean.replace("\n", "\\n").replace("\t", "\\t")
        shown.append("+ " + (clean[:200] or "(unprintable)"))
    extra = len(names) - UNTRACKED_NAMES
    if extra > 0:
        shown.append(f"+{extra} more untracked names not shown")
    return "Untracked names (contents not read):\n" + _fenced("\n".join(shown))


def _read_diff(orch, mode: str, stat_only: bool, paths: tuple[str, ...] = ()) -> str:
    """All filesystem and Git reads run on the worker, with fixed output messages."""
    if mode == "session":
        return _read_session_diff(orch, stat_only, paths)
    root = review_command.project_root(orch)
    if root is None:
        return "No project folder is set for this session. Set llm.project_dir or use /worktree."
    top = worktrees.repo_root(root)
    if top is None:
        return "The current project is not a Git repository."
    try:
        worktrees.require_plain(worktrees.main_repo(top) or top)
    except worktrees.WorktreeRefused:
        return "Git diff refused: this repository's configuration is not permitted for local Git reads."

    pathspecs: tuple[str, ...] = ()
    if paths:
        # The project may be a trusted subdirectory of the checkout. Git runs
        # from the checkout top, so prepend that fixed prefix before constructing
        # literal pathspecs. Do not resolve or normalize any user path.
        try:
            prefix = root.resolve().relative_to(top.resolve()).parts
        except ValueError:
            return "Git diff refused: project scope changed."
        pathspecs = tuple(":(literal)" + "/".join((*prefix, path)) for path in paths)

    args = ["diff", "--no-color", "--no-textconv", "--no-ext-diff",
            "--ignore-submodules=all"]
    if mode == "staged":
        args.append("--cached")
    elif mode == "all":
        args.append("HEAD")
    if stat_only:
        args.append("--stat")
    if pathspecs:
        args.extend(("--", *pathspecs))
    result = worktrees.run_git(top, *args, limit=CAPTURE_BYTES)
    if result.stderr == "git output exceeded its bound":
        return "Git diff is too large to display safely. No diff was shown."
    if result.returncode:
        return "Git diff failed. Check the project and local Git state; no diff was shown."
    # run_git's capture bound applies before decoding, then the *whole* captured
    # successful diff is redacted before display clipping. Otherwise a long known
    # secret could have its prefix sent before its full value reached the redactor.
    clean = sanitize_text(result.stdout)
    if clean == _WITHHELD:
        return _WITHHELD
    if result.stdout and not clean:
        return "The diff could not be displayed after redaction."
    names = _untracked(top, pathspecs)
    if names == _WITHHELD:
        return _WITHHELD
    label = {"working": "Unstaged tracked changes", "staged": "Staged tracked changes",
             "all": "Staged and unstaged tracked changes against HEAD"}[mode]
    if stat_only:
        label += " (stat)"
    if paths:
        label += " in selected paths"
    tracked = (f"{label}:\n{_display(clean)}" if clean else
               f"No tracked changes for {mode} mode" + (" in selected paths." if paths else "."))
    return tracked + "\n" + names


def _read_session_diff(orch, stat_only: bool, paths: tuple[str, ...] = ()) -> str:
    """Compare the earliest retained full-project terminal checkpoint off-loop."""
    from .env_config import env_flag
    from .environments.local_transport import default_roots
    from .file_checkpoint_history import HISTORY_SUPPORTED, FileCheckpointHistory
    from .file_tools import FileScope, FileScopeError, SnapshotStore

    if not HISTORY_SUPPORTED or not env_flag("JARVIS_TERMINAL_CHECKPOINTS"):
        return "Project checkpoint comparison is disabled or unsupported; nothing was read."
    project = review_command.project_root(orch)
    if project is None:
        return "No project folder is set for this session. Set llm.project_dir or use /worktree."
    try:
        permitted = FileScope([*FileScope.from_env().roots, *default_roots()])
        root = permitted.resolve(str(project))
        if not root.is_dir():
            return "Project checkpoint comparison is unavailable: the project folder is not a directory."
        exact_scope = FileScope([root])
        if exact_scope.resolve(str(root)) != root:
            return "Project checkpoint comparison refused: project scope changed."
    except (FileScopeError, OSError, ValueError):
        return "Project checkpoint comparison refused: project is outside the allowed file scope."
    options = {"stat_only": stat_only, "max_bytes": SESSION_CAPTURE_BYTES}
    if paths:
        options["paths"] = paths
    result = FileCheckpointHistory(SnapshotStore(), exact_scope).session_diff(root, **options)
    if type(result) is not dict or result.get("ok") is not True:
        reason = result.get("reason") if type(result) is dict else None
        if reason in {"no_baseline", "no_comparable_baseline", "baseline_unavailable"}:
            return ("No comparable retained full-project terminal checkpoint baseline is available; "
                    "/diff session cannot infer a clean project.")
        if reason in {"output_overflow", "too_large", "diff_too_large", "scan_limit"}:
            return "Project checkpoint comparison exceeded its read or output bound; no diff was shown."
        if reason in {"root_changed", "scope_changed"}:
            return "Project checkpoint comparison refused: project root changed."
        return "Project checkpoint comparison is unavailable or failed integrity checks; no diff was shown."
    baseline = result.get("baseline")
    excluded = result.get("excluded")
    diff = result.get("diff")
    stat = result.get("stat")
    if (result.get("approximate") is not True or type(baseline) is not str
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", baseline)
            or type(excluded) is not int or not 0 <= excluded <= 100_000
            or type(diff) is not str or type(stat) is not str
            or len(diff.encode("utf-8")) > SESSION_CAPTURE_BYTES
            or len(stat.encode("utf-8")) > SESSION_CAPTURE_BYTES):
        return "Project checkpoint comparison is unavailable or failed integrity checks; no diff was shown."
    # Empty-file or mode-only changes can have a nonzero stat and no textual
    # hunk. Show the stat in the normal view too; never infer "no changes" from
    # an empty diff body. Sanitize both together before the display cut.
    body = stat if stat_only else (
        "Stat:\n" + stat + "\nDiff:\n" +
        (diff if diff else "[No textual diff lines; see the change counts above.]"))
    # The entire bounded comparator output, including a possibly secret-bearing
    # file name, must pass the outbound gate before the display cut.
    clean = sanitize_text(body)
    if clean == _WITHHELD:
        return _WITHHELD
    if body and not clean:
        return "The project checkpoint diff could not be displayed after redaction."
    header = (f"Approximate project checkpoint comparison from earliest retained full-project "
              f"terminal checkpoint {baseline} to current files. It may predate this chat or "
              f"postdate its start after pruning; it covers that checkpoint's project scope, "
              f"not all file-tool history. Excluded paths: {excluded}.")
    if paths:
        header += " Showing selected paths."
    if not clean:
        return "The project checkpoint diff could not be displayed after redaction."
    return header + "\n" + _display(clean)


async def diff_command(ctx) -> str:
    """Show only this session's project diff, without model, tool or network work."""
    if not ctx.principal.admin:
        return "Only the owner can view the project diff."
    raw_text = getattr(ctx, "raw_text", "")
    if (not isinstance(raw_text, str) or "\\" in raw_text
            or any(ord(char) < 32 or ord(char) == 127 for char in raw_text)):
        return USAGE
    options = _options(ctx.args)
    if options is None:
        return USAGE
    try:
        return await asyncio.to_thread(_read_diff, ctx.orch, *options)
    except OSError:
        if options[0] == "session":
            return "Project checkpoint comparison is unavailable; no diff was shown."
        return "Git diff failed. Check the project and local Git state; no diff was shown."
    except Exception:
        return "The project diff is unavailable; no diff was shown."
