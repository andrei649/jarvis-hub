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
import shutil
from pathlib import Path

from agents.core.paths import app_root

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


def plan_uninstall(root: Path | None = None) -> dict:
    """Report which installer-created targets exist under *root* (default: app_root())."""
    base = Path(root) if root is not None else app_root()
    targets = []
    for rel in UNINSTALL_TARGETS:
        p = base / rel
        exists = p.exists() or p.is_symlink()
        targets.append({
            "path": rel,
            "exists": exists,
            "kind": "dir" if p.is_dir() and not p.is_symlink() else ("file" if exists else "absent"),
        })
    return {"root": str(base), "targets": targets}


def run_uninstall(root: Path | None = None, *, purge_data: bool = False,
                  data_backup_first: bool = True,
                  data_source_root: str | None = None) -> dict:
    """Remove every existing entry in :data:`UNINSTALL_TARGETS` under *root*.

    Best-effort per target, like ``data_purge.purge_data``: a target that exists but
    cannot be removed is reported under ``not_removed`` rather than silently skipped, and
    ``ok`` goes ``False`` so a caller can't mistake a partial removal for a clean one.

    Never touches the data root. Pass ``purge_data=True`` to *also* erase it via
    ``data_purge.purge_data`` (backup-first by default) — a separate, explicit decision.

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
        "ok": not not_removed,
    })
    if not_removed:
        report["not_removed"] = not_removed
    return report


# ── CLI ───────────────────────────────────────────────────────────
def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m agents.core.uninstall",
        description="Remove Nerva's installer-created software footprint (venv(s), "
                     "WorldView's Node deps and generated env files). Your data is never "
                     "touched unless --purge-data is also given.",
    )
    ap.add_argument("--confirm", action="store_true",
                    help="required: acknowledge this removes .venv/ and WorldView's "
                         "node_modules/ + generated env files")
    ap.add_argument("--purge-data", action="store_true",
                    help="ALSO erase the user's data root via data_purge.purge_data "
                         "(backup-first by default; irreversible)")
    ap.add_argument("--no-backup", action="store_true",
                    help="with --purge-data, skip the pre-forget backup safety net — "
                         "NOT recommended")
    ap.add_argument("--root", default=None,
                    help="app root to uninstall from (defaults to the detected app root)")
    args = ap.parse_args(argv)

    if not args.confirm:
        print("refusing to uninstall without --confirm (this removes .venv/ and "
              "WorldView's node_modules/ + generated env files)")
        return 2

    if args.purge_data:
        from agents.core.data_purge import PurgeError
        try:
            report = run_uninstall(
                root=Path(args.root) if args.root else None,
                purge_data=True,
                data_backup_first=not args.no_backup,
            )
        except PurgeError as e:
            print(f"uninstall aborted: {e}")
            return 1
    else:
        report = run_uninstall(root=Path(args.root) if args.root else None)
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
