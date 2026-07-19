# Packaging — the Jarvis executable & the owner's data folder

> How the repo becomes an installable app, and where a packaged install keeps
> the owner's personal state. Build tooling: `packaging/jarvis.spec` +
> `scripts/build_exe.py` + `packaging/windows/install.ps1`.

## The two-folder model

A packaged install strictly separates **the app** (replaceable) from **your
data** (yours, survives upgrades/uninstalls):

| Folder | Contents | Lifecycle |
|---|---|---|
| install dir (e.g. `%LOCALAPPDATA%\Programs\Jarvis`) | the executable + bundled read-only content: HUD assets, `agents.yaml`, SOUL/HEARTBEAT *templates*, bundled skills | replaced wholesale on upgrade; delete = uninstall |
| **`~/Documents/Jarvis`** (the *user data home*) | `README.md` · `.env` (secrets/config) · `memory/` (every runtime store: settings.db, checkpoints, audit, autonomy, embeddings) · `skills/` (user-installed/generated) · `souls/<id>/SOUL.local.md` + `HEARTBEAT.local.md` (personal persona overlays) | created on first run; **never** touched by install/upgrade/uninstall; backup = copy the folder |

Resolution lives in `agents/core/paths.py`:

- `user_home()` — `$JARVIS_USER_HOME` → that path; frozen executable → `~/Documents/Jarvis`; plain dev checkout → `None` (everything below is inert, dev behavior unchanged).
- `data_root()` — `$JARVIS_HOME`/`$JARVIS_MEMORY_DIR` (unchanged, always win) → `<user home>/memory` when a user home is active → `<repo>/memory_logs` dev default.
- `app_root()` — `$JARVIS_APP_ROOT` → PyInstaller bundle dir (`sys._MEIPASS`) when frozen → repo root. Anchors every formerly CWD-relative read (skills, souls, heartbeats, `agents.yaml`), so the app runs from any working directory.
- `ensure_user_home()` — idempotent first-run scaffold (folders + README + `.env` copied from `.env.example`); runs at boot in `web.py`'s lifespan and in `serve.py`.

Precedence for personal content when a user home is active:

- **Skills:** bundled `skills/` load first, then `<home>/skills` — a same-named user skill wins. New generated/marketplace-installed skills are written to `<home>/skills` (they're personal content). CDX-8 quarantine, signing, and contracts apply identically in both roots.
- **Souls/heartbeats:** `<home>/souls/<id>/SOUL.local.md` → repo-local `SOUL.local.md` → shipped `SOUL.md` template (same for `HEARTBEAT.local.md`).
- **`.env`:** repo `.env` (dev) loads first and keeps precedence; `<home>/.env` fills unset keys — in a packaged install there is no repo `.env`, so the Documents copy is the config source.

## Building

One-folder (onedir) build — startup stays instant and bundled files remain
real, debuggable paths. PyInstaller does **not** cross-compile: build on the
OS you're shipping for (the Windows exe is built on the Windows box —
`docs/OWNER_TASKS.md`).

```bash
pip install -r requirements-beta.txt pyinstaller
python scripts/build_exe.py          # build + boot smoke test
python scripts/build_exe.py --no-smoke
```

The smoke test boots the built binary with an isolated temp
`JARVIS_USER_HOME`, polls `/readyz`, and verifies the first-run scaffold —
proving the bundle actually starts, not just that PyInstaller exited 0.

Output: `dist/jarvis/` — the whole folder is the app (`jarvis[.exe]` +
`_internal/`). Zip it, or on Windows run the installer:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\windows\install.ps1
```

which copies it to `%LOCALAPPDATA%\Programs\Jarvis` (no admin needed) and adds
a Start Menu shortcut. Frontend note: the HUD ships pre-built (`agents/web/v2`
is committed), so no Node toolchain is needed at package time.

## What deliberately does NOT ship

- `*.local.md` personal overlays (excluded by the spec even if present in the build checkout), `.env`, `memory_logs/` — personal data never enters a bundle.
- `tests/`, `worldview/`, `mobile/`, `frontend/` sources, dev requirements.
- Optional heavy deps (torch / faster-whisper / wake word) — same opt-in installs as the dev checkout; the packaged app degrades gracefully exactly like `serve.py` does.

## Upgrading / uninstalling

- **Upgrade:** rebuild, re-run the installer — it replaces the app folder; `Documents/Jarvis` is untouched.
- **Uninstall:** delete the install folder (+ shortcut). Your data stays in `Documents/Jarvis`.
- **Full reset:** stop Jarvis, delete `Documents/Jarvis/memory`.

## Relocating data

Set in the app's environment (or a wrapper script): `JARVIS_USER_HOME` moves
the whole data folder; `JARVIS_HOME` moves only the runtime stores (legacy,
still honored and always wins for `data_root()`).
