"""``python scripts/doctor.py`` — the install check-up, one named reason per check.

The bootstrap (``scripts/bootstrap.py``) *makes* an install; the doctor *proves* it is
still healthy, in the same vocabulary, without changing anything on disk. It is the
first thing to run when "Nerva does not start", and the thing a bug report pastes.

Checks (``DoctorReport.checks``; each row is ``{name, status, reason, detail}``):

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
readyz              advisory   no server answering ``/readyz`` on :8080 (not started, or
                               not ready)
runtime_resolves    advisory   the route a Jarvis turn takes does not resolve to a usable
                               model (``configured_not_resident``, ``route_unselected``,
                               ``residency_unknown`` …) — read from the running hub; with
                               no ready hub it is ``skip`` (``skipped:hub_down``), never ok
smoke               advisory   the install smoke (only with ``--smoke``; ~30s) failed
==================  =========  ==========================================================

``runtime_resolves`` is the strict check (Hermes ``setup.runtime_check``, ledger H242):
``runtimes`` proves something listens, this proves the configured route is runnable. It
reads the ``model`` block of ``GET /api/onboarding/command-center`` — the hub's own
``select_backend`` + residency verdict (``agents/core/routers/onboarding._model_snapshot``)
— with ``JARVIS_USER_TOKEN`` / ``JARVIS_ADMIN_TOKEN`` when set. One loopback GET; it
starts, loads and uploads nothing.

Exit status: 0 when every *required* check is ok, 1 otherwise. Advisory failures are
reported as ``warn`` and never fail the run — a doctor that reds on "server not started"
would be noise, not signal. ``--json`` prints the whole report.

Stdlib-only, like the bootstrap: the doctor must run in a broken install.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import bootstrap  # noqa: E402

LOCK_SOURCES = ("requirements.txt", "requirements-beta.txt", "requirements-dev.txt")
LOCK_HEADER = "# source-sha256: "
HUB_URL = "http://127.0.0.1:8080"
READYZ_URL = HUB_URL + "/readyz"
COMMAND_CENTER_URL = HUB_URL + "/api/onboarding/command-center"

# Mirrors ``agents.core.boot_guards._LOOPBACK_HOSTS`` — kept local so the doctor stays
# stdlib-only; ``tests/test_doctor.py`` pins the two sets equal so they cannot drift.
LOOPBACK_HOSTS = frozenset({"", "127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"})

REQUIRED = ("python", "venv", "locks_in_sync", "bind_is_loopback", "data_root_writable")
ADVISORY = ("runtimes", "readyz", "runtime_resolves", "smoke")

OK, FAIL, WARN, SKIP = "ok", "fail", "warn", "skip"


@dataclass
class Check:
    name: str
    status: str
    reason: str
    detail: str = ""


@dataclass
class DoctorReport:
    ok: bool
    root: str
    checks: list = field(default_factory=list)

    def by_name(self) -> dict:
        return {c.name: c for c in self.checks}

    def to_dict(self) -> dict:
        return {"ok": self.ok, "root": self.root, "checks": [asdict(c) for c in self.checks]}


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


def check_runtimes(opener=urllib.request.urlopen) -> Check:
    rows = bootstrap.detect_runtimes(opener=opener)
    reachable = [r["name"] for r in rows if r["reachable"]]
    detail = ";".join(f"{r['name']}={r['reason']}" for r in rows)
    if reachable:
        return _result("runtimes", True, "found:" + ",".join(reachable), detail)
    return _result("runtimes", False, "no_local_runtime", detail)


def check_readyz(opener=urllib.request.urlopen, url: str = READYZ_URL, timeout: float = 2.0) -> Check:
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
    except (urllib.error.URLError, TimeoutError, OSError):
        return _result("readyz", False, "server_not_running", url)
    if status != 200:
        return _result("readyz", False, f"readyz_status:{status}")
    return _result("readyz", True, "ready", body[:200])


def _hub_headers(env) -> dict:
    """The same local credentials ``nerva`` sends (agents/cli/client.py) — never printed."""
    headers = {"Accept": "application/json"}
    user = env.get("JARVIS_USER_TOKEN", "").strip()
    admin = env.get("JARVIS_ADMIN_TOKEN", "").strip()
    if user:
        headers["x-user-token"] = user
    if admin:
        headers["x-admin-token"] = admin
    return headers


def check_runtime_resolves(opener=urllib.request.urlopen, *, readyz: Check | None = None,
                           env=None, url: str = COMMAND_CENTER_URL,
                           timeout: float = 10.0) -> Check:
    """Does the route a Jarvis turn takes resolve to a usable model — not "does some
    runtime answer"? Ok only when the hub's verdict is ``ready: true``; every other
    verdict warns with the hub's named reason and a detail naming route/provider/model.

    Runs only after ``readyz`` is ok: the verdict belongs to the running hub, so with no
    ready hub the check did not run and says so (``skip``), rather than passing.
    """
    name = "runtime_resolves"
    if readyz is not None and readyz.status != OK:
        cause = "hub_down" if readyz.reason == "server_not_running" else "hub_not_ready"
        return Check(name, SKIP, f"skipped:{cause}",
                     "the route is resolved by the running hub — start it, then re-run")
    env = os.environ if env is None else env
    request = urllib.request.Request(url, headers=_hub_headers(env), method="GET")
    try:
        resp = opener(request, timeout=timeout)
        try:
            raw = resp.read()
        finally:
            close = getattr(resp, "close", None)
            if close:
                close()
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return _result(name, False, "needs_token",
                           "set JARVIS_USER_TOKEN (or JARVIS_ADMIN_TOKEN) to read the route")
        return _result(name, False, f"command_center_status:{exc.code}")
    except (urllib.error.URLError, TimeoutError, OSError):
        return _result(name, False, "hub_unreachable", url)
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        payload = None
    model = payload.get("model") if isinstance(payload, dict) else None
    if not isinstance(model, dict):
        return _result(name, False, "malformed_reply", "no model block in the hub's reply")

    ready = model.get("ready")
    route = model.get("route") or "none"
    provider = model.get("selected_provider") or model.get("active_provider") or "none"
    model_id = model.get("selected_model") or model.get("active_model") or "none"
    reason = str(model.get("reason") or "unreported")
    detail = f"route={route} provider={provider} model={model_id}"
    if ready is True:
        return _result(name, True, f"resolves:{provider}/{model_id}", f"{detail} ({reason})")
    residents = [
        f"{row.get('provider')}/{row.get('id')}"
        for row in (model.get("resident_models") or [])
        if isinstance(row, dict) and row.get("provider") and row.get("id")
    ]
    if residents:
        detail += " resident=" + ",".join(residents[:8])
    return _result(name, False, reason, detail)


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
def run_doctor(root: Path = REPO_ROOT, *, env=None, opener=urllib.request.urlopen,
               smoke: bool = False, run=None, version_info=None) -> DoctorReport:
    root = Path(root)
    readyz = check_readyz(opener)
    checks = [
        check_python(version_info),
        check_venv(root),
        check_locks(root),
        check_bind(env),
        check_data_root(root, env),
        check_runtimes(opener),
        readyz,
        check_runtime_resolves(opener, readyz=readyz, env=env),
        check_smoke(root, enabled=smoke, run=run),
    ]
    ok = all(c.status != FAIL for c in checks)
    return DoctorReport(ok=ok, root=str(root), checks=checks)


def format_report(report: DoctorReport) -> str:
    lines = [f"Nerva doctor — {report.root}"]
    for c in report.checks:
        mark = {OK: "ok  ", FAIL: "FAIL", WARN: "warn", SKIP: "skip"}[c.status]
        tail = f"  ({c.detail})" if c.detail else ""
        lines.append(f"[{mark}] {c.name:<19} {c.reason}{tail}")
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
