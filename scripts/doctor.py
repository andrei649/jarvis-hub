"""``python scripts/doctor.py`` — the install check-up, one named reason per check.

The bootstrap (``scripts/bootstrap.py``) *makes* an install; the doctor *proves* it is
still healthy, in the same vocabulary, without changing anything on disk. It is the
first thing to run when "Nerva does not start", and the thing a bug report pastes.

Checks (``DoctorReport.checks``; each row is ``{name, status, reason, detail}``, plus
``data`` when a check has rows to show — only ``config_sources`` does):

==================  =========  ==========================================================
name                severity   what a red row means
==================  =========  ==========================================================
python              required   interpreter below the 3.12 floor (``python_too_old:3.11<3.12``)
venv                required   no ``.venv`` interpreter — run the bootstrap
locks_in_sync       required   a ``requirements*.lock`` is stale or missing for its ``.txt``
                               (same rule as ``scripts/lock_deps.sh --check``)
bind_is_loopback    required   ``JARVIS_HOST`` is set to a non-loopback address without a
                               token — ``boot_guards.assert_safe_bind`` would refuse to boot
data_root_writable  required   the runtime-data root cannot be created/written
runtimes            advisory   no local model runtime answers on loopback (reachability
                               only — a runtime that answers may not hold the model)
readyz              advisory   no server answering ``/readyz`` at the hub's address (not
                               started, not ready, or ``hub_url_invalid``)
runtime_resolves    advisory   the route a Jarvis turn takes does not resolve to a usable
                               model (``configured_not_resident``, ``route_unselected``,
                               ``residency_unknown``, and for a cloud route a key its
                               provider refused — ``cloud_auth_failed``, ``cloud_forbidden``,
                               ``cloud_unreachable`` … (H380)) — read from the running hub; with
                               no ready hub it is ``skip`` (``skipped:hub_down``), never ok
config_sources      advisory   informational: which layer supplied each configuration key
                               (process environment > repo .env > data-home .env, first
                               wins) and which .env values a higher layer overrides — names
                               only, never a value (H273). Read from the running hub when it
                               answers (asked without a credential first; the admin token
                               follows a refusal only to a hub on this machine), else
                               predicted from this shell; warns when it withholds a .env name
                               that may be value material (a mis-quoted multi-line value),
                               which it never prints
smoke               advisory   the install smoke (only with ``--smoke``; ~30s) failed
host_not_root       advisory   the hub runs as root, or elevated on Windows (H501)
sshd_no_passwords   advisory   sshd accepts passwords, by its own reading of sshd_config and
                               its Include files (absent is the sshd default, yes) (H501)
container_storage   advisory   in a container, the data root is not on a volume or bind
                               mount (H501); each host row says the fix, and is ``skip``
                               when it cannot tell, never ok
==================  =========  ==========================================================

The hub's address is the one ``nerva status`` reads (``hub_url``: ``NERVA_HUB_URL``, else
``JARVIS_HOST``/``JARVIS_PORT``, default ``http://127.0.0.1:8080``); ``readyz``,
``runtime_resolves`` and ``config_sources`` share it, and every request to it goes through
``hub_open``, which never follows a redirect and never goes through a proxy to a hub on
this machine — so what answered ``/readyz`` is what the credential reaches. The admin
credential goes only to a hub on this machine, decided by its address rather than its
spelling: ``config_sources`` sends it only after the route refused the request without it,
``runtime_resolves`` only when no user token is set (H273 second and third reviews, A1).

``runtime_resolves`` is the strict check (Hermes ``setup.runtime_check``, ledger H242):
``runtimes`` proves something listens, this proves the configured route is runnable. It
reads the ``model`` block of ``GET /api/onboarding/command-center`` — the hub's own
``select_backend`` + residency verdict (``agents/core/routers/onboarding._model_snapshot``)
— with one credential when set: ``JARVIS_USER_TOKEN``, else ``JARVIS_ADMIN_TOKEN`` to a hub
on this machine (the route is user-guarded; the admin token is never sent when a user token
will do, nor to another machine). One GET;
it starts, loads and uploads nothing. It is ``ok`` only on ``ready: true`` naming the
route, provider and model; a reply it could not read is ``hub_unreachable`` /
``malformed_reply`` / ``needs_token`` / ``command_center_status:<code>``, never a pass.

Exit status: 0 when every *required* check is ok, 1 otherwise. Advisory failures are
reported as ``warn`` and never fail the run — a doctor that reds on "server not started"
would be noise, not signal. ``--json`` prints the whole report.

Stdlib-only, like the bootstrap: the doctor must run in a broken install.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import ipaddress
import json
import os
import re
import socket
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import bootstrap  # noqa: E402

LOCK_SOURCES = ("requirements.txt", "requirements-beta.txt", "requirements-dev.txt")
LOCK_HEADER = "# source-sha256: "
READYZ_PATH = "/readyz"
COMMAND_CENTER_PATH = "/api/onboarding/command-center"
# Mirrors ``agents.cli.client.WILDCARD_HOSTS`` (a bind address is dialled over loopback).
WILDCARD_HOSTS = frozenset({"0.0.0.0", "::", "[::]"})  # nosec B104 — compared against, never bound

# Mirrors ``agents.core.boot_guards._LOOPBACK_HOSTS`` — kept local so the doctor stays
# stdlib-only; ``tests/test_doctor.py`` pins the two sets equal so they cannot drift.
LOOPBACK_HOSTS = frozenset({"", "127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"})

REQUIRED = ("python", "venv", "locks_in_sync", "bind_is_loopback", "data_root_writable")
ADVISORY = ("runtimes", "readyz", "runtime_resolves", "config_sources", "smoke",
            "host_not_root", "sshd_no_passwords", "container_storage")

OK, FAIL, WARN, SKIP = "ok", "fail", "warn", "skip"


@dataclass
class Check:
    name: str
    status: str
    reason: str
    detail: str = ""
    data: dict = field(default_factory=dict)


@dataclass
class DoctorReport:
    ok: bool
    root: str
    checks: list = field(default_factory=list)

    def by_name(self) -> dict:
        return {c.name: c for c in self.checks}

    def to_dict(self) -> dict:
        checks = []
        for c in self.checks:
            row = asdict(c)
            if not row.get("data"):
                row.pop("data", None)  # only a check with a table carries one (config_sources)
            checks.append(row)
        return {"ok": self.ok, "root": self.root, "checks": checks}


def _result(name: str, ok: bool, reason: str, detail: str = "") -> Check:
    if ok:
        return Check(name, OK, reason, detail)
    return Check(name, FAIL if name in REQUIRED else WARN, reason, detail)


# ── individual checks ──────────────────────────────────────────────
def check_python(version_info=None) -> Check:
    ok, reason = bootstrap.check_python(version_info)
    return _result("python", ok, reason)


def check_venv(root: Path) -> Check:
    target = bootstrap.venv_python(root)
    if target.exists():
        return _result("venv", True, "venv_ok", str(target))
    return _result("venv", False, "venv_missing", "run scripts/bootstrap.py")


def lock_status(root: Path, sources=LOCK_SOURCES) -> list:
    """Per-lock rows: ``(source, lock, reason)`` with reason ok/lock_missing/lock_stale."""
    rows = []
    for src_name in sources:
        src = root / src_name
        lock = root / (src_name[: -len(".txt")] + ".lock")
        if not src.exists():
            rows.append((src_name, lock.name, "source_missing"))
            continue
        if not lock.exists():
            rows.append((src_name, lock.name, "lock_missing"))
            continue
        want = hashlib.sha256(src.read_bytes()).hexdigest()
        have = ""
        with lock.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith(LOCK_HEADER):
                    have = line[len(LOCK_HEADER):].strip()
                    break
        rows.append((src_name, lock.name, "ok" if want == have else "lock_stale"))
    return rows


def check_locks(root: Path) -> Check:
    rows = lock_status(root)
    bad = [f"{reason}:{lock}" for _src, lock, reason in rows if reason != "ok"]
    if bad:
        return _result("locks_in_sync", False, bad[0], ";".join(bad))
    return _result("locks_in_sync", True, "locks_ok", ",".join(lock for _s, lock, _r in rows))


def check_bind(env=None) -> Check:
    env = os.environ if env is None else env
    host = env.get("JARVIS_HOST", "127.0.0.1").strip().lower()
    if host in LOOPBACK_HOSTS:
        return _result("bind_is_loopback", True, "loopback", host or "127.0.0.1")
    has_token = bool(env.get("JARVIS_USER_TOKEN", "").strip()
                     or env.get("JARVIS_ADMIN_TOKEN", "").strip())
    if has_token:
        return _result("bind_is_loopback", True, "non_loopback_with_token", host)
    return _result("bind_is_loopback", False, "non_loopback_without_token", host)


def resolve_data_root(root: Path, env=None) -> Path:
    """Where runtime data lives — ``agents.core.paths.data_root`` when importable, else
    the same precedence re-derived from the environment (broken-install fallback)."""
    env = os.environ if env is None else env
    try:
        from agents.core.paths import data_root
        return data_root()
    except Exception:
        override = env.get("JARVIS_HOME", "").strip() or env.get("JARVIS_MEMORY_DIR", "").strip()
        if override:
            return Path(override).expanduser()
        return Path(root) / "memory_logs"


def check_data_root(root: Path, env=None) -> Check:
    target = resolve_data_root(root, env)
    try:
        target.mkdir(parents=True, exist_ok=True)
        fd, probe = tempfile.mkstemp(prefix=".doctor-", dir=str(target))
        os.close(fd)
        os.unlink(probe)
    except OSError as exc:
        return _result("data_root_writable", False, "data_root_not_writable",
                       f"{target}: {exc.strerror or exc}")
    return _result("data_root_writable", True, "writable", str(target))


#: H501 — the host checks (agents/core/host_posture.py), under the doctor's own names.
HOST_CHECK_NAMES = {"root": "host_not_root", "sshd_passwords": "sshd_no_passwords",
                    "container_storage": "container_storage"}


def check_host_posture(root: Path, env=None, *, run=None) -> list:
    """The three read-only host checks: root, sshd passwords, container storage. A
    warning is advisory (it never fails the doctor); a check that could not tell is
    skipped with its reason, never shown as ok."""
    try:
        if run is None:
            from agents.core.host_posture import run_checks as run
        findings = run(resolve_data_root(root, env))
    except Exception as exc:
        return [Check(name, SKIP, "host_posture_unavailable", type(exc).__name__)
                for name in HOST_CHECK_NAMES.values()]
    out = []
    for finding in findings:
        name = HOST_CHECK_NAMES.get(finding.get("check"))
        if name is None:
            continue
        detail = finding.get("detail", "")
        if finding.get("status") == "ok":
            out.append(Check(name, OK, finding.get("reason", ""), detail))
        elif finding.get("status") == "warn":
            out.append(Check(name, WARN, finding.get("reason", ""),
                             f"{detail}; fix: {finding.get('fix', '')}" if detail else f"fix: {finding.get('fix', '')}"))
        else:
            out.append(Check(name, SKIP, finding.get("reason", "unknown"), detail))
    return out


def check_runtimes(opener=urllib.request.urlopen) -> Check:
    rows = bootstrap.detect_runtimes(opener=opener)
    reachable = [r["name"] for r in rows if r["reachable"]]
    detail = ";".join(f"{r['name']}={r['reason']}" for r in rows)
    if reachable:
        return _result("runtimes", True, "found:" + ",".join(reachable), detail)
    return _result("runtimes", False, "no_local_runtime", detail)


def hub_url(env=None) -> str:
    """The hub the doctor probes — the address ``nerva status`` reads, derived the same
    way (``agents.cli.client.hub_url``: ``NERVA_HUB_URL``, else ``JARVIS_HOST`` /
    ``JARVIS_PORT``). Mirrored so the doctor stays stdlib-only and import-light;
    ``tests/test_doctor.py`` pins the two equal. /readyz and the route read share it, so
    the readyz verdict vouches for the hub the credential goes to."""
    env = os.environ if env is None else env
    explicit = (env.get("NERVA_HUB_URL") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    host = (env.get("JARVIS_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    port = (env.get("JARVIS_PORT") or "8080").strip() or "8080"
    if host in WILDCARD_HOSTS:
        host = "127.0.0.1"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"  # an IPv6 literal (::1): unbracketed, the URL has no host
    return f"http://{host}:{port}"


def check_readyz(opener=None, url: str | None = None, timeout: float = 2.0,
                 *, env=None) -> Check:
    url = url or hub_url(env) + READYZ_PATH
    opener = opener or hub_open
    try:
        resp = opener(url, timeout=timeout)
        status = int(getattr(resp, "status", None) or getattr(resp, "code", 200))
        try:
            body = resp.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        close = getattr(resp, "close", None)
        if close:
            close()
    except urllib.error.HTTPError as exc:
        return _result("readyz", False, f"readyz_status:{exc.code}", "server up but not ready")
    except (ValueError, http.client.InvalidURL):
        return _result("readyz", False, "hub_url_invalid", f"{url} — check NERVA_HUB_URL")
    except (urllib.error.URLError, TimeoutError, OSError):
        return _result("readyz", False, "server_not_running", url)
    except http.client.HTTPException as exc:  # something answers, but not in HTTP
        return _result("readyz", False, "readyz_bad_reply", f"{url}: {type(exc).__name__}")
    if status != 200:
        return _result("readyz", False, f"readyz_status:{status}")
    return _result("readyz", True, "ready", body[:200])


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """A redirect is refused: returning None leaves the 3xx to urllib's default error
    handler, which raises HTTPError. A credential never follows one to another address."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _dialled_host(url: str) -> str:
    """The host urllib dials for *url*. A bare IPv6 netloc (``http://::1:8080``) has no
    ``hostname`` for ``urlsplit``, yet http.client dials it, splitting the port at the
    last colon after any ``]``; the same split is made here. It is made first for any
    unbracketed netloc with two colons or more: ``urlsplit`` reads
    ``0:0:0:0:0:0:0:1:8080`` as host ``0``, which is not what is dialled (review-H273f n1)."""
    parts = urllib.parse.urlsplit(url)
    netloc = parts.netloc.rpartition("@")[2]
    if "[" not in netloc and netloc.count(":") > 1:
        return netloc[:netloc.rfind(":")]
    if parts.hostname:
        return parts.hostname
    colon, bracket = netloc.rfind(":"), netloc.rfind("]")
    return netloc[:colon] if colon > bracket else netloc


def is_loopback_url(url: str) -> bool:
    """Whether *url* names this machine, decided by address rather than by spelling: the
    name ``localhost`` (a trailing dot too) or any loopback address, however it is written
    (``127.0.0.2``, ``127.1``, ``2130706433``, ``::1``, ``::ffff:127.0.0.1``). Each of those
    reaches this machine's listener; a list of spellings let the others through a proxy. A
    URL with no host (``file:``, ``data:``) names no machine."""
    try:
        host = _dialled_host(url)
    except ValueError:
        return False
    host = host.strip("[]").rstrip(".").lower()
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            address = ipaddress.IPv4Address(socket.inet_aton(host))   # 127.1, 2130706433 …
        except OSError:
            return False
    # An IPv4-mapped loopback (::ffff:127.0.0.1): the patched ipaddress counts it as
    # loopback, the 3.12 releases before that fix do not.
    mapped = getattr(address, "ipv4_mapped", None)
    return bool(address.is_loopback or (mapped is not None and mapped.is_loopback))


def hub_open(request, timeout: float = 10.0):
    """Open a request to the hub over http or https: never follows a redirect, and never
    goes through a proxy to a hub on this machine (an ``http_proxy`` with no ``no_proxy``
    entry would otherwise answer ``/readyz`` itself and receive the credential in clear
    text). Any other scheme (``file:``, ``data:``) is a ``ValueError``, which the checks
    name ``hub_url_invalid``; there is always a timeout."""
    url = str(getattr(request, "full_url", request))
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"the hub address is not http or https ({scheme or 'no scheme'})")
    handlers = [_RefuseRedirects()]
    if is_loopback_url(url):
        handlers.append(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(*handlers).open(request, timeout=timeout)


def _hub_headers(env, url: str = "") -> dict:
    """The least-privileged local credential that opens the (user-guarded) route read at
    *url*: ``JARVIS_USER_TOKEN`` when set, else ``JARVIS_ADMIN_TOKEN``, and that one only
    to a hub on this machine (``is_loopback_url``) — never both, so the admin token stays
    home whenever a user token will do, and never leaves this machine. Never printed."""
    headers = {"Accept": "application/json"}
    user = (env.get("JARVIS_USER_TOKEN") or "").strip()
    admin = (env.get("JARVIS_ADMIN_TOKEN") or "").strip()
    if user:
        headers["x-user-token"] = user
    elif admin and is_loopback_url(url):
        headers["x-admin-token"] = admin
    return headers


def _text(value) -> str | None:
    """A non-empty string from the hub's reply, else None (a strict check reads no
    ``0``/``False``/``""`` as a name)."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def check_runtime_resolves(opener=None, *, readyz: Check | None = None,
                           env=None, url: str | None = None,
                           timeout: float = 10.0) -> Check:
    """Does the route a Jarvis turn takes resolve to a usable model — not "does some
    runtime answer"? Ok only when the hub's verdict is ``ready: true`` AND names the
    route, provider and model it resolved; every other verdict warns with the hub's
    named reason and a detail naming route/provider/model.

    Runs only after ``readyz`` is ok: the verdict belongs to the running hub, so with no
    ready hub the check did not run and says so (``skip``), rather than passing. Any
    failure to read the verdict — a refused token, a reply cut off mid-body, a listener
    that does not speak HTTP — is a named reason too, never a traceback.
    """
    name = "runtime_resolves"
    if readyz is not None and readyz.status != OK:
        cause = {"server_not_running": "hub_down",
                 "hub_url_invalid": "hub_url_invalid"}.get(readyz.reason, "hub_not_ready")
        return Check(name, SKIP, f"skipped:{cause}",
                     "the route is resolved by the running hub — start it, then re-run")
    env = os.environ if env is None else env
    url = url or hub_url(env) + COMMAND_CENTER_PATH
    opener = opener or hub_open
    headers = _hub_headers(env, url)
    try:
        request = urllib.request.Request(url, headers=headers, method="GET")
        resp = opener(request, timeout=timeout)
        try:
            raw = resp.read()
        finally:
            close = getattr(resp, "close", None)
            if close:
                close()
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            sent = next((h for h in ("x-user-token", "x-admin-token") if h in headers), None)
            if sent is not None:
                hint = (f"the hub refused the {sent} sent — check JARVIS_USER_TOKEN / "
                        "JARVIS_ADMIN_TOKEN")
            elif (env.get("JARVIS_ADMIN_TOKEN") or "").strip():
                hint = ("the admin token is sent only to a hub on this machine: set "
                        "JARVIS_USER_TOKEN to read the route of this one")
            else:
                hint = "set JARVIS_USER_TOKEN (or JARVIS_ADMIN_TOKEN) to read the route"
            return _result(name, False, "needs_token", hint)
        return _result(name, False, f"command_center_status:{exc.code}")
    except (ValueError, http.client.InvalidURL):
        return _result(name, False, "hub_url_invalid", f"{url} — check NERVA_HUB_URL")
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
        # IncompleteRead (a hub killed mid-reply) and BadStatusLine (a listener that does
        # not speak HTTP) are HTTPException, not OSError — named here, not a traceback.
        return _result(name, False, "hub_unreachable", f"{url}: {type(exc).__name__}")
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        payload = None
    model = payload.get("model") if isinstance(payload, dict) else None
    if not isinstance(model, dict):
        return _result(name, False, "malformed_reply", "no model block in the hub's reply")

    ready = model.get("ready")
    route = _text(model.get("route"))
    provider = _text(model.get("selected_provider")) or _text(model.get("active_provider"))
    model_id = _text(model.get("selected_model")) or _text(model.get("active_model"))
    reason = _text(model.get("reason")) or "unreported"
    detail = f"route={route or 'none'} provider={provider or 'none'} model={model_id or 'none'}"
    if ready is True:
        if not (route and provider and model_id):
            # A strict check never turns green on a verdict that does not say what resolves.
            return _result(name, False, "malformed_reply", f"ready without a named route: {detail}")
        return _result(name, True, f"resolves:{provider}/{model_id}", f"{detail} ({reason})")
    rows = model.get("resident_models")
    residents = [
        f"{row.get('provider')}/{row.get('id')}"
        for row in (rows if isinstance(rows, list) else [])
        if isinstance(row, dict) and _text(row.get("provider")) and _text(row.get("id"))
    ]
    if residents:
        detail += " resident=" + ",".join(residents[:8])
    return _result(name, False, reason, detail)


# Configuration keys worth naming: every key a .env file sets, and the process
# environment's keys the hub's own code reads (found by reading agents/ and serve.py)
# or that carry Nerva's prefixes. The rest of a shell's environment (PATH, HOME, other
# tools' tokens …) is not Nerva configuration.
CONFIG_PREFIXES = ("JARVIS_", "NERVA_")
OS_NAMES = frozenset({
    "PATH", "HOME", "USER", "USERNAME", "USERPROFILE", "LOGNAME", "SHELL", "PWD", "OLDPWD", "LANG",
    "LANGUAGE", "TERM", "TZ", "TMP", "TEMP", "TMPDIR", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA",
    "SYSTEMROOT", "COMSPEC", "PATHEXT", "DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR",
    "XDG_SESSION_TYPE", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
    "DBUS_SESSION_BUS_ADDRESS", "GITHUB_STEP_SUMMARY",
})
# A read of the environment in the hub's code: through os.environ or a helper, through
# a mapping bound to it (``env.get(...)``, as GroupPolicy.from_env reads its group
# allowlist), a module constant naming a variable (``*_ENV = "..."``, private ones too, as
# proxy_trust names uvicorn's forwarding knobs and http_client its CA bundle), a pool's
# ``from_env("NAME", "NAMES")`` or a descriptor's ``*_env="NAME"`` keyword (the providers'
# keys and base URLs).
_ENV_READ = re.compile(
    r"""(?:os\.environ\.get|os\.getenv|environ\.get|\benv\.get|env_str|env_int|env_flag|env_float|env_list"""
    r"""|env_json_object|env_int_map)\(\s*["']([A-Z][A-Z0-9_]+)["']"""
    r"""|environ\[\s*["']([A-Z][A-Z0-9_]+)["']\s*\]"""
    r"""|^[ \t]*_?[A-Z][A-Z0-9_]*_ENV[ \t]*=[ \t]*["']([A-Z][A-Z0-9_]+)["']"""
    r"""|\bfrom_env\(\s*["']([A-Z][A-Z0-9_]+)["'](?:\s*,\s*["']([A-Z][A-Z0-9_]+)["'])?"""
    r"""|\b[a-z_]*_env\s*=\s*["']([A-Z][A-Z0-9_]+)["']""", re.M)
# A name from a .env file the doctor prints although nothing declares it: an identifier
# in one case, and only when python-dotenv gives it a real value. A mis-quoted
# multi-line value turns its lines into "keys": a PEM or base64 line is mixed case, and
# a base32 seed or a hex digest line is one case but its "value" is only "=" padding or
# nothing. Those are counted instead of printed.
_SHOWN_NAME = re.compile(r"(?:[A-Z_][A-Z0-9_]*|[a-z_][a-z0-9_]*)\Z")
# Every name the doctor prints is an identifier: a known prefix admits any suffix, and a
# suffix can carry terminal control characters (a title change, a screen clear).
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
# A long run of hex digits, or of base32's alphabet, with a digit in it and no underscore
# is value material, not a name: a digest, a TOTP seed, an access key id.
_VALUE_SHAPED = re.compile(r"(?=[A-Za-z0-9]*[0-9])(?:[0-9a-f]{16,}|[A-Z2-7]{16,})\Z")
ENV_SOURCES_PATH = "/api/admin/env/sources"


def names_read_in(text: str) -> set:
    """The environment names one source file reads (see ``_ENV_READ``); a pool read names
    two (``from_env("GEMINI_API_KEY", "GEMINI_API_KEYS")``)."""
    return {group for m in _ENV_READ.finditer(text) for group in m.groups() if group}


def _code_base(root: Path) -> Path:
    return Path(root) if (Path(root) / "agents").is_dir() else REPO_ROOT   # the code this doctor ships with


def hub_env_names(root: Path) -> frozenset:
    """The environment names the hub's code reads (``agents/`` and ``serve.py``),
    found by reading the source, less the operating system's own variables."""
    names: set = set()
    base = _code_base(root)
    for path in [*sorted((base / "agents").rglob("*.py")), base / "serve.py"]:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        names.update(names_read_in(text))
    return frozenset(names - OS_NAMES)


def declared_env_names(root: Path) -> frozenset:
    """The names ``.env.example`` tells the owner to set (commented out or not)."""
    try:
        text = (_code_base(root) / ".env.example").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return frozenset()
    return frozenset(re.findall(r"^#?[ \t]*([A-Z][A-Z0-9_]+)=", text, re.M))


def _home_env(environ) -> Path | None:
    """The data-home .env the hub would read for this environment (``user_home``)."""
    raw = str(environ.get("JARVIS_USER_HOME", "") or "").strip()
    if not raw:
        return None
    try:
        return Path(raw).expanduser() / ".env"
    except (RuntimeError, KeyError):   # ~nosuchuser
        return Path(raw) / ".env"


def _not_utf8(path) -> bool:
    """A regular .env file python-dotenv cannot read (it decodes UTF-8): the hub's load
    raises on it."""
    try:
        if not os.path.isfile(path):
            return False
        Path(path).read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return True
    except (OSError, ValueError, TypeError):
        return False
    return False


def _file_state(ep, path) -> str:
    if path is None:
        return "not configured (no JARVIS_USER_HOME)"
    if ep.is_fifo(path):
        return f"{path} (a named pipe: the hub reads it, the doctor does not)"
    if _not_utf8(path):
        return f"{path} (present, not UTF-8: python-dotenv cannot read it, so the hub's load fails)"
    return f"{path} ({'present' if ep.is_file_or_fifo(path) else 'absent'})"


def _read_json(opener, url: str, headers: dict, timeout: float):
    request = urllib.request.Request(url, headers=headers, method="GET")
    resp = opener(request, timeout=timeout)
    try:
        return json.loads(resp.read().decode("utf-8", "replace"))
    finally:
        close = getattr(resp, "close", None)
        if close:
            close()


def _hub_sources(env, opener, readyz, timeout: float = 5.0):
    """``(payload, "")`` with the running hub's own table, or ``(None, why)``. Asked only of
    a ready hub. The route is admin-only, but a hub in its localhost dev posture answers it
    without a credential, so it is asked without one first; the admin credential follows
    a refusal only when the hub is on this machine. Never raises."""
    if opener is None or readyz is None or readyz.status != OK:
        return None, "no running hub answered /readyz"
    url = hub_url(env) + ENV_SOURCES_PATH
    admin = (env.get("JARVIS_ADMIN_TOKEN") or "").strip()
    attempts = [{"Accept": "application/json"}]
    if admin and is_loopback_url(url):
        attempts.append({"Accept": "application/json", "x-admin-token": admin})
    why = "the running hub refused the admin route"
    for headers in attempts:
        try:
            payload = _read_json(opener, url, headers, timeout)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                why = ("the running hub refused the admin token" if "x-admin-token" in headers else
                       "the admin credential is sent only to a hub on this machine" if admin else
                       "the running hub needs the admin token (JARVIS_ADMIN_TOKEN)")
                continue
            return None, f"the running hub answered {exc.code}"
        except Exception as exc:
            return None, f"the running hub could not be read ({type(exc).__name__})"
        if not isinstance(payload, dict) or not isinstance(payload.get("sources"), list):
            return None, "the running hub's reply is not a sources table"
        return payload, ""
    return None, why


def check_config_sources(root: Path, env=None, *, opener=None, readyz: Check | None = None) -> Check:
    """H273 — which layer supplies each configuration key: the process environment,
    then ``<root>/.env``, then the data-home ``.env``, the first one to set a key
    winning. Read from the running hub when it answers with the admin credential,
    else derived offline the way the hub loads it (``agents.core.env_provenance``).
    Names and layers only. A .env name is printed when the hub reads it, it carries
    Nerva's prefix, ``.env.example`` declares it, or it is a plain one-case name with a
    real value; anything else (value material from a mis-quoted multi-line value looks
    like that) is counted, never printed. Informational: ``ok`` unless such a name turns
    up or the table cannot be had, never a crash."""
    env = os.environ if env is None else env
    try:
        return _config_sources(Path(root), env, opener, readyz)
    except Exception as exc:  # advisory: a broken install still gets the rest of the report
        return _result("config_sources", False, f"provenance_unavailable:{type(exc).__name__}")


def _config_sources(root: Path, env, opener, readyz) -> Check:
    try:
        from agents.core import env_provenance as ep
    except Exception as exc:  # a broken install must still get the rest of the report
        return _result("config_sources", False, "provenance_unavailable", type(exc).__name__)
    hub, why = _hub_sources(env, opener, readyz)
    unreadable: list = []
    values: dict | None = {}
    if hub is not None:
        table = {row["key"]: {"layer": row.get("layer"), "shadowed": _layers(row.get("shadowed"))}
                 for row in hub["sources"] if isinstance(row, dict) and isinstance(row.get("key"), str)}
        files = hub.get("files") if isinstance(hub.get("files"), dict) else {}
        where = f"read from the running hub at {hub_url(env)}"
        detail = "; ".join(f"{ep.LABELS.get(layer, layer)} {info.get('path')} ({info.get('kind') or ('present' if info.get('present') else 'absent')})"
                           for layer, info in files.items() if isinstance(info, dict))
        if is_loopback_url(hub_url(env)):
            # The hub is on this machine: its files are here, and their values tell a name
            # from value material as they do in a prediction (the repo's value wins).
            for layer in (ep.USER_ENV, ep.REPO_ENV):
                info = files.get(layer)
                path = info.get("path") if isinstance(info, dict) else None
                if isinstance(path, str) and path:
                    values.update(ep.raw_values(path))
        else:
            values = None      # another machine's files: only names Nerva knows are shown
    else:
        repo_env = root / ".env"
        table = ep.derive(repo_env, _home_env, env)
        where = f"predicted from this shell's environment ({why})"
        home = _home_env(ep.after_repo_layer(repo_env, env))
        detail = f"repo .env {_file_state(ep, repo_env)}; data-home .env {_file_state(ep, home)}"
        for path in (home, repo_env):                 # the first layer's value wins, as in the load
            if path is not None:
                values.update(ep.raw_values(path))
        unreadable = [label for label, path in (("repo_env", repo_env), ("user_env", home))
                      if path is not None and _not_utf8(path)]
        if ep.dotenv_disabled(env):
            detail += "; PYTHON_DOTENV_DISABLED is set: no .env file is loaded"
    names = hub_env_names(root)
    declared = declared_env_names(root)
    rows, withheld, unseen = [], 0, 0
    for key, row in sorted(table.items()):
        known = key in names or key in declared or (key.startswith(CONFIG_PREFIXES)
                                                     and bool(_IDENTIFIER.match(key)))
        in_file = row["layer"] in (ep.REPO_ENV, ep.USER_ENV) or bool(row["shadowed"])
        if not (in_file or known):
            continue
        if not known and values is None:
            unseen += 1
            continue
        if not known and not _plain_name(key, values.get(key)):
            withheld += 1
            continue
        item = {"key": key, "layer": row["layer"], "shadowed": list(row["shadowed"])}
        note = ep.note_for(key, row["layer"])
        if note:
            item["note"] = note
        rows.append(item)
    counts = {layer: sum(1 for row in rows if row["layer"] == layer)
              for layer in (ep.PROCESS, ep.REPO_ENV, ep.USER_ENV, ep.RUNTIME)}
    reason = (f"{len(rows)} key{'s' if len(rows) != 1 else ''}: {counts[ep.PROCESS]} process environment, "
              f"{counts[ep.REPO_ENV]} repo .env, {counts[ep.USER_ENV]} data-home .env")
    if counts[ep.RUNTIME]:
        reason += f", {counts[ep.RUNTIME]} set while running"
    if unseen:
        reason += (f"; {unseen} other .env key{'s' if unseen != 1 else ''} not shown: the hub is on "
                   f"another machine, so only names Nerva knows are shown")
    overriding = sum(1 for row in rows if row["layer"] == ep.PROCESS and row["shadowed"])
    if overriding:
        reason += (f"; {overriding} key{'s' if overriding != 1 else ''} set in the process environment "
                   f"override{'' if overriding != 1 else 's'} a .env value")
    status = OK
    if unreadable:
        status = WARN
        reason = f"env_not_utf8:{','.join(unreadable)} — the hub's load fails on it. " + reason
    if withheld:
        status = WARN
        reason = (f"withheld_env_names:{withheld} — {withheld} .env key{'s' if withheld != 1 else ''} not "
                  f"shown: not a name Nerva reads or .env.example declares, nor a plain one-case name with "
                  f"a value (an unquoted or mis-escaped multi-line value may produce such keys). " + reason)
    return Check("config_sources", status, reason, f"{where}; {detail}",
                 data={"sources": rows, "labels": dict(ep.LABELS)})


def _layers(value) -> list:
    """A hub row's ``shadowed``: a list of layer names, anything else read as none."""
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _plain_name(key: str, value) -> bool:
    """An undeclared .env key the doctor may print: a one-case identifier with a value,
    an empty one included (a placeholder for another tool). What looks like value
    material is counted instead: a key shaped like a digest or a seed (``_VALUE_SHAPED``),
    a value that is only ``=`` padding (the tail of a base32 or base64 line), and a key
    with no ``=`` at all."""
    if not (_SHOWN_NAME.match(key) and isinstance(value, str)) or _VALUE_SHAPED.match(key):
        return False
    return value == "" or value.strip("=") != ""


def check_smoke(root: Path, *, enabled: bool, run=None) -> Check:
    if not enabled:
        return Check("smoke", SKIP, "skipped", "pass --smoke to run it (~30s)")
    venv_py = bootstrap.venv_python(root)
    if not venv_py.exists():
        return _result("smoke", False, "venv_missing")
    kwargs = {"run": run} if run is not None else {}
    try:
        payload = bootstrap.run_install_smoke(venv_py, root, **kwargs)
    except bootstrap.BootstrapError as exc:
        return _result("smoke", False, exc.reason, exc.detail)
    return _result("smoke", True, "ok", f"{payload.get('agents')} agents")


# ── report ─────────────────────────────────────────────────────────
def run_doctor(root: Path = REPO_ROOT, *, env=None, opener=None,
               smoke: bool = False, run=None, version_info=None) -> DoctorReport:
    """``opener`` stands in for every request (tests); left out, the hub is reached only
    through ``hub_open`` and the local runtime probes through urllib's own opener."""
    root = Path(root)
    to_hub = opener or hub_open
    readyz = check_readyz(to_hub, env=env)
    checks = [
        check_python(version_info),
        check_venv(root),
        check_locks(root),
        check_bind(env),
        check_data_root(root, env),
        check_runtimes(opener or urllib.request.urlopen),
        readyz,
        check_runtime_resolves(to_hub, readyz=readyz, env=env),
        check_config_sources(root, env, opener=to_hub, readyz=readyz),
        check_smoke(root, enabled=smoke, run=run),
        *check_host_posture(root, env),   # H501: advisory, never a FAIL
    ]
    ok = all(c.status != FAIL for c in checks)
    return DoctorReport(ok=ok, root=str(root), checks=checks)


def format_report(report: DoctorReport) -> str:
    lines = [f"Nerva doctor — {report.root}"]
    for c in report.checks:
        mark = {OK: "ok  ", FAIL: "FAIL", WARN: "warn", SKIP: "skip"}[c.status]
        tail = f"  ({c.detail})" if c.detail else ""
        lines.append(f"[{mark}] {c.name:<19} {c.reason}{tail}")
        labels = c.data.get("labels", {}) if c.data else {}
        for row in (c.data or {}).get("sources", []):
            ignored = ", ".join(labels.get(layer, layer) for layer in row["shadowed"])
            lines.append(f"         {row['key']:<28} <- {labels.get(row['layer'], row['layer'])}"
                         + (f" (ignored: {ignored})" if ignored else "")
                         + (f" [{row['note']}]" if row.get("note") else ""))
    lines.append("verdict: " + ("healthy" if report.ok else "NOT healthy — fix the FAIL rows"))
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python scripts/doctor.py",
        description="Check a Nerva install: interpreter, venv, locks, bind, data root, "
                    "runtimes, /readyz, and whether the configured model route resolves. "
                    "Changes nothing.",
    )
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--smoke", action="store_true",
                        help="also run the install smoke in the venv (~30s)")
    parser.add_argument("--json", action="store_true", help="machine-readable report")
    args = parser.parse_args(argv)

    report = run_doctor(Path(args.root), smoke=args.smoke)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print(format_report(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
