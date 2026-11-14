"""Quote-aware terminal command allowlist, what-if shell policy analyzer, and history rule-suggester (H020, H482, H483).

Pure offline policy evaluation and owner-managed allowlist storage:
1. ``analyze_shell_command`` — quote-aware compound-command, redirection, substitution,
   env-prefix, and re-interpreting-flag inspection without spawning anything.
2. ``CommandAllowlistStore`` / ``evaluate_allowlist`` — literal and narrow glob
   entries (e.g. ``cargo *``, ``pytest *``, ``git status``) guarded against shell
   chaining, command substitution, wrapper commands, and re-interpreting flags,
   evaluated across both raw text and unwrapped/deobfuscated detection variants.
3. ``explain_command_policy`` — full offline dry-run ("what-if") command check
   combining normalized shell variants, hardline floor, command content scanner,
   Hermes dangerous-command & H487 consent categories, allowlist, SmartPolicy,
   autonomy mode, and emergency stop.
4. ``suggest_allowlist_rules`` — conservative pass over approved terminal history
   that proposes narrow globs, hard-excludes destructive classes and root/path
   binaries, and writes nothing unless ``apply=True``.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shlex
import sqlite3
import tempfile
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import estop
from ..environments.terminal_contract import _detection_variants, hardline_match
from ..paths import data_path
from ..security.command_content_scanner import scan_command_content
from . import hermes_command_detection as detector
from .mode import read_mode
from .smart_approvals import smart_policy
from .terminal_consent_categories import (
    terminal_consent_categories,
    terminal_consent_descriptions,
)

SCHEMA_VERSION = 1
MAX_PATTERNS = 256
MAX_PATTERN_CHARS = 256
_BINARY_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}\Z")
_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*\Z", re.DOTALL)

#: Shells and command-dispatch wrappers never permitted as allowlist heads.
SHELL_AND_WRAPPER_BINARIES: frozenset[str] = frozenset({
    "sh", "bash", "zsh", "dash", "ksh", "ash", "fish", "csh", "tcsh",
    "busybox", "cmd", "powershell", "pwsh",
    "sudo", "doas", "su", "pkexec", "runuser", "chroot",
    "env", "xargs", "nohup", "eval", "exec", "command", "builtin",
    "nice", "ionice", "setsid", "nohup", "time", "timeout", "watch",
    "strace", "ltrace", "script", "expect", "screen", "tmux",
})

#: Destructive, system-admin, privilege, container/cluster, and network-transfer
#: binaries hard-excluded from allowlist entries and history suggestions.
DESTRUCTIVE_AND_ROOT_BINARIES: frozenset[str] = frozenset({
    # Filesystem wipe / mutation / permissions
    "rm", "rmdir", "unlink", "shred", "wipefs", "mkfs", "dd", "mv", "cp",
    "install", "truncate", "chmod", "chown", "chgrp", "chattr", "setfacl",
    "ln",
    # Process / host lifecycle / root admin
    "kill", "pkill", "killall", "shutdown", "reboot", "halt", "poweroff",
    "init", "telinit", "systemctl", "service", "launchctl", "crontab",
    "at", "mount", "umount", "fdisk", "sfdisk", "parted", "diskpart",
    " diskutil", "losetup", "cryptsetup", "lvm", "lvremove", "vgremove",
    "pvremove", "zpool", "zfs", "btrfs", "mdadm", "swapon", "swapoff",
    "iptables", "ip6tables", "nft", "ufw", "firewall-cmd", "setenforce",
    "sysctl", "modprobe", "insmod", "rmmod", "useradd", "userdel",
    "usermod", "groupadd", "groupdel", "passwd", "chpasswd", "visudo",
    "reg", "bcdedit", "netsh", "sc",
    # Network / remote execution / exfiltration
    "curl", "wget", "iwr", "invoke-webrequest", "irm", "invoke-restmethod",
    "ssh", "scp", "sftp", "rsync", "ftp", "tftp", "telnet",
    "nc", "ncat", "netcat", "socat", "openssl",
    # Containers / orchestration / infra mutation
    "docker", "podman", "nerdctl", "ctr", "crictl", "kubectl", "helm",
    "terraform", "pulumi", "ansible", "ansible-playbook", "vagrant",
})

#: System root directories whose binaries are root/admin tools by location.
ROOT_BINARY_PREFIXES: tuple[str, ...] = (
    "/sbin/", "/usr/sbin/", "/usr/local/sbin/", "/bin/", "/usr/bin/",
    "/system/", "/private/etc/", "c:\\windows\\", "c:/windows/",
)

#: Inline code execution flags per interpreter family.
_INTERPRETER_EXEC_FLAGS: dict[str, frozenset[str]] = {
    "python": frozenset({"-c", "-m", "-"}),
    "python2": frozenset({"-c", "-m", "-"}),
    "python3": frozenset({"-c", "-m", "-"}),
    "pypy": frozenset({"-c", "-m", "-"}),
    "pypy3": frozenset({"-c", "-m", "-"}),
    "node": frozenset({"-e", "--eval", "-p", "--print", "eval"}),
    "nodejs": frozenset({"-e", "--eval", "-p", "--print", "eval"}),
    "deno": frozenset({"eval", "run"}),
    "bun": frozenset({"-e", "--eval", "run", "x"}),
    "npx": frozenset({"*"}),
    "bunx": frozenset({"*"}),
    "uvx": frozenset({"*"}),
    "pipx": frozenset({"run"}),
    "perl": frozenset({"-e", "-E"}),
    "ruby": frozenset({"-e"}),
    "php": frozenset({"-r"}),
    "lua": frozenset({"-e"}),
    "osascript": frozenset({"-e"}),
    "Rscript": frozenset({"-e"}),
    "rscript": frozenset({"-e"}),
}

#: Multi-verb tools that require a subcommand in history suggestions, and safe git verbs.
_MULTI_VERB_TOOLS: frozenset[str] = frozenset({
    "git", "cargo", "ruff", "uv", "poetry", "go", "npm", "pnpm", "yarn",
})
_SAFE_GIT_SUBCOMMANDS: frozenset[str] = frozenset({
    "status", "diff", "log", "show", "rev-parse", "ls-files", " status", "describe",
})
_SUGGEST_ALLOWED_SINGLE_VERB: frozenset[str] = frozenset({
    "pytest", "mypy", "pyright", "flake8", "black", "isort", "shellcheck",
    "ls", "pwd", "whoami", "uname", "date", "wc", "head", "tail", "stat",
    "file", "which", "cat",
})


def _basename_lower(token: str) -> str:
    base = token.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
    return base[:-4] if base.endswith(".exe") else base


@dataclass(frozen=True)
class ShellCommandAnalysis:
    command: str
    argv: tuple[str, ...]
    executable: str
    quote_error: str | None
    compound: bool
    compound_reasons: tuple[str, ...]
    reinterpreting_flags: tuple[str, ...]
    has_env_assignment: bool
    root_or_path_binary: bool


def _scan_unquoted_shell_hazards(command: str) -> tuple[list[str], str | None]:
    """Return ``(hazard_reasons, quote_error)`` from a quote-aware walk of *command*.

    Single quotes protect everything until the matching ``'``. Double quotes protect
    separators like ``;`` and ``|`` as literal argument text, EXCEPT ``$(...)`` and
    backticks `` `...` `` which POSIX shells still evaluate inside double quotes.
    """
    reasons: list[str] = []
    seen: set[str] = set()

    def note(reason: str) -> None:
        if reason not in seen:
            seen.add(reason)
            reasons.append(reason)

    quote: str | None = None
    i = 0
    n = len(command)
    while i < n:
        ch = command[i]
        if quote == "'":
            if ch == "'":
                quote = None
            i += 1
            continue
        if quote == '"':
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == '"':
                quote = None
                i += 1
                continue
            if ch == "`":
                note("backtick_substitution")
            elif ch == "$" and i + 1 < n and command[i + 1] == "(":
                note("command_substitution")
            i += 1
            continue
        # Unquoted context
        if ch == "\\":
            if i + 1 < n:
                if command[i + 1] in ("\r", "\n"):
                    i += 3 if command[i + 1:i + 3] == "\r\n" else 2
                    continue
                i += 2
                continue
            return reasons, "trailing_backslash"
        if ch in ("'", '"'):
            quote = ch
            i += 1
            continue
        if ch == "#" and (i == 0 or command[i - 1].isspace()):
            # Comment runs until newline.
            newline = command.find("\n", i + 1)
            if newline < 0:
                break
            i = newline
            continue
        if ch in ("\r", "\n"):
            note("newline_separator")
            i += 1
            continue
        if ch == ";":
            note("semicolon_chain")
            i += 1
            continue
        if ch == "|":
            if i + 1 < n and command[i + 1] == "|":
                note("or_chain")
                i += 2
            else:
                note("pipeline")
                i += 1
            continue
        if ch == "&":
            if i + 1 < n and command[i + 1] == "&":
                note("and_chain")
                i += 2
            else:
                note("background_or_redirect")
                i += 1
            continue
        if ch == "`":
            note("backtick_substitution")
            i += 1
            continue
        if ch == "$" and i + 1 < n and command[i + 1] == "(":
            note("command_substitution")
            i += 2
            continue
        if ch in ("<", ">"):
            if i + 1 < n and command[i + 1] == "(":
                note("process_substitution")
                i += 2
            else:
                note("redirection")
                i += 1
            continue
        if ch in ("(", ")"):
            note("subshell_group")
            i += 1
            continue
        if ch == "{" and (i == 0 or command[i - 1].isspace()) and i + 1 < n and command[i + 1].isspace():
            note("brace_group")
            i += 1
            continue
        i += 1

    if quote is not None:
        return reasons, "unterminated_quote"
    return reasons, None


def _detect_reinterpreting_flags(argv: Sequence[str], raw_command: str) -> tuple[str, ...]:
    """Identify flags or wrappers that re-interpret argument text as code or commands."""
    findings: list[str] = []
    seen: set[str] = set()

    def add(item: str) -> None:
        if item not in seen:
            seen.add(item)
            findings.append(item)

    if not argv:
        return ()

    # Skip leading KEY=VALUE assignments to inspect the actual head word as well.
    idx = 0
    while idx < len(argv) and _ASSIGNMENT_RE.match(argv[idx]):
        idx += 1
    if idx >= len(argv):
        return ()

    head = argv[idx]
    exe = _basename_lower(head)
    rest = tuple(argv[idx + 1:])

    if exe in SHELL_AND_WRAPPER_BINARIES:
        add(f"wrapper_or_shell:{exe}")

    # Python combined short flags such as -Ic or -uc
    if exe in {"python", "python2", "python3", "pypy", "pypy3"}:
        for arg in rest:
            if arg == "--":
                break
            if arg in {"-c", "-m", "-"} or (
                arg.startswith("-") and not arg.startswith("--")
                and any(flag in arg[1:] for flag in ("c", "m"))
            ):
                add(f"interpreter_exec:{exe}:{arg}")
                break
            if not arg.startswith("-"):
                break
    elif exe in _INTERPRETER_EXEC_FLAGS:
        blocked = _INTERPRETER_EXEC_FLAGS[exe]
        if "*" in blocked:
            add(f"package_exec_runner:{exe}")
        else:
            for arg in rest:
                if arg == "--":
                    break
                flag = arg.split("=", 1)[0]
                if flag in blocked:
                    add(f"interpreter_exec:{exe}:{flag}")
                    break

    if exe == "find":
        for arg in rest:
            if arg in {"-exec", "-execdir", "-ok", "-okdir", "-delete"}:
                add(f"find_exec_or_delete:{arg}")

    if exe == "git":
        for pos, arg in enumerate(rest):
            if arg == "-c" or arg.startswith("-c"):
                cfg = arg[2:] if len(arg) > 2 else (rest[pos + 1] if pos + 1 < len(rest) else "")
                add(f"git_inline_config:{cfg.split('=', 1)[0] or '-c'}")
            elif arg.startswith(("--upload-pack", "--receive-pack", "--exec-path")):
                add(f"git_exec_flag:{arg.split('=', 1)[0]}")

    if exe == "cargo":
        for arg in rest:
            if arg == "--config" or arg.startswith("--config="):
                add("cargo_inline_config:--config")

    if exe in {"tar", "gtar"}:
        for arg in rest:
            if arg == "-I" or arg.startswith((
                "--checkpoint-action", "--to-command", "--use-compress-program",
            )):
                add(f"tar_exec_flag:{arg.split('=', 1)[0]}")

    if exe in {"awk", "gawk", "nawk", "mawk"} and any("system(" in arg for arg in rest):
        add("awk_system_call")

    if exe in {"sed", "gsed"}:
        for arg in rest:
            if arg == "-f" or arg.startswith("--file"):
                add("sed_script_file")
            elif re.search(r"(?:^|;)s(?P<sep>[^\w\s]).*?(?P=sep).*?(?P=sep)[a-z]*e", arg):
                add("sed_eval_substitute")

    if exe in {"make", "gmake"}:
        for arg in rest:
            if arg in {"-E", "--eval"} or arg.startswith("--eval="):
                add("make_eval_flag")

    if exe in {"rg", "ripgrep"}:
        for arg in rest:
            if arg == "--pre" or arg.startswith("--pre="):
                add("ripgrep_pre_exec")

    if exe == "zip":
        for arg in rest:
            if arg in {"-TT", "--unzip-command"} or arg.startswith("--unzip-command="):
                add("zip_test_command")

    # Also consult the pinned Hermes execution-flag detector for parity.
    try:
        normalized = detector._normalize_command_for_detection(raw_command)
        for description, _payload in detector._execution_flag_findings(normalized):
            add(f"hermes_exec_flag:{description}")
    except Exception:
        add("hermes_exec_scan_error")

    return tuple(findings)


def analyze_shell_command(command: str) -> ShellCommandAnalysis:
    """Parse *command* offline with quote-aware compound and re-interpreting-flag checks."""
    if not isinstance(command, str) or not command.strip() or "\x00" in command:
        return ShellCommandAnalysis(
            command=str(command or ""),
            argv=(),
            executable="",
            quote_error="empty_or_nul_command",
            compound=False,
            compound_reasons=(),
            reinterpreting_flags=(),
            has_env_assignment=False,
            root_or_path_binary=False,
        )
    stripped = command.strip()
    hazards, quote_err = _scan_unquoted_shell_hazards(stripped)
    argv: tuple[str, ...] = ()
    if quote_err is None:
        try:
            argv = tuple(shlex.split(stripped, posix=True))
        except ValueError as exc:
            quote_err = f"shlex_error:{exc}"
    if not argv and quote_err is None:
        quote_err = "empty_argv"

    has_env = bool(argv and _ASSIGNMENT_RE.match(argv[0]))
    idx = 0
    while idx < len(argv) and _ASSIGNMENT_RE.match(argv[idx]):
        idx += 1
    head = argv[idx] if idx < len(argv) else ""
    exe = _basename_lower(head) if head else ""
    root_or_path = bool(
        head and ("/" in head or "\\" in head or head.lower().startswith(ROOT_BINARY_PREFIXES))
    )
    reinterp = _detect_reinterpreting_flags(argv, stripped) if argv else ()
    return ShellCommandAnalysis(
        command=stripped,
        argv=argv,
        executable=exe,
        quote_error=quote_err,
        compound=bool(hazards),
        compound_reasons=tuple(hazards),
        reinterpreting_flags=reinterp,
        has_env_assignment=has_env,
        root_or_path_binary=root_or_path,
    )


def normalized_command_variants(command: str) -> list[str]:
    """Collect deduplicated raw, unwrapped, and deobfuscated command variants."""
    if not isinstance(command, str) or not command.strip():
        return []
    out: list[str] = []
    seen: set[str] = set()

    def push(text: str) -> None:
        cleaned = text.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            out.append(cleaned)

    push(command)
    try:
        for item in _detection_variants(command):
            rendered = item if isinstance(item, str) else " ".join(str(part) for part in item)
            push(rendered)
    except Exception:
        pass
    try:
        for item in detector._command_detection_variants(command):
            if isinstance(item, str):
                push(item)
    except Exception:
        pass
    return out


def validate_allowlist_pattern(pattern: str) -> str:
    """Validate and normalize one literal/glob allowlist pattern, raising ``ValueError`` if unsafe."""
    if not isinstance(pattern, str):
        raise ValueError("allowlist pattern must be a string")
    cleaned = " ".join(pattern.strip().split())
    if not cleaned or len(cleaned) > MAX_PATTERN_CHARS:
        raise ValueError("allowlist pattern must be 1..256 printable characters")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in cleaned):
        raise ValueError("allowlist pattern must not contain control characters")
    if all(ch in "*?[]" for ch in cleaned):
        raise ValueError("wildcard-only allowlist patterns are refused")

    hazards, quote_err = _scan_unquoted_shell_hazards(cleaned)
    if quote_err is not None:
        raise ValueError(f"allowlist pattern has invalid quoting ({quote_err})")
    if hazards:
        raise ValueError(f"allowlist pattern cannot contain compound shell syntax ({', '.join(hazards)})")

    tokens = shlex.split(cleaned, posix=True)
    if not tokens:
        raise ValueError("allowlist pattern must name a command")
    head = tokens[0]
    if _ASSIGNMENT_RE.match(head):
        raise ValueError("allowlist pattern cannot start with an environment assignment")
    if "/" in head or "\\" in head:
        raise ValueError(f"path-qualified or root binary patterns are refused: {head!r}")
    if any(ch in head for ch in "*?[]"):
        raise ValueError(f"wildcard in executable name is refused: {head!r}")
    if not _BINARY_TOKEN_RE.match(head):
        raise ValueError(f"invalid executable name in allowlist pattern: {head!r}")

    exe = _basename_lower(head)
    if exe in SHELL_AND_WRAPPER_BINARIES:
        raise ValueError(f"shell or wrapper executable cannot be allowlisted: {exe}")
    if exe in DESTRUCTIVE_AND_ROOT_BINARIES:
        raise ValueError(f"destructive or privileged executable cannot be allowlisted: {exe}")

    probe_flags = _detect_reinterpreting_flags(tokens, cleaned)
    if probe_flags:
        raise ValueError(f"allowlist pattern includes re-interpreting flag ({', '.join(probe_flags)})")
    if hardline_match(cleaned):
        raise ValueError("allowlist pattern matches terminal hardline denylist")
    return cleaned


def _canonical_single_command(argv: Sequence[str]) -> str:
    """Canonical projection of a parsed single command for glob matching."""
    return " ".join(argv)


def _pattern_matches_argv(pattern: str, argv: Sequence[str], raw: str) -> bool:
    """Return True when *argv* (a validated single command) matches *pattern*."""
    if not argv:
        return False
    pat_tokens = shlex.split(pattern, posix=True)
    if not pat_tokens:
        return False
    if argv[0] != pat_tokens[0]:
        return False
    canonical = _canonical_single_command(argv)
    has_glob = any(ch in pattern for ch in "*?[")
    if not has_glob:
        return list(argv) == pat_tokens
    return fnmatch.fnmatchcase(canonical, pattern) or fnmatch.fnmatchcase(" ".join(raw.split()), pattern)


def evaluate_allowlist(command: str, patterns: Iterable[str]) -> dict[str, Any]:
    """Evaluate *command* against *patterns* with full shell, floor, and variant guards."""
    analysis = analyze_shell_command(command)
    if analysis.quote_error:
        return {"matched": False, "pattern": None, "blocked_reason": f"quote_error:{analysis.quote_error}"}
    if hardline := hardline_match(command):
        return {"matched": False, "pattern": None, "blocked_reason": f"hardline_denied:{hardline}"}
    if content := scan_command_content(command):
        return {"matched": False, "pattern": None, "blocked_reason": f"content_scanner:{content[0]}"}
    if analysis.compound:
        return {
            "matched": False,
            "pattern": None,
            "blocked_reason": f"compound_command:{','.join(analysis.compound_reasons)}",
        }
    if analysis.has_env_assignment:
        return {"matched": False, "pattern": None, "blocked_reason": "env_assignment_prefix"}
    if analysis.root_or_path_binary:
        return {"matched": False, "pattern": None, "blocked_reason": "path_or_root_binary"}
    if analysis.executable in SHELL_AND_WRAPPER_BINARIES:
        return {"matched": False, "pattern": None, "blocked_reason": f"wrapper_or_shell:{analysis.executable}"}
    if analysis.executable in DESTRUCTIVE_AND_ROOT_BINARIES:
        return {"matched": False, "pattern": None, "blocked_reason": f"destructive_binary:{analysis.executable}"}
    if analysis.reinterpreting_flags:
        return {
            "matched": False,
            "pattern": None,
            "blocked_reason": f"reinterpreting_flag:{','.join(analysis.reinterpreting_flags)}",
        }
    is_dangerous, _, danger_desc = detector.detect_dangerous_command(command)
    if is_dangerous:
        return {"matched": False, "pattern": None, "blocked_reason": f"dangerous_pattern:{danger_desc}"}

    # Screen every unwrapped/deobfuscated variant as well so intra-word quote splicing cannot slip by.
    for variant in normalized_command_variants(command):
        if hardline_match(variant):
            return {"matched": False, "pattern": None, "blocked_reason": "variant_hardline_denied"}
        var_danger, _, var_desc = detector.detect_dangerous_command(variant)
        if var_danger:
            return {"matched": False, "pattern": None, "blocked_reason": f"variant_dangerous:{var_desc}"}

    valid_patterns: list[str] = []
    for raw_pat in patterns:
        try:
            valid_patterns.append(validate_allowlist_pattern(raw_pat))
        except ValueError:
            continue

    for pat in valid_patterns:
        if _pattern_matches_argv(pat, analysis.argv, analysis.command):
            return {"matched": True, "pattern": pat, "blocked_reason": None}
    return {"matched": False, "pattern": None, "blocked_reason": None}


class CommandAllowlistStore:
    """Owner-managed persistent command allowlist under ``<data_root>/autonomy/command_allowlist.json``."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = Path(path) if path is not None else data_path("autonomy", "command_allowlist.json")

    @property
    def path(self) -> Path:
        return self._path

    def list_patterns(self) -> list[str]:
        if not self._path.is_file() or self._path.is_symlink():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(raw, dict) or not isinstance(raw.get("patterns"), list):
            return []
        kept: list[str] = []
        seen: set[str] = set()
        for entry in raw["patterns"][:MAX_PATTERNS]:
            try:
                normalized = validate_allowlist_pattern(entry)
            except ValueError:
                continue
            if normalized not in seen:
                seen.add(normalized)
                kept.append(normalized)
        return kept

    def _write_patterns(self, patterns: Sequence[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for item in patterns:
            normalized = validate_allowlist_pattern(item)
            if normalized not in seen:
                seen.add(normalized)
                deduped.append(normalized)
        if len(deduped) > MAX_PATTERNS:
            raise ValueError(f"allowlist cannot exceed {MAX_PATTERNS} patterns")
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self._path.exists() and self._path.is_symlink():
            raise ValueError("refusing to write allowlist through a symlink")
        payload = json.dumps(
            {"version": SCHEMA_VERSION, "patterns": deduped},
            indent=2,
            ensure_ascii=False,
        ) + "\n"
        fd, tmp_name = tempfile.mkstemp(prefix=".allowlist-", dir=str(self._path.parent))
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, self._path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return deduped

    def add(self, pattern: str) -> list[str]:
        normalized = validate_allowlist_pattern(pattern)
        current = self.list_patterns()
        if normalized not in current:
            current.append(normalized)
        return self._write_patterns(current)

    def remove(self, pattern: str) -> tuple[bool, list[str]]:
        target = " ".join(str(pattern or "").strip().split())
        current = self.list_patterns()
        remaining = [p for p in current if p != target]
        removed = len(remaining) != len(current)
        if removed:
            self._write_patterns(remaining)
        return removed, remaining

    def clear(self) -> None:
        self._write_patterns(())

    def evaluate(self, command: str) -> dict[str, Any]:
        return evaluate_allowlist(command, self.list_patterns())


def _load_approved_history_from_db(db_path: Path | None = None, *, limit: int = 500) -> list[str]:
    """Read approved ``toolrpc.terminal_run`` commands from the local autonomy SQLite DB."""
    target = Path(db_path) if db_path is not None else data_path("autonomy.db")
    if not target.is_file() or target.is_symlink():
        return []
    commands: list[str] = []
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(f"file:{target}?mode=ro", uri=True, timeout=2.0)
        rows = conn.execute(
            """SELECT payload FROM autonomy_tasks
               WHERE kind = 'toolrpc.terminal_run'
                 AND status IN ('done', 'approved', 'running')
                 AND COALESCE(decided_by, '') != ''
                 AND LOWER(COALESCE(decided_by, '')) != 'policy'
               ORDER BY id DESC LIMIT ?""",
            (max(1, min(5000, int(limit))),),
        ).fetchall()
        for (raw_payload,) in rows:
            try:
                parsed = json.loads(raw_payload) if isinstance(raw_payload, str) else raw_payload
            except ValueError:
                continue
            args = parsed.get("args") if isinstance(parsed, Mapping) else None
            cmd = args.get("command") if isinstance(args, Mapping) else None
            if isinstance(cmd, str) and cmd.strip():
                commands.append(cmd.strip())
    except sqlite3.Error:
        return []
    finally:
        if conn is not None:
            conn.close()
    return commands


def _candidate_narrow_rule(analysis: ShellCommandAnalysis) -> tuple[str | None, str | None]:
    """Derive a narrow allowlist rule ``(rule, exclusion_reason)`` for one safe command."""
    if analysis.quote_error:
        return None, f"quote_error:{analysis.quote_error}"
    if analysis.compound:
        return None, f"compound:{','.join(analysis.compound_reasons)}"
    if analysis.has_env_assignment:
        return None, "env_assignment_prefix"
    if analysis.root_or_path_binary:
        return None, f"root_or_path_binary:{analysis.argv[0] if analysis.argv else ''}"
    exe = analysis.executable
    if not exe or not _BINARY_TOKEN_RE.match(analysis.argv[0]):
        return None, "invalid_executable"
    if exe in SHELL_AND_WRAPPER_BINARIES:
        return None, f"wrapper_or_shell:{exe}"
    if exe in DESTRUCTIVE_AND_ROOT_BINARIES:
        return None, f"destructive_class:{exe}"
    if analysis.reinterpreting_flags:
        return None, f"reinterpreting_flag:{','.join(analysis.reinterpreting_flags)}"
    if hardline_match(analysis.command):
        return None, "hardline_denied"
    if scan_command_content(analysis.command):
        return None, "content_scanner_flagged"
    is_dangerous, _, desc = detector.detect_dangerous_command(analysis.command)
    if is_dangerous:
        return None, f"dangerous_pattern:{desc}"

    argv = analysis.argv
    if exe == "git":
        if len(argv) < 2 or argv[1].startswith("-"):
            return None, "git_missing_subcommand"
        sub = argv[1]
        if sub not in _SAFE_GIT_SUBCOMMANDS:
            return None, f"git_mutating_or_network_subcommand:{sub}"
        pattern = f"git {sub}" if len(argv) == 2 else f"git {sub} *"
    elif exe in _MULTI_VERB_TOOLS:
        if len(argv) < 2 or argv[1].startswith("-"):
            return None, f"{exe}_missing_subcommand"
        sub = argv[1]
        if not _BINARY_TOKEN_RE.match(sub):
            return None, f"{exe}_invalid_subcommand"
        if sub in {"publish", "install", "uninstall", "add", "remove", "login", "logout", "clean"}:
            return None, f"{exe}_mutating_subcommand:{sub}"
        pattern = f"{exe} {sub}" if len(argv) == 2 else f"{exe} {sub} *"
    elif exe in _SUGGEST_ALLOWED_SINGLE_VERB:
        pattern = exe if len(argv) == 1 else f"{exe} *"
    else:
        return None, f"unreviewed_binary_class:{exe}"

    try:
        validated = validate_allowlist_pattern(pattern)
    except ValueError as exc:
        return None, f"pattern_invalid:{exc}"
    return validated, None


def suggest_allowlist_rules(
    commands: Iterable[str] | None = None,
    *,
    min_count: int = 2,
    apply: bool = False,
    store: CommandAllowlistStore | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Propose narrow allowlist rules from command history; write ONLY when ``apply=True``."""
    threshold = max(1, int(min_count))
    allowlist_store = store if store is not None else CommandAllowlistStore()
    existing = set(allowlist_store.list_patterns())
    history = list(commands) if commands is not None else _load_approved_history_from_db(db_path)

    counts: Counter[str] = Counter()
    examples: dict[str, list[str]] = {}
    excluded: list[dict[str, str]] = []

    for raw in history:
        if not isinstance(raw, str) or not raw.strip():
            continue
        analysis = analyze_shell_command(raw)
        rule, reason = _candidate_narrow_rule(analysis)
        if rule is None:
            excluded.append({"command": raw.strip()[:200], "reason": reason or "excluded"})
            continue
        counts[rule] += 1
        sample = examples.setdefault(rule, [])
        if raw.strip() not in sample and len(sample) < 3:
            sample.append(raw.strip())

    proposals = [
        {
            "pattern": rule,
            "count": count,
            "already_present": rule in existing,
            "examples": examples.get(rule, []),
        }
        for rule, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        if count >= threshold and rule not in existing
    ]

    added: list[str] = []
    if apply and proposals:
        merged = allowlist_store.list_patterns()
        for item in proposals:
            pat = item["pattern"]
            if pat not in merged:
                merged.append(pat)
                added.append(pat)
        if added:
            allowlist_store._write_patterns(merged)

    return {
        "scanned": len(history),
        "min_count": threshold,
        "applied": bool(apply),
        "added": added,
        "proposals": proposals,
        "excluded": excluded,
        "store_path": str(allowlist_store.path),
    }


def explain_command_policy(
    command: str,
    *,
    environ: Mapping[str, str] | None = None,
    store: CommandAllowlistStore | None = None,
    autonomy_mode: str | None = None,
) -> dict[str, Any]:
    """Offline dry-run ('what-if') evaluation of every shell policy layer on *command*."""
    analysis = analyze_shell_command(command)
    variants = normalized_command_variants(command)
    hardline = hardline_match(command)
    content_findings = list(scan_command_content(command) or ())

    is_dangerous, danger_key, danger_desc = (
        detector.detect_dangerous_command(command)
        if isinstance(command, str) and command.strip()
        else (False, None, None)
    )

    descriptions = terminal_consent_descriptions()
    raw_categories = (
        terminal_consent_categories(command, resolved_user_home=str(Path.home()))
        if isinstance(command, str) and command.strip()
        else None
    )
    consent_rows = [
        {
            "key": cat.key,
            "description": descriptions.get(cat.key, cat.key),
            "permanent": cat.permanent,
        }
        for cat in (raw_categories or ())
    ]

    variant_reports: list[dict[str, Any]] = []
    for variant in variants:
        v_hardline = hardline_match(variant)
        v_danger, _, v_desc = detector.detect_dangerous_command(variant)
        v_content = list(scan_command_content(variant) or ())
        variant_reports.append({
            "variant": variant,
            "hardline": v_hardline,
            "dangerous": v_desc if v_danger else None,
            "content_findings": v_content,
        })
        if hardline is None and v_hardline is not None:
            hardline = v_hardline
        if not is_dangerous and v_danger:
            is_dangerous, danger_key, danger_desc = True, v_desc, v_desc
        for finding in v_content:
            if finding not in content_findings:
                content_findings.append(finding)

    allowlist_store = store if store is not None else CommandAllowlistStore()
    allowlist_eval = allowlist_store.evaluate(command)

    sp = smart_policy(environ)
    smart_allowed = sp.command_allowed(command)

    if autonomy_mode is None:
        try:
            from .. import safe_mode

            autonomy_mode = read_mode(safe_mode.get_value("autonomy", "mode", "auto"))
        except Exception:
            autonomy_mode = "ask"
    else:
        autonomy_mode = read_mode(autonomy_mode)

    estop_state = estop.get_state()

    reasons: list[str] = []
    if estop_state is not None:
        verdict = "deny"
        reasons.append("estop_engaged")
    elif analysis.quote_error:
        verdict = "deny"
        reasons.append(f"quote_error:{analysis.quote_error}")
    elif hardline is not None:
        verdict = "deny"
        reasons.append(f"hardline_denied:{hardline}")
    elif content_findings:
        verdict = "deny"
        reasons.extend(f"content_scanner:{item}" for item in content_findings)
    elif autonomy_mode == "off":
        verdict = "ask"
        reasons.append("autonomy_mode_off")
    elif allowlist_eval["matched"] and not is_dangerous:
        verdict = "allow"
        reasons.append(f"allowlist_match:{allowlist_eval['pattern']}")
    else:
        verdict = "ask"
        if is_dangerous and danger_desc:
            reasons.append(f"dangerous_command:{danger_desc}")
        if allowlist_eval.get("blocked_reason"):
            reasons.append(f"allowlist_guard:{allowlist_eval['blocked_reason']}")
        if not reasons:
            reasons.append("terminal_requires_approval")

    gates = [
        {"gate": "kill-switch", "result": "engaged" if estop_state else "clear"},
        {"gate": "shell-parse", "result": analysis.quote_error or ("compound" if analysis.compound else "single")},
        {"gate": "variants", "result": f"{len(variants)} inspected"},
        {"gate": "hardline", "result": f"denied ({hardline})" if hardline else "clear"},
        {"gate": "content-scan", "result": ", ".join(content_findings) if content_findings else "clear"},
        {"gate": "dangerous", "result": danger_desc if is_dangerous and danger_desc else "clear"},
        {"gate": "allowlist", "result": (
            f"matched ({allowlist_eval['pattern']})"
            if allowlist_eval["matched"]
            else (f"blocked ({allowlist_eval['blocked_reason']})" if allowlist_eval.get("blocked_reason") else "no match")
        )},
        {"gate": "smart-policy", "result": (
            "enabled (eligible)" if sp.enabled and smart_allowed
            else ("enabled (denied)" if sp.enabled else "disabled")
        )},
        {"gate": "autonomy-mode", "result": autonomy_mode},
    ]

    return {
        "command": command,
        "verdict": verdict,
        "reasons": reasons,
        "shell_analysis": {
            "argv": list(analysis.argv),
            "executable": analysis.executable,
            "quote_error": analysis.quote_error,
            "compound": analysis.compound,
            "compound_reasons": list(analysis.compound_reasons),
            "reinterpreting_flags": list(analysis.reinterpreting_flags),
            "has_env_assignment": analysis.has_env_assignment,
            "root_or_path_binary": analysis.root_or_path_binary,
        },
        "normalized_variants": variants,
        "variant_findings": variant_reports,
        "hardline": hardline,
        "content_findings": content_findings,
        "dangerous": {
            "matched": bool(is_dangerous),
            "key": danger_key,
            "description": danger_desc,
        },
        "consent_categories": consent_rows,
        "allowlist": allowlist_eval,
        "smart_approvals": {
            "enabled": sp.enabled,
            "command_allowed": smart_allowed,
        },
        "autonomy_mode": autonomy_mode,
        "estop": estop_state,
        "gates": gates,
    }


__all__ = [
    "CommandAllowlistStore",
    "DESTRUCTIVE_AND_ROOT_BINARIES",
    "SHELL_AND_WRAPPER_BINARIES",
    "ShellCommandAnalysis",
    "analyze_shell_command",
    "evaluate_allowlist",
    "explain_command_policy",
    "normalized_command_variants",
    "suggest_allowlist_rules",
    "validate_allowlist_pattern",
]
