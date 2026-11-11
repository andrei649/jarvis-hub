"""hub_update.py — restart the hub and check for an update from the HUD (G21 · H160/H173/H624).

The owner can now see, in the HUD, what code the hub runs and whether it is behind, ask
the remote for news, and restart the hub. Applying an update is deliberately **not**
offered (see "Apply" below).

* **Check** (:func:`check`, read-only, local): the version, the install kind (a git
  checkout, a container, or neither), the branch, the commit, the tracked upstream, how many
  commits the checkout is behind and ahead **as of the last fetch** — with the fetch's age,
  so a stale count is labelled stale — whether the working tree has uncommitted changes to
  tracked files, and whether this process can restart itself.
* **Fetch** (:func:`start_fetch`): one ``git fetch`` of the tracked upstream's remote, run
  in the background with a timeout; its output lines (with any ``user:password@`` in a URL
  removed) are kept as an action log the HUD polls (:func:`action`). One action at a time.
* **Restart** (:func:`restart`): the hub's own restart (``hub_restart``, installed by
  ``serve.py``: a same-pid re-exec on POSIX, the service manager's relaunch on Windows). A
  hub started another way cannot restart itself; that is said, never faked. A staged
  backup restore is applied by that restart, as it is by any start.

**Apply** — pulling and running new code is host execution and irreversible in the sense
that the code that runs next is not the code that approved it. It would need, at least: a
verified pre-update backup, a clean tree, a tracked branch, the irreversible approval tier,
and a way to tell that the new commit is one the owner trusts (a signed tag, a pinned ref).
This repository has no signature or pinned-ref check for its own code, so an apply cannot
be made safe here; :func:`check` reports ``can_apply: false`` with its reasons and the
manual steps (``docs/UPGRADE.md``).

git runs with a fixed argv (never a shell), ``GIT_TERMINAL_PROMPT=0``, no pager, its
fsmonitor and hooks turned off and the ``ext::`` transport refused for the call, a timeout,
and in the hub's own checkout, with a minimal environment (PATH, HOME, locale, proxy and CA
variables, the ssh agent socket) — never the hub's own secrets or inherited ``GIT_*``.
A log line drops a URL's userinfo (to the last ``@``) and its whole query string.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess  # nosec B404 - fixed argv, no shell, the hub checkout only
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any

logger = logging.getLogger("jarvis.hub_update")

GIT_TIMEOUT_S = 10
FETCH_TIMEOUT_S = 120
MAX_LOG_LINES = 200
MAX_LINE_CHARS = 400
MAX_ACTIONS = 8
RESTART_CONFIRM = "restart"
RESTART_DELAY_S = 0.5

_LOCK = threading.Lock()
_ACTIONS: dict[str, dict] = {}
_ORDER: deque[str] = deque()
#: Review m2: the userinfo runs to the LAST '@' before the host (a password may hold '@'),
#: and a URL's query string (where tokens travel) is dropped whole.
_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s?#]*@")
_QUERY = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^\s?#]*)\?[^\s#]*")
#: The only variables the subprocess gets from the hub's environment (never the hub's secrets).
_GIT_ENV_KEEP = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "TMPDIR", "SSH_AUTH_SOCK", "SYSTEMROOT",
                 "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "COMSPEC",
                 "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy",
                 "SSL_CERT_FILE", "SSL_CERT_DIR", "GIT_SSL_CAINFO")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_REMOTE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _git_argv(*args: str) -> list[str]:
    return ["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null",
            "-c", "core.pager=cat", "-c", "protocol.ext.allow=never", "--no-pager", *args]


def _git_env() -> dict[str, str]:
    env = {k: os.environ[k] for k in _GIT_ENV_KEEP if os.environ.get(k)}
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "", "SSH_ASKPASS": "", "LC_ALL": "C"})
    return env


def _git(*args: str, timeout: float = GIT_TIMEOUT_S) -> tuple[int, str, str]:
    try:
        done = subprocess.run(_git_argv(*args), cwd=repo_root(), capture_output=True, text=True,  # nosec B603 B607
                              timeout=timeout, env=_git_env(), check=False)
    except FileNotFoundError:
        return 127, "", "git is not installed"
    except subprocess.TimeoutExpired:
        return 124, "", "git timed out"
    except OSError as exc:
        return 126, "", type(exc).__name__
    return done.returncode, done.stdout.strip(), done.stderr.strip()


def clean_line(line: str) -> str:
    """A log line without credentials in URLs or control characters, bounded."""
    line = _QUERY.sub(r"\1?[redacted]", _USERINFO.sub(r"\1", line))
    line = _CONTROL.sub("", line)
    return line[:MAX_LINE_CHARS]


def _install_kind() -> str:
    try:
        from agents.core.host_identity import identity

        if identity().container:
            return "container"
    except Exception:  # noqa: BLE001 — an unknown host is not a container claim
        logger.debug("host identity unavailable", exc_info=True)
    return "git" if (repo_root() / ".git").exists() else "not_git"


def _fetched_age() -> float | None:
    code, out, _ = _git("rev-parse", "--git-path", "FETCH_HEAD")
    if code != 0 or not out:
        return None
    path = Path(out) if os.path.isabs(out) else repo_root() / out
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return None


def restart_mode() -> str:
    from agents.core import hub_restart

    return "self" if hub_restart.available() else "manual"


def check() -> dict:
    """What the hub runs and how it stands against its upstream — local reads only."""
    from agents import __version__

    install = _install_kind()
    body: dict[str, Any] = {"version": __version__, "install": install, "restart": restart_mode(),
                            "branch": None, "commit": None, "upstream": None, "behind": None, "ahead": None,
                            "fetched_seconds_ago": None, "dirty": None, "can_apply": False,
                            "manual_steps": "docs/UPGRADE.md"}
    reasons = ["no signature or pinned-ref check exists for this repository's own code, so applying "
               "an update from the HUD cannot be made safe; update by hand (docs/UPGRADE.md)"]
    if install == "container":
        reasons.append("a container is updated by pulling a new image, not from inside it")
    if install != "git":
        body["apply_refused"] = reasons
        return body
    code, branch, _ = _git("rev-parse", "--abbrev-ref", "HEAD")
    body["branch"] = branch if code == 0 and branch != "HEAD" else None
    code, commit, _ = _git("rev-parse", "--short=12", "HEAD")
    body["commit"] = commit if code == 0 else None
    code, status, _ = _git("status", "--porcelain", "--untracked-files=no")
    body["dirty"] = bool(status) if code == 0 else None
    code, upstream, _ = _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if code == 0 and upstream:
        body["upstream"] = upstream
        code, counts, _ = _git("rev-list", "--left-right", "--count", "HEAD...@{u}")
        parts = counts.split() if code == 0 else []
        if len(parts) == 2 and all(p.isdigit() for p in parts):
            body["ahead"], body["behind"] = int(parts[0]), int(parts[1])
        age = _fetched_age()
        body["fetched_seconds_ago"] = None if age is None else round(age)
    else:
        reasons.append("the branch tracks no upstream")
    if body["dirty"]:
        reasons.append("the working tree has uncommitted changes")
    body["apply_refused"] = reasons
    return body


# ── actions (a fetch), polled by the HUD ───────────────────────────────────────

def _new_action(kind: str) -> dict | None:
    with _LOCK:
        if any(a["status"] == "running" for a in _ACTIONS.values()):
            return None
        action_id = uuid.uuid4().hex[:16]
        record = {"id": action_id, "kind": kind, "status": "running", "started_at": time.time(),
                  "ended_at": None, "lines": [], "result": None}
        _ACTIONS[action_id] = record
        _ORDER.append(action_id)
        while len(_ORDER) > MAX_ACTIONS:
            _ACTIONS.pop(_ORDER.popleft(), None)
        return record


def _log(record: dict, line: str) -> None:
    with _LOCK:
        if len(record["lines"]) < MAX_LOG_LINES:
            record["lines"].append(clean_line(line))


def _finish(record: dict, status: str, result: dict | None = None) -> None:
    with _LOCK:
        record["status"] = status
        record["ended_at"] = time.time()
        record["result"] = result


def action(action_id: str) -> dict | None:
    with _LOCK:
        record = _ACTIONS.get(action_id)
        return None if record is None else {**record, "lines": list(record["lines"])}


def _remote_of(upstream: str | None) -> str | None:
    if not upstream or "/" not in upstream:
        return None
    remote = upstream.split("/", 1)[0]
    return remote if _REMOTE.match(remote) else None


def _run_fetch(record: dict, remote: str) -> None:
    _log(record, f"$ git fetch --prune {remote}")
    code, out, err = _git("fetch", "--prune", "--no-recurse-submodules", remote, timeout=FETCH_TIMEOUT_S)
    for line in (out + "\n" + err).splitlines():
        if line.strip():
            _log(record, line)
    if code != 0:
        _log(record, f"git fetch ended with code {code}")
        _finish(record, "failed", {"code": code})
        return
    after = check()
    _log(record, f"behind {after.get('behind')} · ahead {after.get('ahead')} · upstream {after.get('upstream')}")
    _finish(record, "ok", {k: after.get(k) for k in ("behind", "ahead", "upstream", "commit")})


def start_fetch() -> tuple[dict | None, str | None]:
    """Start a background fetch: ``(action, None)`` or ``(None, refusal reason)``."""
    if _install_kind() != "git":
        return None, "not_a_git_checkout"
    code, upstream, _ = _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    remote = _remote_of(upstream) if code == 0 else None
    if remote is None:
        return None, "no_upstream"
    record = _new_action("fetch")
    if record is None:
        return None, "action_running"
    threading.Thread(target=_run_fetch, args=(record, remote), name="hub-update-fetch", daemon=True).start()
    return action(record["id"]), None


def restart(reason: str = "owner restart from the HUD") -> tuple[dict | None, str | None]:
    """Ask the running hub to restart, shortly after the answer leaves:
    ``(action, None)`` or ``(None, "manual")`` when this process cannot restart itself."""
    from agents.core import hub_restart

    if not hub_restart.available():
        return None, "manual"
    record = _new_action("restart")
    if record is None:
        return None, "action_running"
    _log(record, "restart requested; the hub stops serving, then starts again")

    def _go() -> None:
        requested = hub_restart.request(reason)
        _finish(record, "ok" if requested else "failed", {"requested": requested})

    timer = threading.Timer(RESTART_DELAY_S, _go)
    timer.daemon = True
    timer.start()
    return action(record["id"]), None


def reset_for_tests() -> None:
    with _LOCK:
        _ACTIONS.clear()
        _ORDER.clear()


__all__ = ["RESTART_CONFIRM", "action", "check", "clean_line", "repo_root", "restart", "restart_mode",
           "start_fetch"]
