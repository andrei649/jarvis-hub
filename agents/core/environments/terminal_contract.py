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
   ``powershell -Command``) is screened as its own command, a command word is
   read by its basename so ``/sbin/mkfs.ext4`` is ``mkfs``, and intra-word
   quoting/escapes (``mk""fs``) are collapsed. Every extra spelling can only
   *add* a refusal — none can clear one — and every payload that is found is
   both screened *and* unwrapped again, because a budget the caller can fill
   with decoy segments is not a floor and a re-expansion budget spent in
   encounter order is exactly that. Only nesting DEPTH is capped; breadth needs
   no cap, because the payloads at one level are disjoint substrings of the
   level above, so the whole expansion is linear in the input. The set is
   deliberately **not** exhaustive. ``_detection_variants`` lists the gaps this
   module knows about — a list of known gaps, not a proof that there are no
   others, and the two reviews that produced the current list found eleven it
   did not have.
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

# The ONLY cap on the variant scan, and the only one that can be one: nesting
# depth. A breadth cap moved the bypass rather than closing it — the caller picks
# the encounter order, so eight cheap `sh -c ok` segments in front of a
# `sh -c "sh -c 'mkfs…'"` spent the whole re-expansion budget and the real
# payload was never unwrapped. Breadth needs no cap anyway: at most one payload
# is taken per segment and a payload is a token of the level above, so the
# payloads at each level are disjoint substrings of the input and the total work
# is linear in it.
_MAX_SHELL_DEPTH = 2

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
# `{` is a command position only when the shell reads it as a WORD — POSIX requires
# whitespace after it (`{ cmd; }`). Anchoring on a bare `{` made
# `jq '{reboot: .needs_reboot}'` a power_cycle refusal, which is precisely the
# "a commit message mentioning mkfs must not trip this" case two lines up.
# A command word may carry a DIRECTORY PREFIX, and `/` is not one of the anchors
# above: `/sbin/mkfs.ext4 /dev/sda` and `mkfs.ext4 /dev/sda` are the same program,
# so every anchored entry was one absolute path away from being skipped. Spelled
# as repeated `component/` chunks rather than `.*[/\\]` so the match is
# deterministic (no backtracking over a long word), and `=` is excluded so a bare
# assignment (`FOO=/sbin/mkfs.ext4`) stays an assignment instead of becoming a
# command position.
_PATH_PREFIX = r"(?:[^\s;&|(){}<>`'\"=/\\]*[/\\])*"
_CMD = (r"(?:^|[;&|(`]\s*|\{\s+)"
        r"(?:(?:then|do|else|elif)\s+)*"
        r"(?:[a-z_][a-z0-9_]*=\S*\s+)*"
        r"(?:" + _PATH_PREFIX +
        r"(?:sudo|doas|env|nice|nohup|xargs|time|command|exec|busybox)\s+"
        r"(?:-\S+\s+|[a-z_][a-z0-9_]*=\S*\s+)*)*"
        + _PATH_PREFIX)

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
        r"\b(?:curl|wget|invoke-webrequest|iwr)\b.*\|\s*(?:sudo\s+)?"
        + _PATH_PREFIX + r"(?:ba|z|k|da|fi)?sh\b",
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
        if not quote and char == "\\" and command[index + 1:index + 2] in ("\r", "\n"):
            # A line continuation, NOT a statement separator: the shell splices the
            # two lines into one command and removes both characters. Splitting here
            # invented a command position the shell does not have
            # (`ansible-playbook -i hosts \` + newline + `reboot.yml` became
            # `...; reboot.yml` and tripped power_cycle) and broke one the shell does
            # join (`mk\` + newline + `fs.ext4 /dev/sda` runs as `mkfs.ext4`).
            index += 2
            if command[index - 1] == "\r" and command[index:index + 1] == "\n":
                index += 1
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


_HEREDOC_DELIM_RE = re.compile(r"-?[ \t]*(?:'([^']*)'|\"([^\"]*)\"|([A-Za-z_][A-Za-z0-9_]*))")


def _heredoc_open(line: str) -> tuple[int, str] | None:
    """``(offset, delimiter)`` of the first real heredoc redirection on *line*.

    ``<<`` by itself is not a heredoc, and reading it as one is expensive: the
    rest of the input is marked as body, which is the whole newline screening
    switched off. So this is quote- and context-aware. ``<<`` inside quotes is
    text (`grep "<<<<<<< HEAD" src/x.py`, `echo "a<<b"`), ``<<`` inside
    ``$(( ))`` is the arithmetic shift operator (`echo $((1 << n))`), and ``<<<``
    is a here-STRING, which has no body at all.
    """
    index = 0
    quote = ""
    while index < len(line):
        char = line[index]
        if quote:
            if char == "\\" and quote == '"' and index + 1 < len(line):
                index += 2
                continue
            if char == quote:
                quote = ""
            index += 1
            continue
        if char in "'\"":
            quote = char
            index += 1
            continue
        if char == "\\":
            index += 2
            continue
        if char == "(" and line[index + 1:index + 2] == "(":
            close = line.find("))", index + 2)
            index = len(line) if close < 0 else close + 2
            continue
        if char == "<" and line[index + 1:index + 2] == "<":
            if line[index + 2:index + 3] == "<":
                index += 3
                continue
            match = _HEREDOC_DELIM_RE.match(line, index + 2)
            if match is not None:
                delimiter = next(g for g in match.groups() if g is not None)
                if delimiter:
                    return index, delimiter
            index += 2
            continue
        index += 1
    return None


def _heredoc_feeds_a_shell(prefix: str) -> bool:
    """Does the command this heredoc redirects into EXECUTE the body?

    ``cat <<EOF`` hands the body to a program that prints it; ``bash <<EOF``,
    ``sh <<'EOF'`` and ``bash -s <<EOF`` hand it to a shell, which runs every
    line of it — so treating those lines as data was a hole straight through the
    floor. Only the last pipeline stage before the ``<<`` owns the redirection,
    which is why *prefix* is the text left of it: ``cat x | sh <<EOF`` counts and
    ``bash --version; cat <<EOF`` does not.
    """
    try:
        lexer = shlex.shlex(prefix, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = [str(token).strip().lower() for token in lexer]
    except ValueError:
        tokens = [token.strip().lower() for token in prefix.split()]
    stage: list[str] = []
    for token in tokens:
        if token and all(char in ";&|" for char in token):
            stage = []
        else:
            stage.append(token)
    return _shell_head(stage) is not None


def _heredoc_body(lines: list[str]) -> list[bool]:
    """Per line: is it the BODY of a heredoc rather than a statement?

    A heredoc body is text the shell feeds to a command's stdin — it never parses
    those lines as commands, so joining them with `;` invented command positions
    that do not exist. Writing a config file through
    `cat > x <<'EOF'` / `shutdown: graceful` / `EOF` was refused as `power_cycle`,
    which is the exact case `_CMD`'s docstring promises not to trip.

    The body is still screened, just not as a statement: `_normalize` joins these
    lines with a space instead of `; `. That keeps command SUBSTITUTION inside an
    unquoted heredoc caught — `$(mkfs.ext4 /dev/sda)` carries its own `(` anchor —
    while ordinary data lines stop being read as commands.

    Two things make a heredoc real, and both are checked here because each was a
    way to switch the newline screening off: the ``<<`` has to be a redirection
    rather than quoted text or an arithmetic shift (``_heredoc_open``), and the
    delimiter has to come BACK. An invented delimiter that never reappears is not
    a heredoc, so those lines stay statements — an unterminated real heredoc lands
    there too, which is the conservative direction.

    Nesting and multiple heredocs on one line are not modelled: the first
    delimiter on a line wins and the body runs to the next line equal to it.
    """
    body = [False] * len(lines)
    index = 0
    while index < len(lines):
        opened = _heredoc_open(lines[index])
        if opened is None:
            index += 1
            continue
        offset, delimiter = opened
        start = index + 1
        end = next(
            (
                position
                for position in range(start, len(lines))
                if lines[position].strip().lstrip("\t") == delimiter
            ),
            None,
        )
        if end is None:
            index += 1
            continue
        if not _heredoc_feeds_a_shell(lines[index][:offset]):
            for position in range(start, end):
                body[position] = True
        body[end] = True                # the terminator line is data either way
        index = end + 1
    return body


# A `case` LABEL sits exactly where a command does but is a PATTERN, not a command
# word: joining `case $1 in` / `shutdown) echo bye ;;` with `; ` put `shutdown` in
# command position, so any script dispatching on a `shutdown`/`reboot`/`halt`
# subcommand became a refusal no approval can lift.
#
# The label is removed from the screened text rather than skipped inside `_CMD`,
# and only inside a `case … esac` region, because a word ending in `)` means
# something else everywhere else: `(echo | reboot)` is a pipeline whose last stage
# is a command, and a `_CMD` that stepped over `reboot)` would have lost it. What
# sits in FRONT of the label is kept — the `;;` that closed the clause before it,
# a `;` put in place of `in` for the first — so the branch BODY stays a command
# position and `a) mkfs.ext4 /dev/sda ;;` still refuses.
#
# A label follows `in` or the `;;` (`;&`, `;;&`) that ended the previous clause,
# never a plain `;`: inside a branch a `;` is an ordinary separator, and
# `a) (echo; reboot) ;;` must keep its `reboot`. A `(pattern)` label is not
# handled either, for the same reason — dropping a leading `(` would take
# `; (reboot)` with it.
_CASE_BLOCK_RE = re.compile(r"\bcase\b.*?\besac\b")
_CASE_PATTERN = r"[;&\s]*[^\s;&(){}<>`'\"]*\)(?=[\s;]|$)"
_CASE_LABEL_RE = re.compile(r"(?:(?<=;;)|(?<=;&))" + _CASE_PATTERN)
_CASE_FIRST_LABEL_RE = re.compile(r"(?<=\bin)" + _CASE_PATTERN)


def _strip_case_labels(flat: str) -> str:
    """*flat* with the patterns of every ``case`` clause removed."""
    def clause(match: re.Match[str]) -> str:
        block = _CASE_FIRST_LABEL_RE.sub("; ", match.group(0))
        return _CASE_LABEL_RE.sub(" ", block)

    return _CASE_BLOCK_RE.sub(clause, flat)


_SUBSTITUTION_RE = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")


def _substituted(text: str) -> str:
    """The parts of a heredoc body line a shell would still RUN, as statements.

    An unquoted heredoc substitutes, so `$(rm -rf /)` in a body executes while
    the words around it are data. Joined with `;` so each substitution is its own
    segment.
    """
    parts = [
        group
        for match in _SUBSTITUTION_RE.finditer(text)
        for group in match.groups()
        if group
    ]
    return " ; ".join(parts)


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
        # A heredoc body is stdin, not statements — join those with a space so they
        # carry no command-position anchor, and the rest with `; ` as before.
        is_body = _heredoc_body(lines)
        text = ""
        for position, line in enumerate(lines):
            if not text:
                text = line
            else:
                text += (" " if is_body[position] else "; ") + line
        segments: list[tuple[str, ...]] = []
        # An UNQUOTED newline is a statement separator in a shell, exactly like
        # `;` — and a `sh -c` payload is a shell script, so this is the most
        # ordinary shape one takes. Before this the newline reached `shlex` with
        # `whitespace_split=True`, which squeezes it into a space, so nothing ever
        # occupied a command position on line 2 and `sh -c 'echo hi\nmkfs.ext4
        # /dev/sda'` passed the floor. Splitting is quote-aware: a newline INSIDE
        # quotes is data, and splitting there would screen ordinary text as a
        # command.
        for position, line in enumerate(lines):
            # The same rule as the `text` join, which `segments` used to ignore:
            # a body line is stdin, so tokenising all of it and handing it to
            # `_recursive_root_removal` refused a README that quotes `rm -rf /`.
            # What a body line still RUNS is its command substitutions, so that
            # is what is segmented — dropping the line outright would have let
            # `cat <<EOF` / `$(rm -rf /)` / `EOF` through.
            source = _substituted(line) if is_body[position] else line
            if not source.strip():
                continue
            try:
                lexer = shlex.shlex(source, posix=True, punctuation_chars=True)
                lexer.whitespace_split = True
                tokens = tuple(lexer)
            except ValueError:
                tokens = tuple(source.split())
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
    flat = _strip_case_labels(_WS_RE.sub(" ", str(text or "")).strip().lower())
    return flat, tuple(segments)


def _recursive_root_removal(tokens: Sequence[str]) -> bool:
    """``rm -rf /``-style deletions (any flag spelling, any root operand).

    Command words are compared by BASENAME. This used to list ``/bin/rm`` and
    ``/usr/bin/rm`` literally — a path problem solved for one spelling of one
    command — and the wrapper walk did not do it at all, so ``/usr/bin/sudo`` was
    not a wrapper and ``/usr/local/bin/rm`` was not ``rm``.
    """
    if not tokens:
        return False
    lowered = [str(token).strip().lower() for token in tokens]
    # A `case` clause opens with a pattern the shell never runs; the flat text has
    # those removed, and a segment gets the same treatment so `wipe) rm -rf / ;;`
    # is read as the `rm` it is.
    head = 2 if len(lowered) > 1 and lowered[1] == ")" else 0
    while head < len(lowered) and _command_name(lowered[head]) in _WRAPPERS:
        head += 1
    if head >= len(lowered) or _command_name(lowered[head]) != "rm":
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


def _command_name(token: str) -> str:
    """Basename of a command word with a Windows ``.exe`` suffix dropped.

    ``C:\\Windows\\System32\\cmd.exe`` and ``sh.exe`` name the same shells as
    ``cmd`` and ``sh``; keeping the extension would hide the payload. Used for
    every command word compared against a name — shells, ``_WRAPPERS`` and
    ``rm`` — because a path in front of any of them is the same evasion.
    """
    name = _basename(token)
    return name[:-4] if name.endswith(".exe") else name


_ASSIGNMENT_RE = re.compile(r"[a-z_][a-z0-9_]*=.*", re.IGNORECASE)


def _shell_head(lowered: Sequence[str]) -> int | None:
    """Index of the shell a segment invokes, or None if it does not invoke one.

    The walk used to step over head tokens that were literally in ``_WRAPPERS`` and
    then demand the very next word be a shell. Anything else in the prefix ended
    the walk on a non-shell word, so no payload was extracted and the whole `sh -c`
    screening was skipped — `env FOO=1 sh -c 'mkfs.ext4 /dev/sda'` reached a real
    shell with this floor returning None, and removing the five characters
    ``FOO=1 `` turned the same string into `hardline_denied:mkfs`. `_CMD` had been
    widened for exactly that assignment prefix; this had not.

    Three prefix shapes are stepped over, all of them things a shell consumes
    before deciding what to run: an assignment (`FOO=1`), a wrapper from
    ``_WRAPPERS``, and a wrapper's own options — including an option that takes a
    separate argument (`sudo -u root`, `nice -n 10`), which is why one bare word is
    allowed directly after an option. `--` ends option parsing.

    Conservative by construction: anything it does not recognise ends the walk and
    the segment is skipped, which is the same answer as before rather than a new
    refusal.
    """
    index = 0
    after_option = False
    while index < len(lowered):
        word = lowered[index]
        if _command_name(word) in _POSIX_SHELLS or _command_name(word) in _WINDOWS_SHELLS:
            return index
        if word == "--":
            index += 1
            after_option = False
            continue
        if len(word) > 1 and word.startswith("-"):
            index += 1
            after_option = True
            continue
        if _ASSIGNMENT_RE.fullmatch(word) or word in _WRAPPERS:
            index += 1
            after_option = False
            continue
        if after_option:                 # the argument of the option before it
            index += 1
            after_option = False
            continue
        return None
    return None


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
        head = _shell_head(lowered)
        if head is None:
            continue
        name = _command_name(lowered[head])
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
                # Named `word`, not `token`: bandit's B105 reads `token == "--"` as a
                # hardcoded password comparison purely from the variable name, and a
                # `# nosec` for a shell word would be a suppression where a rename
                # costs nothing.
                word = lowered[cursor]
                if word == "--":
                    cursor += 1
                    break
                if len(word) > 1 and word.startswith("-"):
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

    **Every payload found is yielded, and every payload found is re-expanded.**
    The only cap is ``_MAX_SHELL_DEPTH``, because the caller chooses the order and
    anything counted in encounter order is something they fill with decoys:
    capping the yields let seven cheap ``sh -c ok; `` segments push a trailing
    ``sh -c 'mkfs…'`` out of the scan, and capping the re-expansions let eight of
    them push ``sh -c "sh -c 'mkfs…'"`` out of the unwrapping instead — the same
    bypass one level down. Work stays bounded without a breadth cap: at most one
    payload is taken per segment and a payload is a token of the level above, so
    each level's payloads are disjoint substrings of the input.

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

    Nor is a ``case`` label with a leading ``(`` (``(shutdown) echo bye ;;``) or a
    ``case`` nested inside another one read as a label — both are refusals that
    are not commands, which is the direction that costs nothing but a false no.

    This list is what the module knows it misses, not a proof of completeness.
    Two adversarial reviews of the list itself found eleven entries missing from
    it — a decoy option between ``-c`` and the payload, a newline inside a
    payload, an assignment prefix, a brace group, a compound-command keyword
    position, a re-expansion budget filled with decoys, a path in front of the
    command word, a ``<<`` that opens no heredoc, a heredoc a shell reads as a
    script, a heredoc body screened as argv, and a ``case`` label. Those are
    closed rather than listed; the point of recording it here is that the next
    eleven are found the same way, by somebody trying.
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
                # EVERY payload is re-expanded, not the first few and not the
                # short ones: both of those were budgets the caller filled — with
                # decoy segments in front, or with padding inside the payload —
                # and a budget the caller can fill is not a floor. Depth is what
                # bounds the work.
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
