"""The coding posture's workspace snapshot: a read-only look at the project's git state.

Hermes puts a snapshot of the repository into the coding agent's system prompt at the
start of a session (``coding_context.build_coding_workspace_block``): root, branch and
upstream with ahead/behind, linked worktree, dirty counts, recent commits and the
project's verify loop. This is Nerva's version.

**A repository's config can make git run code** (a ``filter.<x>.clean``/``process`` on a
re-timestamped file, ``log.showSignature`` with ``gpg.program``, a lazy fetch of a partial
clone over ``core.sshCommand``, a ``config.worktree`` or an included file carrying any of
those). So git runs here only for a repository whose own config is plain, judged by an
**allowlist**: the repository's config (local and worktree scopes, read with
``git config --list --show-scope`` and no ``--includes``, so an include is a key like any
other) may hold only the keys in :data:`ALLOWED_KEYS` / :data:`ALLOWED_SUBSECTION_KEYS`
(core format and line-ending flags, remotes' url/fetch, branches' upstream, user name and
e-mail, a few pull/push defaults). Any other key — a filter, an include, an extension
(``worktreeConfig``, ``partialClone``), a ``gpg.*`` program, ``core.sshCommand``, an alias,
a diff or merge driver — withholds the git part of the snapshot, and the snapshot says
which key did. Reading the config list itself runs nothing.

**Defence in depth** for the reads that then run: no system or global config, no terminal
prompt, no optional locks (``status`` does not write the index), no lazy fetch
(``GIT_NO_LAZY_FETCH``), every transport refused (``protocol.allow=never``), hooks,
fsmonitor, signatures, ``gpg.*`` programs, ``core.sshCommand`` and the external diff
overridden on the command line, submodules ignored, ``--no-textconv --no-ext-diff``, one
deadline for the whole snapshot (:data:`TOTAL_BUDGET`) and output read in a stream and
cut at :data:`MAX_OUTPUT`. These are fixed reads of the owner's project, never a command
the model or the project chose, so they are not ``terminal.exec``; nothing runs while the
e-stop is engaged.

**Data, not instructions.** Branch names are shown only when they are plain
(``[A-Za-z0-9._/@+-]``); a commit subject or a recipe string only when the
prompt-injection scanner passes it, single-line, printable and capped; the block sits in
the untrusted-data fence.

**Pinned per session**, as in Hermes: probed once for a session and project, then replayed
on every later prompt build, so the stable prompt tier stays cached. The header tells the
model to re-check with git before relying on it.
"""
from __future__ import annotations

import logging
import os
import re
import selectors
import subprocess  # nosec B404 - fixed read-only git argv, see module doc
import threading
import time
from collections import OrderedDict
from pathlib import Path

logger = logging.getLogger("jarvis.verify.workspace")

GIT_TIMEOUT = 3.0
TOTAL_BUDGET = 6.0
MAX_OUTPUT = 64_000
MAX_SESSIONS = 256
RECENT_COMMITS = 3
HEADER = "Workspace (snapshot at session start; re-check with git before acting on it):"
_SAFE_REF = re.compile(r"[A-Za-z0-9._/@+-]{1,120}")
_cache: OrderedDict[tuple[str, str], str] = OrderedDict()
_lock = threading.Lock()

#: Plain keys (``section.variable``, lower-case) a repository's config may hold.
ALLOWED_KEYS = frozenset({
    "core.repositoryformatversion", "core.filemode", "core.bare", "core.logallrefupdates",
    "core.ignorecase", "core.precomposeunicode", "core.symlinks", "core.autocrlf", "core.eol",
    "core.safecrlf", "core.quotepath", "core.checkstat", "core.trustctime",
    "extensions.objectformat", "init.defaultbranch", "user.name", "user.email",
    "pull.rebase", "pull.ff", "push.default", "push.autosetupremote", "fetch.prune", "color.ui",
})
#: ``section.<subsection>.variable`` keys allowed for any subsection.
ALLOWED_SUBSECTION_KEYS = frozenset({
    ("remote", "url"), ("remote", "fetch"), ("remote", "pushurl"), ("remote", "tagopt"), ("remote", "prune"),
    ("branch", "remote"), ("branch", "merge"), ("branch", "rebase"), ("branch", "pushremote"),
    ("branch", "description"),
})
_SCOPES = frozenset({"local", "worktree"})


def _env() -> dict[str, str]:
    return {
        "PATH": os.defpath + os.pathsep + "/usr/local/bin",
        "LC_ALL": "C",
        "HOME": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_PROTOCOL_FROM_USER": "0",
        "GIT_PAGER": "cat",
    }


_BASE = (
    "-c", f"core.hooksPath={os.devnull}", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
    "-c", "diff.external=", "-c", "core.pager=cat", "-c", "log.showSignature=false",
    "-c", "gpg.program=false", "-c", "gpg.ssh.program=false", "-c", "gpg.x509.program=false",
    "-c", "gpg.openpgp.program=false", "-c", "core.sshCommand=false", "-c", "protocol.allow=never",
    "-c", "credential.helper=", "--no-pager",
)


class _Budget:
    def __init__(self, seconds: float = TOTAL_BUDGET) -> None:
        self.deadline = time.monotonic() + seconds

    def left(self) -> float:
        return min(GIT_TIMEOUT, self.deadline - time.monotonic())


def git(root: Path, *args: str, budget: _Budget | None = None) -> str | None:
    """Run one fixed read-only git command in *root*; its stdout (cut at
    :data:`MAX_OUTPUT`, read as a stream), or None on any failure or past the deadline."""
    budget = budget or _Budget(GIT_TIMEOUT)
    if budget.left() <= 0:
        return None
    argv = ["git", *_BASE, *args]
    try:
        proc = subprocess.Popen(argv, cwd=str(root), env=_env(), stdin=subprocess.DEVNULL,  # nosec B603 - fixed argv, no shell
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        return None
    output = bytearray()
    try:
        assert proc.stdout is not None  # nosec B101 - Popen with stdout=PIPE always sets it
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            while True:
                left = budget.left()
                if left <= 0 or len(output) > MAX_OUTPUT:
                    proc.kill()
                    proc.wait()
                    return None if left <= 0 else output[:MAX_OUTPUT].decode("utf-8", errors="replace")
                if not selector.select(left):
                    continue
                chunk = os.read(proc.stdout.fileno(), 65536)
                if not chunk:
                    break
                output.extend(chunk)
        code = proc.wait(timeout=max(0.05, budget.left()))
    except (OSError, subprocess.SubprocessError):
        proc.kill()
        proc.wait()
        return None
    finally:
        if proc.stdout is not None:
            proc.stdout.close()
    if code != 0:
        return None
    return output[:MAX_OUTPUT].decode("utf-8", errors="replace")


def config_refusal(root: Path, budget: _Budget | None = None) -> str | None:
    """Why the repository's config is not plain (the first key outside the allowlist,
    case preserved), or None when every key is allowed. An unreadable config refuses."""
    listed = git(root, "config", "--list", "--show-scope", "-z", budget=budget)
    if listed is None:
        return "its git config could not be read"
    fields = listed.split("\0")
    # ``-z --show-scope``: ``<scope>\0<key>\n<value>\0`` per entry.
    for scope, entry in zip(fields[0::2], fields[1::2], strict=False):
        key = entry.split("\n", 1)[0]
        if scope == "command":
            continue        # Nerva's own -c overrides
        if scope not in _SCOPES:
            return f"a {scope or 'unknown'}-scope setting ({key[:60]})"
        first, _, tail = key.partition(".")
        sub, _, var = tail.rpartition(".")
        section, var = first.lower(), var.lower()
        if not sub and f"{section}.{var}" in ALLOWED_KEYS:
            continue
        if sub and (section, var) in ALLOWED_SUBSECTION_KEYS:
            continue
        shown = key if _SAFE_REF.fullmatch(key) else f"{section}.….{var}"
        return f"its git config sets {shown[:80]}"
    return None


def _ref(value: str) -> str:
    return value if _SAFE_REF.fullmatch(value or "") else "(name withheld)"


def safe_text(text: object, cap: int = 72) -> str | None:
    """*text* as one printable line, capped, or None when it is empty, carries a fence
    marker or the prompt-injection scanner flags it."""
    from agents.core.security.quarantine import (
        _FENCE_MARKER_TOKENS,
        detect_injection_normalized,
        strip_invisible,
    )

    if not isinstance(text, str):
        return None
    raw = strip_invisible(text)
    if "\n" in raw.strip() or "\r" in raw.strip() or any(token in raw for token in _FENCE_MARKER_TOKENS):
        return None
    clean = "".join(ch for ch in raw if ch.isprintable()).strip()
    if not clean or len(clean) > cap or "`" in clean or detect_injection_normalized(clean):
        return None
    return clean


def _subject(text: str) -> str | None:
    return safe_text(text[:200].strip()[:72] if isinstance(text, str) else text, 72)


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
            fields = line.split(maxsplit=2)
            if len(fields) >= 2 and len(fields[1]) == 2:
                counts["staged"] += fields[1][0] != "."
                counts["modified"] += fields[1][1] != "."
        elif line.startswith(("u ", "? ")):
            counts["conflicts" if line[0] == "u" else "untracked"] += 1
    return branch, counts


def git_lines(root: Path) -> list[str]:
    """The git part of the snapshot ([] outside a repository or when git is unavailable)."""
    from agents.core import estop

    if estop.is_engaged():
        return ["- Git: not read while the emergency stop is engaged"]
    budget = _Budget()
    refused = config_refusal(root, budget)
    if refused is not None:
        return [f"- Git: not read ({refused}; Nerva runs git only on a repository whose config "
                "cannot make it run a program)"]
    lines: list[str] = []
    status = git(root, "status", "--porcelain=v2", "--branch", "--ignore-submodules=all",
                 "--untracked-files=normal", "--no-renames", budget=budget)
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
                   "--ignore-submodules=all", budget=budget)
        if stat and stat.strip():
            lines.append(f"- Uncommitted diff: {' '.join(stat.split())[:160]}")
    git_dir = git(root, "rev-parse", "--path-format=absolute", "--git-dir", budget=budget)
    common = git(root, "rev-parse", "--path-format=absolute", "--git-common-dir", budget=budget)
    if git_dir and common and Path(git_dir.strip()).resolve() != Path(common.strip()).resolve():
        lines.append("- Worktree: linked (git state is shared with the primary checkout; changes here do "
                     "not touch it)")
    recent = git(root, "log", f"-{RECENT_COMMITS}", "--no-color", "--no-show-signature", "--pretty=%h %s",
                 budget=budget)
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
        # A committed .hermes/environment.json is the project's text: sanitised like a subject.
        name = safe_text(getattr(recipe, "name", None), 60) or "(name withheld)"
        start_cmd = getattr(recipe, "start", None)
        start = ""
        if start_cmd:
            shown = safe_text(start_cmd, 120)
            start = (f"; start command {shown!r} (shown, never run by /verify)" if shown
                     else "; start command withheld")
        lines.append(f"- Run recipe: {name}{start}")
    if evidence_status:
        lines.append(f"- Verification at session start: {evidence_status}")
    return "\n".join(lines)


def session_block(session: str, root: Path, builder) -> str:
    """The pinned snapshot for (*session*, *root*): built once by *builder()*, replayed after."""
    key = (session_key(session), str(root))
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


def session_key(session: object) -> str:
    """The cache key for a session id: an empty one is the hub's ``default`` session."""
    return str(session or "") or "default"


def cached(session: str, root: Path) -> str | None:
    with _lock:
        return _cache.get((session_key(session), str(root)))


def forget(session: str | None = None) -> None:
    with _lock:
        if session is None:
            _cache.clear()
        else:
            for key in [k for k in _cache if k[0] == session_key(session)]:
                del _cache[key]


__all__ = ["ALLOWED_KEYS", "ALLOWED_SUBSECTION_KEYS", "HEADER", "cached", "config_refusal", "forget", "git", "git_lines",
           "parse_status", "safe_text", "session_block", "session_key", "snapshot"]
