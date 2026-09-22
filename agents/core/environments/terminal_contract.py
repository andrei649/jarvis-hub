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
   others, and the five reviews that produced the current list found twenty-five
   it did not have.
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
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
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
    is a here-STRING, which has no body LINE — its WORD is the command's stdin on
    the same line, screened separately by ``_herestring_scripts`` when a shell
    runs that WORD as a script (`sh <<< reboot`), not here.
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


def _shell_words(text: str) -> list[str]:
    """*text* tokenised the way a segment is, lower-cased, for shell-head tests."""
    try:
        lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        return [str(token).strip().lower() for token in lexer]
    except ValueError:
        return [token.strip().lower() for token in text.split()]


def _statement_pieces(text: str) -> list[tuple[int, str]]:
    """``(start, statement)`` for each ``;``/``&&``/``||``/``&``-bounded piece.

    A single ``|`` is a PIPE and stays inside the piece; ``||`` is a separator.
    The ``&`` of a redirection (``2>&1``, ``>&2``, ``&>x``) and of a ``|&`` pipe is
    not a separator either — splitting ``cat <<EOF 2>&1 | sh`` at that ``&`` put
    the ``sh`` in a piece of its own and the body went unread. Quote-aware, so a
    separator inside a string literal is data. The start index is into *text*,
    which is how the piece owning a ``<<`` at a known offset is found.
    """
    pieces: list[tuple[int, str]] = []
    start = 0
    index = 0
    quote = ""
    while index < len(text):
        char = text[index]
        if quote:
            if char == "\\" and quote == '"' and index + 1 < len(text):
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
        step = 0
        if char == ";":
            step = 1
        elif char == "&":
            following = text[index + 1:index + 2]
            if following == "&":
                step = 2
            elif following != ">" and (index == 0 or text[index - 1] not in "<>|"):
                step = 1
        elif char == "|" and text[index + 1:index + 2] == "|":
            step = 2
        if step:
            pieces.append((start, text[start:index]))
            start = index + step
            index += step
            continue
        index += 1
    pieces.append((start, text[start:]))
    return pieces


def _pipe_stages(statement: str) -> list[tuple[int, str]]:
    """``(start, stage)`` for each stage of *statement*, split at its single
    ``|`` (or bash ``|&``) pipes, quote-aware. The start is into *statement*."""
    stages: list[tuple[int, str]] = []
    start = 0
    index = 0
    quote = ""
    while index < len(statement):
        char = statement[index]
        if quote:
            if char == "\\" and quote == '"' and index + 1 < len(statement):
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
        if char == "|" and statement[index + 1:index + 2] != "|":
            stages.append((start, statement[start:index]))
            index += 2 if statement[index + 1:index + 2] == "&" else 1
            start = index
            continue
        index += 1
    stages.append((start, statement[start:]))
    return stages


# A redirection with its operand, dropped before a stage is read as words so
# `bash <<EOF` does not read `<<`/`EOF` as the shell's script operand.
_REDIRECTION_RE = re.compile(
    r"\d*(?:&>>?|[<>]&|>>?|<<<|<<-?|<)\s*(?:\"[^\"]*\"|'[^']*'|[^\s;&|<>()`'\"]*)")
# The FILE a `>`/`>>`/`&>` redirection writes to, quoted or bare. Quoted
# spellings are targets too: `cat > "x.sh" <<'EOF'` + `bash x.sh` runs the body.
_REDIRECT_TARGET_RE = re.compile(
    r"(?:\d*>>?|&>>?)\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s;&|<>()`'\"]+))")
# Tokens a shell steps over on its way to the command of a stage: a subshell or
# brace-group opener, negation, and the compound-command keywords `_CMD` accepts.
# `(sh x.sh)`, `{ sh x.sh; }` and `if true; then sh x.sh; fi` all run x.sh.
_COMMAND_PREFIXES = frozenset({"(", "{", "!", "if", "then", "do", "else", "elif", "while", "until"})
# The builtins that read a file and execute it in the current shell, and `eval`,
# which runs whatever a command substitution read (`eval "$(cat)"`).
_SOURCE_BUILTINS = frozenset({".", "source"})
_RUN_BUILTINS = _SOURCE_BUILTINS | {"eval"}
# Script operands that ARE the shell's standard input: `sh /dev/stdin <<EOF` and
# `sh -c '. /dev/stdin' <<EOF` run the body exactly as `sh <<EOF` does.
_STDIN_FILES = frozenset({"/dev/stdin", "/dev/fd/0", "/proc/self/fd/0"})
# Shell options that take a separate argument, so the word after them is not the
# script operand: `bash -o pipefail <<EOF` reads its stdin.
_SHELL_OPTIONS_WITH_ARGUMENT = frozenset({"-o", "+o", "-O", "+O", "--rcfile", "--init-file"})
_WINDOWS_FILE_FLAG_RE = re.compile(r"[-/](?:f|fi|fil|file)")
# The tokens that CLOSE a subshell or brace group, or separate its commands: a
# stage that is `(sh)`, `( sh )`, `(exec sh)` or `{ sh; }` ends in one of these
# once the leading `(`/`{` prefix is stripped. They are not the shell's command
# or its script operand, so they are dropped from the tail before the stage is
# read — otherwise `['sh', ')']` read as `sh` running a script named `)` and the
# stdin verdict for `| (sh)` (which every shell runs) was never reached.
_STAGE_CLOSERS = frozenset({")", "}", ";"})


def _stage_words(stage: str) -> list[str]:
    """The words of a pipeline stage, redirections dropped, the prefixes a shell
    steps over (``(``, ``{``, ``!``, ``then``, ``do``, …) removed from the front
    and the closers a group ends in (``)``, ``}``, ``;``) removed from the tail."""
    words = _shell_words(_REDIRECTION_RE.sub(" ", stage))
    index = 0
    while index < len(words) and words[index] in _COMMAND_PREFIXES:
        index += 1
    end = len(words)
    while end > index and words[end - 1] in _STAGE_CLOSERS:
        end -= 1
    return words[index:end]


def _interpreter_call(words: Sequence[str]) -> tuple[str, str | None] | None:
    """How the command in *words* (one stage's words) executes a script, if at all.

    * ``("stdin", None)`` — a shell that reads its STANDARD INPUT as the script:
      ``sh``, ``bash -s``, ``sh -``, ``bash -o pipefail``. This is the only kind
      that runs a heredoc body piped or redirected into it.
    * ``("file", name)`` — a shell, or the ``.``/``source`` builtin, running the
      named file: ``sh x.sh``, ``sudo bash ./x.sh``, ``. x.sh``. Its stdin is that
      script's DATA.
    * ``("payload", text)`` — a shell running an inline ``-c`` command line (or a
      Windows ``/c``-style flag, whose payload is left to ``_shell_c_payloads``).
      Its stdin is data unless the command line itself hands it to something
      that executes it (``_payload_reads_stdin``): ``cat <<EOF | sh -c cat``
      prints the body, ``bash -c sh <<EOF`` runs it.
    * ``("eval", None)`` — ``eval`` fed by a command substitution, which reads the
      stdin of the stage it runs in: ``cat <<EOF | eval "$(cat)"`` and ``sh -c
      'eval "$(cat)"' <<EOF`` run the body. On the heredoc's OWN stage the
      substitution expands before the redirection attaches (``eval "$(cat)"
      <<EOF`` runs nothing), which is why this is its own kind.
    * ``None`` — not an interpreter call, or one reached through ``xargs``:
      ``xargs sh -c 'rm -f {}'`` hands the lines it reads to the shell as
      ARGUMENTS (``{}``, ``$@``), never as its script.
    """
    head = _shell_head(words, _RUN_BUILTINS)
    if head is None:
        return None
    if any(_command_name(word) == "xargs" for word in words[:head]):
        return None
    name = _command_name(words[head])
    rest = words[head + 1:]
    if name == "eval":
        substituted = any(word in ("$", "(", "`") or "$(" in word or "`" in word for word in rest)
        return ("eval", None) if substituted else None
    if name in _SOURCE_BUILTINS:
        operand = next((word for word in rest if not word.startswith("-")), None)
        if operand in _STDIN_FILES:
            return ("stdin", None)
        return ("file", operand) if operand else None
    if name in _WINDOWS_SHELLS:
        if any(_WINDOWS_C_FLAG_RE.fullmatch(word) for word in rest):
            return ("payload", None)
        for index, word in enumerate(rest):
            if _WINDOWS_FILE_FLAG_RE.fullmatch(word) and index + 1 < len(rest):
                return ("file", rest[index + 1])
        return ("stdin", None)
    cursor = 0
    while cursor < len(rest):
        word = rest[cursor]
        if word in ("--", "-"):
            cursor += 1
            break
        if len(word) > 1 and word[0] in "-+":
            if word[0] == "-" and word[1] != "-" and _POSIX_C_FLAG_RE.fullmatch(word):
                # A real shell keeps parsing options after -c and runs the first
                # NON-option operand, `--` included — the same walk as
                # `_shell_c_payloads`.
                cursor += 1
                while cursor < len(rest) and len(rest[cursor]) > 1 and rest[cursor][0] in "-+":
                    if rest[cursor] == "--":
                        cursor += 1
                        break
                    cursor += 1
                return ("payload", rest[cursor] if cursor < len(rest) else None)
            if word[1] != "-" and "s" in word[1:]:
                return ("stdin", None)   # `-s`: the operands are positional parameters
            cursor += 2 if word in _SHELL_OPTIONS_WITH_ARGUMENT else 1
            continue
        break
    if cursor < len(rest) and rest[cursor] not in _STDIN_FILES:
        return ("file", rest[cursor])
    return ("stdin", None)


def _payload_reads_stdin(text: str) -> bool:
    """Does the inline command line *text* execute the stdin of the shell running it?

    ``bash -c sh <<EOF``, ``bash -c 'cat | sh' <<EOF``, ``sh -c 'eval "$(cat)"'
    <<EOF`` and ``sh -c '. /dev/stdin' <<EOF`` all run the body (the inner shell
    inherits the heredoc); ``sh -c cat <<EOF`` prints it. One level only, the
    same depth ``_script_runs`` reads a payload at.
    """
    for _, piece in _statement_pieces(text):
        for _, stage in _pipe_stages(piece):
            call = _interpreter_call(_stage_words(stage))
            if call is not None and call[0] in ("stdin", "eval"):
                return True
    return False


# The WORD of a ``<<<`` here-string, quoted or bare. A here-string sends WORD to
# the command's stdin; ``<<`` and ``<<-`` are heredocs and are excluded by the
# third ``<``.
_HERESTRING_RE = re.compile(r"<<<\s*(\"[^\"]*\"|'[^']*'|[^\s;&|<>()`]+)")


def _herestring_scripts(command: str) -> list[str]:
    """WORDs of ``<<<`` here-strings a shell runs as a script, screened as commands.

    A here-string feeds WORD to a command's standard input, and a shell that
    reads its stdin as the script RUNS it — ``sh <<< reboot``, ``bash <<< reboot``,
    ``bash -s <<< reboot`` all execute WORD (``sh``/``dash`` lack ``<<<``, but
    bash is a supported target), and ``cat <<< reboot | sh`` carries the bytes
    through a passthrough into one. ``_heredoc_open`` skips ``<<<`` because it has
    no body LINE, so nothing modelled it; the WORD is returned here to be screened
    in command position, exactly as a heredoc body would be.

    Only fired when the here-string's own pipeline stage is a stdin-reading shell,
    or a stage DOWNSTREAM of it in the same statement is: ``cat <<< reboot | cat``
    only prints, so its WORD is data. The stage's own shell is read with the
    here-string redirection already stripped (``_stage_words`` drops ``<<< WORD``),
    so ``sh <<< reboot`` reads as the bare ``sh`` it is.
    """
    scripts: list[str] = []
    for line in _unquoted_lines(command):
        for _, piece in _statement_pieces(line):
            stages = _pipe_stages(piece)
            calls = [_interpreter_call(_stage_words(stage)) for _, stage in stages]
            for index, (_, stage) in enumerate(stages):
                matches = _HERESTRING_RE.findall(stage)
                if not matches:
                    continue
                consumed = any(
                    call is not None and call[0] in ("stdin", "eval")
                    for call in calls[index:]
                )
                if not consumed:
                    continue
                for word in matches:
                    # The OUTER shell removes the here-string WORD's quotes before
                    # the bytes reach the inner shell, which parses them as a
                    # command line: `sh <<< 'rm -rf /'` runs `rm -rf /`. So the
                    # WORD is dequoted to its shell value, not screened with the
                    # quotes still on (a single quoted token is not a command).
                    try:
                        dequoted = " ".join(shlex.split(word)) or word
                    except ValueError:
                        dequoted = word
                    scripts.append(dequoted)
    return scripts


def _script_runs(text: str, depth: int = 0) -> set[str]:
    """Names (and basenames) of the files a shell READS AND EXECUTES in *text*.

    ``sh x.sh``, ``sudo bash ./x.sh``, ``. x.sh``, ``source x.sh``, the same
    behind ``(``/``{``/``then``/``do``, a file an upstream stage reads into a
    stdin-reading shell (``cat x.sh | sh``), and — one level down — a file the
    shell's own ``-c`` command line runs (``sh -c '. x.sh'``). A file that is
    merely an ARGUMENT of a shell-run script (``bash run.sh x.yaml``) is not run
    by that shell and is not named here.
    """
    names: set[str] = set()
    for _, piece in _statement_pieces(text):
        staged = [_stage_words(stage) for _, stage in _pipe_stages(piece)]
        calls = [_interpreter_call(words) for words in staged]
        for index, call in enumerate(calls):
            if call is None:
                continue
            kind, value = call
            if kind == "file" and value:
                names.add(value)
            elif kind == "payload" and value and depth == 0:
                names |= _script_runs(value, depth + 1)
            elif kind == "stdin":
                for earlier in range(index):
                    if calls[earlier] is None:
                        names.update(word for word in staged[earlier][1:] if not word.startswith("-"))
    return names | {_basename(name) for name in names}


def _inside_process_substitution(text: str, position: int) -> bool:
    """Is character *position* inside an unclosed ``<(``/``>(`` on *text*?

    A process substitution ``<(cmd)`` runs ``cmd`` and exposes its output as a
    file. A heredoc opened between the ``<(`` and its matching ``)`` belongs to
    that inner command, so a shell running the substitution's file runs the body.
    Not quote-aware: *text* is a single pipeline stage, and a ``<(`` inside quotes
    is rare enough that reading it as a real one only ADDS a refusal.
    """
    depth = 0
    index = 0
    while index < position and index < len(text):
        pair = text[index:index + 2]
        if pair in ("<(", ">("):
            depth += 1
            index += 2
            continue
        if text[index] == ")" and depth:
            depth -= 1
        index += 1
    return depth > 0


def _heredoc_feeds_a_shell(line: str, offset: int, later: Callable[[], set[str]]) -> bool:
    """Does a shell EXECUTE the body of the heredoc opened at *offset* on *line*?

    ``cat <<EOF`` hands the body to a program that prints it; a shell that reads
    its stdin as a script runs it, every line a statement — so treating those
    lines as data was a hole straight through the floor. A shell reaches the body
    four ways, all checked here:

    * The heredoc's own pipeline stage IS such a shell: ``bash <<EOF``,
      ``sh <<'EOF'``, ``bash -s <<EOF``, ``sudo bash <<EOF``, ``sh /dev/stdin
      <<EOF`` — or a shell whose ``-c`` line launches one (``bash -c sh <<EOF``).
      A subshell or brace group as a pipe stage counts here too: ``| (sh)``,
      ``| ( sh )``, ``| (exec sh)``, ``| { sh; }`` — ``_stage_words`` drops the
      trailing ``)``/``}`` so the stage reads as the bare shell it is.
    * A stage DOWNSTREAM of it is: ``cat <<EOF | sh``, ``cat <<EOF | grep -v '^#'
      | sh``. #1177 read only the stage LEFT of ``<<`` and so missed these,
      although /bin/sh, dash and bash all run the body.
    * The heredoc is opened INSIDE a ``<(...)`` process substitution the owning
      stage's shell/``source`` runs: ``source <(cat <<EOF …)``, ``sh <(cat <<EOF
      …)``, ``bash <(…)``, ``. <(…)`` execute the substitution's output — the
      body — as a script (``_inside_process_substitution``; bash-only, and bash
      is a supported target).
    * The body is written to a FILE — a ``>``/``>>`` target, quoted or not, or a
      ``tee`` operand, on the owning stage or downstream — that a shell then runs
      in the same command: ``cat <<'EOF' >x.sh; sh x.sh`` (same line) or ``cat
      <<EOF >y.sh`` … ``. y.sh`` (a later line; *later* returns the files run on
      the statement lines after the heredoc, computed lazily by the caller).

    A heredoc redirects only its OWN command's stdin, so a shell UPSTREAM of that
    command (``bash -c echo | cat <<EOF``) never sees the body and does not count
    — every shell prints the literal body there. Nor does a shell with its own
    script (``cat <<EOF | bash run.sh``, ``| sh -c cat``, and on the own stage
    ``sh -c cat <<EOF`` / ``bash run.sh <<EOF``, which #1177 refused although
    every shell prints the body) or one behind ``xargs``, whose stdin is data
    (``_interpreter_call``). The heredoc belongs to one
    ``;``/``&&``/``||``/``&``-bounded statement, so ``bash --version; cat <<EOF``
    does not count and ``cat <<EOF; sh`` — where ``sh`` is a separate statement
    reading the parent's stdin, not the heredoc — is still data. The file test
    looks only at the operand a shell RUNS (``_script_runs``), never at every
    word of the statement: a heredoc-written ``x.yaml`` handed to ``bash run.sh
    x.yaml`` is an argument, not a script.
    """
    pieces = _statement_pieces(line)
    # The piece OWNING the ``<<`` is the one with the greatest start at or before
    # the offset; pieces are in order, so it is the last that qualifies.
    owner = 0
    for index, (start, _) in enumerate(pieces):
        if start <= offset:
            owner = index
    statement_start, statement = pieces[owner]
    stages = _pipe_stages(statement)
    first = 0
    for index, (start, _) in enumerate(stages):
        if statement_start + start <= offset:
            first = index
    # A heredoc opened INSIDE a process substitution ``<(...)`` whose fd is
    # consumed by a shell or ``.``/``source`` on the OWNING stage: the
    # substitution runs its inner command (``cat <<EOF``) and exposes the output —
    # the body — as a file, and ``source <(...)``, ``. <(...)``, ``sh <(...)`` and
    # ``bash <(...)`` execute that file as a script. bash runs these (``sh``/
    # ``dash`` lack ``<(``), and bash is a supported target. The consumer sits
    # BEFORE the ``<(`` on this line; a consumer piped in AFTER it (``cat <(...)
    # | sh``) lands on a later line once the heredoc has a body and terminator,
    # so it is not reached here and stays a disclosed gap.
    first_start, first_stage = stages[first]
    if _inside_process_substitution(first_stage, offset - statement_start - first_start):
        call = _interpreter_call(_stage_words(first_stage))
        if call is not None and call[0] == "file" and (call[1] or "").startswith("("):
            return True
    downstream = [(stage, _stage_words(stage)) for _, stage in stages[first:]]
    for index, (_, words) in enumerate(downstream):
        call = _interpreter_call(words)
        if call is None:
            continue
        kind, value = call
        if kind == "stdin" or (kind == "eval" and index > 0):
            return True
        if kind == "payload" and value and _payload_reads_stdin(value):
            return True
    targets: set[str] = set()
    for stage, words in downstream:
        for groups in _REDIRECT_TARGET_RE.findall(stage):
            targets.add(next(group for group in groups if group).lower())
        head = _shell_head(words, frozenset({"tee"}))
        if head is not None and _command_name(words[head]) == "tee":
            targets.update(word for word in words[head + 1:] if not word.startswith("-"))
    if not targets:
        return False
    names = targets | {_basename(target) for target in targets}
    if owner + 1 < len(pieces) and names & _script_runs(line[pieces[owner + 1][0]:]):
        return True
    return bool(names & later())


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

    Whether a shell runs a body (``_heredoc_feeds_a_shell``) is decided LAST
    heredoc first: the answer depends only on the heredoc's own statement and the
    text after it, and the body of a later heredoc a shell runs is itself
    statements that may run an earlier heredoc's file. The statement lines after
    each heredoc are tokenised once, lazily, and shared — doing it per heredoc
    was quadratic (400 ``cat <<E >x`` blocks: 2.5 s).

    Nesting and multiple heredocs on one line are not modelled: the first
    delimiter on a line wins and the body runs to the next line equal to it.
    """
    extents: list[tuple[int, int, int]] = []
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
        extents.append((index, offset, end))
        index = end + 1
    body = [False] * len(lines)
    for opener, _, end in extents:
        for position in range(opener + 1, end + 1):
            body[position] = True        # the terminator line is data either way
    run_names: set[str] = set()
    unscanned: list[int] = []
    pending = len(lines) - 1

    def later() -> set[str]:
        while unscanned:
            run_names.update(_script_runs(lines[unscanned.pop()]))
        return run_names

    for opener, offset, end in reversed(extents):
        while pending > end:
            if not body[pending]:
                unscanned.append(pending)
            pending -= 1
        if _heredoc_feeds_a_shell(lines[opener], offset, later):
            for position in range(opener + 1, end):
                body[position] = False
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
# The region must be a REAL case statement, not any `case … esac` text: a `case`
# keyword sits in command position (start of the text or after a shell operator)
# and is `case WORD in …`. Matching a bare `\bcase\b.*?\besac\b` fired on `case`
# and `esac` used as ordinary words, and its first-label rule then stripped the
# last command of a subshell after an unrelated `in`: `(echo case in; reboot);
# echo esac` — which /bin/sh, dash and bash all run — lost its `reboot`, and the
# `$IFS`-spliced `(echo case in; mkfs.ext4$IFS/dev/sda); echo esac` and
# `wipefs$IFS-a$IFS/dev/sda` in the same shape lost theirs. So the region is
# anchored on a command-position `case` followed by `WORD` and `in`.
#
# A label follows `in` or the `;;` (`;&`, `;;&`) that ended the previous clause,
# never a plain `;`: inside a branch a `;` is an ordinary separator, and
# `a) (echo; reboot) ;;` must keep its `reboot`. A `(pattern)` label is not
# handled either, for the same reason — dropping a leading `(` would take
# `; (reboot)` with it.
#
# The region is found by three single-purpose searches rather than one regex:
# the opener `case WORD `, then the first `in` after it, then the first `esac`
# after that. A single `\bcase\s+WORD\s+.*?\bin\b.*?\besac\b` gave the same
# answer but, for every `case` with no later `esac`, re-scanned to the end of the
# text once per later `in` — and `case`/`in` are ordinary English words, so 4000
# chars of prose cost 0.5 s and eight argv items of it 128 s. Each search here
# starts where the last one stopped, so the whole strip is linear in the text.
_CASE_OPEN_RE = re.compile(r"\bcase\s+[^\s;&|]\S*\s+")
_CASE_IN_RE = re.compile(r"\bin\b")
_CASE_ESAC_RE = re.compile(r"\besac\b")
_CASE_PATTERN = r"[;&\s]*[^\s;&(){}<>`'\"]*\)(?=[\s;]|$)"
_CASE_LABEL_RE = re.compile(r"(?:(?<=;;)|(?<=;&))" + _CASE_PATTERN)
_CASE_FIRST_LABEL_RE = re.compile(r"(?<=\bin)" + _CASE_PATTERN)
# A compound-command keyword right before the `case`, whether spaced (`; then
# case`) or compact (`;then case`, `b;do case`): the word boundary in front of
# the keyword is the start of the text, whitespace or a shell operator.
_KEYWORD_BEFORE_RE = re.compile(r"(?:^|[\s;&|(`])(?:then|do|else|elif)$")


def _in_command_position(text: str, position: int) -> bool:
    """Is a ``case`` at *position* in *text* a keyword rather than an argument?

    A ``case`` in command position opens a real statement; ``echo case`` does not.
    Only the tail matters — the start of the text, a shell operator (optionally
    then whitespace), a POSIX brace group ``{`` followed by whitespace, or a
    compound-command keyword right before it. The keyword test used to read the
    last whitespace-separated WORD, so the compact ``if true;then case`` saw
    ``true;then``, judged the ``case`` an argument, skipped the label strip and
    refused the label — on a script every shell runs label-only.
    """
    index = position
    while index > 0 and text[index - 1].isspace():
        index -= 1
    if index == 0:
        return True
    last = text[index - 1]
    if last in ";&|(`":
        return True
    if last == "{":
        return index < position
    return _KEYWORD_BEFORE_RE.search(text, max(0, index - 8), index) is not None


def _strip_case_labels(text: str) -> str:
    """*text* with the patterns of every real ``case`` clause removed.

    A clause is stripped only when its ``case`` is a keyword in command position
    (``_in_command_position``): ``case`` and ``esac`` used as ordinary words —
    ``(echo case in; reboot); echo esac`` — must keep the command the subshell
    still runs after the unrelated ``in``. The region never crosses a newline
    (one can sit inside quotes on a segment line), as the regex it replaces did
    not.
    """
    if "case" not in text:
        return text
    out: list[str] = []
    last = 0
    position = 0
    while True:
        opener = _CASE_OPEN_RE.search(text, position)
        if opener is None:
            break
        if not _in_command_position(text, opener.start()):
            position = opener.start() + 1
            continue
        line_end = text.find("\n", opener.end())
        if line_end < 0:
            line_end = len(text)
        marker = _CASE_IN_RE.search(text, opener.end(), line_end)
        closer = _CASE_ESAC_RE.search(text, marker.end(), line_end) if marker else None
        if closer is None:
            # No `in … esac` is left on this line, so no later `case` on it can
            # open a region either.
            position = line_end
            continue
        block = text[opener.start():closer.end()]
        out.append(text[last:opener.start()])
        out.append(_CASE_LABEL_RE.sub(" ", _CASE_FIRST_LABEL_RE.sub("; ", block)))
        last = position = closer.end()
    if not out:
        return text
    out.append(text[last:])
    return "".join(out)


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
            #
            # A `case` label is stripped from the segment source too, not only
            # from `flat`: `_recursive_root_removal` runs over segments, so a
            # one-line clause `case $1 in wipe) rm -rf / ;; esac` — whose body is
            # a single segment — only refused once the label `wipe)` stopped
            # sitting in front of the `rm`. The strip fires solely inside a real
            # `case … esac` region and can only ADD a separator, never hide a
            # command, so it moves nothing in the dangerous direction.
            source = _substituted(line) if is_body[position] else _strip_case_labels(line)
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


def _shell_head(lowered: Sequence[str], extra: frozenset[str] = frozenset()) -> int | None:
    """Index of the shell a segment invokes, or None if it does not invoke one.

    *extra* names further command words that end the walk the way a shell does
    (the ``.``/``source`` builtins, ``tee``) for callers reading a pipeline stage.

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
        name = _command_name(word)
        if name in _POSIX_SHELLS or name in _WINDOWS_SHELLS or name in extra:
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
    base64; a ``cmd /c`` payload split across several argv items; an obfuscated
    shell HEAD in argv form (``['s""h', '-c', …]``), because the de-obfuscation
    pass runs after payload extraction and its output is not fed back through it;
    and, for a heredoc body written to a file, the ways of running that file that
    name neither a shell nor the file: a bare path in command position (``…
    >x.sh; ./x.sh``), a file name carried by a variable (``for f in x.sh; do sh
    $f; done``), a file the environment loads (``BASH_ENV=x.sh bash -c :``), and
    a heredoc opened inside a command substitution (``eval "$(cat <<EOF …)"``,
    which ``_heredoc_open`` reads as quoted text). ``_heredoc_feeds_a_shell``
    catches ``sh x.sh``, ``. x.sh``/``source x.sh``, the same behind ``(``/``{``/
    ``then``, a ``tee`` or quoted target, ``cat x.sh | sh``, ``sh -c '. x.sh'``,
    the pipe forms, a subshell or brace group as the final pipe stage
    (``| (sh)``, ``| ( sh )``, ``| (exec sh)``, ``| { sh; }`` — the trailing
    closer is dropped by ``_stage_words``) and a heredoc inside a ``<(...)`` a
    leading shell/``source`` runs (``source <(cat <<EOF …)``, ``sh <(…)``,
    ``bash <(…)``, ``. <(…)`` — modelled by ``_heredoc_feeds_a_shell`` and
    ``_inside_process_substitution``) — each pinned — and misses two more pipe
    shapes: ``xargs -I{} sh -c '{}'`` (each line becomes the command line; an
    ``xargs``-reached shell is read as taking arguments) and a ``;`` inside a
    ``( )`` group of a pipe stage (``cat <<EOF | (cd /tmp; sh)``, split at the
    ``;`` by ``_statement_pieces`` before the subshell is seen), plus a ``<(...)``
    consumed by a shell DOWNSTREAM on a later line (``cat <(cat <<EOF …) | sh``,
    where the ``| sh`` follows the heredoc terminator). A ``<<<`` here-string fed
    to a stdin-reading shell (``sh <<< reboot``, ``bash <<< 'rm -rf /'``,
    ``cat <<< reboot | sh``) is screened separately by ``_herestring_scripts``,
    which dequotes the WORD and hands it to the scan in command position.

    Nor is a ``case`` label with a leading ``(`` (``(shutdown) echo bye ;;``) or a
    ``case`` nested inside another one read as a label — both are refusals that
    are not commands, which is the direction that costs nothing but a false no.

    This list is what the module knows it misses, not a proof of completeness.
    Five adversarial reviews of the list itself found twenty-five entries missing
    from it — a decoy option between ``-c`` and the payload, a newline inside a
    payload, an assignment prefix, a brace group, a compound-command keyword
    position, a re-expansion budget filled with decoys, a path in front of the
    command word, a ``<<`` that opens no heredoc, a heredoc a shell reads as a
    script, a heredoc body screened as argv, a ``case`` label, a ``case`` word
    that is not a ``case`` statement (``(echo case in; reboot); echo esac``), a
    heredoc body a shell consumes AFTER the redirection (``cat <<EOF | sh``), and
    — from the review of that last closure, which had named ``./x.sh`` as its only
    remaining gap — nine spellings of running the written file: six closed since
    (a shell behind ``(``/``{``/``then``, the ``.``/``source`` builtins, a ``tee``
    operand, a quoted redirect target, a file piped into a stdin-reading shell, a
    ``-c`` command line that runs the file) and three listed above (a
    variable-carried name, ``BASH_ENV``, a heredoc inside a substitution). That
    review also found the closure over-refusing five shapes no shell executes — a
    shell UPSTREAM of the heredoc's stage, an ``xargs``-reached shell, a shell
    with its own script or ``-c`` line, a written file handed to a script as an
    ARGUMENT, and a compact ``;then case`` read as an argument — and two of its
    new scans super-linear on prose; all fixed. The fifth review found three more
    cleared refusals, all closed here and each reproduced under /bin/sh, /bin/dash
    and /bin/bash first: a subshell/brace group as the final pipe stage with no
    internal ``;`` (``cat <<EOF | (sh)`` — the disclosure had said the machinery
    missed only two pipe shapes and this was a third), a ``<<<`` here-string into
    a stdin shell (``sh <<< reboot`` — the ``<<<`` note had said it "has no body
    at all"), and a heredoc inside a ``<(...)`` a leading shell/``source`` runs
    (``source <(cat <<EOF …)`` — process substitution was neither modelled nor
    listed next to the ``$()`` entry). Closed entries are closed rather than
    listed; the point of recording it here is that the next entries are found the
    same way, by somebody trying.
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
    # A ``<<<`` here-string fed to a stdin-reading shell is a script: its WORD is
    # screened in command position, the same way a heredoc body is. Only string
    # commands can carry a here-string; an argv never meets a shell.
    if isinstance(command, str):
        for script in _herestring_scripts(command):
            if script in seen:
                continue
            seen.add(script)
            yield script


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
