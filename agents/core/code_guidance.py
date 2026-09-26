"""H507 — warn when code the agent writes contains a known-dangerous pattern.

Hermes runs a table of code-pattern rules over what the model writes and hands the
findings back, so the model (and the owner reading the approval) sees
"``pickle.load`` on data you did not create is remote code execution" before the file
is used. Nerva had no such check: ``file_write`` returned only ok/path/bytes, the
approval card only named instruction files (H506), and a generated or installed skill
was checked for its contract and signature, never for what its code does.

This module is that table: about twenty-five rules, each scoped to the file types it
applies to, with guards so the common false positives do not fire (``model.eval()`` is
not ``eval``; ``yaml.load(..., Loader=SafeLoader)`` is fine; a whole-line comment is not
code). It covers unsafe deserialization, command and code injection, SQL built from an
f-string, XSS sinks, crypto and TLS footguns, XXE, a remote ``<script>`` without
Subresource Integrity, and a GitHub Actions ``run:`` step that interpolates
``${{ github.event.* }}``.

It only ever warns. Nothing is refused, rewritten or delayed: the findings ride on
the ``file_write`` approval card (``code_warnings`` / ``code_warning_count`` and a
notice in its title) and its ``approval_required`` answer, which the tool loop's pause
reply names (a gated call ends the model's turn); on the approved write's result; and
on the result of a skill install or of ``skill_propose``. Every scan is linear in what
it reads and bounded in time: a scan cut short says so. The owner's switch is
``security.code_guidance``.
"""
from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

logger = logging.getLogger("jarvis.code_guidance")

SETTING = ("security", "code_guidance")
MAX_SCAN_BYTES = 1_000_000
MAX_FINDINGS = 20
MAX_FILES = 200
#: How far a guarded call's arguments are read (across lines), and how many calls on one
#: line are looked at: a guard costs a bounded read, never one per character of a line.
MAX_CALL_CHARS = 400
MAX_CALLS_PER_LINE = 8
#: Wall-clock bounds for one file and for a whole skill folder. A scan runs on the hub's
#: event loop (the approval card is labelled before it exists), so no crafted file may
#: hold it; a scan cut short by these or by MAX_SCAN_BYTES ends with a finding that says
#: so, rather than reading as clean.
SCAN_SECONDS = 0.5
TREE_SECONDS = 2.0
INCOMPLETE_RULE_ID = "scan-incomplete"
INCOMPLETE_MESSAGE = "not checked from here on: a size or time limit cut the scan short"

PY = frozenset({".py", ".pyw"})
JS = frozenset({".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".mts", ".cts"})
GO = frozenset({".go"})
HTML = frozenset({".html", ".htm"})
SHELLISH = frozenset({".sh", ".bash", ".zsh", ".env"})
_COMMENT_PREFIX = {**dict.fromkeys(PY | SHELLISH, ("#",)), **dict.fromkeys(JS | GO, ("//",))}
#: Shell files known by name alone: their suffix is empty (``.env``), or ``.local``.
_SHELL_DOTFILES = frozenset({".env", ".bashrc", ".bash_profile", ".zshrc", ".zprofile", ".profile"})


@dataclass(frozen=True)
class Rule:
    id: str
    message: str
    pattern: re.Pattern[str]
    exts: frozenset[str]
    # Read in what the match opens (a call's arguments, across lines) or, for a match
    # that is not a call, in the match itself: ``needs`` must be there and ``unless``
    # must not, or it is no finding.
    needs: re.Pattern[str] | None = None
    unless: re.Pattern[str] | None = None
    # The rule applies only to a file that also matches this (it imports the module).
    within: re.Pattern[str] | None = None


def _r(rule_id: str, message: str, pattern: str, exts: Iterable[str], flags: int = 0, *,
       needs: str | None = None, unless: str | None = None, within: str | None = None) -> Rule:
    def _compiled(source: str | None) -> re.Pattern[str] | None:
        return None if source is None else re.compile(source, flags)

    return Rule(rule_id, message, re.compile(pattern, flags), frozenset(exts),
                _compiled(needs), _compiled(unless), _compiled(within))


RULES: tuple[Rule, ...] = (
    # ── unsafe deserialization ──────────────────────────────────────────────────
    _r("py-pickle-load", "pickle/dill/joblib/marshal load runs code from the data: never load bytes you did not create",
       r"(?<![\w.])(?:pickle|cPickle|_pickle|dill|joblib|marshal)\.loads?\s*\(", PY),
    _r("py-yaml-load", "yaml.load without SafeLoader can build arbitrary Python objects: use yaml.safe_load",
       r"(?<![\w.])yaml\.(?:unsafe_)?load\s*\(", PY, unless=r"Loader\s*=\s*(?:yaml\.)?C?SafeLoader\b"),
    _r("py-torch-load", "torch.load without weights_only=True unpickles the file: pass weights_only=True",
       r"(?<![\w.])torch\.load\s*\(", PY, unless=r"\bweights_only\s*=\s*True\b"),
    # ── command and code injection ──────────────────────────────────────────────
    _r("py-os-system", "os.system/os.popen run a shell: use subprocess with a list of arguments",
       r"(?<![\w.])os\.(?:system|popen)\s*\(", PY),
    _r("py-shell-true", "shell=True hands the string to a shell: pass a list of arguments instead",
       r"\bshell\s*=\s*True\b", PY),
    _r("py-eval", "eval/exec run text as code: parse the data instead (ast.literal_eval, json)",
       r"(?<![\w.])(?<!def\s)(?:eval|exec)\s*\(", PY),
    _r("py-sql-fstring", "SQL built with an f-string or % is injectable: use query parameters",
       r"\.execute(?:many)?\s*\(", PY, needs=r"\A\s*(?:f[\"']|[\"'][^\"'\n]*[\"']\s*%)"),
    _r("py-mktemp", "tempfile.mktemp is racy: use mkstemp or NamedTemporaryFile",
       r"(?<![\w.])tempfile\.mktemp\s*\(", PY),
    _r("js-eval", "eval runs text as code: parse the data instead (JSON.parse)",
       r"(?<![\w.$])eval\s*\(", JS),
    _r("js-new-function", "new Function(...) compiles text into code: avoid building code from data",
       r"\bnew\s+Function\s*\(", JS),
    _r("js-child-exec", "child_process.exec runs a shell: use execFile/spawn with an argument list",
       r"(?:(?:\bchild_process|\brequire\s*\(\s*[\"'](?:node:)?child_process[\"']\s*\))\s*\.\s*exec(?:Sync)?"
       r"|\bexecSync)\s*\(", JS),
    _r("js-exec-imported", "exec from child_process runs a shell: use execFile/spawn with an argument list",
       r"(?<![\w.$])exec\s*\(", JS, within=r"[\"'](?:node:)?child_process[\"']"),
    _r("go-exec-shell", "exec.Command(\"sh\", \"-c\", ...) runs a shell: call the program with its arguments",
       r"\bexec\.Command(?:Context)?\s*\((?:[^,()\n]+,\s*)?\"(?:/bin/)?(?:sh|bash|zsh|cmd(?:\.exe)?|powershell)\"", GO),
    # ── XSS sinks ────────────────────────────────────────────────────────────────
    _r("js-inner-html", "assigning innerHTML/outerHTML renders markup: use textContent or sanitise first",
       r"\.(?:inner|outer)HTML\s*(?:\+)?=(?!=)", JS | HTML),
    _r("js-document-write", "document.write inserts raw markup into the page",
       r"(?<![\w.$])document\.write(?:ln)?\s*\(", JS | HTML),
    _r("react-dangerous-html", "dangerouslySetInnerHTML renders raw markup: sanitise it first",
       r"\bdangerouslySetInnerHTML\b", JS),
    # ── crypto and TLS footguns ─────────────────────────────────────────────────
    _r("crypto-ecb", "ECB mode leaks patterns in the data: use an authenticated mode (GCM)",
       r"\bMODE_ECB\b|\bmodes\.ECB\s*\(|[\"']aes-\d+-ecb[\"']", PY | JS | GO, re.IGNORECASE),
    _r("js-create-cipher", "crypto.createCipher derives the key with no IV: use createCipheriv",
       r"(?<![\w$])createCipher\s*\(", JS),
    _r("py-tls-verify-off", "verify=False turns off certificate checks: anyone on the path can read the traffic",
       r"\bverify\s*=\s*False\b", PY),
    _r("py-ssl-unverified", "an unverified SSL context turns off certificate checks",
       r"\bssl\._create_unverified_context\b|\bCERT_NONE\b|check_hostname\s*=\s*False", PY),
    _r("js-tls-off", "rejectUnauthorized: false / NODE_TLS_REJECT_UNAUTHORIZED=0 turns off certificate checks",
       r"\brejectUnauthorized\s*:\s*false\b|\bNODE_TLS_REJECT_UNAUTHORIZED\s*=\s*[\"']?0\b", JS | SHELLISH),
    _r("go-tls-insecure", "InsecureSkipVerify: true turns off certificate checks",
       r"\bInsecureSkipVerify\s*:\s*true\b", GO),
    _r("py-weak-hash-password", "md5/sha1 are not password hashes: use hashlib.scrypt, bcrypt or argon2",
       r"(?<![\w.])hashlib\.(?:md5|sha1)\s*\(", PY, re.IGNORECASE, needs=r"pass"),
    # ── XML ─────────────────────────────────────────────────────────────────────
    _r("py-xxe", "an XML parser that resolves entities or loads DTDs can read local files (XXE)",
       r"\bresolve_entities\s*=\s*True\b|\bload_dtd\s*=\s*True\b|\bno_network\s*=\s*False\b", PY),
    _r("js-xxe", "noent/dtdload in an XML parser resolves external entities (XXE)",
       r"\b(?:noent|dtdload)\s*:\s*true\b", JS),
    # ── supply chain ────────────────────────────────────────────────────────────
    _r("html-script-no-sri", "a remote <script> without integrity= runs whatever that host serves: add Subresource Integrity",
       r"<script\b[^>]{0,2000}", HTML, re.IGNORECASE,
       needs=r"\bsrc\s*=\s*[\"']?(?:https?:)?//", unless=r"\bintegrity\s*="),
)
WORKFLOW_RULE_ID = "gha-expression-injection"
WORKFLOW_MESSAGE = ("${{ github.event.* }} inside a run: step is pasted into the shell before it runs: "
                    "pass it through env: and quote the variable")
_WORKFLOW_EXPR = re.compile(r"\$\{\{\s*github\.event\.", re.IGNORECASE)
# The key's own column is the block's: for ``- run: |`` that is past the dash, so the
# step's other keys (env:, with:, if:) end the block.
_RUN_KEY = re.compile(r"^(\s*(?:-\s+)?)run\s*:\s*(.*)$")
_PARENS = re.compile(r"[()]")


def enabled() -> bool:
    """The owner's switch (on by default); an unreadable store keeps it on, and safe
    mode puts an owner's off back on."""
    from .safe_mode import get_value

    try:
        return get_value(*SETTING, True) is not False
    except Exception:
        return True


def _ext(path: str) -> str:
    name = PurePosixPath(str(path).replace("\\", "/"))
    lowered = name.name.lower()
    if lowered in _SHELL_DOTFILES or lowered.startswith(".env."):
        return ".sh"
    return name.suffix.lower()


def _is_workflow(path: str) -> bool:
    norm = str(path).replace("\\", "/").lower()
    return "/.github/workflows/" in f"/{norm}" and _ext(norm) in (".yml", ".yaml")


def _incomplete(line: int) -> dict:
    return {"rule": INCOMPLETE_RULE_ID, "line": line, "message": INCOMPLETE_MESSAGE}


def _workflow_findings(lines: list[str], deadline: float) -> tuple[list[dict], int | None]:
    out: list[dict] = []
    block_indent: int | None = None
    for number, line in enumerate(lines, 1):
        if time.monotonic() > deadline:
            return out, number
        indent = len(line) - len(line.lstrip())
        if block_indent is not None and line.strip() and indent <= block_indent:
            block_indent = None
        match = _RUN_KEY.match(line)
        if match:
            value = match.group(2).strip()
            if value[:1] in ("|", ">"):
                block_indent = len(match.group(1))
            elif _WORKFLOW_EXPR.search(value):
                out.append({"rule": WORKFLOW_RULE_ID, "line": number, "message": WORKFLOW_MESSAGE})
            continue
        if block_indent is not None and _WORKFLOW_EXPR.search(line):
            out.append({"rule": WORKFLOW_RULE_ID, "line": number, "message": WORKFLOW_MESSAGE})
    return out, None


def _call_args(text: str, start: int) -> str:
    """The arguments of the call whose ``(`` ends at ``start``: up to the parenthesis
    that closes it, across lines, at most :data:`MAX_CALL_CHARS`."""
    window = text[start:start + MAX_CALL_CHARS]
    depth = 0
    for paren in _PARENS.finditer(window):
        if paren.group() == "(":
            depth += 1
        elif depth:
            depth -= 1
        else:
            return window[:paren.start()]
    return window


def _guarded(rule: Rule, line: str, text: str, start: int) -> bool:
    """Whether a match of a guarded rule on this line survives its guard."""
    calls = 0
    for match in rule.pattern.finditer(line):
        seen = match.group()
        if seen.endswith("("):
            calls += 1
            if calls > MAX_CALLS_PER_LINE:
                return False
            seen = _call_args(text, start + match.end())
        if rule.needs is not None and not rule.needs.search(seen):
            continue
        if rule.unless is not None and rule.unless.search(seen):
            continue
        return True
    return False


def _rule_findings(rules: list[Rule], comment: tuple[str, ...], text: str, lines: list[str],
                   deadline: float) -> tuple[list[dict], int | None]:
    out: list[dict] = []
    start = 0
    for number, line in enumerate(lines, 1):
        if time.monotonic() > deadline:
            return out, number
        offset, start = start, start + len(line) + 1
        if comment and line.lstrip().startswith(comment):
            continue
        for rule in rules:
            if rule.pattern.search(line) is None:
                continue
            if (rule.needs is not None or rule.unless is not None) and not _guarded(rule, line, text, offset):
                continue
            out.append({"rule": rule.id, "line": number, "message": rule.message})
            if len(out) >= MAX_FINDINGS:
                return out, None
    return out, None


def scan(path: str, content: str, *, deadline: float | None = None, cut: bool = False) -> list[dict]:
    """The findings for one file: ``[{"rule", "line", "message"}]``, at most
    :data:`MAX_FINDINGS`, in line order. Only the first :data:`MAX_SCAN_BYTES` are read,
    for at most :data:`SCAN_SECONDS` (or until ``deadline``); a scan cut short by either
    (or handed a ``cut`` file) ends with a ``scan-incomplete`` finding at the first line
    it did not finish."""
    if not isinstance(content, str) or not content:
        return []
    workflow = _is_workflow(path)
    ext = _ext(path)
    rules = [rule for rule in RULES if ext in rule.exts]
    if not workflow and not rules:
        return []
    if deadline is None:
        deadline = time.monotonic() + SCAN_SECONDS
    # Lines as Python and a shell count them: CRLF and CR end one; a form feed or a
    # U+2028 inside a line does not (str.splitlines would split at those too).
    text = content[:MAX_SCAN_BYTES].replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if workflow:
        out, stopped = _workflow_findings(lines, deadline)
    else:
        rules = [rule for rule in rules if rule.within is None or rule.within.search(text)]
        out, stopped = _rule_findings(rules, _COMMENT_PREFIX.get(ext, ()), text, lines, deadline)
    if stopped is None and (cut or len(content) > MAX_SCAN_BYTES) and len(out) < MAX_FINDINGS:
        stopped = len(lines)
    if stopped is not None:
        out.append(_incomplete(stopped))
    return out[:MAX_FINDINGS]


def labels(path: str, content: str, *aliases: str) -> dict[str, Any] | None:
    """The approval-card labels for a write (never a ``class``: the approval stays
    bound to what H506 classes it as), or None when nothing was found or the switch is
    off. ``aliases`` are other names of the same file (what a symlink or a ``./``
    spelling resolves to): each kind of file among them is scanned, so the card says what
    the write's result will."""
    if not enabled():
        return None
    found: list[dict] = []
    kinds: set[tuple[bool, str]] = set()
    for name in (path, *aliases):
        kind = (_is_workflow(name), _ext(name))
        if kind not in kinds:
            kinds.add(kind)
            found += [f for f in scan(name, content) if f not in found]
    if not found:
        return None
    found = sorted(found, key=lambda f: f["line"])[:MAX_FINDINGS]
    ids = ", ".join(f"{f['rule']}@{f['line']}" for f in found)
    risky = sum(f["rule"] != INCOMPLETE_RULE_ID for f in found)
    notice = f"code warnings: {risky} risky pattern(s)"
    if risky < len(found):
        notice = f"{notice}, not fully scanned" if risky else "code not fully scanned"
    return {
        "code_warnings": ids[:200],
        "code_warning_count": len(found),
        "notice": notice,
    }


def result_fields(path: str, content: str) -> dict[str, Any]:
    """What the write result tells the model (empty when nothing was found)."""
    if not enabled():
        return {}
    found = scan(path, content)
    if not found:
        return {}
    return {
        "code_warnings": found,
        "code_guidance": "These are warnings, not refusals: the file was written. Fix each "
                         "pattern, or say why it is safe here.",
    }


def scan_tree(root: Any, *, max_files: int = MAX_FILES) -> list[dict]:
    """Findings for every code file under a skill folder: ``[{"path", "rule", "line",
    "message"}]`` (paths relative to ``root``), bounded. Only code files count toward
    ``max_files``; the file a bound stops at gets a ``scan-incomplete`` finding."""
    from pathlib import Path

    base = Path(root)
    if not enabled() or not base.is_dir():
        return []
    deadline = time.monotonic() + TREE_SECONDS
    out: list[dict] = []
    scanned = 0
    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(base).as_posix()
        if not _is_workflow(rel) and not any(_ext(rel) in rule.exts for rule in RULES):
            continue
        if scanned >= max_files or time.monotonic() > deadline:
            out.append({"path": rel, **_incomplete(1)})
            return out
        scanned += 1
        try:
            with open(path, "rb") as handle:
                data = handle.read(MAX_SCAN_BYTES + 1)
        except OSError:
            continue
        text = data[:MAX_SCAN_BYTES].decode("utf-8", errors="replace")
        found = scan(rel, text, deadline=min(deadline, time.monotonic() + SCAN_SECONDS),
                     cut=len(data) > MAX_SCAN_BYTES)
        for finding in found:
            out.append({"path": rel, **finding})
            if len(out) >= MAX_FINDINGS:
                return out
    return out


__all__ = [
    "INCOMPLETE_RULE_ID", "MAX_FINDINGS", "RULES", "SETTING", "WORKFLOW_RULE_ID", "enabled", "labels",
    "result_fields", "scan", "scan_tree",
]
