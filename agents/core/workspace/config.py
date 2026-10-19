"""Runtime configuration of Nerva Workspace (spec §3).

Every value is read at call time through ``agents.core.env_config`` — the tests flip
flags with ``monkeypatch.setenv`` and an operator may change ``.env`` between restarts,
so nothing is cached. Out-of-range numbers are clamped to the documented bounds rather
than rejected: a typo must never take the workspace down.

The setup code is the one secret this module manages. When the operator does not set
``NERVA_WORKSPACE_SETUP_CODE``, a code is generated on first need and written next to
the database with mode 0600; only the file's path is ever logged, so the code never
lands in a log aggregator. ``nerva-run -m agents.core.workspace setup-code`` (PILOT_GUIDE §2)
prints it.
"""

from __future__ import annotations

import logging
import os
import secrets
import tempfile
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path

from agents.core.env_config import env_flag, env_int, env_str, is_recognized_bool, truthy
from agents.core.paths import data_path

logger = logging.getLogger("nerva.workspace.config")

ENV_ENABLED = "NERVA_WORKSPACE"
ENV_SETUP_CODE = "NERVA_WORKSPACE_SETUP_CODE"
ENV_COOKIE_SECURE = "NERVA_WORKSPACE_COOKIE_SECURE"
ENV_SSO_HEADER = "NERVA_WORKSPACE_SSO_HEADER"
ENV_SSO_KEY = "NERVA_WORKSPACE_SSO_SECRET"
ENV_MAX_UPLOAD_MB = "NERVA_WORKSPACE_MAX_UPLOAD_MB"
ENV_SESSION_IDLE_HOURS = "NERVA_WORKSPACE_SESSION_IDLE_HOURS"
ENV_SESSION_MAX_DAYS = "NERVA_WORKSPACE_SESSION_MAX_DAYS"
ENV_MAX_CONCURRENT_LLM = "NERVA_WORKSPACE_MAX_CONCURRENT_LLM"
ENV_SCHEDULER = "NERVA_WORKSPACE_SCHEDULER"

SETUP_CODE_FILE = "setup-code.txt"

#: The workspace's own directory under the data root. It is NOT ``workspace``: that name is
#: the hub's default root for the owner's file tools (``JARVIS_FILE_ROOTS``), for
#: ``JARVIS_TERMINAL_LOCAL_ROOTS`` and for the tool-result spill directory
#: (``workspace/tool_results``), so company data there would be readable by the owner's
#: personal assistant. No other hub module uses ``business``; ``data_purge.KEEP_DIRS`` keeps
#: it through the owner's "forget me" (spec §3 "Data location", BACKLOG NWS-14).
DATA_DIRNAME = "business"

_MIB = 1024 * 1024
_HOUR = 3600
_DAY = 86400

# Raw NERVA_WORKSPACE_COOKIE_SECURE spellings already warned about, so a bad value logs
# once per process instead of once per request.
_warned_cookie_values: set[str] = set()


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def enabled() -> bool:
    """Whether the workspace answers at all (off → every route is a 404)."""
    return env_flag(ENV_ENABLED, False)


def workspace_dir() -> Path:
    """``data_path(DATA_DIRNAME)`` (``<data>/business``), created with mode 0700 on demand.

    The directory holds the database, uploaded files and the setup code, so it is
    created private; an existing directory keeps whatever mode the operator chose.
    """
    path = data_path(DATA_DIRNAME)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


#: Explicit hub roots already warned about, as ``(setting, root)``: one warning each per process.
_warned_hub_roots: set[tuple[str, str]] = set()


def _relation(root: Path, data: Path) -> str | None:
    """How *root* overlaps *data*: ``is``, ``contains``, ``is inside`` — or ``None``."""
    if root == data:
        return "is"
    if data.is_relative_to(root):
        return "contains"
    if root.is_relative_to(data):
        return "is inside"
    return None


def hub_roots_without_workspace(setting: str, roots: Sequence[str]) -> list[str]:
    """*roots* without every root that is, contains or lies inside the workspace directory.

    The hub's own tools — the owner's file tools (``JARVIS_FILE_ROOTS``) and the governed
    terminal (``JARVIS_TERMINAL_LOCAL_ROOTS``) — must never reach company data, even when an
    operator sets such a root by mistake (``<data>/business`` itself, the data root that
    contains it, or a folder under it). Each root is compared by its real location
    (``~``, ``..`` and symlinks resolved); a dropped one is logged once per process, as a
    WARNING naming *setting*. Every other entry is returned unchanged and in order — blank,
    relative or unresolvable ones included, so the caller treats them exactly as before.
    Nothing is dropped while there is no company data to protect — the workspace is off and
    its directory does not exist — nor when the data root cannot be determined (the hub
    does not start then either).
    """
    try:
        data = data_path(DATA_DIRNAME).resolve()
    except (OSError, RuntimeError):
        return list(roots)
    if not (enabled() or data.exists()):
        return list(roots)
    kept: list[str] = []
    for raw in roots:
        text = str(raw or "").strip()
        try:
            root = Path(text).expanduser().resolve() if text else None
        except (OSError, RuntimeError, ValueError):
            root = None
        relation = _relation(root, data) if root is not None else None
        if relation is None:
            kept.append(raw)
            continue
        if (setting, str(root)) not in _warned_hub_roots:
            _warned_hub_roots.add((setting, str(root)))
            logger.warning(
                "%s lists %s, which %s the Nerva Workspace data directory %s: the hub's file "
                "tools and terminal never reach company data, so this root is ignored (when no "
                "other root is left, the default one is used; PILOT_GUIDE §13)",
                setting, root, relation, data)
    return kept


def setup_code_path() -> Path:
    """Where a generated setup code lives (it may not exist)."""
    return data_path(DATA_DIRNAME, SETUP_CODE_FILE)


def create_private_file(path: Path, data: bytes) -> bytes:
    """Create *path* (mode 0600) holding *data* unless it exists; return what it holds.

    The content is written to an ``O_EXCL`` temporary file first and then hard-linked
    into place, so a concurrent reader never sees a half-written file and two racing
    creators agree on one value (the loser reads the winner's). Filesystems without
    hard links fall back to a direct ``O_EXCL`` create.
    """
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(tmp_name, path)
        except FileExistsError:
            return path.read_bytes()
        except OSError:
            return _create_exclusive(path, data)
        return data
    finally:
        with suppress(FileNotFoundError):
            os.unlink(tmp_name)


def _create_exclusive(path: Path, data: bytes) -> bytes:
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path.read_bytes()
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    return data


def setup_code() -> str:
    """The first-run setup code: the env value, else the generated file's content.

    Generated on first need with ``secrets.token_urlsafe(18)``; the log line names the
    file and the CLI command, never the code.
    """
    configured = env_str(ENV_SETUP_CODE, "").strip()
    if configured:
        return configured
    path = setup_code_path()
    if path.exists():
        existing = path.read_bytes().decode("utf-8").strip()
        if existing:
            return existing
        # An empty file can only be an operator's leftover; it would lock setup out.
        path.unlink()
    workspace_dir()
    stored = create_private_file(path, secrets.token_urlsafe(18).encode("utf-8"))
    logger.warning(
        "Nerva Workspace setup code written to %s (print it with the service's environment: "
        "nerva-run -m agents.core.workspace setup-code — PILOT_GUIDE §2, §6)", path,
    )
    return stored.decode("utf-8").strip()


def clear_setup_code() -> None:
    """Delete the generated setup code once setup has succeeded (idempotent)."""
    with suppress(FileNotFoundError):
        setup_code_path().unlink()


def cookie_secure_mode() -> str:
    """``'auto'`` (Secure on https), ``'on'`` or ``'off'``; junk → auto plus one warning."""
    raw = env_str(ENV_COOKIE_SECURE, "auto").strip().lower()
    if raw in ("", "auto"):
        return "auto"
    if is_recognized_bool(raw):
        return "on" if truthy(raw) else "off"
    if raw not in _warned_cookie_values:
        _warned_cookie_values.add(raw)
        logger.warning("%s is not auto or a boolean; using auto", ENV_COOKIE_SECURE)
    return "auto"


def max_upload_bytes() -> int:
    """Largest accepted upload: 1..200 MiB, default 25."""
    return min(env_int(ENV_MAX_UPLOAD_MB, 25, minimum=1), 200) * _MIB


def session_idle_seconds() -> int:
    """Idle timeout of a session: 1..168 hours, default 12."""
    return _clamp(env_int(ENV_SESSION_IDLE_HOURS, 12, minimum=1), 1, 168) * _HOUR


def session_max_seconds() -> int:
    """Absolute lifetime of a session: 1..90 days, default 7."""
    return _clamp(env_int(ENV_SESSION_MAX_DAYS, 7, minimum=1), 1, 90) * _DAY


def max_concurrent_llm() -> int:
    """Size of the process-wide model semaphore: 1..16, default 2."""
    return _clamp(env_int(ENV_MAX_CONCURRENT_LLM, 2, minimum=1), 1, 16)


def sso_header() -> str:
    """Name of the header a trusted proxy fills with the user's email ('' = no SSO)."""
    return env_str(ENV_SSO_HEADER, "").strip()


def sso_secret() -> str:
    """Shared secret the proxy sends as ``X-Nerva-Proxy-Secret`` ('' = no SSO)."""
    return env_str(ENV_SSO_KEY, "").strip()


def sso_configured() -> bool:
    """SSO needs both the header name and the shared secret."""
    return bool(sso_header() and sso_secret())


def scheduler_enabled() -> bool:
    """Whether the in-process report/housekeeping scheduler runs (default on)."""
    return env_flag(ENV_SCHEDULER, True)
