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
notice in its title), on the write result the model reads, and on the result of a
skill install or generation. The owner's switch is ``security.code_guidance``.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

logger = logging.getLogger("jarvis.code_guidance")

SETTING = ("security", "code_guidance")
MAX_SCAN_BYTES = 1_000_000
MAX_FINDINGS = 20
MAX_FILES = 200

PY = frozenset({".py", ".pyw"})
JS = frozenset({".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".mts", ".cts"})
GO = frozenset({".go"})
HTML = frozenset({".html", ".htm"})
SHELLISH = frozenset({".sh", ".bash", ".zsh", ".env"})
_COMMENT_PREFIX = {**dict.fromkeys(PY | SHELLISH, ("#",)), **dict.fromkeys(JS | GO, ("//",))}


@dataclass(frozen=True)
class Rule:
    id: str
    message: str
    pattern: re.Pattern[str]
    exts: frozenset[str]


def _r(rule_id: str, message: str, pattern: str, exts: Iterable[str], flags: int = 0) -> Rule:
    return Rule(rule_id, message, re.compile(pattern, flags), frozenset(exts))


RULES: tuple[Rule, ...] = (
    # ── unsafe deserialization ──────────────────────────────────────────────────
    _r("py-pickle-load", "pickle/dill/joblib/marshal load runs code from the data: never load bytes you did not create",
       r"(?<![\w.])(?:pickle|cPickle|_pickle|dill|joblib|marshal)\.loads?\s*\(", PY),
    _r("py-yaml-load", "yaml.load without SafeLoader can build arbitrary Python objects: use yaml.safe_load",
       r"(?<![\w.])yaml\.(?:unsafe_load\s*\(|load\s*\((?![^)\n]*Loader\s*=\s*(?:yaml\.)?C?SafeLoader))", PY),
    _r("py-torch-load", "torch.load without weights_only=True unpickles the file: pass weights_only=True",
       r"(?<![\w.])torch\.load\s*\((?![^)\n]*weights_only\s*=\s*True)", PY),
    # ── command and code injection ──────────────────────────────────────────────
    _r("py-os-system", "os.system/os.popen run a shell: use subprocess with a list of arguments",
       r"(?<![\w.])os\.(?:system|popen)\s*\(", PY),
    _r("py-shell-true", "shell=True hands the string to a shell: pass a list of arguments instead",
       r"\bshell\s*=\s*True\b", PY),
    _r("py-eval", "eval/exec run text as code: parse the data instead (ast.literal_eval, json)",
       r"(?<![\w.])(?:eval|exec)\s*\(", PY),
    _r("py-sql-fstring", "SQL built with an f-string or % is injectable: use query parameters",
       r"\.execute(?:many)?\s*\(\s*(?:f[\"']|[\"'][^\"'\n]*[\"']\s*%)", PY),
    _r("py-mktemp", "tempfile.mktemp is racy: use mkstemp or NamedTemporaryFile",
       r"(?<![\w.])tempfile\.mktemp\s*\(", PY),
    _r("js-eval", "eval runs text as code: parse the data instead (JSON.parse)",
       r"(?<![\w.$])eval\s*\(", JS),
    _r("js-new-function", "new Function(...) compiles text into code: avoid building code from data",
       r"\bnew\s+Function\s*\(", JS),
    _r("js-child-exec", "child_process.exec runs a shell: use execFile/spawn with an argument list",
       r"(?:\bchild_process\s*\.\s*exec(?:Sync)?|\bexecSync)\s*\(", JS),
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
       r"(?<![\w.$])(?:crypto\.)?createCipher\s*\(", JS),
    _r("py-tls-verify-off", "verify=False turns off certificate checks: anyone on the path can read the traffic",
       r"\bverify\s*=\s*False\b", PY),
    _r("py-ssl-unverified", "an unverified SSL context turns off certificate checks",
       r"\bssl\._create_unverified_context\b|\bCERT_NONE\b|check_hostname\s*=\s*False", PY),
    _r("js-tls-off", "rejectUnauthorized: false / NODE_TLS_REJECT_UNAUTHORIZED=0 turns off certificate checks",
       r"\brejectUnauthorized\s*:\s*false\b|\bNODE_TLS_REJECT_UNAUTHORIZED\s*=\s*[\"']?0\b", JS | SHELLISH),
    _r("go-tls-insecure", "InsecureSkipVerify: true turns off certificate checks",
       r"\bInsecureSkipVerify\s*:\s*true\b", GO),
    _r("py-weak-hash-password", "md5/sha1 are not password hashes: use hashlib.scrypt, bcrypt or argon2",
       r"(?<![\w.])hashlib\.(?:md5|sha1)\s*\([^)\n]*pass", PY, re.IGNORECASE),
    # ── XML ─────────────────────────────────────────────────────────────────────
    _r("py-xxe", "an XML parser that resolves entities or loads DTDs can read local files (XXE)",
       r"\bresolve_entities\s*=\s*True\b|\bload_dtd\s*=\s*True\b|\bno_network\s*=\s*False\b", PY),
    _r("js-xxe", "noent/dtdload in an XML parser resolves external entities (XXE)",
       r"\b(?:noent|dtdload)\s*:\s*true\b", JS),
    # ── supply chain ────────────────────────────────────────────────────────────
    _r("html-script-no-sri", "a remote <script> without integrity= runs whatever that host serves: add Subresource Integrity",
       r"<script\b(?![^>]*\bintegrity\s*=)[^>]*\bsrc\s*=\s*[\"']?(?:https?:)?//", HTML, re.IGNORECASE),
)
WORKFLOW_RULE_ID = "gha-expression-injection"
WORKFLOW_MESSAGE = ("${{ github.event.* }} inside a run: step is pasted into the shell before it runs: "
                    "pass it through env: and quote the variable")
_WORKFLOW_EXPR = re.compile(r"\$\{\{\s*github\.event\.", re.IGNORECASE)
_RUN_KEY = re.compile(r"^(\s*)(?:-\s+)?run\s*:\s*(.*)$")


def enabled() -> bool:
    """The owner's switch (on by default); an unreadable store keeps it on."""
    from .settings_db import get_value

    try:
        return get_value(*SETTING, True) is not False
    except Exception:
        return True


def _ext(path: str) -> str:
    return PurePosixPath(str(path).replace("\\", "/")).suffix.lower()


def _is_workflow(path: str) -> bool:
    norm = str(path).replace("\\", "/").lower()
    return "/.github/workflows/" in f"/{norm}" and _ext(norm) in (".yml", ".yaml")


def _workflow_findings(text: str) -> list[dict]:
    out: list[dict] = []
    block_indent: int | None = None
    for number, line in enumerate(text.splitlines(), 1):
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
    return out


def scan(path: str, content: str) -> list[dict]:
    """The findings for one file: ``[{"rule", "line", "message"}]``, at most
    :data:`MAX_FINDINGS`, in line order. Only the first :data:`MAX_SCAN_BYTES` are read."""
    if not isinstance(content, str) or not content:
        return []
    text = content[:MAX_SCAN_BYTES]
    if _is_workflow(path):
        return _workflow_findings(text)[:MAX_FINDINGS]
    ext = _ext(path)
    rules = [rule for rule in RULES if ext in rule.exts]
    if not rules:
        return []
    comment = _COMMENT_PREFIX.get(ext, ())
    out: list[dict] = []
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        if comment and stripped.startswith(comment):
            continue
        for rule in rules:
            if rule.pattern.search(line):
                out.append({"rule": rule.id, "line": number, "message": rule.message})
                if len(out) >= MAX_FINDINGS:
                    return out
    return out


def labels(path: str, content: str) -> dict[str, Any] | None:
    """The approval-card labels for a write (never a ``class``: the approval stays
    bound to what H506 classes it as), or None when nothing was found or the switch is
    off."""
    if not enabled():
        return None
    found = scan(path, content)
    if not found:
        return None
    ids = ", ".join(f"{f['rule']}@{f['line']}" for f in found)
    return {
        "code_warnings": ids[:200],
        "code_warning_count": len(found),
        "notice": f"code warnings: {len(found)} risky pattern(s)",
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
    """Findings for every file under a skill folder: ``[{"path", "rule", "line",
    "message"}]`` (paths relative to ``root``), bounded."""
    from pathlib import Path

    base = Path(root)
    if not enabled() or not base.is_dir():
        return []
    out: list[dict] = []
    seen = 0
    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        seen += 1
        if seen > max_files:
            break
        rel = path.relative_to(base).as_posix()
        if not _is_workflow(rel) and not any(_ext(rel) in rule.exts for rule in RULES):
            continue
        try:
            with open(path, "rb") as handle:
                text = handle.read(MAX_SCAN_BYTES).decode("utf-8", errors="replace")
        except OSError:
            continue
        for finding in scan(rel, text):
            out.append({"path": rel, **finding})
            if len(out) >= MAX_FINDINGS:
                return out
    return out


__all__ = [
    "MAX_FINDINGS", "RULES", "SETTING", "WORKFLOW_RULE_ID", "enabled", "labels", "result_fields",
    "scan", "scan_tree",
]
