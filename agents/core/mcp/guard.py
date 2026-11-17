"""guard.py — refuse a malicious MCP server config or a poisoned tool definition (H555).

Two checks, both run on text a third party controls:

**Config validator** (:func:`config_findings`). A saved MCP server is a command Nerva
spawns as the owner's own user, and the saved list lives in settings storage, so a
hand-edited, imported or planted entry is a direct path to code execution. The validator
runs at **save** (``POST /api/admin/mcp`` and the catalog install refuse with
``config_refused``) and again at **spawn** (:meth:`MCPServer._connect_impl` refuses with
``config_refused:<finding>``, a permanent refusal the supervisor does not retry), so an
entry that reached storage some other way still never runs. It looks for shapes, not names:

* ``shell_egress`` — a shell or script interpreter handed inline code (``bash -c``,
  ``python -c``, ``node -e``, ``pwsh -Command`` …) that also reaches the network
  (``curl``, ``wget``, ``/dev/tcp``, a URL, ``urllib``, ``socket`` …): the
  download-and-run shape, which no real MCP server needs;
* ``encoded_command`` — PowerShell ``-EncodedCommand``, and inline code that decodes
  base64 before running it;
* ``network_tool_command`` — the command itself is a raw network tool (``curl``,
  ``wget``, ``nc``, ``socat`` …), never an MCP server;
* ``persistence_path`` — the command, its arguments, its environment or its working
  directory names an OS persistence location (``authorized_keys``, cron, shell rc files,
  ``pam_*.so``, systemd units, launchd agents, ``ld.so.preload`` …);
* ``loader_injection_env`` — an environment variable that loads code into the child or its
  children (``LD_PRELOAD``, ``DYLD_INSERT_LIBRARIES``, ``BASH_ENV``, ``PERL5OPT``,
  ``NODE_OPTIONS`` with ``--require``/``--import`` …);
* ``embedded_ssh_key`` — an SSH public key in the command, environment or headers.

Hermes also ships a hardcoded list of indicators from one incident (an SSH key prefix and
source addresses). Those values are not in the pinned vendored tree, so they are not
reproduced here; the shapes above cover the class of payload they came from.

**Tool-definition scan** (:func:`inspect_tool`). A tool's description and its input schema
go straight into the model's context, and a server can change them after the owner
approved it (a "rug pull" on reconnect). So every listing is:

* cleaned of invisible characters (zero-width marks, bidi overrides, Unicode TAG
  characters, private use, controls) in the description and in every ``description`` /
  ``title`` string inside the schema; an *identifier* the model sends back verbatim (a
  property name, an ``enum`` / ``const`` value) that carries one is not rewritten — the
  tool gets the ``invisible_identifier`` finding instead;
* scanned with ten pattern families over the description, the schema's descriptions and
  the annotations' title: the shared prompt-injection scan
  (``detect_injection_normalized``), role-tag injection, concealment from the owner,
  instructions about other tools, network commands, base64 decoding, ``exec``/``eval``,
  dangerous imports, credential paths and exfiltration to a URL.

A tool with any finding is **quarantined**: :meth:`MCPManager.model_tools` does not offer
it, and the admin list shows it under ``quarantined_tools`` with its findings and the
digest of its raw definition. The owner releases a false positive by adding
``"accepted_definitions": {"<tool>": "<digest>"}`` to the server's saved entry
(``mcp.servers``); the release names that exact definition, so a later change to the
description re-quarantines the tool.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from typing import Any

from agents.core.mcp.resources import clean_deep, clean_text
from agents.core.security.quarantine import detect_injection_normalized, strip_format_chars

# ── config validator ────────────────────────────────────────────────────────

_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "mksh", "fish", "csh", "tcsh",
                     "ash", "busybox", "cmd"})
_PY = re.compile(r"^(python|pypy)[0-9.]*w?$")
_INTERPRETER_FLAGS: dict[str, re.Pattern] = {
    # bash -c / -lc / -ic …; python -c / -Ic …
    "shell": re.compile(r"^-[A-Za-z]*c[A-Za-z]*$|^/c$", re.IGNORECASE),
    "python": re.compile(r"^-[A-Za-z]*c$"),
    "node": re.compile(r"^(-e|--eval|-p|--print|-pe)$"),
    "deno": re.compile(r"^eval$"),
    "bun": re.compile(r"^(-e|--eval|-p|--print)$"),
    "perl": re.compile(r"^-[A-Za-z]*[eE]$"),
    "ruby": re.compile(r"^-[A-Za-z]*e$"),
    "php": re.compile(r"^-r$"),
    "lua": re.compile(r"^-e$"),
    "rscript": re.compile(r"^-e$", re.IGNORECASE),
    "osascript": re.compile(r"^-e$"),
    "powershell": re.compile(r"^[-/](c|co|com|comm|comma|comman|command|e|ec|en|enc|enco|encod|"
                             r"encode|encoded|encodedc\w*|encodedcommand)$", re.IGNORECASE),
}
_INTERPRETER_OF = {
    "node": "node", "nodejs": "node", "deno": "deno", "bun": "bun",
    "perl": "perl", "ruby": "ruby", "php": "php", "lua": "lua", "luajit": "lua",
    "rscript": "rscript", "osascript": "osascript",
    "pwsh": "powershell", "powershell": "powershell",
}
_ENCODED_PS = re.compile(r"^[-/]e(n|nc|nco|ncod|ncode|ncoded\w*)?$", re.IGNORECASE)
_EGRESS = re.compile(
    r"\b(curl|wget|aria2c|netcat|ncat|socat|telnet|tftp)\b|\bnc\s+-?[a-z]|/dev/(tcp|udp)/"
    r"|\b(https?|ftp|wss?)://|\burllib\b|\burlopen\b|\brequests\.(get|post|put)\b"
    r"|\bhttp\.client\b|\bsocket\b|\bfetch\s*\(|\bnet\.connect\b|\bhttps?\.get\b"
    r"|invoke-(webrequest|restmethod)|\biwr\b|\birm\b|downloadstring|downloadfile"
    r"|net\.webclient|xmlhttp|bitsadmin|certutil\s+-urlcache",
    re.IGNORECASE,
)
_DECODE = re.compile(r"base64\s+(-d|--decode|-D)|\bb64decode\b|\batob\s*\(|frombase64string"
                     r"|\bbase64\.decode|codecs\.decode\([^)]*base64", re.IGNORECASE)
_NETWORK_TOOLS = frozenset({"curl", "wget", "nc", "ncat", "netcat", "socat", "telnet", "tftp",
                            "aria2c"})
_PERSISTENCE = re.compile(
    r"authorized_keys2?\b|/etc/cron|\bcrontab\b|/var/spool/cron|/etc/anacrontab"
    r"|(^|[/\\~])\.(bashrc|bash_profile|bash_login|profile|zshrc|zprofile|zshenv|zlogin"
    r"|kshrc|cshrc|tcshrc|config/fish/config\.fish)\b"
    r"|\bpam_[A-Za-z0-9_]+\.so\b|/etc/pam\.d\b|/etc/systemd/|\.config/systemd/"
    r"|/(usr/)?lib/systemd/system/|\bsystemctl\b|\.config/autostart\b|/etc/xdg/autostart"
    r"|Library/Launch(Agents|Daemons)|/etc/rc\.local|/etc/rc\.d/|/etc/init\.d/"
    r"|/etc/profile(\.d)?\b|/etc/environment\b|ld\.so\.preload|/etc/sudoers"
    r"|\\CurrentVersion\\Run\b|schtasks\b",
    re.IGNORECASE,
)
_LOADER_ENV = frozenset({"LD_PRELOAD", "LD_AUDIT", "DYLD_INSERT_LIBRARIES", "DYLD_LIBRARY_PATH",
                         "DYLD_FRAMEWORK_PATH", "BASH_ENV", "ENV", "PROMPT_COMMAND", "PERL5OPT",
                         "PERL5DB", "RUBYOPT", "PYTHONSTARTUP", "PYTHONINSPECT",
                         "JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "GIT_SSH_COMMAND"})
_NODE_LOADER = re.compile(r"(^|\s)(--require|-r|--import|--loader|--experimental-loader)\b")
_SSH_KEY = re.compile(r"\b(ssh-(rsa|ed25519|dss)|ecdsa-sha2-nistp\d+|sk-ssh-ed25519@openssh\.com)"
                      r"\s+AAAA[0-9A-Za-z+/]{20,}")

#: Every finding :func:`config_findings` can return.
CONFIG_FINDINGS = ("shell_egress", "encoded_command", "network_tool_command",
                   "persistence_path", "loader_injection_env", "embedded_ssh_key")


def _base(argv0: str) -> str:
    name = re.split(r"[\\/]", argv0.strip())[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


def _interpreter(argv0: str) -> str | None:
    base = _base(argv0)
    if base in _SHELLS:
        return "shell"
    if _PY.match(base):
        return "python"
    return _INTERPRETER_OF.get(base)


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings(v)


def config_findings(argv: list[str] | None, *, env: dict | None = None, cwd: str | None = None,
                    headers: dict | None = None) -> list[str]:
    """The shapes in one server's launch configuration that refuse it (empty = clean).

    *argv* is the already-split command (``None`` for an HTTP server). Ordered, without
    duplicates; never raises on odd input.
    """
    found: list[str] = []

    def add(code: str) -> None:
        if code not in found:
            found.append(code)

    args = [str(a) for a in (argv or []) if isinstance(a, (str, int, float))]
    env = env if isinstance(env, dict) else {}
    headers = headers if isinstance(headers, dict) else {}
    if args:
        kind = _interpreter(args[0])
        if kind is not None:
            flag = _INTERPRETER_FLAGS[kind]
            inline_at = next((i for i, a in enumerate(args[1:], 1) if flag.match(a)), None)
            if kind == "powershell" and any(_ENCODED_PS.match(a) for a in args[1:]):
                add("encoded_command")
            if inline_at is not None:
                code = " ".join(args[inline_at + 1:])
                if _EGRESS.search(code):
                    add("shell_egress")
                if _DECODE.search(code):
                    add("encoded_command")
        if _base(args[0]) in _NETWORK_TOOLS:
            add("network_tool_command")
    texts = list(args) + [str(v) for v in env.values()] + ([str(cwd)] if cwd else [])
    if any(_PERSISTENCE.search(t) for t in texts):
        add("persistence_path")
    for name, value in env.items():
        upper = str(name).upper()
        loader = upper in _LOADER_ENV or upper.startswith(("DYLD_", "LD_PRELOAD"))
        if loader or (upper == "NODE_OPTIONS" and _NODE_LOADER.search(str(value))):
            add("loader_injection_env")
    if any(_SSH_KEY.search(t) for t in texts + list(_strings(headers))):
        add("embedded_ssh_key")
    return found


# ── tool-definition scan ────────────────────────────────────────────────────

_DESCRIPTION_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("role_tag", re.compile(
        r"<\s*/?\s*(system|assistant|user|human|developer|im_start|im_end|tool_call|"
        r"important|instructions?)\s*>|<\|im_(start|end)\|>|\[/?INST\]|^\s*(system|assistant)\s*:",
        re.IGNORECASE | re.MULTILINE)),
    ("concealment", re.compile(
        r"\b(do\s*n[o']t|never|without)\s+(tell(ing)?|mention(ing)?|inform(ing)?|reveal(ing)?|"
        r"show(ing)?|disclos(e|ing)|notify(ing)?|ask(ing)?|alert(ing)?)\b[^.\n]{0,60}"
        r"\b(user|owner|human|operator)\b|\b(secretly|covertly|silently\s+(send|upload|post|"
        r"copy|forward|exfiltrate))\b|\bhide\s+(this|it)\s+from\b", re.IGNORECASE)),
    ("tool_override", re.compile(
        r"\b(before|instead\s+of)\s+(using|calling)\s+(any|the|other|another)\s+\w*\s*tools?\b|"
        r"\b(always|must)\s+(call|use|run)\s+this\s+tool\s+(first|before)\b|"
        r"\b(ignore|override|replace)\s+(the\s+)?(other|previous|built-?in)\s+tools?\b",
        re.IGNORECASE)),
    ("network_command", re.compile(
        r"\b(curl|wget|netcat|ncat|socat)\s+[-\w'\"$]|\bnc\s+-[a-z]|/dev/(tcp|udp)/|"
        r"invoke-webrequest|downloadstring", re.IGNORECASE)),
    ("base64_decode", re.compile(
        r"base64\s+(-d|--decode)|\bb64decode\b|\batob\s*\(|frombase64string|"
        r"\bdecode\s+(the\s+)?(following\s+)?base64\b", re.IGNORECASE)),
    ("exec_eval", re.compile(
        r"\b(eval|exec|execfile|compile)\s*\(|\bos\.(system|popen|exec\w*)\b|\bsubprocess\.\w+|"
        r"\bchild_process\b|\bRuntime\.getRuntime\b|\bpty\.spawn\b", re.IGNORECASE)),
    ("dangerous_import", re.compile(
        r"\b__import__\s*\(|\bimport\s+(os|subprocess|socket|ctypes|pty|marshal|pickle)\b|"
        r"\bfrom\s+(os|subprocess|socket|ctypes|pty)\s+import\b|"
        r"\brequire\s*\(\s*['\"](child_process|net|fs|vm)['\"]\s*\)", re.IGNORECASE)),
    ("credential_path", re.compile(
        r"~/\.ssh\b|\.ssh/(id_\w+|authorized_keys)|\bid_(rsa|ed25519|ecdsa|dsa)\b|"
        r"\.aws/credentials|\.netrc\b|\.git-credentials|/etc/(passwd|shadow)\b|"
        r"\.kube/config|\.docker/config\.json|\.npmrc\b|\.pypirc\b", re.IGNORECASE)),
    ("exfiltration", re.compile(
        r"\b(send|post|upload|forward|transmit|exfiltrate|copy)\b[^.\n]{0,80}\bto\s+"
        r"(https?://|ftp://|\w[\w.-]*\.\w{2,}/|\d{1,3}(\.\d{1,3}){3})", re.IGNORECASE)),
)

#: Every finding :func:`inspect_tool` can return (the injection family plus the rest).
DESCRIPTION_FINDINGS = ("injection",) + tuple(code for code, _ in _DESCRIPTION_PATTERNS) + (
    "invisible_identifier",)
#: Scan bound: a description or schema text past this is cut for the scan (the model sees
#: at most :data:`agents.core.mcp.model_bridge.MAX_DESCRIPTION_CHARS` of a description).
MAX_SCAN_CHARS = 64_000
_TEXT_KEYS = frozenset({"description", "title", "$comment", "markdownDescription"})
_IDENTIFIER_KEYS = frozenset({"enum", "const", "default", "examples", "required"})


def scan_text(text: str) -> list[str]:
    """The finding families present in *text* (empty = clean). Scans the cleaned text and
    the invisible-stripped copy, so a zero-width character inside a phrase does not hide it."""
    if not isinstance(text, str) or not text.strip():
        return []
    text = text[:MAX_SCAN_CHARS]
    variants = [text]
    stripped = strip_format_chars(text)
    if stripped != text:
        variants.append(stripped)
    found: list[str] = []
    if any(detect_injection_normalized(v) for v in variants):
        found.append("injection")
    for code, pattern in _DESCRIPTION_PATTERNS:
        if any(pattern.search(v) for v in variants):
            found.append(code)
    return found


def _schema_texts(schema: Any, out: list[str], depth: int = 0) -> bool:
    """Collect the schema's human-text strings into *out*; True when an identifier (a
    property name, an enum / const / default value, a required entry) carries a character
    :func:`clean_text` would remove."""
    if depth > 64:
        return False
    dirty = False
    if isinstance(schema, dict):
        for key, value in schema.items():
            if isinstance(key, str) and clean_text(key) != key:
                dirty = True
            if key in _TEXT_KEYS and isinstance(value, str):
                out.append(value)
            elif key in _IDENTIFIER_KEYS:
                dirty = dirty or any(clean_text(s) != s for s in _strings(value))
            elif key == "properties" and isinstance(value, dict):
                for prop, sub in value.items():
                    if isinstance(prop, str) and clean_text(prop) != prop:
                        dirty = True
                    dirty = _schema_texts(sub, out, depth + 1) or dirty
            else:
                dirty = _schema_texts(value, out, depth + 1) or dirty
    elif isinstance(schema, list):
        for item in schema:
            dirty = _schema_texts(item, out, depth + 1) or dirty
    return dirty


def _clean_schema_texts(schema: Any, depth: int = 0) -> Any:
    """*schema* with every ``description`` / ``title`` string cleaned; identifiers untouched."""
    if depth > 64:
        return schema
    if isinstance(schema, dict):
        out = {}
        for key, value in schema.items():
            if key in _TEXT_KEYS and isinstance(value, str):
                out[key] = clean_text(value)
            elif key in _IDENTIFIER_KEYS:
                out[key] = value
            else:
                out[key] = _clean_schema_texts(value, depth + 1)
        return out
    if isinstance(schema, list):
        return [_clean_schema_texts(item, depth + 1) for item in schema]
    return schema


def definition_digest(description: Any, input_schema: Any, annotations: Any) -> str:
    """sha256 over the raw definition a server listed — what an owner's release names."""
    try:
        raw = json.dumps([description, input_schema, annotations], sort_keys=True,
                         ensure_ascii=True, default=str)
    except (TypeError, ValueError, RecursionError):
        raw = repr((description, input_schema, annotations))
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()


def inspect_tool(description: Any, input_schema: Any, annotations: Any = None,
                 ) -> tuple[str, Any, dict, list[str]]:
    """``(clean description, clean schema, clean annotations, findings)`` for one listed
    tool. Never raises: an unreadable definition comes back empty with no findings, and
    the schema normalizer downstream refuses what it cannot repair."""
    desc = clean_text(description) if isinstance(description, str) else ""
    texts: list[str] = [desc]
    findings: list[str] = []
    try:
        if _schema_texts(input_schema, texts):
            findings.append("invisible_identifier")
        schema = _clean_schema_texts(input_schema)
    except RecursionError:
        schema = {}
    notes = clean_deep(annotations) if isinstance(annotations, dict) else {}
    title = notes.get("title") if isinstance(notes, dict) else None
    if isinstance(title, str):
        texts.append(title)
    # The raw text too: a pattern spelled with invisible characters inside it is caught on
    # the stripped copy scan_text makes, and the cleaned copy catches the rest.
    if isinstance(description, str) and description != desc:
        texts.append(description)
    for text in texts:
        for code in scan_text(text):
            if code not in findings:
                findings.append(code)
    order = {code: i for i, code in enumerate(DESCRIPTION_FINDINGS)}
    findings.sort(key=lambda c: order.get(c, len(order)))
    return desc, schema, notes, findings
