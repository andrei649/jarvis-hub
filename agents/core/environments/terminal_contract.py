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
   worth more than a clever exception.
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
from collections.abc import Mapping, Sequence
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

_WRAPPERS = frozenset({"sudo", "doas", "env", "nice", "nohup", "xargs", "time", "command", "exec"})

# A "command position": start of the text or right after a shell operator, with
# optional privilege/wrapper prefixes. Anchoring here keeps `echo shutdown` or a
# commit message mentioning mkfs from tripping the line, while `foo; shutdown`
# and `sudo mkfs` still do.
_CMD = r"(?:^|[;&|(`]\s*)(?:(?:sudo|doas|env|nice|nohup|xargs|time|command|exec)\s+(?:-\S+\s+)*)*"

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


def _normalize(command: str | Sequence[str]) -> tuple[str, tuple[tuple[str, ...], ...]]:
    """Return ``(flat_text, segments)`` for either a command string or an argv.

    A command *string* may be destined for a shell (the docker path), so it is
    split at shell operators into segments and each segment is screened on its
    own; an argv *sequence* never meets a shell and is one segment.
    """
    if isinstance(command, str):
        text = command
        try:
            lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
            lexer.whitespace_split = True
            tokens = tuple(lexer)
        except ValueError:
            tokens = tuple(command.split())
        segments: list[tuple[str, ...]] = []
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


def hardline_match(command: str | Sequence[str]) -> str | None:
    """Return the name of the first hardline entry the command hits, else ``None``.

    Accepts a raw command string or an argv sequence. Static, case-insensitive,
    never raises for ordinary input; a normalization failure is a match on
    nothing (the caller still fails closed on invalid argv shapes).
    """
    try:
        flat, segments = _normalize(command)
    except Exception:
        return "unparseable"
    if not flat:
        return None
    if any(_recursive_root_removal(segment) for segment in segments):
        return "recursive_root_removal"
    for entry in HARDLINE:
        if entry.matches(flat):
            return entry.name
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
