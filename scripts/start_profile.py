"""Run this checkout's hub on loopback with an existing named profile."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.core.paths import data_root, profile_name  # noqa: E402

# The chosen profile supplies provider settings and credentials through its own .env.
SYSTEM_ENV = {
    "PATH", "HOME", "USER", "LOGNAME", "USERPROFILE", "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE",
    "COMSPEC", "PATHEXT", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES",
    "PROGRAMFILES(X86)", "PROGRAMW6432", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS",
    "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "DISPLAY", "WAYLAND_DISPLAY",
    "XDG_RUNTIME_DIR",
}


def profile_environment(profile: Path) -> dict[str, str]:
    if not profile.is_absolute() or not profile.is_dir():
        raise ValueError("Choose an existing named profile directory by its absolute path.")
    parent = profile.parent
    suffix = "-profiles"
    if not os.path.normcase(parent.name).endswith(suffix) or parent.name == suffix:
        raise ValueError("Expected a named profile under <installation>-profiles.")
    base = parent.with_name(parent.name[:-len(suffix)])
    env = {key: value for key, value in os.environ.items() if key.upper() in SYSTEM_ENV}
    env.update(JARVIS_HOME=str(base), JARVIS_PROFILE=profile.name, JARVIS_HOST="127.0.0.1", PYTHONUTF8="1")
    if profile_name(env) != profile.name or data_root(env) != profile:
        raise ValueError("The selected directory is not a valid named Nerva profile.")
    return env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path, help="absolute path to <installation>-profiles/<name>")
    parser.add_argument("--check", action="store_true", help="show the selected checkout and profile, then exit")
    parser.add_argument("--safe-mode", action="store_true", help="use the hub's recovery mode")
    args = parser.parse_args(argv)
    try:
        env = profile_environment(args.profile)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Checkout: {ROOT}\nProfile:  {data_root(env)}", flush=True)
    if args.check:
        return 0
    command = [sys.executable, "-s", str(ROOT / "serve.py")]
    if args.safe_mode:
        command.append("--safe-mode")
    if os.name != "nt":
        os.chdir(ROOT)
        os.execve(sys.executable, command, env)
    # Ctrl+C goes to both Windows console processes. Let the hub finish its own shutdown.
    with subprocess.Popen(command, cwd=ROOT, env=env) as hub:
        while True:
            try:
                return hub.wait()
            except KeyboardInterrupt:
                continue


if __name__ == "__main__":
    raise SystemExit(main())
