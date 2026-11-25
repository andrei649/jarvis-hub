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
                     "ash", "cmd", "rbash", "yash", "elvish", "nu", "xonsh"})
_PY = re.compile(r"^(python|pypy)[0-9.]*w?$")
#: Inline-code flags per interpreter, matched on the flag's name (``--eval=CODE`` is split
#: at ``=``; ``-eCODE`` is read as ``-e`` followed by the code).
_INTERPRETER_FLAGS: dict[str, re.Pattern] = {
    # bash -c / -lc / -ic …; python -c / -Ic …
    "shell": re.compile(r"^-[A-Za-z]*c[A-Za-z]*$|^/c$|^/k$|^--command$", re.IGNORECASE),
    "python": re.compile(r"^-[A-Za-z]*c$"),
    "node": re.compile(r"^(-e|--eval|-p|--print|-pe|-ep)$"),
    "deno": re.compile(r"^eval$"),
    "bun": re.compile(r"^(-e|--eval|-p|--print)$"),
    "perl": re.compile(r"^-[A-Za-z]*[eE]$"),
    "ruby": re.compile(r"^-[A-Za-z]*e$"),
    "php": re.compile(r"^(-r|--run)$"),
    "lua": re.compile(r"^-e$"),
    "rscript": re.compile(r"^(-e|--expr)$", re.IGNORECASE),
    "osascript": re.compile(r"^-e$"),
    "tcl": re.compile(r"^-c$"),
}
#: Short flags whose code may be glued on (``-e'code'``, ``-cprint(1)``).
_GLUED = {"python": "-c", "node": "-e", "perl": "-e", "ruby": "-e", "php": "-r", "lua": "-e"}
_INTERPRETER_OF = {
    "node": "node", "nodejs": "node", "deno": "deno", "bun": "bun",
    "perl": "perl", "ruby": "ruby", "php": "php", "lua": "lua", "luajit": "lua",
    "rscript": "rscript", "osascript": "osascript", "tclsh": "tcl", "wish": "tcl",
    "pwsh": "powershell", "powershell": "powershell", "powershell_ise": "powershell",
}
_EGRESS = re.compile(
    r"\b(curl|wget|aria2c|netcat|ncat|socat|telnet|tftp)\b|\bnc\s+-?[a-z]|/dev/(tcp|udp)/"
    r"|\b(https?|ftp|wss?)://|\burllib\b|\burlopen\b|\brequests\.(get|post|put)\b"
    r"|\bhttp\.client\b|\bsocket\b|\bfetch\s*\(|\bnet\.connect\b|\bhttps?\.get\b"
    r"|\brequire\s*\(\s*['\"](https?|net|dgram|tls|child_process)['\"]"
    r"|invoke-(webrequest|restmethod)|\biwr\b|\birm\b|downloadstring|downloadfile"
    r"|net\.webclient|xmlhttp|bitsadmin|certutil\s+-urlcache|IO::Socket|Net::HTTP|open-uri",
    re.IGNORECASE,
)
_DECODE = re.compile(r"base64\s+(-d|--decode|-D)|\bb64decode\b|\batob\s*\(|frombase64string"
                     r"|\bbase64\.decode|codecs\.decode\([^)]*base64", re.IGNORECASE)
_NETWORK_TOOLS = frozenset({"curl", "wget", "nc", "ncat", "netcat", "socat", "telnet", "tftp",
                            "aria2c", "ftp"})
_PRIVILEGE = frozenset({"sudo", "doas", "pkexec", "su", "runuser", "runas"})
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
#: Code-loading variables beyond the catalog's refused list (``catalog._env_refused``, which
#: the guard applies too: PATH, HOME, PYTHONPATH, PYTHONHOME, PYTHONSTARTUP, LD_*, DYLD_*,
#: NODE_OPTIONS, NODE_PATH, PERL5OPT, PERL5LIB, RUBYOPT, RUBYLIB, GCONV_PATH, BASH_ENV, ENV,
#: JAVA_TOOL_OPTIONS, GIT_SSH*, npm/pip/uv registries …).
_LOADER_ENV = frozenset({"PROMPT_COMMAND", "PERL5DB", "PYTHONINSPECT", "PYTHONUSERBASE",
                         "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS", "CLASSPATH", "LUA_PATH",
                         "LUA_CPATH", "TCLLIBPATH", "PSMODULEPATH", "ZDOTDIR", "SHELLOPTS",
                         "BASHOPTS", "PS4", "IFS", "MALLOC_CONF", "SSL_CERT_FILE",
                         "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
                         "NODE_EXTRA_CA_CERTS"})
_SSH_KEY = re.compile(r"\b(ssh-(rsa|ed25519|dss)|ecdsa-sha2-nistp\d+|sk-ssh-ed25519@openssh\.com)"
                      r"\s+AAAA[0-9A-Za-z+/]{20,}")

#: Every finding :func:`config_findings` can return.
CONFIG_FINDINGS = ("shell_egress", "encoded_command", "network_tool_command",
                   "privilege_escalation", "persistence_path", "loader_injection_env",
                   "embedded_ssh_key", "unparsed_wrapper")


def _base(argv0: str) -> str:
    name = re.split(r"[\\/]", argv0.strip())[-1].lower()
    for ext in (".exe", ".cmd", ".bat", ".com"):
        if name.endswith(ext):
            return name[: -len(ext)]
    return name


def _interpreter(argv0: str) -> str | None:
    base = _base(argv0)
    if base in _SHELLS:
        return "shell"
    if _PY.match(base):
        return "python"
    return _INTERPRETER_OF.get(base)


def _ps_name(token: str) -> str | None:
    """A PowerShell parameter's name without its ``-``/``--``/``/`` and ``:value``."""
    match = re.match(r"^(--|-|/)([A-Za-z]+)(:.*)?$", token)
    return match.group(2).lower() if match else None


def _encoded_ps(token: str) -> bool:
    """``-EncodedCommand`` / ``-EncodedArguments`` in any spelling PowerShell accepts:
    ``-ec``, ``-ea``, ``-e`` and every prefix of the full names."""
    name = _ps_name(token)
    return bool(name) and (name in ("e", "ec", "ea") or (len(name) >= 2 and (
        "encodedcommand".startswith(name) or "encodedarguments".startswith(name))))


def _ps_inline(token: str) -> bool:
    name = _ps_name(token)
    return bool(name) and "command".startswith(name)


# ── wrappers: commands that run another command ─────────────────────────────

#: Options that take a value, per wrapper (the value is skipped with the option).
_WRAPPER_VALUE_OPTS: dict[str, frozenset[str]] = {
    "env": frozenset({"-u", "--unset", "-C", "--chdir", "-a", "--argv0"}),
    "timeout": frozenset({"-s", "--signal", "-k", "--kill-after"}),
    "nice": frozenset({"-n", "--adjustment"}),
    "ionice": frozenset({"-c", "--class", "-n", "--classdata", "-p", "-P", "-u"}),
    "stdbuf": frozenset({"-i", "-o", "-e", "--input", "--output", "--error"}),
    "chrt": frozenset(),
    "taskset": frozenset(),
    "setsid": frozenset(),
    "nohup": frozenset(),
    "time": frozenset({"-f", "--format", "-o", "--output"}),
    "exec": frozenset({"-a"}),
    "command": frozenset(),
    "xvfb-run": frozenset({"-n", "-s", "-f", "-e", "-p", "--server-num", "--server-args"}),
    "uvx": frozenset({"--with", "--with-requirements", "--python", "-p", "--from", "--index",
                      "--index-url", "--extra-index-url", "-w"}),
    "npx": frozenset({"-p", "--package", "-c", "--call", "--node-options", "--userconfig"}),
    "bunx": frozenset({"-p", "--package"}),
}
#: Wrappers whose first non-option operand is not the command (``timeout DURATION cmd``,
#: ``taskset MASK cmd``, ``chrt PRIORITY cmd``).
_WRAPPER_OPERAND = {"timeout": 1, "taskset": 1, "chrt": 1}
#: ``uv run``, ``poetry run``, ``pipx run``, ``pnpm dlx/exec``, ``npm exec`` …: the value
#: options of each, and the subcommands that run a command.
_SUBCOMMAND_WRAPPERS: dict[str, tuple[tuple[str, ...], frozenset[str]]] = {
    "uv": (("run",), frozenset({"--with", "--with-requirements", "--with-editable", "--python",
                                "-p", "--project", "--directory", "--package", "--extra",
                                "--group", "--env-file", "--index", "--index-url",
                                "--extra-index-url", "--from", "-w"})),
    "poetry": (("run",), frozenset({"-C", "--directory", "-P", "--project"})),
    "pipx": (("run",), frozenset({"--spec", "--python", "--index-url", "--pip-args"})),
    "pnpm": (("dlx", "exec"), frozenset({"-C", "--dir", "--filter"})),
    "yarn": (("dlx", "exec"), frozenset({"--cwd"})),
    "npm": (("exec", "x"), frozenset({"-p", "--package", "-c", "--call"})),
    "bun": (("x", "run"), frozenset({"--cwd"})),
    "conda": (("run",), frozenset({"-n", "--name", "-p", "--prefix"})),
    "pdm": (("run",), frozenset()),
    "hatch": (("run",), frozenset()),
    "rye": (("run",), frozenset()),
}
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
MAX_UNWRAP = 8


def _skip_options(rest: list[str], value_opts: frozenset[str], operands: int) -> list[str]:
    out = list(rest)
    while out and out[0].startswith("-") and out[0] != "-":
        tok = out.pop(0)
        if tok == "--":
            break
        if tok in value_opts and out:
            out.pop(0)
    for _ in range(operands):
        if out:
            out.pop(0)
    return out


def _env_operands(rest: list[str], env: dict) -> list[str] | None:
    """``env``'s command after its options, ``-S`` strings split and ``NAME=VALUE``
    assignments moved into *env*; None when a ``-S`` string does not split."""
    import shlex

    tail = list(rest)
    out: list[str] = []
    while tail:
        tok = tail.pop(0)
        if tok == "--":
            out.extend(tail)
            break
        if tok in ("-S", "--split-string") or tok.startswith(("-S", "--split-string=")):
            if tok.startswith("--split-string="):
                raw = tok.split("=", 1)[1]
            elif tok.startswith("-S") and len(tok) > 2:
                raw = tok[2:]
            else:
                raw = tail.pop(0) if tail else ""
            try:
                tail = shlex.split(raw) + tail
            except ValueError:
                return None
            continue
        if _ASSIGN.match(tok):
            name, _, value = tok.partition("=")
            env[name] = value
            continue
        if tok.startswith("-"):
            if tok in _WRAPPER_VALUE_OPTS["env"] and tail:
                tail.pop(0)
            continue
        out.append(tok)
        out.extend(tail)
        break
    return out


def _unwrap(argv: list[str], env: dict) -> tuple[list[list[str]], bool]:
    """Every command *argv* runs through its wrappers, outermost first, and whether a
    wrapper could not be read (a ``-S`` string that does not split, too many layers).
    ``env NAME=VALUE`` assignments are added to *env* so they are checked too."""
    layers = [argv]
    current = argv
    for _ in range(MAX_UNWRAP):
        base = _base(current[0])
        rest = current[1:]
        if base in ("busybox", "toybox"):
            nxt = rest
        elif base in _SUBCOMMAND_WRAPPERS:
            subs, opts = _SUBCOMMAND_WRAPPERS[base]
            idx = next((i for i, a in enumerate(rest) if not a.startswith("-")), None)
            if idx is not None and base == "uv" and rest[idx] == "tool" \
                    and idx + 1 < len(rest) and rest[idx + 1] == "run":
                idx += 1                                   # ``uv tool run`` (``uvx``)
            elif idx is None or rest[idx] not in subs:
                return layers, False
            nxt = _skip_options(rest[idx + 1:], opts, 0)
        elif base == "env":
            nxt = _env_operands(rest, env)
            if nxt is None:
                return layers, True
        elif base in _WRAPPER_VALUE_OPTS:
            nxt = _skip_options(rest, _WRAPPER_VALUE_OPTS[base], _WRAPPER_OPERAND.get(base, 0))
        else:
            return layers, False
        if not nxt:
            return layers, False
        layers.append(nxt)
        current = nxt
    return layers, True


def _inline_code(kind: str, args: list[str]) -> str | None:
    """The inline code an interpreter call carries, or None."""
    if kind == "powershell":
        for i, tok in enumerate(args):
            if _ps_inline(tok):
                glued = tok.split(":", 1)[1] if ":" in tok else ""
                return " ".join([glued, *args[i + 1:]]).strip()
        return None
    flag = _INTERPRETER_FLAGS[kind]
    glue = _GLUED.get(kind)
    for i, tok in enumerate(args):
        if tok.startswith("--") and "=" in tok:
            name, _, value = tok.partition("=")
            if flag.match(name):
                return " ".join([value, *args[i + 1:]])
            continue
        if flag.match(tok):
            return " ".join(args[i + 1:])
        if glue and tok.startswith(glue) and len(tok) > len(glue):
            return " ".join([tok[len(glue):], *args[i + 1:]])
        if kind in ("python", "perl", "ruby", "node", "php", "lua") and not tok.startswith("-"):
            return None          # a script path: what follows is the script's own arguments
    return None


def _env_refused(name: str) -> bool:
    from agents.core.mcp.catalog import _env_refused as catalog_refused

    upper = str(name).upper()
    return catalog_refused(upper) or upper in _LOADER_ENV or upper.startswith("BASH_FUNC_")


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

    *argv* is the already-split command (``None`` for an HTTP server). Wrappers that run
    another command (``env``, ``timeout``, ``nice``, ``nohup``, ``stdbuf``, ``setsid``,
    ``uv run``, ``uvx``, ``npx``, ``busybox`` applets …) are unwrapped first and every
    layer is classified; ``env NAME=VALUE`` assignments are checked like the server's own
    environment. Ordered, without duplicates; never raises on odd input.
    """
    found: list[str] = []

    def add(code: str) -> None:
        if code not in found:
            found.append(code)

    args = [str(a) for a in (argv or []) if isinstance(a, (str, int, float))]
    env = dict(env) if isinstance(env, dict) else {}
    headers = headers if isinstance(headers, dict) else {}
    layers, unreadable = _unwrap(args, env) if args else ([], False)
    if unreadable:
        add("unparsed_wrapper")
    for layer in layers:
        base = _base(layer[0])
        if base in _PRIVILEGE:
            add("privilege_escalation")
        if base in _NETWORK_TOOLS:
            add("network_tool_command")
        kind = _interpreter(layer[0])
        if kind is None:
            continue
        if kind == "powershell" and any(_encoded_ps(a) for a in layer[1:]):
            add("encoded_command")
        code = _inline_code(kind, layer[1:])
        if code is not None:
            if _EGRESS.search(code):
                add("shell_egress")
            if _DECODE.search(code):
                add("encoded_command")
    texts = list(args) + [str(v) for v in env.values()] + ([str(cwd)] if cwd else [])
    if any(_PERSISTENCE.search(t) for t in texts):
        add("persistence_path")
    if any(_env_refused(name) for name in env):
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
        r"show(ing)?|disclos(e|ing)|notify(ing)?|ask(ing)?|alert(ing)?)\b[^\n]{0,80}?"
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
        r"~/\.ssh\b|\.ssh/(id_\w+|authorized_keys)|\bssh\s+id\s+(rsa|ed25519|ecdsa|dsa)\b|"
        r"\bid_(rsa|ed25519|ecdsa|dsa)\b|"
        r"\.aws/credentials|\.netrc\b|\.git-credentials|/etc/(passwd|shadow)\b|"
        r"\.kube/config|\.docker/config\.json|\.npmrc\b|\.pypirc\b", re.IGNORECASE)),
    # Not cut at a '.': a path such as ~/.ssh/id_rsa sits between the verb and the target.
    ("exfiltration", re.compile(
        r"\b(send|post|upload|forward|transmit|exfiltrate|copy|leak)\b[^\n]{0,160}?\bto\s+"
        r"(https?://|ftp://|\w[\w.-]*\.\w{2,}/|\d{1,3}(\.\d{1,3}){3})", re.IGNORECASE)),
)

#: Every finding :func:`inspect_tool` can return (the injection family plus the rest).
DESCRIPTION_FINDINGS = ("injection",) + tuple(code for code, _ in _DESCRIPTION_PATTERNS) + (
    "invisible_identifier",)
#: Scan bound: a description or schema text past this is cut for the scan (the model sees
#: at most :data:`agents.core.mcp.model_bridge.MAX_DESCRIPTION_CHARS` of a description).
MAX_SCAN_CHARS = 64_000
#: Strings collected from one definition for the scan (every leaf counts against it).
MAX_SCAN_STRINGS = 4_096
_TEXT_KEYS = frozenset({"description", "title", "$comment", "markdownDescription"})
_IDENTIFIER_KEYS = frozenset({"enum", "const", "default", "examples", "required"})
_NAME_MAP_KEYS = frozenset({"properties", "patternProperties", "$defs", "definitions",
                            "dependentSchemas", "dependentRequired"})

#: Latin look-alikes from Cyrillic, Greek and Armenian (a confusables *skeleton*, not the
#: whole Unicode table): enough that "Ignоre" with a Cyrillic о reads as "Ignore".
_HOMOGLYPHS = str.maketrans({
    "а": "a", "в": "b", "е": "e", "ё": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p",
    "с": "c", "т": "t", "у": "y", "х": "x", "і": "i", "ї": "i", "ј": "j", "ѕ": "s", "ԁ": "d",
    "ԛ": "q", "ԝ": "w", "һ": "h", "ӏ": "l", "ɡ": "g", "ɑ": "a", "ɩ": "i", "ʏ": "y",
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C",
    "Т": "T", "У": "Y", "Х": "X", "І": "I", "Ј": "J", "Ѕ": "S", "Ԁ": "D", "Ԛ": "Q", "Ԝ": "W",
    "α": "a", "ο": "o", "ρ": "p", "ι": "i", "κ": "k", "ν": "v", "υ": "u", "χ": "x", "ε": "e",
    "τ": "t", "ω": "w", "γ": "y", "η": "n",
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N",
    "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
    "օ": "o", "ս": "u", "ց": "g", "հ": "h", "ո": "n", "ա": "w", "ք": "q",
    "ı": "i", "ȷ": "j", "ℓ": "l",
})
_SEPARATORS = re.compile(r"[_\-./]+|(?<=[a-z])(?=[A-Z])")


def _skeleton(text: str) -> str:
    """NFKC, combining marks removed, look-alike letters mapped to Latin."""
    import unicodedata

    folded = unicodedata.normalize("NFKC", text)
    decomposed = unicodedata.normalize("NFD", folded)
    bare = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return unicodedata.normalize("NFC", bare).translate(_HOMOGLYPHS)


def scan_text(text: str) -> list[str]:
    """The finding families present in *text* (empty = clean).

    Scans the text, its invisible-stripped copy, its confusables skeleton (NFKC,
    combining marks removed, Cyrillic/Greek/Armenian look-alikes mapped to Latin) and a
    copy with identifier separators (``_``, ``-``, ``.``, ``/``, camelCase) turned into
    spaces, so ``ignore_all_previous_instructions`` reads as the phrase it spells."""
    if not isinstance(text, str) or not text.strip():
        return []
    text = text[:MAX_SCAN_CHARS]
    variants: list[str] = []
    for base in (text, strip_format_chars(text)):
        skeleton = _skeleton(base)
        for candidate in (base, skeleton, _SEPARATORS.sub(" ", skeleton)):
            if candidate not in variants:
                variants.append(candidate)
    found: list[str] = []
    if any(detect_injection_normalized(v) for v in variants):
        found.append("injection")
    for code, pattern in _DESCRIPTION_PATTERNS:
        if any(pattern.search(v) for v in variants):
            found.append(code)
    return found


def _schema_texts(schema: Any, out: list[str], depth: int = 0) -> bool:
    """Collect every string the model will read in the schema into *out* — each string
    leaf (descriptions and titles, but also ``enum`` / ``const`` / ``default`` /
    ``examples`` / ``pattern`` values, nested at any depth) and every property name.
    True when an identifier (a key, a property name, an enum / const / default / examples /
    required value) carries a character :func:`clean_text` would remove."""
    if depth > 64 or len(out) > MAX_SCAN_STRINGS:
        return False
    dirty = False
    if isinstance(schema, dict):
        for key, value in schema.items():
            if isinstance(key, str) and clean_text(key) != key:
                dirty = True
            if key in _IDENTIFIER_KEYS:
                strings = list(_strings(value))
                out.extend(strings)
                dirty = dirty or any(clean_text(s) != s for s in strings)
            elif key in _NAME_MAP_KEYS and isinstance(value, dict):
                for prop, sub in value.items():
                    if isinstance(prop, str):
                        out.append(prop)
                        if clean_text(prop) != prop:
                            dirty = True
                    dirty = _schema_texts(sub, out, depth + 1) or dirty
            elif isinstance(value, str):
                out.append(value)
            else:
                dirty = _schema_texts(value, out, depth + 1) or dirty
    elif isinstance(schema, list):
        for item in schema:
            dirty = _schema_texts(item, out, depth + 1) or dirty
    elif isinstance(schema, str):
        out.append(schema)
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
                 name: Any = None) -> tuple[str, Any, dict, list[str]]:
    """``(clean description, clean schema, clean annotations, findings)`` for one listed
    tool. The tool's name, its description, every string of its schema (values and
    property names) and every string of its annotations are scanned. Never raises: an
    unreadable definition comes back empty with no findings, and the schema normalizer
    downstream refuses what it cannot repair."""
    desc = clean_text(description) if isinstance(description, str) else ""
    texts: list[str] = [desc]
    findings: list[str] = []
    if isinstance(name, str):
        texts.append(name)
        if clean_text(name) != name:
            findings.append("invisible_identifier")
    try:
        if _schema_texts(input_schema, texts) and "invisible_identifier" not in findings:
            findings.append("invisible_identifier")
        schema = _clean_schema_texts(input_schema)
    except RecursionError:
        schema = {}
    notes = clean_deep(annotations) if isinstance(annotations, dict) else {}
    if isinstance(notes, dict):
        texts.extend(list(_strings(notes))[:MAX_SCAN_STRINGS])
    # The raw text too: a pattern spelled with invisible characters inside it is caught on
    # the stripped copy scan_text makes, and the cleaned copy catches the rest.
    if isinstance(description, str) and description != desc:
        texts.append(description)
    for text in texts[:MAX_SCAN_STRINGS]:
        for code in scan_text(text):
            if code not in findings:
                findings.append(code)
    order = {code: i for i, code in enumerate(DESCRIPTION_FINDINGS)}
    findings.sort(key=lambda c: order.get(c, len(order)))
    return desc, schema, notes, findings
