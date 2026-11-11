"""Bounded local developer checks; no installs, live calls or release promotion.

Run with the project's Python 3.12 venv. --smoke composes the existing install
smoke (real orchestration and /readyz, synthetic local inference); --frontend
also requires Node 22 and the installed frontend tools. Output never includes
subprocess stdout/stderr or configuration values. CI/release gates stay separate.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import io
import json
import os
import re
import subprocess  # nosec B404 -- fixed local argv, no shell
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_WEBSITE_POLICY_PROBE = (
    "from agents.core.security.website_policy import website_refusal; "
    "print('WEBSITE_POLICY_READY' if website_refusal() is None else 'WEBSITE_POLICY_UNAVAILABLE')"
)


def _row(name: str, passed: bool, reason: str, action: str = "") -> dict:
    return {"name": name, "status": "pass" if passed else "fail", "reason": reason,
            "action": action if not passed else ""}


def _isolated_env(environ: dict, state: Path) -> dict:
    # Carry executable/OS plumbing only; owner tokens, provider keys and channel
    # activation settings must never enter the synthetic product process.
    env = {key: value for key, value in environ.items()
           if key in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL"}}
    env.update(JARVIS_HOME=str(state), JARVIS_TESTING="1", JARVIS_LLM_WARMUP="0",
               PYTHONDONTWRITEBYTECODE="1", NERVA_SAVE_TRAJECTORIES="0")
    return env


def _command(runner, argv: list[str], *, root: Path, env: dict, timeout: int,
             name: str, action: str, validate=None) -> dict:
    try:
        result = runner(argv, cwd=root, env=env, capture_output=True, text=True,
                        timeout=timeout, check=False)
        if result.returncode:
            return _row(name, False, "command_failed", action)
        if validate is not None and not validate(result.stdout or ""):
            return _row(name, False, "invalid_result", action)
        return _row(name, True, "passed")
    except subprocess.TimeoutExpired:
        return _row(name, False, "timeout", action)
    except (OSError, ValueError, TypeError):
        return _row(name, False, "prerequisite_unavailable", action)


def _smoke_ok(raw: str) -> bool:
    try:
        return json.loads(raw).get("ok") is True
    except (ValueError, AttributeError):
        return False


def locked_versions_match(root: Path, *, lookup=importlib.metadata.version) -> bool:
    """Compare applicable lock pins with installed metadata, without importing packages.

    This checks versions, not wheel-content attestation. The separately checked
    source hashes keep the lock files tied to their requirement sources.
    """
    try:
        from packaging.requirements import Requirement

        for name in ("requirements-beta.lock", "requirements-dev.lock"):
            for line in (root / name).read_text(encoding="utf-8").splitlines():
                if not line or line.startswith(("#", " ", "\t")):
                    continue
                requirement = Requirement(line.removesuffix("\\").strip())
                if requirement.marker is not None and not requirement.marker.evaluate():
                    continue
                pins = list(requirement.specifier)
                if len(pins) != 1 or pins[0].operator != "==" or "*" in pins[0].version:
                    return False
                if lookup(requirement.name) not in requirement.specifier:
                    return False
        return True
    except (ImportError, OSError, ValueError, importlib.metadata.PackageNotFoundError):
        return False


def run_preflight(root: Path = ROOT, *, version=None, runner=subprocess.run,
                  environ=None, smoke: bool = False, frontend: bool = False,
                  check_files: bool = True, timeout: int = 45) -> dict:
    """Run declared local checks, with unavailable/unexecuted work explicit."""
    if not 1 <= timeout <= 120:
        raise ValueError("timeout must be in 1..120 seconds")
    root = Path(root).resolve()
    version = sys.version_info if version is None else version
    environ = dict(os.environ if environ is None else environ)
    checks = [_row("python", tuple(version[:2]) == (3, 12), "requires_python_3_12",
                   "Use .venv created with Python 3.12.")]
    unexecuted = ["persisted_configuration", "full_backend", "full_frontend", "full_mobile", "release_gates",
                  "live_provider", "native_device", "upstream_hermes_runtime"]
    if not smoke:
        unexecuted.append("install_smoke")
    payload = {"ok": False, "checks": checks, "unexecuted": unexecuted,
               "source": {"head": None, "dirty": None},
               "supported_environment": {"python": "3.12", "node_if_frontend": "22",
                                         "host": sys.platform},
               "acceptance": {"live_provider": "not_run", "native_device": "not_run",
                              "upstream_hermes_runtime": "not_run", "production": "not_established"},
               "rollback": "No configuration or dependencies are changed; temporary smoke state is removed."}
    if checks[0]["status"] == "fail":
        if "install_smoke" not in unexecuted:
            unexecuted.append("install_smoke")
        return payload

    from agents.core import boot_guards
    from agents.core.env_config import truthy
    from scripts import doctor

    if check_files:
        interpreter = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        active = interpreter.is_file() and Path(sys.prefix).resolve() == (root / ".venv").resolve()
        checks.append(_row("venv", active, "project_venv_must_be_active",
                           "Run .venv's Python 3.12; install both hash-locked requirement files."))
        lock_check = doctor.check_locks(root)
        checks.append(_row("locks", lock_check.status == doctor.OK, "lock_source_hashes",
                           "Check requirements lock source hashes; do not install unlocked dependencies."))
        modules = ("fastapi", "httpx", "pytest", "xdist", "ruff")
        available = all(importlib.util.find_spec(name) is not None for name in modules)
        checks.append(_row("dependencies", available, "required_modules",
                           "Install requirements-beta.lock and requirements-dev.lock with --require-hashes."))
        checks.append(_row("installed_lock_versions", locked_versions_match(root), "applicable_lock_pins",
                           "Recreate the Python 3.12 venv from both --require-hashes lock files."))
    try:
        # Boot notices go to a private buffer, never into the JSON protocol.
        # Check the supplied process environment only, not private .env stores.
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            boot_guards.assert_parseable_posture_flags(environ)
            boot_guards.assert_front_door(environ)
        host = environ.get("JARVIS_HOST", "127.0.0.1").strip().lower()
        authenticated = bool(environ.get("JARVIS_USER_TOKEN", "").strip()
                             or environ.get("JARVIS_ADMIN_TOKEN", "").strip())
        acknowledged = truthy(environ.get("JARVIS_ALLOW_INSECURE_BIND"))
        safe_bind = host in boot_guards._LOOPBACK_HOSTS or authenticated or acknowledged
        audit_key = bool(environ.get("JARVIS_AUDIT_KEY", "").strip())
        hardened_ok = not truthy(environ.get("JARVIS_HARDENED")) or audit_key
        checks.append(_row("configuration", safe_bind and hardened_ok,
                           "process_front_door_and_hardening",
                           "Check bind/authentication, channel/posture flags and hardened audit-key presence."))
    except (SystemExit, ValueError, TypeError):
        checks.append(_row("configuration", False, "front_door_configuration_invalid",
                           "Check documented boolean flags and channel pairing/allowlists; values are withheld."))

    # This fixed, read-only guard probes the selected owner's policy, not the
    # disposable product-smoke profile. It imports no provider or orchestrator;
    # only a fixed readiness marker may leave the bounded child process.
    policy_env = {key: value for key, value in environ.items()
                  if key not in {"PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME", "PYTHONINSPECT"}}
    policy_env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1")
    policy = _command(
        runner, [sys.executable, "-c", _WEBSITE_POLICY_PROBE], root=root,
        env=policy_env, timeout=timeout, name="website_policy",
        action="Review security.website_blocklist and shared-list accessibility; values are withheld.",
        validate=lambda raw: raw.strip() == "WEBSITE_POLICY_READY",
    )
    if policy["status"] == "fail" and policy["reason"] in {"command_failed", "invalid_result"}:
        policy["reason"] = "website_policy_unavailable"
    checks.append(policy)

    if frontend and check_files:
        tools = root / "frontend" / "node_modules"
        installed = all((tools / name / "package.json").is_file()
                        for name in ("typescript", "vite", "vitest"))
        checks.append(_row("frontend_dependencies", installed, "frontend_tools_required",
                           "Run npm ci in frontend with Node 22."))

    # Only ephemeral state is writable; no current install data directory or
    # credentials are offered to CLI help or the optional synthetic turn.
    with tempfile.TemporaryDirectory(prefix=".nerva-preflight-", dir=root) as state:
        env = _isolated_env(environ, Path(state))
        checks.append(_command(runner, [sys.executable, "-m", "pip", "check"], root=root,
                               env=env, timeout=timeout, name="pip_check",
                               action="Repair the locked Python environment; raw pip output is withheld."))
        if frontend:
            checks.append(_command(runner, ["node", "--version"], root=root, env=env,
                                   timeout=timeout, name="node", action="Select Node 22 on PATH.",
                                   validate=lambda raw: re.fullmatch(r"v22\.\d+\.\d+\s*", raw) is not None))
        checks.append(_command(runner, [sys.executable, "-m", "agents.cli.nerva", "--help"],
                               root=root, env=env, timeout=timeout, name="cli",
                               action="Inspect the Nerva CLI startup; no runtime output is disclosed.",
                               validate=lambda raw: "usage:" in raw.lower() and "nerva" in raw.lower()))
        if smoke:
            checks.append(_command(runner, [sys.executable, str(root / "scripts/install_smoke.py"), "--json"],
                                   root=root, env=env, timeout=timeout, name="install_smoke",
                                   action="Inspect the isolated install smoke; no real provider was requested.",
                                   validate=_smoke_ok))

    try:
        # Metadata only; do not include changed paths, diffs or user data.
        head = runner(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                      text=True, timeout=timeout, check=False)
        if head.returncode == 0 and re.fullmatch(r"[a-f0-9]{40}\s*", head.stdout or ""):
            payload["source"]["head"] = head.stdout.strip()
        dirty = runner(["git", "status", "--porcelain", "--untracked-files=normal"],
                       cwd=root, capture_output=True, text=True, timeout=timeout, check=False)
        if dirty.returncode == 0:
            payload["source"]["dirty"] = bool(dirty.stdout)
    except (OSError, subprocess.TimeoutExpired):
        pass
    payload["ok"] = all(row["status"] == "pass" for row in checks)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true", help="Run the isolated synthetic install smoke.")
    parser.add_argument("--frontend", action="store_true", help="Require Node 22 and frontend dependencies.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--timeout", type=int, default=45, help="Per-command bound in seconds, 1..120.")
    args = parser.parse_args(argv)
    try:
        payload = run_preflight(smoke=args.smoke, frontend=args.frontend, timeout=args.timeout)
    except ValueError as exc:
        parser.error(str(exc))
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        for check in payload["checks"]:
            print(f"{check['status'].upper()} {check['name']}: {check['reason']}")
            if check["action"]:
                print(f"  {check['action']}")
        print("Unexecuted: " + ", ".join(payload["unexecuted"]))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
