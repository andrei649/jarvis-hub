"""Terminal execution contract: hardline denylist + ``terminal.exec`` kernel kind.

Pure, offline policy for a governed shell command on a named target. Nothing
here spawns anything; the transport (``local_transport.py``) and the runner
(``execution.py``) consume these decisions. Two layers, in order:

1. **HARDLINE** — a static denylist evaluated *first*, before target policy,
   before the kernel, before any autonomy level. A hardline match is
   ``hardline_denied:<name>`` regardless of who asks or what was approved. The
   list is deliberately about catastrophic, non-recoverable host effects
   (wiping a filesystem, writing raw block devices, fork bombs, piping the
   network into a shell, power-cycling the box, disabling security controls).
   It stays ON for container targets too: a cheap check that never spawns is
   worth more than a clever exception. Because the promise is "regardless of
   approval", the scan runs over *more* spellings than the one submitted: the
   payload of a shell wrapper (``sh -cx``, ``bash -lc``, ``cmd /c``,
   ``powershell -Command``) is screened as its own command, and intra-word
   quoting/escapes (``mk""fs``) are collapsed. Every extra spelling can only
   *add* a refusal — none can clear one — and every payload that is found is
   screened, never dropped to stay inside a budget, because a budget the
   caller can fill with decoy segments is not a floor. The budget limits one
   thing only: how far a payload is unwrapped *again*. The set is deliberately
   **not** exhaustive. ``_detection_variants`` lists the gaps this module knows
   about — a list of known gaps, not a proof that there are no others, and the
   review that produced the current list found five it did not have.
2. **TERMINAL_EXEC_CONTRACT** — the ``ContractTemplate`` for the kernel kind
   ``terminal.exec``: target/backend present, argv fingerprinted, cwd inside
   the configured roots, timeout bounded, a durable approved task presented.
   ``requires_approval`` is always ``True`` — shell effects are not
   automatically reversible, so the manifest rollback mode is ``none`` and the
   tier floor is the approval queue.

Kernel registration (``kernel/registry.py``, ``action_auth.json``,
``capability_manifests.py``) is integrator work; this module only defines the
kind constant and the contract so nothing self-authorizes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from agents.core.automation_contracts import ContractTemplate, predicate

TERMINAL_EXEC_KIND = "terminal.exec"
TERMINAL_BACKENDS = frozenset({"local", "docker", "ssh"})
DEFAULT_TIMEOUT_S = 60
MAX_TIMEOUT_S = 600
MAX_ARGV_ITEMS = 64
MAX_ARG_CHARS = 4000

_TARGET_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class HardlinePattern:
    """One static denylist entry: a stable name and a case-insensitive regex."""

    name: str
    pattern: str

    def __post_init__(self) -> None:
        name = str(self.name or "").strip()
        if not re.fullmatch(r"[a-z0-9_]{1,48}", name):
            raise ValueError("hardline pattern name must be a short snake_case token")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "_regex", re.compile(self.pattern, re.IGNORECASE))

    def matches(self, text: str) -> bool:
        return self._regex.search(text) is not None  # type: ignore[attr-defined]


# Filesystem roots whose recursive removal / permission rewrite is never allowed.
_ROOT_OPERANDS = frozenset({
    "/", "/*", "~", "~/", "~/*", "*", "$home", "$home/", "${home}", "%userprofile%",
    "/home", "/home/*", "/users", "/users/*", "/etc", "/usr", "/bin", "/sbin", "/lib",
    "/lib64", "/boot", "/var", "/sys", "/dev", "/proc", "/opt", "/root", "/system",
    "/library", "/applications", "c:\\", "c:\\*", "c:/", "c:/*", "c:", "\\", "\\*",
})

# `busybox` is here as well as in `_POSIX_SHELLS`: it is both. `busybox sh -c …`
# is a shell, and `busybox mkfs.ext4 /dev/sda` is an applet invocation that puts
# the real command one token to the right — the same shape as `sudo`/`env`, and
# the standard shape on exactly the container targets this module says it keeps
# the floor on.
_WRAPPERS = frozenset({"sudo", "doas", "env", "nice", "nohup", "xargs", "time", "command",
                       "exec", "busybox"})

# Shells whose ``-c`` payload is a command line in its own right. A floor whose
# promise is "regardless of who approved it" cannot be bypassed by writing
# `sh -c '<the same thing>'`, so the payload is screened as its own command.
# Both families are listed: four HARDLINE entries exist only for Windows
# (diskpart, format_drive, registry_hklm_delete, windows_root_wipe) and two more
# carry Windows-only branches (netsh / Set-MpPreference inside `security_disable`,
# Stop-Computer / Restart-Computer inside `power_cycle`), and ``parse_argv`` has
# an explicit ``windows=`` branch, so a Windows target is a supported shape.
_POSIX_SHELLS = frozenset({
    "sh", "bash", "zsh", "dash", "ksh", "ash", "busybox", "fish", "csh", "tcsh",
})
_WINDOWS_SHELLS = frozenset({"cmd", "powershell", "pwsh"})

# The flag that introduces an inline command line, per family. Generous on
# purpose: under-matching is exactly what let `sh -cx <catastrophe>` through the
# floor.
#
# Over-matching used to be able to CLEAR a refusal, and the reason is worth
# keeping written down. The payload used to be taken as the token immediately
# after the first flag-shaped word, and the search then stopped — so
# `powershell /c -Command Stop-Computer` screened `-Command`, found nothing and
# returned None, while `powershell -Command Stop-Computer` refused. The scan now
# steps over options to the first non-option operand, the way a shell does, so an
# extra flag-shaped word costs nothing.
# Any single-dash short *cluster* containing `c` counts, wherever `c` sits in
# it — `sh -c`, `bash -lc` and `sh -cx` are the same invocation.
_POSIX_C_FLAG_RE = re.compile(r"-[a-z]*c[a-z]*")
# `cmd /c`, `cmd /k`, `powershell -Command` with the prefix abbreviations
# PowerShell accepts, and the `-c` alias.
_WINDOWS_C_FLAG_RE = re.compile(r"[-/](?:c|k|co|com|comm|comma|comman|command)")

_MAX_SHELL_DEPTH = 2
# Bounds *re-expansion* only. A payload beyond this many is still screened as a
# command in its own right; it is merely not unwrapped one level further. A cap
# that skipped the scan instead would let a caller bury the real payload behind
# cheap decoy segments it controls the order of.
_MAX_SHELL_EXPANSIONS = 8

# De-obfuscation neighbours: a quote or backslash only *hides* a command name
# when it sits between ordinary word characters (``mk""fs``, ``m\kfs``). Shell
# operators and whitespace are excluded on purpose — collapsing `print("hi")`
# into `print(hi)` would hand `_CMD` a fake command position after the paren.
_OBF_NEIGHBOUR = r"[^\s;&|(){}<>`]"
_INTRA_QUOTE_RE = re.compile(rf"(?<={_OBF_NEIGHBOUR})[\"'](?={_OBF_NEIGHBOUR})")
_INTRA_ESCAPE_RE = re.compile(rf"\\(?={_OBF_NEIGHBOUR})")

# A "command position": start of the text or right after a shell operator, with
# optional privilege/wrapper prefixes. Anchoring here keeps `echo shutdown` or a
# commit message mentioning mkfs from tripping the line, while `foo; shutdown`
# and `sudo mkfs` still do.
# What may sit between a command position and the command itself. Everything here
# is a shape a shell steps over on its way to the word it will execute, and each
# was a live miss before it was listed: `{ mkfs.ext4 /dev/sda; }` (a brace group
# is a command position and `{` was not in the operator class), `if true; then
# mkfs.ext4 /dev/sda; fi` (a compound-command keyword), `FOO=1 mkfs.ext4
# /dev/sda` and `env FOO=1 mkfs.ext4 /dev/sda` (an assignment prefix, which the
# shell consumes before deciding what to run).
_CMD = (r"(?:^|[;&|(`{]\s*)"
        r"(?:(?:then|do|else|elif)\s+)*"
        r"(?:[a-z_][a-z0-9_]*=\S*\s+)*"
        r"(?:(?:sudo|doas|env|nice|nohup|xargs|time|command|exec|busybox)\s+"
        r"(?:-\S+\s+|[a-z_][a-z0-9_]*=\S*\s+)*)*")

HARDLINE: tuple[HardlinePattern, ...] = (
    HardlinePattern("mkfs", _CMD + r"mkfs(?:\.[a-z0-9]+)?\b"),
    HardlinePattern("dd_block_device", _CMD + r"dd\b.*\bof=/dev/"),
    HardlinePattern("raw_device_write", r">\s*/dev/(?:sd|hd|nvme|disk|mmcblk|xvd|vd|loop)"),
    HardlinePattern("wipefs", _CMD + r"wipefs\b"),
    HardlinePattern("shred_device", _CMD + r"shred\b.*\s/dev/"),
    HardlinePattern("diskpart", _CMD + r"diskpart(?:\.exe)?\b"),
    HardlinePattern("format_drive", _CMD + r"format(?:\.com)?\s+[a-z]:"),
    HardlinePattern("find_root_delete", _CMD + r"find\s+(?:/|~|\$home)(?:\s.*)?\s-delete\b"),
    HardlinePattern(
        "fork_bomb",
        r":\s*\(\s*\)\s*\{[^}]*:\s*\|\s*:\s*&[^}]*\}\s*;\s*:|%0\s*\|\s*%0",
    ),
    HardlinePattern(
        "network_to_shell",
        r"\b(?:curl|wget|invoke-webrequest|iwr)\b.*\|\s*(?:sudo\s+)?(?:ba|z|k|da|fi)?sh\b",
    ),
    HardlinePattern(
        "power_cycle",
        _CMD + r"(?:shutdown|reboot|halt|poweroff|init\s+[06]|telinit\s+[06]|"
        r"systemctl\s+(?:poweroff|halt|reboot|kexec)|stop-computer|restart-computer)"
        r"(?:\.exe)?\b",
    ),
    HardlinePattern(
        "registry_hklm_delete",
        _CMD + r"reg(?:\.exe)?\s+delete\s+(?:hklm|hkey_local_machine)\b",
    ),
    HardlinePattern(
        "windows_root_wipe",
        _CMD + r"(?:rd|rmdir|del|erase)(?:\.exe)?\b(?:\s+/[sqf])+\s+"
        r"(?:[a-z]:\\?\*?|\\|%systemroot%|%windir%)(?:\s|$)",
    ),
    HardlinePattern(
        "recursive_root_chmod",
        _CMD + r"ch(?:mod|own|grp)\s+(?:-[a-z]+\s+)*(?:[0-7]{3,4}|[a-z:.]+)\s+(?:/|/\*|~)(?:\s|$)",
    ),
    HardlinePattern("kill_everything", _CMD + r"kill\s+(?:-9\s+|-kill\s+|-s\s+kill\s+)?-1(?:\s|$)"),
    HardlinePattern("crontab_wipe", _CMD + r"crontab\s+(?:-[a-z]+\s+)*-r\b"),
    HardlinePattern("auth_file_overwrite", r">\s*/etc/(?:passwd|shadow|sudoers|fstab)\b"),
    HardlinePattern(
        "security_disable",
        _CMD + r"(?:iptables\s+(?:-t\s+\w+\s+)?(?:-F|--flush)\b|ufw\s+disable\b|setenforce\s+0\b|"
        r"systemctl\s+(?:stop|disable|mask)\s+(?:firewalld|ufw|apparmor|auditd)\b|"
        r"set-mppreference\b.*-disablerealtimemonitoring|"
        r"netsh\s+advfirewall\s+set\s+\w+\s+state\s+off)",
    ),
)


def _unquoted_lines(command: str) -> list[str]:
    """*command* split at newlines that are outside quotes.

    Deliberately not ``str.splitlines()``: a newline inside `\'` or `"` is part of
    a string literal, and splitting there would put ordinary prose into a command
    position and refuse it. Backslash-escapes are honoured so ``\\"`` inside a
    double-quoted string does not close it. An unterminated quote leaves the rest
    of the input as one line, which is the conservative reading.
    """
    lines: list[str] = []
    current: list[str] = []
    quote = ""
    index = 0
    while index < len(command):
        char = command[index]
        if quote == '"' and char == "\\" and index + 1 < len(command):
            current.append(char)
            current.append(command[index + 1])
            index += 2
            continue
        if quote:
            if char == quote:
                quote = ""
            current.append(char)
        elif char in "'\"":
            quote = char
            current.append(char)
        elif char in "\r\n":
            lines.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    lines.append("".join(current))
    return [line for line in lines if line.strip()] or [""]


def _normalize(command: str | Sequence[str]) -> tuple[str, tuple[tuple[str, ...], ...]]:
    """Return ``(flat_text, segments)`` for either a command string or an argv.

    A command *string* may be destined for a shell (the docker path), so it is
    split at shell operators into segments and each segment is screened on its
    own; an argv *sequence* never meets a shell and is one segment.
    """
    if isinstance(command, str):
        # `flat` is what the HARDLINE patterns match, and `_CMD`'s command-position
        # anchor is `^` or one of `;&|(\``. Squeezing an unquoted newline into a
        # space leaves no anchor, so line 2 of a payload was never in command
        # position. A newline IS a `;` to a shell, so it is spelled as one here.
        lines = _unquoted_lines(command)
        text = "; ".join(lines)
        segments: list[tuple[str, ...]] = []
        # An UNQUOTED newline is a statement separator in a shell, exactly like
        # `;` — and a `sh -c` payload is a shell script, so this is the most
        # ordinary shape one takes. Before this the newline reached `shlex` with
        # `whitespace_split=True`, which squeezes it into a space, so nothing ever
        # occupied a command position on line 2 and `sh -c 'echo hi\nmkfs.ext4
        # /dev/sda'` passed the floor. Splitting is quote-aware: a newline INSIDE
        # quotes is data, and splitting there would screen ordinary text as a
        # command.
        for line in lines:
            try:
                lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
                lexer.whitespace_split = True
                tokens = tuple(lexer)
            except ValueError:
                tokens = tuple(line.split())
            current: list[str] = []
            for token in tokens:
                if token and all(char in ";&|" for char in token):
                    if current:
                        segments.append(tuple(current))
                    current = []
                else:
                    current.append(token)
            if current:
                segments.append(tuple(current))
    else:
        segments = [tuple(str(item) for item in command)]
        text = " ".join(segments[0])
    flat = _WS_RE.sub(" ", str(text or "")).strip().lower()
    return flat, tuple(segments)


def _recursive_root_removal(tokens: Sequence[str]) -> bool:
    """``rm -rf /``-style deletions (any flag spelling, any root operand)."""
    if not tokens:
        return False
    head = 0
    lowered = [str(token).strip().lower() for token in tokens]
    while head < len(lowered) and lowered[head] in _WRAPPERS:
        head += 1
    if head >= len(lowered) or lowered[head] not in {"rm", "/bin/rm", "/usr/bin/rm"}:
        return False
    recursive = False
    for token in lowered[head + 1:]:
        if token == "--recursive" or (  # nosec B105 - a CLI flag in the rm -rf detector, not a secret
            token.startswith("-") and not token.startswith("--") and "r" in token
        ):
            recursive = True
            break
    if not recursive:
        return False
    return any(
        token.rstrip("/") in _ROOT_OPERANDS or token in _ROOT_OPERANDS
        for token in lowered[head + 1:]
        if not token.startswith("-")
    )


def _basename(token: str) -> str:
    """Last path component of a command word (``/bin/sh`` -> ``sh``)."""
    return token.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]


def _shell_name(token: str) -> str:
    """Basename of a command word with a Windows ``.exe`` suffix dropped.

    ``C:\\Windows\\System32\\cmd.exe`` and ``sh.exe`` name the same shells as
    ``cmd`` and ``sh``; keeping the extension would hide the payload.
    """
    name = _basename(token)
    return name[:-4] if name.endswith(".exe") else name


def _shell_c_payloads(command: str | Sequence[str]) -> tuple[str, ...]:
    """Payloads of ``sh -c <payload>``-style invocations, at most one per segment.

    Head tokens in ``_WRAPPERS`` are skipped exactly as ``_recursive_root_removal``
    skips them, so ``sudo sh -c ...`` and ``env bash -lc ...`` are seen. The head
    is matched on its shell name (basename, ``.exe`` dropped), so ``/bin/sh -c``,
    ``sh.exe -c`` and ``busybox sh -c`` are covered too. The first following
    argument whose shape is that family's payload flag marks the *next* argument
    as the payload.

    Known gap: only the single argument after the flag is taken. That is exactly
    right for a POSIX shell (later words become ``$0``/``$@``), but ``cmd /c a b``
    re-parses *all* remaining words as one command line, so a ``cmd``/``powershell``
    payload spread over several argv items is not reassembled here. Joining them
    would re-introduce the string-splitting that ``_deobfuscated`` avoids on
    purpose, so it stays a disclosed gap rather than a guess.
    """
    try:
        _, segments = _normalize(command)
    except Exception:
        return ()
    payloads: list[str] = []
    for segment in segments:
        lowered = [str(token).strip().lower() for token in segment]
        head = 0
        while head < len(lowered) and lowered[head] in _WRAPPERS:
            head += 1
        if head >= len(lowered):
            continue
        name = _shell_name(lowered[head])
        if name in _POSIX_SHELLS:
            flag_re = _POSIX_C_FLAG_RE
        elif name in _WINDOWS_SHELLS:
            flag_re = _WINDOWS_C_FLAG_RE
        else:
            continue
        for index in range(head + 1, len(segment) - 1):
            if not flag_re.fullmatch(lowered[index]):
                continue
            # A real shell keeps parsing options after -c and runs the first
            # NON-OPTION operand as the script. Taking ``index + 1`` on faith meant
            # a single decoy option skipped the payload and screened the option
            # instead: `sh -c -x 'mkfs.ext4 /dev/sda'`, `sh -c -- 'rm -rf /'`,
            # `sh -c -e …`, `sh -c -u …` all execute — verified against dash and
            # bash — and all returned None from this floor. `--` ends option
            # parsing, so the operand is the token after it.
            cursor = index + 1
            while cursor < len(segment):
                token = lowered[cursor]
                if token == "--":
                    cursor += 1
                    break
                if len(token) > 1 and token.startswith("-"):
                    cursor += 1
                    continue
                break
            if cursor < len(segment):
                payload = str(segment[cursor])
                if payload.strip():
                    payloads.append(payload)
            break
    return tuple(payloads)


def _deobfuscated(command: str | Sequence[str]) -> str | Sequence[str] | None:
    """The command with intra-word quotes and escapes dropped, or ``None``.

    Type-preserving on purpose: an argv stays an argv, so collapsing a quote
    inside one argument can never turn a literal ``;`` in that argument into a
    segment break that a string command would have had.
    """
    def strip(text: str) -> str:
        return _INTRA_QUOTE_RE.sub("", _INTRA_ESCAPE_RE.sub("", text))

    if isinstance(command, str):
        plain = strip(command)
        return plain if plain != command else None
    try:
        tokens = [str(item) for item in command]
    except Exception:
        return None
    plain_tokens = [strip(token) for token in tokens]
    return plain_tokens if plain_tokens != tokens else None


def _detection_variants(command: str | Sequence[str]) -> Iterator[str | Sequence[str]]:
    """Yield the command plus every other spelling of it the scan must see.

    Variant 0 is the command as given, so an existing match keeps its existing
    name. Then the payloads of shell wrappers (recursive, depth-capped), then a
    de-obfuscated copy of each, in that order.

    **Every payload found is yielded.** The caps bound how far a payload is
    *re-expanded*, never whether it is screened, because the caller chooses the
    order: capping the yields let seven cheap decoy ``sh -c ok; `` segments push
    a trailing ``sh -c 'mkfs…'`` out of the scan entirely. Work stays bounded
    anyway — level-1 payloads are substrings of the input, and only
    ``_MAX_SHELL_EXPANSIONS`` of them are unwrapped again.

    Spellings this deliberately does **not** reach, so nobody reads it as total:
    nesting deeper than ``_MAX_SHELL_DEPTH``; a quote at a word *boundary*
    (``'mkfs.ext4' /dev/sda``) rather than inside a word; payloads of non-shell
    interpreters (``python -c``, ``perl -e``, ``node -e``) — left alone on
    purpose, since ``jobs_scripts.snapshot_script`` legitimately builds
    ``[sys.executable, '-I', '-c', source]``; ``powershell -EncodedCommand``
    base64; a ``cmd /c`` payload split across several argv items; and an
    obfuscated shell HEAD in argv form (``['s""h', '-c', …]``), because the
    de-obfuscation pass runs after payload extraction and its output is not fed
    back through it.

    This list is what the module knows it misses, not a proof of completeness.
    An adversarial review of the list itself found five entries missing from it —
    a decoy option between ``-c`` and the payload, a newline inside a payload, an
    assignment prefix, a brace group and a compound-command keyword position.
    Those are closed rather than listed; the point of recording it here is that
    the next five are found the same way, by somebody trying.
    """
    yield command
    produced: list[str | Sequence[str]] = [command]
    seen: set[str] = set()
    layer: list[str | Sequence[str]] = [command]
    for _ in range(_MAX_SHELL_DEPTH):
        following: list[str] = []
        for item in layer:
            for payload in _shell_c_payloads(item):
                if payload in seen:
                    continue
                seen.add(payload)
                yield payload
                produced.append(payload)
                # Re-expansion is the only step that can fan out, so it is the
                # only step the cap touches; the payload was screened above
                # either way. A payload longer than one legal argument is also
                # not re-expanded.
                if len(payload) <= MAX_ARG_CHARS and len(following) < _MAX_SHELL_EXPANSIONS:
                    following.append(payload)
        if not following:
            break
        layer = following
    for item in produced:
        plain = _deobfuscated(item)
        if plain is None:
            continue
        key = plain if isinstance(plain, str) else "\x00".join(plain)
        if key in seen:
            continue
        seen.add(key)
        yield plain


def _scan_one(command: str | Sequence[str]) -> str | None:
    """The hardline scan for a single spelling of a command."""
    flat, segments = _normalize(command)
    if not flat:
        return None
    if any(_recursive_root_removal(segment) for segment in segments):
        return "recursive_root_removal"
    for entry in HARDLINE:
        if entry.matches(flat):
            return entry.name
    return None


def hardline_match(command: str | Sequence[str] | Iterable[str]) -> str | None:
    """Return the name of the first hardline entry the command hits, else ``None``.

    Accepts a raw command string or any iterable of argv words. Static,
    case-insensitive, never raises for ordinary input; a normalization failure of
    the command as given is a match on nothing (the caller still fails closed on
    invalid argv shapes), and a shape that is not even iterable is
    ``"unparseable"``.

    A non-string command is materialised **once**, up front: ``_detection_variants``
    reads the command several times, and a one-shot iterator would otherwise be
    drained by the variant pass and reach the scan empty — turning a refusal
    ``hardline_match(["rm", "-rf", "/"])`` makes into a miss.

    Each command is then screened in every spelling ``_detection_variants``
    yields — as given, unwrapped from a shell wrapper, and de-obfuscated — so the
    floor holds for ``sh -c 'mkfs.ext4 /dev/sda'`` exactly as it does for the
    bare spelling. That set is bounded but never truncated mid-scan, and it is
    not exhaustive: ``_detection_variants`` lists what it does not reach.
    """
    if not isinstance(command, str):
        try:
            command = list(command)  # type: ignore[arg-type]
        except Exception:
            return "unparseable"
    for index, variant in enumerate(_detection_variants(command)):
        try:
            hit = _scan_one(variant)
        except Exception:
            if index == 0:
                return "unparseable"
            continue
        if hit is not None:
            return hit
    return None


def argv_fingerprint(argv: Sequence[str]) -> str:
    """SHA-256 over the canonical JSON encoding of the argv list."""
    canonical = json.dumps(
        [str(item) for item in argv], ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _valid_argv(value: Any) -> bool:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        return False
    items = list(value)
    if not items or len(items) > MAX_ARGV_ITEMS:
        return False
    if not all(isinstance(item, str) and item != "" and len(item) <= MAX_ARG_CHARS for item in items):
        return False
    return "\x00" not in items[0] and all("\x00" not in item for item in items)


def _abs_norm(path: Any) -> str | None:
    text = str(path or "").strip()
    if not text:
        return None
    return os.path.normcase(os.path.normpath(os.path.abspath(text)))


def cwd_inside_roots(cwd: Any, roots: Any) -> bool:
    """Pure (no filesystem access) containment check: ``cwd`` is under a root."""
    target = _abs_norm(cwd)
    if target is None or isinstance(roots, (str, bytes)) or not isinstance(roots, Sequence):
        return False
    for root in roots:
        base = _abs_norm(root)
        if base is None:
            continue
        if target == base or target.startswith(base.rstrip(os.sep) + os.sep):
            return True
    return False


def _valid_timeout(view: Mapping[str, Any]) -> bool:
    timeout = view.get("timeout")
    ceiling = view.get("max_timeout", MAX_TIMEOUT_S)
    if isinstance(timeout, bool) or not isinstance(timeout, int):
        return False
    if isinstance(ceiling, bool) or not isinstance(ceiling, int) or ceiling <= 0:
        return False
    return 1 <= timeout <= min(ceiling, MAX_TIMEOUT_S)


def _valid_task_id(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _terminal_exec_contract_template() -> ContractTemplate:
    return ContractTemplate(
        kind=TERMINAL_EXEC_KIND,
        description=(
            "A governed shell command: argv only, fingerprinted, cwd-jailed, "
            "time-bounded, hardline-screened and held for durable approval."
        ),
        constraints=(
            predicate(
                "terminal-kind",
                lambda view, _now: view.get("kind") == TERMINAL_EXEC_KIND,
                reason="invalid_kind",
            ),
            predicate(
                "has-target",
                lambda view, _now: _TARGET_RE.fullmatch(str(view.get("target") or "")) is not None,
                reason="invalid_target",
            ),
            predicate(
                "known-backend",
                lambda view, _now: view.get("backend") in TERMINAL_BACKENDS,
                reason="invalid_backend",
            ),
            predicate(
                "argv-shape",
                lambda view, _now: _valid_argv(view.get("argv")),
                reason="invalid_argv",
            ),
            predicate(
                "argv-fingerprint",
                lambda view, _now: (
                    _SHA256_RE.fullmatch(str(view.get("argv_sha256") or "")) is not None
                    and view.get("argv_sha256") == argv_fingerprint(view.get("argv"))
                ),
                reason="argv_fingerprint_mismatch",
            ),
            predicate(
                "hardline",
                lambda view, _now: hardline_match(view.get("argv")) is None,
                reason="hardline_denied",
            ),
            predicate(
                "cwd-inside-roots",
                lambda view, _now: cwd_inside_roots(view.get("cwd"), view.get("roots")),
                reason="cwd_outside_roots",
            ),
            predicate("timeout-bounded", lambda view, _now: _valid_timeout(view),
                      reason="invalid_timeout"),
            predicate(
                "durable-approval",
                lambda view, _now: _valid_task_id(view.get("approved_task_id")),
                reason="approval_missing",
            ),
        ),
        requires_approval=True,
    )


TERMINAL_EXEC_CONTRACT = _terminal_exec_contract_template()


def terminal_exec_payload(
    *,
    target: str,
    backend: str,
    argv: Sequence[str],
    cwd: str,
    roots: Sequence[str],
    timeout: int,
    approved_task_id: int | None,
    max_timeout: int = MAX_TIMEOUT_S,
) -> dict[str, Any]:
    """Build the canonical ``terminal.exec`` view the contract and kernel see."""
    argv_list = [str(item) for item in argv]
    return {
        "kind": TERMINAL_EXEC_KIND,
        "target": str(target),
        "backend": str(backend),
        "argv": argv_list,
        "argv_sha256": argv_fingerprint(argv_list),
        "cwd": str(cwd),
        "roots": [str(root) for root in roots],
        "timeout": timeout,
        "max_timeout": max_timeout,
        "approved_task_id": approved_task_id,
    }


__all__ = [
    "DEFAULT_TIMEOUT_S",
    "HARDLINE",
    "HardlinePattern",
    "MAX_ARGV_ITEMS",
    "MAX_ARG_CHARS",
    "MAX_TIMEOUT_S",
    "TERMINAL_BACKENDS",
    "TERMINAL_EXEC_CONTRACT",
    "TERMINAL_EXEC_KIND",
    "argv_fingerprint",
    "cwd_inside_roots",
    "hardline_match",
    "terminal_exec_payload",
]
