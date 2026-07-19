#!/usr/bin/env python3
"""Build the Nerva executable (PyInstaller onedir) and smoke-test it.

    pip install pyinstaller
    python scripts/build_exe.py            # build + boot smoke test (/readyz)
    python scripts/build_exe.py --no-smoke # build only

Output: dist/nerva/ — the whole folder is the app. Ship it as-is (zip it, or
run packaging/windows/install.ps1 on Windows). On first run the executable
creates the owner's data folder at ~/Documents/Nerva (README, .env, memory/,
skills/, souls/) — all personal state lives there, never inside dist/nerva.

The smoke test boots the built binary on a throwaway port with an isolated
temp JARVIS_USER_HOME and polls /readyz — proving the bundle actually starts
(bundled assets found, imports complete), not merely that PyInstaller exited 0.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess  # noqa: S404  # nosec B404  (fixed-argv commands, never a shell)
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SPEC = REPO / "packaging" / "nerva.spec"
DIST = REPO / "dist" / "nerva"
SMOKE_PORT = 8123
SMOKE_TIMEOUT_S = 90


def build() -> None:
    # Invoke through the running interpreter so the venv that owns the app's
    # dependencies is also the one PyInstaller analyzes.
    if importlib.util.find_spec("PyInstaller") is None:
        sys.exit("PyInstaller not found in this interpreter — run: pip install pyinstaller")
    subprocess.run(  # noqa: S603  # nosec B603
        [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", str(SPEC),
         "--distpath", str(REPO / "dist"),
         "--workpath", str(REPO / "build" / "pyinstaller")],
        cwd=str(REPO), check=True,
    )
    exe = DIST / ("nerva.exe" if os.name == "nt" else "nerva")
    if not exe.exists():
        sys.exit(f"build finished but {exe} is missing")
    print(f"\nBuilt: {exe}")


def smoke() -> None:
    exe = DIST / ("nerva.exe" if os.name == "nt" else "nerva")
    with tempfile.TemporaryDirectory(prefix="nerva-smoke-") as tmp:
        env = {
            **os.environ,
            "JARVIS_PORT": str(SMOKE_PORT),
            # Isolated throwaway data home — the smoke test must not touch the
            # builder's real Documents/Nerva.
            "JARVIS_USER_HOME": str(Path(tmp) / "userhome"),
            "JARVIS_LLM_WARMUP": "0",
        }
        proc = subprocess.Popen(  # noqa: S603  # nosec B603
            [str(exe)], cwd=tmp, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        url = f"http://127.0.0.1:{SMOKE_PORT}/readyz"
        deadline = time.monotonic() + SMOKE_TIMEOUT_S
        ready = False
        try:
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    break  # crashed — report below
                try:
                    # Fixed loopback URL polled during the smoke test.
                    with urllib.request.urlopen(url, timeout=2) as resp:  # noqa: S310  # nosec B310
                        if resp.status == 200:
                            ready = True
                            break
                except OSError:
                    time.sleep(1.0)
            if not ready:
                out = ""
                if proc.poll() is not None and proc.stdout is not None:
                    out = proc.stdout.read()[-4000:]
                sys.exit(f"smoke test FAILED: {url} not ready in {SMOKE_TIMEOUT_S}s\n{out}")
            home = Path(tmp) / "userhome"
            missing = [p for p in ("README.md", ".env", "memory", "skills", "souls")
                       if not (home / p).exists()]
            if missing:
                sys.exit(f"smoke test FAILED: user home not scaffolded, missing {missing}")
            print(f"Smoke test OK — {url} ready, user home scaffolded at {home}")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-smoke", action="store_true", help="build only, skip the boot test")
    args = parser.parse_args()
    build()
    if not args.no_smoke:
        smoke()


if __name__ == "__main__":
    main()
