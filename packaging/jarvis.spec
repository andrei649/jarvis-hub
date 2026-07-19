# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — builds the Jarvis one-folder (onedir) executable.

Build (from the repo root, inside the project venv):

    pip install pyinstaller
    python scripts/build_exe.py          # wraps: pyinstaller packaging/jarvis.spec

Output: dist/jarvis/jarvis(.exe on Windows) + dist/jarvis/_internal/ (the
bundle). One-folder, not one-file: this app reads real files at runtime
(HUD assets, agents.yaml, SOUL templates, bundled skills) and onedir keeps
startup instant and paths debuggable.

Data files are collected at bundle paths mirroring the source layout
(agents/web, agents/_system, agents/<id>/*.md, skills/, .env.example), so
`agents.core.paths.app_root()` — which returns sys._MEIPASS when frozen —
anchors them exactly like the repo root does in a dev checkout. All personal
state (memory, .env, generated skills, soul overlays) lives OUTSIDE the
bundle, in ~/Documents/Jarvis (see docs/PACKAGING.md).
"""

import glob
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # noqa: F821 — SPECPATH is a PyInstaller global

# The codebase imports its own modules under BOTH names (`agents.core.*` and the
# `core.*` alias via the agents/ sys.path entry) — make both resolvable for
# collect_submodules below.
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "agents"))

datas = [
    # HUD (v1 static + built v2 bundle) — served by agents/web.py.
    (os.path.join(ROOT, "agents", "web"), os.path.join("agents", "web")),
    # Canonical agent registry + system config.
    (os.path.join(ROOT, "agents", "_system"), os.path.join("agents", "_system")),
    # Bundled skill packs (read-only shipped content; user skills live in Documents/Jarvis).
    (os.path.join(ROOT, "skills"), "skills"),
    # First-run template copied to Documents/Jarvis/.env by ensure_user_home().
    (os.path.join(ROOT, ".env.example"), "."),
]

# Agent SOUL/HEARTBEAT templates: agents/<id>/*.md (generic templates only —
# *.local.md overlays are gitignored personal files and are deliberately NOT
# globbed here; a stray local overlay in the build checkout must never ship).
for md in glob.glob(os.path.join(ROOT, "agents", "*", "*.md")):
    if md.endswith(".local.md"):
        continue
    rel_dir = os.path.join("agents", os.path.basename(os.path.dirname(md)))
    datas.append((md, rel_dir))

hiddenimports = (
    # uvicorn selects loop/protocol/logging implementations dynamically.
    collect_submodules("uvicorn")
    # apscheduler trigger classes are resolved by name at add_job time.
    + collect_submodules("apscheduler")
    # Force-collect the app's own tree under BOTH import names — static
    # analysis misses lazily-imported `core.*` modules (routers import at
    # request time, channels/plugins conditionally), and a missing one is a
    # boot-time ModuleNotFoundError in the frozen app.
    + collect_submodules("agents")
    + collect_submodules("core")
    + ["dotenv"]
)

a = Analysis(
    [os.path.join(ROOT, "serve.py")],
    # Both roots — the codebase imports as `agents.core.*` AND `core.*`.
    pathex=[ROOT, os.path.join(ROOT, "agents")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Dev/test-only trees that must never ship.
    excludes=["pytest", "tests", "worldview", "mobile", "frontend"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="jarvis",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,   # server app: the console shows the startup banner + URL
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="jarvis",
)
