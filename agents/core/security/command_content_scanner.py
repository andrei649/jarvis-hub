"""H508 — In-process pre-command content scanner for homograph/IDN URLs & escape injection.

Screens terminal command strings before execution / consent classification for two classes
of deception that NFKC / ANSI-stripping pattern matchers otherwise normalise away:

1. **Homograph / IDN / confusable hosts in argv URLs** (punycode ``xn--`` labels, mixed-script
   or non-ASCII look-alike hostnames such as Cyrillic ``аррӏе.com`` or ``gіthub.com``,
   fullwidth / confusable characters, and invisible format characters in URL or SCP hosts).
2. **Terminal-escape & control injection** (OSC title/clipboard sequences ``\\x1b]``,
   DCS/SOS/PM/APC control strings, non-SGR CSI cursor/erase/mode sequences such as
   ``\\x1b[2K`` or ``\\x1b[1A``, bare ``\\r`` line-overwrite, backspace ``\\x08`` masking,
   raw C0/C1 controls, and Trojan Source bidirectional override characters). Pure SGR colour
   sequences (``\\x1b[[0-9;]*m``) alone are permitted so coloured wrappers retain their
   underlying warning identity.

Availability & policy semantics:
- **Fail-open default** (``security.command_scanner_fail_open = True``): if the scanner hits
  an internal error or its circuit breaker is open, it logs a warning and returns ``()``.
- **Circuit breaker + 24h failure marker**: after ``FAILURE_THRESHOLD`` consecutive internal
  errors, the breaker opens for ``BREAKER_COOLDOWN_SECONDS`` and records a non-symlink marker
  under ``<data_root>/security/command_scanner_failure.json`` (24h TTL).
- **Fail-closed mode** (``security.command_scanner_fail_open = False``): whenever a scan fails
  or the scanner is unavailable (breaker open / active failure marker), it emits a
  **synthesized ``HIGH`` finding** routed to the human gate with **session-only** scope.
"""

from __future__ import annotations

import json
import logging
import re
import shlex
import threading
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from agents.core.paths import data_path

logger = logging.getLogger("jarvis.security.command_scanner")

HOMOGRAPH_HOST_DESCRIPTION = "homograph or IDN confusable host in command URL"
TERMINAL_ESCAPE_DESCRIPTION = "terminal escape or bidi control injection in command"
SCANNER_UNAVAILABLE_DESCRIPTION = "content scanner unavailable under fail-closed policy"

HOMOGRAPH_HOST_KEY = "terminal.warning.homograph_or_idn_confusable_host_in_command_url"
TERMINAL_ESCAPE_KEY = "terminal.warning.terminal_escape_or_bidi_control_injection_in_command"
SCANNER_UNAVAILABLE_KEY = "terminal.warning.content_scanner_unavailable_under_fail_closed_policy"

FAILURE_THRESHOLD = 3
BREAKER_COOLDOWN_SECONDS = 300.0
MARKER_TTL_SECONDS = 86_400.0

# Pure SGR colour codes (`\x1b[31m`, `\x1b[0m`, `\x1b[1;32m`) do not move the cursor,
# erase text, touch the clipboard, or redefine keys.
_PURE_SGR_RE = re.compile(r"\x1b\[[0-9;]*m")

# Dangerous terminal escape & control patterns checked AFTER stripping pure SGR codes:
_OSC_OR_STRING_ESC_RE = re.compile(r"\x1b[\]PX^_]|[\x90\x98\x9d\x9e\x9f]")
_NON_SGR_CSI_RE = re.compile(r"\x1b\[[0-9;?<>!]*[A-Za-ln-z@-~]|\x1b\[[?<>!][0-9;]*m")
_OTHER_ESC_RE = re.compile(r"\x1b")
_BARE_CR_RE = re.compile(r"\r(?!\n)")
_BIDI_CONTROL_RE = re.compile(r"[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]")
_RAW_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1a\x1c-\x1f\x7f-\x9f]")

# URL & SSH/SCP target extraction inside argv tokens:
_URL_SUBSTRING_RE = re.compile(
    r"(?:https?|ssh|git|ftps?|sftp|wss?)://[^\s'\"<>`|;&]+",
    re.IGNORECASE,
)
# Matches `git@host:org/repo` or `user@host:/path` while avoiding plain `user@domain` emails
# that have no `:path` suffix and avoiding URLs (`://`).
_SCP_TARGET_RE = re.compile(
    r"^(?:[A-Za-z0-9._-]+@)([^\s/:@]+):[A-Za-z0-9._~/+-]+$"
)
_INVISIBLE_HOST_CHARS_RE = re.compile(
    r"[\u00ad\u034f\u180e\u200b-\u200f\u2028\u2029\u2060-\u2064\ufeff]"
)

# High-signal Unicode confusable characters frequently used in IDN homograph attacks against
# ASCII hostnames (Cyrillic, Greek, Armenian, Latin look-alikes, and fullwidth forms).
_CONFUSABLE_CODEPOINTS: frozenset[str] = frozenset(
    ch
    for ch in (
        "аеіорсухѕјӏԁԛԝ"  # Cyrillic lowercase look-alikes
        "АВЕКМНОРСТУХЅЈӀ"  # Cyrillic uppercase look-alikes
        "αβγδεζηικλμνξοπρστυφχψω"  # Greek lowercase
        "ΑΒΕΖΗΙΚΜΝΟΡΤΥΧ"  # Greek uppercase
        "ıȷɑɡɩɫɪʀꜱ"  # Latin dotless / IPA look-alikes
        "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘꞯʀꜱᴛᴜᴠᴡʏᴢ"
    )
    if ord(ch) > 127
)


@dataclass(frozen=True, slots=True)
class CommandScanFinding:
    """One pre-command content finding routed to the session-only human gate."""

    category_key: str
    description: str
    severity: str
    detail: str
    session_only: bool = True


def _char_script(ch: str) -> str:
    """Coarse Unicode script bucket for mixed-script hostname detection."""
    cp = ord(ch)
    if cp < 128:
        if ch.isalpha():
            return "LATIN"
        return "COMMON"
    if 0xFF01 <= cp <= 0xFF5E:
        return "FULLWIDTH"
    name = unicodedata.name(ch, "")
    for script in (
        "LATIN",
        "CYRILLIC",
        "GREEK",
        "ARMENIAN",
        "HEBREW",
        "ARABIC",
        "DEVANAGARI",
        "HAN",
        "HIRAGANA",
        "KATAKANA",
        "HANGUL",
        "THAI",
    ):
        if script in name:
            return script
    return "OTHER_NON_ASCII"


_PURE_URL_TOKEN_RE = re.compile(
    r"^(?:https?|ssh|git|ftps?|sftp|wss?)://[^\s'\"<>`|;&]+$",
    re.IGNORECASE,
)


def _extract_candidate_hosts(command: str, *, _depth: int = 0) -> list[str]:
    """Extract URL and SSH/SCP hostnames from argv tokens (and nested -c/-lc scripts)."""
    if _depth > 3:
        return []
    hosts: list[str] = []

    def _parse_url_host(raw_url: str) -> None:
        cleaned = raw_url.rstrip(".,;)]}'\"")
        try:
            parsed = urlsplit(cleaned)
        except ValueError:
            authority = cleaned.split("://", 1)[-1].split("/", 1)[0]
            host = authority.rsplit("@", 1)[-1].split(":", 1)[0].strip("[]")
            if host:
                hosts.append(host)
            return
        if parsed.hostname:
            hosts.append(parsed.hostname)

    # Split unquoted shell pipeline/chain segments (`|`, `&&`, `||`, `;`) first so each
    # command in a pipeline has its own argv inspected while quoted prose stays intact.
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars="|;&")
        lexer.whitespace_split = True
        raw_tokens = list(lexer)
    except ValueError:
        raw_tokens = command.split()

    segments: list[list[str]] = [[]]
    for tok in raw_tokens:
        if tok in {"|", "||", "&&", ";", "&"}:
            if segments[-1]:
                segments.append([])
        else:
            segments[-1].append(tok)

    for seg in segments:
        if not seg:
            continue
        head = Path(seg[0]).name.lower()
        # `echo` / `printf` print literal strings rather than fetching URLs.
        if head in {"echo", "printf"}:
            continue
        for idx, tok in enumerate(seg):
            if tok in ("-c", "-lc", "-e") and idx + 1 < len(seg):
                hosts.extend(_extract_candidate_hosts(seg[idx + 1], _depth=_depth + 1))
                continue
            value = tok.split("=", 1)[1] if tok.startswith("-") and "=" in tok else tok
            if _PURE_URL_TOKEN_RE.match(value):
                _parse_url_host(value)
                continue
            scp_match = _SCP_TARGET_RE.match(value)
            if scp_match:
                hosts.append(scp_match.group(1).strip("[]"))

    return hosts


def _inspect_host_for_homograph(host: str) -> str | None:
    """Return a finding detail string if *host* uses IDN punycode or confusables, else None."""
    cleaned = host.strip().rstrip(".")
    if not cleaned:
        return None
    if _INVISIBLE_HOST_CHARS_RE.search(cleaned):
        return f"invisible/format character in host {cleaned!r}"

    labels = [lbl for lbl in cleaned.split(".") if lbl]
    if not labels:
        return None

    host_scripts: set[str] = set()
    for label in labels:
        low = label.lower()
        if low.startswith("xn--"):
            return f"IDN punycode label {label!r} in host {cleaned!r}"
        label_scripts = {_char_script(ch) for ch in label if _char_script(ch) != "COMMON"}
        host_scripts |= label_scripts
        if "FULLWIDTH" in label_scripts:
            return f"fullwidth confusable characters in host {cleaned!r}"
        if len(label_scripts) > 1:
            return f"mixed-script label {label!r} ({sorted(label_scripts)}) in host {cleaned!r}"
        if any(ch in _CONFUSABLE_CODEPOINTS for ch in label):
            return f"Unicode confusable character in host {cleaned!r}"
        if any(ord(ch) > 127 for ch in label):
            return f"non-ASCII IDN hostname {cleaned!r}"

    if len(host_scripts) > 1:
        return f"cross-label mixed-script hostname {cleaned!r} ({sorted(host_scripts)})"
    return None


def _default_probe(command: str) -> tuple[CommandScanFinding, ...]:
    """Pure in-process scan for homograph URLs and terminal-escape injection."""
    findings: list[CommandScanFinding] = []

    # 1. Terminal-escape / bidi / raw control injection check (ignoring pure SGR colour).
    without_sgr = _PURE_SGR_RE.sub("", command)
    escape_reason: str | None = None
    if _BIDI_CONTROL_RE.search(without_sgr):
        escape_reason = "bidirectional control override character"
    elif _OSC_OR_STRING_ESC_RE.search(without_sgr):
        escape_reason = "OSC/DCS/APC terminal control string"
    elif _NON_SGR_CSI_RE.search(without_sgr):
        escape_reason = "non-SGR CSI cursor/erase/mode escape sequence"
    elif _OTHER_ESC_RE.search(without_sgr):
        escape_reason = "raw ESC control sequence"
    elif _BARE_CR_RE.search(without_sgr):
        escape_reason = "bare carriage-return line overwrite"
    elif _RAW_CONTROL_RE.search(without_sgr):
        escape_reason = "raw C0/C1/DEL control character"

    if escape_reason is not None:
        findings.append(
            CommandScanFinding(
                category_key=TERMINAL_ESCAPE_KEY,
                description=TERMINAL_ESCAPE_DESCRIPTION,
                severity="HIGH",
                detail=escape_reason,
                session_only=True,
            )
        )

    # 2. Homograph / IDN / confusable hosts in argv URLs & SSH targets.
    for host in _extract_candidate_hosts(command):
        homograph_reason = _inspect_host_for_homograph(host)
        if homograph_reason is not None:
            findings.append(
                CommandScanFinding(
                    category_key=HOMOGRAPH_HOST_KEY,
                    description=HOMOGRAPH_HOST_DESCRIPTION,
                    severity="HIGH",
                    detail=homograph_reason,
                    session_only=True,
                )
            )
            break

    return tuple(findings)


def _configured_fail_open() -> bool:
    """Read ``security.command_scanner_fail_open`` (default ``True`` = fail-open)."""
    try:
        from agents.core import safe_mode

        val = safe_mode.get_value("security", "command_scanner_fail_open", True)
        if isinstance(val, bool):
            return val
        return bool(val)
    except Exception:
        return True


class CommandContentScanner:
    """In-process pre-command scanner with circuit breaker and fail-open/closed policy."""

    def __init__(
        self,
        *,
        probe_fn: Callable[[str], tuple[CommandScanFinding, ...]] | None = None,
        failure_threshold: int = FAILURE_THRESHOLD,
        cooldown_seconds: float = BREAKER_COOLDOWN_SECONDS,
        marker_ttl_seconds: float = MARKER_TTL_SECONDS,
        marker_path: Path | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._probe = probe_fn or _default_probe
        self._failure_threshold = max(1, int(failure_threshold))
        self._cooldown_seconds = max(0.0, float(cooldown_seconds))
        self._marker_ttl_seconds = max(1.0, float(marker_ttl_seconds))
        self._marker_path = marker_path
        self._clock = clock
        self._lock = threading.Lock()
        self._consecutive_failures = 0
        self._opened_until = 0.0
        self._last_error = ""

    def _resolved_marker_path(self) -> Path:
        if self._marker_path is not None:
            return self._marker_path
        return data_path("security", "command_scanner_failure.json")

    def _write_failure_marker(self, now: float, error: str) -> None:
        path = self._resolved_marker_path()
        try:
            parent = path.parent
            if parent.exists() and parent.is_symlink():
                return
            parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.is_symlink():
                return
            payload = {
                "recorded_at": now,
                "expires_at": now + self._marker_ttl_seconds,
                "consecutive_failures": self._consecutive_failures,
                "error": error[:200],
            }
            tmp = parent / f".{path.name}.tmp"
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            logger.debug("could not persist command scanner failure marker", exc_info=True)

    def _clear_failure_marker(self) -> None:
        path = self._resolved_marker_path()
        try:
            if path.exists() and not path.is_symlink():
                path.unlink()
        except OSError:
            pass

    def has_active_failure_marker(self) -> bool:
        path = self._resolved_marker_path()
        try:
            if not path.is_file() or path.is_symlink():
                return False
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return False
            expires_at = float(data.get("expires_at", 0.0))
            return self._clock() < expires_at
        except (OSError, TypeError, ValueError):
            return False

    @property
    def breaker_open(self) -> bool:
        with self._lock:
            return self._clock() < self._opened_until

    def reset(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._opened_until = 0.0
            self._last_error = ""
        self._clear_failure_marker()

    @staticmethod
    def _synthesized_unavailable_finding(detail: str) -> CommandScanFinding:
        return CommandScanFinding(
            category_key=SCANNER_UNAVAILABLE_KEY,
            description=SCANNER_UNAVAILABLE_DESCRIPTION,
            severity="HIGH",
            detail=detail,
            session_only=True,
        )

    def scan(
        self,
        command: str,
        *,
        fail_open: bool | None = None,
    ) -> tuple[CommandScanFinding, ...]:
        """Scan *command* and return findings; apply fail-open or fail-closed on outage."""
        if not isinstance(command, str) or not command.strip():
            return ()
        effective_fail_open = _configured_fail_open() if fail_open is None else bool(fail_open)
        now = self._clock()

        with self._lock:
            is_open = now < self._opened_until
            last_err = self._last_error

        if is_open:
            if effective_fail_open:
                logger.warning(
                    "command content scanner circuit breaker open (%s); failing open",
                    last_err or "unavailable",
                )
                return ()
            return (
                self._synthesized_unavailable_finding(
                    f"circuit breaker open: {last_err or 'scanner unavailable'}"
                ),
            )

        try:
            result = self._probe(command)
        except Exception as exc:
            err_msg = f"{type(exc).__name__}: {exc}"
            tripped = False
            with self._lock:
                self._consecutive_failures += 1
                self._last_error = err_msg
                if self._consecutive_failures >= self._failure_threshold:
                    self._opened_until = now + self._cooldown_seconds
                    tripped = True
            if tripped:
                self._write_failure_marker(now, err_msg)
            if effective_fail_open:
                logger.warning(
                    "command content scanner internal error (%s); failing open",
                    err_msg,
                )
                return ()
            return (
                self._synthesized_unavailable_finding(
                    f"scanner error under fail-closed policy: {err_msg}"
                ),
            )

        # Successful probe resets breaker state and clears any stale marker.
        had_failures = False
        with self._lock:
            if self._consecutive_failures > 0 or self._opened_until > 0.0:
                self._consecutive_failures = 0
                self._opened_until = 0.0
                self._last_error = ""
                had_failures = True
        if had_failures:
            self._clear_failure_marker()
        return result


DEFAULT_COMMAND_SCANNER = CommandContentScanner()


def scan_command_content(
    command: str,
    *,
    fail_open: bool | None = None,
    scanner: CommandContentScanner | None = None,
) -> tuple[CommandScanFinding, ...]:
    """Run the shared in-process pre-command content scanner."""
    active = scanner if scanner is not None else DEFAULT_COMMAND_SCANNER
    return active.scan(command, fail_open=fail_open)


__all__ = [
    "BREAKER_COOLDOWN_SECONDS",
    "CommandContentScanner",
    "CommandScanFinding",
    "DEFAULT_COMMAND_SCANNER",
    "FAILURE_THRESHOLD",
    "HOMOGRAPH_HOST_DESCRIPTION",
    "HOMOGRAPH_HOST_KEY",
    "MARKER_TTL_SECONDS",
    "SCANNER_UNAVAILABLE_DESCRIPTION",
    "SCANNER_UNAVAILABLE_KEY",
    "TERMINAL_ESCAPE_DESCRIPTION",
    "TERMINAL_ESCAPE_KEY",
    "scan_command_content",
]
