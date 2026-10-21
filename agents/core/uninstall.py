"""Provable software uninstall (roadmap theme 0.22 — the appliance install/update tail).

Mirrors the forget/export invariant (``data_purge.py``): a forget erases everything an
export can reveal about the user's *content*; this module removes everything
``install.sh``/``INSTALL.bat`` put on disk for the *software* — the venv(s), WorldView's
Node dependencies and the generated env files — while leaving the data root
(``memory_logs/`` or ``$JARVIS_HOME``) alone **by construction**. That matches the promise
``paths.py`` already documents for a packaged install ("Uninstall: delete the app install
directory; this folder is yours and is never touched by an uninstall").

``--purge-data`` is the explicit, opt-in bridge to the separately-audited, backup-first
``data_purge.purge_data`` for callers who *also* want the user's content erased — software
removal and data erasure stay two decisions, never one implicit action. It erases the
*data root* only: in a packaged install the rest of the user home (``.env`` with API keys,
``skills/``, ``souls/``) survives, and the plan and the prompt list those paths by name
(``kept_after_purge``) so nobody mistakes the purge for a full wipe.

``--dry-run`` prints :func:`plan_uninstall` — every target, whether it exists, the desktop
app paths when ``--gui``/``--gui-only`` is given, and whether (and which) data root would be
purged — and removes nothing. ``--purge-data`` is never a bare flag: interactively the data
root's folder name must be typed back; non-interactively ``--yes-purge=<absolute
data-root path>`` must name the exact root, so a script written for one machine cannot erase another
machine's data with a guessable constant. ``--yes-purge`` without ``--purge-data`` is refused.
The wrappers run this module from the *system* interpreter (so ``.venv`` is not locked while
it is removed), which normally lacks the engine's dependencies that ``data_purge`` needs; the
purge is then handed to ``.venv``'s interpreter (``--purge-only`` in a child process, before
any software is removed), and refused cleanly — exit 2, nothing touched — when no such
interpreter exists. The dry run reports which of the three applies (``purge_runnable``).
"Already running in ``.venv``" is an *environment* check (``sys.prefix``), never a resolved
executable comparison: a POSIX venv's ``bin/python`` is a symlink to the very base binary the
wrappers run. On Windows, a run from inside ``.venv`` (``nerva uninstall``) that would remove
the software is refused (exit 2, nothing touched) with a pointer to ``UNINSTALL.bat``, because
Windows locks the running venv's files; ``--dry-run`` reports this as ``venv_locked_on_windows``.
The one exception is ``UNINSTALL.bat``'s own fallback when no system Python exists: it runs
from ``.venv\\Scripts\\python.exe`` and passes ``--allow-locked-venv``, so every other target is
removed (and a purge runs in process, the venv having the dependencies) while ``.venv`` is
left untouched and reported under ``not_removed`` / ``venv_left_behind`` to delete by hand.

``--gui`` also removes the Tauri desktop shell (``desktop/src-tauri``: productName ``Jarvis
Hub``, identifier ``com.jarvis.hub``) from the per-OS places its bundles install to, plus the
shell's own per-identifier webview/cache/preference/log dirs and launcher entries — and a
source-built shell's cargo output tree (``desktop/src-tauri/target``, the binary and any
``bundle/``), which is how the desktop app is obtained today (no CI job ships a bundle).
``--gui-only`` is Hermes' ``uninstall --gui``: it removes *only* the desktop shell and leaves
the engine (venvs, WorldView) and the data alone. ``--gui-summary`` is the read-only JSON probe
(installed or not — OS install or source build —, app paths, source-built artifacts, userdata
paths, package-managed copies, ``engine_installed``, ``platform``, ``app_root``) a desktop app can
use to gate its own uninstall choice. A copy owned by a system package manager (``.deb``/``.rpm``
under ``/usr``, an MSI in Program Files) is reported with the command that removes it rather
than deleted behind the package manager's back; an NSIS install is removed by running its own
``uninstall.exe /S _?=<dir>`` (in place, so the call waits for it) so its registry entries go
too. Every desktop path is re-checked after its action: it is only reported ``removed`` once
it is gone. ``nerva uninstall`` (``agents/cli/nerva.py``) delegates here.

``UNINSTALL_TARGETS`` is the single source of truth for what counts as installer residue
— both shell wrappers (``uninstall.sh``/``UNINSTALL.bat``) and this module read the same
list, and ``tests/test_uninstall.py`` cross-checks it against ``install.sh``/``INSTALL.bat``
so a target this module claims to remove but neither installer creates anymore (or vice
versa, for a target already tracked here) cannot silently drift. That test is a *drift
guard for the targets already named here*, not proof that no new installer-created
artifact could ever escape it — same honestly-scoped boundary the no-telemetry gate
(0.22's sibling item) draws for itself.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

from agents.core import paths as _paths
from agents.core.paths import data_root, user_home

logger = logging.getLogger("jarvis.uninstall")

# Relative to the app root (repo checkout in dev, the frozen bundle dir when packaged).
# Every entry here is gitignored and created only by the installers below — never by the
# app at runtime — so removing them cannot touch anything the user typed or Nerva learned.
UNINSTALL_TARGETS: tuple[str, ...] = (
    ".venv",
    "worldview/node_modules",
    "worldview/.env",
    "worldview/backend-api/.env",
    "worldview/frontend/.env.local",
    "worldview/ingestion-workers/.env",
    "worldview/ingestion-workers/.venv",
)

# The Tauri desktop shell's identity (desktop/src-tauri/tauri.conf.json + Cargo.toml);
# tests/test_uninstall.py pins these against the config so a rename cannot drift.
DESKTOP_PRODUCT_NAME = "Jarvis Hub"
DESKTOP_IDENTIFIER = "com.jarvis.hub"
DESKTOP_BINARY = "jarvis-hub-desktop"
DESKTOP_PACKAGE = "jarvis-hub"

# Where a source build of the shell lands (desktop/README.md "Host build": `cargo run` /
# `cargo tauri build` in desktop/src-tauri). No CI job ships a bundle, so for most users
# this tree — the binary plus target/*/bundle/* — *is* the desktop app.
DESKTOP_SOURCE_TARGET = "desktop/src-tauri/target"

# Signals that the engine (not just its source) is installed under the app root.
ENGINE_MARKERS: tuple[str, ...] = (".venv", "worldview/node_modules")

# What a packaged user home holds next to the data root, which --purge-data does NOT erase.
USER_HOME_KEPT: tuple[str, ...] = (".env", "skills", "souls")

_NOT_FOUND = 127


def _kind(p: Path) -> str:
    exists = p.exists() or p.is_symlink()
    return "dir" if p.is_dir() and not p.is_symlink() else ("file" if exists else "absent")


def _ours(name: str) -> bool:
    """A launcher/icon file name that belongs to the desktop shell (AppImage integration
    names them ``appimagekit_<hash>-jarvis-hub.desktop`` / ``..._jarvis-hub.png``)."""
    n = name.lower().replace(" ", "-")
    return DESKTOP_PACKAGE in n or DESKTOP_IDENTIFIER in n


def desktop_app_targets(*, platform: str | None = None, home: Path | None = None,
                        environ: Mapping[str, str] | None = None,
                        system_root: Path | None = None,
                        app_root: Path | None = None) -> list[dict]:
    """Where the desktop shell can live on this host, and how each copy is removed.

    ``action`` is ``remove`` (deleted by this module), ``uninstaller`` (an NSIS install,
    removed by running its own ``uninstall.exe /S _?=<dir>``) or ``manual`` (owned by a
    system package manager — ``hint`` names the command). ``role`` is ``app`` (the program
    itself), ``userdata`` (the shell's per-identifier state) or ``integration`` (launcher
    entries, icons, shortcuts) or ``source_build`` (``<app_root>/desktop/src-tauri/target``,
    the cargo output tree of a source-built shell). Every argument is injectable so the
    per-OS layouts are tested on any host; *system_root* prefixes absolute system paths and
    *app_root* (default: the detected app root) locates the source build.
    """
    plat = platform or sys.platform
    env = os.environ if environ is None else environ
    h = Path(home) if home is not None else Path.home()
    sysroot = Path(system_root) if system_root is not None else Path("/")
    cands: list[tuple[Path, str, str | None, str]] = []
    if plat == "darwin":
        app = f"{DESKTOP_PRODUCT_NAME}.app"
        cands += [(sysroot / "Applications" / app, "remove", None, "app"),
                  (h / "Applications" / app, "remove", None, "app")]
        lib = h / "Library"
        cands += [(lib / sub / DESKTOP_IDENTIFIER, "remove", None, "userdata")
                  for sub in ("Application Support", "Caches", "WebKit", "HTTPStorages", "Logs")]
        cands += [(lib / "Preferences" / f"{DESKTOP_IDENTIFIER}.plist", "remove", None, "userdata"),
                  (lib / "Saved Application State" / f"{DESKTOP_IDENTIFIER}.savedState",
                   "remove", None, "userdata")]
    elif plat.startswith("win"):
        local = Path(env.get("LOCALAPPDATA") or h / "AppData" / "Local")
        roaming = Path(env.get("APPDATA") or h / "AppData" / "Roaming")
        # NSIS installs per-user under %LOCALAPPDATA% by default; an MSI (or a per-machine
        # NSIS) lands in Program Files. A dir with uninstall.exe is NSIS either way.
        bases = [(local, False)]
        if env.get("ProgramFiles"):
            bases.append((Path(env["ProgramFiles"]), True))
        for base, managed in bases:
            d = base / DESKTOP_PRODUCT_NAME
            if (d / "uninstall.exe").is_file():
                cands.append((d, "uninstaller", None, "app"))
            elif managed:
                cands.append((d, "manual",
                              f"remove '{DESKTOP_PRODUCT_NAME}' in Settings > Apps (MSI install)", "app"))
            else:
                cands.append((d, "remove", None, "app"))
        cands += [(local / DESKTOP_IDENTIFIER, "remove", None, "userdata"),
                  (roaming / DESKTOP_IDENTIFIER, "remove", None, "userdata"),
                  (roaming / "Microsoft" / "Windows" / "Start Menu" / "Programs"
                   / f"{DESKTOP_PRODUCT_NAME}.lnk", "remove", None, "integration")]
    else:
        cands.append((sysroot / "usr" / "bin" / DESKTOP_BINARY, "manual",
                      f"sudo apt remove {DESKTOP_PACKAGE}  (or: sudo dnf remove {DESKTOP_PACKAGE})", "app"))
        xdg_data = Path(env.get("XDG_DATA_HOME") or h / ".local" / "share")
        xdg_cache = Path(env.get("XDG_CACHE_HOME") or h / ".cache")
        xdg_config = Path(env.get("XDG_CONFIG_HOME") or h / ".config")
        cands += [(d / DESKTOP_IDENTIFIER, "remove", None, "userdata")
                  for d in (xdg_data, xdg_cache, xdg_config)]
        # An AppImage is wherever the user put it; these are the two conventional folders.
        for folder in (h / "Applications", h / ".local" / "bin"):
            if folder.is_dir():
                cands += [(p, "remove", None, "app") for p in sorted(folder.glob("*.AppImage"))
                          if p.name.lower().replace(" ", "-").startswith(DESKTOP_PACKAGE)]
        # AppImage desktop integration (appimaged / AppImageLauncher) writes a per-user
        # launcher and icons; a package-managed copy's live under /usr/share and are its own.
        apps_dir = xdg_data / "applications"
        if apps_dir.is_dir():
            cands += [(p, "remove", None, "integration") for p in sorted(apps_dir.glob("*.desktop"))
                      if _ours(p.name)]
        hicolor = xdg_data / "icons" / "hicolor"
        if hicolor.is_dir():
            cands += [(p, "remove", None, "integration") for p in sorted(hicolor.glob("*/apps/*"))
                      if _ours(p.name)]
    src_root = Path(app_root) if app_root is not None else _paths.app_root()
    cands.append((src_root / DESKTOP_SOURCE_TARGET, "remove", None, "source_build"))
    rows = []
    for p, action, hint, role in cands:
        kind = _kind(p)
        row = {"path": str(p), "exists": kind != "absent", "kind": kind, "action": action, "role": role}
        if hint:
            row["hint"] = hint
        rows.append(row)
    return rows


def source_built_artifacts(app_root: Path | None = None, *, platform: str | None = None) -> list[str]:
    """The runnable shell a source build produced: ``target/<profile>/jarvis-hub-desktop``
    (``.exe`` on Windows) and any ``target/<profile>/bundle`` (also under a
    ``target/<triple>/<profile>`` cross build). An empty ``target/`` (an aborted ``cargo
    check``) has none — it is still listed by :func:`desktop_app_targets` for cleanup."""
    root = Path(app_root) if app_root is not None else _paths.app_root()
    target = root / DESKTOP_SOURCE_TARGET
    if not target.is_dir():
        return []
    exe = DESKTOP_BINARY + (".exe" if (platform or sys.platform).startswith("win") else "")
    found: list[Path] = []
    for pattern in ("*", "*/*"):  # <profile>/... and <triple>/<profile>/...
        for profile in sorted(target.glob(pattern)):
            if not profile.is_dir():
                continue
            if (profile / exe).is_file():
                found.append(profile / exe)
            if (profile / "bundle").is_dir():
                found.append(profile / "bundle")
    return [str(p) for p in found]


def gui_summary(**desktop) -> dict:
    """Read-only probe of the desktop shell (Hermes' ``--gui-summary``): is it installed
    (an OS install *or* a source build), where, what userdata it left, which copies a
    package manager owns — and whether the engine is installed too, so the desktop app can
    offer "remove the app only" vs "remove everything" from this probe alone."""
    root = Path(desktop["app_root"]) if desktop.get("app_root") is not None else _paths.app_root()
    desktop = {**desktop, "app_root": root}
    plat = desktop.get("platform") or sys.platform
    rows = [r for r in desktop_app_targets(**desktop) if r["exists"]]
    app = [r["path"] for r in rows if r["role"] == "app"]
    built = source_built_artifacts(root, platform=plat)
    return {
        "installed": bool(app) or bool(built),
        "engine_installed": any(_kind(root / rel) != "absent" for rel in ENGINE_MARKERS),
        "platform": plat,
        "app_root": str(root),
        "app_paths": app,
        "source_built_paths": built,
        "userdata_paths": [r["path"] for r in rows if r["role"] == "userdata"],
        "integration_paths": [r["path"] for r in rows if r["role"] == "integration"],
        "manual": [{"path": r["path"], "hint": r.get("hint", "")} for r in rows
                   if r["action"] == "manual"],
    }


def kept_after_purge(environ: Mapping[str, str] | None = None) -> list[str]:
    """User-home entries (packaged installs) that ``--purge-data`` leaves on disk."""
    home = user_home(environ)
    if home is None:
        return []
    return [str(home / name) for name in USER_HOME_KEPT if (home / name).exists()]


def _purge_import_error() -> str | None:
    """Why ``data_purge`` cannot be imported by *this* interpreter (``None`` when it can).

    The wrappers run the module from the system interpreter so ``.venv`` is not locked while
    it is removed, but the installers put the engine's dependencies (``httpx`` for the
    ingestion chain, ``cryptography`` for the backup's secret store) into ``.venv`` only.
    """
    try:
        import agents.core.data_purge  # noqa: F401
    except ImportError as e:
        return f"{type(e).__name__}: {e}"
    return None


def venv_python(base: Path) -> Path | None:
    """The app's own ``.venv`` interpreter under *base*, when one exists."""
    for rel in (".venv/bin/python", ".venv/Scripts/python.exe"):
        p = base / rel
        if p.is_file():
            return p
    return None


def _platform() -> str:
    return sys.platform


def _running_in_venv(base: Path) -> bool:
    """Is THIS process running inside *base*'s ``.venv`` environment?

    An environment check, not a binary check: ``python3 -m venv`` makes ``.venv/bin/python`` a
    symlink to the base interpreter, so the resolved executables of the system ``python3`` and
    of the venv are the same file — yet ``pyvenv.cfg`` gives the venv its own ``sys.prefix``
    and site-packages (where the engine's dependencies live).
    """
    if sys.prefix == sys.base_prefix:
        return False
    try:
        return Path(sys.prefix).resolve() == (Path(base) / ".venv").resolve()
    except (OSError, RuntimeError):
        return False


WINDOWS_VENV_LOCK_HINT = (
    "on Windows this process runs from the .venv it would delete, and Windows locks a running "
    "interpreter's files; run UNINSTALL.bat instead - with a system Python on PATH (py -3 or "
    "python) it removes .venv too; without one it removes everything else and leaves .venv "
    "for you to delete by hand")

VENV_LEFT_BEHIND_HINT = (
    ".venv was left in place: this run uses .venv's own interpreter (no system Python was "
    "found) and Windows locks a running interpreter's files; delete the .venv folder by hand "
    "after this window closes")


def purge_runnable(base: Path) -> dict:
    """Can a ``--purge-data`` run actually erase the data root from here?

    ``in_process``: this interpreter imports ``data_purge``. Otherwise ``handoff`` names the
    ``.venv`` interpreter the purge is delegated to (``--purge-only`` in a child process, run
    before any software is removed); with neither, the purge is refused before anything is
    touched. The dry run reports this so it never promises a purge the real run cannot do.
    """
    err = _purge_import_error()
    if err is None:
        return {"runnable": True, "in_process": True, "handoff": None, "reason": None}
    vpy = venv_python(base)
    if vpy is not None and not _running_in_venv(base):
        return {"runnable": True, "in_process": False, "handoff": str(vpy), "reason": err}
    # ``venv_python`` tells the refusal apart: None = no .venv interpreter at all; a path =
    # it exists but is the environment already running (and it lacks the dependencies).
    return {"runnable": False, "in_process": False, "handoff": None, "reason": err,
            "venv_python": str(vpy) if vpy is not None else None}


def _run_purge_handoff(vpy: Path, data: Path, no_backup: bool) -> tuple[int, str, dict | None]:
    """Run ``--purge-only`` under the ``.venv`` interpreter *vpy*; return (rc, output, report).

    The typed confirmation already passed in this process, so the child gets the data root's
    absolute path as ``--yes-purge`` — and re-resolves the root itself, so a child that sees a
    different root refuses instead of erasing it. The child exits before any target is
    removed, so on Windows the venv interpreter is not locked during the removal.
    """
    import subprocess  # nosec B404 - fixed argv: the app's own .venv interpreter and this module

    code_root = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(code_root)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    argv = [str(vpy), "-m", "agents.core.uninstall", "--confirm", "--purge-data",
            "--purge-only", f"--yes-purge={data}"]
    if no_backup:
        argv.append("--no-backup")
    try:
        res = subprocess.run(argv, cwd=str(code_root), env=env, capture_output=True,  # nosec B603
                             text=True, check=False)
    except OSError as e:
        return _NOT_FOUND, f"could not start {vpy}: {e}", None
    output = (res.stdout or "") + (res.stderr or "")
    if res.returncode != 0:
        return res.returncode, output.strip(), None
    try:
        report = json.loads(res.stdout)
    except ValueError:
        return 1, f"unreadable purge report: {output.strip()}", None
    if not isinstance(report, dict) or "data_purge" not in report:
        return 1, f"unexpected purge report: {output.strip()}", None
    return 0, output.strip(), report


def plan_uninstall(root: Path | None = None, *, purge_data: bool = False, gui: bool = False,
                   gui_only: bool = False,
                   data_source_root: str | None = None, desktop: dict | None = None) -> dict:
    """Report which installer-created targets exist under *root* (default: app_root()).

    Read-only — this is what ``--dry-run`` prints. ``purge_data`` reports whether (and
    which) data root a real run would erase, and what in the user home survives it; a data
    root that cannot be resolved (a refused ``$JARVIS_PROFILE``) is reported as
    ``data_root_error`` instead of raising. ``gui`` adds the desktop app's paths;
    ``gui_only`` lists *only* those (*desktop* forwards :func:`desktop_app_targets`'
    injectable arguments).
    """
    base = Path(root) if root is not None else _paths.app_root()
    plan: dict = {"root": str(base)}
    if gui_only:
        plan["gui_only"] = True
    else:
        targets = []
        for rel in UNINSTALL_TARGETS:
            kind = _kind(base / rel)
            targets.append({"path": rel, "exists": kind != "absent", "kind": kind})
        plan["targets"] = targets
    plan["purge_data"] = bool(purge_data)
    if purge_data:
        try:
            plan["data_root"] = str(Path(data_source_root) if data_source_root else data_root())
        except RuntimeError as e:
            plan["data_root_error"] = str(e)
        plan["kept_after_purge"] = kept_after_purge()
        plan["purge_runnable"] = purge_runnable(base)
    if gui or gui_only:
        plan["desktop"] = desktop_app_targets(**{"app_root": base, **(desktop or {})})
    return plan


def _default_runner(argv: list[str], *, windows: bool | None = None) -> int:
    """Run *argv*, wait for it and return its exit code (127 when the program is missing).

    NSIS honours its in-place switch only when ``_?=<dir>`` is the last token and is
    *not* quoted — even when ``<dir>`` contains a space — so on Windows the command line is
    built by hand for that one token instead of letting ``list2cmdline`` quote it.
    """
    import subprocess  # nosec B404 - fixed argv: a found uninstall.exe or update-desktop-database, never a shell

    win = sys.platform.startswith("win") if windows is None else windows
    cmd: list[str] | str = argv
    if win and argv and argv[-1].startswith("_?="):
        cmd = subprocess.list2cmdline(argv[:-1]) + " " + argv[-1]
    try:
        return subprocess.run(cmd, check=False, timeout=600).returncode  # nosec B603 - see above
    except (OSError, subprocess.SubprocessError):
        logger.warning("uninstall: could not run %s", argv[0] if argv else argv, exc_info=True)
        return _NOT_FOUND


def _gone(p: Path) -> bool:
    return not (p.exists() or p.is_symlink())


def _remove_desktop(rows: list[dict], runner: Callable[[list[str]], int] | None) -> dict:
    removed: list[str] = []
    manual: list[dict] = []
    not_removed: list[str] = []
    run = runner or _default_runner
    launcher_dirs: set[str] = set()
    for row in rows:
        if not row["exists"]:
            continue
        p = Path(row["path"])
        if row["action"] == "manual":
            manual.append({"path": row["path"], "hint": row.get("hint", "")})
            continue
        try:
            if row["action"] == "uninstaller":
                # `_?=<dir>`: run in place and wait (without it NSIS copies itself to %TEMP%,
                # relaunches and exits 0 at once). In-place mode leaves uninstall.exe and the
                # dir behind by design, so they are removed after a successful run.
                if run([str(p / "uninstall.exe"), "/S", f"_?={p}"]) != 0:
                    not_removed.append(row["path"])
                    continue
                if not _gone(p):
                    shutil.rmtree(p)
            elif p.is_symlink() or p.is_file():
                p.unlink()
            else:
                shutil.rmtree(p)
        except (OSError, ValueError):
            logger.warning("uninstall: could not remove desktop path %s", p, exc_info=True)
        # An exit code or a silent call is not proof — the path itself must be gone.
        if _gone(p):
            removed.append(row["path"])
            if p.suffix == ".desktop":
                launcher_dirs.add(str(p.parent))
        else:
            not_removed.append(row["path"])
    report: dict = {"removed": removed, "manual": manual, "not_removed": not_removed}
    if launcher_dirs:
        # Refresh the application-menu cache; best-effort, never a reason for ok=False.
        codes = [run(["update-desktop-database", d]) for d in sorted(launcher_dirs)]
        if all(c == 0 for c in codes):
            report["menu_cache"] = "refreshed"
        elif all(c == _NOT_FOUND for c in codes):
            report["menu_cache"] = "skipped: update-desktop-database not found"
        else:
            report["menu_cache"] = "failed"
    return report


def run_uninstall(root: Path | None = None, *, purge_data: bool = False,
                  data_backup_first: bool = True,
                  data_source_root: str | None = None, gui: bool = False,
                  gui_only: bool = False,
                  desktop: dict | None = None,
                  runner: Callable[[list[str]], int] | None = None,
                  keep_venv: bool = False) -> dict:
    """Remove every existing entry in :data:`UNINSTALL_TARGETS` under *root*.

    Best-effort per target, like ``data_purge.purge_data``: a target that exists but
    cannot be removed is reported under ``not_removed`` rather than silently skipped, and
    ``ok`` goes ``False`` so a caller can't mistake a partial removal for a clean one. A
    data purge that reports ``ok: False`` (something it could not erase) counts the same
    way: ``data_purge`` lands in ``not_removed``.

    Never touches the data root. Pass ``purge_data=True`` to *also* erase it via
    ``data_purge.purge_data`` (backup-first by default) — a separate, explicit decision.
    Pass ``gui=True`` to also remove the desktop app (:func:`desktop_app_targets`; *runner*
    runs an NSIS ``uninstall.exe`` and ``update-desktop-database`` and is faked in tests);
    package-managed copies come back under ``desktop.manual`` with their removal command and
    do not make ``ok`` false. ``gui_only=True`` removes the desktop app and nothing else
    (it cannot be combined with ``purge_data``). ``keep_venv=True`` (Windows, running from
    ``.venv`` itself) never touches ``.venv`` — a recursive delete of a locked venv would
    leave it half-gone — and reports it under ``not_removed`` with ``venv_left_behind``.

    The data purge, when requested, runs **before** any target is removed. Two reasons:
    a failed purge (``PurgeError`` — e.g. its own pre-forget backup won't verify) must
    leave the software install intact so the caller can retry, rather than aborting
    halfway with the venv already gone; and when this runs from ``.venv/bin/python``
    (as ``uninstall.sh`` may, if no system interpreter is available), ``data_purge``'s own
    imports need the venv's dependencies (e.g. ``cryptography`` for the backup) to still
    be on disk — ``.venv`` is one of the targets this function removes.
    """
    if gui_only and purge_data:
        raise ValueError("gui_only removes only the desktop app; it cannot purge data")
    base = Path(root) if root is not None else _paths.app_root()
    report: dict = {"root": str(base)}
    not_removed: list[str] = []

    if gui_only:
        report["gui_only"] = True
    else:
        if purge_data:
            from agents.core.data_purge import purge_data as _purge_data
            report["data_purge"] = _purge_data(
                source_root=data_source_root, backup_first=data_backup_first, memory=True,
            )
            if report["data_purge"].get("ok") is False:
                not_removed.append("data_purge")

        removed: list[str] = []
        already_absent: list[str] = []

        for rel in UNINSTALL_TARGETS:
            p = base / rel
            if not (p.exists() or p.is_symlink()):
                already_absent.append(rel)
                continue
            if keep_venv and rel == ".venv":
                not_removed.append(rel)
                report["venv_left_behind"] = VENV_LEFT_BEHIND_HINT
                continue
            try:
                if p.is_symlink() or p.is_file():
                    p.unlink()
                elif p.is_dir():
                    shutil.rmtree(p)
                else:  # pragma: no cover - neither file, dir nor symlink is not reachable in practice
                    not_removed.append(rel)
                    continue
                removed.append(rel)
            except OSError:
                logger.warning("uninstall: could not remove %s", rel, exc_info=True)
                not_removed.append(rel)

        report.update({
            "removed": removed,
            "already_absent": already_absent,
        })
    if gui or gui_only:
        report["desktop"] = _remove_desktop(
            desktop_app_targets(**{"app_root": base, **(desktop or {})}), runner)
        not_removed = not_removed + report["desktop"]["not_removed"]
    report["ok"] = not not_removed
    if not_removed:
        report["not_removed"] = not_removed
    return report


# ── CLI ───────────────────────────────────────────────────────────
def _same_path(a: str, b: Path) -> bool:
    """*a* names *b* — and *a* is absolute. A relative value (``memory_logs``,
    ``./memory_logs``) would resolve against the wrappers' working directory, the repo root,
    and so match the default data root on every machine: a constant, not a confirmation."""
    try:
        p = Path(a).expanduser()
        if not p.is_absolute():
            return False
        return p.resolve() == b.resolve()
    except (OSError, RuntimeError, ValueError):
        return False


def _confirm_purge(args, out, inp) -> bool:
    """The typed confirmation --purge-data needs.

    Interactively: the data root's folder name, typed back. Non-interactively:
    ``--yes-purge=<the data root's absolute path>`` — the folder name alone (``memory`` /
    ``memory_logs``), or any relative path, is the same on every machine, so it would be a
    second bare flag.
    """
    try:
        root = data_root()
    except RuntimeError as e:
        out.write(f"refusing to purge: the data root cannot be resolved ({e})\n")
        return False
    expected = root.name
    kept = kept_after_purge()
    if args.yes_purge is not None:
        if _same_path(args.yes_purge, root):
            return True
        out.write(f"refusing to purge: --yes-purge={args.yes_purge!r} is not the data root's "
                  f"absolute path ({root}); a relative path or bare folder name is refused\n")
        return False
    isatty = getattr(inp, "isatty", None)
    if not (callable(isatty) and isatty()):
        out.write(f"refusing to purge without a typed confirmation: re-run with "
                  f"--yes-purge={root} (the data root's absolute path)\n")
        return False
    out.write(f"--purge-data ERASES your data at {root} (irreversible).\n")
    if kept:
        out.write("These are NOT erased and stay on disk (delete them yourself for a full wipe): "
                  + ", ".join(kept) + "\n")
    out.write(f"Type the folder name ({expected}) to confirm: ")
    out.flush()
    typed = (inp.readline() or "").strip()
    if typed != expected:
        out.write("purge cancelled — the typed name did not match; nothing was removed\n")
        return False
    return True


def _main_purge_handoff(args, root: Path | None, vpy: Path, out) -> int:
    """--purge-data when this interpreter lacks the dependencies: purge under *vpy* first,
    then remove the software here. A failed purge removes nothing (same order and reason as
    :func:`run_uninstall`)."""
    data = data_root()
    rc, output, purge_report = _run_purge_handoff(vpy, data, args.no_backup)
    if rc != 0 or purge_report is None:
        out.write(f"uninstall aborted: the data purge under {vpy} failed (exit {rc}); "
                  f"nothing was removed\n")
        if output:
            out.write(output + "\n")
        return 2 if rc == 2 else 1  # a refusal in the child stays a refusal
    report = run_uninstall(root=root, gui=args.gui, keep_venv=_keep_venv(args, root))
    report["data_purge"] = purge_report["data_purge"]
    report["data_purge_interpreter"] = str(vpy)
    if report["data_purge"].get("ok") is False:
        report["not_removed"] = ["data_purge"] + report.get("not_removed", [])
        report["ok"] = False
    out.write(json.dumps(report, indent=2) + "\n")
    return 0 if report["ok"] else 1


def _venv_locked(args, root: Path | None) -> bool:
    """Would this run try to delete the ``.venv`` it is running from, on Windows?

    ``nerva uninstall`` (and ``.venv\\Scripts\\python -m agents.core.uninstall``) runs inside
    the app's own venv; Windows keeps a running interpreter's files locked, so the removal
    would leave ``.venv`` behind half-deleted. ``--gui-only`` and ``--purge-only`` never touch
    ``.venv``, and POSIX unlinks open files fine.
    """
    if args.gui_only or args.purge_only or not _platform().startswith("win"):
        return False
    return _running_in_venv(root if root is not None else _paths.app_root())


def _keep_venv(args, root: Path | None) -> bool:
    """UNINSTALL.bat's no-system-Python fallback (``--allow-locked-venv``) in the locked case:
    proceed with everything else and leave ``.venv`` for the user to delete by hand."""
    return bool(args.allow_locked_venv) and _venv_locked(args, root)


def _main(argv=None, *, out=None, inp=None) -> int:
    out = out if out is not None else sys.stdout
    inp = inp if inp is not None else sys.stdin
    ap = argparse.ArgumentParser(
        prog="python -m agents.core.uninstall",
        description="Remove Nerva's installer-created software footprint (venv(s), "
                     "WorldView's Node deps and generated env files). Your data is never "
                     "touched unless --purge-data is also given.",
    )
    ap.add_argument("--confirm", action="store_true",
                    help="required: acknowledge this removes .venv/ and WorldView's "
                         "node_modules/ + generated env files")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be removed (and whether data would be purged); "
                         "remove nothing")
    ap.add_argument("--purge-data", action="store_true",
                    help="ALSO erase the user's data root via data_purge.purge_data "
                         "(backup-first by default; irreversible; needs the data root's "
                         "folder name typed back, or --yes-purge=<absolute data-root path>)")
    ap.add_argument("--yes-purge", default=None, metavar="PATH",
                    help="non-interactive typed confirmation for --purge-data: the data "
                         "root's absolute path (relative paths are refused)")
    ap.add_argument("--no-backup", action="store_true",
                    help="with --purge-data, skip the pre-forget backup safety net — "
                         "NOT recommended")
    ap.add_argument("--gui", action="store_true",
                    help="also remove the desktop app (Tauri shell) and its webview caches")
    ap.add_argument("--gui-only", action="store_true",
                    help="remove ONLY the desktop app; keep the engine (venvs, WorldView) "
                         "and your data")
    ap.add_argument("--gui-summary", action="store_true",
                    help="print a JSON probe of the desktop app (installed, paths); remove nothing")
    ap.add_argument("--purge-only", action="store_true",
                    help="with --confirm --purge-data: erase the data root and remove nothing "
                         "else (used to run the purge under .venv's interpreter when the "
                         "calling interpreter lacks the engine's dependencies)")
    ap.add_argument("--root", default=None,
                    help="app root to uninstall from (defaults to the detected app root)")
    ap.add_argument("--allow-locked-venv", action="store_true",
                    help="(UNINSTALL.bat's fallback when no system Python exists) on Windows, "
                         "running from .venv: remove everything else and report .venv under "
                         "not_removed instead of refusing")
    args = ap.parse_args(argv)
    root = Path(args.root) if args.root else None

    if args.purge_only and (not args.purge_data or args.gui or args.gui_only
                            or args.gui_summary or args.dry_run):
        out.write("refusing: --purge-only needs --confirm --purge-data and cannot be combined "
                  "with --gui, --gui-only, --gui-summary or --dry-run\n")
        return 2

    if args.gui_summary:
        out.write(json.dumps(gui_summary(app_root=root), indent=2) + "\n")
        return 0
    if args.gui_only and args.purge_data:
        out.write("refusing: --gui-only removes only the desktop app; it cannot be combined "
                  "with --purge-data\n")
        return 2
    if args.yes_purge is not None and not args.purge_data:
        out.write("refusing: --yes-purge confirms --purge-data, which was not given\n")
        return 2

    if args.dry_run:
        plan = plan_uninstall(root, purge_data=args.purge_data, gui=args.gui,
                              gui_only=args.gui_only)
        plan["dry_run"] = True
        if _keep_venv(args, root):
            plan["venv_left_behind"] = VENV_LEFT_BEHIND_HINT
        elif _venv_locked(args, root):
            plan["venv_locked_on_windows"] = WINDOWS_VENV_LOCK_HINT
        out.write(json.dumps(plan, indent=2) + "\n")
        return 0

    if not args.confirm:
        out.write("refusing to uninstall without --confirm (this removes .venv/ and "
                  "WorldView's node_modules/ + generated env files)\n")
        return 2

    keep_venv = _keep_venv(args, root)
    if _venv_locked(args, root) and not keep_venv:
        out.write(f"refusing to uninstall: {WINDOWS_VENV_LOCK_HINT}; nothing was removed\n")
        return 2

    if args.purge_data:
        base = root if root is not None else _paths.app_root()
        # Checked BEFORE the typed confirmation: never ask the owner to type the data
        # root's name for a purge this interpreter cannot perform.
        can = purge_runnable(base)
        if args.purge_only and not can["in_process"]:
            out.write(f"refusing to purge: the engine's dependencies are unavailable under "
                      f"{sys.executable} ({can['reason']}); nothing was removed\n")
            return 2
        if not can["runnable"]:
            if can.get("venv_python"):
                out.write(f"refusing to purge: the .venv interpreter {can['venv_python']} "
                          f"exists but is the one running, and it cannot import the engine's "
                          f"dependencies ({can['reason']}); nothing was removed. Repair the "
                          f"venv (re-run the installer) and try again\n")
            else:
                out.write(f"refusing to purge: the engine's dependencies are unavailable "
                          f"under {sys.executable} ({can['reason']}) and no .venv interpreter "
                          f"was found under {base}; nothing was removed. Re-run with the "
                          f"interpreter the engine was installed into, e.g. .venv/bin/python "
                          f"-m agents.core.uninstall ...\n")
            return 2
        if not _confirm_purge(args, out, inp):
            return 2
        if can["handoff"]:
            return _main_purge_handoff(args, root, Path(can["handoff"]), out)
        from agents.core.data_purge import PurgeError
        from agents.core.data_purge import purge_data as _purge_data
        if args.purge_only:
            try:
                purge = _purge_data(source_root=None, backup_first=not args.no_backup,
                                    memory=True)
            except PurgeError as e:
                out.write(f"purge aborted: {e}\n")
                return 1
            out.write(json.dumps({"data_purge": purge, "ok": purge.get("ok") is not False},
                                 indent=2) + "\n")
            return 0
        try:
            report = run_uninstall(
                root=root,
                purge_data=True,
                data_backup_first=not args.no_backup,
                gui=args.gui,
                keep_venv=keep_venv,
            )
        except PurgeError as e:
            out.write(f"uninstall aborted: {e}\n")
            return 1
    else:
        report = run_uninstall(root=root, gui=args.gui, gui_only=args.gui_only,
                               keep_venv=keep_venv)
    out.write(json.dumps(report, indent=2) + "\n")
    return 0 if report["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
