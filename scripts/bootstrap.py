"""One-step native install for Nerva — the top of the activation funnel.

``install.sh`` / ``INSTALL.bat`` are thin wrappers around this file: they only find an
interpreter (and, for the hosted one-liner, ``git clone`` the checkout) and then hand
over here. Everything below is **stdlib-only** so it runs before a single dependency
is installed, and it must stay parseable by an *old* interpreter so the version-floor
refusal is a readable message instead of a SyntaxError.

What a run does, in order (each step is a plain function so ``tests/test_bootstrap_script.py``
can drive it with fakes — no network, no real subprocess beyond ``python -c``):

1. ``check_python``      — refuses anything below :data:`PYTHON_FLOOR` (3.12) with a
                            named reason (``python_too_old:3.11<3.12``).
2. ``ensure_venv``       — creates ``.venv`` once; idempotent on re-runs.
3. ``pip_install_locked``— ``pip install --require-hashes -r requirements-beta.lock``
                            (the hash-pinned lock, never the loose ``.txt``, unless the
                            operator passes ``--unlocked``).
4. ``detect_runtimes``   — loopback-only probes for Ollama (:11434) and LM Studio
                            (:1234); report only, nothing is started or installed.
5. ``run_install_smoke`` — ``scripts/install_smoke.py --json`` inside the venv
                            (real boot, ``/readyz``, one deterministic fake turn).
6. ``print_next_step``   — the one line that ends inside the Command Center.

Invariants (MOONSHOT §5, local-first by default):

* the bootstrap never writes a bind other than ``127.0.0.1`` — it writes **no** config
  at all, and the environment it hands to child processes pins ``JARVIS_HOST`` to
  loopback (``subprocess_env``);
* it never writes, prompts for, or echoes a cloud API key;
* every failure is a named reason on stderr and a non-zero exit — no half-installed
  state is reported as success.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess  # nosec B404 - fixed argv only, no shell; the installer runs pip and the smoke test
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PYTHON_FLOOR = (3, 12)
VENV_DIR = ".venv"
LOCK_FILE = "requirements-beta.lock"
LOOSE_REQUIREMENTS = "requirements-beta.txt"
SMOKE_SCRIPT = os.path.join("scripts", "install_smoke.py")

LOOPBACK_HOST = "127.0.0.1"
NEXT_STEP_URL = "http://127.0.0.1:8080/v2"

# Local model runtimes we look for. Loopback only — the bootstrap never probes the
# network, and a runtime on another box is a PHONE_ACCESS/LAN decision, not ours.
RUNTIME_PROBES = (
    ("ollama", "http://127.0.0.1:11434/api/tags"),
    ("lm_studio", "http://127.0.0.1:1234/v1/models"),
)

# Environment keys that must never be written or echoed by this script. They are only
# used to *scrub* the child environment for the smoke run so a stray key in the
# operator's shell cannot turn the install smoke into a cloud hop.
_CLOUD_KEY_SUFFIXES = ("_API_KEY", "_TOKEN_SECRET")
_CLOUD_KEY_NAMES = frozenset({
    "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY",
    "MISTRAL_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY",
})


class BootstrapError(RuntimeError):
    """A step failed with a *named* reason (``reason`` is machine-readable)."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason if not detail else f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


# ── 1. interpreter floor ───────────────────────────────────────────
def check_python(version_info=None) -> tuple:
    """Return ``(ok, reason)`` for the running interpreter (or *version_info*).

    The floor is :data:`PYTHON_FLOOR`; the reason names both versions so the message
    is actionable (``python_too_old:3.11<3.12``) and stable for tests.
    """
    vi = tuple(version_info or sys.version_info)[:2]
    have = f"{vi[0]}.{vi[1]}"
    want = f"{PYTHON_FLOOR[0]}.{PYTHON_FLOOR[1]}"
    if vi < PYTHON_FLOOR:
        return False, f"python_too_old:{have}<{want}"
    return True, f"python_ok:{have}"


# ── 2. venv ────────────────────────────────────────────────────────
def venv_python(root: Path) -> Path:
    """Path of the interpreter inside ``<root>/.venv`` for this OS (may not exist yet)."""
    root = Path(root)
    if os.name == "nt":
        return root / VENV_DIR / "Scripts" / "python.exe"
    return root / VENV_DIR / "bin" / "python"


def ensure_venv(root: Path, python: str = sys.executable, run=subprocess.run) -> tuple:
    """Create ``<root>/.venv`` with *python* unless it already exists.

    Returns ``(venv_python_path, created)``. Idempotent: a second call is a no-op
    that still returns the interpreter path. Raises :class:`BootstrapError`
    (``venv_create_failed``) when ``python -m venv`` exits non-zero or leaves no
    interpreter behind.
    """
    root = Path(root)
    target = venv_python(root)
    if target.exists():
        return target, False
    proc = run([python, "-m", "venv", str(root / VENV_DIR)], check=False)
    rc = getattr(proc, "returncode", 1)
    if rc != 0:
        raise BootstrapError("venv_create_failed", f"python -m venv exited {rc}")
    if not target.exists():
        raise BootstrapError("venv_create_failed", f"no interpreter at {target}")
    return target, True


# ── 3. dependencies ────────────────────────────────────────────────
def pip_install_locked(venv_py: Path, root: Path, *, unlocked: bool = False,
                       run=subprocess.run) -> list:
    """Install the beta dependency set into the venv from the hash-pinned lock.

    Returns the argv that was executed (so callers/tests can inspect it). With
    ``unlocked=True`` the loose ``requirements-beta.txt`` is used instead — the
    escape hatch for a platform whose wheel is not in the universal lock; the
    report marks it so the choice is visible, never silent.
    """
    root = Path(root)
    lock = root / LOCK_FILE
    loose = root / LOOSE_REQUIREMENTS
    if unlocked or not lock.exists():
        if not loose.exists():
            raise BootstrapError("requirements_missing", str(loose))
        argv = [str(venv_py), "-m", "pip", "install", "--quiet", "-r", str(loose)]
    else:
        argv = [str(venv_py), "-m", "pip", "install", "--quiet", "--require-hashes",
                "-r", str(lock)]
    proc = run(argv, check=False)
    rc = getattr(proc, "returncode", 1)
    if rc != 0:
        raise BootstrapError("pip_install_failed", f"pip exited {rc} ({argv[-1]})")
    return argv


# ── 4. runtimes / hardware (report only) ───────────────────────────
def detect_runtimes(opener=urllib.request.urlopen, timeout: float = 1.5,
                    probes=RUNTIME_PROBES) -> list:
    """Probe the loopback model runtimes; never raises, never starts anything.

    Each entry: ``{"name", "url", "reachable", "reason"}`` where *reason* names why a
    runtime is not reachable (``connection_refused``, ``http_status:500``,
    ``timeout``) — the doctor surfaces the same rows.
    """
    found = []
    for name, url in probes:
        row = {"name": name, "url": url, "reachable": False, "reason": ""}
        try:
            resp = opener(url, timeout=timeout)
            status = getattr(resp, "status", None) or getattr(resp, "code", 200)
            try:
                close = getattr(resp, "close", None)
                if close:
                    close()
            except Exception:  # nosec B110 - pragma: no cover; closing a probe response is best effort, a failure here says nothing about reachability
                pass
            if int(status) == 200:
                row["reachable"] = True
                row["reason"] = "ok"
            else:
                row["reason"] = f"http_status:{status}"
        except urllib.error.HTTPError as exc:
            row["reason"] = f"http_status:{exc.code}"
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
                row["reason"] = "timeout"
            else:
                row["reason"] = "connection_refused"
        except (TimeoutError, OSError):
            row["reason"] = "timeout"
        except Exception as exc:  # pragma: no cover - defensive; probes must not raise
            row["reason"] = f"probe_error:{type(exc).__name__}"
        found.append(row)
    return found


def detect_gpu(which=shutil.which, machine=platform.machine, system=platform.system) -> dict:
    """Best-effort accelerator hint for the report (no driver calls, no subprocess)."""
    if system() == "Darwin" and machine().lower() in ("arm64", "aarch64"):
        return {"kind": "apple_silicon", "reason": "ok"}
    if which("nvidia-smi"):
        return {"kind": "nvidia", "reason": "ok"}
    if which("rocm-smi") or which("rocminfo"):
        return {"kind": "amd_rocm", "reason": "ok"}
    return {"kind": "none_detected", "reason": "no_accelerator_tool_on_path"}


# ── 5. smoke ───────────────────────────────────────────────────────
def subprocess_env(base=None) -> dict:
    """Environment for child processes: loopback bind pinned, cloud keys scrubbed.

    The bootstrap never *writes* a bind; this is the only place it *sets* one, and
    it is always :data:`LOOPBACK_HOST`. Cloud keys are removed so the install smoke
    cannot become an accidental cloud hop, and so no key ever appears in our output.
    """
    env = dict(os.environ if base is None else base)
    for key in list(env):
        upper = key.upper()
        if upper in _CLOUD_KEY_NAMES or upper.endswith(_CLOUD_KEY_SUFFIXES):
            env.pop(key, None)
    env["JARVIS_HOST"] = LOOPBACK_HOST
    return env


def run_install_smoke(venv_py: Path, root: Path, *, run=subprocess.run, env=None) -> dict:
    """Run ``scripts/install_smoke.py --json`` in the venv and return its payload.

    Raises :class:`BootstrapError` with ``smoke_failed`` (non-zero exit) or
    ``smoke_output_unparseable`` (no JSON on stdout).
    """
    root = Path(root)
    argv = [str(venv_py), str(root / SMOKE_SCRIPT), "--json"]
    proc = run(argv, check=False, capture_output=True, text=True,
               env=subprocess_env(env), cwd=str(root))
    rc = getattr(proc, "returncode", 1)
    stdout = getattr(proc, "stdout", "") or ""
    if rc != 0:
        stderr = (getattr(proc, "stderr", "") or "").strip().splitlines()
        raise BootstrapError("smoke_failed", stderr[-1] if stderr else f"exit {rc}")
    start = stdout.find("{")
    if start < 0:
        raise BootstrapError("smoke_output_unparseable", "no JSON on stdout")
    try:
        payload = json.loads(stdout[start:])
    except ValueError as exc:
        raise BootstrapError("smoke_output_unparseable", str(exc)) from exc
    if not payload.get("ok"):
        raise BootstrapError("smoke_failed", "payload ok=false")
    return payload


# ── 6. next step ───────────────────────────────────────────────────
def start_command(root: Path) -> str:
    return "START.bat" if os.name == "nt" else "./start.sh"


def print_next_step(url: str = NEXT_STEP_URL, root: Path = REPO_ROOT, out=None) -> str:
    """The single line an install ends on: how to start, and where the cockpit is."""
    out = out or sys.stdout
    text = (
        "Nerva is installed.\n"
        f"  Start it:   {start_command(root)}\n"
        f"  Then open:  {url}   (the Command Center; loopback only — see docs/PHONE_ACCESS.md "
        "for a second device)\n"
        "  Check-up:   python scripts/doctor.py\n"
    )
    print(text, file=out, end="")
    return text


# ── orchestration ──────────────────────────────────────────────────
def bootstrap(root: Path, *, python: str = sys.executable, unlocked: bool = False,
              skip_smoke: bool = False, run=subprocess.run,
              opener=urllib.request.urlopen, version_info=None) -> dict:
    """Run every step and return the report dict (``ok`` False on the first failure)."""
    root = Path(root)
    report = {
        "ok": False, "root": str(root), "steps": [], "python": "", "venv": "",
        "venv_created": None, "lock": "", "runtimes": [], "gpu": {}, "smoke": {},
        "next_step_url": NEXT_STEP_URL, "reason": "",
    }

    def step(name, ok, reason):
        report["steps"].append({"step": name, "ok": bool(ok), "reason": reason})

    ok, reason = check_python(version_info)
    report["python"] = reason
    step("python", ok, reason)
    if not ok:
        report["reason"] = reason
        return report

    try:
        venv_py, created = ensure_venv(root, python=python, run=run)
        report["venv"], report["venv_created"] = str(venv_py), created
        step("venv", True, "created" if created else "reused")

        argv = pip_install_locked(venv_py, root, unlocked=unlocked, run=run)
        report["lock"] = os.path.basename(argv[-1])
        step("deps", True, "installed_from:" + report["lock"])
    except BootstrapError as exc:
        step("venv" if exc.reason.startswith("venv") else "deps", False, exc.reason)
        report["reason"] = str(exc)
        return report

    report["runtimes"] = detect_runtimes(opener=opener)
    report["gpu"] = detect_gpu()
    reachable = [r["name"] for r in report["runtimes"] if r["reachable"]]
    step("runtimes", True, "found:" + ",".join(reachable) if reachable else "no_local_runtime")

    if skip_smoke:
        step("smoke", True, "skipped")
    else:
        try:
            report["smoke"] = run_install_smoke(venv_py, root, run=run)
            step("smoke", True, "ok")
        except BootstrapError as exc:
            step("smoke", False, exc.reason)
            report["reason"] = str(exc)
            return report

    report["ok"] = True
    return report


def _print_human(report: dict, out=None) -> None:
    out = out or sys.stdout
    for row in report["steps"]:
        mark = "ok  " if row["ok"] else "FAIL"
        print(f"[{mark}] {row['step']:<9} {row['reason']}", file=out)
    for rt in report.get("runtimes", []):
        state = "reachable" if rt["reachable"] else rt["reason"]
        print(f"       runtime {rt['name']:<9} {state}", file=out)
    if not any(rt["reachable"] for rt in report.get("runtimes", [])):
        print("       no local model runtime found — install Ollama or LM Studio for "
              "local-first replies (Nerva still starts; cloud stays opt-in).", file=out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python scripts/bootstrap.py",
        description="Install Nerva natively: venv + locked deps + smoke, loopback only.",
    )
    parser.add_argument("--root", default=str(REPO_ROOT),
                        help="checkout to install into (default: this repo)")
    parser.add_argument("--unlocked", action="store_true",
                        help="install from requirements-beta.txt instead of the hash lock")
    parser.add_argument("--skip-smoke", action="store_true",
                        help="skip the install smoke (venv + deps only)")
    parser.add_argument("--json", action="store_true", help="machine-readable report")
    args = parser.parse_args(argv)

    report = bootstrap(Path(args.root), unlocked=args.unlocked, skip_smoke=args.skip_smoke)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human(report)
        if report["ok"]:
            print_next_step(root=Path(args.root))
    if not report["ok"]:
        print("bootstrap failed: " + report["reason"], file=sys.stderr)
        if report["reason"].startswith("python_too_old"):
            print(f"Install Python {PYTHON_FLOOR[0]}.{PYTHON_FLOOR[1]}+ "
                  "(https://www.python.org/downloads/) and re-run.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
