# Desktop app — Electron main process, backend lifecycle, remote/SSH backends, updates, deep links, SDK/plugins

This shard documents everything on the **native/Electron side** of Hermes Desktop v2026.8.31: the
`apps/desktop/electron/**` main process (window/menu/protocol/permission wiring, the whole preload
IPC bridge, backend resolution + spawn + ownership + pooling, the multi-connection registry, remote /
Hermes Cloud / SSH backends, managed SSH updates, self-update + uninstall, HUD/Quick-Entry/pet/wake
auxiliary windows, terminal PTY host, git & fs IPC, hardening and platform quirks), the
`apps/desktop` packaging/build/scripts surface, the desktop **plugin SDK** (`src/sdk`, `src/plugins`),
the theme engine (`src/themes`), the REST/RPC client layer (`src/hermes.ts`, `src/api`), and the
JSON-RPC/WebSocket wire protocol the renderer speaks to `tui_gateway`.
Deliberately left to sibling shards: every React surface the user *sees* — chat, sidebars, HUD chrome,
command palette, Command Center, statusbar (`desktop-a`), sessions/agents/artifacts/cron/pets/bots
(`desktop-b`), and the entire Settings overlay including its Gateways/Connections *forms*
(`desktop-settings`); the gateway/Telegram surfaces (`gw-*`); tools/toolsets (`tools`); CLI commands
(`cli-*`); config keys other than `desktop.*` (`config-*`).

---

## 1. Packaging, build, and developer entry points

### Desktop app identity & packaging metadata  `id: desktop-main.package-identity`
- **Surface:** Desktop app
- **Where:** The installed application — macOS `Hermes.app`, Windows `Hermes` (Start-menu shortcut label `Hermes`), Linux `Hermes`. Bundle id `com.nousresearch.hermes`.
- **What it does:** Defines the app's name, version, icon, bundle identifier, protocol registration and per-OS installer targets used by electron-builder.
- **How it works:** `apps/desktop/package.json:1-13` (`"name": "hermes"`, `"productName": "Hermes"`, `"version": "0.17.0"`, `"main": "dist/electron-main.mjs"`, `"type": "module"`, engines `node ^22.22.0 || ^24.11.0 || >=26.0.0`). The `build` block at `apps/desktop/package.json:199-300` sets `electronVersion: "40.10.2"`, `appId: "com.nousresearch.hermes"`, `executableName: "Hermes"`, `artifactName: "Hermes-${version}-${os}-${arch}.${ext}"`, `icon: "assets/icon"`, `directories.output: "release"`, `asar: true`, `asarUnpack: ["**/*.node", "**/prebuilds/**", "dist/**"]`, `files: ["dist/**","assets/**","public/**","package.json"]`, hooks `beforeBuild: scripts/before-build.mjs`, `beforePack: scripts/before-pack.mjs`, `afterPack: scripts/after-pack.mjs`, `afterSign: scripts/notarize.mjs`, and `extraResources` copying `build/install-stamp.json → install-stamp.json` and `assets/icon.ico → icon.ico`.
- **Inputs / options:** n/a (build-time data).
- **Outputs / side effects:** Installers under `apps/desktop/release/`; the packaged app carries `install-stamp.json` (consumed by bundle-skew detection) and `icon.ico`.
- **Config / env:** n/a
- **Edge cases / guards:** `version` here is the **Electron shell** version and is deliberately *not* what the About panel shows — see `desktop-main.version-ipc`.
- **Rebuild notes:** Ship one Electron app id + productName; keep an install stamp resource so the shell can tell whether it is older than the Python runtime beside it.

### `hermes` URL scheme registration (`protocols`)  `id: desktop-main.protocol-declaration`
- **Surface:** Desktop app
- **Where:** OS URL-handler registration; a `hermes://…` link in any browser/app opens Hermes.
- **What it does:** Declares the app as the handler for the `hermes:` URL scheme so deep links launch or focus it.
- **How it works:** `apps/desktop/package.json:206-214` → `"protocols": [{ "name": "Hermes Protocol", "schemes": ["hermes"] }]`. At runtime `registerDeepLinkProtocol()` (`electron/main.ts:17274`) also calls `app.setAsDefaultProtocolClient(HERMES_PROTOCOL)` — in dev (`process.defaultApp`) with `process.execPath` + the resolved entry script so the OS can relaunch the dev instance with the URL.
- **Inputs / options:** n/a
- **Outputs / side effects:** OS-level scheme association; a log line `[deeplink] registered hermes:// handler` (or `[deeplink] protocol registration failed: …`) in `desktop.log`.
- **Config / env:** `HERMES_DESKTOP_DEV_SERVER` set → the scheme becomes `hermes-dev` (`electron/main.ts:17192`), and both `hermes-dev` and `hermes` are accepted when parsing (`DEEPLINK_SCHEMES`, `electron/main.ts:17194`).
- **Edge cases / guards:** Registration failures are logged, never fatal.
- **Rebuild notes:** Declare the scheme in the installer manifest *and* re-assert at runtime; use a separate dev scheme so a dev build cannot steal links from the installed app.

### macOS build target (DMG + zip, hardened runtime, entitlements, usage strings)  `id: desktop-main.build-mac`
- **Surface:** Desktop app / Platform:macOS
- **Where:** `npm run dist:mac` output; the DMG installer window titled **"Install Hermes"**.
- **What it does:** Produces a signed, notarized DMG and zip for macOS with the TCC usage descriptions macOS shows in permission prompts.
- **How it works:** `apps/desktop/package.json:231-278`. `mac.category: "public.app-category.developer-tools"`, `entitlements: electron/entitlements.mac.plist`, `entitlementsInherit: electron/entitlements.mac.inherit.plist`, `gatekeeperAssess: false`, `hardenedRuntime: true`, `target: ["dmg","zip"]`. `extendInfo` sets `CFBundleDisplayName/Executable/Name = "Hermes"` plus the usage strings quoted verbatim below. DMG layout: `title: "Install Hermes"`, `backgroundColor: "#f5f5f7"`, `iconSize: 96`, window `560×360`, contents `{x:160,y:170,type:"file"}` and `{x:400,y:170,type:"link",path:"/Applications"}`. `scripts/notarize.mjs` runs as `afterSign`; `scripts/patch-electron-builder-mac-binary.mjs` runs as `prebuilder`.
- **Inputs / options:** Verbatim `Info.plist` usage strings —
  - `NSAudioCaptureUsageDescription`: "Hermes uses audio capture for voice conversations."
  - `NSCameraUsageDescription`: "Hermes uses the camera when a plugin or feature you enable requests it."
  - `NSMicrophoneUsageDescription`: "Hermes uses the microphone for voice input and voice conversations."
  - `NSCalendarsUsageDescription`: "Hermes needs access to Calendar to provide requested meeting and scheduling support."
  - `NSCalendarsFullAccessUsageDescription`: "Hermes needs full access to Calendar to read and manage events when explicitly requested."
  - `NSRemindersUsageDescription`: "Hermes needs access to Reminders to provide requested personal-assistant and scheduling support."
  - `NSRemindersFullAccessUsageDescription`: "Hermes needs full access to Reminders to read and manage reminders when explicitly requested."
  - `NSScreenCaptureUsageDescription`: "Hermes captures the screen when you ask the agent to screenshot or record it."
  - `NSLocalNetworkUsageDescription`: "Hermes connects to devices on your local network when a plugin or feature you enable requests it."
  - `NSAppleMusicUsageDescription`: "Hermes accesses your music library when a plugin or feature you enable requests it."
- **Outputs / side effects:** `Hermes-<version>-mac-<arch>.dmg` and `.zip` in `release/`.
- **Config / env:** Signing/notarization engage automatically when `CSC_LINK`, `CSC_KEY_PASSWORD`, `APPLE_*` are present (README "Building installers").
- **Edge cases / guards:** `gatekeeperAssess: false` skips the local Gatekeeper assessment during build; hardened runtime requires the entitlements files above.
- **Rebuild notes:** Every TCC-touching capability needs a usage string or macOS kills the process on first use; keep a separate `entitlementsInherit` for helper processes.

### Windows build target (NSIS + MSI)  `id: desktop-main.build-win`
- **Surface:** Desktop app / Platform:Windows
- **Where:** `npm run dist:win` (`dist:win:msi`, `dist:win:nsis`); the installer UI and Programs-and-Features entry.
- **What it does:** Builds a per-user NSIS installer and an MSI.
- **How it works:** `apps/desktop/package.json:279-299` — `win.legalTrademarks: "Hermes"`, `win.target: ["nsis","msi"]`, `win.signAndEditExecutable: false`; `nsis`: `oneClick: false`, `allowToChangeInstallationDirectory: true`, `perMachine: false`, `shortcutName: "Hermes"`, `uninstallDisplayName: "Hermes"`, `warningsAsErrors: false`. `scripts/set-exe-identity.mjs` + `rcedit` adjust exe metadata.
- **Inputs / options:** `--win`, `--win msi`, `--win nsis` builder flags.
- **Outputs / side effects:** `Hermes-<version>-win-<arch>.exe` / `.msi`.
- **Config / env:** `WIN_CSC_*` for signing.
- **Edge cases / guards:** `perMachine: false` means no admin elevation; `signAndEditExecutable: false` avoids electron-builder's own signing pass (identity is patched separately).
- **Rebuild notes:** Prefer per-user installs so an agent that self-updates never needs elevation.

### Linux build targets (AppImage + deb + rpm)  `id: desktop-main.build-linux`
- **Surface:** Desktop app / Platform:Linux
- **Where:** `npm run dist:linux`.
- **What it does:** Builds AppImage, .deb, and .rpm packages.
- **How it works:** `apps/desktop/package.json:280-292` — `linux.category: "Development"`, `maintainer: "Nous Research <support@nousresearch.com>"`, `synopsis: "Native desktop shell for Hermes Agent."`, `target: ["AppImage","deb","rpm"]`.
- **Inputs / options:** builder flag `--linux AppImage deb rpm`.
- **Outputs / side effects:** three artifacts in `release/`.
- **Config / env:** `APPIMAGE` env var is read at runtime by the update/relaunch path.
- **Edge cases / guards:** AppImage self-update relaunch has to re-exec the AppImage path, not the extracted binary.
- **Rebuild notes:** Ship all three; AppImage is the only one that works without a package manager.

### npm scripts — build, dev, dist, test, repro  `id: desktop-main.npm-scripts`
- **Surface:** Desktop app / Docs
- **Where:** `cd apps/desktop && npm run <script>`; documented in `apps/desktop/README.md` ("Development", "Building installers", "Verification").
- **What it does:** The complete developer command surface for the desktop app.
- **How it works:** `apps/desktop/package.json:15-84`.
- **Inputs / options:** Every script, verbatim:
  - `clean`, `clean:e2e` (`tsc --build tsconfig.e2e.json --clean`), `clean:renderer`, `clean:electron`
  - `dev` — `concurrently -k "npm:dev:renderer" "npm:dev:electron"`
  - `dev:fake-boot` — `cross-env HERMES_DESKTOP_BOOT_FAKE=1 HERMES_DESKTOP_BOOT_FAKE_STEP_MS=650 npm run dev`
  - `dev:mock` — `node scripts/dev-mock.mjs`
  - `dev:renderer` — asserts root install, cleans, `vite --host 127.0.0.1 --port 5174`
  - `dev:electron` — builds electron TS, `wait-on http://127.0.0.1:5174`, bundles main with `--dev`, launches `electron .` with `XCURSOR_SIZE=24` and `HERMES_DESKTOP_DEV_SERVER=http://127.0.0.1:5174`
  - `profile:main` — same as `dev:electron` plus `electron --inspect=9229 .`
  - `profile:main:cpu` — same plus `NODE_OPTIONS=--cpu-prof`
  - `start` — `npm run build && electron .`
  - `prebuild` (`clean`), `build` (assert-root-install → write-build-stamp → `vite build` → bundle-electron-main → stage-native-deps), `postbuild` (`assert-dist-built`)
  - `prebuilder` (`patch-electron-builder-mac-binary.mjs`), `builder` (`NODE_OPTIONS=--max-old-space-size=16384 node scripts/run-electron-builder.mjs`)
  - `pack` (`--dir --publish never`), `dist`, `dist:mac`, `dist:mac:dmg`, `dist:mac:zip`, `dist:win`, `dist:win:msi`, `dist:win:nsis`, `dist:linux`
  - `perf` (`scripts/perf/run.mjs`), `perf:serve` (`scripts/perf/serve.mjs`)
  - `update:shim`, `update:shim:fail`, `update:repro:fresh`, `update:repro:behind`, `update:repro:error`, `update:repro:gate`, `update:repro:launch` — all `bash ../../scripts/desktop-update/repro.sh <mode>`
  - `test:desktop`, `test:desktop:all`, `test:desktop:dmg`, `test:desktop:nsis`, `test:desktop:existing`, `test:desktop:fresh` — `node scripts/test-desktop.mjs [mode]`
  - `typecheck` (three tsconfigs), `lint` (`eslint src/ electron/`), `lint:fix`, `fmt` (prettier), `fix`
  - `test:ui` (`vitest run --project ui`), `test:desktop:platforms` (`vitest run --project electron`), `test:find-in-page-native` (`electron electron/find-in-page-native-fixture`), `test`
  - `preview` (`vite preview --host 127.0.0.1 --port 4174`)
  - `check:test:ui`, `check:test:desktop:platforms`, `check:test:desktop:all`, `check:lint`, `check`
  - `test:e2e` (`npm run build && playwright test e2e/`), `test:e2e:visual` and `test:e2e:update-snapshots` (both run under `cage` with `WLR_BACKENDS=headless WLR_NO_HARDWARE_CURSORS=1`)
  - `repro:short-session-hang`, `repro:short-session-hang:test`
- **Outputs / side effects:** `dist/`, `release/`, `build/install-stamp.json`.
- **Config / env:** `HERMES_DESKTOP_DEV_SERVER`, `HERMES_DESKTOP_BOOT_FAKE*`, `XCURSOR_SIZE`, `ELECTRON_MIRROR`.
- **Edge cases / guards:** `scripts/assert-root-install.mjs` refuses to run if workspace deps were not installed from the repo root; `assert-dist-built.mjs` fails a build that produced no bundle.
- **Rebuild notes:** Separate renderer and main build lanes, gate the electron launch on the vite server being up, and stamp the build commit so skew detection is possible.

### Dev sandboxing (`dev-sandbox.sh`, `HERMES_DESKTOP_USER_DATA_DIR`, `HERMES_DESKTOP_APP_NAME`)  `id: desktop-main.dev-sandbox`
- **Surface:** Env / Desktop app
- **Where:** `../scripts/dev-sandbox.sh npm run dev` (README "Development").
- **What it does:** Runs a dev build against a throwaway `HERMES_HOME`, a separate Electron `userData` directory and a distinct app name so it does not fight the installed app's single-instance lock.
- **How it works:** `USER_DATA_OVERRIDE = process.env.HERMES_DESKTOP_USER_DATA_DIR` (`electron/main.ts:442`); when set, main `mkdirSync`s it and calls `app.setPath('userData', resolved)` **before** anything reads userData paths. `APP_NAME = process.env.HERMES_DESKTOP_APP_NAME || 'Hermes'` (`electron/main.ts:890`) and `HUD_WINDOW_TITLE = \`${APP_NAME} HUD\`` (`:891`).
- **Inputs / options:** `HERMES_DESKTOP_USER_DATA_DIR=<path>`, `HERMES_DESKTOP_APP_NAME=<name>`, `HERMES_HOME=<path>`, `HERMES_DESKTOP_HERMES_ROOT=<checkout>`.
- **Outputs / side effects:** All userData JSON stores (connection.json, connections.json, window-state.json, …) relocate under the override.
- **Config / env:** as above.
- **Edge cases / guards:** Must be applied before `app.getPath('userData')` is first evaluated — main does it at module top.
- **Rebuild notes:** One env var that relocates the whole app-state root makes parallel dev instances trivial.

### `hermes desktop` launcher flags  `id: desktop-main.cli-desktop-flags`
- **Surface:** CLI / Desktop app
- **Where:** `hermes desktop [flags]`; documented at `website/docs/user-guide/desktop.md` → "CLI reference: `hermes desktop`".
- **What it does:** Builds (or skips building) and launches the desktop app against the current Hermes install.
- **How it works:** `hermes_cli/subcommands/gui.py` defines the argparse surface; the launcher bridges config → env (`HERMES_DESKTOP_CWD`, `HERMES_DESKTOP_HERMES_ROOT`, `HERMES_DESKTOP_IGNORE_EXISTING`, `HERMES_DESKTOP_DISABLE_GPU`, `HERMES_DESKTOP_PASSWORD_STORE`, `ELECTRON_OZONE_PLATFORM_HINT`) before spawning Electron.
- **Inputs / options:** `--skip-build`, `--force-build`, `--build-only`, `--source`, `--cwd PATH`, `--hermes-root PATH`, `--ignore-existing`, `--fake-boot`, `--setup-tcc-identity`, `--identity <name>` (default `Hermes Local Signing`).
- **Outputs / side effects:** May run `npm install` + `npm run pack`, then launches the packaged app from `apps/desktop/release`.
- **Config / env:** `desktop.electron_flags`, `desktop.ozone_platform_hint`, `desktop.disable_gpu`, `desktop.password_store`, `desktop.macos_signing_identity`.
- **Edge cases / guards:** `--build-only` is what `hermes update` uses; `--source` launches `electron .` against `apps/desktop/dist` instead of the packaged artifact.
- **Rebuild notes:** Keep the build step idempotent behind a content stamp so a launch is instant when nothing changed.

### macOS local code-signing identity (`hermes desktop --setup-tcc-identity`)  `id: desktop-main.tcc-identity`
- **Surface:** CLI / Platform:macOS / Config
- **Where:** `hermes desktop --setup-tcc-identity [--identity "Hermes Local Signing"]`; config key `desktop.macos_signing_identity`.
- **What it does:** Creates (or reuses) a self-signed code-signing certificate in the login keychain, grants `codesign` access to it, writes the identity into config, and re-signs the packaged desktop app — so macOS TCC grants (Full Disk Access, Desktop/Downloads/Documents, Accessibility, Automation, microphone, ScreenCapture) survive every self-update.
- **How it works:** `hermes_cli/main.py:7924-8068` implements the one-shot setup: requires `openssl`, `security`, `codesign`; on success prints `→ set desktop.macos_signing_identity = '<name>'` via `set_config_value("desktop.macos_signing_identity", identity)` (`main.py:8065`). Signing at update time reads the key back at `main.py:7661`. `hermes_cli/doctor.py:1097-1107` reports the certificate-anchored DR state.
- **Inputs / options:** `--setup-tcc-identity` (macOS only; prints "(--setup-tcc-identity is macOS-only; skipping)" elsewhere, `main.py:7943`), `--identity <cert name>`.
- **Outputs / side effects:** New keychain certificate; config value written; the packaged app re-signed.
- **Config / env:** `desktop.macos_signing_identity` (default `""` → stable identifier-pinned ad-hoc signature).
- **Edge cases / guards:** Manual path documented in `website/docs/user-guide/desktop.md` (Keychain Access → Create a Certificate… → Self-Signed Root → Code Signing → Trust → Always Trust). Grants made before the identifier-pinned signing fix (PR #73681) carry a cdhash-pinned requirement and must be reset with `tccutil reset <Service> com.nousresearch.hermes`.
- **Rebuild notes:** Anchor TCC on a certificate-backed Designated Requirement, not on the binary hash; make the setup idempotent so it can be re-run after any update.

### Stable macOS TCC anchor for the uv-managed interpreter  `id: desktop-main.tcc-anchor-python`
- **Surface:** Core / Platform:macOS
- **Where:** Invisible; runs during install/update. Reported by `hermes doctor`.
- **What it does:** Copies the uv-managed Python interpreter to the stable path `venv/bin/python` and identifier-pins its signature, so macOS TCC grants keyed to the interpreter path survive every uv patch bump.
- **How it works:** `hermes_cli/macos_tcc_anchor.py`. Detection of a uv store interpreter uses `_STORE_COMMON_MARKERS = ("cpython-", "-macos-")` and `_STORE_ROOT_MARKERS = ("/uv/python/", f"/{_RUNTIME_DIR_NAME}/python/")` (`:60-63`). `_provision_libpython` (`:186`) hardlinks (or copies across devices) `libpython*` into `venv/lib/` because the build's `LC_RPATH` is `@executable_path/../lib`. `_materialize_aliases` (`:250`) writes `python3`/`python3.N` as **real file copies**, never symlinks (a symlink makes CPython `getpath` lose the venv prefix → `ModuleNotFoundError: encodings`). `_passes_boot_gate` (`:278`) actually launches the staged copy and demands `import encodings` and `sys.prefix == <venv>`; failure raises `_BootGateFailed` and rolls the staging file back. `ensure_tcc_anchor()` (`:368`) is the entry point; `tcc_anchor_state()` (`:413`) reports state. Provenance marker file: `.tcc-anchor-source` (`_MARKER_NAME`, `:58`).
- **Inputs / options:** `ensure_tcc_anchor(project_root=None)`.
- **Outputs / side effects:** `venv/bin/python` (+ aliases) become real copies; `venv/lib/libpython*` provisioned; `.tcc-anchor-source` marker written.
- **Config / env:** n/a
- **Edge cases / guards:** No-op on non-macOS and on interpreters that are not uv-managed; never raises to callers (best-effort).
- **Rebuild notes:** If the OS keys permissions to a binary path, own that path yourself and copy the real interpreter in — and gate the swap on an actual boot test.

### Install-stamp resource (`install-stamp.json`)  `id: desktop-main.install-stamp`
- **Surface:** Core
- **Where:** Packaged app resources; written at build time by `scripts/write-build-stamp.mjs`.
- **What it does:** Records the git commit the renderer bundle was built from, enabling bundle-skew detection.
- **How it works:** `loadInstallStamp()` (`electron/main.ts:684`) reads it and validates `INSTALL_STAMP_SCHEMA_VERSION = 1` (`:682`); the value is exported as `INSTALL_STAMP` (`:727`) and consumed by `detectBundleSkew` (`electron/bundle-skew.ts:56`) and by the bootstrap-needed sentinel payload.
- **Inputs / options:** n/a
- **Outputs / side effects:** none at runtime.
- **Config / env:** n/a
- **Edge cases / guards:** Missing stamp (dev), all-zero fallback commit (`isFallbackCommit`, `bundle-skew.ts:52`), unknown commit in a shallow clone, or any git failure all report "not stale" — the warning must never false-positive.
- **Rebuild notes:** A single build-commit stamp is the cheapest way to detect "new backend, old UI".

---

## 2. Process model, app lifecycle and launch-time switches

### Single-instance lock and second-instance routing  `id: desktop-main.single-instance`
- **Surface:** Desktop app
- **Where:** Invisible. Observed when a second `Hermes` launch (Start Menu, `hermes desktop`, an `hermes://` link) focuses the existing window instead of opening a new app.
- **What it does:** Only one Hermes Desktop process may own the backend machinery. A second launch hands its argv to the running instance and exits immediately.
- **How it works:** `const _gotSingleInstanceLock = app.requestSingleInstanceLock()` / `const isPrimaryInstance = _gotSingleInstanceLock` (`electron/main.ts:17295-17296`). A lock loser calls `app.exit(0)` — **not** `app.quit()` — at `main.ts:17318`, because the `before-quit` teardown coordinator defers a plain quit and `ready` would still fire, letting the loser's `reapOrphans()` SIGTERM the live instance's backend (#87295). The winner registers `app.on('second-instance', (_event, argv) => …)` (`main.ts:17321`), which extracts a deep link from argv and calls `ensureMainWindow(mainWindow, { isReady: app.isReady(), createWindow, focusWindow, focusExisting: !url })` (`main.ts:17328`, helper in `electron/main-window-lifecycle.ts`).
- **Inputs / options:** none (implicit: the OS-level lock, the second process's `process.argv`).
- **Outputs / side effects:** Second process exits with code 0; the first window is restored/focused, or receives a `hermes:deep-link` payload.
- **Config / env:** n/a
- **Edge cases / guards:** `startHermes()` re-checks `isPrimaryInstance` and throws `Hermes Desktop is already running in another window.` (`main.ts:12259-12262`) so no code path can spawn a backend from a non-primary instance.
- **Rebuild notes:** Take the OS single-instance lock before anything else, hard-exit the loser (never a graceful quit that can still run `ready`), and forward argv to the winner.

### Remote-display GPU fallback  `id: desktop-main.remote-display-gpu`
- **Surface:** Desktop app / Core
- **Where:** Invisible; logged as `[hermes] remote display detected (<reason>); disabling GPU hardware acceleration to prevent flicker`. Readable by the renderer via `window.hermesDesktop.getRemoteDisplayReason()`.
- **What it does:** When the app is running on a forwarded/remote display (SSH X11, VNC, RDP) it turns off GPU acceleration so scrolling and streaming do not flicker.
- **How it works:** `const REMOTE_DISPLAY_REASON = detectRemoteDisplay()` (`main.ts:484`, implementation in `electron/bootstrap-platform.ts`). When truthy, `app.disableHardwareAcceleration()` plus `app.commandLine.appendSwitch('disable-gpu-compositing')` (`main.ts:487-489`). Must run before `app` `ready`. IPC read: `ipcMain.handle('hermes:get-remote-display-reason', () => REMOTE_DISPLAY_REASON)` (`main.ts:646`).
- **Inputs / options:** `HERMES_DESKTOP_DISABLE_GPU` (`1`/`true` → always disable, `0`/`false` → keep GPU on).
- **Outputs / side effects:** Chromium runs software-composited; renderer can display an explanation.
- **Config / env:** env `HERMES_DESKTOP_DISABLE_GPU`; `desktop.ozone_platform_hint` (separate, see Wayland entry).
- **Edge cases / guards:** WSLg is *not* treated as remote — it renders locally (see the `/dev/dxg` entry).
- **Rebuild notes:** Detect the remote display cheaply from environment (DISPLAY host, SSH_CONNECTION, session type) and fail toward software rendering; expose the reason so the UI can explain the degraded mode.

### WSL GPU passthrough un-blocklisting  `id: desktop-main.wsl-gpu`
- **Surface:** Desktop app / Platform:WSL
- **Where:** Invisible; logged `[hermes] WSL GPU passthrough (/dev/dxg) detected; enabling GPU acceleration`.
- **What it does:** On WSLg with a real vGPU, re-enables GPU rasterization that Chromium's blocklist would otherwise disable (which caused typing lag).
- **How it works:** `if (IS_WSL && !REMOTE_DISPLAY_REASON && fs.existsSync('/dev/dxg'))` → appends switches `ignore-gpu-blocklist`, `enable-gpu-rasterization`, `enable-zero-copy` (`main.ts:522-527`).
- **Inputs / options:** n/a — purely detected.
- **Outputs / side effects:** GPU-composited rendering under WSLg.
- **Config / env:** n/a
- **Edge cases / guards:** Skipped when a remote display already forced software (SSH'd into WSL).
- **Rebuild notes:** Probe for the vGPU device node rather than trusting the platform string.

### Linux keychain backend selection (`--password-store`)  `id: desktop-main.linux-password-store`
- **Surface:** Desktop app / Platform:Linux
- **Where:** Invisible; logged `[hermes] using password-store backend: <store>` (and a warning line when detection is ambiguous).
- **What it does:** Points Chromium's `safeStorage` at the session's keyring backend so remote-gateway tokens can be encrypted at rest on Linux.
- **How it works:** `const PASSWORD_STORE = resolveLinuxPasswordStore()` (`main.ts:534`, in `electron/bootstrap-platform.ts`); `app.commandLine.appendSwitch('password-store', PASSWORD_STORE.store)` (`main.ts:542`). The value arrives via `HERMES_DESKTOP_PASSWORD_STORE`, bridged by the `hermes desktop` launcher from detection or `desktop.password_store` in config.yaml. Keyring-less Linux is handled by `enableBasicPasswordStoreEncryption({ platform, passwordStoreSwitch: app.commandLine.getSwitchValue('password-store'), safeStorageApi: safeStorage })` (`main.ts:17350`, in `electron/hardening.ts`).
- **Inputs / options:** env `HERMES_DESKTOP_PASSWORD_STORE`; config `desktop.password_store`.
- **Outputs / side effects:** safeStorage becomes usable (or explicitly `basic`).
- **Config / env:** `desktop.password_store`, `HERMES_DESKTOP_PASSWORD_STORE`.
- **Edge cases / guards:** Must run before `ready`. `PASSWORD_STORE.warning` is printed when the detection is not confident.
- **Rebuild notes:** Never assume a keyring exists on Linux; make encryption opt-in and degrade to file permissions.

### Windows Chromium-sandbox fallback and ACL repair  `id: desktop-main.windows-sandbox-fallback`
- **Surface:** Desktop app / Platform:Windows
- **Where:** Invisible; logged `[hermes] Windows sandbox fallback enabled (<reason>); launching with --no-sandbox (#38216)`, `[hermes] granted ALL APPLICATION PACKAGES RX on <dir> (#38216)`, `[hermes] Windows GPU sandbox crashed (exit=…); relaunching once with --no-sandbox`.
- **What it does:** Recovers Windows installs where Chromium's sandboxed GPU/renderer children die with 0x80000003 (AMD RX 6000 drivers, missing `S-1-15-2-2` ACEs) by repairing the install-dir ACL and, if needed, relaunching without the sandbox — recorded in a version-scoped sticky marker.
- **How it works:** `readSandboxMarker(userData)` → `shouldAttemptAclRepair(priorMarker)` → `grantAllApplicationPackagesAcl(exeDir, { execFileSync })` (icacls /T on the install dir only, never on userData) → `decideWindowsSandboxLaunch({ argv, env, marker, appVersion })` → `app.commandLine.appendSwitch('no-sandbox')` + `process.env.ELECTRON_DISABLE_SANDBOX = '1'` → `writeSandboxMarker(userData, decision.nextMarker)`. Live GPU deaths hook `app.on('child-process-gone', …)` with `shouldRelaunchForGpuSandboxCrash({ details, alreadyNoSandbox, relaunchAttempted })`, then `app.relaunch({ args: buildNoSandboxRelaunchArgs(process.argv.slice(1)) })` and `exitAfterBackendShutdown(0)`. All of `main.ts:560-641`; implementation `electron/windows-sandbox-fallback.ts` (394 lines) exporting `alreadyHasNoSandbox`, `buildNoSandboxRelaunchArgs`, `decideWindowsSandboxLaunch`, `fallbackMarker`, `grantAllApplicationPackagesAcl`, `markerAfterSuccessfulBoot`, `readSandboxMarker`, `shouldAttemptAclRepair`, `shouldRelaunchForGpuSandboxCrash`, `shouldRelaunchForRendererSandboxCrashLoop`, `writeSandboxMarker`.
- **Inputs / options:** `--no-sandbox` on argv; `ELECTRON_DISABLE_SANDBOX`; marker states `booting` / `fallback` / clean with `reason ∈ {boot-loop, gpu-breakpoint, renderer-crash-loop}` and the app version.
- **Outputs / side effects:** Marker file under `userData`; ACL grant on the install directory; a one-time process relaunch.
- **Config / env:** env `ELECTRON_DISABLE_SANDBOX`.
- **Edge cases / guards:** `windowsSandboxFallbackActive` (running without the sandbox, any cause) vs `windowsSandboxFallbackSticky` (the fallback machinery engaged and the marker must stay `fallback`). A clean quit mid-boot writes `markerAfterSuccessfulBoot({ fallbackActive: false })` so it doesn't trip next launch (`main.ts:17565-17572`). Version-scoped so an app update re-probes the sandbox rather than degrading forever. Relaunch happens at most once per process (`windowsNoSandboxRelaunchAttempted`).
- **Rebuild notes:** Record a boot marker before the window opens, clear it on a clean boot, and treat "marker still says booting" as proof of a crash loop; scope the marker to the app version so a fix re-enables the sandbox.

### Renderer background-priority switch  `id: desktop-main.renderer-backgrounding`
- **Surface:** Desktop app
- **Where:** Invisible.
- **What it does:** Keeps the renderer process at normal OS scheduling priority when its windows are hidden, so a streaming answer keeps painting at full speed while minimized — without pinning `document.visibilityState`.
- **How it works:** `app.commandLine.appendSwitch('disable-renderer-backgrounding')` (`main.ts:665`). The old process-wide `disable-background-timer-throttling` / `disable-backgrounding-occluded-windows` switches and static `backgroundThrottling: false` were removed because they made an idle minimized Hermes burn ~20% CPU; timer throttling is now a runtime dial (see `desktop-main.stream-throttle`).
- **Inputs / options:** n/a
- **Outputs / side effects:** Scheduling priority only.
- **Config / env:** n/a
- **Edge cases / guards:** Does not exempt timers from throttling.
- **Rebuild notes:** Separate "process priority" from "timer throttling"; only the second one has the visibility side effects.

### Renderer debugging port (dev CDP)  `id: desktop-main.dev-cdp`
- **Surface:** Desktop app / Env
- **Where:** Invisible; logged `[hermes] renderer debugging on http://127.0.0.1:<port> — anything that can reach it can run code in the renderer. HERMES_DESKTOP_CDP_PORT=off to disable.`
- **What it does:** Opens a Chrome DevTools Protocol port on loopback for dev-server runs so the repo's CDP tooling (`scripts/eval.mjs`, `scripts/perf/lib/cdp.mjs`, `diag-*`/`probe-*`) can attach. Never in a packaged build.
- **How it works:** `resolveDevCdpPort({ env, isPackaged: IS_PACKAGED, devServer: DEV_SERVER })` (`electron/dev-cdp.ts:56+`), then `app.commandLine.appendSwitch('remote-debugging-port', String(port))` and `('remote-debugging-address', '127.0.0.1')` (`main.ts:502-504`). Closed reasons are `'packaged' | 'no-dev-server' | 'opted-out' | 'invalid-port'`, rendered by `describeDevCdpDecision(DEV_CDP)`.
- **Inputs / options:** `HERMES_DESKTOP_CDP_PORT` — a port number in 1024–65535, or one of `0` / `off` / `false` / `no` to opt out. Default port 9222.
- **Outputs / side effects:** A loopback CDP listener.
- **Config / env:** env `HERMES_DESKTOP_CDP_PORT`, `HERMES_DESKTOP_DEV_SERVER`, `HERMES_DESKTOP_IS_PACKAGED`.
- **Edge cases / guards:** Packaged wins over every env combination; the bind address is deliberately not configurable.
- **Rebuild notes:** Gate a debugger port on "packaged" first and only then on env; log the risk in plain language.

### `desktop.log` — rotating main-process log  `id: desktop-main.desktop-log`
- **Surface:** Desktop app / Core
- **Where:** `HERMES_HOME/logs/desktop.log` (next to `agent.log`, `errors.log`, `gateway.log`). Surfaced by **Open logs** in error cards, `hermesDesktop.revealLogs()`, `hermesDesktop.getRecentLogs()` and the CLI `hermes logs gui -f`.
- **What it does:** Records boot, backend output, update, SSH and crash lines from the Electron main process, with size bounds so a boot loop cannot fill the disk.
- **How it works:** Constants at `main.ts:851-872`: `DESKTOP_LOG_PATH`, `DESKTOP_LOG_FLUSH_MS = 120`, `DESKTOP_LOG_BUFFER_MAX_CHARS = 64 * 1024`, `DESKTOP_LOG_MAX_BYTES = 10 * 1024 * 1024`, `DESKTOP_LOG_BACKUP_COUNT = 3`, `DESKTOP_LOG_DISCARD_BYTES = DESKTOP_LOG_MAX_BYTES * 4`, `desktopLogBackupPath = n => \`${DESKTOP_LOG_PATH}.${n}\``. Functions: `planDesktopLogRotation(size)` (`:1508`), `rotateDesktopLogIfNeededSync` (`:1532`), `rotateDesktopLogIfNeededAsync` (`:1554`), `flushDesktopLogBufferSync` (`:1576`), `flushDesktopLogBufferAsync` (`:1593`), `scheduleDesktopLogFlush` (`:1614`), `rememberLog(chunk)` (`:1625`). Line formatting lives in `electron/desktop-log-line.ts` (`formatDesktopLogLine`). In-memory ring `hermesLog` (`main.ts:1484`) keeps the tail; `recentHermesLog()` (`:2727`) renders it into errors; `getRecentLogs` returns `{ path: DESKTOP_LOG_PATH, lines: hermesLog.slice(-200) }` (`:16820`).
- **Inputs / options:** IPC `hermes:logs:reveal` (opens the folder), `hermes:logs:recent`, `hermes:logs:renderer-error` (fire-and-forget renderer error-boundary report, formatted by `formatRendererBoundaryReport` in `electron/renderer-log.ts`).
- **Outputs / side effects:** `desktop.log`, `desktop.log.1`, `.2`, `.3`; anything above 40 MB is deleted outright rather than rotated (self-heals a disk a boot-looping build filled).
- **Config / env:** n/a
- **Edge cases / guards:** Buffered writes flushed every 120 ms; a synchronous flush runs in `before-quit` so a crash still lands the tail.
- **Rebuild notes:** Cascade rotation with a hard discard ceiling; a forensic log must be bounded *and* self-healing.

### Main-process crash forensics  `id: desktop-main.crash-forensics`
- **Surface:** Desktop app / Core
- **Where:** Invisible; lines `[main] Uncaught exception: <stack>` / `[main] Unhandled rejection: <stack>` in `desktop.log`.
- **What it does:** Writes main-process faults to `desktop.log` and flushes synchronously, so a fault is visible in a `hermes debug share` bundle instead of dying on a discarded stderr.
- **How it works:** `installCrashForensics({ flush, log, target = process })` registers `uncaughtException` and `unhandledRejection` listeners; `describeCrashReason(reason)` prefers `error.stack`, then `message`, then `name`, then `JSON.stringify`, then `String()` (`electron/crash-forensics.ts:26-58`).
- **Inputs / options:** n/a
- **Outputs / side effects:** Log lines + a synchronous flush.
- **Config / env:** n/a
- **Edge cases / guards:** Electron itself keeps the process alive for uncaught exceptions; this only adds the record.
- **Rebuild notes:** Always synchronously flush a fault record — the batched async flush may never run.

### Renderer crash / reload budget  `id: desktop-main.renderer-reload-budget`
- **Surface:** Desktop app
- **Where:** Invisible; guards every window (primary, secondary session, instance).
- **What it does:** Auto-reloads a crashed renderer a few times inside a rolling window, then stops so a deterministic startup crash cannot loop forever.
- **How it works:** `RENDERER_RELOAD_WINDOW_MS = 60_000` and `RENDERER_RELOAD_MAX = 3` (`main.ts:1442-1443`); the shared budget is applied by `installWindowRendererLifecycle` (`electron/window-renderer-lifecycle.ts`, 427 lines) which also reports the crash reason via `describeCrashReason`.
- **Inputs / options:** n/a
- **Outputs / side effects:** Window reloads; log lines; after the budget, an error page (`electron/renderer-load-error-page.ts` `loadRendererLoadErrorPage`).
- **Config / env:** n/a
- **Edge cases / guards:** Budget is process-wide, not per-window, so a crash loop anywhere is suppressed after the same budget.
- **Rebuild notes:** Bound automatic recovery, and show the failure once the budget is spent.

### Renderer bundle-missing guard  `id: desktop-main.renderer-bundle-guard`
- **Surface:** Desktop app
- **Where:** The window shows a load-error page instead of a blank white screen.
- **What it does:** Detects a packaged app whose renderer assets are missing/incomplete and renders an explanatory page.
- **How it works:** `missingRendererAssets` (`electron/renderer-bundle.ts`, 160 lines) is consulted by `resolveRendererIndex()` (`main.ts:4406`); `loadRendererLoadErrorPage` (`electron/renderer-load-error-page.ts`, 198 lines) paints the fallback. `resolveWebDist()` (`main.ts:4374`) resolves the web dashboard bundle passed to the backend as `HERMES_WEB_DIST`.
- **Inputs / options:** n/a
- **Outputs / side effects:** An inline data-URL page.
- **Config / env:** n/a
- **Edge cases / guards:** Dev-server runs load `HERMES_DESKTOP_DEV_SERVER` instead.
- **Rebuild notes:** Never let a missing bundle present as a blank window.

### Bundle-skew warning (new backend, old UI)  `id: desktop-main.bundle-skew`
- **Surface:** Desktop app
- **Where:** Surfaced by the renderer after a backend update — "Update desktop app" affordance.
- **What it does:** Detects that the running renderer bundle predates desktop-side commits present in the installed source tree (typical after `hermes update` from a terminal) and lets the UI say so.
- **How it works:** `detectBundleSkew(stamp, runGit, repoRoot)` runs `git rev-list --count <stampCommit>..HEAD -- apps/desktop` (`electron/bundle-skew.ts:63-84`); `> 0` ⇒ `{ desktopCommitsBehind, outOfSync: true }`. `detectRendererSkew()` (`main.ts:16923`) wires it to `INSTALL_STAMP` and `resolveUpdateRoot()`; `showAboutPanelFresh()` (`main.ts:16931`) surfaces it. Fail-quiet: no stamp, `source === 'fallback'`, `isFallbackCommit()` (all-zero commit), a non-zero git exit, or any throw all return `{ desktopCommitsBehind: null, outOfSync: false }`.
- **Inputs / options:** n/a
- **Outputs / side effects:** A boolean + count the renderer renders.
- **Config / env:** n/a
- **Edge cases / guards:** Scoped to `apps/desktop/` so agent-only commits never trigger it; must never false-positive.
- **Rebuild notes:** Stamp the UI bundle with its build commit; compare only the paths the bundle is built from.

### Spellchecker language seeding  `id: desktop-main.spellchecker`
- **Surface:** Desktop app
- **Where:** Right-click a misspelled word in any text field → the suggestion menu.
- **What it does:** Enables Chromium's spellchecker with the system locale (falling back to `en-US`), so Windows/Linux actually download a Hunspell dictionary.
- **How it works:** `configureSpellChecker()` (`main.ts:17432-17449`): reads `session.defaultSession.availableSpellCheckerLanguages`, picks the first of `[locale, locale.split('-')[0], 'en-US', 'en']` that is available, calls `setSpellCheckerLanguages([chosen])`.
- **Inputs / options:** `app.getLocale()`.
- **Outputs / side effects:** Dictionary download on Win/Linux.
- **Config / env:** n/a
- **Edge cases / guards:** macOS uses the native spellchecker and ignores the list; failure logs `Spellchecker setup failed: <message>` and continues.
- **Rebuild notes:** Chromium enables no language by default — you must set one.

### Quit confirmation while a turn is in flight  `id: desktop-main.quit-guard`
- **Surface:** Desktop app
- **Where:** Native modal on quit. Buttons (verbatim): **"Keep Running"**, **"Quit Anyway"**. Message: `Hermes is still working on 1 chat.` or `Hermes is still working on <N> chats.` Detail: a bullet list of up to 4 session titles (`• <title>`), then `• 1 more` / `• <N> more`, then `Quitting stops the agent mid-turn. Any work it has not finished writing is lost.`
- **What it does:** Asks before a quit kills a running agent turn.
- **How it works:** Renderers publish `hermes:active-work` (`{ titles, count }`); main normalizes with `normalizeActiveWork` and merges every window's report with `mergeActiveWork` (`electron/quit-guard.ts:26-64`); `quitPromptFor(work, quittingForHandoff)` builds the copy (`:80-107`, `MAX_LISTED = 4`). `heldQuitForActiveWork(event)` (`main.ts:17454-17495`) preventDefaults `before-quit` and shows `dialog.showMessageBox(parent, { buttons: ['Keep Running','Quit Anyway'], cancelId: 0, defaultId: 0, type: 'question', message, detail })`. Choosing index 1 sets `quitConfirmedWithActiveWork = true` and re-enters `app.quit()`.
- **Inputs / options:** IPC `hermes:active-work` payload `{ titles: string[], count: number }`; env `HERMES_DESKTOP_SKIP_QUIT_CONFIRM=1`.
- **Outputs / side effects:** Quit is either held or proceeds to the teardown chain.
- **Config / env:** env `HERMES_DESKTOP_SKIP_QUIT_CONFIRM`.
- **Edge cases / guards:** Never shown when `isQuittingForHandoff` (update/uninstall relaunch) — a modal there would strand the detached script waiting on the PID. A dialog that throws is converted into "quit anyway" so an unshowable dialog can never wedge the quit. `quitPromptOpen` prevents stacking prompts.
- **Rebuild notes:** Collect "am I busy" from every renderer, merge, and never let the confirmation block a self-replacement handoff.

### Ordered quit teardown  `id: desktop-main.before-quit-teardown`
- **Surface:** Desktop app / Core
- **Where:** Invisible; runs on every quit.
- **What it does:** Shuts down in a strict order so no backend, SSH tunnel, PTY, overlay window, installer or log write is orphaned.
- **How it works:** `app.on('before-quit', …)` (`main.ts:17496-17618`), in order: (1) `heldQuitForActiveWork`; (2) join in-flight managed remote updates/recoveries via `waitForManagedUpdateOperations` before anything else; (3) `sshBootstrapCoordinator.shutdown()`; (4) `backendShutdown.run()` (`backendQuitTeardownDone` latch); (5) tear down every SSH connection + coordinator promise, racing a 6 s ceiling then `sshBootstrapCoordinator.forceCleanupAll()`; (6) Windows: `writeSandboxMarker(markerAfterSuccessfulBoot(...))` when not sticky; (7) `closePetOverlay()`; (8) `wakeIndicatorController.close()`; (9) `hudSnapShortcut.dispose()` + destroy the HUD window directly (not `closeHudWindow()`, which would re-show the main window); (10) `closeQuickEntryWindow()` (also unregisters its global accelerator); (11) `bootstrapAbortController.abort()`; (12) clear the log flush timer + `flushDesktopLogBufferSync()`; (13) `closePreviewWatchers()`; (14) `terminalIpc.disposeAllTerminalSessions()` (before environment teardown, to avoid the node-pty#904 ThreadSafeFunction SIGABRT race); (15) `backendShutdown.run()` again.
- **Inputs / options:** n/a
- **Outputs / side effects:** Every child process, watcher and overlay released.
- **Config / env:** n/a
- **Edge cases / guards:** Each stage uses a `…Done` latch so the re-entrant `app.quit()` chain converges. `app.on('window-all-closed')` quits on non-darwin **or** when `isQuittingForHandoff` (`main.ts:17620-17630`), so an updater/uninstaller script is never left waiting for a PID that stays alive in the macOS Dock.
- **Rebuild notes:** Model quit as a re-entrant state machine with per-stage latches, not a single synchronous block.

### Power resume + battery state broadcast  `id: desktop-main.power-events`
- **Surface:** Desktop app
- **Where:** Invisible; drives the renderer's `onPowerResume` and `onBatteryChanged` callbacks.
- **What it does:** Tells every window when the machine wakes from sleep and when it flips between AC and battery, so renderers can re-dial sockets and slow their backstop polls.
- **How it works:** `registerPowerResumeListeners()` (`main.ts:6412`) subscribes to `powerMonitor` and re-broadcasts via `sendPowerResume()` (`:6371`) → `hermes:power-resume`; `broadcastBatteryState(next)` (`:6396`) → `hermes:power-battery`; `ipcMain.handle('hermes:power-battery:get', () => onBatteryPower === true)` (`:6394`). Resume also drives `revalidatePool()` (`:14289`), `redialPoolBackendAfterResume(poolKey)` (`:14302`), `revalidateSuspectPoolAfterResume()` (`:14323`) and `attachPowerResumeRemoteRevalidation` (`electron/remote-liveness.ts`).
- **Inputs / options:** n/a
- **Outputs / side effects:** IPC broadcasts; remote/pool revalidation.
- **Config / env:** n/a
- **Edge cases / guards:** `powerResumeRegistered` prevents double registration.
- **Rebuild notes:** Wake is the single most common cause of a dead socket — treat it as a first-class event that triggers revalidation, not just a notification.

### Keep computer awake  `id: desktop-main.keep-awake`
- **Surface:** Desktop app / Config
- **Where:** **Settings → Advanced → Keep computer awake**.
- **What it does:** Holds one machine-global power-save blocker so long/overnight agent runs are not interrupted by system sleep (the display may still dim).
- **How it works:** `createKeepAwake(powerSaveBlocker)` (`electron/power-save.ts:29-56`) with type `'prevent-app-suspension'`; the object is idempotent (`set(on)` returns the resulting state, `isActive()` re-checks `blocker.isStarted(id)`). Main holds it at `main.ts:16570`; the renderer mirrors its persisted preference via `ipcMain.on('hermes:keep-awake', …)` (`:16580`), persisted at `KEEP_AWAKE_CONFIG_PATH = <userData>/keep-awake.json` (`:16569`) and re-applied at ready via `keepAwake.set(readPersistedKeepAwake())` (`main.ts:17383`).
- **Inputs / options:** `hermesDesktop.setKeepAwake(on: boolean)`.
- **Outputs / side effects:** `<userData>/keep-awake.json`; a native blocker id.
- **Config / env:** n/a (device-local, not in config.yaml).
- **Edge cases / guards:** Electron auto-releases the blocker on quit. `prevent-display-sleep` is available in the module but not used.
- **Rebuild notes:** Keep exactly one blocker id in the main process; make `set()` idempotent so repeated IPC is free.

### Stream-aware background throttling  `id: desktop-main.stream-throttle`
- **Surface:** Desktop app / Core
- **Where:** Invisible.
- **What it does:** Un-throttles chat windows while any turn is in flight (so a live answer keeps painting when blurred/occluded/minimized) and restores Chromium's default throttling 5 s after the last turn ends.
- **How it works:** `createStreamThrottle()` (`electron/stream-throttle.ts:52-137`), `RETHROTTLE_DELAY_MS = 5_000`. `register(win)` tracks a window and applies the current state; `update(busy)` rides the merged edge of the `hermes:active-work` reports (`updateStreamThrottleFromActiveWork()`, `main.ts:16431`). Applies `webContents.setBackgroundThrottling(!unthrottled)`.
- **Inputs / options:** derived from `hermes:active-work`.
- **Outputs / side effects:** Timer/rAF cadence of chat renderers.
- **Config / env:** n/a
- **Edge cases / guards:** Trailing delay covers the stream queue's final coalesced flush; destroyed windows are dropped from the set; a throw during teardown is swallowed.
- **Rebuild notes:** Never use a static `backgroundThrottling: false` — it pins `visibilityState` and makes every gated timer always-on.

### Cross-window one-shot de-duplication  `id: desktop-main.event-dedupe`
- **Surface:** Desktop app / Core
- **Where:** Invisible; governs OS notifications and ambient cues (turn-end sound, spoken reply).
- **What it does:** Ensures N open windows produce exactly one notification/sound per backend event.
- **How it works:** `createEventDeduper(intervalMs = 1000)` (`electron/event-dedupe.ts`) returns `isDuplicate(key, now)`, self-evicting stale keys on every call. Two instances in main: `isDuplicateNotification` and `claimedAmbientCue` (`main.ts:16057-16058`). Ambient claim: `ipcMain.handle('hermes:ambient:claim', (_event, key) => !claimedAmbientCue(String(key ?? '')))` (`:16062`) — first caller gets `true`.
- **Inputs / options:** `hermesDesktop.claimAmbientCue(key)`.
- **Outputs / side effects:** boolean claim result.
- **Config / env:** n/a
- **Edge cases / guards:** Notification dedupe returns `true` (not `false`) for a duplicate so a "send test notification" probe stays honest — a notification *is* being shown, by the first caller.
- **Rebuild notes:** The main process is the only serial, shared place — put the claim there.

---

## 3. Backend lifecycle — resolution, spawn, ownership, readiness, pooling

### `HERMES_HOME` resolution  `id: desktop-main.hermes-home`
- **Surface:** Desktop app / Env / Core
- **Where:** Invisible; determines where config, sessions, `.env`, skills, and logs live. The same layout a CLI install uses, which is why the two are interchangeable.
- **What it does:** Picks the Hermes home directory the desktop app and the backend it spawns both use.
- **How it works:** `resolveHermesHome()` (`main.ts:756-793`), in order: (1) `process.env.HERMES_HOME` → `normalizeHermesHomeRoot()`; (2) `HERMES_DESKTOP_USER_DATA_DIR` → `<override>/hermes-home` (used by `test:desktop:fresh`); (3) Windows only — the live `HKCU\Environment` value read by `readWindowsUserEnvVar('HERMES_HOME')` (`electron/windows-user-env.ts`), because a GUI launched from Explorer inherits the login-time environment block and misses a post-login `setx` (#45471); (4) Windows with `LOCALAPPDATA` → `%LOCALAPPDATA%\hermes`, unless that directory does not exist and legacy `~/.hermes` does (then legacy wins, so no state is orphaned); (5) otherwise `~/.hermes`. `normalizeHermesHomeRoot` (`electron/backend-env.ts:106-119`) walks up out of a `profiles/<name>` path so a profile home resolves to the root. The value is exported as `HERMES_HOME` (`main.ts:795`) and pinned into every spawned backend's env.
- **Inputs / options:** env `HERMES_HOME`, `HERMES_DESKTOP_USER_DATA_DIR`, `LOCALAPPDATA`.
- **Outputs / side effects:** derived paths `ACTIVE_HERMES_ROOT = <home>/hermes-agent` (`:806`), `VENV_ROOT = <root>/venv` (`:808`), `BOOTSTRAP_COMPLETE_MARKER = <root>/.hermes-bootstrap-complete` (`:820`), `DESKTOP_LOG_PATH = <home>/logs/desktop.log`.
- **Config / env:** as above.
- **Edge cases / guards:** The value is set inline on every backend spawn (`HERMES_HOME` in the child env, `main.ts:12419`) because the desktop cannot reliably `setx`.
- **Rebuild notes:** Resolve the home once, pin it into every child, and read the OS's live user environment on Windows rather than the inherited block.

### Backend resolution ladder  `id: desktop-main.backend-resolution`
- **Surface:** Desktop app / Core
- **Where:** Invisible; the label appears in the boot overlay ("Using `<label>`") and `desktop.log`.
- **What it does:** Chooses which Hermes runtime the desktop launches as its headless backend, verifying each candidate before trusting it.
- **How it works:** `resolveHermesBackend(backendArgs)` (`main.ts:4637-4812`), six rungs in order:
  1. `HERMES_DESKTOP_HERMES_ROOT` — a developer checkout, honoured as-is when `isHermesSourceRoot()` passes; built by `createPythonBackend(root, label, args)` (`:4581`), label `Hermes source at <root>`.
  2. Development source: when `!IS_PACKAGED && isHermesSourceRoot(SOURCE_REPO_ROOT)` (`SOURCE_REPO_ROOT = path.resolve(APP_ROOT, '../..')`, `:667`).
  3. `ACTIVE_HERMES_ROOT` — the canonical managed install; gated on `activeRuntimeState().shouldUseActiveRuntime && !bootstrapRepairRequested`. A usable runtime is used even when the bootstrap marker is missing/stale (logging `[bootstrap] Active Hermes runtime at <root> is usable but the bootstrap marker is missing or stale; skipping first-run bootstrap.`). Built by `createActiveBackend(args)` (`:4617`) with `bootstrap: true`.
  4. An existing `hermes` on `PATH` (or `HERMES_DESKTOP_HERMES`), skipped entirely when `HERMES_DESKTOP_IGNORE_EXISTING=1`. Guards: `looksLikeDesktopAppBinary()` rejects the desktop app itself on PATH; `isWindowsBinaryPathInWsl()` rejects a Windows binary override under WSL; `unwrapWindowsVenvHermesCommand()` (`:2273`) unwraps a Windows venv `hermes.exe` shim into its interpreter; then `verifyHermesCli(cmd, { shell })` runs `<cmd> --version`. `shouldTrustHermesOverride(hermesOverride)` skips the probe for an explicit deployment override (the Nix wrapper). Label `existing Hermes CLI at <cmd>`.
  5. System Python with `hermes_cli` importable — `findSystemPython()` (`:2436`) then `canImportHermesCli(python)` which runs `python -c "import yaml; import dotenv; import hermes_cli.config"`. Label `installed hermes_cli module via <python>`.
  6. Sentinel `{ kind: 'bootstrap-needed', label: 'Hermes Agent not installed yet; bootstrap required', command: null, activeRoot, installStamp, isPackaged, platform }` — never a throw, so the GUI can drive the install.
- **Inputs / options:** env `HERMES_DESKTOP_HERMES_ROOT`, `HERMES_DESKTOP_HERMES`, `HERMES_DESKTOP_IGNORE_EXISTING`, `HERMES_PROBE_TIMEOUT_MS`; `backendArgs` from `serveBackendArgs(profile)`.
- **Outputs / side effects:** A backend descriptor `{ kind, label, command, args, env, root?, bootstrap, shell }`; log lines for every rejected rung.
- **Config / env:** `HERMES_PROBE_TIMEOUT_MS` (default 15 000 ms, clamped to ≤ 120 000; one automatic retry on timeout — `electron/backend-probes.ts:39-113`).
- **Edge cases / guards:** Each rejection is logged with the reason (`Ignoring existing Hermes CLI at …: --version probe failed; falling through to bootstrap.`, `Ignoring system Python …: hermes_cli is not importable; …`, `Ignoring desktop app executable on PATH …`, `Ignoring Windows Hermes override under WSL: …`). The step-4 unwrap is deliberately not re-run to avoid paying a second un-memoized probe timeout.
- **Rebuild notes:** Verify a candidate by running it, not by `existsSync`; fall through to a *recoverable* "not installed" state rather than throwing.

### `serve` vs legacy `dashboard --no-open`  `id: desktop-main.backend-subcommand`
- **Surface:** Desktop app / Core
- **Where:** Invisible.
- **What it does:** The desktop always wants `hermes serve` (headless), but falls back to `hermes dashboard --no-open` when the resolved runtime predates the `serve` subcommand — so an app update never outruns its backend.
- **How it works:** `serveBackendArgs(profile)` returns `[...(profile ? ['--profile', profile] : []), 'serve', '--host', '127.0.0.1', '--port', '0']` (`electron/backend-command.ts:18-22`). `backendSupportsServe(backend)` (`main.ts:2303`, memoized in `_serveSupportCache`) reads the runtime's `hermes_cli/subcommands/dashboard.py` and applies `sourceDeclaresServe(src)` = `/add_parser\(\s*["']serve["']/` — matched precisely so "server"/"start_server" cannot false-positive. `getBackendArgsForRuntime(backend)` (`main.ts:2363`) rewrites via `dashboardFallbackArgs(args)`, which replaces the `serve` token with `dashboard --no-open` while preserving `-m hermes_cli.main` and `--profile <name>`.
- **Inputs / options:** n/a
- **Outputs / side effects:** The child argv.
- **Config / env:** n/a
- **Edge cases / guards:** Both forms produce the same headless gateway. The ready line matcher accepts either announcement (see next entry).
- **Rebuild notes:** Detect the capability from the runtime's own source, not from a version string.

### Ephemeral-port ready announcement  `id: desktop-main.backend-ready-announce`
- **Surface:** Desktop app / Core
- **Where:** Invisible; boot overlay step "Waiting for Hermes backend to launch".
- **What it does:** Discovers the port the spawned backend bound to, by watching its stdout (or a ready file) for the announcement uvicorn prints after it binds.
- **How it works:** `waitForDashboardPortAnnouncement(child, { describeOutputTail, readyFile, timeoutMs })` (`electron/backend-ready.ts:187-204`). Regex `/^HERMES_(?:BACKEND|DASHBOARD)_READY port=(\d+)/m` accepts both the new `serve` and legacy `dashboard` announcements (`:6`). Two strategies: stdout line scan (`waitForDashboardPort`) or a JSON ready file polled every 50 ms (`waitForDashboardReadyFile` + `readDashboardReadyFile`), selected by `options.readyFile`. Ready file path minted by `makeDashboardReadyFile()` (`main.ts:2653`) and passed to the child as `HERMES_DESKTOP_READY_FILE`; unlinked after the port is read (`main.ts:12559`).
- **Inputs / options:** env `HERMES_DESKTOP_PORT_ANNOUNCE_TIMEOUT_MS` — overrides the deadline, clamped to a floor of `MIN_PORT_ANNOUNCE_TIMEOUT_MS = 45_000`; default `DEFAULT_PORT_ANNOUNCE_TIMEOUT_MS = 90_000`.
- **Outputs / side effects:** The resolved port; rejections `Hermes backend: exited before port announcement (<signal|code>)<output tail>` or `Timed out waiting for Hermes backend port announcement (<ms>ms)`.
- **Config / env:** env `HERMES_DESKTOP_PORT_ANNOUNCE_TIMEOUT_MS`.
- **Edge cases / guards:** A single `cleanup()` removes data/exit/error/timeout listeners on every terminal path so repeated spawns cannot leak listener slots. The generous default exists because the clock starts before uvicorn binds and Windows AV scans every fresh `.pyc` (#50209).
- **Rebuild notes:** Bind `--port 0` and have the child announce; never guess a port or poll a fixed one.

### Backend output tail (crash forensics at spawn)  `id: desktop-main.backend-output-tail`
- **Surface:** Desktop app / Core
- **Where:** Appears appended to boot-failure messages: `\nRecent backend output:\n<tail>`.
- **What it does:** Buffers the last 8 KiB of the backend child's combined stdout+stderr from the instant of spawn, so an early crash's real traceback survives into the error the user sees.
- **How it works:** `createBackendOutputTail(limit = DEFAULT_OUTPUT_TAIL_LIMIT /* 8192 */)` (`electron/backend-claim.ts:162-196`) with `attach(child)`, `append(chunk)`, `text()`, `describe()`. Attached before the claim and before the READY wait (`main.ts:12492-12493`), because `rememberLog` attaches later and would miss pre-claim output.
- **Inputs / options:** `limit`.
- **Outputs / side effects:** Error message suffixes.
- **Config / env:** n/a
- **Edge cases / guards:** Ring-buffered — memory is bounded regardless of how noisy the child is.
- **Rebuild notes:** Attach the tail at spawn, not after the handshake.

### Backend ownership record + spawn nonce  `id: desktop-main.backend-ownership`
- **Surface:** Desktop app / Core
- **Where:** `<userData>/backend-ownership.json` (mode 0600). Corrupt file is parked at `backend-ownership.json.corrupt`.
- **What it does:** Records exactly which OS processes this desktop install spawned as backends, so orphans from a previous crash can be reaped and a live instance's backends are never killed.
- **How it works:** `createBackendOwnership({ matchesIdentity, matchesParent, stop, store })` (`main.ts:3388`, implementation `electron/backend-ownership.ts`, 309 lines). Each record carries `{ command, nonce, pid, profile, startMarker, parentPid, parentStartMarker }`. Written atomically: temp file `${path}.<pid>.tmp` mode 0600 then `renameSync` (`writeBackendOwnership`, `main.ts:3250-3268`). Identity matching layers three checks: `processIdentityMatches(identity)` (start marker or, for a degraded PID-only marker, `process.kill(pid, 0)` with `ESRCH`/`ENOENT` → false, `EPERM` → true) → `backendCommandForPid(pid)` (`ps -p <pid> -o command=` / `Get-CimInstance Win32_Process`) → `backendCommandMatches(command)`. `backendParentMatches(entry)` compares the recorded parent Electron PID + start marker so a live parent's backend is never reaped (#87295). The spawn nonce is 16 random bytes hex (`crypto.randomBytes(16).toString('hex')`, `main.ts:12405`) and is exported into the child as part of `parentWatchdogEnv`.
- **Inputs / options:** n/a
- **Outputs / side effects:** `backend-ownership.json`; SIGTERM/SIGKILL or `taskkill /T /F` on reaped PIDs; log `Reaped orphaned desktop backend PID(s): <list>`.
- **Config / env:** n/a
- **Edge cases / guards:** A corrupt ownership file is *quarantined*, not rewritten, because its records are the only pointer to still-running backends (#89298). `stopOwnedBackend(identity)` re-validates identity immediately before escalating from SIGTERM (POSIX group kill `process.kill(-pid, …)`) to SIGKILL after 1500 ms, so PID reuse can never target a replacement; it throws `Backend PID <pid> did not stop cleanly.` when the process survives.
- **Rebuild notes:** Identity = PID + a start marker + the command line; anything less lets PID reuse kill an innocent process.

### Cross-platform process start marker  `id: desktop-main.start-marker`
- **Surface:** Core
- **Where:** Invisible.
- **What it does:** Produces a value that changes when a PID is reused, so `pid + marker` identifies one specific process incarnation.
- **How it works:** `processStartMarker(pid)` (`electron/backend-claim.ts:44-95`): Linux reads field 19 (`starttime`) of `/proc/<pid>/stat` after the last `)` → `linux:<ticks>`; Windows first tries `electronProcessStartMarker(pid, process.pid, process.getCreationTime?.())` → `winms:<ms>` for its own PID, else `powershell.exe -NoProfile -NonInteractive -Command "$p = Get-Process -Id <pid> -ErrorAction Stop; $p.StartTime.ToUniversalTime().Ticks"` with a 30 000 ms budget (PS 5.1 cold starts run 2.4–8 s, #87169) → `win:<ticks>`; other POSIX runs `ps -p <pid> -o lstart=` → `ps:<value>`. `execText(command, args, { timeout = 3000 })` (`:26`) is the shared exec helper, wrapped in `hiddenWindowsChildOptions`.
- **Inputs / options:** `pid`.
- **Outputs / side effects:** none.
- **Config / env:** n/a
- **Edge cases / guards:** Throws on a malformed/absent marker; callers convert with `probeStartMarker(pid)` into `{ ok: true, startMarker } | { ok: false, reason }`.
- **Rebuild notes:** Never identify a process by PID alone.

### Claim policy: degrade, never kill a healthy backend  `id: desktop-main.claim-decision`
- **Surface:** Desktop app / Core
- **Where:** `desktop.log` warning `WARNING: process start marker probe failed for live Hermes backend PID <pid>; claiming with PID-only identity instead of stopping it: <reason>`.
- **What it does:** Decides what to do when the identity probe of a freshly spawned backend fails: degrade to PID-only identity if the child is alive, fail closed only if it actually died.
- **How it works:** `claimDecision(childAlive, probe)` (`electron/backend-claim.ts:139-147`) → `{action:'claim'|'degrade'|'fail'}`. `pidOnlyStartMarker(pid)` = `pid-only:<pid>` and `isPidOnlyStartMarker()` (`:119-125`). Applied by `claimBackendChild(child, command, profile, nonce, outputTail)` (`main.ts:3428-3468`): on `fail` it stops the child, waits for exit, and throws `Hermes backend (PID <pid>) died before its identity could be recorded: <reason><output tail>`; a persist failure throws `Could not persist ownership for the Hermes backend: <message><output tail>`. `releaseBackendChild(child)` (`:3483`) releases the record on exit.
- **Inputs / options:** n/a
- **Outputs / side effects:** An ownership record on the child as `child.hermesBackendIdentity`.
- **Config / env:** n/a
- **Edge cases / guards:** History (#93608): hard-failing on any probe error made a PowerShell timeout kill a healthy backend, the renderer "repaired" by respawning, and the next timeout killed that one too.
- **Rebuild notes:** A flaky identity probe must never be a reason to kill a working process.

### Orphan reap on boot  `id: desktop-main.orphan-reap`
- **Surface:** Desktop app / Core
- **Where:** Invisible; log `Reaped orphaned desktop backend PID(s): …`.
- **What it does:** On first backend start of a process, kills backends recorded by a previous desktop instance whose parent Electron is gone.
- **How it works:** `reapOrphanedBackendsOnce()` (`main.ts:3497-3529`) memoizes `backendOwnership.reapOrphans()` in `backendOrphanReapPromise`; a rejection clears the memo so the next attempt retries. Called from `startHermes()` (`:12266`) and `spawnPoolBackend()` (`:11964`).
- **Inputs / options:** n/a
- **Outputs / side effects:** Killed PIDs; rewritten ownership file.
- **Config / env:** n/a
- **Edge cases / guards:** Never runs on a non-primary instance. A record whose parent is *alive* is skipped. Records that predate parent tracking (`parentPid`/`parentStartMarker` absent) fall back to the legacy orphan rule (`backendParentMatches` returns `undefined`).
- **Rebuild notes:** Reap on the way in, not on the way out — a crash never gets to run cleanup.

### Parent-watchdog environment for the backend child  `id: desktop-main.parent-watchdog-env`
- **Surface:** Env / Core
- **Where:** Invisible; env of every spawned backend.
- **What it does:** Gives the Python backend the exact identity of its parent Electron so it can self-exit after an unclean desktop death without mistaking a reused PID for its owner.
- **How it works:** `parentWatchdogEnv(pid, startMarker, nonce)` (`electron/parent-process-identity.ts:80-104`) emits `HERMES_PARENT_PID`, and — when the marker probe succeeded — `HERMES_PARENT_START_MARKER` and `HERMES_PARENT_NONCE` atomically. Always emits `HERMES_SPAWN = spawnTag(pid, startMarker)` = `v1:-:serve:<pid>:<create-seconds|->` mirroring `hermes_cli/process_identity.py`. `createParentStartMarkerResolver({ load, onError })` (`:71`) caches a successful marker and lets a transient failure retry; on failure it logs `Could not resolve the Desktop process start marker; starting the backend with PID-only parent tracking: <detail>`.
- **Inputs / options:** n/a
- **Outputs / side effects:** Child environment variables.
- **Config / env:** env `HERMES_PARENT_PID`, `HERMES_PARENT_START_MARKER`, `HERMES_PARENT_NONCE`, `HERMES_SPAWN`.
- **Edge cases / guards:** Throws when `pid` is not a positive integer, or when a non-null marker is paired with an empty nonce.
- **Rebuild notes:** Pass identity down, not just a PID; make the child able to notice it has been orphaned.

### Backend spawn environment  `id: desktop-main.backend-env`
- **Surface:** Env / Core
- **Where:** Invisible.
- **What it does:** Builds the `PATH`, `PYTHONPATH` and UTF-8 settings the spawned backend needs so it can find Hermes-managed Node, the venv, and the user's CLI tools.
- **How it works:** `buildDesktopBackendEnv({ hermesHome, pythonPathEntries, venvRoot, currentEnv, platform, pathModule })` (`electron/backend-env.ts:121-150`) returns `{ PYTHONPATH, PYTHONUTF8, [PATH-key]: … }`. `buildDesktopBackendPath` (`:91-104`) orders: Hermes-managed Node dirs → venv `bin`/`Scripts` → the current PATH → POSIX sane entries. `hermesManagedNodePathEntries(hermesHome)` (`:77-89`) emits **both** layouts on every platform (`<home>/node` and `<home>/node/bin`), leading with the platform-native one — mirrors `iter_hermes_node_dirs()` in `hermes_constants.py`. `POSIX_SANE_PATH_ENTRIES` = `/opt/homebrew/bin`, `/opt/homebrew/sbin`, `/usr/local/sbin`, `/usr/local/bin`, `/usr/sbin`, `/usr/bin`, `/sbin`, `/bin` (`:6-15`). `pathEnvKey()` finds the case-correct `PATH` key on Windows. `PYTHONUTF8` defaults to `'1'` (user's explicit setting wins) so pre-import tracebacks decode correctly on GBK/cp1252 Windows locales.
- **Inputs / options:** n/a
- **Outputs / side effects:** Child env.
- **Config / env:** env `PYTHONPATH`, `PYTHONUTF8`, `PATH`.
- **Edge cases / guards:** Duplicate PATH entries are removed in first-seen order by `appendUniquePathEntries`.
- **Rebuild notes:** Emit both plausible layouts of your managed runtime dir; a GUI-launched app has a hostile PATH.

### Login-shell PATH merge  `id: desktop-main.login-shell-path`
- **Surface:** Desktop app / Platform:macOS / Platform:Linux
- **Where:** Invisible; log `[env] merged login-shell PATH into process.env for backend spawn` or `[env] login-shell PATH resolution unavailable (<reason>); keeping inherited PATH`.
- **What it does:** Runs the user's shell once as an interactive login shell and merges its `$PATH` into `process.env`, so nvm/pyenv/asdf shims, `~/.local/bin`, `~/.cargo/bin` and nix profiles are visible to the backend and to the Electron-side resolvers.
- **How it works:** `ensureLoginShellPath()` (`electron/shell-path.ts`, 187 lines): shell from `$SHELL`, else `/bin/zsh` on darwin / `/bin/bash` elsewhere; runs `printf '%s' "__HERMES_LOGIN_PATH_START__${PATH}__HERMES_LOGIN_PATH_END__"`; `extractSentinelPath` uses the **last** start marker so a profile that echoes the environment cannot poison the capture; `ATTEMPT_TIMEOUT_MS = 5000`; login-shell entries first, current-only entries appended. Single-flight, warmed at `app.whenReady()` (`main.ts:17335`) and awaited in `startHermes()` (`:12352`).
- **Inputs / options:** env `SHELL`.
- **Outputs / side effects:** `process.env.PATH` mutated.
- **Config / env:** env `SHELL`.
- **Edge cases / guards:** Windows returns reason `win32`; an unchanged PATH returns `unchanged`; any failure leaves PATH untouched — a broken profile must never block startup.
- **Rebuild notes:** Sentinel-wrap the capture; profile banners will otherwise corrupt it.

### Primary backend startup (`startHermes`)  `id: desktop-main.start-hermes`
- **Surface:** Desktop app / Core
- **Where:** Boot overlay progress steps (verbatim messages): `Resolving Hermes backend` (8%), `Connecting to remote Hermes backend at <url>` (24%), `Using <label>` (32%) / `Resolving Hermes runtime` (28%), `Starting Hermes backend via <label>` (84%), `Waiting for Hermes backend to launch` (86%), `Waiting for Hermes backend to become ready` (90%), `Hermes backend is ready. Finalizing desktop startup` (94%) / `Remote Hermes backend is ready` (94%).
- **What it does:** Starts (or attaches to) the one backend the primary window talks to, and returns its connection descriptor.
- **How it works:** `startHermes()` (`main.ts:12253-12700`). Sequence: primary-instance check → `reapOrphanedBackendsOnce()` → latched-failure short circuits (`bootstrapFailure`, `backendStartFailure`, `remoteReauthFailure`) → `BOOT_FAKE_ERROR` E2E hook → reuse an existing `backendConnectionState.getPromise()` → `startAttempt()` generation token → `setActiveGatewayProfile(primaryProfile)` → `ensureLoginShellPath()` → mint `token = crypto.randomBytes(32).toString('base64url')` → `backendArgs = ['serve','--host','127.0.0.1','--port','0']` with `--profile <name>` unshifted when `readActiveDesktopProfile()` is set → `runPrimaryBackendStartup({ connectRemote, ensureLocalRuntime: ensureRuntime, prepareLocalBackend, resolveRemote, waitForDecision: waitForFirstRunSetupChoice, waitForLocalStart: waitForUpdateToFinish })` (`electron/primary-backend-startup.ts`). Local path: `getBackendArgsForRuntime` → `resolveHermesCwd()` → `resolveWebDist()` → optional ready file → `spawn(backend.command, backend.args, hiddenWindowsChildOptions({ cwd, env, shell, stdio: ['ignore','pipe','pipe'] }))` → output tail → `claimBackendChild` → `backendConnectionState.attachProcess` → stdout/stderr piped to `rememberLog` → `waitForDashboardPortAnnouncement` raced against a `backendStartFailed` promise → `baseUrl = http://127.0.0.1:<port>` → `waitForHermes(baseUrl, token)` → `adoptServedDashboardToken(...)` → `probeGatewayWebSocket(wsUrl)` → returns `{ baseUrl, mode:'local', source:'local', authMode:'token', token, wsUrl, logs, ...getWindowState() }`. Child env additions: `HERMES_HOME`, `...backend.env`, `TERMINAL_CWD`, `HERMES_DASHBOARD_SESSION_TOKEN`, `HERMES_DESKTOP='1'` (makes the backend run the cron scheduler tick loop), the parent-watchdog vars, `HERMES_WEB_DIST`, optional `HERMES_DESKTOP_READY_FILE`.
- **Inputs / options:** none directly; driven by config/registry state.
- **Outputs / side effects:** A live backend child; boot-progress broadcasts; `hermes:backend-exit` events; log lines `Starting Hermes backend via <label>`, `Hermes backend exited (<signal|code>)`, `Hermes backend failed to start: <message>`.
- **Config / env:** env `HERMES_DESKTOP_BOOT_FAKE`, `HERMES_DESKTOP_BOOT_FAKE_ERROR`, `HERMES_DESKTOP_BOOT_FAKE_STEP_MS` (default 650 ms, floor 120 ms).
- **Edge cases / guards:** Every async boundary re-checks `backendConnectionState.isCurrentAttempt(attempt)` and throws `Hermes backend start was superseded by a newer connection attempt.` A superseded process is stopped, awaited and released. Remote path disables WSL path bridging for that profile (`setWslBridgeProfileState(primaryProfile, false)`, #66433). On success `bootstrapRepairAttempt = 0`.
- **Rebuild notes:** Generation-token every start attempt; a late success from a superseded attempt must never publish a descriptor.

### Boot-failure classification and latching  `id: desktop-main.boot-failure-latch`
- **Surface:** Desktop app
- **Where:** The boot-failure overlay, its **Retry** / **Sign in** actions, and the renderer's self-heal loop.
- **What it does:** Decides which boot failures are transient (retry with backoff) and which latch until the user acts.
- **How it works:** `electron/backend-start-failure.ts` exports `shouldLatchBackendStartFailure({ attemptedRemote })` (local failures latch, remote ones do not), `shouldLatchHostKeyChangedFailure({ attemptedRemote, isReauth, isHostKeyChanged })`, `shouldLatchRemoteReauthFailure({ attemptedRemote, isReauth })`, `isRetryableRemoteBootFailure({ attemptedRemote, isReauth, isHostKeyChanged })`, `isHostKeyChangedBootFailure(error)`. Applied in `startHermes`'s catch (`main.ts:12626-12695`), which also forwards `isCloudBackendDown` and an integer `statusCode` through the boot-progress payload so the renderer keys on structure rather than message text (#85335).
- **Inputs / options:** n/a
- **Outputs / side effects:** `bootProgressState` fields `error`, `message`, `phase: 'backend.error'`, `retryable`, `running: false`, `statusCode`, `isCloudBackendDown`.
- **Config / env:** n/a
- **Edge cases / guards:** A host-key **change** is the one terminal remote failure (one bundle showed 157 consecutive doomed boots over 2.5 h); a confirmed reauth rejection latches separately so the overlay keeps its "Sign in" button.
- **Rebuild notes:** Latch only failures that cannot self-heal; carry structured metadata across the IPC boundary instead of re-parsing messages.

### Backend connection generation state  `id: desktop-main.backend-connection-state`
- **Surface:** Core
- **Where:** Invisible.
- **What it does:** Makes concurrent/overlapping backend start attempts safe: only the current generation may publish a process or a connection promise.
- **How it works:** `createBackendConnectionState<TProcess, TConnection>()` (`electron/backend-connection-state.ts`) with `startAttempt()`, `setPromise(attempt, p)`, `isCurrentAttempt(attempt)`, `attachProcess(attempt, proc)`, `clearForCurrentProcess(owner)`, `clearPromiseForAttempt(attempt)`, `getProcess()`, `getPromise()`, `invalidate()` (bumps the generation and returns the process to stop). Instance at `main.ts:1381`.
- **Inputs / options:** n/a
- **Outputs / side effects:** none.
- **Config / env:** n/a
- **Edge cases / guards:** `clearForCurrentProcess` compares both generation and process identity, so a stale exit handler cannot clear a newer process.
- **Rebuild notes:** Generation counters beat cancellation tokens for "last write wins" lifecycles.

### Single-owner dial claim  `id: desktop-main.backend-dial-claim`
- **Surface:** Core
- **Where:** Invisible.
- **What it does:** Deduplicates concurrent dial/reconnect requests for the same `(connectionId, profile)` across *windows*, so two windows waking at once cannot bootstrap duplicate remote backends.
- **How it works:** `class BackendDialClaims` (`electron/backend-dial-claim.ts:20-58`) with `inFlight(key)` and `run(key, dial)`. Keys come from `backendScopeKey(connectionId, profile)`. The claim exists only while its promise is unsettled — both outcomes release it, so a failed dial is never cached. A synchronously throwing `dial()` is converted into a rejection of the claim so it cannot bypass the seam. Instance `backendDialClaims` (`main.ts:1390`).
- **Inputs / options:** n/a
- **Outputs / side effects:** none.
- **Config / env:** n/a
- **Edge cases / guards:** The renderer's own in-flight lock only dedupes inside one window; Electron main is the single owner.
- **Rebuild notes:** Put cross-window mutual exclusion in the process every window shares.

### Per-profile backend pool  `id: desktop-main.backend-pool`
- **Surface:** Desktop app / Core
- **Where:** Invisible; enables concurrent multi-profile and multi-gateway sessions.
- **What it does:** Keeps up to N extra backends alive — one per `(connection, profile)` scope actively being chatted through — so background agents keep streaming while you look at another profile or gateway.
- **How it works:** `backendPool: Map<string, { process, port, token, connectionPromise, lastActiveAt }>` (`main.ts:1400`). Scope keys are built by `backendScopeKey(connectionId, profile)` / parsed by `parseBackendScopeKey` (`electron/connection-registry.ts`). `ensureBackend(profile)` (`main.ts:10988`) and `ensureRegistryBackend(connectionId, profile, correlationId)` (`:11070`) resolve or create entries; `connectRegistryBackend(...)` (`:11303`) dials one; `spawnPoolBackend(profile, entry, { forceLocal, poolKey })` (`:11961`) spawns the local child (mirroring `startHermes`'s local half minus boot-progress, bootstrap and remote handling). Descriptor-only entries (`entry.process === null`) represent remote/cloud sources.
- **Inputs / options:** env `HERMES_DESKTOP_POOL_MAX` (default 3, min 1), `HERMES_DESKTOP_POOL_IDLE_MS` (default 600 000, min 60 000), `HERMES_DESKTOP_POOL_KEEPALIVE_FRESH_MS` (default 240 000, min 120 000).
- **Outputs / side effects:** Extra `hermes serve` children; ownership records for each.
- **Config / env:** the three env vars above.
- **Edge cases / guards:** `profileDeletionGate.assertCanStart(profile)` refuses to spawn a backend for a profile being deleted (whose `ensure_hermes_home()` would recreate the directory).
- **Rebuild notes:** Key the pool by `(connection, profile)`, not by profile alone.

### Pool LRU eviction  `id: desktop-main.pool-lru`
- **Surface:** Core
- **Where:** Log `Evicting idle profile backend "<key>" (LRU cap <N>)`.
- **What it does:** Keeps the pool small by stopping the least-recently-used *spawned* backends over the cap — but never one that still has a live renderer socket.
- **How it works:** `evictLruPoolBackends(keep)` (`main.ts:1919-1926`) delegates to `selectPoolEvictions(entries, keep, now, POOL_KEEPALIVE_FRESH_MS)` (`electron/pool-eviction.ts`). Process-less descriptor entries are excluded from the cap entirely — counting them let a roster refresh across N remote connections evict a real local backend.
- **Inputs / options:** `HERMES_DESKTOP_POOL_MAX`, `HERMES_DESKTOP_POOL_KEEPALIVE_FRESH_MS`.
- **Outputs / side effects:** Stopped children.
- **Config / env:** as above.
- **Edge cases / guards:** The keepalive-fresh window is deliberately ≫ the renderer's 60 s ping cadence: 3× ping + 60 s headroom absorbs two missed pings and a WSL2 9p IPC stall (#95189, where the previous 90 s window killed the active profile's backend ~700×/day).
- **Rebuild notes:** "Over the cap" must never beat "actively in use".

### Pool idle reaper  `id: desktop-main.pool-idle-reaper`
- **Surface:** Core
- **Where:** Log `Reaping idle profile backend "<key>" (idle > <N>s)`.
- **What it does:** Tears down pooled backends that have gone untouched past the idle ceiling, then stops itself when the pool empties.
- **How it works:** `startPoolIdleReaper()` (`main.ts:1928-1959`) — a 60 s `setInterval` (unref'd) that stops any entry with `now - lastActiveAt > POOL_IDLE_MS` and clears itself when `backendPool.size === 0`.
- **Inputs / options:** `HERMES_DESKTOP_POOL_IDLE_MS`.
- **Outputs / side effects:** Stopped children.
- **Config / env:** as above.
- **Edge cases / guards:** Descriptor-only entries are reclaimed here (they are exempt from the LRU cap).
- **Rebuild notes:** Unref the timer so it cannot hold the process alive.

### Backend keepalive touch  `id: desktop-main.backend-touch`
- **Surface:** Core / Desktop app
- **Where:** `window.hermesDesktop.touchBackend(profile)`; IPC `hermes:backend:touch`.
- **What it does:** Renderers ping every open profile every ~60 s so the pool knows those backends are in use.
- **How it works:** `ipcMain.handle('hermes:backend:touch', …)` → `touchPoolBackend(profile)` (`main.ts:11897-11907`), which tries each key from `poolTouchKeys(profile)` (`electron/pool-touch-scope.ts`) and stamps `lastActiveAt = Date.now()` on the first match. Returns `{ ok: true }`.
- **Inputs / options:** `profile` (string or a `{ connectionId, profile }`-derived scope key).
- **Outputs / side effects:** `lastActiveAt` update.
- **Config / env:** n/a
- **Edge cases / guards:** Only the first matching key is touched.
- **Rebuild notes:** Let the consumer declare liveness; the owner should not have to guess.

### Pool teardown helpers  `id: desktop-main.pool-teardown`
- **Surface:** Core
- **Where:** Invisible.
- **What it does:** Stops one pooled backend, one profile's every local pool key, or all of them, waiting for actual exit.
- **How it works:** `createPoolStopper({ pool, stopChild, waitForExit })` (`electron/pool-stop.ts`) → `poolStopper` (`main.ts:2164`); `stopPoolBackend(profile)`, `teardownPoolBackendAndWait(profile)` (fans out over `localProfilePoolKeys(profile)`), `stopAllPoolBackends()`. `createBackendShutdownCoordinator(fn)` (`electron/backend-ownership.ts`) wraps the whole shutdown: invalidate the primary, stop it, stop the pool, clear the idle reaper, await every exit (`main.ts:12182-12194`). `exitAfterBackendShutdown(code)` (`:12196`) runs it then `app.exit(code)`.
- **Inputs / options:** n/a
- **Outputs / side effects:** Killed children.
- **Config / env:** n/a
- **Edge cases / guards:** `waitForBackendExit(child, timeoutMs = 5000)` (`main.ts:10904`) bounds the wait.
- **Rebuild notes:** Always *await* the exit; "sent SIGTERM" is not "stopped".

### Platform-correct child kill  `id: desktop-main.stop-backend-child`
- **Surface:** Core / Platform:Windows / Platform:POSIX
- **Where:** Invisible.
- **What it does:** Kills a backend and everything it spawned (MCP servers, PTYs, the gateway) using the right mechanism per platform.
- **How it works:** `stopBackendChild(child, deps)` (`electron/backend-child.ts:58-83`): Windows → `forceKillProcessTree(pid)` = `taskkill /PID <pid> /T /F` (`main.ts:3233-3249`); POSIX → `process.kill(-pid, 'SIGTERM')` (the backend is spawned with `start_new_session=True`, so pgid == pid), falling back to `child.kill('SIGTERM')`. `stopBackendTreesForUpdate(primary, deps)` (`:94-103`) tree-kills the primary root **before** signalling anything else, because a root that exits first makes its grandchildren un-enumerable on Windows.
- **Inputs / options:** n/a
- **Outputs / side effects:** Terminated process trees.
- **Config / env:** n/a
- **Edge cases / guards:** No-ops on a falsy/already-killed child or a throwing kill.
- **Rebuild notes:** `child.kill()` reaches one process; a supervised agent needs the whole group/tree.

### Windows pre-update release gate  `id: desktop-main.release-gate`
- **Surface:** Core / Platform:Windows
- **Where:** Log `[<tag>] venv shim unlocked and <N> signalled backend PID(s) exited; safe to proceed`.
- **What it does:** After tree-killing its own backends, waits until the venv `hermes.exe` shim is genuinely unlocked **and** every signalled PID has left the process table, before handing off to the updater or uninstaller.
- **How it works:** `waitForBackendRelease(initialPids, deps, tag, deadlineMs = RELEASE_GATE_DEADLINE_MS /* 15000 */)` (`electron/backend-release-gate.ts:65-100`), polling every `RELEASE_GATE_POLL_MS = 300`. Deps: `isShimLocked` (real: an `O_RDWR` open attempt — `isShimLocked(shimPath)` at `main.ts:3199`), `isPidAlive` (`isPidAliveWindows`), `collectStragglerPids` (re-collected and re-killed each pass, because a supervised backend can respawn mid-teardown), `killProcessTree`, `sleep`, `now`, `log`. On deadline it falls back to the pre-#74805 criterion (shim unlocked alone) rather than inventing a new failure mode. Callers: `releaseBackendLockForUpdate(updateRoot)` (`main.ts:3531`) and `releaseBackendLock(updateRoot, tag)` (`:3545`, also used by the uninstaller with tag `uninstall`).
- **Inputs / options:** `initialPids`, `tag`, `deadlineMs`.
- **Outputs / side effects:** `{ unlocked, lingeringPids }`.
- **Config / env:** n/a
- **Edge cases / guards:** No-op off Windows. `venvHermesShimPath(updateRoot)` (`main.ts:3189`) locates the shim.
- **Rebuild notes:** `taskkill /T /F` returns when termination is *initiated*; gate on the process table actually draining.

### Readiness probe (`waitForHermes`)  `id: desktop-main.wait-for-hermes`
- **Surface:** Core
- **Where:** Boot step "Waiting for Hermes backend to become ready".
- **What it does:** Polls the backend until it answers a health probe with the right credentials for its auth mode.
- **How it works:** `waitForHermes(baseUrl, token, signal?, authMode?, headers)` (`main.ts:6180`) builds a probe with `buildReadinessHealthProbe(baseUrl, authMode, token)` (`:6149`) and delegates to `waitForHermesReady` (`electron/backend-health.ts`, 317 lines, which also exports `isReauthRequiredError`, `makeNousCloudBackendDownError`, `makeUnsignedOauthError`). Auth for the probe is chosen by `resolveReadinessProbeAuth` (`electron/native-auth-decisions.ts`) so the probe authenticates the same way the rest of the connection does — a credential-free probe against a gated gateway 401s forever and cannot distinguish a missing route from a rejected session. `gatewayAuthProviders(baseUrl, headers)` (`main.ts:6113`, cached in `gatewayAuthProvidersCache`) reads the advertised providers.
- **Inputs / options:** `baseUrl`, `token`, `AbortSignal`, `authMode`, `headers`.
- **Outputs / side effects:** Resolves when ready; throws a classified error otherwise.
- **Config / env:** n/a
- **Edge cases / guards:** Cloud-down errors carry `isCloudBackendDown`; reauth errors carry the flag `isReauthRequiredError` checks.
- **Rebuild notes:** The readiness probe must use production credentials, or it lies.

### Served-token adoption / foreign-backend refusal  `id: desktop-main.dashboard-token-adopt`
- **Surface:** Core
- **Where:** Log `[boot] dashboard served a different session token; using served token for WebSocket auth`; hard error `<label> exited and <baseUrl>/ is served by a process we did not spawn; refusing its session token.`
- **What it does:** Reads the session token the backend actually serves (from the injected `window.__HERMES_SESSION_TOKEN__` in its index HTML), adopts benign drift, and refuses a port squatter.
- **How it works:** `adoptServedDashboardToken(baseUrl, spawnToken, { childAlive, label, rememberLog, timeoutMs })` (`electron/dashboard-token.ts:83-100`) → `resolveServedDashboardToken` → `fetchPublicText(dashboardIndexUrl(baseUrl))` (`DEFAULT_TOKEN_FETCH_TIMEOUT_MS = 3000`, only `http:`/`https:` allowed) → `extractInjectedDashboardToken(html)` matching `/window\.__HERMES_SESSION_TOKEN__\s*=\s*("(?:\\.|[^"\\])*")/`. `isForeignBackendToken({ servedToken, spawnToken, childAlive })` — a differing token while our child is **dead** means a process we did not spawn satisfied the public readiness probe.
- **Inputs / options:** `childAlive` is a thunk so liveness is sampled *after* the fetch.
- **Outputs / side effects:** The token used for `/api/ws`.
- **Config / env:** n/a
- **Edge cases / guards:** A fetch failure logs `[boot] could not read served dashboard token (<label>): <message>` and keeps the spawn token.
- **Rebuild notes:** HTTP readiness alone does not prove *your* process answered; compare a secret you injected.

### WebSocket handshake probe  `id: desktop-main.ws-probe`
- **Surface:** Core
- **Where:** Error `Local Hermes backend is HTTP-reachable but the WebSocket (/api/ws) rejected the session token: <reason>`.
- **What it does:** Verifies the session token on `/api/ws` before declaring the backend ready, so an HTTP-healthy backend with a bad WS auth never reaches the chat UI.
- **How it works:** `probeGatewayWebSocket(wsUrl, { WebSocketImpl: globalThis.WebSocket })` (`electron/gateway-ws-probe.ts`, 237 lines), called at `main.ts:12578`. Also used by **Test** on a registered connection so a pass means chat will actually work.
- **Inputs / options:** `wsUrl`.
- **Outputs / side effects:** `{ ok, reason }`.
- **Config / env:** n/a
- **Edge cases / guards:** Distinguishes close-code classes so the message names the real cause.
- **Rebuild notes:** Probe the socket you will actually use, with the credential you will actually present.

### Active-runtime usability classification  `id: desktop-main.active-runtime-state`
- **Surface:** Core
- **Where:** Invisible; decides whether first-run bootstrap is skipped.
- **What it does:** Separates "did Desktop install this?" (marker provenance) from "can we launch it right now?" (runtime usability), so a CLI-created install is never forced into the first-run installer.
- **How it works:** `hasValidBootstrapMarker(marker, schemaVersion)` requires `schemaVersion === 1` and a `pinnedCommit` string ≥ 7 chars; `classifyActiveRuntime(marker, schemaVersion, runtimeUsable)` returns `{ hasValidMarker, shouldUseActiveRuntime, usabilityReason: 'usable'|'unusable' }` (`electron/active-runtime-state.ts`). Wired via `isActiveRuntimeUsable()` (`main.ts:4335`), `activeRuntimeState()` (`:4349`), `readBootstrapMarker()` (`:4326`), `writeBootstrapMarker(payload)` (`:4358`).
- **Inputs / options:** n/a
- **Outputs / side effects:** none.
- **Config / env:** n/a
- **Edge cases / guards:** Marker file lives *inside* `ACTIVE_HERMES_ROOT` so deleting the checkout also deletes the marker.
- **Rebuild notes:** Never let a bookkeeping file decide whether a working install works.

### Python / venv discovery  `id: desktop-main.python-discovery`
- **Surface:** Core
- **Where:** Invisible.
- **What it does:** Finds the interpreter to run `-m hermes_cli.main` with, and the venv whose site-packages belong on `PYTHONPATH`.
- **How it works:** `findPythonForRoot(root)` (`main.ts:4414`), `findSystemPython()` (`:2436`), `getVenvPython(venvRoot)` (`:2599`), `venvRootForPython(python, root)` (`:2614`) — which prevents mixing a `.venv` interpreter with a `venv` site-packages (a crash on the first native import). `getVenvSitePackagesEntries(venvRoot)` and `resolveVenvHermesCommand`, `buildPathExtCandidates`, `chooseUpdaterArgs` live in `electron/windows-hermes-path.ts` (293 lines). `findOnPath(command)` (`main.ts:2227`), `isCommandScript(command)` (`:2269`), `unpackedPathFor(filePath)` (`:2223`), `isHermesSourceRoot(root)` (`:2410`), `normalizeExecutablePathForCompare` (`:2367`), `looksLikeDesktopAppBinary` (`:2383`).
- **Inputs / options:** n/a
- **Outputs / side effects:** none.
- **Config / env:** n/a
- **Edge cases / guards:** On Windows a venv `python.exe` is preferred over a system one when it exists.
- **Rebuild notes:** The interpreter and the site-packages must come from the same venv.

### Working directory for the backend  `id: desktop-main.hermes-cwd`
- **Surface:** Config / Env / Desktop app
- **Where:** `hermes desktop --cwd <path>`; **Settings → Workspace → default project directory**; the file browser's initial directory.
- **What it does:** Picks the working directory the backend (and therefore new chat sessions) starts in.
- **How it works:** `resolveHermesCwd()` (`main.ts:4483`); `sanitizeWorkspaceCwd(cwd)` (`:4519`) rejects paths inside a packaged install (`isPackagedInstallPath(dir)` at `:4472`, and `isPackagedInstallPathUnderRoots` from `electron/workspace-cwd.ts`); `DEFAULT_PROJECT_DIR_CONFIG_FILENAME = 'project-dir.json'` with `readDefaultProjectDir()` / `writeDefaultProjectDir(dir)` (`:4543-4579`). IPC: `hermes:setting:defaultProjectDir:get|set|pick` and `hermes:workspace:sanitize`.
- **Inputs / options:** env `HERMES_DESKTOP_CWD`; `hermesDesktop.settings.getDefaultProjectDir()`, `.setDefaultProjectDir(dir)`, `.pickDefaultProjectDir()`; `hermesDesktop.sanitizeWorkspaceCwd(cwd)`.
- **Outputs / side effects:** `<userData>/project-dir.json`; child `cwd` and `TERMINAL_CWD`.
- **Config / env:** env `HERMES_DESKTOP_CWD`.
- **Edge cases / guards:** A cwd inside the app install is refused so sessions never write into a directory an update replaces.
- **Rebuild notes:** Sanitize the workspace root centrally; every surface (terminal, picker, backend) must agree.

### Desktop profile pin (`active-profile.json`)  `id: desktop-main.active-profile`
- **Surface:** Desktop app / Config
- **Where:** Profile rail / **⌘K → switch profile**; persisted per install.
- **What it does:** Records which Hermes profile the desktop launches its local backend as, pinned deterministically with `--profile`.
- **How it works:** `DESKTOP_PROFILE_CONFIG_PATH = <userData>/active-profile.json` (`main.ts:840`); `readActiveDesktopProfile()` (`:9289`), `writeActiveDesktopProfile(name)` (`:9305`). Validated against `PROFILE_NAME_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/` (`:843`), mirroring `hermes_cli.profiles._PROFILE_ID_RE`. `--profile <name>` wins over the sticky `~/.hermes/active_profile` file and resolves `HERMES_HOME` exactly like `hermes -p <name>`. IPC: `hermes:profile:get` → `{ profile }`, `hermes:profile:remember` (name), `hermes:profile:set` (name).
- **Inputs / options:** `hermesDesktop.profile.get()`, `.remember(name)`, `.set(name)`.
- **Outputs / side effects:** `<userData>/active-profile.json`; the next backend launch's argv.
- **Config / env:** n/a
- **Edge cases / guards:** Unset (null) preserves legacy behaviour: no `--profile` flag, backend honours `active_profile`/default.
- **Rebuild notes:** Pin the profile explicitly on the child's command line; sticky global files are ambiguous under concurrency.

### Profile delete routing  `id: desktop-main.profile-delete-routing`
- **Surface:** Core
- **Where:** Invisible; triggered by a profile-delete REST call passing through `hermes:api`.
- **What it does:** Tears the right backend down *before* the delete runs, so `ensure_hermes_home()` cannot recreate the directory that was just removed.
- **How it works:** `prepareProfileDeleteRequest(request)` (`main.ts:12210-12233`) → `profileNameFromDeleteRequest(request)` and `decideProfileDeleteAction(profile, { isDefaultProfile, isValidProfileName, primaryProfileKey })` (`electron/profile-delete-routing.ts`, 246 lines). Actions: `noop`; `teardown-primary` (writes `active-profile.json = 'default'`, then awaits `teardownPrimaryBackendAndWait()` **and** `teardownPoolBackendAndWait(profile)`); otherwise `teardownPoolBackendAndWait(profile)`. Same module exports `assertLocalProfileCanStart`, `dispatchConnectionScopedProfileDelete`, `localProfilePoolKeys`, `ProfileDeletionGate`, `resolveRouteProfile`.
- **Inputs / options:** the API request.
- **Outputs / side effects:** Backends stopped; the profile name returned so the caller skips `ensureBackend` for it.
- **Config / env:** n/a
- **Edge cases / guards:** `ProfileDeletionGate` blocks new spawns for a profile mid-delete.
- **Rebuild notes:** Order matters: stop the owner, then delete its state.

### Profile rename routing  `id: desktop-main.profile-rename-routing`
- **Surface:** Core
- **Where:** Invisible; triggered by a profile-rename REST call.
- **What it does:** Stops the affected backends, rewrites the desktop's pinned profile, restarts the primary backend and reloads the primary window so no surface keeps the old name.
- **How it works:** `prepareProfileRenameRequest(request)` (`main.ts:12235-12251`) → `prepareProfileRenameLifecycle(request, { isValidProfileName, primaryProfileKey, reloadPrimaryWindow, restartPrimaryBackend, teardownPoolBackendAndWait, teardownPrimaryBackendAndWait, writeActiveDesktopProfile })` and `profileRenameFromRequest` (`electron/profile-rename-routing.ts`, 138 lines).
- **Inputs / options:** the API request.
- **Outputs / side effects:** Backend restart + window reload.
- **Config / env:** n/a
- **Edge cases / guards:** Invalid names are rejected by `PROFILE_NAME_RE`.
- **Rebuild notes:** A rename is a delete+create for every cached scope key — reload rather than patch.

---

## 4. First-run bootstrap (installing the agent from the app)

### Boot-progress channel  `id: desktop-main.boot-progress`
- **Surface:** Desktop app
- **Where:** The startup overlay's progress bar and status line.
- **What it does:** Publishes a single monotonic `{ phase, message, progress, running, error, retryable, statusCode, isCloudBackendDown, fakeMode, timestamp }` snapshot from main to the renderer for the whole boot.
- **How it works:** `bootProgressState` (`main.ts:1492`); `updateBootProgress(update, { allowDecrease })` (`:2055-2081`) clamps `progress` to 0–100 with `clampBootProgress`, refuses to go backwards unless `allowDecrease`, mirrors `retryable` alongside `error`, logs `[boot] <message>` and calls `broadcastBootProgress()` → `hermes:boot-progress` on the main window. `advanceBootProgress(phase, message, progress)` (`:2083`) is the awaited wrapper that also sleeps `BOOT_FAKE_STEP_MS` in fake mode. Snapshot read: `ipcMain.handle('hermes:boot-progress:get', …)` (`:14572`). `resetBootProgressForReconnect()` (`:10819`).
- **Inputs / options:** `hermesDesktop.getBootProgress()`, `hermesDesktop.onBootProgress(cb)`.
- **Outputs / side effects:** IPC pushes + log lines.
- **Config / env:** env `HERMES_DESKTOP_BOOT_FAKE=1`, `HERMES_DESKTOP_BOOT_FAKE_ERROR=<message>`, `HERMES_DESKTOP_BOOT_FAKE_STEP_MS`.
- **Edge cases / guards:** Only the *main* window receives boot progress. Phases used: `backend.resolve`, `backend.remote`, `runtime.external`, `backend.runtime`, `runtime.ready`, `backend.spawn`, `backend.port`, `backend.wait`, `backend.ready`, `backend.error`, `bootstrap.choice`.
- **Rebuild notes:** One monotonic state object beats a stream of ad-hoc messages; make the snapshot queryable so a devtools reload recovers.

### First-run setup choice gate  `id: desktop-main.first-run-setup-gate`
- **Surface:** Desktop app
- **Where:** First-launch overlay: install locally, or point at a remote gateway instead. Boot message `Waiting for first-run setup choice`; stuck message `Still waiting for first-run setup choice after <N> seconds`.
- **What it does:** Parks the boot before the installer runs, until the user chooses "install the agent here" or applies a remote/Cloud connection.
- **How it works:** `createFirstRunSetupGate({ hideChoice, log, onStuck, promptChoice, stuckAfterMs = 120000 })` (`electron/first-run-setup-gate.ts`) exposes `shouldGate(backend)` (true only for `kind === 'bootstrap-needed'` and not already confirmed), `wait(backend)`, `continueLocal()`, `resetForRetry()`, `resetForRepair()`, `abandonForRemoteApply()`, `hasWaiter()`, `isLocalBootstrapConfirmed()`. Decisions: `'continue-local' | 'remote-applied' | 'reset'`. Main wires it at `main.ts:1975-2053` (`promptFirstRunSetupChoice`, `hideFirstRunSetupChoice`, `getFirstRunSetupGate`, `waitForFirstRunSetupChoice`, `continueFirstRunLocalBootstrap`, `abandonFirstRunSetupChoiceForRemoteApply`) and emits a `setup-choice` bootstrap event carrying `{ active, platform, activeRoot }`.
- **Inputs / options:** IPC `hermes:bootstrap:continue-local`; applying a remote connection resolves the gate as `remote-applied`.
- **Outputs / side effects:** Boot resumes down the chosen branch; a `dismissed` bootstrap event clears the snapshot.
- **Config / env:** n/a
- **Edge cases / guards:** A stuck timer (120 s, unref'd) reports rather than failing; the gate settles exactly once and never leaks a pending connection promise.
- **Rebuild notes:** Never start a multi-minute install without an explicit user decision, and make the wait cancellable and observable.

### Bootstrap runner (staged installer)  `id: desktop-main.bootstrap-runner`
- **Surface:** Desktop app / Core
- **Where:** The first-launch install overlay: a stage checklist, live output under "Show details", and a "Copy output" affordance.
- **What it does:** Runs the platform installer (`scripts/install.ps1` on Windows, `scripts/install.sh` on POSIX) stage-by-stage, streaming manifest/stage/log/complete/failed events to the renderer, then writes the bootstrap-complete marker.
- **How it works:** `runBootstrap({ installStamp, activeRoot, sourceRepoRoot, hermesHome, logRoot, onEvent, abortSignal, writeMarker })` (`electron/bootstrap-runner.ts:859-1010`). Steps: open a per-run log `<logRoot>/bootstrap-<ISO-timestamp>.log` (`openRunLog`); detect `hasExistingGitCheckout(activeRoot)` (an existing checkout is **not** pinned to the packaged stamp); `resolveInstallScript({ installStamp, sourceRepoRoot, hermesHome, emit })` (local checkout, installed agent copy, or a download for the stamped ref via `installRefForStamp`); `fetchManifest(...)` runs the script in manifest mode and takes the **last** line that parses as JSON with a `stages` array; emit `{ type:'manifest', stages, protocolVersion }`; iterate stages in manifest order calling `runStage(...)` which spawns `install.sh --stage <name> --non-interactive --json …` or `install.ps1 -Stage <name> -NonInteractive -Json …` (`spawnBash` / `spawnPowerShell`, `:459` / `:563`) and parses the single JSON result frame (`parseStageResult` requires `{ ok: boolean, stage: string }`); finally resolve the marker pin via `resolveMarkerPinnedCommit(installStamp, activeRoot)` (packaged all-zero fallback stamps never win; `resolveCheckoutHead` runs `git -c windows.appendAtomically=false rev-parse HEAD`, `readExistingPinnedCommit` prefers install.ps1's own marker) and call `writeMarker({ pinnedCommit, pinnedBranch })`.
- **Inputs / options:** every stage's `{ name, title, category, needs_user_input }` from the manifest; `abortSignal` from `bootstrapAbortController`.
- **Outputs / side effects:** A per-run bootstrap log; the installed checkout + venv at `ACTIVE_HERMES_ROOT`; `<root>/.hermes-bootstrap-complete`.
- **Config / env:** `ELECTRON_MIRROR` is honoured by the Electron download inside the build stage and never overridden by the installer.
- **Edge cases / guards:** Aborting before the first spawn emits `{ type:'failed', error:'bootstrap cancelled by user' }` and returns `{ ok:false, cancelled:true }`. Stages flagged `needs_user_input` are still invoked; the script's own `-NonInteractive` handler emits `skipped: true`. A subscriber that throws cannot crash the run (`emit error: <message>` is written to the run log). `WARNING: could not resolve a real pinnedCommit …` warns when subsequent launches may re-run bootstrap.
- **Rebuild notes:** Have the installer expose a machine-readable stage manifest and one JSON result frame per stage; the GUI then needs no knowledge of installer internals.

### Bootstrap event snapshot + overlay state  `id: desktop-main.bootstrap-state`
- **Surface:** Desktop app
- **Where:** The install overlay; recovered after a devtools reload via `hermesDesktop.getBootstrapState()`.
- **What it does:** Keeps a queryable snapshot of the bootstrap: stage list, per-stage state, a bounded log ring, error, setup choice and unsupported-platform info.
- **How it works:** `bootstrapState = { active, manifest, stages, error, log, startedAt, completedAt, setupChoice, unsupportedPlatform }` (`main.ts:1872`); `broadcastBootstrapEvent(ev)` (`:1886-1955`) folds each event type into it and re-emits `hermes:bootstrap:event` to the main window. Stage states: `'pending' | 'running' | 'succeeded' | 'skipped' | 'failed'`. Log ring bound `BOOTSTRAP_LOG_RING_MAX = 500` entries of `{ ts, stage, line, stream }`. Event types handled: `manifest`, `stage`, `log`, `complete`, `failed`, `unsupported-platform` (`{ platform, activeRoot, installCommand, docsUrl }`), `setup-choice`, `dismissed`. `getBootstrapState()` (`:1957`), `resetBootstrapSnapshot()` (`:1961`).
- **Inputs / options:** `hermesDesktop.getBootstrapState()`, `hermesDesktop.onBootstrapEvent(cb)`.
- **Outputs / side effects:** IPC pushes.
- **Config / env:** n/a
- **Edge cases / guards:** A synthetic empty manifest is emitted *before* the runner fetches the real one, so the overlay appears immediately on slow networks instead of leaving the user on a generic splash.
- **Rebuild notes:** Snapshot + stream, not stream alone — reloads must recover.

### Bootstrap controls: Reset / Repair / Continue locally / Cancel  `id: desktop-main.bootstrap-controls`
- **Surface:** Desktop app
- **Where:** The recovery overlay's buttons ("Reload and retry", the repair action, "Cancel" during install) and the first-run choice.
- **What it does:** Four renderer-driven controls over the bootstrap/boot state machine.
- **How it works:**
  - `hermes:bootstrap:reset` (`main.ts:14484-14497`): logs `[bootstrap] reset requested by renderer; clearing latched failure`, awaits `teardownPrimaryBackendAndWait()`, clears `bootstrapFailure`, `backendStartFailure`, `remoteReauthFailure`, calls `gate.resetForRetry()` and `resetBootstrapSnapshot()`. Returns `{ ok: true }`.
  - `hermes:bootstrap:repair` (`:14498-14549`): increments `bootstrapRepairAttempt`, probes the live primary child (`exitCode === null && signalCode === null`), asks `decideBootstrapRepair({ attempt, maxSoftAttempts: MAX_BOOTSTRAP_REPAIR_SOFT_ATTEMPTS /* 3 */, primaryBackendAlive })` (`electron/bootstrap-repair-guard.ts`), logs `[bootstrap] repair requested by renderer; forcing reinstall + clearing latched failure (attempt=<n>/3, primaryBackendAlive=<bool>, hardReinstall=<bool>): <reason>`, sets `bootstrapRepairRequested = decision.hardReinstall`, clears the three latches, calls `gate.resetForRepair()` and `resetHermesConnection()`. Deliberately does **not** delete the bootstrap marker (#72166 stranded users in first-run setup).
  - `hermes:bootstrap:continue-local` (`:14550`): logs `[bootstrap] local install selected by renderer; continuing first-launch bootstrap`, resolves the gate.
  - `hermes:bootstrap:cancel` (`:14556`): aborts `bootstrapAbortController`; returns `{ ok: true, cancelled: true }` or `{ ok: false, cancelled: false }`.
- **Inputs / options:** `hermesDesktop.resetBootstrap()`, `.repairBootstrap()`, `.continueBootstrapLocal()`, `.cancelBootstrap()`.
- **Outputs / side effects:** Latches cleared; installer possibly re-run; the install script SIGTERM'd.
- **Config / env:** n/a
- **Edge cases / guards:** Repair escalates to a hard reinstall only after 3 soft restarts, so a GIL stall cannot loop the user into a 30-minute reinstall cycle (#74874).
- **Rebuild notes:** "Repair" must distinguish a broken install from a stalled process; default to the non-destructive action.

### Runtime preparation (`ensureRuntime`)  `id: desktop-main.ensure-runtime`
- **Surface:** Core
- **Where:** Boot messages `Using <label>` (32%) and `Hermes runtime is ready` (82%).
- **What it does:** Converts a resolved backend descriptor into a launchable one — running the bootstrap when needed and wiring the venv interpreter afterwards.
- **How it works:** `ensureRuntime(backend)` (`main.ts:4814-4980`). `bootstrap: false` → advance to `runtime.external` and return unchanged. `kind === 'bootstrap-needed'` → try `handOffWindowsBootstrapRecovery('bootstrap-needed')` first (`:3963`, Windows+packaged only, throws a `bootstrapHandedOff` error with the message `Hermes recovery was handed off to Hermes Setup. The desktop will restart when recovery completes.`), else emit the synthetic manifest, create `bootstrapAbortController`, clear `bootstrapRepairRequested`/`bootstrapRepairAttempt`, run `runBootstrap(...)`, then recurse into `ensureRuntime(resolveHermesBackend(backend.args))`. `bootstrap: true` with a real checkout → validate `isHermesSourceRoot(ACTIVE_HERMES_ROOT)`, on Windows require Git Bash, require the venv python, then set `backend.command = getVenvPython(VENV_ROOT)` and `backend.label = 'Hermes at <root> (venv: <venvRoot>)'`.
- **Inputs / options:** n/a
- **Outputs / side effects:** Possibly a full install; boot progress.
- **Config / env:** n/a
- **Edge cases / guards:** Error strings (verbatim): `Hermes install was cancelled.`; `Hermes bootstrap failed at stage '<stage>': <error>. Check <HERMES_HOME>/logs/desktop.log for the full transcript.`; `Hermes install at <root> is missing or incomplete. Reinstall via the desktop installer or scripts/install.ps1.`; `Git for Windows is required for Hermes on Windows (provides Git Bash, which the agent's terminal tool uses). Install it from https://git-scm.com/download/win or run \`winget install -e --id Git.Git\`, then relaunch Hermes.`; `Hermes venv missing at <venvRoot>. Re-run the desktop installer or \`scripts/install.ps1\` to rebuild it.`
- **Rebuild notes:** Make bootstrap a recursive "resolve → install → re-resolve" so one code path covers cold and warm installs.

### Windows bootstrap recovery hand-off to Hermes Setup  `id: desktop-main.windows-bootstrap-handoff`
- **Surface:** Desktop app / Platform:Windows
- **Where:** Invisible; the app quits and the Hermes Setup window takes over, then relaunches the app.
- **What it does:** On a packaged Windows build with a staged updater binary, hands a failed/absent bootstrap to the Tauri installer instead of trying to install from inside Electron.
- **How it works:** `handOffWindowsBootstrapRecovery(reason)` (`main.ts:3963-4073`): requires `IS_WINDOWS && IS_PACKAGED` and a `resolveUpdaterBinary()`; spawns it detached and sets `isQuittingForHandoff`.
- **Inputs / options:** `reason` (e.g. `'bootstrap-needed'`).
- **Outputs / side effects:** Detached setup process; the desktop exits.
- **Config / env:** n/a
- **Edge cases / guards:** Returns `false` (and the normal bootstrap path runs) when not packaged, not Windows, or no updater binary is staged.
- **Rebuild notes:** Let the installer own installation; the app should only hand off.

### `state.db` pre-flight guard  `id: desktop-main.preflight-state-db`
- **Surface:** Core
- **Where:** Invisible; runs immediately before an update hand-off, while the backend is still alive.
- **What it does:** Takes an emergency backup of the session database and verifies its header, so an interrupted update cannot leave an unrecoverable `state.db`.
- **How it works:** `preflightStateDb(hermesHome, rememberLog)` (`main.ts:4095-4179`), called from `applyUpdates` (`:3739`).
- **Inputs / options:** n/a
- **Outputs / side effects:** A backup file beside `state.db`; log lines.
- **Config / env:** n/a
- **Edge cases / guards:** Best-effort; failures are logged, not fatal.
- **Rebuild notes:** Back up user state before any self-replacement.

### Stale git-lock self-heal  `id: desktop-main.git-lock-heal`
- **Surface:** Core
- **Where:** Invisible; makes update checks recover from `Unable to create '.git/shallow.lock': File exists`.
- **What it does:** Deletes abandoned `.git/*.lock` files left by a crashed fetch, which git never removes itself, before running `git fetch`.
- **How it works:** `clearStaleGitLocks(updateRoot)` (`electron/gitlock.ts`, 96 lines) called at `main.ts:3020` in `checkUpdates()`.
- **Inputs / options:** n/a
- **Outputs / side effects:** Removed lock files.
- **Config / env:** n/a
- **Edge cases / guards:** Only clears locks that are actually stale.
- **Rebuild notes:** A self-updater must repair its own VCS state, or one crash disables updates forever.

---

## 5. Multi-connection registry (v2) — main-process side

> The Settings → Gateways *forms* are documented by `desktop-settings`; this section documents the
> storage format, the invariants, the IPC surface and the routing the main process performs.

### `connections.json` — the v2 registry file  `id: desktop-main.registry-file`
- **Surface:** Config / Core
- **Where:** `<userData>/connections.json`, beside the untouched v1 `connection.json`. Corrupt files get a `.corrupt` sidecar.
- **What it does:** Persists the named list of every Hermes gateway this desktop can reach — the local runtime, remote gateways, Hermes Cloud instances and SSH hosts — plus which one is primary and which one Sessions opens on launch.
- **How it works:** Shape `{ version: 2, primary: string, launchMode: 'last-used'|'primary', lastUsed: string, connections: RegistryConnection[], quarantined?: QuarantinedRegistryEntry[] }` (`electron/connection-registry.ts:92-104`, `REGISTRY_VERSION = 2`). `RegistryConnection` = `{ id, kind: 'cloud'|'local'|'remote'|'ssh', label, url?, authMode?: 'oauth'|'token', token?, headers?, org?, host?, user?, port?, keyPath?, remoteHermesPath?, remoteProfile? }` (`:49-73`). Read/write in main: `readDesktopConnectionsRegistry()` (`main.ts:9047`), `writeDesktopConnectionsRegistry(registry)` (`:9157`), `preserveCorruptRegistrySidecar()` (`:9135`), `sanitizeRegistryConnection(entry)` (`:9171`), `sanitizeConnectionsRegistry(registry)` (`:9191`) — the sanitized shape is what ever reaches the renderer (no token bytes). Caching: `connectionRegistryCache` + `connectionRegistryCacheMtime` (`:1480-1481`).
- **Inputs / options:** n/a
- **Outputs / side effects:** The file (mode 0600, atomic write); secrets only inside encrypted envelopes.
- **Config / env:** n/a
- **Edge cases / guards:** `normalizeRegistry(raw)` (`:1058`) quarantines malformed entries verbatim in `quarantined[]` (cap `REGISTRY_QUARANTINE_CAP = 20`, `:90`) instead of dropping them — a corrupt entry never requires "delete connections.json" recovery (#94246).
- **Rebuild notes:** Preserve unparseable user data; never silently drop connection material.

### Registry invariants: exactly one local, unique labels, primary  `id: desktop-main.registry-invariants`
- **Surface:** Core
- **Where:** Enforced on every save; surfaced as the error strings the Gateways editor shows.
- **What it does:** Guarantees the registry always holds exactly one non-removable `local` connection, that every label is unique case-insensitively, and that `primary` names a live entry.
- **How it works:** `labelKey(label)` = trimmed+lowercased (`:111`); `LABEL_MAX = 64`; `uniqueLabel(candidate, taken)` (`:123`) clamps to `LABEL_MAX - 4` and suffixes ` 2`, ` 3`, … on collision; `labelSlug(label)` (`:145`) kebab-cases and clamps to 48 chars, falling back to `connection`; `connectionIdForLabel(label, taken)` (`:787`) mints an id that never equals `local`. `normalizeConnectionInput(input, registry)` (`:829`) throws the verbatim messages: `Every connection needs a name. Give this instance a device name (e.g. "Homelab", "Work laptop").`; `Connection name is too long (max 64 characters).`; `A connection named "<label>" already exists. Connection names must be unique.`; `The id "local" is reserved for the local connection.`; `SSH connections need a host.`; `A connection to this SSH host already exists ("<label>").`; `A connection to this gateway URL already exists ("<label>").`; `Unknown connection kind: <kind>`. `setPrimaryConnection` (`:1393`), `removeConnection` (`:1371` — removing the primary retargets to `local`), `setLastUsedConnection` (`:1402`), `setConnectionLaunchMode` (`:1605`), `upsertConnection` (`:1359`).
- **Inputs / options:** n/a
- **Outputs / side effects:** A normalized registry.
- **Config / env:** n/a
- **Edge cases / guards:** Duplicate keys — remote/cloud on the normalized URL (trimmed, trailing slashes stripped, lowercased, **across both kinds**); ssh on `<user>@<host>:<port>::<remoteProfile>` (default port 22). A crafted IPC payload claiming `id: 'local'` with a non-local kind is rejected so the exactly-one-local invariant cannot be broken.
- **Rebuild notes:** Put duplicate detection in the normalizer, not the form — the IPC surface is reachable without the form.

### Backend scope keys  `id: desktop-main.backend-scope-key`
- **Surface:** Core
- **Where:** Invisible; the pool key, the reaper log line, the renderer's socket registry key.
- **What it does:** Names one backend by `(connection, profile)` in a way that is byte-identical to the legacy profile key for single-gateway users.
- **How it works:** `backendScopeKey(connectionId, profile)` (`electron/connection-registry.ts:181-197`) returns the bare `profile` (default `'default'`) for a null/`'local'` connection, else `conn:<id>::<profile>` (colons are invalid in profile names, so no collision). `parseBackendScopeKey(key)` (`:199`) inverts it with `/^conn:(.+?)::(.+)$/`. `backendScopePrefix(connectionId)` (`:211`) = `conn:<id>::`, used to stop every backend a removed connection owns. The renderer's twin lives in `apps/shared/src/backend-scope.ts` and is pinned byte-identical by a cross-copy contract test.
- **Inputs / options:** n/a
- **Outputs / side effects:** none.
- **Config / env:** n/a
- **Edge cases / guards:** Changing one copy without the other fails `connection-registry.test.ts`.
- **Rebuild notes:** Make the multi-tenant key degrade to the single-tenant key so the migration is a no-op for existing users.

### `@profile-device` agent handles  `id: desktop-main.agent-handle`
- **Surface:** Core / Desktop app
- **Where:** Roster badges, `@mentions`, update results — e.g. `@research-homelab`.
- **What it does:** Disambiguates a profile name that exists on several gateways; a globally unique profile keeps its bare name.
- **How it works:** `agentHandle(profile, connectionLabel, duplicated)` (`electron/connection-registry.ts:161-166`) → `duplicated ? \`${name}-${labelSlug(connectionLabel)}\` : name`, with `name` defaulting to `'default'`.
- **Inputs / options:** n/a
- **Outputs / side effects:** none.
- **Config / env:** n/a
- **Edge cases / guards:** Single home of the rule — every surface calls it.
- **Rebuild notes:** One function owns the naming rule, or surfaces will disagree.

### Union agent roster  `id: desktop-main.agent-roster`
- **Surface:** Core / Desktop app / Tool (plugin SDK `host.agents()`)
- **Where:** Bot Mode roster, the fleet profile rail, the Capabilities scope selector.
- **What it does:** Lists one row per `(gateway, profile)` across every registered connection, with the precomputed handle and per-gateway reachability.
- **How it works:** `ipcMain.handle('hermes:agents:roster', …)` (`main.ts:15088-15108`) → `enumerateRegistryAgentSources(registry)` (`:14935`) → `buildAgentRoster(enumerations, { primaryConnectionId })` (`electron/connection-registry.ts:650`). Response: `{ agents, primaryConnectionId, sources: [{ connectionId, label, kind, reachable, installId?, error? }] }`. Enumeration is eager over REST but never dials sockets; SSH sources that have never been dialed are **skipped** (connect-on-demand) and served from `sshRosterCache` (`main.ts:14838`) with `SSH_INVENTORY_RETRY_MS = 60_000` throttling (`shouldRetrySshInventory`, `rememberSshEnumeration`, `probeSshProfileInventory` at `:14885`, remote listing parsed by `parseRemoteProfileListing`). `shouldDeferLocalEnumeration` (`:511`) and `resolveRegistryLocalRoute` (`:490`) decide whether the local entry delegates to the legacy path.
- **Inputs / options:** `hermesDesktop.getAgentRoster()`.
- **Outputs / side effects:** Possible REST calls to every registered gateway.
- **Config / env:** n/a
- **Edge cases / guards:** An unreachable gateway returns a per-row `error` rather than failing the roster. `primaryConnectionId` lets the plugin merger annotate the active gateway's own profiles in place instead of duplicating every bot (#88344). Two registrations of one backend collapse via `installId` (`rememberConnectionInstallId` / `probeConnectionInstallId`, `main.ts:14852-14883`, TTLs `INSTALL_ID_TTL_MS = 5 * 60_000`, `INSTALL_ID_NEGATIVE_TTL_MS = 60_000`).
- **Rebuild notes:** Enumerate over the cheap protocol; open the expensive one only on demand.

### Registry CRUD IPC  `id: desktop-main.registry-ipc`
- **Surface:** Core / Desktop app
- **Where:** `window.hermesDesktop.connections.*`; the Gateways page's Add / Edit / Remove / Test / Make primary / launch-mode controls.
- **What it does:** The complete main-process API for managing registered gateways.
- **How it works:** each handler below is registered with `ipcMain.handle` in `main.ts` and exposed on `window.hermesDesktop.connections`; every one reads/writes `connections.json` through `readDesktopConnectionsRegistry` / `writeDesktopConnectionsRegistry` and returns the sanitized registry.
- **Inputs / options:** every handler, with its exact channel:
  - `hermes:connections:list` → `sanitizeConnectionsRegistry()`; SDK: `connections.list()`.
  - `hermes:connections:save` (payload = a connection input) → `saveRegistryConnection(payload)` (`main.ts:9226`), returns `{ ok: true, connection, registry }`. SDK: `connections.save(payload)`.
  - `hermes:connections:remove` (id) → asserts `managedConnectionUpdateGate.assertCanMutate(id)`, `removeConnection`, write, `stopRegistryConnectionBackends(id)` (`:11872`, stops every pooled backend under `backendScopePrefix(id)` and any SSH scopes), then `broadcastConnectionsChanged({ connectionId, reason: 'removed' })`. Returns `{ ok: true, registry }`. SDK: `connections.remove(id)`.
  - `hermes:connections:set-primary` (id) → `assertCanMutateManagedPrimaryRouting()` then `setPrimaryConnection`. SDK: `connections.setPrimary(id)`.
  - `hermes:connections:set-launch-mode` (`'primary' | 'last-used'`) → `assertCanMutateManagedPrimaryRouting()` then `setConnectionLaunchMode`. SDK: `connections.setLaunchMode(mode)`.
  - `hermes:connections:set-last-used` (id) → `setLastUsedConnection`. SDK: `connections.setLastUsed(id)`.
  - `hermes:connections:test` (id) → see `desktop-main.registry-test`. SDK: `connections.test(id)`.
  - `hermes:connections:update-managed` (id) → `requestManagedSshUpdate(id)`. SDK: `connections.updateManaged(id)`.
  - `hermes:connections:update-all` (`{ excludeIds? }`) → the fleet fan-out. SDK: `connections.updateAll(options)`.
  - `hermes:connections:changed` (main → renderer push) with `{ connectionId, reason: 'removed'|'saved'|'updated' }`. SDK: `connections.onChanged(cb)`.
- **Outputs / side effects:** Registry writes; backend/tunnel teardown; renderer socket disposal.
- **Config / env:** n/a
- **Edge cases / guards:** Without the `changed` push, secondaries scoped to a removed remote keep their WebSocket open and stream ghost events until a page reload (remote/cloud have no local process to kill).
- **Rebuild notes:** A registry mutation must also be a lifecycle event; storage-only CRUD leaks live sockets.

### Connection save pipeline  `id: desktop-main.registry-save`
- **Surface:** Core
- **Where:** **Save connection** in the Gateways add/edit editor.
- **What it does:** Validates, merges over the stored entry, encrypts secrets, writes the registry and recycles anything that now points at the old target.
- **How it works:** `saveRegistryConnection(input)` (`main.ts:9226-9287`): `mergeConnectionInput(input, existing)` (inherits `url`, `authMode`, `org`, `host`, `keyPath`, `remoteHermesPath`, `remoteProfile`, `headers`; `user`/`port` are **not** inherited when the payload carries a `host` string, because the editor's composite `user@host:port` field is authoritative; `token` is never merged — the caller owns secret handling) → `normalizeConnectionInput(merged, registry)` → encrypt token/headers (`encryptDesktopSecret`, `encryptIncomingRemoteHeaders`) → `upsertConnection` → write → `connectionDialFieldsChanged(before, after)` (`electron/connection-registry.ts:1010`) decides whether to broadcast `{ reason: 'updated' }` (recycle live backends/sockets) or `{ reason: 'saved' }` (label-only edit, traffic keeps flowing).
- **Inputs / options:** `{ id?, kind, label, url?, authMode?, token?, headers?, org?, host?, user?, port?, keyPath?, remoteHermesPath?, remoteProfile? }`.
- **Outputs / side effects:** The registry file; possibly torn-down backends.
- **Config / env:** n/a
- **Edge cases / guards:** Switching a remote from `token` to `oauth` (or saving a cloud entry) deliberately **drops** the stored token so dead secret material does not ride along.
- **Rebuild notes:** Distinguish cosmetic edits from dial-affecting edits; only the latter should disturb live traffic.

### Connection **Test** (two-leg probe)  `id: desktop-main.registry-test`
- **Surface:** Desktop app
- **Where:** **Test** on a registered-gateway row; success toast **"Reachable"**.
- **What it does:** Probes the connection's own HTTP *and* WebSocket legs, so a pass means chat will actually work.
- **How it works:** `ipcMain.handle('hermes:connections:test', …)` (`main.ts:14742-15086`). SSH entries route to `testDesktopConnectionConfig({ mode:'ssh', sshHost, sshUser, sshPort, sshKeyPath, sshRemoteHermesPath })` and, on success, clear `sshInventoryAttemptedAt`/`sshRosterCache` and re-run `probeSshProfileInventory(entry)`. Local entries call `startHermes()` and use its baseUrl/token. Remote/cloud entries are built **directly from the registry entry** (never through `coerceDesktopConnectionConfig`, which would inherit the v1 global remote's token and send it to this entry's URL — cross-host credential transmission plus a false "reachable"). Then `fetchConnectionStatus(baseUrl, authMode, token, headers)` (`:10797`) → `rememberConnectionInstallId(entry.id, status)` → `resolveTestWsUrl(baseUrl, authMode, token, { mintTicket })` → `probeGatewayWebSocket(wsUrl, { WebSocketImpl, headers })`.
- **Inputs / options:** `connections.test(id)`.
- **Outputs / side effects:** `{ ok: true, baseUrl, version }`, or a throw.
- **Config / env:** n/a
- **Edge cases / guards:** Error strings (verbatim): `No connection with id "<id>".`; `This connection has no saved session token. Edit the connection and paste one.`; `Reached the gateway over HTTP, but the live WebSocket (/api/ws) connection failed: <reason> The HTTP check can pass while the WebSocket is blocked by a proxy, firewall, or gateway auth/origin guard.`
- **Rebuild notes:** Test the transport the feature uses, not just a reachability ping.

### Fleet update fan-out (**Update all instances**)  `id: desktop-main.update-all`
- **Surface:** Desktop app
- **Where:** **Settings → Gateways → Update all instances** (shown once more than one connection is registered); also driven automatically by **Update now**, ⌘K **Update Hermes**, and the update-ready toast.
- **What it does:** Dispatches `hermes update` to every eligible registered connection in parallel, each reporting independently.
- **How it works:** `ipcMain.handle('hermes:connections:update-all', …)` (`main.ts:15179-15310`). Per connection: `updateEligibility(connection)` (`electron/connection-registry.ts:778`) — ineligible rows return `{ ok:false, skipped:true, reason }` (Hermes Cloud entries report *"Managed by Hermes Cloud"*). `local` → `applyUpdates({})`, the same pipeline as Settings → Updates. `ssh` → `requestManagedSshUpdate(connection.id)` (the transactional drain/update/restore lifecycle). Everything else → `backendDialClaims.run(backendScopeKey(id, null), () => ensureRegistryBackend(id, null))` then `postJsonForBackend(descriptor, '/api/hermes/update', {}, { timeoutMs: 15_000 })`; a backend that refuses (docker/nix/externally managed) surfaces **its** message per row (`{ ok:false, skipped:true, reason: body.error, detail: body.message }`).
- **Inputs / options:** `connections.updateAll({ excludeIds?: string[] })` — the everything-update flow excludes the active backend and the local client because it dispatches those itself (active backend first, local client **last**, since applying it relaunches the app).
- **Outputs / side effects:** `{ ok: true, results: [{ connectionId, label, kind, ok, skipped?, reason?, detail?, error?, managed? }] }`.
- **Config / env:** n/a
- **Edge cases / guards:** One unreachable box never wedges the batch (`Promise.all` over per-row try/catch).
- **Rebuild notes:** Fan out with per-row results and an explicit exclusion list so a caller can compose its own ordering.

### v1 → v2 migration and drift reconciliation  `id: desktop-main.registry-migration`
- **Surface:** Core
- **Where:** Invisible; happens on the first launch of a registry-capable build.
- **What it does:** Imports the legacy global connection and any per-profile overrides from `connection.json` into named registry entries, and keeps the two representations coherent afterwards.
- **How it works:** `migrateV1ToRegistry(v1)` (`electron/connection-registry.ts:1226`), deduplicated by URL/host, colliding labels suffixed via `uniqueLabel` (`Homelab 2`). The legacy file is left untouched so older builds on the same machine keep working. `reconcileAppliedGlobalConnection(...)` (`:1422`) and `reconcileRegistryDrift(...)` (`:1507`) keep `connection.json` and `connections.json` consistent after an Apply. `registrySourceOwnsPrimaryBackend(...)` (`:442`) decides whether a registry entry owns the window backend. `resolvedConnectionId(registry, descriptor)` (`:258`) recovers registry identity for a descriptor resolved through the legacy v1 path — an explicitly present but unusable `connectionId` fails closed rather than falling back to endpoint-shaped inference.
- **Inputs / options:** n/a
- **Outputs / side effects:** A populated `connections.json`.
- **Config / env:** n/a
- **Edge cases / guards:** Presence of the `connectionId` property is authoritative even when its value is unusable.
- **Rebuild notes:** Migrate by copy, never by move — the old format must keep working for older clients.

### Window connection route registry  `id: desktop-main.window-connection-route`
- **Surface:** Core
- **Where:** Invisible; per-window `(connection, profile)` routing.
- **What it does:** Tracks which gateway/profile each window is currently on, so REST calls and SSH scopes resolve to the right backend per window.
- **How it works:** `class WindowConnectionRouteRegistry` (`electron/window-connection-route.ts`, 67 lines) + `registrySshScopeForWindowRoute`; instance `windowConnectionRoutes` (`main.ts:14211`), owners tracked in `windowConnectionRouteOwners: Set<number>` (`:14212`). Renderer publishes with `ipcMain.on('hermes:connection:active-route', (event, route) => …)` (`:14214`), preload `setActiveConnectionRoute(route)`. `connection-route-identity.ts` (131 lines) supplies `matchingConnectionId` and the `StoredRoute` type. `resolveDesktopRemoteRoute` (`electron/desktop-remote-route.ts`, 212 lines) resolves a route to a remote descriptor.
- **Inputs / options:** `hermesDesktop.setActiveConnectionRoute(route)`.
- **Outputs / side effects:** Routing decisions for `hermes:api`, terminals and previews.
- **Config / env:** n/a
- **Edge cases / guards:** Routes are per-`webContents.id`, cleaned up on window close.
- **Rebuild notes:** Windows are independent tenants; do not keep one global "current connection".

### Registry-scoped backend resolution IPC  `id: desktop-main.connection-for`
- **Surface:** Core
- **Where:** `window.hermesDesktop.getConnection(profile)`, `.getConnectionFor({ connectionId, profile })`, `.revalidateConnection()`, `.getGatewayWsUrl(profile)`, `.getGatewayWsUrlFor({ connectionId, profile })`.
- **What it does:** Hands the renderer a connection descriptor (base URL, auth mode, token, ws URL) for the primary backend or for any registered `(connection, profile)`.
- **How it works:** `hermes:connection` → `ensureBackend(profile)`; `hermes:connection:for` → `ensureRegistryBackend(connectionId, profile)`; `hermes:connection:revalidate` (`main.ts:14244`) re-probes the current remote via `revalidateRemoteConnection` / `RemoteRevalidationCoordinator`; `hermes:gateway:ws-url` → `gatewayWsUrlIpcResult(() => freshGatewayWsUrl(profile))`; `hermes:gateway:ws-url-for` → `createRegistryGatewayWsUrlHandler({ ensureBackend: ensureRegistryBackend, mintTicket: mintGatewayWsTicket, buildTicketUrl: buildGatewayWsUrlWithTicket, rememberHeaders: rememberRemoteWsHeaders })` (`electron/remote-ws-headers.ts`).
- **Inputs / options:** as above.
- **Outputs / side effects:** Descriptors; possibly a backend spawn or an SSH dial.
- **Config / env:** n/a
- **Edge cases / guards:** `gatewayWsUrlIpcResult` wraps the result as `{ ok: true, wsUrl }` or `{ ok: false, error, needsOauthLogin? }` so the renderer can distinguish a lapsed session from a transport error.
- **Rebuild notes:** Mint a fresh WS URL per connect; a cached OAuth ticket is single-use.

### Plugin profile routes IPC  `id: desktop-main.plugin-profile-routes`
- **Surface:** Core / Tool (plugin SDK)
- **Where:** `window.hermesDesktop.getProfileRoutes(profiles)`.
- **What it does:** Resolves a list of profile names to the registry routes that own them, so a plugin can address agents across gateways.
- **How it works:** `ipcMain.handle('hermes:plugin-profile-routes', …)` (`main.ts:14577-14644`) → `buildRegistryProfileRoutes(...)` with `isLocalEnumerationFailure`, `localRouteFallbackProfiles`, `undialedSshRouteSeeds` (`electron/plugin-profile-routes.ts`, 312 lines).
- **Inputs / options:** `profiles: string[]` (non-strings filtered out).
- **Outputs / side effects:** A route map.
- **Config / env:** n/a
- **Edge cases / guards:** Un-dialed SSH connections contribute seed routes rather than being dialed.
- **Rebuild notes:** Give extensions a routing table, not raw connection records.

---

## 6. Remote, SSH and Hermes Cloud backends

### `connection.json` — the v1 connection config  `id: desktop-main.connection-config-file`
- **Surface:** Config / Core
- **Where:** `<userData>/connection.json`; edited through **Settings → Gateways → Connection mode** and the legacy per-profile overrides.
- **What it does:** Stores the machine-level connection mode (`local` / `remote` / `cloud` / `ssh`), the remote block, and legacy per-profile overrides. Left in place unchanged so older builds keep working after the v2 registry migration.
- **How it works:** `readDesktopConnectionConfig()` (`main.ts:8949`, cached with `connectionConfigCache`/`connectionConfigCacheMtime`), `writeDesktopConnectionConfig(config)` (`:9020`), `sanitizeConnectionProfiles(raw)` (`:8865`), `sanitizeDesktopConnectionConfig(config, profile)` (`:9322`), `coerceDesktopConnectionConfig(input, existing, options)` (`:9427`), `buildRemoteBlock(remoteUrl, authMode, token, org, headers)` (`:9401`), `buildSshBlock(input, existingBlock)` (`:9531`). IPC: `hermes:connection-config:get` (sanitized, no token bytes), `:save`, `:apply`, `:test`, `:probe`, `:oauth-login`, `:oauth-logout`.
- **Inputs / options:** `hermesDesktop.getConnectionConfig(profile)`, `.saveConnectionConfig(payload)`, `.applyConnectionConfig(payload)`, `.testConnectionConfig(payload)`, `.probeConnectionConfig(remoteUrl)`, `.oauthLoginConnectionConfig(remoteUrl)`, `.oauthLogoutConnectionConfig(remoteUrl)`.
- **Outputs / side effects:** The file (0600); backend teardown/re-dial on apply.
- **Config / env:** env `HERMES_DESKTOP_REMOTE_URL` overrides the in-app remote URL.
- **Edge cases / guards:** Tokens are always encrypted envelopes; `tokenPreview(value)` (`electron/connection-config.ts:891`) is what the UI shows.
- **Rebuild notes:** Keep the old format readable and writable while the new one takes over; never migrate destructively.

### Remote URL normalization  `id: desktop-main.remote-url-normalize`
- **Surface:** Core
- **Where:** The **Gateway URL** field's validation errors.
- **What it does:** Accepts what users actually paste (`homelab.lan:9119`, a Tailscale IP, a URL with a path prefix) and produces one canonical base URL.
- **How it works:** `normalizeRemoteBaseUrl(rawUrl)` (`electron/connection-config.ts:66-99`): trims; prefixes `http://` when there is no `scheme://` (so `100.64.0.1:9119` does not parse `100.64.0.1:` as a protocol); parses with `URL`; requires `http:`/`https:`; clears `hash` and `search`; strips trailing slashes from the pathname and the result.
- **Inputs / options:** the raw URL string.
- **Outputs / side effects:** The normalized URL, or a throw.
- **Config / env:** n/a
- **Edge cases / guards:** Errors (verbatim): `Remote gateway URL is required.`; `Remote gateway URL is not valid: <message>`; `Remote gateway URL must be http:// or https://, got <protocol>`.
- **Rebuild notes:** Normalize once, at the edge; every dedupe and cache key downstream depends on it.

### Gateway WebSocket URL construction  `id: desktop-main.gateway-ws-url`
- **Surface:** Core
- **Where:** Invisible; the URL the renderer opens.
- **What it does:** Builds `ws(s)://<host><prefix>/api/ws?token=…` for token gateways and `?ticket=…` for OAuth gateways, preserving a reverse-proxy path prefix.
- **How it works:** `buildGatewayWsUrl(baseUrl, token)` and `buildGatewayWsUrlWithTicket(baseUrl, ticket)` (`electron/connection-config.ts:102-116`): `wss` when the base is `https:`, prefix = pathname with trailing slashes stripped, value `encodeURIComponent`-encoded. `resolveTestWsUrl(baseUrl, authMode, token, { mintTicket })` picks the right one for **Test**.
- **Inputs / options:** n/a
- **Outputs / side effects:** A URL string.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** Carry the path prefix — reverse-proxied deployments are common.

### Single-use OAuth WS tickets  `id: desktop-main.ws-ticket`
- **Surface:** Core
- **Where:** Invisible; every OAuth-gated gateway connect.
- **What it does:** Mints a fresh single-use `~30 s` WebSocket ticket immediately before each socket open, because the ticket baked into a cached connection is stale on the second connect.
- **How it works:** `mintGatewayWsTicket(baseUrl, headers)` (`main.ts:7884-7919`) wrapped in `withTransientRetries`: prefers a native bearer (`ensureNativeAccessToken(baseUrl)`) POSTing `<baseUrl>/api/auth/ws-ticket` with an 8 s timeout, else `fetchJsonViaOauthSession` over the cookie partition; throws `Gateway did not return a WS ticket.` when the body has no `ticket` string. `freshGatewayWsUrl(profile)` (`:7928-7950`) resolves the backend for that profile first (so a pooled profile does not silently land on the primary backend and write sessions into the wrong DB), then either mints a ticket or reuses the long-lived token, and calls `rememberRemoteWsHeaders(wsUrl, headers)`.
- **Inputs / options:** `hermesDesktop.getGatewayWsUrl(profile)` / `.getGatewayWsUrlFor({ connectionId, profile })`.
- **Outputs / side effects:** `{ ok: true, wsUrl }` or `{ ok: false, error, needsOauthLogin? }` via `gatewayWsUrlIpcResult`.
- **Config / env:** n/a
- **Edge cases / guards:** `gatewayTicketFailure(error, authMessage, transportMessage)` (`electron/connection-config.ts:129`) marks the error `needsOauthLogin` only when the gateway explicitly rejected the session (`isGatewayAuthRejection`: `needsOauthLogin === true`, or status 401/403).
- **Rebuild notes:** Treat the ticket as a nonce with a TTL; mint at connect time, never cache.

### Extra remote gateway headers (access proxies)  `id: desktop-main.remote-headers`
- **Surface:** Config / Core
- **Where:** The remote-connection editor's extra-headers fields (e.g. Cloudflare Access `CF-Access-Client-Id` / `CF-Access-Client-Secret`).
- **What it does:** Lets a remote gateway sitting behind an access proxy receive additional credential headers on every REST call and on the WebSocket upgrade.
- **How it works:** `normalizeRemoteHeaders(raw)` (`electron/connection-config.ts:310-346`) accepts a `{ name: string | { encoding, value } }` map; names must match `REMOTE_HEADER_NAME_RE = /^[!#$%&'*+.^_\`|~0-9A-Za-z-]+$/` and must not be in `FORBIDDEN_REMOTE_HEADER_NAMES` = `authorization`, `connection`, `content-length`, `content-type`, `cookie`, `host`, `origin`, `referer`, `te`, `trailer`, `transfer-encoding`, `upgrade`, `x-hermes-session-token`; values are stored as `{ encoding: 'plain'|'safeStorage', value }`. Main encrypts/decrypts with `encryptIncomingRemoteHeaders(raw, existing, { allowPlainText })` (`:8790`) and `decryptRemoteHeaders(headers)` (`:8764`). WebSocket upgrades get them via `createRemoteWsHeaderStore()` / `rememberRemoteWsHeaders(wsUrl, headers)` (`:8827`) + `installRemoteHeaderRules()` (`:8851`) which registers a `webRequest.onBeforeSendHeaders` rule; per-request lookup is `headersForRemoteRequest(requestUrl)` (`:8831`) gated by `remoteRequestMatchesBaseUrl` so headers only go to the matching origin.
- **Inputs / options:** the headers map on a remote/cloud connection.
- **Outputs / side effects:** Encrypted envelopes in the registry; headers on outbound requests.
- **Config / env:** n/a
- **Edge cases / guards:** Transport- and Hermes-managed header names are dropped silently; an empty result stores nothing; headers apply to both token- and OAuth-gated remotes.
- **Rebuild notes:** Whitelist by shape and blacklist the transport-owned names; scope the injection to the exact base URL.

### Remote backend resolution  `id: desktop-main.resolve-remote-backend`
- **Surface:** Core
- **Where:** Invisible; used by the primary boot and by every pooled `(connection, profile)`.
- **What it does:** Turns a profile (or registry entry) into a live remote descriptor — dialing SSH, resolving Cloud, or probing a URL remote as needed.
- **How it works:** `resolveRemoteBackend(profile, { poolKey, primary })` (`main.ts:10382-10490`). Route selection helpers from `electron/connection-config.ts`: `profileHasRemoteOverride` (`main.ts:10492`), `configuredRemoteProfileNames` (`:10496`), `globalRemoteActive` (`:10506`), `registryPrimaryIsRemote` (`:10529`), `primaryBackendIsRemote` (`:10546`), plus `resolveProfileBackendRoute`, `profileRemoteOverride`, `profileSshOverride`, `savedProfileSsh`, `localProfileEntry`, `modeIsRemoteLike`, `connectionScopeKey`. `buildRemoteConnection(baseUrl, authMode, token, source, hostLabel, remoteKind, ownershipId)` (`:9562`) assembles the descriptor.
- **Inputs / options:** `profile`, `poolKey`, `primary`.
- **Outputs / side effects:** A descriptor `{ baseUrl, mode:'remote', authMode, token, headers, wsUrl, remoteKind:'url'|'ssh'|'cloud', remoteHost, connectionId, ssh? }`.
- **Config / env:** env `HERMES_DESKTOP_REMOTE_URL`.
- **Edge cases / guards:** `resolveRemoteSshDashboardProfile(configuredRemoteProfile, poolOrProfileKey)` maps a local routing label onto the remote install's actual profile name; `RESERVED_REMOTE_PROFILES` = `hermes`, `test`, `tmp`, `root`, `sudo` are never accepted as an explicit remote profile.
- **Rebuild notes:** One resolver for every remote kind; the caller should not branch on transport.

### SSH connection manager (OpenSSH ControlMaster)  `id: desktop-main.ssh-connection`
- **Surface:** Core / Platform:all
- **Where:** Invisible; used by every registered **SSH** connection.
- **What it does:** Opens and reuses one authenticated OpenSSH connection per SSH gateway, executes remote commands over it, and forwards local ports to the remote dashboard.
- **How it works:** `class SshConnection` (`electron/ssh-connection.ts:564-1120`). Uses the *system* `ssh` so `~/.ssh/config`, the agent, ProxyJump and hardware keys work for free. `baseSshOptions(controlPath, connectTimeoutMs)` (`:207-231`) emits `-o ControlPath=<socket> -o ControlMaster=auto -o ControlPersist=300` (POSIX only) plus, always, `-o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ExitOnForwardFailure=yes -o ConnectTimeout=<secs>`. `hostArgs({ port, keyPath })` adds `-p <port>` (only when ≠ 22) and `-i <keyPath>`. Command builders: `buildExecArgs`, `buildControlArgs('-O <op>')`, `buildMasterArgs('-M -N -f')`, `buildInteractiveSshArgs('-tt')`. Methods: `open({signal})`, `isAlive({signal})`, `_verifyMuxChannel`, `_evictStaleMaster`, `exec(remoteCommand, { timeoutMs, stdinData })`, `forward(localPort, remotePort, remoteHost='127.0.0.1')`, `cancelForward(...)`, `close()`. Timeouts: `DEFAULT_CONNECT_TIMEOUT_MS = 15_000`, `DEFAULT_EXEC_TIMEOUT_MS = 20_000`, `DEFAULT_FORWARD_TIMEOUT_MS = 15_000`. Windows OpenSSH has no mux, so `_mux = false` there: one ssh invocation per operation and a persistent `ssh -N -L` child per tunnel, restarted up to `DEFAULT_TUNNEL_RESTART_LIMIT = 5` times with `DEFAULT_TUNNEL_RESTART_DELAY_MS = 1_000` before the connection is declared dead (#96266). Control-socket path is hashed under a short tmpdir to stay inside macOS's 104-byte `sun_path` limit, keyed by user/host/port + keyPath + ownershipId + scope + effective-config fingerprint.
- **Inputs / options:** `{ host, user, port, keyPath }` and `{ mux, controlDir, ownershipId, scope, effectiveConfigFingerprint, rememberLog, spawnFn, connectTimeoutMs, execTimeoutMs, forwardTimeoutMs, tunnelRestartLimit, tunnelRestartDelayMs }`.
- **Outputs / side effects:** A ControlMaster socket; forwarded local ports; log lines, always through `redactSecrets`.
- **Config / env:** n/a
- **Edge cases / guards:** `validateSshTarget(host, user, port)` rejects empty hosts, hosts starting with `-`, control characters, and shapes that match neither `_HOSTNAME_RE` nor `_IPV6_RE`; `validateKeyPath` guards `-i`. `-O check` passing is not trusted alone: a real exec must succeed (`_verifyMuxChannel`) or the master is evicted and re-dialed. Every operation is raced against a hard timeout, and timeout is treated as connection-dead (a half-open TCP after sleep would otherwise hang forever). `pickLocalPort` chooses the local tunnel port.
- **Rebuild notes:** Shell out to the system ssh; reimplementing SSH loses config, agents and jump hosts.

### SSH error classification and messages  `id: desktop-main.ssh-errors`
- **Surface:** Desktop app
- **Where:** The connection error overlay and toast text.
- **What it does:** Turns raw OpenSSH stderr into one of four actionable errors with concrete remediation.
- **How it works:** `classifySshError(stderr)` (`electron/ssh-connection.ts:340-370`) checks, in order: host-key change (`REMOTE HOST IDENTIFICATION HAS CHANGED|Host key verification failed|Offending (key|ECDSA|RSA|ED25519)`) → `HOST_KEY_CHANGED`; auth (`Permission denied|Too many authentication failures|no matching host key|publickey|password|keyboard-interactive`) → `AUTH_FAILED`; reachability (`Could not resolve hostname|Connection refused|Connection timed out|No route to host|Network is unreachable|Operation timed out|port \d+: Connection`) → `UNREACHABLE`; else `UNKNOWN`. `sshErrorMessage(kind, conn, stderr)` (`:373-404`) renders (verbatim):
  - HOST_KEY_CHANGED: `The host key for <target> has CHANGED since you last connected. This could be a man-in-the-middle attack, or the server was reinstalled. SSH refused to connect. Verify the change is expected, then remove the old key with \`ssh-keygen -R <host>\` and reconnect.` + the raw stderr.
  - AUTH_FAILED: `SSH authentication to <target> failed. Desktop runs ssh non-interactively (BatchMode), so a key requiring a passphrase or 2FA must be loaded into your ssh-agent first (e.g. \`ssh-add ~/.ssh/id_ed25519\`), or set an IdentityFile in ~/.ssh/config. Original error: <stderr>`
  - UNREACHABLE: `Could not reach <target> over SSH. Check the host, port, and your network. Original error: <stderr>`
  - TIMEOUT: `SSH operation to <target> timed out. The connection may be half-open (e.g. after sleep); reconnecting.`
  - default: `SSH error connecting to <target>: <stderr|unknown failure>`
- **Inputs / options:** n/a
- **Outputs / side effects:** An `Error` carrying `.kind`.
- **Config / env:** n/a
- **Edge cases / guards:** Order matters — the host-key banner also contains "WARNING"/"Offending", so it is checked before the generic auth patterns. A host-key change latches the boot failure (see `desktop-main.boot-failure-latch`).
- **Rebuild notes:** Classify before you display; the raw OpenSSH banner is not an actionable error.

### `~/.ssh/config` host suggestions  `id: desktop-main.ssh-config-hosts`
- **Surface:** Desktop app / Core
- **Where:** The **SSH host** field's suggestions in the connection editor.
- **What it does:** Lists concrete `Host` aliases from the user's OpenSSH client config (following `Include` directives) and resolves one alias to its effective settings.
- **How it works:** `collectSshConfigHosts()` and `parseSshGOutput` (`electron/ssh-config.ts`, 175 lines): `parseSshConfigHosts(text)` collects `Host <patterns>` entries, skipping any containing `*`, `?` or a leading `!`; `parseSshConfigIncludes(text)` walks `Include` (read-only). IPC: `hermes:ssh-config:hosts` → `{ hosts }` (`main.ts:14645`); `hermes:ssh-config:resolve` (`:14646`) shells `ssh -G <host>` and parses the output.
- **Inputs / options:** `hermesDesktop.sshConfigHosts()`, `.sshResolveHost(host)`.
- **Outputs / side effects:** Read-only file access.
- **Config / env:** n/a
- **Edge cases / guards:** Wildcard patterns are never offered as suggestions.
- **Rebuild notes:** Read the user's real config; do not invent a parallel host list.

### SSH host string parsing  `id: desktop-main.ssh-host-parse`
- **Surface:** Core
- **Where:** The single composite **SSH host** field (`user@host:22` form).
- **What it does:** Parses one field into `{ host, user?, port?, keyPath?, remoteHermesPath?, remoteProfile? }`, tolerating a pasted `ssh root@box` command and bracketed IPv6.
- **How it works:** `normalizeSshConfig(entry)` (`electron/connection-config.ts:380-462`): strips a leading `ssh `; splits on the first `@` for the user; accepts `[ipv6]` or `[ipv6]:port`, or `host:port` when exactly one colon is present and the port is all digits; explicit `entry.user`/`entry.port` win over parsed ones; the port is stored only when it is an integer in 1–65535 and **not** 22; `remoteProfile` is kept only when it matches `/^[a-z0-9][a-z0-9_-]{0,63}$/` and is not a reserved name.
- **Inputs / options:** `{ mode:'ssh', host, user, port, keyPath, remoteHermesPath, remoteProfile }`.
- **Outputs / side effects:** The normalized object, or `null`.
- **Config / env:** n/a
- **Edge cases / guards:** Returns `null` for a missing host — the caller throws `SSH connections need a host.`
- **Rebuild notes:** One composite field beats four; parse generously, store canonically.

### SSH bootstrap: reuse-or-spawn a remote `hermes serve`  `id: desktop-main.ssh-bootstrap`
- **Surface:** Core
- **Where:** Invisible; happens the first time you open an agent on an SSH gateway. Log `[ssh] connection REUSED|spawned dashboard: <version> at <path>`.
- **What it does:** Over the SSH tunnel, locates the remote Hermes install, reuses an existing desktop-dedicated backend if one is provably ours, or spawns a fresh detached `hermes serve --isolated --host 127.0.0.1 --port 0`, then forwards a local port to it.
- **How it works:** `bootstrapSshConnection(...)` (`main.ts:10076`) → `bootstrapSshConnectionInner(profile, sshConfig, reuseToken, source, metadata, fingerprint, lease)` (`:10161-10325`). Per-profile scope keys `sshScopeKey(profile)` / `sshOwnershipKey(profile)` (`:9856-9862`); the ownership id is `sshOwnershipId(installationId, scope)` = first 32 hex chars of `sha256(installationId + "\0" + scope)` (`electron/desktop-installation.ts`), where `installationId` is a v4 UUID persisted at `<userData>/desktop-installation.json` (0600, created under a `.repair.lock` with up to 40 attempts). Platform gate: `detectRemotePlatform(ssh, remoteHermesPath)`; Windows remotes use `connectWindowsRemote` (`electron/windows-remote-lifecycle.ts`, 783 lines, PowerShell-encoded scripts), POSIX uses `remoteLifecycle.connect` (`electron/remote-lifecycle.ts`, 1691 lines, `SUPPORTED_REMOTE_OS = { Linux, Darwin }`). Remote state lives under `~/.hermes/desktop-ssh/<ownershipId>/` with a lockfile (`LOCKFILE_SCHEMA_VERSION = 2`, `PROTOCOL_VERSION = 1`) holding pid, ports, token **fingerprint** (`sha256`, first 32 hex — never the raw secret), spawn nonce, creation time. Reuse requires an *authenticated* `/api/status` probe plus `classifySshReuseProof(proof, spawnNonce)` (nonce match + protocol match + `runtimeIntact !== false`), not mere pid liveness. Spawn is one atomic remote command (`buildSpawnCommand`, `:1038-1119`) that: takes the update mutex, checks the remote `.hermes-update-in-progress` marker (exit 75 when an update owns the install), atomically `mkdir`s a connect reservation with a 600×50 ms wait, re-checks the lockfile pid, `ulimit -n 65536`, then `setsid`/`nohup` spawns `env HERMES_DESKTOP=1 <hermes> [--profile <p>] serve --isolated --host 127.0.0.1 --port 0 --ssh-session-token-file <path> --ssh-owner-nonce <nonce>` detached with stdout appended to a spawn log, and publishes the lockfile via a temp file + `mv -f`. Readiness is scraped from the spawn log with `READY_RE` (`DEFAULT_READY_TIMEOUT_MS = 45_000`, `READY_POLL_INTERVAL_MS = 750`). Then `openForward` (3 attempts, `isForwardBindCollision` retries), `waitForHermes`, `adoptOwnedServedToken`.
- **Inputs / options:** the SSH connection's fields; `reuseToken` from the registry.
- **Outputs / side effects:** A remote `hermes serve` process; `~/.hermes/desktop-ssh/<id>/` lock + logs on the remote; a local forwarded port; the adopted token persisted encrypted via `persistSshConnectionToken` (`main.ts:10335`).
- **Config / env:** remote env `HERMES_DESKTOP=1`.
- **Edge cases / guards:** A changed `effectiveConfigFingerprint` (`effectiveSshConfigFingerprint(sshConfig)`, `main.ts:10054`, plus `sshConfigFingerprint` from `electron/ssh-bootstrap-coordinator.ts`) tears the old connection down first. A lifecycle failure on a *reused* master tears the cached entry down so the next attempt dials fresh (#82679). Publication is fenced by `fenceManagedSshBootstrapPublication({ assertCanPublish, publish, rollback })` so a managed update in flight cannot be raced; `rollbackSshBootstrapResult(...)` (`:10101`) unwinds a superseded bootstrap. `createBootstrapCoordinator()` (`electron/ssh-bootstrap-coordinator.ts`, 151 lines) hands out leases with `signal`, `assertCurrent()`, `onForceCleanup()`, and supports `shutdown()` / `forceCleanupAll()` / `promises()`.
- **Rebuild notes:** Make remote spawn one atomic shell command with a reservation + lockfile; anything multi-step races another desktop instance.

### SSH teardown  `id: desktop-main.ssh-teardown`
- **Surface:** Core
- **Where:** Invisible; on connection removal, config change, profile switch and quit.
- **What it does:** Cancels the port forward, stops the remote backend when it is provably ours, removes the lockfile, and closes the ControlMaster.
- **How it works:** `teardownSshConnection(profile)` (`main.ts:9882-9920`), `remoteLifecycle.disconnect(ssh, ownershipId)` and `cleanupStale(ssh, ownershipId, lock, pidAlive)` (`electron/remote-lifecycle.ts:647-735`), which builds an owned-termination command (`buildOwnedTerminationCommand` / `buildOwnedStaleTerminationCommand`) that only kills a process matching the recorded ownership. `teardownSshState` from `electron/connection-apply.ts`.
- **Inputs / options:** n/a
- **Outputs / side effects:** Remote process stopped; local port released.
- **Config / env:** n/a
- **Edge cases / guards:** `cleanupStale` waits up to 5 s (50 × 100 ms) for the owned pid to exit; the quit path races the whole SSH teardown against 6 s and then force-cleans, so `serve --isolated` is never left reparented to pid 1.
- **Rebuild notes:** Only terminate what you can prove you started.

### Remote liveness tracking and revalidation  `id: desktop-main.remote-liveness`
- **Surface:** Core
- **Where:** Invisible; drives reconnects after sleep/wake and network changes.
- **What it does:** Coalesces the revalidation N windows would each request into one probe, counts consecutive failures within a window, and rebuilds a dead remote connection.
- **How it works:** `electron/remote-liveness.ts` (458 lines): `REMOTE_LIVENESS_TIMEOUT_MS = 10_000`, `POOLED_REMOTE_DISPATCH_PROBE_TIMEOUT_MS = 2_500`, `REMOTE_LIVENESS_FAILURE_LIMIT = 3`, `REMOTE_LIVENESS_FAILURE_WINDOW_MS = 60_000`. Exports `RemoteLivenessTracker`, `RemoteRevalidationCoordinator`, `revalidateRemoteConnection`, `revalidatePooledRemoteBackends`, `revalidateSuspectPooledRemoteBackends`, `ensureHealthyPooledRemoteBackendForDispatch`, `attachPowerResumeRemoteRevalidation`. Instances in main: `remoteLiveness` (`main.ts:1382`), `remoteRevalidation` (`:1383`), `registryDispatchRevalidation` (`:1384`). IPC `hermes:connection:revalidate` (`:14244`).
- **Inputs / options:** `hermesDesktop.revalidateConnection()`.
- **Outputs / side effects:** `{ ok: true, rebuilt }`; possible re-dial.
- **Config / env:** n/a
- **Edge cases / guards:** A cached descriptor must prove its forwarded endpoint is alive before a click can use it — hence the much shorter dispatch probe budget.
- **Rebuild notes:** Count failures per connection with a window, not per caller.

### Managed SSH update transaction  `id: desktop-main.managed-ssh-update`
- **Surface:** Desktop app / Core
- **Where:** **Update all instances** and the update fan-out, for registered **SSH** connections.
- **What it does:** Updates a Desktop-managed SSH install transactionally: gate new dials → drain every Desktop-owned serve scope → run a detached `hermes update` on the remote → prove a correlated receipt → restore every scope → lift the gate.
- **How it works:** `electron/managed-ssh-update.ts` (1084 lines). Constants: `UPDATE_EXIT_INDEPENDENT_HANDOFF = 75`, `DEFAULT_REMOTE_UPDATE_TIMEOUT_MS = 3 600 000`, `DEFAULT_REMOTE_CLEARANCE_TIMEOUT_MS = 300 000`, `DEFAULT_REMOTE_UPDATE_POLL_MS = 1 000`, `RECEIPT_GRACE_MS = 15 000`, `UUID_RE`. Outcomes: `'updated' | 'update-failed' | 'restore-failed' | 'update-and-restore-failed' | 'refused'`. Exports `ManagedConnectionUpdateGate` (with `claim`/`release`/`assertCanDial`/`assertCanMutate`), `assertManagedUpdatePreflightClear`, `captureManagedSshScopes`, `drainManagedSshScope`, `executeManagedRemoteUpdate`, `fenceManagedSshBootstrapPublication`, `managedSshRecoveryScopes`, `managedSshScopeRole`, `managedSshTokenPersistencePlan`, `recoverManagedSshScopes`, `refusedManagedSshUpdate`, `runManagedSshUpdate`, `validateCorrelationId`, `waitForManagedRemoteClearance`, `waitForManagedSshBootstrapFence`, `waitForManagedUpdateOperations`, plus the `RemoteUpdateTarget` type (`{ ssh, platform: 'Darwin'|'Linux'|'Windows', hermesPath, hermesHome, pythonPath? }`) and `RemoteMarkerState` = `'absent'|'dead'|'live'|'malformed'|'unavailable'`. Main wires it at `main.ts:9671-9851` and `:11390-11870`: `requestManagedSshUpdate(rawId)` (`:15128`) single-flights per connection with a `crypto.randomUUID()` correlation id; `updateManagedSshConnection(source, correlationId)` (`:11735`); `openManagedSshUpdateTransport(...)` (`:11607`); `remoteUpdateTargetFromState(state)` (`:11589`); `ensureManagedSshBackend` / `ensureManagedSshBackendAtKey` / `restoreManagedPrimarySshBackend` (`:11390-11453`); `managedSshConfig(source, profile)` (`:11455`).
- **Inputs / options:** `connections.updateManaged(id)`.
- **Outputs / side effects:** `{ connectionId, correlationId, ok, updateOk, restoreOk, outcome, exitCode, receipt, scopes, error?, message? }`; a durable recovery journal.
- **Config / env:** n/a
- **Edge cases / guards:** Refusals (verbatim): `No connection with id "<id>".`; `Only registered Desktop-managed SSH connections can use this update lifecycle.`; `A managed update is already in progress.` `assertCanMutateManagedPrimaryRouting()` (`main.ts:9689`) blocks primary/launch-mode changes while a managed update owns the routing.
- **Rebuild notes:** Model a remote self-update as a transaction with an explicit correlation id and a receipt; anything less cannot distinguish "still running" from "finished badly".

### Managed-SSH crash recovery journal  `id: desktop-main.managed-ssh-recovery`
- **Surface:** Core
- **Where:** `<userData>/managed-ssh-update-recovery.json`.
- **What it does:** Survives a desktop crash mid-update: on the next launch a worker waits for the remote install marker to clear, reopens every scope the interrupted transaction had drained, then removes the journal entry.
- **How it works:** `readManagedSshRecoveryRecords()` (`main.ts:9709`), `writeManagedSshRecoveryRecords(records)` (`:9785`), `persistManagedSshRecovery(source, correlationId, scopes)` (`:9793`), `markManagedSshRecoveryLaunching(connectionId, correlationId)` (`:9812`), `clearManagedSshRecovery(connectionId, correlationId)` (`:9827`), `recoverManagedSshUpdate(record)` (`:11800`), `resumeManagedSshRecoveries()` (`:11866`) — invoked from `app.whenReady()` (`main.ts:17402`).
- **Inputs / options:** n/a
- **Outputs / side effects:** The journal file (owner-only); reopened SSH scopes.
- **Config / env:** n/a
- **Edge cases / guards:** `before-quit` joins in-flight managed updates and recoveries before any other teardown, so a detached remote updater is never cut off at the generic SSH deadline.
- **Rebuild notes:** Write the intent to disk before you act; a crash without a journal is an unrecoverable half-state.

### Hermes Cloud sign-in and agent discovery  `id: desktop-main.hermes-cloud`
- **Surface:** Desktop app
- **Where:** **Settings → Gateways → Connection mode → Hermes Cloud**; buttons for sign in / sign out, an organization picker, and the discovered agent list.
- **What it does:** One Nous Portal login powers discovery of your hosted agents and silent per-agent sign-in — no URL to paste, no second interactive login.
- **How it works:** All riding one portal session cookie in the OAuth partition. `DEFAULT_NOUS_PORTAL_URL = 'https://portal.nousresearch.com'` (`main.ts:7969`), overridable by `resolvePortalBaseUrl()` (`:7971`). `hasLivePortalSession()` (`:7991`) and `hasPortalAccessToken()` (`:8037`) check the Privy cookies — `PRIVY_SESSION_COOKIE_VARIANTS` = `__Host-privy-token`, `__Secure-privy-token`, `privy-token`, `privy-session`, `privy-refresh-token`; `PRIVY_ACCESS_COOKIE_VARIANTS` = the first three only (`electron/connection-config.ts:47-61`). `renewPortalAccessSilently()` (`main.ts:8078`, single-flighted in `portalAccessRenewal`) mints a fresh short-lived `privy-token` from long-lived renewal material so a cold start does not demand a re-login (#73495). `openPortalLoginWindow()` (`:8196`). `discoverCloudAgents(org?)` (`:8307`) GETs `<portal>/api/agents` over the partition-bound net; `trimCloudOrg` (`:8388`), `parseOrgSelectionError` (`:8405`) drives the organization picker, `trimCloudAgents` (`:8437`). `cloudAgentSilentSignIn(dashboardUrl)` (`:8460`). IPC: `hermes:cloud:status` → `{ … }` (`:15395`), `:login` (`:15399`), `:logout` (`:15404`), `:discover` (org) (`:15409`), `:agent-sign-in` (dashboardUrl) (`:15414`).
- **Inputs / options:** `hermesDesktop.cloud.status()`, `.login()`, `.logout()`, `.discover(org)`, `.agentSignIn(dashboardUrl)`.
- **Outputs / side effects:** Portal cookies in the shared partition; registry `cloud` entries.
- **Config / env:** portal base URL override.
- **Edge cases / guards:** Cloud entries always stay on the **legacy** shared cookie partition — the silent per-agent cascade deliberately shares one jar with the portal session. Cloud connections are skipped by the update fan-out (platform-managed).
- **Rebuild notes:** Separate "renewable session" from "valid access token"; only the second authorizes a call, but the first means no interactive login is needed.

### Remote auth-mode probe  `id: desktop-main.remote-probe`
- **Surface:** Desktop app
- **Where:** The remote-connection editor: the **Sign in** button adapts to what the backend advertises (**Sign in** for username/password, **Sign in with `<provider>`** for OAuth).
- **What it does:** Asks an unknown gateway URL which auth it requires, so the editor renders the right control.
- **How it works:** `probeRemoteAuthMode(rawUrl)` (`main.ts:10576-10641`), IPC `hermes:connection-config:probe`; classification helpers `authModeFromStatus(statusBody)` and `resolveAuthMode(inputAuthMode, existingAuthMode)` (`electron/connection-config.ts:906-940`); provider list via `gatewayAuthProviders(baseUrl, headers)` (`main.ts:6113`). `fetchConnectionStatus(baseUrl, authMode, token, headers)` (`:10797`) reads `/api/status`.
- **Inputs / options:** `hermesDesktop.probeConnectionConfig(remoteUrl)`.
- **Outputs / side effects:** `{ authMode, providers, … }`.
- **Config / env:** n/a
- **Edge cases / guards:** `auth_required: true` means "gated", **not** "speaks OAuth" — a password-provider gateway must not be hard-failed by the OAuth pre-flight guard (`oauthGuardMayHardFail`, `electron/native-auth-decisions.ts`).
- **Rebuild notes:** Let the server advertise its providers; never infer auth from the URL.

### Connection apply (soft re-home)  `id: desktop-main.connection-apply`
- **Surface:** Desktop app
- **Where:** **Save and reconnect** on the Gateways page.
- **What it does:** Switches the desktop shell onto a different backend without a window reload — tearing down the primary backend, wiping session lists and re-dialing.
- **How it works:** `ipcMain.handle('hermes:connection-config:apply', …)` (`main.ts:15427-15474`) → `applyConnectionConfigAtomically(...)` (`electron/connection-config-apply.ts`) and `applyConnectionChange` / `teardownSshState` (`electron/connection-apply.ts`). Teardown: `teardownPrimaryBackendAndWait({ soft })` (`:10856`), `resetHermesConnection({ soft })` (`:10840`), then `sendConnectionApplied()` (`:10875`) pushes `hermes:connection:applied`. `rehomePrimaryConnection(...)` (`electron/primary-connection-rehome.ts`) and `softRehomeInProgress` (`main.ts:1393`) guard the window. `abandonFirstRunSetupChoiceForRemoteApply()` resolves a first-run gate as `remote-applied`.
- **Inputs / options:** `hermesDesktop.applyConnectionConfig(payload)`; `hermesDesktop.onConnectionApplied(cb)`.
- **Outputs / side effects:** New primary backend; renderer wipes and re-dials.
- **Config / env:** n/a
- **Edge cases / guards:** Applying during first-run setup resumes the gated boot rather than falling through to a local install.
- **Rebuild notes:** A backend swap is a soft event; only reload the window when state cannot be reconciled.

---

## 7. Self-update, version reporting and uninstall

### Update check  `id: desktop-main.updates-check`
- **Surface:** Desktop app
- **Where:** **Settings → Updates**, the About panel, ⌘K **Update Hermes**, the update-ready toast.
- **What it does:** Reports whether the installed source tree is behind the tracked branch, how far, and what changed.
- **How it works:** `checkUpdates()` (`main.ts:2905-3058`), IPC `hermes:updates:check`. Steps: `resolveUpdateRoot()` (`:2820` — `HERMES_DESKTOP_HERMES_ROOT`, then the dev source root when unpackaged, then `ACTIVE_HERMES_ROOT`; prefers a candidate that has a `.git`); read the tracked branch from `<userData>/updates.json`; `resolveHealedBranch(updateRoot, branch)` (`:2882`) flips a deleted branch to `main` only on a definitive `git ls-remote --exit-code --heads` exit **2**, never on a network error; `getOriginUrl()`; on an official *SSH* remote (`isOfficialSshRemote`, `electron/update-remote.ts`) it uses `git ls-remote <OFFICIAL_REPO_HTTPS_URL> refs/heads/<branch>` instead of a fetch; otherwise `clearStaleGitLocks()` then `git fetch --quiet origin <branch>`; then `rev-parse HEAD`, `rev-parse origin/<branch>`, `status --porcelain`, `rev-parse --abbrev-ref HEAD`, `rev-parse --is-shallow-repository`; the behind count via `shouldCountCommits({ isShallow })` + `resolveBehindCount(...)` (`electron/update-count.ts`), falling back to `fetchCompareBehindCount({ currentSha, originUrl, targetSha })` (`main.ts:3060`) which calls the GitHub compare API (`compareApiUrl` + `parseCompareBehindCount`); the changelog via `readCommitLog(cwd, branch, isShallow)` (`:3109`) using `resolveCommitLogSelection` (`limit 1` at the remote tip for shallow clones, `limit 40` over `HEAD..origin/<branch>` for full clones).
- **Inputs / options:** `hermesDesktop.updates.check()`.
- **Outputs / side effects:** `{ supported, branch, currentBranch, behind, updateAvailable, currentSha, targetSha, commits, dirty, hermesRoot, fetchedAt }`, or `{ supported: false, reason: 'not-a-git-checkout', message: "<root> isn't a git checkout — desktop self-update only runs against a source install.", … }`, or `{ error: 'fetch-failed', message }`, or `{ error: 'check-failed', message }`.
- **Config / env:** `<userData>/updates.json` (`{ branch }`, default `main`).
- **Edge cases / guards:** A shallow clone can never produce a trustworthy count — `behind: null` means "update available, size unknown" and every surface must say so honestly rather than rendering a fabricated `1`. `ahead_by === 0` with differing tips means the local HEAD is *ahead*, not behind, so it is not flagged (which would nudge the user into wiping their work).
- **Rebuild notes:** Never fabricate a count; `null` is a first-class answer.

### Update branch selection  `id: desktop-main.updates-branch`
- **Surface:** Desktop app / Config
- **Where:** The updates settings row.
- **What it does:** Chooses which branch the self-updater tracks.
- **How it works:** `readDesktopUpdateConfig()` (`main.ts:2733`) / `writeDesktopUpdateConfig(config)` (`:2752`) over `<userData>/updates.json`, written with `writeFileAtomic` (`:2746`). Default `DEFAULT_UPDATE_BRANCH = 'main'`. IPC `hermes:updates:branch:get` → `{ branch }`; `hermes:updates:branch:set` (name) — an empty/blank name resets to `main`.
- **Inputs / options:** `hermesDesktop.updates.getBranch()`, `.setBranch(name)`.
- **Outputs / side effects:** `<userData>/updates.json`.
- **Config / env:** n/a
- **Edge cases / guards:** `resolveHealedBranch` self-heals a branch that origin no longer publishes.
- **Rebuild notes:** Persist the branch outside the app bundle so an update cannot reset it.

### Update apply — Windows hand-off  `id: desktop-main.updates-apply-windows`
- **Surface:** Desktop app / Platform:Windows
- **Where:** **Update now**. Progress message (verbatim): `Updating Hermes — this window will close and the updater will open. Don't reopen Hermes yourself; it restarts automatically when the update finishes.`
- **What it does:** Stops every backend it owns, waits for the venv shim to unlock, verifies no foreign process holds the install, then spawns a detached updater and quits so the update can replace locked files.
- **How it works:** `applyUpdates({ stopSafeBlockers })` (`main.ts:3635-3960`), IPC `hermes:updates:apply`. Order: `updateInFlight` mutex → `resolveUpdaterBinary()` (`resolveStagedUpdaterBinary(HERMES_HOME, …)`) → `updateHandoffConflict(HERMES_HOME)` refuses when a foreign updater already owns the marker (`{ ok:false, error:'update-already-running' }`) → progress `restart` → `repairMacUpdaterHelper(updater)` → resolve branch → `preflightStateDb` → `releaseBackendLockForUpdate(updateRoot)`; if not unlocked, abort with `Update aborted: another process is holding the Hermes install open (a second Hermes window or a terminal running hermes?). Close it and retry.` and restart the backend → Windows only: `scanVenvBlockers(updateRoot)` with optional user-approved `stopSafeVenvBlockers`, then up to **two** re-scans with a 1500 ms settle, then `formatBlockerMessage` / `formatProbeFailedMessage` (`electron/venv-blocker-scan.ts`, 323 lines) → prefer the repo-owned script hand-off `resolveUpdateScriptHandoff(updateRoot)` (`scripts/desktop-update/windows.ps1`, or the legacy flat `scripts/desktop-update.ps1`) over the frozen staged binary, wrapped by `wrapHandoffForDetachedConsole` through `cmd start` (a bare detached hidden PowerShell dies before `-File` processing) with args `-InstallRoot <root> -Branch <branch> -DesktopPid <pid> -RelaunchExe <execPath>` → `spawnUpdaterProcess(...)` detached, `stdio:'ignore'`, env `HERMES_HOME`, `HERMES_UPDATE_STARTED_AT`, `PATH=<managed node><venv Scripts>` → `writeUpdateMarker(HERMES_HOME, child.pid, { startedAt })` → `observeUpdaterHandoff(child, UPDATE_HANDOFF_DWELL_MS /* 2500 */)` → on success `isQuittingForHandoff = true` and quit after the remaining dwell.
- **Inputs / options:** `hermesDesktop.updates.apply({ stopSafeBlockers? })`.
- **Outputs / side effects:** `{ ok:true, handedOff:true, updater }`, `{ ok:true, manual:true, command, hermesRoot }`, or `{ ok:false, error:'venv-blocked'|'venv-probe-failed'|'updater-spawn-failed'|'update-already-running'|'apply-failed', message, blockers? }`.
- **Config / env:** env `HERMES_UPDATE_STARTED_AT` passed to the script.
- **Edge cases / guards:** With no staged updater **and** no script, the app surfaces the exact manual command branch-pinned to the current checkout (`hermes update` or `hermes update --branch <b>`) rather than a bare default that would switch a non-main install off-branch. The marker pre-write is skipped for staged updaters that predate self-adopt (`stagedUpdaterSupportsPrewrittenMarker`), because they would refuse their own claim in an unbreakable loop.
- **Rebuild notes:** Prefer a hand-off script that ships with the source, so each update refreshes the updater; and watch the detached child through a settle window before you quit into nothing.

### Update apply — POSIX hand-off  `id: desktop-main.updates-apply-posix`
- **Surface:** Desktop app / Platform:macOS / Platform:Linux
- **Where:** **Update now**. Progress message (verbatim): `Updating Hermes — this window will close. Don't reopen Hermes yourself; it restarts automatically when the update finishes.`
- **What it does:** Same shape as Windows minus the venv-lock gauntlet: quit → detached orchestrator script → `hermes update` → relaunch.
- **How it works:** `applyUpdatesPosixHandoff(opts)` (`main.ts:4181-4302`) via `resolvePosixScriptHandoff(updateRoot)` (`electron/updater-process.ts`). Args: `[...handoff.args, '--install-root', <root>, '--branch', <branch>, '--desktop-pid', <pid>]`, plus `--relaunch-target <runningAppBundle()|process.execPath>`; on non-macOS also `--relaunch-cwd <cwd>`, `--sandbox-fallback` when `sandboxFallbackFromEnv(process.env, relaunchArgs)`, and `-- <collectRelaunchArgs(process.argv.slice(1))>` so a deep-link or `--no-sandbox` launch context survives the update. Same marker bridge, same `observeUpdaterHandoff` dwell.
- **Inputs / options:** as above.
- **Outputs / side effects:** `{ ok:true, handedOff:true, updater }` or the manual/failed shapes.
- **Config / env:** n/a
- **Edge cases / guards:** A checkout that predates the script gets the manual `hermes update` card. The macOS failure mode this dwell exists for is exactly "the app quits, the script dies early, and the user is left with nothing" (#66753).
- **Rebuild notes:** Replay the original launch context on relaunch; a plain re-exec loses deep links and sandbox opt-outs.

### Update-in-progress marker and gate  `id: desktop-main.update-marker-gate`
- **Surface:** Core
- **Where:** `HERMES_HOME/.hermes-update-in-progress` (two lines: updater pid, unix-seconds start).
- **What it does:** Stops a relaunched desktop from spawning a backend that re-locks the venv while an update is running, and stops two updaters from mutating the checkout at once.
- **How it works:** `readLiveUpdateMarker(hermesHome, { kill, now, maxAgeMs })` (`electron/update-marker.ts:70-118`) returns `{ pid, ageMs }` only when the pid is genuinely alive (`isPidAlive` via signal 0; `EPERM` counts as alive) and the marker is younger than `UPDATE_MARKER_MAX_AGE_MS = 20 * 60 * 1000`; every "no live update" case deletes the file so it self-heals. `writeUpdateMarker(hermesHome, pid, { startedAt })` and `updateHandoffConflict(hermesHome)` complete the module. The gate is `updateGateReason({ hasLiveMarker, isUpdateInFlight })` → `'marker' | 'update-in-flight' | null` and `waitForUpdateClearance(deps, { timeoutMs, pollMs, onWaitTick, now, sleep })` → `'clear' | 'finished' | 'timeout'` (`electron/update-gate.ts`). Main wires it as `updateGateDeps()` (`main.ts:2147`) and `waitForUpdateToFinish()` (`:2157`) with `UPDATE_WAIT_TIMEOUT_MS = 20 * 60 * 1000` and `UPDATE_WAIT_POLL_MS = 1000`, used as `waitForLocalStart` in `runPrimaryBackendStartup`.
- **Inputs / options:** n/a
- **Outputs / side effects:** The marker file; parked backend starts.
- **Config / env:** n/a
- **Edge cases / guards:** The marker alone is insufficient (#73822): `applyUpdates` kills its backend *before* writing the marker, so the in-process `updateInFlight` flag closes that window. On timeout the caller proceeds anyway — a wedged updater must not brick the app forever.
- **Rebuild notes:** Two independent signals (on-disk + in-process) with an age ceiling; a single one always has a race.

### Update hand-off result surfacing  `id: desktop-main.handoff-result`
- **Surface:** Desktop app
- **Where:** A boot-time dialog after a detached update finishes.
- **What it does:** Reads `HERMES_HOME/.hermes-update-result.json` exactly once on the next launch and surfaces failures and action-required outcomes — a silent failed update otherwise looks identical to "nothing happened".
- **How it works:** `readAndConsumeHandoffResult(hermesHome, { now, maxAgeMs })` (`electron/handoff-result.ts:44-95`): reads, **unlinks unconditionally** (so a malformed or stale file cannot re-report forever), parses `{ ok, exit_code, manual, message, branch, finished_at }` and returns `{ ok, exitCode, manual, message, branch }`. `HANDOFF_RESULT_MAX_AGE_MS = 30 * 60 * 1000`; ordinary results older than that are dropped, but `manual: true` results are **exempt** — on a browserless Linux box the boot dialog is the only place the message ever surfaces.
- **Inputs / options:** n/a
- **Outputs / side effects:** The file is removed; the user sees a dialog.
- **Config / env:** n/a
- **Edge cases / guards:** Consumed at most once regardless of freshness.
- **Rebuild notes:** A detached updater must leave a receipt, and the app must consume it exactly once.

### Update progress channel  `id: desktop-main.updates-progress`
- **Surface:** Desktop app
- **Where:** The update overlay / toast.
- **What it does:** Broadcasts `{ stage, message, percent, error, at }` to **every** window during an update attempt.
- **How it works:** `emitUpdateProgress(payload)` (`main.ts:2867-2880`) merges over `{ stage:'idle', message:'', percent:null, error:null }`, logs `[updates] <stage>: <message|error>` and sends `hermes:updates:progress` to all `BrowserWindow.getAllWindows()`. Stages observed: `idle`, `restart`, `manual`, `error`.
- **Inputs / options:** `hermesDesktop.updates.onProgress(cb)`.
- **Outputs / side effects:** IPC + log.
- **Config / env:** n/a
- **Edge cases / guards:** Unlike boot progress, this goes to every window because any window can trigger an update.
- **Rebuild notes:** Broadcast anything that can be triggered from more than one window.

### Version reporting and the About panel  `id: desktop-main.version-about`
- **Surface:** Desktop app
- **Where:** **Settings → About**; macOS menu **About Hermes**; ⌘K.
- **What it does:** Reports the canonical Hermes version (not the Electron package version), the runtime versions, the install root, and whether the renderer bundle is stale.
- **How it works:** `resolveHermesVersion()` (`main.ts:16894-16921`) reads `__version__ = "…"` from `<updateRoot>/hermes_cli/__init__.py`, falling back to `app.getVersion()`. `ipcMain.handle('hermes:version', …)` (`:16944`) returns `{ appVersion, electronVersion: process.versions.electron, nodeVersion: process.versions.node, platform, hermesRoot, bundleOutOfSync, bundleCommitsBehind }`. `showAboutPanelFresh()` (`:16931`) re-resolves before each show and sets `app.setAboutPanelOptions({ applicationName: APP_NAME, applicationVersion, copyright: 'Copyright © 2026 Nous Research' })` — with the version suffixed `<version> — app build out of date, update the desktop app` when skew is detected.
- **Inputs / options:** `hermesDesktop.getVersion()`.
- **Outputs / side effects:** none.
- **Config / env:** n/a
- **Edge cases / guards:** `showAboutPanel()` is macOS-only; other platforms have no application menu (`Menu.setApplicationMenu(null)`).
- **Rebuild notes:** Report the version of the thing that does the work, not the shell that hosts it.

### Uninstall summary probe  `id: desktop-main.uninstall-summary`
- **Surface:** Desktop app
- **Where:** **Settings → About → Danger zone** — used to hide the agent-removing options when no local agent exists.
- **What it does:** Asks the agent what an uninstall would remove, without side effects.
- **How it works:** `getUninstallSummary()` (`main.ts:16977-17049`), IPC `hermes:uninstall:summary`. Spawns `<venvPython> -m hermes_cli.main uninstall --gui-summary` with `cwd = ACTIVE_HERMES_ROOT`, env `HERMES_HOME` + `NO_COLOR=1`, `stdio:['ignore','pipe','ignore']`, an 8000 ms timeout, and parses the **last** non-empty stdout line as JSON. Adds `running_app_path = resolveRemovableAppPath(process.execPath, process.platform, process.env)` — the Python probe only knows the standard locations, not where *this* build runs from. Falls back to a JS-side `{ hermes_home, agent_installed, gui_installed: true, source_built_artifacts: [], packaged_app_paths: [], userdata_dir, userdata_exists: true, platform, probe: 'fallback' }` whenever the venv python is missing, the spawn fails, the exit code is non-zero, the JSON is unparseable, or the timeout fires.
- **Inputs / options:** `hermesDesktop.uninstall.summary()`.
- **Outputs / side effects:** none.
- **Config / env:** n/a
- **Edge cases / guards:** A "lite client" with no bundled agent gets the fallback with `agent_installed: false`, so the agent/full options are hidden.
- **Rebuild notes:** Probe before you offer destructive options.

### Uninstall run (3 modes)  `id: desktop-main.uninstall-run`
- **Surface:** Desktop app
- **Where:** **Settings → About → Danger zone**: **Uninstall Chat GUI only**, **Uninstall GUI + agent, keep my data**, **Uninstall everything**.
- **What it does:** Runs the matching `hermes uninstall` mode through a detached cleanup script that waits for the app to exit, then quits.
- **How it works:** `runDesktopUninstall(mode)` (`main.ts:17051-17164`), IPC `hermes:uninstall:run` with `{ mode }`. `uninstallArgsForMode(mode)` (`electron/desktop-uninstall.ts:40-47`) maps `'gui' | 'lite' | 'full'` → `['-m','hermes_cli.uninstall','--mode',mode]` (the lightweight module entrypoint, not `hermes_cli.main`, so it can run under a *system* Python outside the venv that lite/full delete) and throws `Unknown uninstall mode: <mode>` otherwise. `modeRemovesAgent(mode)` = lite|full; `modeRemovesUserData(mode)` = full. Interpreter choice: gui-only uses the venv python; lite/full prefer `findSystemPython()` with `PYTHONPATH=<agentRoot>`, logging a warning on Windows when no system Python exists. `resolveRemovableAppPath` + `shouldRemoveAppBundle(IS_PACKAGED, appPath)` decide whether the app bundle itself is removed. `releaseBackendLock(ACTIVE_HERMES_ROOT, 'uninstall')` runs first (the same incident-hardened teardown as updates). The script is written to `<temp>/hermes-uninstall-<ts>.cmd` (run with `%ComSpec%|cmd.exe /c`) or `<temp>/hermes-uninstall-<ts>.sh` (mode 0755, run with `/bin/bash`) from `buildWindowsCleanupScript` / `buildPosixCleanupScript` with `{ desktopPid, pythonExe, pythonPath, agentRoot, uninstallArgs, appPath, hermesHome }`, spawned detached + unref'd. Then `isQuittingForHandoff = true` and `app.quit()` after 800 ms.
- **Inputs / options:** `hermesDesktop.uninstall.run(mode)` with mode ∈ `'gui' | 'lite' | 'full'`.
- **Outputs / side effects:** `{ ok:true, mode, willRemoveAppBundle, scriptPath }` or `{ ok:false, error:'invalid-mode'|'agent-missing'|'script-write-failed'|'spawn-failed', message }`; log `[uninstall] launched detached cleanup (<mode>): <script> (removesAgent=… removesUserData=… bundle=…)`.
- **Config / env:** n/a
- **Edge cases / guards:** Error `Can't run the uninstaller: no Hermes agent venv at <venvRoot>.` CLI equivalents: `hermes uninstall --gui`, `hermes uninstall`, `hermes uninstall --full`.
- **Rebuild notes:** Self-deletion needs a detached script that waits on your PID; never try to delete the venv you are running from.

---

## 8. Windows — primary, peers, session pop-outs, HUD, Quick Entry, overlays

### Primary window  `id: desktop-main.main-window`
- **Surface:** Desktop app
- **Where:** The app window itself. Title `Hermes`.
- **What it does:** The one full app window: frameless title bar with a renderer-painted band, restored geometry, theme-aware native surface, hidden until first themed paint.
- **How it works:** `createWindow()` (`main.ts:13932-14180`). Options: `computeWindowOptions(readWindowState(), screen.getAllDisplays())`, `minWidth: WINDOW_MIN_WIDTH /* 400 */`, `minHeight: WINDOW_MIN_HEIGHT /* 620 */`, `title: 'Hermes'`, `titleBarStyle: 'hidden'`, `titleBarOverlay: getTitleBarOverlayOptions()` (`:1133`), `trafficLightPosition: { x: 24, y: TITLEBAR_HEIGHT/2 - MACOS_TRAFFIC_LIGHTS_HEIGHT/2 }` on macOS (`TITLEBAR_HEIGHT = 34`, `MACOS_TRAFFIC_LIGHTS_HEIGHT = 14`), `...chatWindowSurfaceOptions()` (`:1084`, translucency backing), `icon: getAppIconPath()`, `show: false`, `webPreferences: chatWindowWebPreferences(PRELOAD_PATH)`. macOS also calls `setWindowButtonPosition` and `app.dock.setIcon(icon)`. Non-macOS installs a single `nativeTheme.on('updated')` listener that re-applies `applyTitleBarOverlay` to every window. Events wired: `will-enter-full-screen`, `enter-full-screen`, `will-leave-full-screen`, `leave-full-screen`, `minimize`, `restore`, `hide`, `show` → `sendWindowStateChanged(...)`; `move`/`resize` (via `bindGeometryPersistence`), `maximize`, `unmaximize` → `schedulePersistWindowState`; `close` → `schedulePersistWindowState.flush()`; `closed` → `closePetOverlay()`, `wakeIndicatorController.close()`, clear `mainWindow`, reset `_rendererReadyForDeepLink`. Then `streamThrottle.register`, `wireCommonWindowHandlers(win, zoomWiringForWindowKind('chat'))`, `installWindowRendererLifecycle`.
- **Inputs / options:** n/a
- **Outputs / side effects:** `<userData>/window-state.json`; the Windows sandbox marker is cleared to "booted" only after the window is genuinely revealed.
- **Config / env:** env `TEST_WORKER_INDEX` (Playwright) forces an immediate reveal because `ready-to-show` does not fire in some testing environments.
- **Edge cases / guards:** `createWindowRevealController(win, { onRevealed, delayMs: WINDOW_REVEAL_FALLBACK_MS /* 4000 */ })` (`electron/window-reveal.ts`) guarantees the window appears even if `ready-to-show` never fires. `ensureMainWindow(window, { isReady, createWindow, focusWindow, focusExisting })` (`electron/main-window-lifecycle.ts`) replaces a destroyed-but-truthy window before calling native methods.
- **Rebuild notes:** Keep the window hidden until the app has painted its own theme; a vibrancy window ignores `backgroundColor` and flashes the OS appearance.

### Window geometry persistence  `id: desktop-main.window-state`
- **Surface:** Desktop app / Config
- **Where:** `<userData>/window-state.json`.
- **What it does:** Reopens the app where the user left it, refusing garbage and off-screen positions.
- **How it works:** `electron/window-state.ts`: `DEFAULT_WIDTH = 1220`, `DEFAULT_HEIGHT = 800`, `MIN_WIDTH = 400`, `MIN_HEIGHT = 620`, `MIN_VISIBLE = 48`. `sanitizeWindowState(raw)` requires finite `width`/`height`, floors them to the minimums, keeps `x`/`y` only as a finite pair, and treats `isMaximized` strictly (`=== true`). `onScreen(bounds, displays)` requires ≥ 48 px overlap with some display's work area on **both** axes. `computeWindowOptions(state, displays)` always sets width/height, clamped to the largest current display's work area (so a size saved on a since-disconnected larger monitor cannot exceed today's screens), and sets `x`/`y` only when still on-screen (else Electron centers). `debounce(fn, delayMs)` with a `.flush()`. `GEOMETRY_EVENTS = ['move','resize']` — deliberately not `moved`/`resized`, which Electron only emits on darwin/win32, so a Linux window would never save its place. Main: `readWindowState()` (`main.ts:2759`), `persistWindowState()` (`:2770`), `schedulePersistWindowState = debounce(persistWindowState, 250)` (`:2788`).
- **Inputs / options:** n/a
- **Outputs / side effects:** The JSON file.
- **Config / env:** n/a
- **Edge cases / guards:** Persisted as soon as the window is revealed, so a crash before the first move still captures the restored bounds (#56726).
- **Rebuild notes:** Validate restored geometry against the *current* display set, every launch.

### Peer "instance" windows (New Window)  `id: desktop-main.instance-window`
- **Surface:** Desktop app
- **Where:** **File → New Window**; **Cmd/Ctrl+Shift+N**; ⌘K; `window.hermesDesktop.openWindow()`.
- **What it does:** Opens a complete second app window (full shell, own sidebar) that joins the already-running backend.
- **How it works:** `createInstanceWindow()` (`main.ts:12982-13051`), tracked in `instanceWindows: Set` (`:12962`), positioned by `nextInstanceBounds()` (`:12968`) → `instanceWindowBounds(base, fallback)` which cascades `INSTANCE_CASCADE_OFFSET = 32` px off the source window (`electron/session-windows.ts`). URL from `buildInstanceWindowUrl({ devServer, rendererIndexPath })` = `…?peer=1` — a `peer` marker rather than the `win` parameter, so the renderer knows this is a peer (no app-launch source restoration) but still renders the ordinary shell.
- **Inputs / options:** IPC `hermes:window:openInstance` → `{ ok: true }`.
- **Outputs / side effects:** A new BrowserWindow.
- **Config / env:** n/a
- **Edge cases / guards:** The menu item carries **no accelerator** — ⌘⇧N is a rebindable renderer keybind (`session.newWindow`) and a menu accelerator would fight the rebind panel (and be swallowed before the renderer sees it on macOS).
- **Rebuild notes:** Cascade new windows; stacking them exactly makes them look like one.

### Session pop-out windows  `id: desktop-main.session-window`
- **Surface:** Desktop app
- **Where:** A session's context menu → **New window**; the command palette; `window.hermesDesktop.openSessionWindow(sessionId, { watch })`.
- **What it does:** Opens one compact window per chat — a side panel showing a single conversation without the global sidebar; live output streams into every window showing that session.
- **How it works:** `createSessionWindow(sessionId, { watch })` (`main.ts:12868`) via `spawnSecondaryWindow({ sessionId, watch })` (`:12796`), registered in `sessionWindows = createSessionWindowRegistry()` (`:12778`). The registry's `openOrFocus(sessionId, factory)` guarantees **one window per chat**: an existing window is restored (if minimized), shown (if hidden) and focused instead of duplicated; a window removes itself on `closed`. Sizes: `SESSION_WINDOW_MIN_WIDTH = 420`, `SESSION_WINDOW_MIN_HEIGHT = 620`. URL from `buildSessionWindowUrl(sessionId, { devServer, rendererIndexPath, watch })` = `…?win=secondary[&watch=1]#/<sessionId>` — the query **must** precede the `#` or HashRouter swallows it. `watch=1` marks a spectator window (a running subagent's session): the renderer resumes it lazily so the gateway never builds an agent just to stream into it.
- **Inputs / options:** IPC `hermes:window:openSession` with `(sessionId, { watch })`; returns `{ ok: false, error: 'invalid-session-id' }` for a blank id.
- **Outputs / side effects:** A new BrowserWindow.
- **Config / env:** n/a
- **Edge cases / guards:** Shares `chatWindowWebPreferences` with the primary so the two cannot drift (a copy-paste divergence once made secondary windows stall a streamed answer until refocused).
- **Rebuild notes:** One shared `webPreferences` factory for every window of a kind.

### Chat window `webPreferences` contract  `id: desktop-main.chat-web-preferences`
- **Surface:** Core
- **Where:** Invisible; applies to the primary, session pop-outs, peer windows and the HUD.
- **What it does:** Fixes the security and media posture every chat-rendering window must share.
- **How it works:** `chatWindowWebPreferences(preloadPath)` (`electron/session-windows.ts:47-58`) returns `{ preload, contextIsolation: true, webviewTag: true, sandbox: true, nodeIntegration: false, devTools: true, autoplayPolicy: 'no-user-gesture-required', focusOnNavigation: false }`.
- **Inputs / options:** n/a
- **Outputs / side effects:** none.
- **Config / env:** n/a
- **Edge cases / guards:** `backgroundThrottling` is deliberately **absent** (managed at runtime by `streamThrottle`). `autoplayPolicy` is load-bearing for voice: a wake-word-started conversation has no preceding click, so the first reply's audio would be rejected with a silently swallowed `NotAllowedError`. `focusOnNavigation: false` stops an in-page SPA navigation from activating a blurred, streaming window (background focus theft).
- **Rebuild notes:** Every one of those five non-default flags is a bug fix; document them where they are set.

### Popped-out Browser windows  `id: desktop-main.browser-window`
- **Surface:** Desktop app
- **Where:** The in-app Browser tab's pop-out; `window.hermesDesktop.openBrowserWindow(tabId)`.
- **What it does:** Detaches an in-app browser tab into its own OS window; closing it docks the tab back.
- **How it works:** `createBrowserWindow(tabId)` (`main.ts:12949`) / `spawnBrowserWindow(tabId)` (`:12889`), registry `browserWindows = createSessionWindowRegistry()` (`:12875`), close notification `notifyBrowserPopoutClosed(tabId)` (`:12877`) → `hermes:browser-popout:closed`. Sizes from `electron/browser-windows.ts`: `BROWSER_WINDOW_WIDTH = 960`, `BROWSER_WINDOW_HEIGHT = 720`, `BROWSER_WINDOW_MIN_WIDTH = 480`, `BROWSER_WINDOW_MIN_HEIGHT = 400`. URL `buildBrowserWindowUrl(tabId, { devServer, rendererIndexPath })` = `…?win=browser[&tab=<id>]#/`.
- **Inputs / options:** IPC `hermes:window:openBrowser` (tabId) → `{ ok: true }` / `{ ok: false, error: 'invalid-tab-id' }`; `hermesDesktop.onBrowserPopoutClosed(cb)`.
- **Outputs / side effects:** A new BrowserWindow; the tab stays in renderer storage so it can be docked again.
- **Config / env:** n/a
- **Edge cases / guards:** Same query-before-hash contract.
- **Rebuild notes:** Keep the tab's state in the app, not the window, so a pop-out can dock back.

### Open session in the user's terminal  `id: desktop-main.open-in-terminal`
- **Surface:** Desktop app
- **Where:** A session's context menu; `window.hermesDesktop.openSessionInTerminal(sessionId, opts)`.
- **What it does:** Continues a chat in the user's own terminal emulator, running the TUI against that session.
- **How it works:** `ipcMain.handle('hermes:window:openInTerminal', …)` (`main.ts:14385-14436`): `resolveHermesBackend(tuiResumeArgs(sessionId, profile))` — **resolution only**, never `ensureRuntime()`, so a menu click can never kick off a first-run install; `sanitizeWorkspaceCwd(opts.cwd)`; writes a launcher script to `<userData>/open-in-terminal/hermes-<12 hex>.<ext>` (mode 0700) built by `buildTerminalScript({ args, command, cwd, env: terminalScriptEnv(backend.env, HERMES_HOME) })`; `resolveTerminalLaunch({ findOnPath, scriptPath })` picks an installed terminal emulator; spawns it `detached: true, stdio: 'ignore'` and `unref()`s so the terminal outlives the app and never inherits a pipe that would kill the TUI. All helpers in `electron/external-terminal.ts` (173 lines): `buildTerminalScript`, `resolveTerminalLaunch`, `terminalScriptEnv`, `terminalScriptExtension`, `tuiResumeArgs`.
- **Inputs / options:** `(sessionId, { profile?, cwd? })`.
- **Outputs / side effects:** `{ ok: true }` or `{ ok: false, error: 'invalid-session-id' | 'Hermes is not installed yet' | 'No terminal emulator found' | <message> }`; log `[terminal] opening session <id> via <command>`.
- **Config / env:** n/a
- **Edge cases / guards:** as above.
- **Rebuild notes:** Write a script rather than assembling a shell command — argv quoting across terminal emulators is a losing game.

### HUD mode window  `id: desktop-main.hud-window`
- **Surface:** Desktop app
- **Where:** **⌘/Ctrl+Shift+H** or the titlebar button. Window title `Hermes HUD` (`${APP_NAME} HUD`).
- **What it does:** Detaches the chat into a chrome-free, always-on-top floating bar over whatever you are working in; the app window steps aside and the HUD keeps the live conversation and composer.
- **How it works:** `spawnHudWindow(sessionId, profile)` (`main.ts:13524-13634`). BrowserWindow options: `...hudBounds()`, `minWidth: 380`, `minHeight: 160`, `title: HUD_WINDOW_TITLE`, `frame: false`, `transparent: true`, **`resizable: false`** (a transparent frameless window on Windows keeps a system edge-resize hot-zone that would grow the window a few px on every drag; the renderer's edge handles flip `resizable` on for the duration of a `hermes:hud:set-bounds` call), `enableLargerThanScreen: true` (macOS AppKit's `constrainFrameRect` otherwise clamps `setBounds` to the current display, making cross-monitor drag impossible), `movable: true`, `minimizable: false`, `maximizable: false`, `fullscreenable: false`, `skipTaskbar: !IS_MAC`, `hasShadow: false`, `alwaysOnTop: true`, `type: 'panel'` on macOS (so the frameless window never becomes the cmd-tab anchor), `roundedCorners: true`, `visualEffectState: 'active'` (vibrancy must keep rendering while blurred — streaming under another app *is* the feature), `hiddenInMissionControl: IS_MAC`, `show: false`, `backgroundColor: '#00000000'`, `webPreferences: chatWindowWebPreferences(PRELOAD_PATH)`. Then `applyHudElectronOverlay(win, platform)` (`electron/hud-overlay.ts`: `setAlwaysOnTop(true, darwin ? 'floating' : 'screen-saver')`, plus `setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true, skipTransformProcessType: true })` on macOS), `streamThrottle.register`, `wireCommonWindowHandlers`, `bindGeometryPersistence(win, schedulePersistHudState)`, `startHudCursorFeed(win)`, `startHudGameOverlayFeed(win)`, and on reveal `mainWindow.hide()` (when `hudRestoreMainWindow`) plus `promoteHudOverlay({ title: HUD_WINDOW_TITLE })`. Geometry: `HUD_WIDTH = 620`, `HUD_HEIGHT = 320`, `HUD_BOTTOM_MARGIN = 72`, `defaultHudBounds(area)` centers horizontally and parks 72 px above the work-area bottom (`electron/hud-geometry.ts`). Persisted at `HUD_STATE_PATH = <userData>/hud-state.json` via `readHudState()` (`main.ts:13247`), `persistHudState()` (`:13265`), `schedulePersistHudState = debounce(persistHudState, 250)` (`:13299`). URL `buildHudWindowUrl(sessionId, { devServer, profile, rendererIndexPath })` (`electron/hud-url.ts`, 39 lines) = `…?win=hud[&profile=<p>]#/<sessionId|>` — the profile is required because session ids are scoped per profile (#82285). Open/close: `openHudWindow(sessionId, profile)` (`:13649`), `closeHudWindow()` (`:13698`), `restoreMainWindowFromHud()` (`:13637`), `broadcastHudState(open)` (`:13514`) → `hermes:hud:changed` so every window's toggle stays truthful.
- **Inputs / options:** `hermesDesktop.hud.open(request)`, `.close()`, `.setIgnoreMouse(ignore)`, `.beginMove()`, `.endMove()`, `.moveBy(delta)`, `.setWorkspaceTransfer(transferring)`, `.setBounds(bounds)`, `.resetLayout()`, `.setFrost(showing)`, `.setSession(sessionId)`, `.onGoto(cb)`, `.onChanged(cb)`, `.onCursor(cb)`, `.onGameOverlay(cb)`, plus the synchronous `hud.nativeDrag` and `hud.windowing` snapshot. IPC channels: `hermes:hud:open`, `:close`, `:frost`, `:ignore-mouse`, `:begin-move`, `:end-move`, `:move-by`, `:set-bounds`, `:reset-layout`, `:session`, `:native-drag`, `:windowing`, `:workspace-transfer` (all in `electron/hud-ipc.ts`, 303 lines, registered at `main.ts:14472`).
- **Outputs / side effects:** `<userData>/hud-state.json`; the main window hidden/restored.
- **Config / env:** `desktop.ozone_platform_hint` (bridged to `ELECTRON_OZONE_PLATFORM_HINT`).
- **Edge cases / guards:** Closing from its own side (⌘W) still disposes the snap shortcut (idempotent) and restores the main window, so the user is never left with no surface.
- **Rebuild notes:** Every one of those BrowserWindow flags encodes a compositor quirk — copy the comments, not just the values.

### HUD windowing profile (per-compositor capabilities)  `id: desktop-main.hud-windowing`
- **Surface:** Core / Platform:Linux
- **Where:** Invisible; read synchronously by the preload before first paint (`ipcRenderer.sendSync('hermes:hud:windowing')`).
- **What it does:** Derives once, per platform/Ozone backend, whether the HUD can ignore the mouse, place itself, use native drag, transfer workspaces, or needs a polled cursor feed — so no call site re-derives "linux && click-through".
- **How it works:** `resolveHudWindowing(platform, env, argv)` (`electron/hud-windowing.ts:104-127`). macOS/Windows → `{ backend:'cocoa'|'win32', ignoreMouse:true, input:'click-through', move:'renderer', clientPlacement:true, controlDrag:false, workspaceTransfer:false, cursorFeed:false }`. Linux → `linuxOzoneBackend(env, argv)` reads `--ozone-platform=`/`--ozone-platform-hint=` from argv then `ELECTRON_OZONE_PLATFORM_HINT`, else follows the session (`XDG_SESSION_TYPE === 'wayland'`, or `WAYLAND_DISPLAY` set with no `DISPLAY`). Wayland → `{ ignoreMouse:true, input:'click-through', move:'native-drag', clientPlacement:false, controlDrag:false, workspaceTransfer:false, cursorFeed:true }`; X11 → `{ ignoreMouse:false, input:'solid', move:'renderer', clientPlacement:true, controlDrag:true, workspaceTransfer:true, cursorFeed:false }`. `hudWindowingView(windowing)` exposes only `{ clientPlacement, controlDrag, nativeDrag, solid, workspaceTransfer }` to the renderer.
- **Inputs / options:** env `XDG_SESSION_TYPE`, `WAYLAND_DISPLAY`, `DISPLAY`, `ELECTRON_OZONE_PLATFORM_HINT`; argv `--ozone-platform`, `--ozone-platform-hint`.
- **Outputs / side effects:** The capability object.
- **Config / env:** `desktop.ozone_platform_hint` (`auto` default; `x11` is the COSMIC always-on-top escape hatch, at the cost of click-through).
- **Edge cases / guards:** The **Ozone backend**, not the login session, is the normalizer — Electron 20+ prefers a native Wayland surface on a Wayland session.
- **Rebuild notes:** Derive a capability object once; scattering `if (linux)` checks guarantees drift.

### HUD drag, snap and cursor feed  `id: desktop-main.hud-drag-snap`
- **Surface:** Desktop app
- **Where:** Press-and-hold the composer then drag (macOS/Windows); **Ctrl + primary button** drag on Linux/X11; compositor drag handle on native Wayland. **⌘/Ctrl+Shift+G** snaps the bar to the pointer from any app.
- **What it does:** Moves the HUD under the cursor across monitors and DPI scales, and jumps it to the pointer on a global chord.
- **How it works:** Drag: `createHudDragSession()` (`electron/hud-drag.ts`) samples an absolute grab offset in main (`screen.getCursorScreenPoint()` is DIP while renderer PointerEvent coords are CSS px), then `origin(cursor)` returns the new window origin; driven by `hermes:hud:begin-move` / `:move-by` / `:end-move`. Snap: `createHudSnapShortcut(globalShortcut, applyHudSnapToPointer)` (`electron/hud-snap-shortcut.ts`) registers `DEFAULT_HUD_SNAP_SHORTCUT = 'CommandOrControl+Shift+G'`, returning `false` when another app already owns it; `register()`/`dispose()` are idempotent. `applyHudSnapToPointer()` (`main.ts:13314`) uses `snapHudBounds(cursor, anchor, windowSize, zoomFactor, workArea)` = `clampHudOrigin(windowOriginForCursorAnchor(cursor, anchor, zoomFactor), …)` with `HUD_SNAP_ANCHOR_Y = 48` (`main.ts:13308`) and a `minVisible = 40` clamp (`electron/hud-snap.ts`). Cursor feed: `startHudCursorFeed(win)` (`main.ts:13368`) polls every `HUD_CURSOR_POLL_MS = 60` on Linux/Wayland using `cursorPointInWindow(...)` (`electron/hud-cursor.ts`) and pushes `hermes:hud:cursor` (page coordinates or `null`), standing in for the `mousemove` that `setIgnoreMouseEvents(true, { forward: true })` delivers on macOS/Windows but not there.
- **Inputs / options:** as above.
- **Outputs / side effects:** Window position; renderer cursor events.
- **Config / env:** n/a
- **Edge cases / guards:** Electron's `globalShortcut` is press-only (no keyup), so this is tap-to-snap, not hold-to-follow. On native Wayland snapping is a no-op — the compositor owns placement.
- **Rebuild notes:** Sample the grab offset in the process that owns the window; mixing CSS px and DIP breaks on mixed-DPI setups.

### HUD reset layout  `id: desktop-main.hud-reset-layout`
- **Surface:** Desktop app
- **Where:** The discard control on the HUD bar.
- **What it does:** Restores the HUD's default size and (on X11/macOS/Windows) position — the escape hatch when a persisted size leaves the bar unusable.
- **How it works:** `resetHudWindowLayout()` (`main.ts:13279-13297`) → `applyHudResetBounds(...)` + `defaultHudBounds(workArea)` (`electron/hud-geometry.ts`); IPC `hermes:hud:reset-layout`.
- **Inputs / options:** `hermesDesktop.hud.resetLayout()`.
- **Outputs / side effects:** Window bounds + persisted HUD state.
- **Config / env:** n/a
- **Edge cases / guards:** Position is not restored on native Wayland (no client placement).
- **Rebuild notes:** Any persisted geometry needs a reset affordance.

### HUD game-overlay watch  `id: desktop-main.hud-game-overlay`
- **Surface:** Desktop app
- **Where:** Invisible; the renderer steps back to a low-opacity treatment when a fullscreen app owns the screen.
- **What it does:** Tells the HUD renderer when a fullscreen application (a game) is underneath it.
- **How it works:** `startHudGameOverlayFeed(win)` (`main.ts:13415`) → `startHudGameOverlayWatch(...)` (`electron/hud-game-overlay.ts`, 261 lines), pushing `hermes:hud:game-overlay`.
- **Inputs / options:** `hermesDesktop.hud.onGameOverlay(cb)`.
- **Outputs / side effects:** IPC pushes.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** An always-on-top overlay should yield visually when something else owns the screen.

### Hyprland overlay promotion  `id: desktop-main.hud-hyprland`
- **Surface:** Platform:Linux
- **Where:** Invisible; on Hyprland (including Omarchy) the HUD is floated and pinned after it maps.
- **What it does:** Speaks Hyprland's IPC so the HUD is not tiled like an ordinary window (where `always-on-top` is ignored and compositor drag does nothing). No user window rule needed.
- **How it works:** `promoteHudOverlay({ title })` (`electron/hud-overlay.ts:39-41`) → `promoteHudOnHyprland(options)` (`electron/hud-hyprland.ts`, 214 lines). Returns `true` when an adapter applied, `false` for "not that WM".
- **Inputs / options:** the window title, used to address the client over Hyprland IPC.
- **Outputs / side effects:** `float` + `pin` dispatches.
- **Config / env:** n/a
- **Edge cases / guards:** A few compositors (notably COSMIC) ignore `always-on-top` for native Wayland windows — the documented workaround is `desktop.ozone_platform_hint: x11`.
- **Rebuild notes:** Structure this as adapters (Sway/niri hang off the same function later).

### Quick Entry window  `id: desktop-main.quick-entry`
- **Surface:** Desktop app / Config
- **Where:** **Settings → Advanced → Quick Entry**; summoned by a global hotkey (default **Ctrl/Cmd+Shift+Space**).
- **What it does:** A small always-available composer summoned from anywhere on the system: type a prompt and it is handed to the primary renderer, which submits it through the normal prompt path.
- **How it works:** `electron/quick-entry.ts` (421 lines) + main (`:13730-13930`). Sizes `QUICK_ENTRY_WINDOW_WIDTH = 640`, `QUICK_ENTRY_WINDOW_HEIGHT = 168`, placed via `quickEntryWindowBounds(...)` centered horizontally at `QUICK_ENTRY_TOP_FRACTION = 0.22` down the active display. Settings persist at `QUICK_ENTRY_CONFIG_PATH = <userData>/quick-entry.json` (`{ enabled, shortcut }`), read with `sanitizeQuickEntrySettings(raw)` — a malformed file or a shortcut that no longer validates falls back to `DEFAULT_QUICK_ENTRY_SHORTCUT = 'CommandOrControl+Shift+Space'` rather than leaving the feature un-summonable. Registration: `createQuickEntryShortcut(globalShortcut, toggleQuickEntryWindow)`; applied at ready via `applyQuickEntrySettings(readQuickEntrySettings())` (`main.ts:17390`). Window functions: `quickEntryUrl()` (`:13756`), `spawnQuickEntryWindow()` (`:13764`), `repositionQuickEntryWindow(win)` (`:13848`), `showQuickEntryWindow()` (`:13857`), `hideQuickEntryWindow()` (`:13881`), `toggleQuickEntryWindow()` (`:13889`), `closeQuickEntryWindow()` (`:13922`).
- **Inputs / options:** `hermesDesktop.quickEntry.getSettings()`, `.setSettings(patch)`, `.submit(payload)`, `.dismiss()`, `.pushState(payload)`, `.onState(cb)`, `.onSubmit(cb)`, `.onShown(cb)`. IPC: `hermes:quick-entry:settings:get`, `:settings:set`, `:submit`, `:state`, `:dismiss`, `:shown`.
- **Outputs / side effects:** `<userData>/quick-entry.json`; a global accelerator; the primary renderer receives `hermes:quick-entry:submit`.
- **Config / env:** n/a
- **Edge cases / guards:** The quick window holds **no** gateway connection of its own. Main caches the latest pushed state (`quickEntryLastState`, `:13736`) so a freshly spawned quick window starts from truth. The accelerator is released on quit so a quitting Hermes never keeps another app's chord hostage.
- **Rebuild notes:** Keep the hotkey window dumb — capture text, hand it to the real client.

### Quick Entry accelerator validation  `id: desktop-main.quick-entry-accelerator`
- **Surface:** Desktop app / Config
- **Where:** The Quick Entry shortcut field; the row reports when another app already owns the chord.
- **What it does:** Validates and canonicalizes a user-typed Electron accelerator, enforcing two extra rules beyond Electron's grammar.
- **How it works:** `parseQuickEntryShortcut(raw)` (`electron/quick-entry.ts`) → `{ ok: true, accelerator }` or `{ ok: false, reason }` with `reason ∈ 'empty' | 'invalid-key' | 'invalid-modifier' | 'no-key' | 'no-modifier' | 'reserved'`. Accepted modifiers: `alt`, `altgr`, `cmd`, `cmdorctrl`, `command`, `commandorcontrol`, `control`, `ctrl`, `meta`, `option`, `shift`, `super`. Accepted named keys: `backspace`, `delete`, `down`, `end`, `enter`, `escape`, `home`, `insert`, `left`, `medianexttrack`, `mediaplaypause`, `mediaprevioustrack`, `mediastop`, `pagedown`, `pageup`, `plus`, `printscreen`, `return`, `right`, `space`, `tab`, `up`, `volumedown`, `volumemute`, `volumeup`; plus `F1`–`F24`, `num0`–`num9`/`numlock`/`numdec`/`numadd`/`numsub`/`nummult`/`numdiv`, single `a-z0-9`, and the punctuation set `! " # $ % & ' ( ) * + , - . / : ; < = > ? @ [ \ ] ^ _ \` { | } ~`. Canonical modifier casing map and stable order `CommandOrControl, Command, Control, Super, Alt, Option, AltGr, Shift`; duplicate modifiers collapse.
- **Inputs / options:** the raw shortcut string.
- **Outputs / side effects:** The canonical accelerator.
- **Config / env:** n/a
- **Edge cases / guards:** **At least one modifier is required** (a bare global key would steal that key from every app), and `Escape` may not be the key (inside the window Escape means "hide", so a global Escape binding would be un-toggleable). A modifier after the key (`A+Shift`) or two non-modifier keys (`Shift+A+B`) are rejected.
- **Rebuild notes:** Canonicalize so a saved shortcut round-trips identically however the user typed it.

### Pet overlay window  `id: desktop-main.pet-overlay`
- **Surface:** Desktop app
- **Where:** The pop-out mascot (pixel pet) floating over the desktop.
- **What it does:** Detaches the pet into a small always-on-top click-through window that can pop back or accept a composer submit.
- **How it works:** `spawnPetOverlayWindow(bounds)` (`main.ts:13080`), `openPetOverlay(bounds)` (`:13176`), `closePetOverlay()` (`:13197`), URL from `petOverlayUrl()` (`:13072`). IPC in `electron/pet-overlay-ipc.ts` (151 lines), registered via `registerPetOverlayIpc(...)`: `hermes:pet-overlay:open` (`{ bounds, screen }` → resolves with the screen bounds actually used), `:close`, `:set-bounds`, `:ignore-mouse`, `:set-focusable` (flips the overlay focusable and focuses it while the composer needs keys), `:state` (main renderer → overlay), `:control` (overlay → main renderer).
- **Inputs / options:** `hermesDesktop.petOverlay.open(request)`, `.close()`, `.setBounds(bounds)`, `.setIgnoreMouse(ignore)`, `.setFocusable(focusable)`, `.pushState(payload)`, `.control(payload)`, `.onState(cb)`, `.onControl(cb)`.
- **Outputs / side effects:** A frameless overlay window.
- **Config / env:** n/a
- **Edge cases / guards:** Zoom is opted **out** for this window (`wireCommonWindowHandlers(win, { zoom: false })`): the overlay sizes its own OS window to fit the sprite in unzoomed CSS px and has its own Alt+wheel scale, so inheriting global UI zoom would crop the mascot. Closed on `before-quit` and when the main window closes, so a stray pet cannot keep the process alive.
- **Rebuild notes:** Overlay windows need their own scale authority.

### Wake-word indicator window  `id: desktop-main.wake-indicator`
- **Surface:** Desktop app
- **Where:** A small pill that appears at the top-center of the built-in display when the wake word is detected / audio is capturing.
- **What it does:** Shows the wake-word state without raising the app.
- **How it works:** `createWakeIndicatorWindowController({...})` (`main.ts:13053`, implementation `electron/wake-indicator-window.ts`, 185 lines) with pure helpers in `electron/wake-indicator.ts`: `WAKE_INDICATOR_WINDOW_WIDTH = 176`, `WAKE_INDICATOR_WINDOW_HEIGHT = 52`, `WAKE_INDICATOR_FADE_MS = 500`, states `['hidden','detected','capturing']`, `normalizeWakeIndicatorState(value)` (anything else → `hidden`), `selectWakeIndicatorDisplay(displays, primary)` (prefers `display.internal === true`), `wakeIndicatorWindowBounds(display)` (top-centered on that display). IPC: `hermes:wake-indicator:get` → current state; `hermes:wake-indicator:set` (state); push `hermes:wake-indicator:state`.
- **Inputs / options:** `hermesDesktop.wakeIndicator.getState()`, `.setState(state)`, `.onState(cb)`.
- **Outputs / side effects:** A tiny always-on-top window.
- **Config / env:** n/a
- **Edge cases / guards:** macOS re-positions it on `display-added`, `display-metrics-changed` and `display-removed` (`main.ts:17392-17400`). Closed on `before-quit` and when the main window closes.
- **Rebuild notes:** Prefer the internal display for a status pill — that is where the laptop's mic is.

### Link-title preview window  `id: desktop-main.link-title-window`
- **Surface:** Core
- **Where:** Invisible; used when a pasted link needs a title that only a rendered page can supply.
- **What it does:** Renders a URL in a hidden offscreen window to read its `<title>` when the cheap HTTP fetch cannot.
- **How it works:** `createLinkTitleWindow(...)`, `guardLinkTitleSession(...)`, `readLinkTitleWindowTitle(...)` (`electron/link-title-window.ts`, 75 lines); main's `runRenderTitleJob(rawUrl)` (`:5486`) / `fetchHtmlTitleWithRenderer(rawUrl)` (`:5567`). Budget: `RENDER_TITLE_MAX_CONCURRENT = 2`, `RENDER_TITLE_TIMEOUT_MS = 8000`, `RENDER_TITLE_GRACE_MS = 700`, with a queue (`renderTitleQueue`, `dequeueRenderTitle`). `RENDER_TITLE_BLOCKED_RESOURCES` blocks heavy subresources. The offscreen renderer runs in its own cache-less partition `session.fromPartition('hermes:link-titles', { cache: false })` (`main.ts:5465`), guarded by `guardLinkTitleSession`.
- **Inputs / options:** n/a
- **Outputs / side effects:** A hidden window per job.
- **Config / env:** n/a
- **Edge cases / guards:** The session is guarded so the renderer cannot become a general-purpose browser.
- **Rebuild notes:** Try HTTP first; only render when the page needs JS.

---

## 9. Native chrome — menus, shortcuts, deep links, notifications, dock/tray

### Application menu (macOS only)  `id: desktop-main.application-menu`
- **Surface:** Desktop app / Platform:macOS
- **Where:** The macOS menu bar. On Windows and Linux `Menu.setApplicationMenu(null)` — there is no application menu at all (`main.ts:17372-17376`, #77845).
- **What it does:** Provides the native menu with About/Updates, window/file actions, edit roles, view/zoom and help.
- **How it works:** `buildApplicationMenu()` (`main.ts:6496-6613`). Complete template, verbatim labels:
  - **`Hermes`** (APP_NAME): `About Hermes` → `showAboutPanelFresh()`; `Check for Updates…` → `sendOpenUpdatesRequested()`; separator; role `services`; separator; roles `hide`, `hideOthers`, `unhide`; separator; role `quit`.
  - **`File`**: `New Window` → `createInstanceWindow()`; `Open Folder…` → `sendOpenFolderRequested()`; separator; on macOS `Close` → `sendClosePreviewRequested()` (deliberately **no** accelerator so the `before-input-event` hook can route ⌘W to close-active-tab), elsewhere role `quit`.
  - **`Edit`**: roles `undo`, `redo`, separator, `cut`, `copy`, `paste`, `pasteAndMatchStyle` (⇧⌘V only works because this item exists — an accelerator with no menu entry is never translated into an editor command), `delete`, `selectAll`.
  - **`View`**: `Reload` → `sendPreviewNavCommand('reload')` (not `role: 'reload'`, which would hard-reload the whole shell; no accelerator because ⌘R is claimed in `installPreviewShortcut`); role `forceReload`; `Toggle Developer Tools` with accelerator `Alt+Cmd+I` (darwin) / `Ctrl+Shift+I`; separator; `Actual Size` `CommandOrControl+0`; `Zoom In` `CommandOrControl+Plus`; `Zoom Out` `CommandOrControl+-`; separator; role `togglefullscreen`.
  - **`Window`**: macOS roles `minimize`, `zoom`, `front`; elsewhere `minimize`, `close`.
  - **`Help`** (role `help`): `Check for Updates…`.
- **Inputs / options:** n/a
- **Outputs / side effects:** `hermes:open-updates`, `hermes:open-folder-requested`, `hermes:close-preview-requested`, `hermes:preview-nav` IPC to the renderer.
- **Config / env:** env `HERMES_DESKTOP_APP_NAME` renames the app (dev sandboxing).
- **Edge cases / guards:** Accelerators are deliberately omitted where a rebindable renderer keybind owns the chord (⌘⇧N `session.newWindow`, ⌘O `workspace.openFolder`, ⌘W, ⌘R).
- **Rebuild notes:** When your app has a rebindable keymap, the OS menu must not also claim those chords.

### DevTools shortcut and the F12 block  `id: desktop-main.devtools-shortcut`
- **Surface:** Desktop app / Config
- **Where:** **Ctrl+Shift+I** / **Cmd+Opt+I**, and **F12**; **Settings → Advanced** has the "disable F12" toggle.
- **What it does:** Opens DevTools detached from any window (enabled even in packaged builds so field issues can be diagnosed), and lets the user block F12.
- **How it works:** `installDevToolsShortcut(window)` (`main.ts:6644-6672`) hooks `before-input-event`: `F12` is `preventDefault()`ed when `f12Blocked`, otherwise it falls through and opens DevTools; `Cmd+Alt+I` (mac) / `Ctrl+Shift+I` always toggles. `toggleDevTools(window)` (`:6630`) opens with `{ mode: 'detach' }`. The preference is persisted and read by `readPersistedDisableF12()` (`:16669`), set through `ipcMain.on('hermes:devtools:disable-f12', …)` (`:16677`) and applied at ready (`f12Blocked = readPersistedDisableF12()`, `:17384`).
- **Inputs / options:** `hermesDesktop.setDisableF12(blocked)`.
- **Outputs / side effects:** A JSON preference under `userData`; DevTools windows.
- **Config / env:** n/a
- **Edge cases / guards:** Documented trade-off: a tiny attack-surface increase versus a much better support story.
- **Rebuild notes:** Ship DevTools; gate only the accidental key.

### ⌘W / ⌘R interception  `id: desktop-main.preview-shortcut`
- **Surface:** Desktop app
- **Where:** **Cmd/Ctrl+W** closes the focused tab (or window); **Cmd/Ctrl+R** reloads a focused in-app page.
- **What it does:** Claims the two chords in the main process so they mean the app-level thing on every platform.
- **How it works:** `installPreviewShortcut(window)` (`main.ts:6674-6716`), `before-input-event`: `w` + accel (no alt, no shift) → `sendClosePreviewRequested()` (`:6244`, channel `hermes:close-preview-requested`); `r` + accel (no shift) → `sendPreviewNavCommand('reload')` (`:6304`). `⇧⌘R` is left alone (that is `forceReload`, the unconditional escape hatch). `commandFocusedGuest(command)` (`:6271`) routes `back`/`forward`/`reload` to a focused `<webview>` guest when there is one; `installBrowserNavGestures(window)` (`:6333`) wires mouse back/forward buttons.
- **Inputs / options:** `hermesDesktop.setPreviewShortcutActive(active)` (channel `hermes:previewShortcutActive`) — the renderer reports whether a preview owns the chord; `hermesDesktop.onClosePreviewRequested(cb)`, `.onPreviewNav(cb)`.
- **Outputs / side effects:** IPC to the focused window.
- **Config / env:** n/a
- **Edge cases / guards:** ⌘W is claimed unconditionally (the File → Close item has no accelerator, so nothing else does) and the renderer decides tab-vs-window.
- **Rebuild notes:** The application menu only exists on macOS, so a menu accelerator would leave Windows/Linux with no binding at all.

### Zoom (UI scale)  `id: desktop-main.zoom`
- **Surface:** Desktop app / Config
- **Where:** **View → Actual Size / Zoom In / Zoom Out**; **Ctrl/Cmd + `+` / `-` / `0`**; **Settings → Appearance → UI Scale**.
- **What it does:** One clamped zoom scale shared by the menu, the keyboard, and the settings control, persisted per window origin and re-asserted when Chromium drops it.
- **How it works:** `electron/zoom.ts` (214 lines). `ZOOM_FACTOR_BASE = 1.2`, `MIN_ZOOM_LEVEL = -9`, `MAX_ZOOM_LEVEL = 9`, `ZOOM_STEP = 0.1` (half Chromium's default step), `DEFAULT_ZOOM_LEVEL = log(0.9)/log(1.2)` — the shipped Appearance **90%** preset. `clampZoomLevel`, `zoomLevelToPercent`, `percentToZoomLevel`, `applyZoomLevel(webContents, level)` (applies **and** emits `hermes:zoom:changed` in that order, so the settings control can never drift). Persistence rides the renderer's `localStorage` under `ZOOM_STORAGE_KEY = 'hermes:desktop:zoomLevel'`, mirrored from main; also `<userData>/zoom-state.json` (`readZoomState` `:2797` / `writeZoomState` `:2808`). Re-assert: `installZoomReassertOnNavigation`, `installZoomReassertOnWindowEvents`, `zoomReassertWindowEvents(platform)`, `ZOOM_RESIZE_REASSERT_DELAY_MS = 100`, `ZOOM_REASSERT_SETTLE_DELAY_MS = 300`, `ZOOM_REASSERT_MAX_SETTLE_CHECKS = 3` — Chromium drops zoom on resize, minimize/restore, a monitor-scale change, or a focus round-trip on Windows high-DPI. `zoomWiringForWindowKind(kind)` selects the wiring per window kind. Main: `setAndPersistZoomLevel(window, level)` (`:6718`), `restorePersistedZoomLevel(window)` (`:6740`), `installZoomShortcuts(window)` (`:6790`).
- **Inputs / options:** `hermesDesktop.zoom.get()` → `{ level, percent }`; `.factor()` (synchronous `webFrame.getZoomFactor()`, because coordinate math needs it in the same tick as the event); `.setPercent(percent)`; `.onChanged(cb)`. IPC `hermes:zoom:get`, `hermes:zoom:set-percent`, `hermes:zoom:changed`.
- **Outputs / side effects:** Per-window zoom level; persisted preference.
- **Config / env:** n/a
- **Edge cases / guards:** Reads and writes target **the asking window**, so a secondary window's zoom is its own. The Linux settle-verify chain is bounded and drift-guarded, so a window already at the persisted level costs nothing.
- **Rebuild notes:** Apply-and-notify in one function; a silent apply is how a settings control gets stuck.

### Translucency / glass  `id: desktop-main.translucency`
- **Surface:** Desktop app / Config
- **Where:** **Settings → Appearance** translucency controls (row hidden entirely on Linux).
- **What it does:** Paints chat windows with a native material (macOS vibrancy / Windows 11 DWM backdrop) or a "clear" opacity ramp, consistently from the first frame.
- **How it works:** Mapping lives in `apps/shared/src/translucency.ts` (so renderer and main cannot drift) and is re-exported by `electron/translucency.ts`: `GLASS_MATERIALS`, `GLASS_SCOPES`, `WINDOWS_BACKGROUND_MATERIALS`, `WINDOWS_GLASS_MIN_BUILD`, `TRANSLUCENCY_CURVE`, `TRANSLUCENCY_MIN`, `TRANSLUCENCY_MAX`, `TRANSLUCENCY_OPACITY_FLOOR`, `DEFAULT_GLASS_MATERIAL`, `DEFAULT_GLASS_SCOPE`, `defaultTranslucencyState`, `normalizeState/Mode/Material/Scope/Book`, `glassActive`, `glassSupportedOn`, `translucencySupportedOn`, `vibrancyFor`, `backgroundMaterialFor`, `windowOpacityFor`, `hudFrostFor`, `glassSurfaceKeep`, `resolveTranslucency`. Electron-only additions: `windowBackingOptions(state, themedColor)` — glass active ⇒ **omit** `backgroundColor` entirely (Electron gives a vibrancy/backdrop window a transparent default backing; an alpha color would need `transparent: true` and `#00000000` on a normal window is quietly treated as opaque), glass inactive ⇒ the opaque themed color — and `opacityNeedsSetting` / `windowOpacityOptions` (on Windows `setOpacity` adds `WS_EX_LAYERED`, which is not free). Main: `GLASS_SUPPORTED = glassSupportedOn(process.platform, os.release())` (`:460`), `TRANSLUCENCY_SUPPORTED = translucencySupportedOn(process.platform)` (`:463`), state at `TRANSLUCENCY_CONFIG_PATH = <userData>/translucency.json` (`readPersistedTranslucency` `:969`, `writePersistedTranslucency` `:982`, debounced by `scheduleTranslucencyWrite` `:16491`), applied by `applyWindowOpacity(win)` (`:1003`) and `applyWindowTranslucency(win, { backing, material, opacity })` (`:1036`), constructor options from `chatWindowSurfaceOptions()` (`:1084`). `translucencyBackedWindows` is a `WeakSet` of chat surfaces (`:997`). Preload reads support synchronously before first paint via `ipcRenderer.sendSync('hermes:translucency:support')` → `{ glass, translucency }` (`main.ts:16521`).
- **Inputs / options:** `hermesDesktop.glassSupported`, `.translucencySupported`, `.setTranslucency(payload)` (channel `hermes:translucency`), `hermesDesktop.hud.setFrost(showing)`.
- **Outputs / side effects:** `<userData>/translucency.json`; native window materials.
- **Config / env:** n/a
- **Edge cases / guards:** The synchronous preload read deliberately avoids importing `node:os` in the sandboxed preload — a throw there would take the **entire** `window.hermesDesktop` bridge down ("Desktop IPC bridge is unavailable"); no reply degrades to an ordinary opaque window.
- **Rebuild notes:** Decide the backing at construction; a post-creation `setBackgroundColor` swap is unreliable in a fresh process.

### Native theme + title-bar overlay  `id: desktop-main.native-theme`
- **Surface:** Desktop app
- **Where:** Invisible; the native window appearance (vibrancy material, titlebar, pre-first-paint background) follows the **app** theme, not the OS.
- **What it does:** Pins `nativeTheme.themeSource` to the renderer's mode and persists it so a cold launch paints correctly before the renderer loads.
- **How it works:** `NATIVE_THEME_CONFIG_PATH = <userData>/native-theme.json`; `THEME_SOURCES = new Set(['dark','light','system'])` (`main.ts:931`); `readPersistedThemeSource()` (`:933`), `writePersistedThemeSource(mode)` (`:947`); `ipcMain.on('hermes:native-theme', (…, mode) => …)` (`:16468`). Title-bar overlay: `TITLEBAR_OVERLAY_COLOR = 'rgba(1, 0, 0, 0)'` (`:1131`), `getTitleBarOverlayOptions()` (`:1133`), `applyTitleBarOverlay(win)` (`:1164`), `getWindowBackgroundColor()` (`:1121`), `isHexColor(value)` (`:1114`), `rendererTitleBarTheme` (`:919`) set via `ipcMain.on('hermes:titlebar-theme', …)` (`:16449`). Overlay width: `computeNativeOverlayWidth` + `macTitleBarOverlayHeight` (`electron/titlebar-overlay-width.ts`), `getNativeOverlayWidth()` (`:6209`), `getWindowButtonPosition(win)` (`:6195`).
- **Inputs / options:** `hermesDesktop.setNativeTheme(mode)`, `.setTitleBarTheme(payload)`.
- **Outputs / side effects:** `<userData>/native-theme.json`; native chrome colors.
- **Config / env:** n/a
- **Edge cases / guards:** With `vibrancy` set, macOS ignores `backgroundColor` and tracks the window's effective appearance, so a dark app on a light Mac would flash white on every new window without this pin.
- **Rebuild notes:** Persist the theme in the main process — the renderer loads too late to prevent the flash.

### Window state broadcast  `id: desktop-main.window-state-changed`
- **Surface:** Core
- **Where:** Drives the renderer's traffic-light inset and fullscreen chrome.
- **What it does:** Pushes `{ isFullscreen, … }` to a window's renderer whenever its chrome state changes.
- **How it works:** `getWindowState(win)` (`main.ts:6213`) and `sendWindowStateChanged(nextIsFullscreen?, target = mainWindow)` (`:6476`) → `hermes:window-state-changed`. Any full chat window passes itself so its own fullscreen toggle drives its own inset.
- **Inputs / options:** `hermesDesktop.onWindowStateChanged(cb)`.
- **Outputs / side effects:** IPC.
- **Config / env:** n/a
- **Edge cases / guards:** Guarded against destroyed windows/webContents.
- **Rebuild notes:** Chrome insets are per-window; a global broadcast is wrong.

### `hermes://` deep links  `id: desktop-main.deep-links`
- **Surface:** Desktop app / Env
- **Where:** Any `hermes://…` URL — e.g. `hermes://blueprint/morning-brief?time=08:00`, `hermes://mcp/install?name=NAME&config=B64` (the vendor "Add to Hermes" button), `hermes://plugin/install?repo=owner/repo`, `hermes://index-network/…`.
- **What it does:** Routes an OS-level URL into the running app as a `{ kind, name, params }` payload the renderer dispatches; anything install-shaped requires explicit user confirmation there.
- **How it works:** `HERMES_PROTOCOL = DEV_SERVER ? 'hermes-dev' : 'hermes'`; `DEEPLINK_SCHEMES = DEV_SERVER ? ['hermes-dev','hermes'] : ['hermes']` (`main.ts:17192-17194`). `registerDeepLinkProtocol()` (`:17274`) calls `app.setAsDefaultProtocolClient(HERMES_PROTOCOL)` — in dev (`process.defaultApp && argv.length >= 2`) with `process.execPath` and the resolved entry script so the OS can relaunch. `_extractDeepLink(argv)` (`:17198`) finds the first argv entry starting with an accepted scheme. `handleDeepLink(url)` (`:17206-17253`) parses with `URL`, rejects a malformed URL (`[deeplink] ignoring malformed url: <url>`) or a foreign scheme (`[deeplink] ignoring scheme <s> (expected <list>)`), then builds `{ kind: parsed.hostname, name: decodeURIComponent(pathname without leading '/'), params: {…searchParams} }`. Delivery paths: macOS `app.on('open-url')` (registered early, before `whenReady`); Windows/Linux running app via `app.on('second-instance', argv)`; Windows/Linux cold start from `process.argv` after `createWindow()`. If the renderer has not signalled readiness the payload is queued in `_pendingDeepLink` and flushed exactly once by `ipcMain.handle('hermes:deep-link-ready', …)` (`:17259`), which re-serializes the payload back into a URL. Delivery restores + focuses the window and sends `hermes:deep-link`, logging `[deeplink] delivered <kind>/<name>` or `[deeplink] delivery failed: <message>`.
- **Inputs / options:** `hermesDesktop.onDeepLink(cb)`, `.signalDeepLinkReady()` → `{ ok: true }`.
- **Outputs / side effects:** OS protocol registration; IPC delivery.
- **Config / env:** env `HERMES_DESKTOP_DEV_SERVER` switches the registered scheme to `hermes-dev` (bare Electron or a stale OS handler often owns `hermes://` on dev machines).
- **Edge cases / guards:** `_rendererReadyForDeepLink` is reset when the main window closes, so a replacement renderer must re-register before queued links are delivered. The single-instance lock is what makes routing into a running app possible at all.
- **Rebuild notes:** Queue until the renderer says it is listening, and flush exactly once.

### Native notifications  `id: desktop-main.notifications`
- **Surface:** Desktop app
- **Where:** OS notification center; clicking one focuses the app and jumps to the session.
- **What it does:** Shows an OS notification with an optional icon, silence flag and action buttons, and routes clicks/actions back to the renderer.
- **How it works:** `ipcMain.handle('hermes:notify', …)` (`main.ts:16064-16139`). Returns `false` when `Notification.isSupported()` is false. Deduplicates on `` `${payload.kind}:${payload.sessionId ?? payload.tag}` `` via `isDuplicateNotification` and returns **`true`** for a duplicate (a notification for the event *is* being shown by the first caller, so the "send test" probe stays honest). Constructs `new Notification({ title: payload.title || 'Hermes', body: payload.body || '', silent: Boolean(payload.silent), icon?, actions: payload.actions.map(a => ({ type: 'button', text: String(a.text || '') })) })`. `click` → `focusWindow(mainWindow)`, then `hermes:focus-session` with `payload.sessionId`, and/or `hermes:notification-activate` with `{ activate, notifyId, tag }`. `action` → for a session-scoped approval, `hermes:notification-action` with `{ sessionId, actionId }`; otherwise focus + `hermes:notification-activate` with `{ actionId, activate, notifyId, tag }`.
- **Inputs / options:** `hermesDesktop.notify({ title, body, silent, icon, actions: [{ id, text, activate? }], sessionId, tag, notifyId, activate, kind })`; `hermesDesktop.onNotificationAction(cb)`, `.onNotificationActivate(cb)`, `.onFocusSession(cb)`.
- **Outputs / side effects:** An OS notification; IPC callbacks; returns `true`/`false`.
- **Config / env:** n/a
- **Edge cases / guards:** Action buttons render only on signed macOS builds; elsewhere they are dropped and the body click still works.
- **Rebuild notes:** Deduplicate in the shared process and return "shown" for the duplicate, or your test button lies.

### Ambient-cue claim  `id: desktop-main.ambient-claim`
- **Surface:** Core
- **Where:** Invisible; the turn-end sound and spoken replies.
- **What it does:** Lets exactly one window own a one-shot ambient cue when several are open.
- **How it works:** `ipcMain.handle('hermes:ambient:claim', (_e, key) => !claimedAmbientCue(String(key ?? '')))` (`main.ts:16062`).
- **Inputs / options:** `hermesDesktop.claimAmbientCue(key)` → `true` for the winner.
- **Outputs / side effects:** none.
- **Config / env:** n/a
- **Edge cases / guards:** 1 s dedupe window.
- **Rebuild notes:** see `desktop-main.event-dedupe`.

### Dock / taskbar icon  `id: desktop-main.app-icon`
- **Surface:** Desktop app
- **Where:** The dock (macOS), taskbar (Windows), window icon (Linux).
- **What it does:** Resolves a decodable icon from a per-platform candidate ladder, never taking the main process down on a corrupt asset.
- **How it works:** `appIconCandidates({ isWindows, appRoot, resourcesPath, unpackedPathFor })` builds the ladder once (`main.ts:912`); `resolveAppIcon(paths)` re-resolves per window with a **decoding probe**, not just an existence check (`electron/app-icon.ts`, 85 lines). `getAppIconPath()` (`:6442`) catches and returns `undefined` so the platform default is used. macOS additionally calls `app.dock?.setIcon(icon)`.
- **Inputs / options:** n/a
- **Outputs / side effects:** Window/dock icon.
- **Config / env:** n/a
- **Edge cases / guards:** Windows prefers the full-bleed `assets/icon.ico` (shipped to `resources/` via `extraResources`) because the apple-touch PNG bakes in a ~10% margin that reads visibly smaller than neighbouring taskbar icons; it falls back to the PNG when the ico is missing. A truncated PNG inside `app.asar` previously crashed `createWindow` mid-session — hence the decode probe.
- **Rebuild notes:** Existence is not proof the bytes decode.

### macOS Dock activate / window-all-closed  `id: desktop-main.dock-activate`
- **Surface:** Desktop app / Platform:macOS
- **Where:** Clicking the Dock icon with no windows open.
- **What it does:** Recreates or focuses the primary window on `activate`, and keeps the process alive on macOS when the last window closes — except during an update/uninstall hand-off.
- **How it works:** `app.on('activate', …)` (`main.ts:17420-17428`) guards on `mainWindow` directly (not the total window count) so a Dock click restores the main window even when only secondary windows remain. `app.on('window-all-closed', …)` (`:17620`) quits when `process.platform !== 'darwin' || isQuittingForHandoff`.
- **Inputs / options:** n/a
- **Outputs / side effects:** Window creation/focus, or app exit.
- **Config / env:** n/a
- **Edge cases / guards:** Without the handoff exception, a detached updater/uninstaller would spin its PID-wait to the full timeout and the user would be left with an invisible app.
- **Rebuild notes:** Self-replacement must override the platform's "stay resident" convention.

### Find in page  `id: desktop-main.find-in-page`
- **Surface:** Desktop app
- **Where:** **Cmd/Ctrl+F** opens the find bar over the rendered chat transcript; Enter / Shift+Enter (or ⌘G / ⇧⌘G) step matches; Esc closes.
- **What it does:** Searches the focused window's rendered content using Chromium's native `findInPage`, so a ⌘F in a secondary session window searches **that** window.
- **How it works:** `electron/find-in-page.ts` (231 lines) exports `installFindShortcut`, `installFoundInPageForwarder`, `performFindAfterIndexingStarted`, `stopFind`. IPC: `hermes:find-in-page` (`main.ts:16723`) runs against `BrowserWindow.fromWebContents(event.sender)`; `hermes:stop-find-in-page` (`:16738`); results pushed on `hermes:found-in-page` via `ensureFoundInPageForwarder(sender)` (`:16709`) with a per-`webContents.id` forwarder map (`foundInPageForwarders`, `:16707`). The main process also forwards Ctrl/Cmd+F to the renderer as `hermes:open-find-bar` from `before-input-event`, because on Pop!_OS/GNOME the keydown does not reach the renderer's own binding (#81727).
- **Inputs / options:** `hermesDesktop.findInPage(query, options)`, `.stopFindInPage()`, `.onFoundInPage(cb)`, `.onOpenFindBarRequested(cb)`.
- **Outputs / side effects:** Native highlight; result objects.
- **Config / env:** n/a
- **Edge cases / guards:** The forwarder is torn down when the FindBar unmounts; `performFindAfterIndexingStarted` avoids querying before Chromium has begun indexing.
- **Rebuild notes:** Scope find to the IPC sender's window, not the primary.

### Read the window below (HUD context)  `id: desktop-main.window-below`
- **Surface:** Core / Desktop app
- **Where:** Invisible; the HUD uses it so "this", "here" and "that page" resolve to whatever the bar sits over.
- **What it does:** Reports which application window is directly underneath the Hermes window.
- **How it works:** `readWindowBelow(...)`, `enumerateWindowsFrontToBack(...)`, `enumerationFailed(...)` (`electron/window-below.ts`, 298 lines); IPC `hermes:window:readBelow` (`main.ts:15512`).
- **Inputs / options:** `hermesDesktop.readWindowBelow()`.
- **Outputs / side effects:** A descriptor of the window underneath.
- **Config / env:** n/a
- **Edge cases / guards:** Enumeration failure is reported distinctly from "nothing below".
- **Rebuild notes:** Position is context for an always-on-top assistant.

### Context menu bridge  `id: desktop-main.context-menu`
- **Surface:** Desktop app
- **Where:** Right-click in any editable field or on an image.
- **What it does:** Gives the renderer-drawn context menu real native editing, image-copy and spellcheck actions, including inside `<webview>` guests.
- **How it works:** `installContextMenuBridge(window)` (`main.ts:6854`) records the last context-menu point per `webContents.id` (`lastContextMenuPoint`, `:6852`). IPC: `hermes:context-menu:edit` (command → an editing role on the sender), `hermes:context-menu:copy-image`, `hermes:context-menu:spellcheck` (action), `hermes:context-menu:guest-add-word` (payload), plus the push `hermes:context-menu-spellcheck`.
- **Inputs / options:** `hermesDesktop.contextMenuEdit(command)`, `.contextMenuCopyImage()`, `.contextMenuSpellcheck(action)`, `.contextMenuGuestAddWord(payload)`, `.onContextMenuSpellcheck(cb)`.
- **Outputs / side effects:** Native clipboard/edit operations; dictionary additions.
- **Config / env:** n/a
- **Edge cases / guards:** Guest (`<webview>`) frames need the separate add-word channel.
- **Rebuild notes:** A custom menu still needs the native editing commands behind it.

### Download handling and media permissions  `id: desktop-main.downloads-permissions`
- **Surface:** Desktop app
- **Where:** Saving a file from an in-app page; the macOS microphone prompt.
- **What it does:** Installs the session-level download handler and the media-capture permission policy.
- **How it works:** `installDownloadHandling()` (`main.ts:6908`) and `installMediaPermissions()` (`:6933`), both called at ready. `isMediaCapturePermission(permission, details)` (`:6883`) classifies the request. Explicit microphone request: `ipcMain.handle('hermes:requestMicrophoneAccess', …)` (`main.ts:15500`) uses `systemPreferences` on macOS.
- **Inputs / options:** `hermesDesktop.requestMicrophoneAccess()`.
- **Outputs / side effects:** OS permission prompts; downloads.
- **Config / env:** n/a
- **Edge cases / guards:** macOS prompts once; a stuck prompt is reset with `tccutil reset Microphone com.nousresearch.hermes`.
- **Rebuild notes:** Deny by default and allow only the capture kinds the app actually uses.

### External link opening  `id: desktop-main.open-external`
- **Surface:** Desktop app
- **Where:** Every link that should leave the app.
- **What it does:** Opens `http(s)` (and other vetted) URLs in the OS browser instead of navigating the app shell.
- **How it works:** `openExternalUrl(rawUrl)` (`main.ts:1666-1742`), IPC `hermes:openExternal` (`:16688`); in-app navigation stays confined to the dev server / packaged `file:` URL by `wireCommonWindowHandlers`. `loadWindowUrl(win, url, label)` (`:1662`) is the single load helper.
- **Inputs / options:** `hermesDesktop.openExternal(url)`.
- **Outputs / side effects:** A browser launch.
- **Config / env:** n/a
- **Edge cases / guards:** Scheme validation before handing anything to `shell.openExternal`.
- **Rebuild notes:** One guarded exit point for external navigation.

### YouTube embed referer shim  `id: desktop-main.embed-referer`
- **Surface:** Core
- **Where:** Invisible; the embed `<webview>` partition only.
- **What it does:** Stamps a `Referer: https://www.youtube.com/` on YouTube-family requests inside the embed partition so embeds are not refused.
- **How it works:** `installEmbedReferer()` (`electron/embed-referer.ts`) hooks `session.fromPartition('persist:hermes-embed').webRequest.onBeforeSendHeaders`, matching hosts against `/(^|\.)(youtube\.com|youtube-nocookie\.com|googlevideo\.com|ytimg\.com|youtubei\.googleapis\.com)$/i` and only when no Referer is already set.
- **Inputs / options:** n/a
- **Outputs / side effects:** One request header.
- **Config / env:** n/a
- **Edge cases / guards:** Scoped to that one partition; failure is non-fatal (embeds still render, YouTube may show referer errors).
- **Rebuild notes:** Scope header injection to a dedicated partition.

---

## 10. Local-machine IPC surfaces — filesystem, git, terminal, media, previews, clipboard

### Filesystem IPC  `id: desktop-main.fs-ipc`
- **Surface:** Core / Desktop app
- **Where:** The file browser, the projects sidebar, **Open plugins folder**, **Open logs**, rename/delete actions.
- **What it does:** Gives the renderer directory listings, OS file-manager integration, the local plugin/log roots, and rename/write/trash — all through hardened path resolution.
- **How it works:** `registerFsIpc({ hermesHome, readActiveDesktopProfile, expandUserPath, resolveRequestedPathForIpc, directoryExists, resolveGitBinary })` (`electron/fs-ipc.ts`, 203 lines). Handlers:
  - `hermes:fs:readDir` → `readDirForIpc(dirPath)` (`electron/fs-read-dir.ts`, 111 lines).
  - `hermes:fs:gitRoot` → `gitRootForIpc(startPath)` (`electron/git-root.ts`, 50 lines).
  - `hermes:fs:reveal` → `shell.showItemInFolder(target)`; returns `true`/`false`.
  - `hermes:fs:openDir` → `mkdir -p` then `shell.openPath(path.normalize(dir))`; returns `{ ok: true }` or `{ ok: false, error }`. Distinct from `reveal`, which silently no-ops on a missing path (the "Open plugins folder" Windows bug).
  - `hermes:fs:desktopPluginsRoot` → `<HERMES_HOME>[/profiles/<profile>]/desktop-plugins`.
  - `hermes:fs:logsRoot` → the same base + `/logs`.
  - `hermes:fs:agentPluginsRoot` → the same base + `/plugins`.
  - `hermes:plugin:probe` (payload `{ identifier | repo }`) → `probePluginRepo(...)`; returns `{ ok:false, error:'identifier is required', agent:false, desktop:false, warnings:[] }` for a blank id.
  - `hermes:plugin:installDesktop` → `installDesktopPluginFromGit(...)`.
  - `hermes:fs:rename` (targetPath, newName), `hermes:fs:writeText` (filePath, content), `hermes:fs:trash` (targetPath).
- **Inputs / options:** `hermesDesktop.readDir(dirPath)`, `.gitRoot(startPath)`, `.revealPath(targetPath)`, `.openDir(dirPath)`, `.desktopPluginsRoot()`, `.logsRoot()`, `.agentPluginsRoot()`, `.renamePath(targetPath, newName)`, `.writeTextFile(filePath, content)`, `.trashPath(targetPath)`, `.probePluginRepo(payload)`, `.installDesktopPlugin(payload)`.
- **Outputs / side effects:** Directory creation, renames, trash moves, OS windows.
- **Config / env:** n/a
- **Edge cases / guards:** The plugin/log roots are resolved from the **main-process** `HERMES_HOME`, never from the connected backend — a remote backend reports a path on the *remote* box, which yielded `undefined/desktop-plugins` and silently broke the on-disk plugin door (#66899). They are profile-aware: a named profile gets `profiles/<name>/…`, while `default`/unset pins the global root.
- **Rebuild notes:** Local doors must resolve locally, whatever backend is connected.

### Path hardening for IPC  `id: desktop-main.path-hardening`
- **Surface:** Core
- **Where:** Invisible; every renderer-supplied path.
- **What it does:** Resolves and validates a renderer-supplied path before any read, with size caps and purpose-tagged errors.
- **How it works:** `electron/hardening.ts` (554 lines) exports `resolveRequestedPathForIpc(value, { purpose })`, `resolveReadableFileForIpc(...)`, `readFileDataUrlForIpc(filePath, { maxBytes, mimeType, purpose })`, `resolveTimeoutMs`, `DEFAULT_FETCH_TIMEOUT_MS`, `TEXT_PREVIEW_SOURCE_MAX_BYTES`, `ATTACHMENT_UPLOAD_DEFAULT_MAX_BYTES`, `DATA_URL_READ_DEFAULT_MAX_MB`, `clampDataUrlReadMaxMb`, `dataUrlReadMaxBytesFromMb`, `SAFE_STORAGE_ENCODING`, `encryptDesktopSecret`, `resolvePersistedRemoteToken`, `tightenSecretFileMode`, `writeSecretFileAtomic`, `enableBasicPasswordStoreEncryption`. `expandUserPath(filePath)` (`main.ts:5877`) expands `~`.
- **Inputs / options:** n/a
- **Outputs / side effects:** none.
- **Config / env:** n/a
- **Edge cases / guards:** Purpose strings appear in the error the user sees (e.g. `File preview`).
- **Rebuild notes:** One hardening module every IPC read funnels through.

### Data-URL read cap  `id: desktop-main.data-url-read-max`
- **Surface:** Config / Desktop app
- **Where:** **Settings → Chat** — the composer-attachment / local-preview size limit.
- **What it does:** Caps how large a file the renderer may load as a data URL, persisted so every IPC read honours it without the renderer passing `maxBytes`.
- **How it works:** `DATA_URL_READ_MAX_CONFIG_PATH = <userData>/data-url-read-max.json` (`main.ts:16146`), `readPersistedDataUrlReadMaxMb()` (`:16148`), `persistDataUrlReadMaxMb(maxMb)` (`:16158`), clamped by `clampDataUrlReadMaxMb`. Default `DATA_URL_READ_DEFAULT_MAX_MB` = 16 MB. IPC `hermes:data-url-read-max:get` / `:set` both return `{ maxMb, defaultMaxMb, maxBytes }`.
- **Inputs / options:** `hermesDesktop.dataUrlReadMax.get()`, `.set(maxMb)`.
- **Outputs / side effects:** The JSON file.
- **Config / env:** n/a
- **Edge cases / guards:** Remote attachment transfer uses the independent `ATTACHMENT_UPLOAD_DEFAULT_MAX_BYTES` so archives can exceed the preview ceiling while staying inside the gateway WebSocket frame limit after base64 expansion.
- **Rebuild notes:** Own the limit in main; a renderer-passed cap is not a cap.

### File read / attach / write IPC  `id: desktop-main.file-io-ipc`
- **Surface:** Core / Desktop app
- **Where:** Drag-and-drop attach, file previews, plugin source viewing, save dialogs, clipboard image capture.
- **What it does:** Every local file read/write the renderer can perform.
- **How it works:** every read funnels through `electron/hardening.ts` path resolution and the persisted data-URL cap; every write goes through a native dialog or an explicit renderer-supplied path.
- **Inputs / options:** each channel and its preload name:
  - `hermes:readFileDataUrl` ← `readFileDataUrl(filePath)` — capped by the data-URL max, MIME from `mimeTypeForPath`, purpose `File preview` (`main.ts:16189`).
  - `hermes:readFileDataUrlForAttach` ← `readFileDataUrlForAttach(filePath)` — the attachment path with its own cap (`:16201`).
  - `hermes:readFileText` ← `readFileText(filePath)` (`:16209`).
  - `hermes:readPluginSource` ← `readPluginSource(filePath)` (`:16244`), bounded by `PLUGIN_SOURCE_MAX_BYTES = 16 * 1024 * 1024` (`:16242`).
  - `hermes:selectPaths` ← `selectPaths(options)` (`:16258`) — the open dialog.
  - `hermes:selectSavePath` ← `selectSavePath(options)` (`:16303`).
  - `hermes:writeClipboard` ← `writeClipboard(text)` (`:16295`); `hermes:readClipboard` ← `readClipboard()` (`:16321`).
  - `hermes:saveGatewayFile` ← `saveGatewayFile(payload)` (`:16323`).
  - `hermes:saveImageFromUrl` ← `saveImageFromUrl(url)` (`:16325`).
  - `hermes:saveImageBuffer` ← `saveImageBuffer(data, ext)` (`:16379`) → `writeComposerImage(buffer, ext)` (`:5856`).
  - `hermes:saveClipboardImage` ← `saveClipboardImage()` (`:16391`), which on WSL falls back to `readWslWindowsClipboardImage(...)` (`electron/wsl-clipboard-image.ts`).
  - `getPathForFile(file)` — preload-only, `webUtils.getPathForFile(file)` wrapped in try/catch returning `''`.
- **Outputs / side effects:** Files written to the user's chosen locations; clipboard reads/writes.
- **Config / env:** n/a
- **Edge cases / guards:** `resolvePickerDefaultPath(...)` (`electron/wsl-path-bridge.ts`) chooses a sane default directory, WSL-aware.
- **Rebuild notes:** Keep a single MIME/extension mapping (`mimeTypeForPath` `:5273`, `extensionForMimeType` `:5279`, `filenameFromUrl` `:5312`).

### Gateway file download  `id: desktop-main.gateway-file-download`
- **Surface:** Core / Desktop app
- **Where:** **Download** on a file the agent produced.
- **What it does:** Streams a file from the connected gateway (local or remote, token or OAuth or native bearer) to a user-chosen path.
- **How it works:** `saveGatewayFile(payload)` (`main.ts:7783`) and `saveGatewayFileViaDataUrl(...)` (`:7833`), built on `electron/gateway-file-download.ts` (355 lines): `gatewayFilePath`, `gatewayFileRequestPaths`, `resolveGatewayFileBackend`, `filenameFromContentDisposition`, `parseDataUrlToBuffer`, `pumpStreamToFile`, `writeBufferToFile`, `fsPumpDeps`, `isNotFoundError`. Auth is chosen by `gatedFileAuth(connection)` (`main.ts:7765`) → `resolveGatedDownloadAuth` (`electron/native-auth-decisions.ts`), so a cookieless native session downloads with its bearer rather than 401ing. Transport helpers: `downloadViaTokenToFile(url, token, ctx, options)` (`:5118`), `downloadViaOauthSessionToFile(url, ctx, options)` (`:7601`), `finalizeGatewayDownload(res, statusCode, headers, ctx)` (`:7692`), `readGatewayErrorText(res)` (`:7727`).
- **Inputs / options:** `hermesDesktop.saveGatewayFile(payload)`.
- **Outputs / side effects:** A saved file.
- **Config / env:** n/a
- **Edge cases / guards:** Two request-path shapes are tried so old and new backends both work; a 404 on the first is not an error.
- **Rebuild notes:** Downloads must present the same credentials as the REST calls that listed the file.

### Preview normalization, watching and reachability  `id: desktop-main.previews`
- **Surface:** Core / Desktop app
- **Where:** The right-hand preview rail: rendering a local file, a directory, or a dev-server URL.
- **What it does:** Turns "whatever the agent produced" into a previewable target, watches it for changes, and proves a preview URL is actually reachable from this machine.
- **How it works:** `normalizePreviewTarget(rawTarget, baseDir)` (`main.ts:5958`) → `previewFileTarget(...)` (`:5891`) or `previewUrlTarget(...)` (`:5934`); `previewFileMetadata(filePath, mimeType)` (`:1263`) with `looksBinary(buffer)` (`:1242`), `TEXT_PREVIEW_MAX_BYTES = 512 * 1024` (`:1205`), `PREVIEW_HTML_EXTENSIONS = {.html,.htm}`, `PREVIEW_PDF_EXTENSIONS = {.pdf}`, `LOCAL_PREVIEW_HOSTS = {0.0.0.0, 127.0.0.1, ::1, [::1], localhost}`, and `PREVIEW_LANGUAGE_BY_EXT` (`:1207`) for syntax labelling. Watching: `watchPreviewFile(rawUrl)` (`:5996`), `watchDirectory(rawDir)` (`:6072`), `stopPreviewFileWatch(id)` (`:6038`), `closePreviewWatchers()` (`:6051`), debounce `PREVIEW_WATCH_DEBOUNCE_MS = 120`, push `hermes:preview-file-changed` via `sendPreviewFileChanged(payload)` (`:5982`), registry `previewWatchers` (`:1485`). Reachability: `reachablePreviewUrl(webContentsId, rawUrl)` (`:10012`) backed by `PreviewReachRegistry` (`electron/preview-reach.ts`, 210 lines) keyed per `webContents` (`previewReachByWebContents`, `:9983`) with `resetPreviewReach(webContentsId)` (`:9985`) — this is what makes a dev-server preview work when the backend is remote and the port lives on the other machine. `openPreviewInBrowser(rawUrl)` (`:1744`).
- **Inputs / options:** `hermesDesktop.normalizePreviewTarget(target, baseDir)`, `.watchPreviewFile(url)`, `.watchDirectory(dir)`, `.stopPreviewFileWatch(id)`, `.reachPreviewUrl(url)`, `.openPreviewInBrowser(url)`, `.onPreviewFileChanged(cb)`.
- **Outputs / side effects:** fs watchers; a browser launch.
- **Config / env:** n/a
- **Edge cases / guards:** Watchers are closed on quit; binary files are detected and not rendered as text.
- **Rebuild notes:** Preview targets need a normalizer; raw agent output is not a URL.

### `hermes-media://` protocol  `id: desktop-main.media-protocol`
- **Surface:** Core
- **Where:** Invisible; how the renderer loads local images/video/audio without a `file://` origin.
- **What it does:** Registers a custom scheme that serves whitelisted local media with correct MIME types.
- **How it works:** `registerMediaProtocol()` (`main.ts:1332`) uses `createMediaProtocolHandler(...)` and `MEDIA_PROTOCOL` (`electron/media-protocol.ts`, 186 lines). MIME map `MEDIA_MIME_TYPES` (`main.ts:1179`).
- **Inputs / options:** n/a
- **Outputs / side effects:** Served bytes.
- **Config / env:** n/a
- **Edge cases / guards:** Registered once at ready, before any window loads.
- **Rebuild notes:** A dedicated scheme beats relaxing `file://` restrictions.

### Link titles and favicons  `id: desktop-main.link-title-favicon`
- **Surface:** Core / Desktop app
- **Where:** Link cards in the transcript and the artifacts gallery.
- **What it does:** Resolves a URL's page title and site icon, cached, bounded and rate-limited.
- **How it works:** Titles: `fetchLinkTitle(rawUrl)` (`main.ts:5580`), cache `titleCache`/`titleInflight` with `TITLE_CACHE_LIMIT = 500`, `TITLE_BYTE_BUDGET = 96 * 1024`, `TITLE_TIMEOUT_MS = 5000`, `TITLE_MAX_REDIRECTS = 3`; `canonicalTitleCacheKey(rawUrl)` (`:5364`), `cacheTitle` (`:5382`), `parseHtmlTitle(html)` (`:5397`), `decodeHtmlEntities(value)` (`:5390`) with `HTML_ENTITIES = { amp, lt, gt, quot, apos, nbsp, '#39' }`, `fetchHtmlTitleWithCurl(rawUrl)` (`:5403`), and the offscreen-render fallback (`desktop-main.link-title-window`). Favicons: `resolveFaviconCached(rawUrl)` (`:5728`) over `electron/favicon.ts` (347 lines, `resolveFavicon` + `FaviconIo`), persisted at `FAVICON_CACHE_PATH = <userData>/favicon-cache.json` with `FAVICON_CACHE_LIMIT = 400`, `FAVICON_TTL_MS = 30 days`, `FAVICON_MISS_TTL_MS = 12 h`, `FAVICON_TIMEOUT_MS = 6000`, `FAVICON_MAX_BYTES = 256 * 1024`, `FAVICON_WRITE_DEBOUNCE_MS = 3000`; `loadFaviconCache()` (`:5643`), `saveFaviconCacheSoon()` (`:5668`), `faviconFetch(url, accept)` (`:5688`), in-flight dedupe `faviconInflight`.
- **Inputs / options:** `hermesDesktop.fetchLinkTitle(url)`, `.resolveFavicon(url)`.
- **Outputs / side effects:** `<userData>/favicon-cache.json`; outbound HTTP.
- **Config / env:** n/a
- **Edge cases / guards:** Negative results are cached with a shorter TTL so a dead icon is not refetched constantly.
- **Rebuild notes:** Cache misses too, with their own TTL.

### Embedded terminal PTY host  `id: desktop-main.terminal-ipc`
- **Surface:** Desktop app
- **Where:** The right-sidebar terminal. **Ctrl+`** shows it, **Ctrl+Shift+`** spawns another, **Ctrl+Shift+↓/↑** walk tabs, **Ctrl+Shift+W** closes the active one.
- **What it does:** Runs real interactive shells (local, or over the SSH tunnel when the window is on an SSH gateway) with a scrubbed, truecolor environment, and keeps them alive while hidden.
- **How it works:** `registerTerminalIpc({ isWindows, findOnPath, rememberLog, activeSshTerminalTarget, ensureBackend, getSshConnectionState })` (`electron/terminal-ipc.ts`, 378 lines) over `node-pty`. Shell resolution `terminalShellCommand()`: an explicit override (`HERMES_DESKTOP_SHELL`, or `$SHELL` on POSIX only — on Windows `$SHELL` is usually a stray MSYS path node-pty cannot spawn) wins; else Windows tries `pwsh.exe`, `pwsh`, the fixed `%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe`, `%COMSPEC%`, `cmd.exe`; else POSIX tries `/bin/zsh`, `/bin/bash`, `/bin/sh`. Interactive flags by family: PowerShell `['-NoLogo']`, cmd `[]`, zsh/bash `['-il']`, other POSIX `['-i']`. `safeTerminalCwd(cwd)` falls back to the home directory. `terminalShellEnv()` deletes every `npm_config_*` / `npm_package_*` var (nvm/proto warn loudly about a leaked prefix) plus `NO_COLOR`, `FORCE_COLOR`, `COLORFGBG`, then sets `COLORTERM=truecolor`, `LC_CTYPE` (default `UTF-8`), `TERM=xterm-256color`, `TERM_PROGRAM=Hermes`, `TERM_PROGRAM_VERSION=<app version>`, `HERMES_DESKTOP_TERMINAL=1`. Remote panes spawn `ssh` (or `%SystemRoot%\System32\OpenSSH\ssh.exe`) with `buildInteractiveSshArgs(...)`, reusing the existing ControlMaster so no new auth handshake happens; a Windows remote gets `buildWindowsInteractiveCommand(cwd)`. `readProcessCwd(pid)` reads `/proc/<pid>/cwd` on Linux or `lsof -a -p <pid> -d cwd -Fn` on macOS (2 s timeout); Windows returns `null` and the caller falls back to the launch cwd. Data/exit are pushed on per-session channels `hermes:terminal:<id>:data` / `:exit`.
- **Inputs / options:** `hermesDesktop.terminal.start({ cwd, cols, rows })` → `{ id, cwd, shell }`; `.write(id, data)`; `.resize(id, { cols, rows })` (each clamped to ≥ 2, defaults 80×24); `.cwd(id)`; `.dispose(id)`; `.onData(id, cb)`; `.onExit(id, cb)`.
- **Outputs / side effects:** PTY child processes; log line `[terminal] restored +x on node-pty spawn-helper: <path>`.
- **Config / env:** env `HERMES_DESKTOP_SHELL`, `SHELL`, `COMSPEC`, `SystemRoot`/`windir`.
- **Edge cases / guards:** `ensureNodePtySpawnHelper()` restores the exec bit on node-pty's POSIX `spawn-helper` before the first spawn (the published tarball ships it 0644, so the dev flow dies with `posix_spawnp failed`) via `ensureSpawnHelperExecutable(root)` and `writableNodePtyRoot(root)` which redirects `app.asar` → `app.asar.unpacked` (`electron/spawn-helper-perms.ts`). Sessions are disposed when their `webContents` is destroyed, when their SSH scope tears down (`disposeTerminalSessionsForSshScope`), and on quit (`disposeAllTerminalSessions`, before environment teardown, to dodge the node-pty#904 SIGABRT race).
- **Rebuild notes:** Scrub the launcher's environment out of the user's shell; an Electron app inherits a lot of noise.

### Git worktree IPC  `id: desktop-main.git-worktrees`
- **Surface:** Desktop app
- **Where:** **Cmd/Ctrl+Shift+B** or **New worktree** on a project in the sidebar; worktree lanes under a project.
- **What it does:** Lists, creates, removes worktrees and switches/lists branches so an agent can work on a parallel copy of the repo.
- **How it works:** `registerGitIpc({ resolveGitBinary, resolveGhBinary })` (`electron/git-ipc.ts`) over `electron/git-worktree-ops.ts` (537 lines): `listWorktrees`, `addWorktree`, `removeWorktree`, `switchBranch`, `listBranches`, `listBaseBranches`. Channels `hermes:git:worktreeList`, `:worktreeAdd`, `:worktreeRemove`, `:branchSwitch`, `:branchList`, `:baseBranchList`.
- **Inputs / options:** `hermesDesktop.git.worktreeList(repoPath)`, `.worktreeAdd(repoPath, options)`, `.worktreeRemove(repoPath, worktreePath, options)`, `.branchSwitch(repoPath, branch)`, `.branchList(repoPath)`, `.baseBranchList(repoPath)`.
- **Outputs / side effects:** New worktree directories/branches; errors surface as rejected promises the renderer toasts.
- **Config / env:** n/a
- **Edge cases / guards:** Removal offers deleting the directory (branch preserved) or just hiding the lane, with a force option for uncommitted changes.
- **Rebuild notes:** Worktrees are the safe way to parallelize an agent on one repo.

### Git review IPC  `id: desktop-main.git-review`
- **Surface:** Desktop app
- **Where:** **Cmd/Ctrl+G** review pane: **Uncommitted / Branch / Last turn** scopes, stage/unstage/revert, **Generate commit message**, **Commit**, **Commit & Push**, **Create PR**.
- **What it does:** A full working-tree review surface driven by `git` and the GitHub CLI.
- **How it works:** `electron/git-review-ops.ts` (903 lines) behind `registerGitIpc`. Channels: `hermes:git:review:list` (repoPath, scope, baseRef), `:diff` (repoPath, filePath, scope, baseRef, staged), `hermes:git:fileDiff` (repoPath, filePath), `:review:stage`, `:review:unstage`, `:review:revert`, `:review:revParse` (repoPath, ref), `:review:commit` (repoPath, message, push), `:review:commitContext` (repoPath), `:review:push`, `:review:shipInfo` (uses `resolveGhBinary()`), `:review:prList` (repoPath, branches, numbers), `:review:fetchPrComment` (repoPath, url), `:review:createPr`, plus `hermes:git:repoStatus` and `hermes:git:scanRepos` (roots, options → `scanGitRepos`, `electron/git-repo-scan.ts`, 201 lines).
- **Inputs / options:** `hermesDesktop.git.review.{list, diff, stage, unstage, revert, revParse, commit, commitContext, push, shipInfo, prList, fetchPrComment, createPr}`, `hermesDesktop.git.repoStatus(repoPath)`, `.fileDiff(repoPath, filePath)`, `.scanRepos(roots, options)`.
- **Outputs / side effects:** Index/worktree changes, commits, pushes, PRs.
- **Config / env:** `desktop.repo_scan_enabled`, `desktop.repo_scan_roots`, `desktop.repo_scan_exclude_paths` govern `scanRepos`.
- **Edge cases / guards:** `resolveGitBinary()` (`main.ts:2667`, cached in `_gitBinaryCache`) and `resolveGhBinary()` (`:2704`, `_ghBinaryCache`) locate the binaries; `runGit` always sets `GIT_TERMINAL_PROMPT=0` and, on Windows, `-c windows.appendAtomically=false`.
- **Rebuild notes:** Keep the diff scopes (uncommitted / branch / last turn) as first-class parameters — "what the agent just changed" is the most useful one.

### Workspace path sanitisation  `id: desktop-main.workspace-sanitize`
- **Surface:** Core
- **Where:** Invisible; every place a working directory is accepted.
- **What it does:** Rejects a workspace inside the packaged install so sessions never write into a directory an update replaces.
- **How it works:** `sanitizeWorkspaceCwd(cwd)` (`main.ts:4519`) + `isPackagedInstallPath(dir)` (`:4472`) + `isPackagedInstallPathUnderRoots` (`electron/workspace-cwd.ts`); IPC `hermes:workspace:sanitize`.
- **Inputs / options:** `hermesDesktop.sanitizeWorkspaceCwd(cwd)` → `{ cwd, … }`.
- **Outputs / side effects:** none.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** Self-updating apps must fence their own install directory.

### Git Bash discovery (Windows)  `id: desktop-main.find-git-bash`
- **Surface:** Core / Platform:Windows
- **Where:** Invisible; required because the agent's terminal tool calls `bash.exe` directly.
- **What it does:** Locates Git Bash (including the PortableGit that `install.ps1` places at `%LOCALAPPDATA%\hermes\git\`).
- **How it works:** `findGitBash()` (`main.ts:2590`) → `_findGitBash` (`electron/find-git-bash.ts`, 67 lines). `ensureRuntime` fails with an actionable message when it is missing.
- **Inputs / options:** n/a
- **Outputs / side effects:** none.
- **Config / env:** n/a
- **Edge cases / guards:** Only enforced on Windows.
- **Rebuild notes:** Check for the tools your agent shells out to, at boot, with an install command in the error.

---

## 11. Security — secret storage, OAuth, cookie isolation, hardening

### Opt-in OS-keychain encryption for stored secrets  `id: desktop-main.secret-storage-policy`
- **Surface:** Desktop app / Config
- **Where:** **Settings → Gateway → "Encrypt saved secrets with the OS keychain"** (documented also as Settings → Gateway in `multi-connection-desktop.md`).
- **What it does:** Keychain-backed encryption of stored gateway secrets is **off by default**; turning it on re-encrypts every stored secret in place, turning it off decrypts them again. With it off, no `safeStorage` API is ever called.
- **How it works:** `electron/secret-storage-policy.ts` (102 lines): policy `{ on, migrated }` in `<userData>/secure-token-storage.json` (`SECRET_STORAGE_POLICY_FILE`), read by `readSecretStoragePolicy(io)` — anything unreadable/unparseable/hand-mangled is the default (off, not migrated), and `on` uses strict `=== true`; `classifyStoredSecret(secret, policy)` decides `migrate`/keep. Main: `secretStoragePolicy()` (`main.ts:8501`, memoized), `setSecretStoragePolicy(next)` (`:8509`), `probeSecureTokenStorage()` (`:8521` — reports `true` without probing when encryption is off, because `isEncryptionAvailable()` is itself a keychain touch that raises the very macOS dialog this feature avoids), `rewriteAllStoredSecrets(shouldRewrite, reencode)` (`:8539` — walks v1 `connection.json` token/headers + per-profile overrides, v2 registry connections, and the native OAuth token store), `migrateLegacyEncryptedSecretsOnce()` (`:8613`, run once at ready), `applySecretStorageEncryption(on)` (`:8659`), `encryptDesktopSecret(value, options)` (`:8720`), `decryptDesktopSecret(secret)` (`:8730`).
- **Inputs / options:** `hermesDesktop.getSecretStorageEncryption()` → `{ on }` (never touches the keychain); `.setSecretStorageEncryption(on)`.
- **Outputs / side effects:** Rewritten secret envelopes across every store; the policy file.
- **Config / env:** n/a
- **Edge cases / guards:** Turning **on** probes `safeStorage.isEncryptionAvailable()` **first** and throws `OS keychain encryption is unavailable on this machine, so stored gateway secrets cannot be encrypted.` before touching any store; a mid-way failure reverts the policy so reads keep working against whatever encodings are on disk (mixed stores read fine). The one-shot legacy migration keeps an undecryptable blob (locked/absent keychain) but treats it as unset afterwards, and records `migrated: true` whether or not it succeeded — so a broken keychain costs at most one prompt on the first post-update launch, never one per launch. Log lines: `[secret-storage] legacy migration pass failed: <detail>`, `[secret-storage] migrated legacy keychain-encrypted secrets to opt-out storage (one-shot pass)`.
- **Rebuild notes:** On macOS, `safeStorage` parks a per-app key in the login keychain; a locked or broken keychain turns *any* touch into a launch-blocking password prompt. Make encryption opt-in and never probe when it is off.

### Secret file permissions and atomic writes  `id: desktop-main.secret-files`
- **Surface:** Core
- **Where:** `<userData>/connection.json`, `connections.json`, the native token store, `desktop-installation.json`, `backend-ownership.json`, `managed-ssh-update-recovery.json`, `secure-token-storage.json`.
- **What it does:** Every file that can hold secret material is written atomically, owner-only (0600), in the main process — the renderer and plugins never see token bytes.
- **How it works:** `writeSecretFileAtomic(path, text, { encoding })` and `tightenSecretFileMode(path)` (`electron/hardening.ts`); `writeFileAtomic(targetPath, data, encoding)` (`main.ts:2746`); `writeBackendOwnership` writes a `${path}.<pid>.tmp` then renames (`:3250`). `desktop-installation.json` additionally rejects a symlink, a non-file, or a file owned by another uid, and chmods to 0600 on read (`electron/desktop-installation.ts`).
- **Inputs / options:** n/a
- **Outputs / side effects:** 0600 files.
- **Config / env:** n/a
- **Edge cases / guards:** The registry file holds only labels, URLs and hosts — secrets appear solely inside encrypted envelopes.
- **Rebuild notes:** Atomic + 0600 + owner check; a temp file left world-readable defeats the whole scheme.

### Per-connection OAuth cookie partitions  `id: desktop-main.oauth-partition`
- **Surface:** Core
- **Where:** Invisible; one cookie jar per cookie-authenticated registered gateway.
- **What it does:** Stops two registered gateways on the same host from sharing (and stealing) each other's session cookies.
- **How it works:** `electron/oauth-partition.ts` (155 lines). `LEGACY_OAUTH_PARTITION = 'persist:hermes-remote-oauth'`; per-connection partitions are `persist:hermes-remote-oauth:conn:<id>`. `resolveOauthPartition(url, { registry, v1RemoteUrl })` rules: a **non-primary** v2 `remote` entry with cookie auth (`authMode: 'oauth'`, which also covers dashboard basic/password providers — they authenticate via session cookies too) gets its own partition; the registry **primary** and the v1 single-connection remote stay on the legacy shared partition (so existing signed-in users are not signed out by the upgrade); `cloud` entries stay on the legacy partition (the silent per-agent cascade deliberately shares one jar with the portal session); token-auth remotes, portal URLs and anything unmatched fall back to the legacy partition. Main: `OAUTH_SESSION_PARTITION = LEGACY_OAUTH_PARTITION` (`:6981`), `getOauthSession()` (`:6983`), `oauthSessionsByPartition` (`:6999`), `resolveOauthPartitionForUrl(url)` (`:7001`), `getOauthSessionForUrl(url)` (`:7013`).
- **Inputs / options:** n/a
- **Outputs / side effects:** Separate Chromium cookie jars.
- **Config / env:** n/a
- **Edge cases / guards:** Chromium cookie jars scope by host and **ignore the port**, which is exactly why one box hosting two dashboards leaked credentials across connections (#92183).
- **Rebuild notes:** Key the jar on your identity for the connection, not on the auth mode.

### Cookie-session liveness classification  `id: desktop-main.cookie-liveness`
- **Surface:** Core
- **Where:** Invisible; decides whether the app is "signed in" to a gateway or the portal.
- **What it does:** Distinguishes a live session, a renewable session, and no session — for both the Hermes gateway cookies and the Nous Portal (Privy) cookies.
- **How it works:** `electron/connection-config.ts`. Gateway: `AT_COOKIE_VARIANTS = ['__Host-hermes_session_at','__Secure-hermes_session_at','hermes_session_at']`, `RT_COOKIE_VARIANTS = ['__Host-hermes_session_rt','__Secure-hermes_session_rt','hermes_session_rt']`; `cookiesHaveSession(cookies)` (`:942`), `cookiesHaveLiveSession(cookies)` (`:963`) — an expired AT with a live RT is still LIVE, because the gateway middleware transparently rotates a fresh AT on the next authenticated request; checking only the AT would force a full re-login every ~15 minutes. Portal: `PRIVY_SESSION_COOKIE_VARIANTS` and `PRIVY_ACCESS_COOKIE_VARIANTS` with `cookiesHavePrivySession` (`:979`) and `cookiesHavePrivyAccessToken` (`:995`). Main consumers: `hasOauthSessionCookie(baseUrl)` (`:7088`), `hasLiveOauthSession(baseUrl)` (`:7121`), `clearOauthSession(baseUrl)` (`:7171`), `warmOauthCookieStore(url)` (`:7050`, with `oauthCookieWarmups` dedupe).
- **Inputs / options:** n/a
- **Outputs / side effects:** none.
- **Config / env:** n/a
- **Edge cases / guards:** Portal liveness must look at the **Privy** cookie, not the gateway cookies — the portal is a Privy-authed Next.js app.
- **Rebuild notes:** "Signed in" and "has a currently valid access token" are different questions; answer both.

### Embedded OAuth login window  `id: desktop-main.oauth-login-window`
- **Surface:** Desktop app
- **Where:** **Sign in with `<provider>`** on a remote gateway; the Hermes Cloud portal login.
- **What it does:** Opens the provider's browser sign-in inside a partition-bound window and completes the cookie session.
- **How it works:** `openOauthLoginWindow(baseUrl, { silent })` (`main.ts:7211-7348`) and `openPortalLoginWindow()` (`:8196`). REST over the partition: `fetchJsonViaOauthSession(url, options)` (`:7350`), whose request shaping (`serializeJsonBody`, `setJsonRequestHeaders`) lives in `electron/oauth-net-request.ts` (17 lines) so the electron-`net` path and the plain-`http` path cannot disagree about how a JSON body is encoded. IPC `hermes:connection-config:oauth-login` (`:15313`) / `:oauth-logout` (`:15376`).
- **Inputs / options:** `hermesDesktop.oauthLoginConnectionConfig(remoteUrl)`, `.oauthLogoutConnectionConfig(remoteUrl)`.
- **Outputs / side effects:** Cookies in the resolved partition.
- **Config / env:** n/a
- **Edge cases / guards:** `silent: true` is used for the Cloud per-agent cascade, where no interaction should be required.
- **Rebuild notes:** Bind the login window to the same partition its requests will use.

### RFC 8252 native OAuth (system browser + loopback + PKCE)  `id: desktop-main.native-oauth`
- **Surface:** Desktop app
- **Where:** Signing in to a gated gateway that advertises `native_pkce`.
- **What it does:** Signs in through the *system browser* with a loopback redirect and PKCE, so the app holds tokens rather than browser session cookies.
- **How it works:** `electron/native-oauth.ts` (255 lines, electron-free): `generatePkcePair(randomImpl)` → `{ verifier, challenge, method: 'S256' }` (verifier = 32 random bytes base64url, 43 chars), `NATIVE_FLOW_ID = 'native_pkce'` advertised on `/api/status`'s `auth_flows`, `resolveLoginStrategy(...)`, `parseTokenResponse(...)` (snake_case gateway responses), `parseStoredTokenSet(...)` (camelCase on-disk shape — crossing the two produced the "signed out after restart" bug #73271), `nativeRefreshUrl(...)`, `tokenNeedsRefresh(...)`, type `NativeTokenSet = { accessToken, refreshToken, expiresAt, provider, userId }`. The loopback listener + `shell.openExternal` live in `electron/native-oauth-login.ts` (215 lines, `runNativeLogin`). Persistence: `electron/native-token-store.ts` (165 lines, `loadNativeTokenSet` / `persistNativeTokenSet` over an injected `NativeTokenStoreIo`), main's `_nativeTokenStorePath()` (`:7483`), `_nativeTokenStoreIo()` (`:7492`), `_persistNativeTokens` (`:7505`), `_loadNativeTokens` (`:7509`), `_storeNativeTokens` (`:7525`), `_clearNativeTokens` (`:7530`), `hasNativeSession(baseUrl)` (`:7537`), `ensureNativeAccessToken(baseUrl)` (`:7556`). The gateway brokers the flow (`/auth/native/{authorize,token,refresh}`) because the upstream IDP issues a per-gateway client_id and only accepts a redirect_uri on the gateway's own origin.
- **Inputs / options:** driven by the connection editor's sign-in button.
- **Outputs / side effects:** An encrypted token store keyed by gateway base URL.
- **Config / env:** n/a
- **Edge cases / guards:** `electron/native-auth-decisions.ts` pins six contracts: `resolveJsonBody` (never pre-stringify — `fetchJson` owns `JSON.stringify`, and double-encoding makes Pydantic answer 422), `oauthSessionIsLive(hasNativeToken, hasCookieSession)` (either suffices), `resolveOauthRestAuth` (bearer when present, else the cookie partition), `resolveReadinessProbeAuth`, `oauthGuardMayHardFail` (`auth_required: true` means gated, not OAuth), `resolveGatedDownloadAuth` (downloads present the same credentials as REST). Capability detection is an observable ladder: `native_pkce` present ⇒ native flow, absent ⇒ the embedded-webview cookie flow.
- **Rebuild notes:** A native app should not hold browser cookies; broker PKCE through your own server when the IDP will not accept a loopback client.

### MCP OAuth loopback callback (remote backends)  `id: desktop-main.mcp-oauth-callback`
- **Surface:** Core / Desktop app
- **Where:** Adding an OAuth-gated MCP server while connected to a **remote** backend.
- **What it does:** Binds a one-shot loopback listener on the *user's* machine and hands its URL to the gateway as the OAuth `redirect_uri`, so the provider redirect is reachable.
- **How it works:** `registerMcpOauthCallbackIpc(...)` (`electron/mcp-oauth-callback-ipc.ts`, 181 lines). `hermes:mcp-oauth:listen` binds `127.0.0.1` on an ephemeral port (max `MAX_PENDING_LISTENERS = 8`) and returns its id + redirect URI; `hermes:mcp-oauth:wait` (id, timeoutMs; default `DEFAULT_WAIT_TIMEOUT_MS = 5 * 60 * 1000`) resolves with `{ code, state, error }`; `hermes:mcp-oauth:cancel` (id) tears it down. The browser sees a minimal page: `<h2>✓ Authorization received</h2><p>You can close this window and return to Hermes.</p>` which self-closes after 800 ms.
- **Inputs / options:** `hermesDesktop.mcpOauth.listen()`, `.wait(id, timeoutMs)`, `.cancel(id)`.
- **Outputs / side effects:** A short-lived HTTP listener.
- **Config / env:** n/a
- **Edge cases / guards:** The listener only ever **receives** `code`/`state` and forwards them; no tokens are exchanged there, and the gateway verifies `state` in constant time before redeeming anything. Closes on first callback, cancel or timeout.
- **Rebuild notes:** The redirect must land where the browser runs, not where the backend runs.

### Windows system CA trust  `id: desktop-main.windows-system-ca`
- **Surface:** Core / Platform:Windows
- **Where:** Invisible; log `[tls] trusting <N> Windows system CA certificate(s) for backend connections`.
- **What it does:** Adds the machine's Windows certificate store to Node's default CA list so a corporate-MITM'd or internally-signed gateway is reachable.
- **How it works:** `installWindowsSystemCaTrust(tls)` (`electron/windows-system-ca.ts`): `tls.getCACertificates('default')` + `tls.getCACertificates('system')` → `tls.setDefaultCACertificates([...])`. Returns `{ applied, systemCertificateCount, totalCertificateCount, error? }`; called at ready (`main.ts:17338`).
- **Inputs / options:** n/a
- **Outputs / side effects:** Node's default CA list.
- **Config / env:** n/a
- **Edge cases / guards:** No-op off Windows and when the system store is empty; failures log `[tls] could not load Windows system CA certificates: <error>` and continue.
- **Rebuild notes:** Extend, never replace, the default list.

### API transport (keep-alive agents + retries)  `id: desktop-main.api-transport`
- **Surface:** Core
- **Where:** Invisible; every main-process HTTP call to a backend.
- **What it does:** Reuses TCP connections for JSON and download traffic and applies bounded retries to transient failures.
- **How it works:** `electron/api-transport.ts` (178 lines) exports `jsonAgentFor(url)`, `downloadAgentFor(url)`, `withRetry(...)`, `destroyKeepaliveAgents()`. Consumers: `fetchJson(url, token, options)` (`main.ts:5003`), `fetchPublicJson(url, options)` (`:5172`), `downloadViaTokenToFile` (`:5118`), `requestOptionsWithHeaders(options, headers)` (`:6057`), `withTransientRetries(...)` (`electron/connection-config.ts`). `DEFAULT_FETCH_TIMEOUT_MS` (15 s) comes from `hardening.ts`; `STARTUP_REQUEST_TIMEOUT_MS = 60_000` is the renderer-side boot-burst timeout (`src/api/client.ts:16`).
- **Inputs / options:** n/a
- **Outputs / side effects:** Pooled sockets, destroyed on teardown.
- **Config / env:** n/a
- **Edge cases / guards:** Only transient failures are retried; a 401/403 is a verdict, not a blip.
- **Rebuild notes:** Separate the JSON agent from the download agent; long streams starve a shared pool.

### Multipart upload body  `id: desktop-main.multipart-body`
- **Surface:** Core
- **Where:** Invisible; FastAPI `UploadFile` endpoints (e.g. kanban attachments).
- **What it does:** Builds a single-file `multipart/form-data` body by hand, because Node's `http` has no FormData and one file does not justify a dependency.
- **How it works:** `multipartBody(upload)` (`main.ts:4986-5001`) with boundary `----hermes-<24 hex>` and a filename sanitized by `replace(/["\r\n]/g, '_')`.
- **Inputs / options:** `{ filename, contentType, data, field }`.
- **Outputs / side effects:** A Buffer + headers.
- **Config / env:** n/a
- **Edge cases / guards:** Quote and newline injection into the filename is neutralized.
- **Rebuild notes:** Sanitize the filename — it lands in a header.

---

## 12. Platform bridges and quirks

### WSL detection and Windows-binary rejection  `id: desktop-main.wsl-detection`
- **Surface:** Core / Platform:WSL
- **Where:** Invisible; log `Ignoring Windows Hermes override under WSL: <path>`.
- **What it does:** Detects that the app is running inside WSL, and refuses to treat a Windows `.exe`/`.cmd`/`.bat`/`.ps1` as the Hermes CLI there.
- **How it works:** `isWslEnvironment(env, platform, kernelRelease)` (`electron/bootstrap-platform.ts:3-19`) — Linux plus `WSL_DISTRO_NAME`/`WSL_INTEROP`, or `/proc/sys/kernel/osrelease` matching `/microsoft|wsl/i`. `isWindowsBinaryPathInWsl(filePath, { isWsl, env, platform })` (`:21-41`) lower-cases and normalizes slashes before checking the four extensions. `bundledRuntimeImportCheck(platform)` (`:43`) returns `import fastapi, uvicorn, winpty` on Windows and `import fastapi, uvicorn, ptyprocess` elsewhere.
- **Inputs / options:** n/a
- **Outputs / side effects:** none.
- **Config / env:** env `WSL_DISTRO_NAME`, `WSL_INTEROP`.
- **Edge cases / guards:** `IS_WSL` is computed once at `main.ts:454`.
- **Rebuild notes:** WSL is Linux with a Windows filesystem attached — decide per-path, not per-process.

### WSL path bridge (per profile)  `id: desktop-main.wsl-path-bridge`
- **Surface:** Core / Platform:Windows + WSL
- **Where:** Invisible; the native folder dialog's default path and fs reads when the UI runs on Windows but the gateway runs inside WSL.
- **What it does:** Translates WSL/POSIX paths into forms the Windows host can open — and disables itself for profiles whose backend is genuinely remote.
- **How it works:** `electron/wsl-path-bridge.ts` (196 lines). `WIN_DRIVE_RE = /^([A-Za-z]):[\\/]/`, `WSL_MOUNT_RE = /^\/mnt\/([a-z])(?:\/(.*))?$/i`; caches `cachedDistro` / `cachedUncBase` derived from `wsl.exe -l -q` (which emits UTF-16LE without a BOM unless `WSL_UTF8=1`, so NUL bytes are stripped defensively). Eligibility is **per profile**, not process-global: `setActiveGatewayProfile(profile)`, `setWslBridgeProfileState(profile, active)`, `setWslBridgeActive(active)`, `isWslBridgeActive(profile)` (default `true` for unknown profiles). `resolvePickerDefaultPath(...)` is the exported consumer. Main sets state at boot (`main.ts:17386-17387`) and per connection: a remote primary calls `setWslBridgeProfileState(primaryProfile, false)` so native dialogs never spawn `wsl.exe` (or its interactive install prompt on WSL-less machines) for unresolvable remote paths (#66433).
- **Inputs / options:** n/a
- **Outputs / side effects:** Dialog default paths.
- **Config / env:** n/a
- **Edge cases / guards:** The reverse direction (backend path → POSIX) is handled once gateway-side in `hermes_constants.translate_cwd_for_wsl_backend`.
- **Rebuild notes:** One desktop process can hold a local *and* a remote backend at once — never make path translation a process-global flag.

### WSL Windows-font wiring  `id: desktop-main.wsl-fonts`
- **Surface:** Platform:WSL
- **Where:** Invisible; log `[fonts] wired WSL Windows fonts for renderer: <dir>`.
- **What it does:** Makes the Windows host's fonts visible to the Linux renderer under WSLg, so text renders with real fonts.
- **How it works:** `ensureWslWindowsFonts()` (`main.ts:1776-1821`): finds `/mnt/c/Windows/Fonts` or `/mnt/c/windows/fonts`, writes `~/.config/fontconfig/conf.d/99-hermes-wsl-windows-fonts.conf` containing `<fontconfig><dir><fontsDir></dir></fontconfig>` (skipping when the file already references that dir), and spawns `fc-cache -f <fontsDir>` detached + unref'd.
- **Inputs / options:** n/a
- **Outputs / side effects:** A fontconfig file; a background `fc-cache`.
- **Config / env:** n/a
- **Edge cases / guards:** Every failure is swallowed with `[fonts] WSL font setup skipped: <message>`.
- **Rebuild notes:** Idempotent config writes plus a detached cache rebuild.

### WSL clipboard image bridge  `id: desktop-main.wsl-clipboard-image`
- **Surface:** Platform:WSL
- **Where:** Pasting an image into the composer from a Windows app while Hermes runs in WSL.
- **What it does:** Reads an image the Windows clipboard holds when the Linux clipboard has none.
- **How it works:** `readWslWindowsClipboardImage(...)` (`electron/wsl-clipboard-image.ts`, 102 lines), used by `hermes:saveClipboardImage` (`main.ts:16391`).
- **Inputs / options:** `hermesDesktop.saveClipboardImage()`.
- **Outputs / side effects:** A saved image file.
- **Config / env:** n/a
- **Edge cases / guards:** Only attempted under WSL.
- **Rebuild notes:** Two clipboards exist under WSL; check both.

### Windows venv `hermes.exe` shim unwrapping  `id: desktop-main.windows-hermes-path`
- **Surface:** Core / Platform:Windows
- **Where:** Invisible; backend resolution step 4.
- **What it does:** Turns a Windows venv `hermes.exe` entry-point shim into the interpreter + module invocation the desktop can actually supervise.
- **How it works:** `unwrapWindowsVenvHermesCommand(command, backendArgs)` (`main.ts:2273-2299`) over `electron/windows-hermes-path.ts` (293 lines): `resolveVenvHermesCommand`, `getVenvSitePackagesEntries`, `buildPathExtCandidates` (the `PATHEXT` search order used by `findOnPath`), `chooseUpdaterArgs`.
- **Inputs / options:** n/a
- **Outputs / side effects:** A backend descriptor.
- **Config / env:** env `PATHEXT`.
- **Edge cases / guards:** The unwrap runs an import probe; the resolver deliberately does not re-run it a second time (it would cost another full probe timeout on the boot path for an answer already known).
- **Rebuild notes:** Supervise the interpreter, not the shim — the shim is what gets locked and replaced during an update.

### Hidden Windows child processes  `id: desktop-main.windows-child-options`
- **Surface:** Core / Platform:Windows
- **Where:** Invisible; every helper process the app spawns.
- **What it does:** Prevents a console window from flashing for every `ps`/`powershell`/`git`/`taskkill` invocation.
- **How it works:** `hiddenWindowsChildOptions(options)` (`electron/windows-child-options.ts`, 37 lines) merges `windowsHide: true` (and the equivalent creation flags) into spawn/exec options; applied throughout `main.ts`, `backend-claim.ts`, `bootstrap-runner.ts`, `updater-process.ts`.
- **Inputs / options:** n/a
- **Outputs / side effects:** none.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** One options helper; a single missed call site is a visible flash.

### Windows user-environment registry read  `id: desktop-main.windows-user-env`
- **Surface:** Core / Platform:Windows
- **Where:** Invisible; `HERMES_HOME` resolution.
- **What it does:** Reads a User-scoped environment variable straight from `HKCU\Environment`, because a GUI launched from Explorer inherits the login-time environment block and misses a post-login `setx`.
- **How it works:** `readWindowsUserEnvVar(name)` (`electron/windows-user-env.ts`, 99 lines) shells `reg query HKCU\Environment /v <name>`, parses the value line with a type-aware regex (`REG_SZ|REG_EXPAND_SZ|REG_MULTI_SZ|REG_DWORD|REG_QWORD|REG_BINARY|REG_NONE`) preserving embedded spaces, and expands `%VAR%` references against the current env.
- **Inputs / options:** the variable name.
- **Outputs / side effects:** none.
- **Config / env:** n/a
- **Edge cases / guards:** Unknown `%VAR%` references are left verbatim (#45471).
- **Rebuild notes:** `process.env` on Windows is a snapshot; read the registry when the answer must be current.

---

## 13. Wire protocols — the `hermes:api` REST proxy and the JSON-RPC WebSocket

### `hermes:api` — the main-process REST proxy  `id: desktop-main.hermes-api`
- **Surface:** Core / API
- **Where:** `window.hermesDesktop.api(request)`; every REST helper under `apps/desktop/src/api/` goes through it.
- **What it does:** Routes a renderer REST call to the correct backend — a registered gateway, a remote profile's own host, or the local primary/pool — and attaches the right credentials for that backend's auth mode.
- **How it works:** `ipcMain.handle('hermes:api', …)` (`main.ts:16025-16055`) → `handleHermesApiRequest(request)` (`:15908-16023`). Order: (1) `apiRequestRegistryConnectionId(request)` — a registry-pinned request (including an explicit `'local'`, so it can never inherit a v1 remote) goes to `dispatchRegistryApiRequest(request, connectionId, routeProfile?, deletingProfile?)` (`:15861`); (2) `interceptSessionRequestForRemote(request)` reroutes session reads/mutations that belong to a remote profile's own host; (3) `prepareProfileRenameRequest` and `prepareProfileDeleteRequest` perform the lifecycle side effects; (4) `resolveProfileApiRequest(profile, path, profileRouteOptions(profile, request))` picks the backend profile and rewrites the path (adding `?profile=` where the handler supports it — `LOCAL_PRIMARY_SCOPED_ROUTES` and `localPrimaryRequestScope` in `electron/connection-config.ts`, plus `pathWithGlobalRemoteProfile`, `pathWithProfileScope`, `pathForRegistryBackendRequest`, `translateSelfProfileQuery`); (5) `ensureBackend(routeProfile)`; (6) auth: `oauth` mode prefers a native bearer (`ensureNativeAccessToken`, transparently refreshing a near-expiry AT via `/auth/native/refresh`) and otherwise rides Electron's `net` bound to the OAuth partition; token/local modes send the static `X-Hermes-Session-Token` header.
- **Inputs / options:** `HermesApiRequest` = `{ path, method?, body?, upload?, timeoutMs?, profile?, connectionId? }`.
- **Outputs / side effects:** The parsed JSON response, or a throw.
- **Config / env:** default timeout `DEFAULT_FETCH_TIMEOUT_MS` (15 s), overridden per request; the renderer's boot burst uses `STARTUP_REQUEST_TIMEOUT_MS = 60_000`.
- **Edge cases / guards:** `File uploads are not supported against OAuth-gated remote backends yet.` (the OAuth path rides `electron.net` with JSON headers; multipart is not wired there, and failing loudly beats a corrupted upload). A profile-delete or rename holds `profileDeletionGate.acquire(profile)` for the whole request so a concurrent renderer reconnect cannot respawn the old-name backend and recreate its `HERMES_HOME` (#45474). A failed rename PATCH rolls back to the original active profile and restarts its backend.
- **Rebuild notes:** Put routing and credentials in one privileged place; the renderer should never know which host it is talking to.

### Cross-gateway session list merging  `id: desktop-main.session-merge`
- **Surface:** Core
- **Where:** The Sessions sidebar, which shows every connected gateway's chats.
- **What it does:** Merges the local primary's session aggregate with each remote profile's real rows and every connected registry gateway's sessions, re-sorted and re-windowed for the requested page.
- **How it works:** `interceptSessionRequestForRemote(request)` (`main.ts:15536-15670`) handles `GET /api/profiles/sessions` and `GET /api/profiles/sessions/sidebar`. With no remote profiles and no connected registry gateways it returns `undefined` (the byte-identical local fast path — the batched endpoint's single DB open). Otherwise: a specific remote-override profile → `remoteSessionList(profile, searchParams)` (`:15676`, stamping `profile` and `is_default_profile: false` on each row); `all` → `mergeRemoteProfileSessions(searchParams, remoteProfiles)` (`:15745`), which over-fetches each remote from offset 0 with `limit + offset` rows so the merged window is correct for the page, then splices in `pooledRegistrySessionSources()` (`:15814`) rows tagged with `connection_id` + `profile` so opens route correctly (#88880). The sidebar path fans out three slices via `buildSidebarSessionSliceParams(searchParams)` and `fetchProfilesSessionSlice(...)` (`:15725`). Owner lookup for a hint-less session id: `remoteOwnerProfileForSession(sessionId)` (`:15694`) memoized for `REMOTE_OWNER_CACHE_TTL_MS = 30_000` (#85834). Pure helpers in `electron/profile-session-routing.ts` (455 lines): `buildSidebarSessionSliceParams`, `fetchPrimaryProfileSessions`, `fetchRegistrySessionRows`, `fetchRemoteProfileSessions`, `findRemoteOwnerProfileForSession`, `mergeProfileSessionWindow`, `spliceRegistrySessionRows`, `tagRegistrySessionResponse`.
- **Inputs / options:** the REST query params (`profile`, `limit`, `offset`, `order`).
- **Outputs / side effects:** A merged response shape identical to the backend's.
- **Config / env:** n/a
- **Edge cases / guards:** A dead remote contributes nothing rather than breaking the sidebar.
- **Rebuild notes:** Over-fetch from offset 0 per source, merge, then window — paging a merged list any other way is wrong.

### JSON-RPC over WebSocket — the wire  `id: desktop-main.jsonrpc-wire`
- **Surface:** API / Core
- **Where:** `ws(s)://<host><prefix>/api/ws?token=…` or `?ticket=…`.
- **What it does:** The single bidirectional protocol the desktop renderer speaks to the Hermes gateway: newline-delimited JSON-RPC 2.0 requests/responses plus server-pushed `event` notifications — identical to the stdio protocol the TUI uses.
- **How it works:** Server: `@app.websocket("/api/ws")` (`hermes_cli/web_server.py:17618`) gates on `_DASHBOARD_EMBEDDED_CHAT_ENABLED` (close **4403**), `_ws_auth_ok(ws)` (close **4401**) and `_ws_request_is_allowed(ws)` (close **4403**), then delegates to `handle_ws(ws, auth_identity, subprotocol)` (`tui_gateway/ws.py`), which reuses `tui_gateway.server.dispatch` verbatim so every RPC method, slash command, approval/clarify/sudo flow and agent event behaves identically over stdio and WS. The server emits a `gateway.ready` event immediately after accept. Client: `class JsonRpcGatewayClient` (`apps/shared/src/json-rpc-gateway.ts`, 755 lines) subclassed as `HermesGateway` (`apps/desktop/src/api/client.ts:28`). Requests are `{ jsonrpc: '2.0', id, method, params }`; responses carry `result` or `error` (`{ code, message, data }` → `JsonRpcGatewayError` with `.code`/`.data`); notifications are `{ method: 'event', params: { type, session_id?, seq?, payload? } }`.
- **Inputs / options:** client options `{ closedErrorMessage, connectErrorMessage, connectTimeoutMs, createRequestId, heartbeatDeadlineMs, heartbeatIntervalMs, notConnectedErrorMessage, onSocketClose, requestIdPrefix, requestTimeoutMs, socketFactory }`. Desktop values: `closedErrorMessage: 'Hermes gateway connection closed'`, `connectErrorMessage: 'Could not connect to Hermes gateway'`, `notConnectedErrorMessage: 'Hermes gateway is not connected'`, `createRequestId: nextId => nextId` (numeric ids), `requestTimeoutMs: 30_000`. Shared defaults: `DEFAULT_REQUEST_TIMEOUT_MS = 120_000`, `REPLAY_REQUEST_TIMEOUT_MS = 10_000`, `DEFAULT_HEARTBEAT_INTERVAL_MS = 15_000`, `DEFAULT_HEARTBEAT_DEADLINE_MS = 45_000`, `DEFAULT_CONNECT_TIMEOUT_MS = 15_000`. Per-call override `PROMPT_SUBMIT_REQUEST_TIMEOUT_MS = 1_800_000` matches the backend's `agent.gateway_timeout` so a long turn's ack never falsely times out (#55024).
- **Outputs / side effects:** `connect(wsUrl)`, `close()`, `invalidate(message)`, `request<T>(method, params, timeoutMs, signal)`, `on(type, handler)`, `onAny(handler)`, `onEvent(handler)`, `onState(handler)`, `getSeqWatermarks()`; connection states `'idle' | 'connecting' | 'open' | 'closed' | 'error'`.
- **Config / env:** backend `agent.gateway_timeout`, `agent.build_wait_timeout`.
- **Edge cases / guards:** `connect()` refuses a non-string or non-`ws:`/`wss:` URL (WebSocket would otherwise coerce an object into `ws://<origin>/[object%20Object]`, the #68250 stale-emit boot loop). A connect that does not open within `connectTimeoutMs` closes the half-open socket and fails to `'error'` so callers can retry (a reconnect after sleep otherwise hangs in `'connecting'` with the composer stuck on "Starting Hermes..."). A timed-out request rejects with `request timed out after <N>s: <method>`, naming the configured window.
- **Rebuild notes:** One dispatch table serving stdio and WebSocket is what keeps three front ends behaviourally identical.

### Heartbeat and lossless reconnect replay  `id: desktop-main.jsonrpc-replay`
- **Surface:** Core / API
- **Where:** Invisible; after any socket drop (sleep/wake, network change, backend restart).
- **What it does:** Detects a dead-but-open socket, and on reconnect replays the events emitted while disconnected — without duplicating or skipping any.
- **How it works:** `apps/shared/src/json-rpc-gateway.ts`. Heartbeat starts only when the `gateway.ready` payload advertises it (`gatewayReadyAdvertisesHeartbeat`), pinging every 15 s and declaring the socket dead after 45 s without inbound traffic. Replay: `recordSeq(event)` tracks the highest `seq` per `session_id`; on `open` the client fires `fetchReplay()` (fire-and-forget so connect latency is unaffected, and only when watermarks exist), issuing one `session.events.since` RPC per known session with `{ session_id, last_seen }` and a 10 s timeout. While a replay is in flight, live seq'd frames for those sessions are **parked** in `replayHold` and flushed afterwards gated on seq, so a live frame racing the replay can neither dispatch twice nor advance the watermark past the gap. `dispatchIfNewer(event)` drops any event whose seq does not advance the watermark; seq-less events always dispatch. `replayEpoch` (from `gateway.ready`'s `replay_epoch` and from `session.events.since` responses) detects a backend restart — seq counters are in-process, so a restart resets them and the old watermarks are meaningless; `adoptReplayEpoch(epoch)` clears them.
- **Inputs / options:** n/a
- **Outputs / side effects:** Replayed events through the normal dispatch path.
- **Config / env:** n/a
- **Edge cases / guards:** Replay failures are swallowed entirely — it is an optimization over lossy reconnect and must never surface an error.
- **Rebuild notes:** Per-session sequence watermarks plus a server epoch is the minimum honest resume contract.

### Gateway event vocabulary  `id: desktop-main.gateway-events`
- **Surface:** API
- **Where:** Every `{ method: 'event' }` frame.
- **What it does:** Names the server-pushed events the renderer subscribes to.
- **How it works:** `GatewayEventName` (`apps/shared/src/json-rpc-gateway.ts:1-25`) enumerates: `gateway.ready`, `session.info`, `session.usage`, `message.start`, `message.delta`, `message.interim`, `message.complete`, `thinking.delta`, `reasoning.delta`, `reasoning.available`, `status.update`, `tool.start`, `tool.progress`, `tool.complete`, `tool.generating`, `todo.updated`, `clarify.request`, `approval.request`, `sudo.request`, `secret.request`, `background.complete`, `error`, `skin.changed`, and is open-ended (`(string & {})`) so new server events are not dropped. Event shape: `{ type, payload?, session_id?, seq?, profile?, connectionId? }` — `profile` and `connectionId` are **renderer-side source tags** added by the desktop gateway registry, never sent by the server. The server coalesces the high-frequency streaming types `message.delta`, `reasoning.delta`, `thinking.delta` into ~33 ms batches (`_STREAMING_EVENT_TYPES`, `_TOKEN_COALESCE_S = 0.033` in `tui_gateway/ws.py`); anything a client must see promptly flushes the buffer ahead of itself, so ordering is preserved.
- **Inputs / options:** n/a
- **Outputs / side effects:** none.
- **Config / env:** n/a
- **Edge cases / guards:** `_WS_WRITE_TIMEOUT_S = 10.0` bounds how long a pool-dispatched handler waits for the loop to flush a frame before the transport is marked dead.
- **Rebuild notes:** Tag the source in the client, not the server, so one socket registry can multiplex many gateways.

### RPC methods the desktop renderer calls  `id: desktop-main.rpc-methods-used`
- **Surface:** API
- **Where:** `gateway.request(method, params)` from the renderer.
- **What it does:** Enumerates the JSON-RPC methods the desktop surface actually invokes. (The full 188-method server table and per-method semantics belong to the `tui` shard; this is the desktop's usage.)
- **How it works:** Server registration is `@method("<name>")` into `_methods`, dispatched by `handle_request(req)` → `_methods.get(method)` (`tui_gateway/server.py:3024-3040`); unknown methods answer `-32601 unknown method: <name>`. `dispatch(req, transport)` (`:3065`) routes anything in `_LONG_HANDLERS` onto a thread pool (so `approval.respond` / `session.interrupt` are never blocked behind a slow handler) and everything else inline. Methods the desktop calls, grouped:
  - **Turn lifecycle:** `prompt.submit`, `prompt.background`, `prompt.btw`, `session.interrupt`, `session.steer`, `session.redirect`, `subagent.interrupt`, `subagent.steer`.
  - **Sessions:** `session.create`, `session.resume`, `session.activate`, `session.close`, `session.list`, `session.active_list`, `session.most_recent`, `session.history`, `session.title`, `session.save`, `session.delete`, `session.status`, `session.usage`, `session.context_breakdown`, `session.compress`, `session.branch`, `session.undo`, `session.set_hidden`, `session.cwd.set`, `session.workspace.move`, `session.events.since`, `session.events.stats`.
  - **Approvals and prompts:** `approval.pending`, `approval.received`, `approval.respond`, `clarify.respond`, `secret.respond`, `sudo.respond`, `tour.respond`, `mcp.setup.respond`, `preview.act.respond`, `preview.read.respond`, `terminal.read.respond`, `window.read.respond`.
  - **Config and capabilities:** `config.get`, `config.set`, `config.show`, `reload.env`, `reload.mcp`, `skills.manage`, `skills.reload`, `tools.list`, `tools.show`, `tools.configure`, `toolsets.list`, `plugins.list`, `plugins.manage`, `mcp.catalog`, `mcp.servers.list/add/remove/test/set_api_key`, `mcp.servers.oauth.start/callback/poll`.
  - **Profiles and agents:** `profiles.list`, `profiles.create`, `profiles.configure`, `profiles.describe`, `profiles.get_asset`, `profiles.set_asset`, `agents.list`.
  - **Execution:** `cli.exec`, `slash.exec`, `shell.exec`, `command.dispatch`, `command.resolve`, `commands.catalog`, `process.list`, `process.kill`, `process.stop`, `terminal.resize`.
  - **Attachments and media:** `file.attach`, `image.attach`, `image.attach_bytes`, `image.detach`, `image.generate`, `pdf.attach`, `clipboard.paste`, `paste.collapse`, `input.detect_drop`.
  - **Pets:** `pet.info`, `pet.info.meta`, `pet.cells`, `pet.thumb`, `pet.gallery`, `pet.select`, `pet.generate`, `pet.generate.status`, `pet.cancel`, `pet.hatch`, `pet.rename`, `pet.scale`, `pet.export`, `pet.remove`, `pet.disable`.
  - **Wake word / voice:** `wake.start`, `wake.stop`, `wake.pause`, `wake.resume`, `wake.status`, `wake.feed`, `voice.toggle`, `voice.record`, `voice.tts`.
  - **Bots and groups:** `bot_relay.deliver`, `bot_relay.reply`, `bot_relay.outbox.drain`, `bot_relay.roster.sync`, `message.react`, `groups.*` (create/list/state/send/log/approve/promote/demote/rename/disband/retry/stop/capabilities/replicate/replica_state/peer.invite/peer.register/peer.revoke).
  - **Model and billing:** `model.options`, `model.save_key`, `model.disconnect`, `llm.oneshot`, `billing.state`, `billing.charge`, `billing.charge_status`, `billing.auto_reload`, `billing.step_up`, `subscription.state/preview/change/resume/upgrade`, `usage.bars`.
  - **Other:** `ping`, `cron.manage`, `complete.path`, `complete.slash`, `insights.get`, `learning.frames`, `learning.detail`, `learning.edit`, `learning.delete`, `projects.tree`, `projects.discover_repos`, `projects.record_repos`, `projects.project_sessions`, `project.facts`, `rollback.list`, `rollback.diff`, `rollback.restore`, `spawn_tree.list/save/load`, `handoff.request`, `handoff.state`, `handoff.fail`, `delegation.status`, `delegation.pause`, `setup.status`, `setup.runtime_check`, `verification.status`, `diagnostics.share_nous`, `system.battery`, `browser.manage`, `browser.controller.register/heartbeat/result/detach`, `preview.restart`.
- **Inputs / options:** per method (see the `tui` shard).
- **Outputs / side effects:** per method.
- **Config / env:** `agent.build_wait_timeout` (default 600 s) bounds how long `prompt.submit` waits for a deferred agent build.
- **Edge cases / guards:** `isMissingRpcMethod(error)` (`src/lib/gateway-rpc.ts:2`) matches `/method not found|-32601|unknown method|no such method/i` so the renderer can feature-detect an older backend; `isMissingRestEndpoint(error)` is its REST twin (matching `no such api endpoint`, `endpoint is likely missing`, or a leading `404`, and deliberately **not** timeouts/5xx/refused, which are retryable); `isMissingPendingPromptRequest(error, key)` matches `no pending <key> request` (a response that raced a backend-side timeout); `isBusySessionModelSwitch(error)` matches a pre-deferral backend refusing a mid-turn model switch (4009).
- **Rebuild notes:** Feature-detect by error shape, not by version numbers.

### Backend-exit and connection-applied pushes  `id: desktop-main.backend-exit-events`
- **Surface:** Core
- **Where:** Invisible; the renderer's reconnect logic.
- **What it does:** Tells every window when the managed backend died, and when a soft gateway-mode apply finished tearing it down.
- **How it works:** `sendBackendExit(payload)` (`main.ts:6224`) → `hermes:backend-exit` with `{ code, signal }` or `{ code: null, signal: null, error }`. `sendConnectionApplied()` (`:10875`) → `hermes:connection:applied` (renderer wipes session lists and re-dials without a window reload). `broadcastConnectionsChanged(payload)` (`:10894`) → `hermes:connections:changed`.
- **Inputs / options:** `hermesDesktop.onBackendExit(cb)`, `.onConnectionApplied(cb)`, `.connections.onChanged(cb)`.
- **Outputs / side effects:** IPC.
- **Config / env:** n/a
- **Edge cases / guards:** Stale exits from a superseded process are logged (`Ignoring stale Hermes backend exit (<signal|code>)`) and not broadcast.
- **Rebuild notes:** Distinguish "our backend died" from "we deliberately swapped backends"; the renderer reacts differently.

---

## 14. Desktop plugin SDK, plugin installation, and the theme engine

> The SDK's *individual UI components* and the Settings → Plugins pane are documented by the
> `desktop-a` / `desktop-b` / `desktop-settings` shards; this section documents the SDK contract,
> the loader, the install paths and the theme engine.

### `@hermes/plugin-sdk` — the plugin language  `id: desktop-main.plugin-sdk`
- **Surface:** Tool / Core
- **Where:** `import { host, ui, … } from '@hermes/plugin-sdk'` inside a plugin.
- **What it does:** The single module a plugin author imports. Plugins never touch `@/…` internals (lint-fenced) and never need codebase access.
- **How it works:** `apps/desktop/src/sdk/index.ts` (78 KB). Capability tiers: `host.state.*` — **readonly** app state as nanostore atoms (`.get()`, subscribe, or `useValue` in React); `host.*` actions — curated safe verbs; `host.request` — the gateway JSON-RPC door (the plugin's real power, and the future seam for per-plugin capability grants); `ui.*` — the design language so plugin UI looks native by default. Two delivery modes share one surface: **bundled** plugins under `src/plugins/<name>/` resolve the import through a Vite alias, and **runtime** plugins get the same object injected as `window.__HERMES_PLUGIN_SDK__`.
- **Inputs / options:** see the individual entries below.
- **Outputs / side effects:** Registered contributions.
- **Config / env:** n/a
- **Edge cases / guards:** Every `host` door is async-safe — a synchronous throw from an internal helper (e.g. no desktop bridge in a plain browser) becomes a rejection the plugin's `.catch()` sees, never an error-boundary crash.
- **Rebuild notes:** One import surface, tiered by capability, is what makes third-party UI feel native.

### `host.state` — readonly app state  `id: desktop-main.sdk-host-state`
- **Surface:** Tool
- **Where:** `host.state.<atom>`.
- **What it does:** Exposes the app's live state as readonly atoms.
- **How it works:** `readonlyAtom(...)` wrappers (`src/sdk/index.ts:580-627`). Complete list: `activeSessionId` (runtime id of the active chat, `null` on a draft), `awaitingResponse` (send → first assistant payload on the focused chat), `busy` (focused chat working after a send; a draft with no runtime id uses the global flag), `busyBySession` (`Record<string, boolean>` — mid-turn, not socket state), `connectionId` (registry source owning the active gateway), `cwd` (`''` when detached), `focusedSessionId` (the interacted tile, else the primary — prefer this for any readout that should follow the user between tiles), `focusedSessionOwner` (`{ connectionId, profile }` — prefer for source routing), `focusedSessionProfile` (compatibility projection), `focusedStoredSessionId` (durable id for navigation and session-list matching), `focusedUsage` (`context_used`/`context_max`/`context_percent`, token counts, `cost_usd` — streamed, no RPC), `gateway` (socket state string), `model` (main model slug), `profile` (profile the live gateway is routed to), `viewport` (`{ width, height, narrow }`).
- **Inputs / options:** `useValue(atom)` (re-exported `@nanostores/react` `useStore`).
- **Outputs / side effects:** none.
- **Config / env:** n/a
- **Edge cases / guards:** Atoms are readonly by construction.
- **Rebuild notes:** Readonly state + explicit verbs beats handing out the store.

### `host` action doors  `id: desktop-main.sdk-host-actions`
- **Surface:** Tool
- **Where:** `host.<verb>(…)`.
- **What it does:** The curated verbs a plugin may perform.
- **How it works:** every door is defined on the exported `host` object in `apps/desktop/src/sdk/index.ts` and wrapped so a synchronous internal throw becomes a rejection.
- **Inputs / options:** each with its source line in `src/sdk/index.ts`:
  - `notify` / `notifyError` — toast into the app's notification stack (`:630-631`).
  - `logs(...)` — tail an app log file (`agent` / `errors` / `gateway` / `gui` / …) (`:637`).
  - `navigate(path)` — hash-route navigation, e.g. `'/command-center?section=system'` (`:640`).
  - `warmProfile(profile)` — fire-and-forget socket pre-warm (pool-only, no activation/navigation/scope change) so the first click on an agent does not pay the cold spawn (`:651`).
  - `deleteProfile(profile | route)` — delete through the desktop's teardown-routed REST path, the same door `DeleteProfileDialog` uses; a route requires `connectionId`, `profile` and `targetProfile` (`:671`). Plugins must prefer this over `cli.exec ['profile','delete',…]`, which bypasses the interception entirely (#52279).
  - `activeConnectionId()` (`:762`), `connections()` (`:766` — labels, kinds, primary id; **never** token material), `agents()` (`:783` — the union roster with precomputed `@name-device` handles), `warmAgent(connectionId, profile)` (`:797`), `ensureAgent(connectionId, profile)` (`:807`).
  - `openSession(storedSessionId, options)` (`:817`), `openWorkspace(...)` (`:1111`), `setWorkspaceScope(...)` (`:1164`), `newChat(profile | route, options)` (`:1173`), `focusOpenWorkspaceSession(...)` (`:1218`), `paneVisibility(paneId)` → a `ReadableAtom<boolean>` (`:1229`).
  - `onEvent(listener)` — subscribe to gateway events (`:1234`).
  - `restartGateway()` (`:1237`), `status()` (`:1240`), `profileRoutes()` (`:1244`).
  - `requestProfile<T>(route, method, params)` (`:1273`), `retainProfileSocket(route)` → an unsubscribe function (`:1286`), `retainProfile(route)` (`:1301`).
  - `listPersistedSessions(...)` (`:1315`), `setPersistedSessionHidden(...)` (`:1350`).
  - `request<T>(method, params)` — the raw gateway JSON-RPC door (`:1374`); `getGateway()` → the live `HermesGateway | null` (`:1389`).
  - Session hydration timeouts: `DEFAULT_SESSION_HYDRATION_TIMEOUT_MS = 20_000` (`:326`), `BOT_CHAT_SESSION_HYDRATION_TIMEOUT_MS = 60_000` (`:330`).
- **Outputs / side effects:** As documented per verb.
- **Config / env:** n/a
- **Edge cases / guards:** All four multi-gateway doors (`connections`, `agents`, `ensureAgent`, `warmAgent`) are **feature-detected**: on an older Desktop build they are absent and a plugin should fall back to the single-gateway `profiles.list` flow. Bot Mode is the reference consumer.
- **Rebuild notes:** Expose routing verbs, not connection records; and make every new door feature-detectable.

### Contribution areas  `id: desktop-main.sdk-contribution-areas`
- **Surface:** Tool
- **Where:** `registry.register(area, contribution)` with the SDK's area ids.
- **What it does:** The named extension points a plugin registers into — the same ids and payload types core itself uses.
- **How it works:** Exported area constants and types from `src/sdk/index.ts`: `PANES_AREA = 'panes'` (`:1650`), `STATUSBAR_AREAS = { left: 'statusBar.left', right: 'statusBar.right' }` (`:1660`), `TITLEBAR_AREAS = { center: 'titleBar.center', left: 'titleBar.left', right: 'titleBar.right' }` (`:1661`), `PALETTE_AREA` + `PaletteContribution`, `ROUTES_AREA` + `RouteContribution`, `SIDEBAR_NAV_AREA` + `SidebarNavContribution`, `THEMES_AREA`, `TRANSCRIPT_DIRECTIVE_AREA` + `TranscriptDirectiveContribution`/`TranscriptDirectiveProps` (register a named `::directive{...}` and the model can render your component inline in assistant messages), `COMPOSER_AREAS` with `ComposerAtCompletionItem`, `ComposerAtCompletionSource`, `ComposerAttachmentProvider`, `ComposerMiddleware`, plus `StatusbarItem`, `TitlebarTool`, `Contribution`, `GatewayEventListener`, `FloatingAnchor`.
- **Inputs / options:** per area.
- **Outputs / side effects:** UI contributions, live-registered and unregistered.
- **Config / env:** n/a
- **Edge cases / guards:** Panes, pages, sidebar nav, statusbar items, palette commands, keybinds and themes all register through the one registry, so disabling a plugin unregisters everything it added without a restart.
- **Rebuild notes:** Use the same registry for core and plugins — anything else drifts.

### SDK design-language exports  `id: desktop-main.sdk-ui`
- **Surface:** Tool
- **Where:** `import { SessionStatusDot, PanelList, … } from '@hermes/plugin-sdk'`.
- **What it does:** Re-exports the exact primitives core renders, so plugin UI cannot drift from the app.
- **How it works:** From `src/sdk/index.ts`: `SessionStatusDot` + `SessionStatusDotProps` (the one status primitive — resolves live state and project color from a stored session id; never hand-roll a dot beside it), `SidebarRowLead` + `SIDEBAR_ROW_LEAD` / `SIDEBAR_TRUNCATED_LEADING` (row geometry), `ConnectionGlyph` (one glyph per gateway kind — device, cloud, terminal, network), the master-detail toolkit `PanelAction`, `PanelAddButton`, `PanelBlock`, `PanelBody`, `PanelDetail`, `PanelEmpty`, `PanelHeader`, `PanelList`, `PanelListRow`, `PanelMenuItem`, `PanelMeta`, `PanelMetaRow`, `PanelPill`, `PanelPillTone`, `PanelRowMenu`, `PanelSectionLabel` (the overlay-bound `Panel` root is deliberately not exported), `ToolsetConfigPanel`, `ModelCatalogMenu` + `ModelChoice`/`ModelMenuController`/`ModelMenuCloseContext`, `SkillsView` (with `embedded`, `fixedProfile`, `fixedConnection` — probe `SkillsView.supportsFixedConnection` first), `PROFILE_SWATCHES` / `profileColor` / `profileColorSoft`, `queryClient` + `useQuery`/`useMutation`/`useQueryClient`, `DEFAULT_REASONING_EFFORT` / `REASONING_EFFORT_VALUES` / `REASONING_EFFORTS` / `ReasoningEffort` / `reasoningEffortLabel`, `evaluateRuntimeReadiness` + `RuntimeReadinessResult`, time helpers `AgoLabels` / `coarseElapsed` / `fmtDateTime` / `fmtDayTime` / `formatAgo` / `relativeTime`, `cn`, the unread store `ackStoredSessionId` / `forgetSessionUnread` / `markSessionUnreadFinished`, theme doors `$accentOverride` / `setAccentOverride` / `useTheme` / `requestTheme` / `retintTheme` / `themeHue` / `DesktopTheme` / `DesktopThemeColors`, the OKLCH colour maths `contrastRatio` / `hexToOklch` / `hueDelta` / `maxChroma` / `mixOklab` / `normalizeHex` / `Oklch` / `oklchToHex` / `oklchToSrgb255` / `readableOn`, `atom` / `computed` (nanostores), `useValue`, `blobatarSvg` / `Blobatar`, `HermesOpenTarget`, `RpcEvent` / `StatusResponse`, `HermesGateway`, and the markdown renderer core chat uses.
- **Inputs / options:** per component.
- **Outputs / side effects:** none.
- **Config / env:** n/a
- **Edge cases / guards:** `$accentOverride` is deliberately **not** persisted — it is an authoring knob, so a plugin that sets it must clear it on dispose.
- **Rebuild notes:** Ship the primitives, not a style guide.

### Runtime SDK injection and the import map  `id: desktop-main.sdk-runtime`
- **Surface:** Core / Tool
- **Where:** Invisible; how a disk-loaded plugin resolves `@hermes/plugin-sdk`.
- **What it does:** Lets a runtime-loaded ESM plugin import the same bare specifiers a bundled one does, sharing the app's React singletons.
- **How it works:** `apps/desktop/src/sdk/runtime.ts`. `installPluginSdk()` assigns `globalThis.__HERMES_PLUGIN_SDK__`, `__HERMES_REACT__`, `__HERMES_REACT_JSX__`, `__HERMES_REACT_JSX_DEV__`. `sdkImportMap()` returns a specifier → blob-URL map for `'@hermes/plugin-sdk'`, `'react/jsx-dev-runtime'`, `'react/jsx-runtime'`, `'react'`, each a generated shim module that re-exports the live global's members (`export default m.default ?? m;` plus a guarded `export const { … } = m;` built from the namespace's own keys, so the export list cannot drift). The map is cached and consumed longest-key-first by the loader.
- **Inputs / options:** n/a
- **Outputs / side effects:** Blob URLs.
- **Config / env:** n/a
- **Edge cases / guards:** React must be the app's singleton — a second React instance breaks hooks. Only identifier-safe export names are emitted, and the destructuring line is omitted entirely when a namespace has no named exports (`export const { } = m` is a syntax error).
- **Rebuild notes:** Generate the shim from the namespace at runtime; a hand-maintained re-export list rots.

### Disk plugin door  `id: desktop-main.plugin-disk-door`
- **Surface:** Desktop app / Tool
- **Where:** `$HERMES_HOME/desktop-plugins/<id>/plugin.js` (profile-aware: `profiles/<name>/desktop-plugins/…`); managed in **Settings → Plugins**.
- **What it does:** A plugin is a single ESM file dropped in that folder; the app loads it within seconds and hot-reloads on every save.
- **How it works:** The root is resolved by `hermes:fs:desktopPluginsRoot` in the **main** process (see `desktop-main.fs-ipc`). Bundled plugins live at `apps/desktop/src/plugins/<name>/plugin.{ts,tsx}` and register automatically at boot via a Vite glob in `src/contrib/plugins.ts`, with the same inventory + live enable/disable contract as runtime plugins. A unified plugin package may ship `desktop/plugin.js` alongside its Python code (mirroring `dashboard/manifest.json`), and the disk door also scans `hermes:fs:agentPluginsRoot` (`$HERMES_HOME/plugins`) for it — one installable folder serving both SDKs.
- **Inputs / options:** `hermesDesktop.desktopPluginsRoot()`, `.agentPluginsRoot()`, `.readPluginSource(filePath)` (capped at 16 MiB), `.openDir(dirPath)`.
- **Outputs / side effects:** Loaded plugins.
- **Config / env:** n/a
- **Edge cases / guards:** The root must be resolved locally, not from the connected backend's reported `hermes_home` (#66899).
- **Rebuild notes:** One file, one folder, hot reload — anything more is a build step users will not do.

### Install a desktop plugin from Git  `id: desktop-main.plugin-install-git`
- **Surface:** Desktop app / Tool
- **Where:** **Settings → Plugins → install from a repo**; also reachable as `hermes://plugin/install?repo=owner/repo`.
- **What it does:** Probes a Git repository for agent/desktop plugin components, then clones and installs the desktop half into the local plugin root.
- **How it works:** `electron/desktop-plugin-install.ts` (446 lines). `resolvePluginGitUrl(identifier)` accepts a bare `owner/repo`, or a full `https://` / `git@` / `ssh://` / `file://` URL, and understands GitHub browser URLs — `GITHUB_BROWSER_SEGMENTS = { tree, blob, commit }` — extracting a repository subdirectory when present. `probePluginRepo(payload)` returns `{ ok, agent, desktop, agentName, desktopName, warnings, insecure, error? }` (a `PluginComponentDetection` also carries `desktopSourceSubdir`). `installDesktopPluginFromGit(...)` returns `{ ok, pluginName?, path?, error? }`. IPC `hermes:plugin:probe` and `hermes:plugin:installDesktop` (registered in `fs-ipc.ts`).
- **Inputs / options:** `hermesDesktop.probePluginRepo({ identifier | repo })`, `.installDesktopPlugin(payload)`.
- **Outputs / side effects:** A cloned plugin folder under the desktop-plugins root.
- **Config / env:** n/a
- **Edge cases / guards:** `Plugin identifier is required.` for a blank id; `insecure` flags non-HTTPS sources; warnings surface to the renderer, which requires explicit user confirmation for anything install-shaped arriving via a deep link.
- **Rebuild notes:** Probe first, install second, and always require confirmation for a link-initiated install.

### VS Code Marketplace theme import  `id: desktop-main.vscode-marketplace`
- **Surface:** Desktop app
- **Where:** **Settings → Appearance → VS Code Marketplace search**; command palette **Install theme**.
- **What it does:** Searches the Marketplace for color themes, downloads the extension, and converts every color theme it contributes into a desktop theme — without executing any extension code.
- **How it works:** `electron/vscode-marketplace.ts` (337 lines). `searchMarketplaceThemes(query, 20)` and `fetchMarketplaceThemes(id)` POST the (undocumented but stable) gallery ExtensionQuery API at `https://marketplace.visualstudio.com/_apis/public/gallery/extensionquery`, resolve the `Microsoft.VisualStudio.Services.VSIXPackage` asset, download the `.vsix` and read `package.json` plus the referenced `*.json` theme files straight out of the zip — the central directory is parsed and entries inflated with `zlib`, so no zip dependency enters the bundle. Limits: `MAX_VSIX_BYTES = 40 * 1024 * 1024`, `MAX_REDIRECTS = 5`, `REQUEST_TIMEOUT_MS = 20_000`, id shape `/^[\w-]+\.[\w-]+$/`. IPC `hermes:vscode-theme:search` (`main.ts:17178`) and `hermes:vscode-theme:fetch` (`:17175`).
- **Inputs / options:** `hermesDesktop.themes.searchMarketplace(query)`, `.fetchMarketplace(id)`.
- **Outputs / side effects:** Raw theme JSON handed to the renderer.
- **Config / env:** n/a
- **Edge cases / guards:** **No theme code is ever executed** — only JSON is read out of the archive.
- **Rebuild notes:** A `.vsix` is a zip; read it yourself rather than adding a dependency for one feature.

### Theme engine and user themes  `id: desktop-main.theme-engine`
- **Surface:** Desktop app / Tool
- **Where:** **Settings → Appearance**; `/skin` in chat; ⌘K theme switching.
- **What it does:** Paints the app from a `DesktopTheme` — built-in presets plus user-installed (converted) themes — deriving every surface token from a small seed chain.
- **How it works:** `apps/desktop/src/themes/`. Built-ins in `presets.ts` (`BUILTIN_THEMES`): `github`, `nous`, `catppuccin`, `everforest`, `solarized`, `nous-alt`, `midnight`, `ember`, `mono`, `cyberpunk`, `slate`. `context.tsx` owns `useTheme` / `setTheme` / `setMode` and reads the **merged** registry (built-ins + user themes) for `availableThemes` and every skin lookup, so an installed theme appears everywhere a built-in does with no per-surface wiring. `user-themes.ts` persists to `localStorage` under `USER_THEMES_KEY = 'hermes-desktop-user-themes-v1'` so the boot-time paint (which runs before React mounts) resolves a user theme synchronously; validity requires `name`, `label` and at least `background`, `foreground`, `primary` in `colors` (`REQUIRED_COLOR_KEYS`); marketplace imports stamp their description `VS Code · <publisher.extension>` (`MARKETPLACE_DESC_PREFIX`) so install surfaces can tell what is already installed. `install.ts` exports `MARKETPLACE_ID_RE = /^[\w-]+\.[\w-]+$/`, `installVscodeThemeFromText(text, opts)` and `buildThemeFromMarketplace(result)` — which folds every color theme an extension contributes into **one** desktop theme family, mapping the first light variant onto `colors` and the first dark variant onto `darkColors` (a single-variant extension fills both slots, so the toggle is a deliberate no-op), throwing `"<id>" does not contribute any color themes.` when empty. `vscode.ts` is the converter: ~6 workbench keys carry the whole look and the rest are derived by mixing toward background/foreground, with `ACCENT_MIN_CONTRAST = 4.5` nudging an imported accent until small uppercase sidebar labels clear WCAG AA. `retint.ts` (`retintTheme`, `themeHue`), `color.ts` (OKLCH maths), `skin.ts`, `use-skin-command.ts`, `accent-override.ts`, `request.ts` (`requestTheme` returns `false` when the name does not resolve, doubling as an "is this installed?" check), `backend-sync.ts` (`$backendThemes` — themes the backend contributes), `profile-theme.test.ts` (per-profile theme).
- **Inputs / options:** `useTheme()`, `requestTheme(name)`, `setAccentOverride(hex | null)`, `retintTheme(theme, hex)`, `THEMES_AREA` registrations.
- **Outputs / side effects:** CSS custom properties; `localStorage`.
- **Config / env:** n/a
- **Edge cases / guards:** `renderedModeFor` picks the `.dark` class from the real background luminance, so surface-bound UI matches what is actually on screen even for a single-mode imported theme.
- **Rebuild notes:** Derive tokens from a seed chain; a theme format with hundreds of required keys will never be authored by users.

---

## 15. The preload capability bridge, engineering contracts, and the test surface

### `window.hermesDesktop` — the preload capability bridge  `id: desktop-main.preload-bridge`
- **Surface:** Core / API
- **Where:** `window.hermesDesktop.*` in every renderer (primary, session, peer, browser, HUD, Quick Entry, pet overlay).
- **What it does:** The one narrow, typed door between the renderer and the machine. The renderer never touches Node or Electron directly; native power arrives as a deliberate capability, not a general escape hatch.
- **How it works:** `apps/desktop/electron/preload.ts` (531 lines), loaded from `PRELOAD_PATH = <APP_ROOT>/dist/electron-preload.js` (esbuild output — the preload must be plain JS because Electron's sandbox cannot run `.ts` and tsx's ESM loader is broken on Electron 40's Node). It calls `contextBridge.exposeInMainWorld('hermesDesktop', { … })` with the full API and imports only `contextBridge`, `ipcRenderer`, `webFrame`, `webUtils`. Two values are read **synchronously before first paint**: `ipcRenderer.sendSync('hermes:translucency:support')` → `{ glass, translucency }` and `ipcRenderer.sendSync('hermes:hud:windowing')` → the HUD windowing view. Every `on*` subscription helper returns an **unsubscribe function** that calls `ipcRenderer.removeListener`. The complete surface (grouped as it appears): `glassSupported`, `translucencySupported`; `getConnection`, `getConnectionFor`, `getProfileRoutes`, `revalidateConnection`, `touchBackend`, `getGatewayWsUrl`, `getGatewayWsUrlFor`, `getAgentRoster`; `openSessionWindow`, `openSessionInTerminal`, `openWindow`, `openBrowserWindow`, `onBrowserPopoutClosed`; `claimAmbientCue`; `wakeIndicator.{getState,setState,onState}`; `petOverlay.{open,close,setBounds,setIgnoreMouse,setFocusable,pushState,control,onState,onControl}`; `hud.{nativeDrag,windowing,open,close,setIgnoreMouse,beginMove,endMove,moveBy,setWorkspaceTransfer,setBounds,resetLayout,setFrost,setSession,onGoto,onChanged,onCursor,onGameOverlay}`; `quickEntry.{getSettings,setSettings,submit,dismiss,pushState,onState,onSubmit,onShown}`; `getBootProgress`; `getConnectionConfig`, `saveConnectionConfig`, `applyConnectionConfig`, `testConnectionConfig`; `getSecretStorageEncryption`, `setSecretStorageEncryption`; `connections.{list,save,remove,setPrimary,setLaunchMode,setLastUsed,test,updateManaged,updateAll,onChanged}`; `sshConfigHosts`, `sshResolveHost`; `probeConnectionConfig`, `oauthLoginConnectionConfig`, `oauthLogoutConnectionConfig`; `cloud.{status,login,logout,discover,agentSignIn}`; `profile.{get,remember,set}`; `api`; `notify`; `requestMicrophoneAccess`; `readWindowBelow`; `readFileDataUrl`, `readFileDataUrlForAttach`, `dataUrlReadMax.{get,set}`, `readFileText`, `readPluginSource`, `selectPaths`, `selectSavePath`, `writeClipboard`, `readClipboard`, `saveGatewayFile`, `saveImageFromUrl`; `contextMenuEdit`, `contextMenuCopyImage`, `contextMenuSpellcheck`, `contextMenuGuestAddWord`, `onContextMenuSpellcheck`; `saveImageBuffer`, `saveClipboardImage`, `getPathForFile`; `normalizePreviewTarget`, `watchPreviewFile`, `watchDirectory`, `stopPreviewFileWatch`; `setActiveWork`, `setTitleBarTheme`, `setNativeTheme`, `setTranslucency`, `setKeepAwake`, `setDisableF12`, `setPreviewShortcutActive`; `openExternal`; `mcpOauth.{listen,wait,cancel}`; `openPreviewInBrowser`, `reachPreviewUrl`; `setActiveConnectionRoute`; `fetchLinkTitle`, `resolveFavicon`, `sanitizeWorkspaceCwd`; `settings.{getDefaultProjectDir,setDefaultProjectDir,pickDefaultProjectDir}`; `zoom.{get,factor,setPercent,onChanged}`; `revealLogs`, `getRecentLogs`, `reportRendererError`; `readDir`, `gitRoot`, `revealPath`, `openDir`, `desktopPluginsRoot`, `logsRoot`, `agentPluginsRoot`, `renamePath`, `writeTextFile`, `trashPath`; `git.{worktreeList,worktreeAdd,worktreeRemove,branchSwitch,branchList,baseBranchList,repoStatus,fileDiff,scanRepos,review.{list,diff,stage,unstage,revert,revParse,commit,commitContext,push,shipInfo,prList,fetchPrComment,createPr}}`; `terminal.{cwd,dispose,resize,start,write,onData,onExit}`; `onClosePreviewRequested`, `onPreviewNav`, `onOpenFolderRequested`, `onOpenUpdatesRequested`, `onDeepLink`, `signalDeepLinkReady`; `probePluginRepo`, `installDesktopPlugin`; `onWindowStateChanged`, `onFocusSession`, `onNotificationAction`, `onNotificationActivate`, `onPreviewFileChanged`, `onBackendExit`, `onConnectionApplied`, `onPowerResume`, `getOnBattery`, `onBatteryChanged`, `onBootProgress`; `getBootstrapState`, `continueBootstrapLocal`, `resetBootstrap`, `repairBootstrap`, `cancelBootstrap`, `onBootstrapEvent`; `getVersion`, `getRemoteDisplayReason`; `uninstall.{summary,run}`; `updates.{check,apply,getBranch,setBranch,onProgress}`; `themes.{fetchMarketplace,searchMarketplace}`; `findInPage`, `stopFindInPage`, `onFoundInPage`, `onOpenFindBarRequested`.
- **Inputs / options:** as listed.
- **Outputs / side effects:** IPC.
- **Config / env:** n/a
- **Edge cases / guards:** A throw during preload evaluation (for example importing `node:os` in a sandboxed preload) takes the **entire** bridge down and the renderer reports "Desktop IPC bridge is unavailable" — which is exactly why translucency support is asked of main rather than computed locally. `getPathForFile` is the one function implemented in the preload itself, wrapped in try/catch returning `''`. The renderer's TypeScript view of this object lives in `apps/desktop/src/global.d.ts` (59 KB).
- **Rebuild notes:** Keep the preload dependency-free and total: one throw there loses every capability at once.

### Desktop engineering invariants (`AGENTS.md`)  `id: desktop-main.agents-md`
- **Surface:** Docs
- **Where:** `apps/desktop/AGENTS.md` (11 KB), read alongside the repository root `AGENTS.md` and `apps/desktop/DESIGN.md`.
- **What it does:** States the architecture invariants a change must fit — a judgment guide, not an inventory.
- **How it works:** Three authorities, each authoritative for one thing: **Electron** owns the machine (process lifecycle, native filesystem/git/windows, install/update, and a narrow typed capability bridge); **the renderer** owns the experience (navigation, presentation, ephemeral interaction state); **the agent backend** owns the work (sessions, tools, model calls, streaming). Rules: the renderer never reaches for Node or Electron directly; agent behaviour lives behind the gateway and is never reimplemented in React; state is placed by *who is allowed to be right about it* (backend = anything another Hermes surface can change, treated as a cache; Electron = machine and runtime facts; renderer = only this window's presentation); persisted state must **declare its scope in its own key** (global / connection / profile / stored session / project / window) — getting the scope wrong is how one profile's setting bleeds into another; session identities must not be conflated (durable identity for navigation and anything pinned or persisted, runtime identity for live streaming, lineage root for state that must outlive compression), translated at the boundary; "when a rule and the code disagree, trust the code and fix whichever is wrong — but never break an invariant to make a change easier."
- **Inputs / options:** n/a
- **Outputs / side effects:** none.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** Write the seams down; "who is allowed to be right about this" is the question that keeps a three-process app coherent.

### Desktop design contract (`DESIGN.md`)  `id: desktop-main.design-md`
- **Surface:** Docs
- **Where:** `apps/desktop/DESIGN.md` (18.9 KB).
- **What it does:** Owns the visual and interaction contract: "one source per concern, tokens over literals, flat over boxed."
- **How it works:** Two kinds of content maintained differently — durable **principles** (flatness, intent, feedback, motion, cancellation) and **named contracts** (tokens, `Button` variants, primitive names) that must be updated *in the same change* as the code, because a stale name there is a bug exactly like a stale type. Principles include: flat, not boxed (no card-in-card, no divider borders inside a panel; group with whitespace and a single hairline); borderless elevation for floating panels (`shadow-nous` + a `--stroke-nous` hairline); one primitive per concern (one `Button`, one control-variant set, one `SearchField`, one `Loader`, one `ErrorState`); tokens not literals (`--ui-*`, `--shadow-nous`, `--theme-*`, never raw hex or ad-hoc rgba); style lives in the primitive (call sites pass `variant`/`size`, not `className` overrides); intent before automation.
- **Inputs / options:** n/a
- **Outputs / side effects:** none.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** Separate durable principles from the versioned component API in the same document, and say which half must move with the code.

### Test surface — vitest projects, node:test, Playwright e2e  `id: desktop-main.test-surface`
- **Surface:** Docs / Desktop app
- **Where:** `npm run test:ui`, `npm run test:desktop:platforms`, `npm run test:e2e`, `npm run check`.
- **What it does:** Three isolated runners cover the renderer, the Electron main modules, and the packaged app end-to-end.
- **How it works:** `vitest.config.ts` defines two projects: **`ui`** (jsdom, `setupFiles: ['./vitest.setup.ts']`, `include: ['src/**/*.test.{ts,tsx}']`, `testTimeout: 15_000` because the first test in a file pays jsdom init + full transform) and **`electron`** (node, `include: ['electron/**/*.test.ts', 'scripts/**.test.{ts,mjs}', 'e2e/**/*.unit.test.ts']`, excluding `scripts/run-short-session-hang-repro.test.mjs`). `playwright.config.ts` runs `testDir: './e2e'` with `testIgnore: '**/*.unit.test.ts'` (so the e2e *helpers* run in exactly one runner), `timeout: 90_000`, `retries: CI ? 1 : 0`, `fullyParallel: false` (each test gets its own worker so the Electron process is fully isolated), `screenshot: 'on'`, full tracing, and emulated `prefers-reduced-motion: reduce` so overlays are never captured mid-fade. Visual baselines are generated on `main` with `--update-snapshots` and cached; on PRs diffs are surfaced in the CI summary rather than failing the run (`expectVisualSnapshot` in `e2e/visual-snapshot.ts`). E2E specs: `at-rest-connection-token`, `batch-clarify`, `boot-failure`, `boot`, `bot-mode-closed-chat-stays-closed`, `chat`, `context-menu-editables`, `correction-session-switch`, `fleet-profile-rail`, `glyph-spinner`, `group-to-local-bot-handoff`, `hidden-history-messages`, `image-attachment-resume`, `interim-messages`, `large-session-resume`, `launch-packaged-app`, `mock-backend-setup`, `onboarding`, `queue-turn-boundary`, `right-pane`, `session-compression-and-queue-stop`, `sidebar-states`, `submit-drift`, `task-panel-clearance`, `tile-unread-bug`, `unread-dot-restart`, `warm-resume-jitter`, `worktree-branch-status`, `zoom-preservation`; helpers `electron-binary.ts`, `fix-electron-tracing.ts`, `fixtures.ts`, `mock-server.ts`, `real-session-builder.ts`, `test.ts`, `visual-snapshot.ts`.
- **Inputs / options:** the npm scripts.
- **Outputs / side effects:** `playwright-report/`, traces, screenshots.
- **Config / env:** env `CI`, `TEST_WORKER_INDEX` (forces an immediate window reveal in main).
- **Edge cases / guards:** `HERMES_DESKTOP_SKIP_QUIT_CONFIRM=1` is what lets Playwright's `app.close()` quit without hanging on the active-work modal.
- **Rebuild notes:** Give the Electron-side pure modules their own node-environment runner; they are the parts that break silently in production.

### Build and diagnostic scripts  `id: desktop-main.build-scripts`
- **Surface:** Docs / Desktop app
- **Where:** `apps/desktop/scripts/`.
- **What it does:** The build, packaging, signing and live-diagnostic tooling around the app.
- **How it works:** Complete list: `after-pack.mjs`, `assert-dist-built.mjs`, `assert-root-install.mjs`, `before-build.mjs`, `before-pack.mjs`, `bundle-electron-main.mjs` (esbuild bundle of the main process — no tsconfig path resolution, which is why `electron/translucency.ts` imports `../../shared/src/translucency` relatively), `click-session.mjs`, `dev-mock.mjs`, `dev-no-hmr.mjs`, the CDP diagnostics family `diag-code-live`, `diag-drag-churn`, `diag-drag-trace`, `diag-jump`, `diag-key-latency`, `diag-live-state`, `diag-overlay-ab`, `diag-overlay-churn`, `diag-overlay-full`, `diag-overlay-sweep`, `diag-real-loop`, `diag-ro-storm`, `diag-scroll-reset`, `diag-sidebar-dom`, `diag-switch-autopsy`, `diag-switch-trace`, `eval.mjs`, `gen-share-codes.ts`, `live-drive.mjs`, `local-pack-publish.test.mjs`, `notarize-artifact.mjs`, `notarize.mjs`, `patch-electron-builder-mac-binary.mjs`, `perf/` (`run.mjs`, `serve.mjs`, `lib/cdp.mjs`), `probe-command-palette.mjs`, `probe-model-picker.mjs`, `probe-renderer.mjs`, `probe-thread.mjs`, `profile-model-picker.mjs`, `profile-typing-lag.md`, `rebuild-native.mjs`, `reload-renderer.mjs`, `reload.mjs`, `run-electron-builder.mjs`, `run-short-session-hang-repro.mjs`, `set-exe-identity.mjs`, `stage-native-deps.mjs` (chmods the staged node-pty `spawn-helper`), `test-desktop.mjs`, `utils.mjs`, `write-build-stamp.mjs` (emits `install-stamp.json`).
- **Inputs / options:** per script; the diagnostics attach over the dev CDP port.
- **Outputs / side effects:** Build artifacts, signed/notarized packages, diagnostic reports.
- **Config / env:** `CSC_LINK`, `CSC_KEY_PASSWORD`, `APPLE_*` (macOS), `WIN_CSC_*` (Windows), `CSC_IDENTITY_AUTO_DISCOVERY`, `ELECTRON_MIRROR`, `HERMES_DESKTOP_CDP_PORT`.
- **Edge cases / guards:** macOS/Windows signing and notarization run automatically only when the relevant credentials are present.
- **Rebuild notes:** A CDP-attachable dev build turns "reproduce the UI bug" into a script.

### Install identity (`install_id`)  `id: desktop-main.install-identity`
- **Surface:** Core
- **Where:** `<HERMES_HOME>/install_id` (a 32-hex string). Reported by the backend and used by the desktop to collapse two registrations of one backend into a single roster group.
- **What it does:** Gives one physical Hermes install a stable opaque identity shared by every profile in it.
- **How it works:** `hermes_cli/install_identity.py` (153 lines). `read_or_create_install_id(root)` reads `<root>/install_id`, validating `^[0-9a-f]{32}$`; otherwise it mints `uuid.uuid4().hex` under a cross-process file lock (`.install_id.lock`, opened 0600; `fcntl.flock` on POSIX, `msvcrt.locking` on Windows — with an in-process `threading.Lock` first, because Windows byte-range locks report a same-process conflict instead of waiting), writes it via `tempfile.mkstemp` + `fsync` + `os.replace` + a best-effort directory `fsync`, then re-reads and validates the committed value. `get_install_id()` caches per active Hermes root under `_INSTALL_ID_LOCK`. Returning `None` (rather than an ephemeral id) is deliberate: an ephemeral id would violate the authority and connection-registry contract. Consumers: `hermes_cli/web_server.py:51` (advertised on status) and `gateway/hosted_rooms.py:280`.
- **Inputs / options:** optional `root`.
- **Outputs / side effects:** `<HERMES_HOME>/install_id`.
- **Config / env:** n/a
- **Edge cases / guards:** The desktop's own `desktop-installation.json` id (`electron/desktop-installation.ts`) is a **separate**, desktop-local UUID used to derive SSH ownership ids; do not conflate the two.
- **Rebuild notes:** Mint identity atomically under a cross-process lock and fail closed — a duplicated or ephemeral install id silently corrupts every registry that keys on it.

---

## 16. Appendix — complete IPC channel index

### Every `hermes:*` IPC channel  `id: desktop-main.ipc-channel-index`
- **Surface:** Core / API
- **Where:** Invisible; the exhaustive wire between `window.hermesDesktop` (preload) and the Electron main process. Terminal data/exit additionally use the per-session dynamic channels `hermes:terminal:<id>:data` and `hermes:terminal:<id>:exit`.
- **What it does:** Lists every channel name in the desktop IPC surface, with how it is registered and where.
- **How it works:** Registration sites are `ipcMain.handle` (request/response), `ipcMain.on` (fire-and-forget from the renderer), `webContents.send` (main→renderer push), and `ipcRenderer.sendSync` (the two pre-paint reads). Complete list:
  - `hermes:active-work` — `ipcMain.on` in `main.ts:16435`; main→renderer push; preload send
  - `hermes:agents:roster` — `ipcMain.handle` in `main.ts:15088`; preload invoke
  - `hermes:ambient:claim` — `ipcMain.handle` in `main.ts:16062`; preload invoke
  - `hermes:api` — `ipcMain.handle` in `main.ts:16025`; preload invoke
  - `hermes:backend-exit` — main→renderer push; preload on
  - `hermes:backend:touch` — `ipcMain.handle` in `main.ts:14343`; preload invoke
  - `hermes:boot-progress` — main→renderer push; preload on
  - `hermes:boot-progress:get` — `ipcMain.handle` in `main.ts:14572`; preload invoke
  - `hermes:bootstrap:cancel` — `ipcMain.handle` in `main.ts:14556`; preload invoke
  - `hermes:bootstrap:continue-local` — `ipcMain.handle` in `main.ts:14550`; preload invoke
  - `hermes:bootstrap:event` — main→renderer push; preload on
  - `hermes:bootstrap:get` — `ipcMain.handle` in `main.ts:14573`; preload invoke
  - `hermes:bootstrap:repair` — `ipcMain.handle` in `main.ts:14498`; preload invoke
  - `hermes:bootstrap:reset` — `ipcMain.handle` in `main.ts:14484`; preload invoke
  - `hermes:browser-popout:closed` — main→renderer push; preload on
  - `hermes:close-preview-requested` — main→renderer push; preload on
  - `hermes:cloud:agent-sign-in` — `ipcMain.handle` in `main.ts:15414`; preload invoke
  - `hermes:cloud:discover` — `ipcMain.handle` in `main.ts:15409`; preload invoke
  - `hermes:cloud:login` — `ipcMain.handle` in `main.ts:15399`; preload invoke
  - `hermes:cloud:logout` — `ipcMain.handle` in `main.ts:15404`; preload invoke
  - `hermes:cloud:status` — `ipcMain.handle` in `main.ts:15395`; preload invoke
  - `hermes:connection` — `ipcMain.handle` in `main.ts:14183`; preload invoke
  - `hermes:connection-config:apply` — `ipcMain.handle` in `main.ts:15427`; preload invoke
  - `hermes:connection-config:get` — `ipcMain.handle` in `main.ts:14574`; preload invoke
  - `hermes:connection-config:oauth-login` — `ipcMain.handle` in `main.ts:15313`; preload invoke
  - `hermes:connection-config:oauth-logout` — `ipcMain.handle` in `main.ts:15376`; preload invoke
  - `hermes:connection-config:probe` — `ipcMain.handle` in `main.ts:15312`; preload invoke
  - `hermes:connection-config:save` — `ipcMain.handle` in `main.ts:15420`; preload invoke
  - `hermes:connection-config:test` — `ipcMain.handle` in `main.ts:14689`; preload invoke
  - `hermes:connection:active-route` — `ipcMain.on` in `main.ts:14214`; main→renderer push; preload send
  - `hermes:connection:applied` — main→renderer push; preload on
  - `hermes:connection:for` — `ipcMain.handle` in `main.ts:14199`; preload invoke
  - `hermes:connection:revalidate` — `ipcMain.handle` in `main.ts:14244`; preload invoke
  - `hermes:connections:changed` — main→renderer push; preload on
  - `hermes:connections:list` — `ipcMain.handle` in `main.ts:14701`; preload invoke
  - `hermes:connections:remove` — `ipcMain.handle` in `main.ts:14707`; preload invoke
  - `hermes:connections:save` — `ipcMain.handle` in `main.ts:14702`; preload invoke
  - `hermes:connections:set-last-used` — `ipcMain.handle` in `main.ts:14736`; preload invoke
  - `hermes:connections:set-launch-mode` — `ipcMain.handle` in `main.ts:14729`; preload invoke
  - `hermes:connections:set-primary` — `ipcMain.handle` in `main.ts:14722`; preload invoke
  - `hermes:connections:test` — `ipcMain.handle` in `main.ts:14742`; preload invoke
  - `hermes:connections:update-all` — `ipcMain.handle` in `main.ts:15179`; preload invoke
  - `hermes:connections:update-managed` — `ipcMain.handle` in `main.ts:15172`; preload invoke
  - `hermes:context-menu-spellcheck` — main→renderer push; preload on
  - `hermes:context-menu:copy-image` — `ipcMain.handle` in `main.ts:16345`; preload invoke
  - `hermes:context-menu:edit` — `ipcMain.handle` in `main.ts:16329`; preload invoke
  - `hermes:context-menu:guest-add-word` — `ipcMain.handle` in `main.ts:16370`; preload invoke
  - `hermes:context-menu:spellcheck` — `ipcMain.handle` in `main.ts:16353`; preload invoke
  - `hermes:data-url-read-max:get` — `ipcMain.handle` in `main.ts:16172`; preload invoke
  - `hermes:data-url-read-max:set` — `ipcMain.handle` in `main.ts:16179`; preload invoke
  - `hermes:deep-link` — main→renderer push; preload on
  - `hermes:deep-link-ready` — `ipcMain.handle` in `main.ts:17259`; preload invoke
  - `hermes:devtools:disable-f12` — `ipcMain.on` in `main.ts:16677`; main→renderer push; preload send
  - `hermes:fetchLinkTitle` — `ipcMain.handle` in `main.ts:16800`; preload invoke
  - `hermes:find-in-page` — `ipcMain.handle` in `main.ts:16723`; preload invoke
  - `hermes:focus-session` — main→renderer push; preload on
  - `hermes:found-in-page` — main→renderer push; preload on
  - `hermes:fs:agentPluginsRoot` — `ipcMain.handle` in `fs-ipc.ts:112`; preload invoke
  - `hermes:fs:desktopPluginsRoot` — `ipcMain.handle` in `fs-ipc.ts:99`; preload invoke
  - `hermes:fs:gitRoot` — `ipcMain.handle` in `fs-ipc.ts:33`; preload invoke
  - `hermes:fs:logsRoot` — `ipcMain.handle` in `fs-ipc.ts:105`; preload invoke
  - `hermes:fs:openDir` — `ipcMain.handle` in `fs-ipc.ts:57`; preload invoke
  - `hermes:fs:readDir` — `ipcMain.handle` in `fs-ipc.ts:31`; preload invoke
  - `hermes:fs:rename` — `ipcMain.handle` in `fs-ipc.ts:139`; preload invoke
  - `hermes:fs:reveal` — `ipcMain.handle` in `fs-ipc.ts:36`; preload invoke
  - `hermes:fs:trash` — `ipcMain.handle` in `fs-ipc.ts:192`; preload invoke
  - `hermes:fs:writeText` — `ipcMain.handle` in `fs-ipc.ts:166`; preload invoke
  - `hermes:gateway:ws-url` — `ipcMain.handle` in `main.ts:14348`; preload invoke
  - `hermes:gateway:ws-url-for` — `ipcMain.handle` in `main.ts:15120`; preload invoke
  - `hermes:get-remote-display-reason` — `ipcMain.handle` in `main.ts:646`; preload invoke
  - `hermes:git:baseBranchList` — `ipcMain.handle` in `git-ipc.ts:59`; preload invoke
  - `hermes:git:branchList` — `ipcMain.handle` in `git-ipc.ts:57`; preload invoke
  - `hermes:git:branchSwitch` — `ipcMain.handle` in `git-ipc.ts:53`; preload invoke
  - `hermes:git:fileDiff` — `ipcMain.handle` in `git-ipc.ts:78`; preload invoke
  - `hermes:git:repoStatus` — `ipcMain.handle` in `git-ipc.ts:66`; preload invoke
  - `hermes:git:review:commit` — `ipcMain.handle` in `git-ipc.ts:93`; preload invoke
  - `hermes:git:review:commitContext` — `ipcMain.handle` in `git-ipc.ts:96`; preload invoke
  - `hermes:git:review:createPr` — `ipcMain.handle` in `git-ipc.ts:107`; preload invoke
  - `hermes:git:review:diff` — `ipcMain.handle` in `git-ipc.ts:74`; preload invoke
  - `hermes:git:review:fetchPrComment` — `ipcMain.handle` in `git-ipc.ts:104`; preload invoke
  - `hermes:git:review:list` — `ipcMain.handle` in `git-ipc.ts:71`; preload invoke
  - `hermes:git:review:prList` — `ipcMain.handle` in `git-ipc.ts:101`; preload invoke
  - `hermes:git:review:push` — `ipcMain.handle` in `git-ipc.ts:99`; preload invoke
  - `hermes:git:review:revParse` — `ipcMain.handle` in `git-ipc.ts:90`; preload invoke
  - `hermes:git:review:revert` — `ipcMain.handle` in `git-ipc.ts:87`; preload invoke
  - `hermes:git:review:shipInfo` — `ipcMain.handle` in `git-ipc.ts:100`; preload invoke
  - `hermes:git:review:stage` — `ipcMain.handle` in `git-ipc.ts:81`; preload invoke
  - `hermes:git:review:unstage` — `ipcMain.handle` in `git-ipc.ts:84`; preload invoke
  - `hermes:git:scanRepos` — `ipcMain.handle` in `git-ipc.ts:113`; preload invoke
  - `hermes:git:worktreeAdd` — `ipcMain.handle` in `git-ipc.ts:45`; preload invoke
  - `hermes:git:worktreeList` — `ipcMain.handle` in `git-ipc.ts:43`; preload invoke
  - `hermes:git:worktreeRemove` — `ipcMain.handle` in `git-ipc.ts:49`; preload invoke
  - `hermes:hud:begin-move` — `ipcMain.on` in `hud-ipc.ts:176`; main→renderer push; preload send
  - `hermes:hud:changed` — main→renderer push; preload on
  - `hermes:hud:close` — `ipcMain.handle` in `hud-ipc.ts:294`; preload invoke
  - `hermes:hud:cursor` — main→renderer push; preload on
  - `hermes:hud:end-move` — `ipcMain.on` in `hud-ipc.ts:192`; main→renderer push; preload send
  - `hermes:hud:frost` — `ipcMain.handle` in `hud-ipc.ts:146`; preload invoke
  - `hermes:hud:game-overlay` — main→renderer push; preload on
  - `hermes:hud:goto` — main→renderer push; preload on
  - `hermes:hud:ignore-mouse` — `ipcMain.on` in `hud-ipc.ts:158`; main→renderer push; preload send
  - `hermes:hud:move-by` — `ipcMain.on` in `hud-ipc.ts:202`; main→renderer push; preload send
  - `hermes:hud:native-drag` — `ipcMain.on` in `hud-ipc.ts:41`
  - `hermes:hud:open` — `ipcMain.handle` in `hud-ipc.ts:137`; preload invoke
  - `hermes:hud:reset-layout` — `ipcMain.handle` in `hud-ipc.ts:274`; preload invoke
  - `hermes:hud:session` — `ipcMain.on` in `hud-ipc.ts:286`; main→renderer push; preload send
  - `hermes:hud:set-bounds` — `ipcMain.on` in `hud-ipc.ts:240`; main→renderer push; preload send
  - `hermes:hud:windowing` — `ipcMain.on` in `hud-ipc.ts:45`; preload sendSync
  - `hermes:hud:workspace-transfer` — `ipcMain.on` in `hud-ipc.ts:55`; main→renderer push; preload send
  - `hermes:keep-awake` — `ipcMain.on` in `main.ts:16580`; main→renderer push; preload send
  - `hermes:logs:recent` — `ipcMain.handle` in `main.ts:16820`; preload invoke
  - `hermes:logs:renderer-error` — `ipcMain.on` in `main.ts:16827`; main→renderer push; preload send
  - `hermes:logs:reveal` — `ipcMain.handle` in `main.ts:16804`; preload invoke
  - `hermes:mcp-oauth:cancel` — `ipcMain.handle` in `mcp-oauth-callback-ipc.ts:176`; preload invoke
  - `hermes:mcp-oauth:listen` — `ipcMain.handle` in `mcp-oauth-callback-ipc.ts:94`; preload invoke
  - `hermes:mcp-oauth:wait` — `ipcMain.handle` in `mcp-oauth-callback-ipc.ts:142`; preload invoke
  - `hermes:native-theme` — `ipcMain.on` in `main.ts:16468`; main→renderer push; preload send
  - `hermes:normalizePreviewTarget` — `ipcMain.handle` in `main.ts:16412`; preload invoke
  - `hermes:notification-action` — main→renderer push; preload on
  - `hermes:notification-activate` — main→renderer push; preload on
  - `hermes:notify` — `ipcMain.handle` in `main.ts:16064`; preload invoke
  - `hermes:open-find-bar` — main→renderer push; preload on
  - `hermes:open-folder-requested` — main→renderer push; preload on
  - `hermes:open-updates` — main→renderer push; preload on
  - `hermes:openExternal` — `ipcMain.handle` in `main.ts:16688`; preload invoke
  - `hermes:openPreviewInBrowser` — `ipcMain.handle` in `main.ts:16752`; preload invoke
  - `hermes:pet-overlay:close` — `ipcMain.handle` in `pet-overlay-ipc.ts:47`; preload invoke
  - `hermes:pet-overlay:control` — `ipcMain.on` in `pet-overlay-ipc.ts:117`; main→renderer push; preload on/send
  - `hermes:pet-overlay:ignore-mouse` — `ipcMain.on` in `pet-overlay-ipc.ts:84`; main→renderer push; preload send
  - `hermes:pet-overlay:open` — `ipcMain.handle` in `pet-overlay-ipc.ts:23`; preload invoke
  - `hermes:pet-overlay:set-bounds` — `ipcMain.on` in `pet-overlay-ipc.ts:58`; main→renderer push; preload send
  - `hermes:pet-overlay:set-focusable` — `ipcMain.on` in `pet-overlay-ipc.ts:95`; main→renderer push; preload send
  - `hermes:pet-overlay:state` — `ipcMain.on` in `pet-overlay-ipc.ts:109`; main→renderer push; preload on/send
  - `hermes:plugin-profile-routes` — `ipcMain.handle` in `main.ts:14577`; preload invoke
  - `hermes:plugin:installDesktop` — `ipcMain.handle` in `fs-ipc.ts:124`; preload invoke
  - `hermes:plugin:probe` — `ipcMain.handle` in `fs-ipc.ts:114`; preload invoke
  - `hermes:power-battery` — main→renderer push; preload on
  - `hermes:power-battery:get` — `ipcMain.handle` in `main.ts:6394`; preload invoke
  - `hermes:power-resume` — main→renderer push; preload on
  - `hermes:preview-file-changed` — main→renderer push; preload on
  - `hermes:preview-nav` — main→renderer push; preload on
  - `hermes:preview:reach` — `ipcMain.handle` in `main.ts:16750`; preload invoke
  - `hermes:previewShortcutActive` — `ipcMain.on` in `main.ts:15496`; main→renderer push; preload send
  - `hermes:profile:get` — `ipcMain.handle` in `main.ts:15475`; preload invoke
  - `hermes:profile:remember` — `ipcMain.handle` in `main.ts:15480`; preload invoke
  - `hermes:profile:set` — `ipcMain.handle` in `main.ts:15483`; preload invoke
  - `hermes:quick-entry:dismiss` — `ipcMain.on` in `main.ts:16662`; main→renderer push; preload send
  - `hermes:quick-entry:settings:get` — `ipcMain.handle` in `main.ts:16597`; preload invoke
  - `hermes:quick-entry:settings:set` — `ipcMain.handle` in `main.ts:16611`; preload invoke
  - `hermes:quick-entry:shown` — main→renderer push; preload on
  - `hermes:quick-entry:state` — `ipcMain.on` in `main.ts:16654`; main→renderer push; preload on/send
  - `hermes:quick-entry:submit` — `ipcMain.on` in `main.ts:16628`; main→renderer push; preload on/send
  - `hermes:readClipboard` — `ipcMain.handle` in `main.ts:16321`; preload invoke
  - `hermes:readFileDataUrl` — `ipcMain.handle` in `main.ts:16189`; preload invoke
  - `hermes:readFileDataUrlForAttach` — `ipcMain.handle` in `main.ts:16201`; preload invoke
  - `hermes:readFileText` — `ipcMain.handle` in `main.ts:16209`; preload invoke
  - `hermes:readPluginSource` — `ipcMain.handle` in `main.ts:16244`; preload invoke
  - `hermes:requestMicrophoneAccess` — `ipcMain.handle` in `main.ts:15500`; preload invoke
  - `hermes:resolveFavicon` — `ipcMain.handle` in `main.ts:16802`; preload invoke
  - `hermes:saveClipboardImage` — `ipcMain.handle` in `main.ts:16391`; preload invoke
  - `hermes:saveGatewayFile` — `ipcMain.handle` in `main.ts:16323`; preload invoke
  - `hermes:saveImageBuffer` — `ipcMain.handle` in `main.ts:16379`; preload invoke
  - `hermes:saveImageFromUrl` — `ipcMain.handle` in `main.ts:16325`; preload invoke
  - `hermes:secret-storage:get` — `ipcMain.handle` in `main.ts:14694`; preload invoke
  - `hermes:secret-storage:set` — `ipcMain.handle` in `main.ts:14695`; preload invoke
  - `hermes:selectPaths` — `ipcMain.handle` in `main.ts:16258`; preload invoke
  - `hermes:selectSavePath` — `ipcMain.handle` in `main.ts:16303`; preload invoke
  - `hermes:setting:defaultProjectDir:get` — `ipcMain.handle` in `main.ts:16762`; preload invoke
  - `hermes:setting:defaultProjectDir:pick` — `ipcMain.handle` in `main.ts:16786`; preload invoke
  - `hermes:setting:defaultProjectDir:set` — `ipcMain.handle` in `main.ts:16770`; preload invoke
  - `hermes:ssh-config:hosts` — `ipcMain.handle` in `main.ts:14645`; preload invoke
  - `hermes:ssh-config:resolve` — `ipcMain.handle` in `main.ts:14646`; preload invoke
  - `hermes:stop-find-in-page` — `ipcMain.handle` in `main.ts:16738`; preload invoke
  - `hermes:stopPreviewFileWatch` — `ipcMain.handle` in `main.ts:16420`; preload invoke
  - `hermes:terminal:cwd` — `ipcMain.handle` in `terminal-ipc.ts:365`; preload invoke
  - `hermes:terminal:dispose` — `ipcMain.handle` in `terminal-ipc.ts:375`; preload invoke
  - `hermes:terminal:resize` — `ipcMain.handle` in `terminal-ipc.ts:351`; preload invoke
  - `hermes:terminal:start` — `ipcMain.handle` in `terminal-ipc.ts:286`; preload invoke
  - `hermes:terminal:write` — `ipcMain.handle` in `terminal-ipc.ts:339`; preload invoke
  - `hermes:titlebar-theme` — `ipcMain.on` in `main.ts:16449`; main→renderer push; preload send
  - `hermes:translucency` — `ipcMain.on` in `main.ts:16525`; main→renderer push; preload send
  - `hermes:translucency:support` — `ipcMain.on` in `main.ts:16521`; preload sendSync
  - `hermes:uninstall:run` — `ipcMain.handle` in `main.ts:17167`; preload invoke
  - `hermes:uninstall:summary` — `ipcMain.handle` in `main.ts:17166`; preload invoke
  - `hermes:updates:apply` — `ipcMain.handle` in `main.ts:16872`; preload invoke
  - `hermes:updates:branch:get` — `ipcMain.handle` in `main.ts:16880`; preload invoke
  - `hermes:updates:branch:set` — `ipcMain.handle` in `main.ts:16882`; preload invoke
  - `hermes:updates:check` — `ipcMain.handle` in `main.ts:16862`; preload invoke
  - `hermes:updates:progress` — main→renderer push; preload on
  - `hermes:version` — `ipcMain.handle` in `main.ts:16944`; preload invoke
  - `hermes:vscode-theme:fetch` — `ipcMain.handle` in `main.ts:17175`; preload invoke
  - `hermes:vscode-theme:search` — `ipcMain.handle` in `main.ts:17178`; preload invoke
  - `hermes:wake-indicator:get` — `ipcMain.handle` in `main.ts:14438`; preload invoke
  - `hermes:wake-indicator:set` — `ipcMain.on` in `main.ts:14439`; main→renderer push; preload send
  - `hermes:wake-indicator:state` — main→renderer push; preload on
  - `hermes:watchDirectory` — `ipcMain.handle` in `main.ts:16418`; preload invoke
  - `hermes:watchPreviewFile` — `ipcMain.handle` in `main.ts:16416`; preload invoke
  - `hermes:window-state-changed` — main→renderer push; preload on
  - `hermes:window:openBrowser` — `ipcMain.handle` in `main.ts:14365`; preload invoke
  - `hermes:window:openInTerminal` — `ipcMain.handle` in `main.ts:14385`; preload invoke
  - `hermes:window:openInstance` — `ipcMain.handle` in `main.ts:14360`; preload invoke
  - `hermes:window:openSession` — `ipcMain.handle` in `main.ts:14351`; preload invoke
  - `hermes:window:readBelow` — `ipcMain.handle` in `main.ts:15512`; preload invoke
  - `hermes:workspace:sanitize` — `ipcMain.handle` in `main.ts:16768`; preload invoke
  - `hermes:writeClipboard` — `ipcMain.handle` in `main.ts:16295`; preload invoke
  - `hermes:zoom:changed` — main→renderer push; preload on
  - `hermes:zoom:get` — `ipcMain.handle` in `main.ts:14446`; preload invoke
  - `hermes:zoom:set-percent` — `ipcMain.on` in `main.ts:14453`; main→renderer push; preload send
- **Inputs / options:** see the individual feature entries above; each channel's payload is documented with the feature that owns it.
- **Outputs / side effects:** as documented per feature.
- **Config / env:** n/a
- **Edge cases / guards:** Channel names are the only contract between the two processes — the preload is the single place they are spelled on the renderer side, and every `on*` helper it exposes returns an unsubscribe function.
- **Rebuild notes:** Enumerate the channels in one place; a bridge whose surface can only be discovered by grep will drift.

---

## Handoffs

- Settings → Gateways page forms (Connection mode, Registered gateways, Add/Edit editor fields and their verbatim labels/placeholders/toasts) → `desktop-settings`.
- Settings → Plugins pane (installed lists, enable/disable toggles, Bots toggle, Agent plugins "Applies to" selector) → `desktop-settings`.
- Settings → Appearance (theme grid, UI Scale control, translucency rows, terminal font picker, marketplace search UI) → `desktop-settings`.
- Settings → Advanced (Quick Entry row and its conflict message, Keep computer awake, disable-F12) → `desktop-settings`.
- The renderer's chat surfaces, titlebar band, statusbar items, command palette and Command Center → `desktop-a`.
- Sessions/agents/artifacts/cron/webhooks/pets/Bot Mode roster and group chats → `desktop-b`.
- The full 188-method `tui_gateway` RPC catalogue with per-method params/results and the slash-command surface → `tui` / `gw-slash`.
- `hermes serve`, `hermes dashboard`, `hermes update`, `hermes uninstall`, `hermes logs gui`, `hermes doctor`, `hermes profile export/import` CLI semantics → `cli-*`.
- Backend-side dashboard auth providers (`HERMES_DASHBOARD_BASIC_AUTH_*`, OAuth/Nous Portal registration, `hermes dashboard register`) → `docs-rest` / `web-*`.
- `desktop.*` config keys beyond the ones named here (`repo_scan_*`, `ozone_platform_hint`, `password_store`, `disable_gpu`, `electron_flags`, `macos_signing_identity`) → `config-*`.
- `scripts/install.ps1` / `scripts/install.sh` stage manifests and `scripts/desktop-update/{windows,posix}` script internals → `cli-*` / `docs-features`.
- The web dashboard's own plugin system and its `/api/*` routes → `web-*` / `docs-rest`.
