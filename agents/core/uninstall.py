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
removal and data erasure stay two decisions, never one implicit action.

``--dry-run`` prints :func:`plan_uninstall` — every target, whether it exists, the desktop
app paths when ``--gui`` is given, and whether (and which) data root would be purged — and
removes nothing. ``--purge-data`` is never a bare flag: it also needs the data root's
folder name typed back (interactively, or as ``--yes-purge=<name>`` for scripts), the same
"type the name to delete it" guard a hosted product puts in front of an irreversible erase.

``--gui`` (Hermes' ``--gui`` analogue) also removes the Tauri desktop shell
(``desktop/src-tauri``: productName ``Jarvis Hub``, identifier ``com.jarvis.hub``) from the
per-OS places its bundles install to, plus the shell's own per-identifier webview/cache
dirs. A copy owned by a system package manager (``.deb``/``.rpm`` under ``/usr``, an MSI in
Program Files) is reported with the command that removes it rather than deleted behind the
package manager's back; an NSIS install is removed by running its own ``uninstall.exe /S``
so its registry entries go too. ``nerva uninstall`` (``agents/cli/nerva.py``) delegates here.

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

from agents.core.paths import app_root, data_root

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


def _kind(p: Path) -> str:
    exists = p.exists() or p.is_symlink()
    return "dir" if p.is_dir() and not p.is_symlink() else ("file" if exists else "absent")


def desktop_app_targets(*, platform: str | None = None, home: Path | None = None,
                        environ: Mapping[str, str] | None = None,
                        system_root: Path | None = None) -> list[dict]:
    """Where the desktop shell can live on this host, and how each copy is removed.

    ``action`` is ``remove`` (deleted by this module), ``uninstaller`` (an NSIS install,
    removed by running its own ``uninstall.exe /S``) or ``manual`` (owned by a system
    package manager — ``hint`` names the command). Every argument is injectable so the
    per-OS layouts are tested on any host; *system_root* prefixes absolute system paths.
    """
    plat = platform or sys.platform
    env = os.environ if environ is None else environ
    h = Path(home) if home is not None else Path.home()
    sysroot = Path(system_root) if system_root is not None else Path("/")
    cands: list[tuple[Path, str, str | None]] = []
    if plat == "darwin":
        app = f"{DESKTOP_PRODUCT_NAME}.app"
        cands += [(sysroot / "Applications" / app, "remove", None),
                  (h / "Applications" / app, "remove", None)]
        lib = h / "Library"
        cands += [(lib / sub / DESKTOP_IDENTIFIER, "remove", None)
                  for sub in ("Application Support", "Caches", "WebKit")]
        cands.append((lib / "Saved Application State" / f"{DESKTOP_IDENTIFIER}.savedState",
                      "remove", None))
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
                cands.append((d, "uninstaller", None))
            elif managed:
                cands.append((d, "manual",
                              f"remove '{DESKTOP_PRODUCT_NAME}' in Settings > Apps (MSI install)"))
            else:
                cands.append((d, "remove", None))
        cands += [(local / DESKTOP_IDENTIFIER, "remove", None),
                  (roaming / DESKTOP_IDENTIFIER, "remove", None),
                  (roaming / "Microsoft" / "Windows" / "Start Menu" / "Programs"
                   / f"{DESKTOP_PRODUCT_NAME}.lnk", "remove", None)]
    else:
        cands.append((sysroot / "usr" / "bin" / DESKTOP_BINARY, "manual",
                      f"sudo apt remove {DESKTOP_PACKAGE}  (or: sudo dnf remove {DESKTOP_PACKAGE})"))
        xdg_data = Path(env.get("XDG_DATA_HOME") or h / ".local" / "share")
        xdg_cache = Path(env.get("XDG_CACHE_HOME") or h / ".cache")
        xdg_config = Path(env.get("XDG_CONFIG_HOME") or h / ".config")
        cands += [(d / DESKTOP_IDENTIFIER, "remove", None) for d in (xdg_data, xdg_cache, xdg_config)]
        # An AppImage is wherever the user put it; these are the two conventional folders.
        for folder in (h / "Applications", h / ".local" / "bin"):
            if folder.is_dir():
                cands += [(p, "remove", None) for p in sorted(folder.glob("*.AppImage"))
                          if p.name.lower().replace(" ", "-").startswith(DESKTOP_PACKAGE)]
    rows = []
    for p, action, hint in cands:
        kind = _kind(p)
        row = {"path": str(p), "exists": kind != "absent", "kind": kind, "action": action}
        if hint:
            row["hint"] = hint
        rows.append(row)
    return rows


def plan_uninstall(root: Path | None = None, *, purge_data: bool = False, gui: bool = False,
                   data_source_root: str | None = None, desktop: dict | None = None) -> dict:
    """Report which installer-created targets exist under *root* (default: app_root()).

    Read-only — this is what ``--dry-run`` prints. ``purge_data`` reports whether (and
    which) data root a real run would erase; ``gui`` adds the desktop app's paths
    (*desktop* forwards :func:`desktop_app_targets`' injectable arguments).
    """
    base = Path(root) if root is not None else app_root()
    targets = []
    for rel in UNINSTALL_TARGETS:
        kind = _kind(base / rel)
        targets.append({"path": rel, "exists": kind != "absent", "kind": kind})
    plan: dict = {"root": str(base), "targets": targets, "purge_data": bool(purge_data)}
    if purge_data:
        plan["data_root"] = str(Path(data_source_root) if data_source_root else data_root())
    if gui:
        plan["desktop"] = desktop_app_targets(**(desktop or {}))
    return plan


def _default_runner(argv: list[str]) -> int:
    import subprocess  # nosec B404 - fixed argv: a found uninstall.exe and "/S", never a shell

    return subprocess.run(argv, check=False, timeout=600).returncode  # nosec B603 - see above


def _remove_desktop(rows: list[dict], runner: Callable[[list[str]], int] | None) -> dict:
    removed: list[str] = []
    manual: list[dict] = []
    not_removed: list[str] = []
    run = runner or _default_runner
    for row in rows:
        if not row["exists"]:
            continue
        p = Path(row["path"])
        if row["action"] == "manual":
            manual.append({"path": row["path"], "hint": row.get("hint", "")})
            continue
        try:
            if row["action"] == "uninstaller":
                if run([str(p / "uninstall.exe"), "/S"]) != 0:
                    not_removed.append(row["path"])
                    continue
            elif p.is_symlink() or p.is_file():
                p.unlink()
            else:
                shutil.rmtree(p)
            removed.append(row["path"])
        except (OSError, ValueError):
            logger.warning("uninstall: could not remove desktop path %s", p, exc_info=True)
            not_removed.append(row["path"])
    return {"removed": removed, "manual": manual, "not_removed": not_removed}


def run_uninstall(root: Path | None = None, *, purge_data: bool = False,
                  data_backup_first: bool = True,
                  data_source_root: str | None = None, gui: bool = False,
                  desktop: dict | None = None,
                  runner: Callable[[list[str]], int] | None = None) -> dict:
    """Remove every existing entry in :data:`UNINSTALL_TARGETS` under *root*.

    Best-effort per target, like ``data_purge.purge_data``: a target that exists but
    cannot be removed is reported under ``not_removed`` rather than silently skipped, and
    ``ok`` goes ``False`` so a caller can't mistake a partial removal for a clean one.

    Never touches the data root. Pass ``purge_data=True`` to *also* erase it via
    ``data_purge.purge_data`` (backup-first by default) — a separate, explicit decision.
    Pass ``gui=True`` to also remove the desktop app (:func:`desktop_app_targets`; *runner*
    runs an NSIS ``uninstall.exe`` and is faked in tests); package-managed copies come back
    under ``desktop.manual`` with their removal command and do not make ``ok`` false.

    The data purge, when requested, runs **before** any target is removed. Two reasons:
    a failed purge (``PurgeError`` — e.g. its own pre-forget backup won't verify) must
    leave the software install intact so the caller can retry, rather than aborting
    halfway with the venv already gone; and when this runs from ``.venv/bin/python``
    (as ``uninstall.sh`` may, if no system interpreter is available), ``data_purge``'s own
    imports need the venv's dependencies (e.g. ``cryptography`` for the backup) to still
    be on disk — ``.venv`` is one of the targets this function removes.
    """
    base = Path(root) if root is not None else app_root()
    report: dict = {"root": str(base)}

    if purge_data:
        from agents.core.data_purge import purge_data as _purge_data
        report["data_purge"] = _purge_data(
            source_root=data_source_root, backup_first=data_backup_first, memory=True,
        )

    removed: list[str] = []
    already_absent: list[str] = []
    not_removed: list[str] = []

    for rel in UNINSTALL_TARGETS:
        p = base / rel
        if not (p.exists() or p.is_symlink()):
            already_absent.append(rel)
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
    if gui:
        report["desktop"] = _remove_desktop(desktop_app_targets(**(desktop or {})), runner)
        not_removed = not_removed + report["desktop"]["not_removed"]
    report["ok"] = not not_removed
    if not_removed:
        report["not_removed"] = not_removed
    return report


# ── CLI ───────────────────────────────────────────────────────────
def _confirm_purge(args, out, inp) -> bool:
    """The typed confirmation --purge-data needs: the data root's folder name, typed back."""
    root = data_root()
    expected = root.name
    if args.yes_purge is not None:
        if args.yes_purge == expected:
            return True
        out.write(f"refusing to purge: --yes-purge={args.yes_purge!r} does not match the data "
                  f"root's folder name ({expected!r}, at {root})\n")
        return False
    isatty = getattr(inp, "isatty", None)
    if not (callable(isatty) and isatty()):
        out.write(f"refusing to purge without a typed confirmation: re-run with "
                  f"--yes-purge={expected} (the data root's folder name, at {root})\n")
        return False
    out.write(f"--purge-data ERASES your data at {root} (irreversible).\n"
              f"Type the folder name ({expected}) to confirm: ")
    out.flush()
    typed = (inp.readline() or "").strip()
    if typed != expected:
        out.write("purge cancelled — the typed name did not match; nothing was removed\n")
        return False
    return True


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
                         "folder name typed back, or --yes-purge=<name>)")
    ap.add_argument("--yes-purge", default=None, metavar="NAME",
                    help="non-interactive typed confirmation for --purge-data: the data "
                         "root's folder name")
    ap.add_argument("--no-backup", action="store_true",
                    help="with --purge-data, skip the pre-forget backup safety net — "
                         "NOT recommended")
    ap.add_argument("--gui", action="store_true",
                    help="also remove the desktop app (Tauri shell) and its webview caches")
    ap.add_argument("--root", default=None,
                    help="app root to uninstall from (defaults to the detected app root)")
    args = ap.parse_args(argv)
    root = Path(args.root) if args.root else None

    if args.dry_run:
        plan = plan_uninstall(root, purge_data=args.purge_data, gui=args.gui)
        plan["dry_run"] = True
        out.write(json.dumps(plan, indent=2) + "\n")
        return 0

    if not args.confirm:
        out.write("refusing to uninstall without --confirm (this removes .venv/ and "
                  "WorldView's node_modules/ + generated env files)\n")
        return 2

    if args.purge_data:
        if not _confirm_purge(args, out, inp):
            return 2
        from agents.core.data_purge import PurgeError
        try:
            report = run_uninstall(
                root=root,
                purge_data=True,
                data_backup_first=not args.no_backup,
                gui=args.gui,
            )
        except PurgeError as e:
            out.write(f"uninstall aborted: {e}\n")
            return 1
    else:
        report = run_uninstall(root=root, gui=args.gui)
    out.write(json.dumps(report, indent=2) + "\n")
    return 0 if report["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
