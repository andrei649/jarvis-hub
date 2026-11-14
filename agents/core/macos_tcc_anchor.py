"""macOS TCC interpreter anchoring for Nerva virtual environments (H690).

macOS Transparency, Consent, and Control (TCC) binds Accessibility, Screen Recording,
and Automation permissions to the resolved Mach-O binary path and code-signing identity.
Standard ``python -m venv`` creates ``.venv/bin/python*`` as symlinks into Cellar, ``uv``,
``pyenv``, ``mise``, ``asdf``, or ``conda`` versioned directories; upgrading the managed
interpreter changes that resolved target path and invalidates the owner's TCC grants.

This stdlib-only helper runs solely during ``bootstrap.py`` install and ``hub_update_apply``
upgrade/rollback:
1. No-ops off macOS (``sys.platform != "darwin"``) and for unmanaged system interpreters
   (such as ``/usr/bin/python3`` or ``/System/Library/...``), never raising.
2. Hardlinks ``libpython*.dylib`` from the managed interpreter's ``lib/`` into ``.venv/lib/``
   when same-UID and same-device (falling back to a real-file copy when cross-device or
   foreign-UID so ``scripts/venv_ownership.py:preflight_venv`` always passes).
3. Stages a real-file copy (never a symlink) of the managed interpreter inside ``.venv/bin/``,
   pins an ad-hoc signature with a stable identifier (``ai.nerva.python``) via
   ``/usr/bin/codesign --force --sign -``, and runs a pre-commit boot gate
   (``import encodings`` and ``Path(sys.prefix).resolve() == venv.resolve()``).
4. Atomically replaces ``.venv/bin/python*`` interpreter symlinks/binaries with real-file
   copies only after the boot gate passes; rolls back every staged file on any failure.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

TCC_IDENTIFIER = "ai.nerva.python"
CODESIGN_BIN = "/usr/bin/codesign"
BOOT_CHECK_CODE = (
    "import encodings, pathlib, sys; "
    "assert pathlib.Path(sys.prefix).resolve() == pathlib.Path(sys.argv[1]).resolve(), "
    "f'{sys.prefix} != {sys.argv[1]}'"
)
_INTERP_ENTRY = re.compile(r"^python(?:\d+(?:\.\d+)*)?$")
_LIBPYTHON_NAME = re.compile(r"^libpython\d+(?:\.\d+)*[a-z]*\.dylib$")

# Managed Python roots whose upgrade paths rotate across patch versions on macOS.
_MANAGED_MARKERS = (
    "/opt/homebrew/",
    "/usr/local/cellar/",
    "/usr/local/opt/python",
    "/.local/share/uv/python/",
    "/uv/python/",
    "/.pyenv/",
    "/.asdf/",
    "/.local/share/mise/",
    "/mise/installs/python/",
    "/conda/",
    "/miniconda",
    "/miniforge",
    "/mambaforge",
    "/pixi/",
    "/nix/store/",
)


def is_managed_macos_python(executable_path: Path) -> bool:
    """Return True when *executable_path* resolves to a managed non-Apple Python binary."""
    try:
        resolved = Path(os.path.realpath(str(executable_path)))
    except OSError:
        return False
    norm = resolved.as_posix().lower()
    if norm.startswith("/usr/bin/") or norm.startswith("/system/library/"):
        return False
    if any(marker in norm for marker in _MANAGED_MARKERS):
        return resolved.is_file()
    # Standalone python.org or relocatable framework builds installed under user home or /Library/Frameworks.
    if "/python.framework/" in norm and not norm.startswith("/system/"):
        return resolved.is_file()
    return False


def _parse_pyvenv_home(venv_dir: Path) -> Path | None:
    cfg = venv_dir / "pyvenv.cfg"
    if not cfg.is_file():
        return None
    try:
        for raw in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" not in raw:
                continue
            key, val = raw.split("=", 1)
            if key.strip().lower() == "home":
                home = val.strip()
                return Path(home) if home else None
    except OSError:
        return None
    return None


def _resolve_source_interpreter(venv_dir: Path, explicit_python: str | None) -> Path | None:
    """Locate the underlying managed interpreter binary for *venv_dir*."""
    candidates: list[Path] = []
    bin_dir = venv_dir / "bin"
    for name in ("python3", "python"):
        entry = bin_dir / name
        if os.path.islink(entry):
            with contextlib.suppress(OSError):
                candidates.append(Path(os.path.realpath(str(entry))))
    if explicit_python:
        p = Path(explicit_python)
        try:
            real_p = Path(os.path.realpath(str(p)))
            if real_p.parent.resolve() != bin_dir.resolve():
                candidates.append(real_p)
        except OSError:
            pass
    home = _parse_pyvenv_home(venv_dir)
    if home is not None:
        ver = f"python{sys.version_info[0]}.{sys.version_info[1]}"
        for name in (ver, "python3", "python"):
            cand = home / name
            if cand.exists():
                with contextlib.suppress(OSError):
                    candidates.append(Path(os.path.realpath(str(cand))))
    for cand in candidates:
        if cand.is_file() and not os.path.islink(cand):
            return cand
    return None


def _discover_libpython_files(source_bin: Path, venv_dir: Path) -> list[Path]:
    """Find ``libpython*.dylib`` next to the managed interpreter's prefix."""
    search_dirs: list[Path] = []
    home = _parse_pyvenv_home(venv_dir)
    for base in [source_bin.parent.parent, home.parent if home else None]:
        if base is not None:
            lib_dir = base / "lib"
            if lib_dir.is_dir() and lib_dir not in search_dirs:
                search_dirs.append(lib_dir)
    found: list[Path] = []
    for lib_dir in search_dirs:
        try:
            for entry in sorted(lib_dir.iterdir()):
                if _LIBPYTHON_NAME.match(entry.name) and entry.is_file():
                    real_lib = Path(os.path.realpath(str(entry)))
                    if real_lib.is_file():
                        found.append((entry.name, real_lib))  # type: ignore[arg-type]
        except OSError:
            continue
    return found  # type: ignore[return-value]


def _stage_libpython(
    venv_dir: Path,
    libs: list[tuple[str, Path]],
    runtime_uid: int,
) -> tuple[list[Path], list[tuple[Path, Path | None]]]:
    """Anchor ``libpython*.dylib`` into ``.venv/lib/`` via hardlink (same-UID/dev) or real copy.

    Returns ``(created_paths, backups)`` so caller can roll back cleanly if the boot gate fails.
    """
    venv_lib = venv_dir / "lib"
    venv_lib.mkdir(parents=True, exist_ok=True)
    lib_dev = os.stat(venv_lib).st_dev
    created: list[Path] = []
    backups: list[tuple[Path, Path | None]] = []
    pid = os.getpid()

    for link_name, src_real in libs:
        dest = venv_lib / link_name
        stage = venv_lib / f".{link_name}.nerva-stage.{pid}"
        _unlink_quiet(stage)
        src_stat = os.stat(src_real)
        linked = False
        if src_stat.st_uid == runtime_uid and src_stat.st_dev == lib_dev:
            try:
                os.link(src_real, stage)
                linked = True
            except OSError:
                linked = False
        if not linked:
            shutil.copy2(src_real, stage)
            os.chmod(stage, stat.S_IRWXU)

        backup: Path | None = None
        if os.path.lexists(dest):
            backup = venv_lib / f".{link_name}.nerva-bak.{pid}"
            _unlink_quiet(backup)
            os.replace(dest, backup)
        os.replace(stage, dest)
        created.append(dest)
        backups.append((dest, backup))
    return created, backups


def _rollback_libs(backups: list[tuple[Path, Path | None]]) -> None:
    for dest, backup in reversed(backups):
        _unlink_quiet(dest)
        if backup is not None and os.path.lexists(backup):
            try:
                os.replace(backup, dest)
            except OSError:
                _unlink_quiet(backup)


def _commit_libs(backups: list[tuple[Path, Path | None]]) -> None:
    for _, backup in backups:
        if backup is not None:
            _unlink_quiet(backup)


def _unlink_quiet(path: Path) -> None:
    try:
        if os.path.lexists(path):
            os.unlink(path)
    except OSError:
        pass


def anchor_venv_interpreter(
    venv_dir: Path,
    *,
    python: str | None = None,
    platform_name: str | None = None,
    codesign_bin: str = CODESIGN_BIN,
    run: Callable = subprocess.run,
    log: Callable[[str], None] | None = None,
) -> dict[str, object]:
    """Anchor *venv_dir*'s Python binary for macOS TCC survival across interpreter upgrades.

    Never raises: returns a structured dict ``{"ok": True, "anchored": bool, "reason": str, ...}``.
    """
    plat = sys.platform if platform_name is None else platform_name
    if plat != "darwin":
        return {"ok": True, "anchored": False, "reason": "not_macos"}

    try:
        venv_path = Path(venv_dir)
        bin_dir = venv_path / "bin"
        if not (venv_path / "pyvenv.cfg").is_file() or not bin_dir.is_dir():
            return {"ok": True, "anchored": False, "reason": "not_a_pyvenv"}

        source_bin = _resolve_source_interpreter(venv_path, python)
        if source_bin is None:
            return {"ok": True, "anchored": False, "reason": "source_interpreter_unresolved"}

        if not is_managed_macos_python(source_bin):
            return {"ok": True, "anchored": False, "reason": "unmanaged_interpreter", "source": str(source_bin)}

        if not os.path.isfile(codesign_bin):
            return {"ok": True, "anchored": False, "reason": "codesign_unavailable"}

        runtime_uid = os.geteuid() if hasattr(os, "geteuid") else 0
        pid = os.getpid()
        staged_py = bin_dir / f".python.nerva-stage.{pid}"
        _unlink_quiet(staged_py)

        libs = _discover_libpython_files(source_bin, venv_path)
        lib_backups: list[tuple[Path, Path | None]] = []
        try:
            if libs:
                _, lib_backups = _stage_libpython(venv_path, libs, runtime_uid)

            # Real-file copy (never symlink) + owner-executable mode so codesign can rewrite Mach-O signature.
            shutil.copy2(source_bin, staged_py)
            os.chmod(staged_py, stat.S_IRWXU)

            sign_proc = run(
                [codesign_bin, "--force", "--sign", "-", "--identifier", TCC_IDENTIFIER, str(staged_py)],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if getattr(sign_proc, "returncode", 1) != 0:
                _unlink_quiet(staged_py)
                _rollback_libs(lib_backups)
                if log:
                    log("macOS TCC anchor skipped: codesign failed; staged interpreter rolled back")
                return {"ok": False, "anchored": False, "reason": "codesign_failed"}

            # Pre-commit boot gate: verify encodings + sys.prefix == venv before touching live bin/python*.
            boot_proc = run(
                [str(staged_py), "-c", BOOT_CHECK_CODE, str(venv_path)],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if getattr(boot_proc, "returncode", 1) != 0:
                _unlink_quiet(staged_py)
                _rollback_libs(lib_backups)
                if log:
                    log("macOS TCC anchor skipped: boot gate failed; staged interpreter rolled back")
                return {"ok": False, "anchored": False, "reason": "boot_gate_failed"}

            # Collect all python* interpreter entries in .venv/bin (e.g. python, python3, python3.12).
            targets: list[Path] = []
            for entry in sorted(bin_dir.iterdir()):
                if _INTERP_ENTRY.match(entry.name) and (os.path.islink(entry) or entry.is_file()):
                    targets.append(entry)
            if not targets:
                targets = [bin_dir / "python3", bin_dir / "python"]

            bin_backups: list[tuple[Path, Path | None]] = []
            try:
                for idx, target in enumerate(targets):
                    bak: Path | None = None
                    if os.path.lexists(target):
                        bak = bin_dir / f".{target.name}.nerva-bak.{pid}"
                        _unlink_quiet(bak)
                        os.replace(target, bak)
                    bin_backups.append((target, bak))
                    if idx == len(targets) - 1:
                        os.replace(staged_py, target)
                    else:
                        next_stage = bin_dir / f".{target.name}.nerva-copy.{pid}"
                        _unlink_quiet(next_stage)
                        shutil.copy2(staged_py, next_stage)
                        os.chmod(next_stage, stat.S_IRWXU)
                        os.replace(next_stage, target)
            except Exception:
                _unlink_quiet(staged_py)
                for target, bak in reversed(bin_backups):
                    _unlink_quiet(target)
                    if bak is not None and os.path.lexists(bak):
                        with contextlib.suppress(OSError):
                            os.replace(bak, target)
                _rollback_libs(lib_backups)
                return {"ok": False, "anchored": False, "reason": "commit_replace_failed"}

            for _, bak in bin_backups:
                if bak is not None:
                    _unlink_quiet(bak)
            _commit_libs(lib_backups)
            if log:
                log(f"macOS TCC interpreter anchored ({len(targets)} binaries, {len(libs)} libpython dylib(s))")
            return {
                "ok": True,
                "anchored": True,
                "reason": "anchored",
                "source": str(source_bin),
                "binaries": [t.name for t in targets],
                "libpython": [name for name, _ in libs],
            }
        except Exception:
            _unlink_quiet(staged_py)
            _rollback_libs(lib_backups)
            return {"ok": False, "anchored": False, "reason": "anchor_exception"}
    except Exception:
        return {"ok": False, "anchored": False, "reason": "anchor_outer_exception"}
