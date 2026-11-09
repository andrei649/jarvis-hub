"""H492 owner website refusals for URL-taking tools.

Matching and bounded shared-file parsing are adapted from pinned Hermes Agent
``tools/website_policy.py`` (Nous Research, MIT); see website_policy.LICENSE.
An enabled policy that cannot be read refuses the request instead of disappearing.
"""

from __future__ import annotations

import fnmatch
import ipaddress
import logging
import os
import re
import stat
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from agents.core import settings_db
from agents.core.paths import data_root

logger = logging.getLogger("jarvis.security.website_policy")

_DEFAULT = {"enabled": False, "domains": [], "shared_files": []}
_CACHE_SECONDS = 30.0
_MAX_DOMAINS = 256
_MAX_FILES = 16
_MAX_RULES = 1024
_MAX_FILE_BYTES = 256 * 1024
_MAX_PATH_CHARS = 1024
_RULE_CHARS = re.compile(r"^[a-z0-9*?._!\[\]-]+$")
_cache_lock = threading.Lock()
_cache: dict[str, tuple[float, bool, tuple[str, ...]]] = {}
_known_stores: set[str] = set()
_known_rows: set[str] = set()


class WebsitePolicyError(ValueError):
    """The owner's enabled policy is unavailable or malformed."""


def invalidate_cache() -> None:
    """Discard cached owner rules after a settings write or in an isolated test."""
    with _cache_lock:
        _cache.clear()


def _rule(raw: str) -> str:
    if type(raw) is not str or not raw.strip() or len(raw) > 1024:
        raise WebsitePolicyError("invalid website rule")
    text = raw.strip().lower()
    if any(ord(char) <= 32 or ord(char) == 127 or char == "\\" for char in text):
        raise WebsitePolicyError("invalid website rule")
    if "://" in text:
        try:
            parsed = urlsplit(text)
            authority = parsed.netloc
        except ValueError as exc:
            raise WebsitePolicyError("invalid website rule") from exc
        if parsed.scheme not in {"http", "https"}:
            raise WebsitePolicyError("invalid website rule")
    else:
        # A bare host is a glob: '?' belongs to the hostname, not a URL query.
        authority = text.removeprefix("//").split("/", 1)[0]
    if not authority or "@" in authority:
        raise WebsitePolicyError("invalid website rule")
    if authority.startswith("[") and ":" in authority.split("]", 1)[0]:
        close = authority.find("]")
        if close < 0:
            raise WebsitePolicyError("invalid website rule")
        host = authority[1:close]
        try:
            ipaddress.IPv6Address(host)
        except ValueError as exc:
            raise WebsitePolicyError("invalid website rule") from exc
        suffix = authority[close + 1:]
        if suffix and (not suffix.startswith(":") or not suffix[1:].isdigit()):
            raise WebsitePolicyError("invalid website rule")
        return str(ipaddress.IPv6Address(host))
    if authority.count(":") > 1:
        try:
            return str(ipaddress.IPv6Address(authority))
        except ValueError as exc:
            raise WebsitePolicyError("invalid website rule") from exc
    host = authority
    if ":" in host:
        host, separator, port = host.rpartition(":")
        if not separator or not port.isdigit() or not 1 <= int(port) <= 65535:
            raise WebsitePolicyError("invalid website rule")
    host = host.rstrip(".")
    if not host or len(host) > 253:
        raise WebsitePolicyError("invalid website rule")
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        pass
    try:
        labels = [label if any(marker in label for marker in "*?[]")
                  else label.encode("idna").decode("ascii")
                  for label in host.split(".")]
    except UnicodeError as exc:
        raise WebsitePolicyError("invalid website rule") from exc
    canonical = ".".join(labels)
    if (not canonical or len(canonical) > 253 or ".." in canonical
            or not _RULE_CHARS.fullmatch(canonical)):
        raise WebsitePolicyError("invalid website rule")
    return canonical


def configuration_problem(value: object) -> str | None:
    """Validate the JSON setting before an admin settings write persists it."""
    if type(value) is not dict or set(value) - set(_DEFAULT):
        return "website_blocklist: expected enabled, domains and shared_files"
    enabled = value.get("enabled", False)
    domains = value.get("domains", [])
    files = value.get("shared_files", [])
    if type(enabled) is not bool or type(domains) is not list or type(files) is not list:
        return "website_blocklist: enabled must be boolean and domains/shared_files must be lists"
    if len(domains) > _MAX_DOMAINS or len(files) > _MAX_FILES:
        return "website_blocklist: too many domains or shared files"
    try:
        for domain in domains:
            _rule(domain)
    except WebsitePolicyError:
        return "website_blocklist: invalid domain rule"
    for file in files:
        if (type(file) is not str or not file.strip() or len(file) > _MAX_PATH_CHARS
                or any(ord(char) < 32 or ord(char) == 127 for char in file)):
            return "website_blocklist: invalid shared file path"
    return None


def _profile_key() -> str:
    return str(settings_db.DB_PATH.absolute()) + "|" + str(data_root().resolve())


def _shared_path(value: str) -> Path:
    candidate = Path(value).expanduser()
    return candidate if candidate.is_absolute() else data_root() / candidate


def _file_rules(filename: str) -> list[str]:
    path = _shared_path(filename)
    # O_NONBLOCK and O_CLOEXEC are Unix-only; without NONBLOCK a FIFO would hang the open,
    # so on Windows (no FIFOs) the plain read-only open is the same safe choice.
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0))
    try:
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode):
            raise WebsitePolicyError("shared website list is not a regular file")
        if details.st_size > _MAX_FILE_BYTES:
            raise WebsitePolicyError("shared website list exceeds size bound")
        with os.fdopen(fd, "rb") as handle:
            fd = -1
            raw = handle.read(_MAX_FILE_BYTES + 1)
    finally:
        if fd >= 0:
            os.close(fd)
    if len(raw) > _MAX_FILE_BYTES:
        raise WebsitePolicyError("shared website list exceeds size bound")
    rules = []
    for line in raw.decode("utf-8-sig").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        rules.append(_rule(line))
        if len(rules) > _MAX_RULES:
            raise WebsitePolicyError("shared website list exceeds rule bound")
    return rules


def _owner_rules() -> tuple[bool, tuple[str, ...]]:
    # A fresh profile has no owner policy. Once this process has seen its store,
    # disappearance is unavailable; the guard never re-seeds it on a URL check.
    key = _profile_key()
    try:
        settings_db.DB_PATH.lstat()
    except FileNotFoundError as exc:
        with _cache_lock:
            if key in _known_stores:
                raise WebsitePolicyError("known settings store disappeared") from exc
        return False, ()
    now = time.monotonic()
    with _cache_lock:
        _known_stores.add(key)
        saved = _cache.get(key)
        if saved is not None and now - saved[0] < _CACHE_SECONDS:
            return saved[1], saved[2]
    found, value = settings_db.read_setting("security", "website_blocklist", readonly=True)
    with _cache_lock:
        if found:
            _known_rows.add(key)
        elif key in _known_rows:
            raise WebsitePolicyError("known website policy row disappeared")
    policy = value if found else _DEFAULT
    problem = configuration_problem(policy)
    if problem:
        raise WebsitePolicyError(problem)
    enabled = policy.get("enabled", False)
    rules: list[str] = []
    if enabled:
        rules.extend(_rule(item) for item in policy.get("domains", []))
        for filename in policy.get("shared_files", []):
            rules.extend(_file_rules(filename))
            if len(rules) > _MAX_RULES:
                raise WebsitePolicyError("website list exceeds rule bound")
    result = enabled, tuple(dict.fromkeys(rules))
    with _cache_lock:
        _cache[key] = (now, *result)
        if len(_cache) > 16:
            _cache.pop(next(iter(_cache)))
    return result


def _env_rules() -> tuple[str, ...]:
    rules = []
    for item in os.getenv("JARVIS_WEB_BLOCKED_DOMAINS", "").split(","):
        if not item.strip():
            continue
        try:
            rules.append(_rule(item.lstrip("*.") if item.startswith("*.") else item))
        except WebsitePolicyError:
            logger.warning("Ignoring unusable legacy website blocklist entry")
    return tuple(dict.fromkeys(rules))


def _host(value: str) -> str:
    try:
        parsed = urlsplit(value if "://" in value else "//" + value)
        host = parsed.hostname or ""
        try:
            return str(ipaddress.ip_address(host))
        except ValueError:
            pass
        return host.encode("idna").decode("ascii").lower().rstrip(".")
    except (ValueError, UnicodeError):
        return ""


def _matches(host: str, rule: str) -> bool:
    if any(marker in rule for marker in "*?["):
        return fnmatch.fnmatchcase(host, rule)
    return host == rule or host.endswith("." + rule)


def website_refusal(value: str | None = None) -> str | None:
    """None, ``website_blocked`` or ``website_policy_unavailable``.

    No target checks only policy readiness, for web search before a query leaves.
    The legacy environment list remains effective even when the JSON row is off.
    """
    try:
        _enabled, owner_rules = _owner_rules()
    except Exception as exc:
        logger.warning("Owner website policy unavailable (%s)", type(exc).__name__)
        return "website_policy_unavailable"
    if value is None:
        return None
    host = _host(value)
    if host and any(_matches(host, rule) for rule in (*owner_rules, *_env_rules())):
        return "website_blocked"
    return None
