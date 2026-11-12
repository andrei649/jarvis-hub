"""Guards specific to the unattended lane (H457): injection, credential pair, self-lifecycle.

A scheduled job runs while the owner is not watching, so three checks run on what a
job *is* — when it is created or edited, and again when it fires, as a backstop for
records written into the store by anything other than the validating API:

1. **Provenance-tiered prompt scan.** The owner's own prompt text is scanned with the
   *strict* tier: injection directives, invisible/bidi characters and command shapes
   (``rm -rf /``, ``curl … $API_KEY``, ``cat ~/.env``, ``authorized_keys``) all block.
   Text that is loaded at fire time from somewhere else — the job's previous output, a
   ``context_from`` job's output, a script's stdout, a monitor's context — gets the
   *loose* tier: invisible characters are stripped (sanitized, not fatal, so one stray
   zero-width space cannot kill a job forever) and only unambiguous injection
   directives block. Command shapes are not checked there: a triage feed legitimately
   quotes ``rm -rf /``. Every such turn already carries the untrusted ``inbound``
   origin (channel ``job``), so the kernel's taint rule still sends any effect the
   model attempts to the approval queue; the tier decides only whether the run starts.
2. **Credential pair re-validation at use.** Nerva jobs cannot carry an endpoint or a
   key: a pin names a configured adapter, and a non-built-in adapter must be the
   owner's signed selection, whose endpoint and credential generation are bound
   together in one signed record. :func:`check_credential_pair` re-checks that at fire
   time and fails closed — an endpoint/key override, or a selection that cannot be read
   back, refuses the run instead of resolving a backend.
3. **Self-lifecycle guard.** A job whose prompt, script, or any script either of them
   references (recursively, to :data:`MAX_REFERENCED_DEPTH`) would stop, restart,
   update or uninstall the Nerva hub itself is refused: under a supervisor with
   restart-on-exit, one scheduled "restart yourself" turns the box into a respawn loop.
   Detection is command-shaped, not keyword-shaped: prose about restarting is allowed,
   ``systemctl restart jarvis-hub`` is not; a quoted command echoed into a file is data
   and is masked; transparent prefixes (``sudo``, ``env``, ``nohup``, ``timeout`` …)
   are peeled; ``sh -c`` payloads are scanned too.

Nothing here executes anything. Reads are bounded, no-follow and regular-file only.
"""
from __future__ import annotations

import ast
import logging
import os
import re
import shlex
import stat
import unicodedata
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_REFERENCED_DEPTH = 8
MAX_REFERENCED_BYTES = 1024 * 1024
MAX_REFERENCED_FILES = 64
BINARY_SNIFF_BYTES = 4096
MAX_PREFIX_PEELS = 8
MAX_SEGMENTS = 200_000
MAX_COMMAND_WORDS = 64

STRICT = "strict"
LOOSE = "loose"


class JobGuardBlocked(ValueError):
    """A job was refused by an unattended-lane guard; the message names which and why."""


# ── 1. provenance-tiered prompt scan ─────────────────────────────────────────

# Directives: these block in both tiers. Narrow on purpose — the loose tier runs over
# data a third party may write, and a broad rule there would let anyone pause a job.
_DIRECTIVES = (
    (r"\bignore\s+(?:\w+\s+){0,3}(?:previous|prior|above|earlier|all)\s+(?:\w+\s+){0,2}"
     r"(?:instructions|prompts|rules)\b", "prompt_injection"),
    (r"\bdisregard\s+(?:your|all|any|the|previous|prior)\s+(?:\w+\s+){0,2}"
     r"(?:instructions|rules|guidelines)\b", "disregard_rules"),
    (r"\bsystem\s+prompt\s+override\b", "sys_prompt_override"),
    (r"\bdo\s+not\s+tell\s+(?:the|your|my)\s+(?:user|owner)\b", "deception_hide"),
    (r"\bdon'?t\s+tell\s+(?:the|your|my)\s+(?:user|owner)\b", "deception_hide"),
)
_SECRET_VAR = r"\$\{?\w*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|API)\w*"  # nosec B105 - detection regex, not a secret
# Command shapes: strict tier only (the owner's own text, where they are a smoking gun).
_COMMAND_SHAPES = (
    (r"\bcurl\s[^\n]{0,400}?" + _SECRET_VAR, "exfil_curl"),
    (r"\bwget\s[^\n]{0,400}?" + _SECRET_VAR, "exfil_wget"),
    (r"\b(?:cat|less|more|head|tail|base64|xxd)\s[^\n]{0,400}?"
     r"(?:\.env\b|credentials\b|\.netrc\b|\.pgpass\b|id_rsa\b|id_ed25519\b|\.ssh/)", "read_secrets"),
    (r"authorized_keys", "ssh_backdoor"),
    (r"/etc/sudoers|\bvisudo\b", "sudoers_mod"),
    (r"\brm\s+(?:-[a-z]*\s+)*-[a-z]*(?:rf|fr)[a-z]*\s+/", "destructive_root_rm"),
    (r"\brm\s+(?:-[a-z]*r[a-z]*\s+)(?:-[a-z]*f[a-z]*\s+)/", "destructive_root_rm"),
)
_DIRECTIVE_RES = tuple((re.compile(p, re.IGNORECASE), name) for p, name in _DIRECTIVES)
_SHAPE_RES = tuple((re.compile(p, re.IGNORECASE), name) for p, name in _COMMAND_SHAPES)

# Invisible and bidi controls that hide or reorder what the owner sees on screen.
_STRICT_INVISIBLE = frozenset(
    "\u200b\u200c\u200d\u2060\ufeff\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\u180e"
)


def _is_tag(char: str) -> bool:
    return 0xE0000 <= ord(char) <= 0xE007F


def _emoji_joiner(text: str, index: int) -> bool:
    """A ZWJ between two pictographs builds one emoji (👨\u200d👩\u200d👧); it hides nothing."""
    if text[index] != "\u200d" or index == 0 or index + 1 >= len(text):
        return False
    before, after = text[index - 1], text[index + 1]
    return (unicodedata.category(before) == "So" or before == "️") and unicodedata.category(after) == "So"


def invisible_characters(text: str) -> list[str]:
    """Code points (``U+XXXX``) of the hidden characters in *text*, de-duplicated."""
    found: list[str] = []
    for index, char in enumerate(text):
        if (char in _STRICT_INVISIBLE or _is_tag(char)) and not _emoji_joiner(text, index):
            code = f"U+{ord(char):04X}"
            if code not in found:
                found.append(code)
    return found


def _variants(text: str) -> list[str]:
    """The text, its NFKC fold, each with format characters removed and whitespace collapsed."""
    from agents.core.security.quarantine import collapse_whitespace, strip_format_chars

    out: list[str] = []
    folded = unicodedata.normalize("NFKC", text)
    for base in (text, folded):
        for variant in (base, strip_format_chars(base), collapse_whitespace(strip_format_chars(base))):
            if variant not in out:
                out.append(variant)
    return out


def _matches(text: str, rules) -> list[str]:
    hits: list[str] = []
    for variant in _variants(text):
        for pattern, name in rules:
            if name not in hits and pattern.search(variant):
                hits.append(name)
    return hits


def prompt_findings(text: str, *, tier: str = STRICT) -> list[str]:
    """Named findings for *text* under *tier*; empty means it may run."""
    if tier not in (STRICT, LOOSE):
        raise ValueError(f"unknown scan tier {tier!r}")
    if not isinstance(text, str) or not text:
        return []
    hits = _matches(text, _DIRECTIVE_RES)
    if tier == STRICT:
        hits.extend(name for name in _matches(text, _SHAPE_RES) if name not in hits)
        hidden = invisible_characters(text)
        if hidden:
            hits.append("invisible_unicode:" + ",".join(hidden[:4]))
    return hits


def scan_owner_prompt(text: str, *, where: str = "prompt") -> None:
    """Strict tier: the owner's own job text. Raises :class:`JobGuardBlocked`."""
    hits = prompt_findings(text, tier=STRICT)
    if hits:
        raise JobGuardBlocked(f"{where} blocked by the scheduled-job injection scanner (strict): "
                              + ", ".join(hits))


def sanitize_loaded(text: str, *, source: str) -> str:
    """Loose tier: content loaded into a job's prompt at fire time from elsewhere.

    Invisible characters are stripped (and logged); only an unambiguous injection
    directive blocks. Returns the text the model will read.
    """
    if not isinstance(text, str) or not text:
        return text
    from agents.core.security.quarantine import strip_format_chars

    cleaned = strip_format_chars(text)
    if cleaned != text:
        logger.warning("scheduled job: stripped %d invisible character(s) from %s",
                       len(text) - len(cleaned), source)
    hits = prompt_findings(text, tier=LOOSE)
    if hits:
        raise JobGuardBlocked(f"{source} blocked by the scheduled-job injection scanner (loose): "
                              + ", ".join(hits))
    return cleaned


def sanitize_loaded_deep(value, *, source: str, _depth: int = 0):
    """:func:`sanitize_loaded` over every string of a JSON-like value (bounded depth)."""
    if _depth > 32:
        raise JobGuardBlocked(f"{source} is nested too deeply to scan")
    if isinstance(value, str):
        return sanitize_loaded(value, source=source)
    if isinstance(value, dict):
        return {sanitize_loaded_deep(key, source=source, _depth=_depth + 1):
                sanitize_loaded_deep(item, source=source, _depth=_depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_loaded_deep(item, source=source, _depth=_depth + 1) for item in value]
    return value


# ── 2. provider/credential pair at use time ──────────────────────────────────

# Option keys that would redirect a stored credential: no Nerva job may carry one.
ENDPOINT_OVERRIDE_KEYS = frozenset({
    "base_url", "api_base", "api_url", "base", "endpoint", "url", "host", "api_key", "key",
    "token", "credential", "headers",
})


def check_credential_pair(options) -> None:
    """Fail closed unless the job's model pin can only reach its own adapter's endpoint.

    Run when the job fires, before any backend is resolved.
    """
    if not isinstance(options, dict):
        raise JobGuardBlocked("job options are unreadable; refusing to resolve a provider")
    overrides = sorted(ENDPOINT_OVERRIDE_KEYS & set(options))
    if overrides:
        raise JobGuardBlocked("job carries an endpoint/credential override (" + ", ".join(overrides)
                              + "); refusing to run a job that could send a stored key elsewhere")
    if "provider" not in options and "model" not in options:
        return
    from ..llm.job_selection import validate_pins

    try:
        validate_pins(options)
    except ValueError as exc:
        raise JobGuardBlocked(f"provider pin no longer valid: {exc}") from exc
    except Exception as exc:  # the signed selection could not be read back: fail closed
        raise JobGuardBlocked("could not validate the provider pin against the signed selection "
                              f"({type(exc).__name__}); refusing to run") from exc


# ── 3. self-lifecycle guard ──────────────────────────────────────────────────

# Names this hub runs as: systemd units, the Windows service, launchd labels,
# containers/compose services, process command lines.
_HUB_NAME = re.compile(
    r"(?:^|[^A-Za-z0-9])(?:jarvis[-_.]?hub|jarvis[-_.]?runtime|jarvishub|nerva|jarvis)"
    r"(?:[-_.@][A-Za-z0-9_.@-]*)?(?:\.service)?(?:$|[^A-Za-z0-9])",
    re.IGNORECASE,
)
_HUB_PROCESS = re.compile(
    r"jarvis|nerva|serve\.py|agents[./]serve|agents[./]web|uvicorn|python[0-9.]*(?:\.exe)?$",
    re.IGNORECASE,
)
_SYSTEMCTL_VERBS = frozenset({
    "stop", "restart", "kill", "disable", "mask", "reload-or-restart", "try-restart",
    "try-reload-or-restart", "condrestart", "force-reload", "freeze", "clean",
})
_HOST_POWER = frozenset({"reboot", "poweroff", "halt", "shutdown", "kexec"})
_SERVICE_VERBS = frozenset({"stop", "restart", "force-reload", "condrestart", "try-restart"})
_LAUNCHCTL_VERBS = frozenset({
    "bootout", "unload", "remove", "kill", "kickstart", "stop", "disable", "submit", "bootstrap",
})
_WINDOWS_SERVICE_VERBS = frozenset({"stop", "restart", "remove", "delete", "pause", "rotate", "set"})
_POWERSHELL_SERVICE = frozenset({"stop-service", "restart-service", "remove-service", "suspend-service",
                                 "set-service"})
_COMPOSE_VERBS = frozenset({"stop", "restart", "kill", "down", "rm", "pause"})
_CONTAINER_VERBS = frozenset({"stop", "restart", "kill", "rm", "pause"})
_KILL_TOOLS = frozenset({"pkill", "killall", "taskkill", "skill"})
_SHELLS = frozenset({"sh", "bash", "zsh", "ksh", "dash", "fish", "pwsh", "powershell", "cmd"})
_SELF_SCRIPTS = frozenset({"uninstall.sh", "uninstall.bat", "update.bat", "update.sh"})
_OPS_ROUTE = re.compile(r"/api/admin/ops/(?:restart|update/apply|update/rollback)\b", re.IGNORECASE)
_SUBSTITUTION_KILL = re.compile(
    r"\bkill\b[^\n;|&]{0,200}?(?:\$\(|`)\s*(?:pgrep|pidof|cat)\b[^)`\n]{0,200}?(?:jarvis|nerva|serve\.py|uvicorn|\.pid)",
    re.IGNORECASE,
)
_PARENT_KILL = re.compile(r"\bkill\b[^\n;|&]{0,200}?\$\{?PPID\b", re.IGNORECASE)
_PEELABLE = frozenset({
    "sudo", "doas", "env", "nohup", "nice", "ionice", "timeout", "setsid", "exec", "command",
    "builtin", "time", "stdbuf", "chrt", "taskset", "unbuffer", "caffeinate", "run0",
})
_PEEL_OPTION_ARGS = {
    "sudo": {"-u", "-g", "-h", "-p", "-c", "-C", "-D", "-r", "-t", "-U"},
    "doas": {"-u", "-C"},
    "env": {"-u", "-C", "-S"},
    "nice": {"-n"},
    "ionice": {"-c", "-n", "-p"},
    "timeout": {"-s", "-k", "--signal", "--kill-after"},
    "stdbuf": {"-i", "-o", "-e"},
    "chrt": set(),
    "taskset": set(),
}
_POSITIONAL_AFTER_PEEL = {"timeout": 1, "chrt": 1, "taskset": 1}
# Words that begin a command wherever they appear in prose. Host power words, "service",
# "kill", "sc" and "net" are ordinary English or too short, so they count only at the
# start of a command segment.
_MID_HEADS = frozenset({
    "systemctl", "launchctl", "pkill", "killall", "taskkill", "nssm", "docker", "podman",
    "docker-compose", "nerva", "sudo", "doas", "nohup", "setsid", "python", "python3",
}) | _POWERSHELL_SERVICE
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
# echo/printf whose words go into a file are data, not a command the job runs.
_DATA_SINK = re.compile(r"\b(?:echo|printf)\b[^\n;|&<>]{0,2000}(?:>>?|\|\s*tee\b)[^\n;|&]{0,400}", re.IGNORECASE)
_SEGMENT_SPLIT = re.compile(r"\n|;|&&|\|\||\||&|\$\(|`|\(|\)|\{|\}")
_SCRIPT_REF = re.compile(
    r"""(?:^|[\s'"=(:,\[])((?:~|\.{1,2}|/)?(?:[\w.@+-]+/)*[\w.@+-]+\.(?:sh|bash|zsh|ksh|py|ps1|bat|cmd|command))\b""",
    re.IGNORECASE,
)
_CLOUD_PLACEHOLDER = ("Mobile Documents", "CloudStorage", "OneDrive", "Dropbox", "Google Drive")
_BINARY_MAGICS = (b"\x7fELF", b"MZ", b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe",
                  b"PK\x03\x04", b"\x1f\x8b")


def _tokens(segment: str) -> list[str]:
    try:
        return shlex.split(segment, comments=False, posix=True)
    except ValueError:
        return segment.split()


def _base(word: str) -> str:
    return re.split(r"[\\/]", word)[-1].lower()


def _peel(tokens: list[str]) -> list[str]:
    """Drop leading assignments and transparent wrappers (sudo, env, nohup, timeout …)."""
    for _ in range(MAX_PREFIX_PEELS):
        while tokens and _ASSIGNMENT.match(tokens[0]):
            tokens = tokens[1:]
        if not tokens or _base(tokens[0]) not in _PEELABLE:
            return tokens
        head = _base(tokens[0])
        tokens = tokens[1:]
        with_arg = _PEEL_OPTION_ARGS.get(head, set())
        while tokens and tokens[0].startswith("-") and tokens[0] != "--":
            option = tokens.pop(0)
            if option in with_arg and tokens:
                tokens.pop(0)
        if tokens and tokens[0] == "--":
            tokens = tokens[1:]
        for _ in range(_POSITIONAL_AFTER_PEEL.get(head, 0)):
            if tokens:
                tokens = tokens[1:]
    return tokens


_POWER_ARG = re.compile(r"-{1,2}[A-Za-z-]+|now|\+\d+|\d{1,2}:\d{2}")


def _explicit_project(lowered: list[str]) -> bool:
    """A compose command naming its file or project (otherwise it acts on the cwd's stack)."""
    return any(arg in ("-f", "--file", "-p", "--project-name") or arg.startswith(("--file=", "--project-name="))
               for arg in lowered)


def _hub_args(args: list[str]) -> bool:
    return any(_HUB_NAME.search(arg) for arg in args)


def _command_finding(tokens: list[str]) -> str | None:
    """A lifecycle finding for one peeled simple command, or None."""
    if not tokens:
        return None
    head = _base(tokens[0]).removesuffix(".exe")
    args = tokens[1:]
    lowered = [arg.lower() for arg in args]
    verbs = [arg for arg in lowered if not arg.startswith("-")]
    if head == "systemctl":
        verb = next((v for v in verbs if v in _SYSTEMCTL_VERBS or v in _HOST_POWER), None)
        if verb in _HOST_POWER:
            return "systemctl power action (stops the hub with the host)"
        if verb is not None and _hub_args(args):
            return f"systemctl {verb} of the Nerva service"
    if tokens[0] in _HOST_POWER and all(_POWER_ARG.fullmatch(arg) for arg in args):
        return f"{tokens[0]} (stops the hub with the host)"
    if head == "service" and len(verbs) >= 2 and verbs[1] in _SERVICE_VERBS and _HUB_NAME.search(verbs[0]):
        return f"service {verbs[1]} of the Nerva service"
    if head == "launchctl" and verbs:
        if verbs[0] == "submit":
            return "launchctl submit (can relaunch anything under a neutral label)"
        if verbs[0] in _LAUNCHCTL_VERBS and _hub_args(args[1:]):
            return f"launchctl {verbs[0]} of the Nerva agent"
    if head in {"nssm", "sc", "net"} and verbs and verbs[0] in _WINDOWS_SERVICE_VERBS | {"config"} \
            and _hub_args(args):
        return f"{head} {verbs[0]} of the Nerva Windows service"
    if head in _POWERSHELL_SERVICE and _hub_args(args):
        return f"{head} of the Nerva Windows service"
    if head in _KILL_TOOLS:
        targets = [arg for arg in args if not arg.startswith("-") and not arg.startswith("/")]
        if head == "taskkill":
            targets = [arg for arg in args if not arg.startswith("/")]
        if any(_HUB_PROCESS.search(target) for target in targets):
            return f"{head} of the Nerva hub process"
    if head == "kill" and any(re.search(r"\$\{?PPID\b", arg) for arg in args):
        return "kill of the parent process (the hub that spawned the job)"
    if head in {"docker", "podman"} and verbs:
        compose = verbs[0] == "compose"
        verb = next((v for v in verbs[1:] if v in _COMPOSE_VERBS), None) if compose else (
            verbs[0] if verbs[0] in _CONTAINER_VERBS else None)
        if compose and verb is not None:
            if _hub_args(args) or not _explicit_project(lowered):
                return f"{head} compose {verb} of the Nerva stack"
        elif verb is not None and _hub_args(args[1:]):
            return f"{head} {verb} of the Nerva container"
    if head == "docker-compose":
        verb = next((v for v in verbs if v in _COMPOSE_VERBS), None)
        if verb is not None and (_hub_args(args) or not _explicit_project(lowered)):
            return f"docker-compose {verb} of the Nerva stack"
    if head == "nerva" or (head.startswith("python") and args[:2] in (["-m", "agents.cli.nerva"], ["-m", "agents.cli"])):
        rest = verbs[1:] if head.startswith("python") else verbs
        if rest[:1] == ["uninstall"] or rest[:2] in (["update", "apply"], ["update", "rollback"]):
            return f"nerva {' '.join(rest[:2])} (replaces or removes the running hub)"
    if head in _SELF_SCRIPTS:
        return f"{head} (removes or updates the running hub)"
    if head in _SHELLS and args and _base(args[0]) in _SELF_SCRIPTS:
        return f"{_base(args[0])} (removes or updates the running hub)"
    return None


def _payloads(tokens: list[str]) -> list[str]:
    """Inline shell payloads (``sh -c '…'``) of a peeled command, to scan in turn."""
    if not tokens or _base(tokens[0]).removesuffix(".exe") not in _SHELLS:
        return []
    for index, arg in enumerate(tokens[1:], start=1):
        if arg in ("-c", "-lc", "-ic", "/c", "-command", "-Command") and index + 1 < len(tokens):
            return [tokens[index + 1]]
    return []


def lifecycle_findings(text: str, *, _depth: int = 0) -> list[str]:
    """Command-shaped findings in *text* that would stop or restart this hub."""
    if not isinstance(text, str) or not text or _depth > MAX_REFERENCED_DEPTH:
        return []
    hits: list[str] = []
    if _OPS_ROUTE.search(text):
        hits.append("call to the hub's own restart/update route")
    if _SUBSTITUTION_KILL.search(text):
        hits.append("kill of the hub via pgrep/pidof/pid-file expansion")
    if _PARENT_KILL.search(text) and "kill of the parent process (the hub that spawned the job)" not in hits:
        hits.append("kill of the parent process (the hub that spawned the job)")
    masked = _DATA_SINK.sub(" ", text)
    # Inline code spans and fenced blocks in a prompt are commands; their backticks are not
    # shell substitutions, so drop them before splitting.
    masked = masked.replace("```", "\n").replace("`", "\n")
    segments = _SEGMENT_SPLIT.split(masked)
    if len(segments) > MAX_SEGMENTS:
        # Fail closed: an unscanned tail could hide the command.
        return ["text too complex to scan for hub lifecycle commands"]
    for segment in segments:
        segment = segment.strip().lstrip("$#> ").strip()
        if not segment:
            continue
        words = _tokens(segment)
        # A prompt embeds commands in prose ("then run systemctl restart jarvis-hub"), so
        # a command may start at any word that only ever begins one; the segment start is
        # always a candidate.
        starts = [0] + [index for index, word in enumerate(words) if index and (
            _base(word).removesuffix(".exe") in _MID_HEADS or _base(word) in _SELF_SCRIPTS)]
        for start in starts:
            tokens = _peel(words[start:start + MAX_COMMAND_WORDS])
            finding = _command_finding(tokens)
            if finding and finding not in hits:
                hits.append(finding)
            for payload in _payloads(tokens):
                for inner in lifecycle_findings(payload, _depth=_depth + 1):
                    if inner not in hits:
                        hits.append(inner)
    return hits


def _python_candidates(source: str) -> tuple[list[str], list[str]]:
    """Command-like strings in Python *source*, and findings no string shows.

    Every string literal is a candidate, and so is every list/tuple of string literals
    joined with spaces — ``subprocess.run(["systemctl", "restart", "jarvis-hub"])``.
    ``os.kill(os.getppid(), …)`` is the hub that spawned the script.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return [source], []
    candidates: list[str] = []
    findings: list[str] = []
    # Simple ``NAME = "text"`` bindings, so ``["systemctl", "restart", unit]`` and
    # ``"systemctl restart " + unit`` read as the command they build.
    names: dict[str, str] = {}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
            names[node.targets[0].id] = node.value.value

    def text_of(item) -> str | None:
        if isinstance(item, ast.Constant) and isinstance(item.value, str):
            return item.value
        if isinstance(item, ast.Name):
            return names.get(item.id)
        if isinstance(item, ast.JoinedStr):
            return "".join(text_of(part.value) or "X" if isinstance(part, ast.FormattedValue)
                           else (text_of(part) or "") for part in item.values)
        if isinstance(item, ast.BinOp) and isinstance(item.op, ast.Add):
            left, right = text_of(item.left), text_of(item.right)
            return None if left is None and right is None else (left or "X") + (right or "X")
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            candidates.append(node.value)
        elif isinstance(node, (ast.List, ast.Tuple)) and node.elts:
            parts = [text_of(item) for item in node.elts]
            if any(part is not None for part in parts):
                candidates.append(shlex.join(part if part is not None else "X" for part in parts))
        elif isinstance(node, (ast.JoinedStr, ast.BinOp)):
            built = text_of(node)
            if built:
                candidates.append(built)
        elif isinstance(node, ast.Call):
            name = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
            if name in {"os.kill", "os.killpg", "kill", "killpg"} and node.args:
                target = ast.unparse(node.args[0])
                if "getppid" in target:
                    findings.append("kill of the parent process (the hub that spawned the job)")
    return candidates, findings


def _read_bounded(path: Path) -> str | None:
    """A referenced script's text: regular file, no symlink at the end, at most 1 MiB.

    Binaries and cloud-placeholder paths (reading them can block on a download) are
    opaque: None. Raises :class:`JobGuardBlocked` when the file exceeds the bound.
    """
    if any(part in str(path) for part in _CLOUD_PLACEHOLDER):
        return None
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            return None
        if info.st_size > MAX_REFERENCED_BYTES:
            raise JobGuardBlocked(f"referenced script {path.name} is larger than "
                                  f"{MAX_REFERENCED_BYTES} bytes and cannot be scanned")
        with os.fdopen(os.dup(fd), "rb") as stream:
            raw = stream.read(MAX_REFERENCED_BYTES + 1)
    finally:
        os.close(fd)
    head = raw[:BINARY_SNIFF_BYTES]
    if b"\x00" in head or head.startswith(_BINARY_MAGICS):
        return None
    return raw.decode("utf-8", errors="replace")


def _resolve_ref(ref: str, base: Path) -> Path:
    """Where a referenced script really is: what runs is the symlink's target, so scan that."""
    path = Path(ref).expanduser()
    return Path(os.path.realpath(path if path.is_absolute() else base / path))


def _scan_source(text: str, *, python: bool, base: Path, depth: int, seen: set, hits: list[str]) -> None:
    candidates, extra = _python_candidates(text) if python else ([text], [])
    for finding in extra:
        if finding not in hits:
            hits.append(finding)
    for candidate in candidates:
        for finding in lifecycle_findings(candidate):
            if finding not in hits:
                hits.append(finding)
    if depth >= MAX_REFERENCED_DEPTH:
        return
    for candidate in candidates:
        for match in _SCRIPT_REF.finditer(candidate):
            if len(seen) >= MAX_REFERENCED_FILES:
                raise JobGuardBlocked("job references more scripts than the guard will scan")
            path = _resolve_ref(match.group(1), base)
            try:
                key = os.stat(path, follow_symlinks=False)
            except OSError:
                continue
            identity = (key.st_dev, key.st_ino)
            if identity in seen:
                continue
            seen.add(identity)
            content = _read_bounded(path)
            if content is None:
                continue
            before = len(hits)
            _scan_source(content, python=path.suffix.lower() == ".py", base=path.parent,
                         depth=depth + 1, seen=seen, hits=hits)
            for index in range(before, len(hits)):
                if " (in " not in hits[index]:
                    hits[index] = f"{hits[index]} (in {path.name})"


def _scripts_root() -> Path:
    from agents.core.paths import data_path

    return data_path("scripts")


def check_lifecycle(*, prompt: str | None = None, script_source: str | None = None,
                    script_name: str | None = None) -> None:
    """Refuse a job whose prompt or script would stop or restart the Nerva hub.

    ``script_source`` is the exact Python a script job runs; ``script_name`` names a
    script under the scripts root to read when the source is not already in hand.
    Scripts referenced from either are read and scanned recursively.
    """
    hits: list[str] = []
    seen: set = set()
    base = _scripts_root()
    if prompt:
        _scan_source(prompt, python=False, base=base, depth=0, seen=seen, hits=hits)
    if script_source is None and script_name:
        path = _resolve_ref(script_name, base)
        try:
            info = os.stat(path, follow_symlinks=False)
            seen.add((info.st_dev, info.st_ino))
        except OSError:
            pass
        script_source = _read_bounded(path)
    if script_source:
        _scan_source(script_source, python=True, base=base, depth=0, seen=seen, hits=hits)
    if hits:
        raise JobGuardBlocked("job would stop or restart the Nerva hub (self-lifecycle guard): "
                              + "; ".join(hits[:6]))


# ── entry points ─────────────────────────────────────────────────────────────


def guard_job(action, options, *, read_scripts: bool = True) -> None:
    """Every write-boundary check for one job's effective action and options.

    Called by create and edit (``read_scripts=True``) and again by fire, where the
    script itself is checked on its exact bytes by ``snapshot_script`` instead.
    """
    if not isinstance(action, dict):
        return
    options = options if isinstance(options, dict) else {}
    prompt = action.get("prompt") if action.get("type") == "ask" else None
    if isinstance(prompt, str) and prompt:
        scan_owner_prompt(prompt, where="job prompt")
    script = None
    if read_scripts:
        for key in ("script", "monitor_script"):
            if isinstance(options.get(key), str) and options[key]:
                script = options[key]
    check_lifecycle(prompt=prompt if isinstance(prompt, str) else None, script_name=script)


# ── the same guard inside a job's own model turn ─────────────────────────────

_JOB_TURN: ContextVar[str | None] = ContextVar("scheduled_job_turn", default=None)
# Tools whose argument is something the host will execute.
_EXECUTING_TOOLS = {"terminal_run": ("command", False), "execute_code": ("code", True)}


@contextmanager
def job_turn_scope(job_id: str):
    """Mark the model turn a scheduled job runs, so its tool calls meet the lifecycle guard."""
    token = _JOB_TURN.set(str(job_id))
    try:
        yield
    finally:
        _JOB_TURN.reset(token)


def job_turn_refusal(tool: str, arguments) -> str | None:
    """A refusal notice when a job's own turn asks to run something that restarts the hub.

    Only adds a refusal: a call it lets through still goes to approval and the kernel
    unchanged (a job turn carries the untrusted origin, so that is an approval card).
    """
    job_id = _JOB_TURN.get()
    if job_id is None or tool not in _EXECUTING_TOOLS or not isinstance(arguments, dict):
        return None
    key, python = _EXECUTING_TOOLS[tool]
    text = arguments.get(key)
    if not isinstance(text, str) or not text:
        return None
    try:
        check_lifecycle(prompt=None if python else text, script_source=text if python else None)
    except JobGuardBlocked as exc:
        logger.warning("scheduled job %s: tool call refused by the self-lifecycle guard", job_id)
        return f"Refused for scheduled job {job_id}: {exc}"
    return None
