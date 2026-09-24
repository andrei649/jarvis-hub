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
readyz              advisory   no server answering ``/readyz`` at the hub's address (not
                               started, not ready, or ``hub_url_invalid``)
runtime_resolves    advisory   the route a Jarvis turn takes does not resolve to a usable
                               model (``configured_not_resident``, ``route_unselected``,
                               ``residency_unknown`` …) — read from the running hub; with
                               no ready hub it is ``skip`` (``skipped:hub_down``), never ok
config_sources      advisory   informational: which layer supplied each configuration key
                               (process environment > repo .env > data-home .env, first
                               wins) and which .env values a higher layer overrides — names
                               only, never a value (H273)
smoke               advisory   the install smoke (only with ``--smoke``; ~30s) failed
==================  =========  ==========================================================

The hub's address is the one ``nerva status`` reads (``hub_url``: ``NERVA_HUB_URL``, else
``JARVIS_HOST``/``JARVIS_PORT``, default ``http://127.0.0.1:8080``); ``readyz`` and
``runtime_resolves`` share it, so the ``readyz`` verdict vouches for the hub the credential
goes to.

``runtime_resolves`` is the strict check (Hermes ``setup.runtime_check``, ledger H242):
``runtimes`` proves something listens, this proves the configured route is runnable. It
reads the ``model`` block of ``GET /api/onboarding/command-center`` — the hub's own
``select_backend`` + residency verdict (``agents/core/routers/onboarding._model_snapshot``)
— with one credential when set: ``JARVIS_USER_TOKEN``, else ``JARVIS_ADMIN_TOKEN`` (the
route is user-guarded; the admin token is never sent when a user token will do). One GET;
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
READYZ_PATH = "/readyz"
COMMAND_CENTER_PATH = "/api/onboarding/command-center"
# Mirrors ``agents.cli.client.WILDCARD_HOSTS`` (a bind address is dialled over loopback).
WILDCARD_HOSTS = frozenset({"0.0.0.0", "::", "[::]"})  # nosec B104 — compared against, never bound

# Mirrors ``agents.core.boot_guards._LOOPBACK_HOSTS`` — kept local so the doctor stays
# stdlib-only; ``tests/test_doctor.py`` pins the two sets equal so they cannot drift.
LOOPBACK_HOSTS = frozenset({"", "127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"})

REQUIRED = ("python", "venv", "locks_in_sync", "bind_is_loopback", "data_root_writable")
ADVISORY = ("runtimes", "readyz", "runtime_resolves", "config_sources", "smoke")

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
    return f"http://{host}:{port}"


def check_readyz(opener=urllib.request.urlopen, url: str | None = None, timeout: float = 2.0,
                 *, env=None) -> Check:
    url = url or hub_url(env) + READYZ_PATH
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


def _hub_headers(env) -> dict:
    """The least-privileged local credential that opens the (user-guarded) route read:
    ``JARVIS_USER_TOKEN`` when set, else ``JARVIS_ADMIN_TOKEN`` — never both, so the
    admin token stays home whenever a user token will do. Never printed."""
    headers = {"Accept": "application/json"}
    user = (env.get("JARVIS_USER_TOKEN") or "").strip()
    admin = (env.get("JARVIS_ADMIN_TOKEN") or "").strip()
    if user:
        headers["x-user-token"] = user
    elif admin:
        headers["x-admin-token"] = admin
    return headers


def _text(value) -> str | None:
    """A non-empty string from the hub's reply, else None (a strict check reads no
    ``0``/``False``/``""`` as a name)."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def check_runtime_resolves(opener=urllib.request.urlopen, *, readyz: Check | None = None,
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
    headers = _hub_headers(env)
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
            hint = ("set JARVIS_USER_TOKEN (or JARVIS_ADMIN_TOKEN) to read the route"
                    if sent is None else
                    f"the hub refused the {sent} sent — check JARVIS_USER_TOKEN / "
                    "JARVIS_ADMIN_TOKEN")
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
# environment's keys with these prefixes or suffixes. The rest of a shell's
# environment (PATH, HOME …) is not Nerva configuration.
CONFIG_PREFIXES = ("JARVIS_", "NERVA_", "MEMORY_", "KNOWLEDGE_GRAPH_", "QDRANT_", "NEO4J_",
                   "OLLAMA_", "LMSTUDIO_", "LM_STUDIO_")
CONFIG_SUFFIXES = ("_API_KEY", "_TOKEN", "_SECRET", "_BASE_URL", "_MODEL")


def check_config_sources(root: Path, env=None) -> Check:
    """H273 — which layer supplies each configuration key, derived offline the way
    the hub loads it (``agents.core.env_provenance``): the process environment, then
    ``<root>/.env``, then ``$JARVIS_USER_HOME/.env``, the first one to set a key
    winning. Names and layers only. Informational: it is ``ok`` unless the table
    cannot be derived."""
    env = os.environ if env is None else env
    try:
        from agents.core import env_provenance
    except Exception as exc:  # a broken install must still get the rest of the report
        return _result("config_sources", False, "provenance_unavailable", type(exc).__name__)
    repo_env = Path(root) / ".env"
    home_dir = str(env.get("JARVIS_USER_HOME", "") or "").strip()
    home_env = Path(home_dir).expanduser() / ".env" if home_dir else None
    table = env_provenance.derive(repo_env, home_env, env)
    in_files = set(env_provenance.env_file_keys(repo_env))
    if home_env is not None:
        in_files |= set(env_provenance.env_file_keys(home_env))
    rows = [{"key": key, "layer": row["layer"], "shadowed": list(row["shadowed"])}
            for key, row in sorted(table.items())
            if key in in_files or key.startswith(CONFIG_PREFIXES) or key.endswith(CONFIG_SUFFIXES)]
    counts = {layer: sum(1 for row in rows if row["layer"] == layer)
              for layer in (env_provenance.PROCESS, env_provenance.REPO_ENV, env_provenance.USER_ENV)}
    reason = (f"{len(rows)} keys: {counts[env_provenance.PROCESS]} process environment, "
              f"{counts[env_provenance.REPO_ENV]} repo .env, {counts[env_provenance.USER_ENV]} data-home .env")
    overriding = sum(1 for row in rows if row["layer"] == env_provenance.PROCESS and row["shadowed"])
    if overriding:
        reason += (f"; {overriding} key{'s' if overriding != 1 else ''} set in the process environment "
                   f"override{'' if overriding != 1 else 's'} a .env value")
    # The files it read, like Hermes' `config env-path`: paths, never contents.
    detail = (f"repo .env {repo_env} ({'present' if repo_env.is_file() else 'absent'}); data-home .env "
              + (f"{home_env} ({'present' if home_env.is_file() else 'absent'})" if home_env is not None
                 else "not configured (no JARVIS_USER_HOME)"))
    return Check("config_sources", OK, reason, detail,
                 data={"sources": rows, "labels": dict(env_provenance.LABELS)})


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
    readyz = check_readyz(opener, env=env)
    checks = [
        check_python(version_info),
        check_venv(root),
        check_locks(root),
        check_bind(env),
        check_data_root(root, env),
        check_runtimes(opener),
        readyz,
        check_runtime_resolves(opener, readyz=readyz, env=env),
        check_config_sources(root, env),
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
        labels = c.data.get("labels", {}) if c.data else {}
        for row in (c.data or {}).get("sources", []):
            ignored = ", ".join(labels.get(layer, layer) for layer in row["shadowed"])
            lines.append(f"         {row['key']:<28} <- {labels.get(row['layer'], row['layer'])}"
                         + (f" (ignored: {ignored})" if ignored else ""))
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
