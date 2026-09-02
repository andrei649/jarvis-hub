# 01. Install, environment & boot

> **Scope.** Everything that must be true *before* any other section of this manual can run, plus the
> honesty of the surfaces that describe the boot itself. Covers: the four install paths
> (`INSTALL.bat`/`install.ps1` on Windows, `install.sh` on Linux/macOS, `docker-compose.yml`, the
> PyInstaller package in `packaging/`), the launchers (`START.bat`, `start.sh`, `serve.py`, raw
> `uvicorn agents.web:app`), `UPDATE.bat` upgrade-in-place, the **full environment-variable matrix**
> actually read by the code, local/cloud model-backend detection and the hybrid router's
> `llm_backend` string, the readiness/version truth surfaces (`/healthz`, `/readyz`, `/status`,
> `/api/status`, `/metrics`, `/api/health/components`), the `product.posture` flip through the
> ~30-second settings watcher, the build's own integrity counters (pytest · vitest · jest, each against `project-status.json`
> · `status_sync.py` · `release_gate.py` · the `hud-v2-build` freshness gate), the data lifecycle
> (`JARVIS_HOME`, backup/verify/export/forget, cold start, upgrade preserving data), and every
> degraded boot the owner can realistically hit.
> **Deliberately left to siblings:** the *content* of HUD panels and modes beyond the first-run gate
> and the boot badges (see the HUD sections), chat quality and per-agent fabrication grading (see the
> chat/agent sections), autonomy/approval mechanics beyond "the queue survives a restart", channels,
> memory/RAG behaviour, mobile/WorldView/Tauri surfaces, and §N AI-OS host operators. Where a boot
> check hands off, the case says so.

> **Prereqs for this whole section.** The repo checked out at or past `06cf011` (run 2's floor); a
> Windows 11 box with an NVIDIA GPU **or** a Linux/macOS box; Python **3.12+** on PATH; ~6 GB free
> disk; the ability to stop/start the server and to reboot it; optional Node 22 (for the frontend
> gates), Docker (for `docker-compose` + sandbox), and LM Studio and/or Ollama. A throwaway
> `JARVIS_HOME` directory for the destructive cases — **never point them at the owner's real data
> root.** Two terminals help (one long-lived for `pytest`).

> **Time.** 4–5h30 end to end on a warm machine for the 158 cases below, plus one clean-VM pass
> (~45 min) and one overnight boundary for the ⏱ cases. The full offline suite alone is 8–25 min;
> `npm ci` in `frontend/` another 2–4 min the first time. If you only have two hours, run in this
> order: the sanity gate (ENV-076) → ENV-143 (R4 regression) → ENV-077+ENV-146 (posture, because every
> later 🤖 section depends on it) → ENV-063 (`sys` telemetry, the anti-fabrication anchor) → ENV-113/114
> (the no-model honest state) → ENV-098 (backup, your rollback for everything else).

Legend, markers, severities and the `Auto:` notation are the manual's shared legend — not redefined here.

---

## 01.1 Clean-machine install — Windows (the owner's box)

The owner's primary path. Run **ENV-001..ENV-005 on a clean Windows 11 VM/user profile**, not on the
already-installed RTX box, or you are testing an upgrade rather than an install.

#### ENV-001 — `INSTALL.bat` on a machine with nothing installed  🖥⏱
- **Surface:** `INSTALL.bat` (repo root) · **Tier:** n/a · **Auto:** ❌ (no test executes any installer script)
- **Why it matters:** this is the *only* install path the product promises a non-technical owner ("Just double-click"). If it needs a terminal, the promise is broken.
- **Prereq:** clean Windows 11 with `winget` available and **no** Python/Git/Node/Docker. Start a stopwatch.
- **Steps:** 1) Download/copy only `INSTALL.bat` into an empty folder. 2) Double-click it. 3) Read every line it prints; note each `[MISSING]`/`[OK]`. 4) When it prints the `[IMPORTANT] New programs were installed / CLOSE this window and run INSTALL.bat AGAIN` block, close and re-run. 5) Repeat until it reaches `[5/7] Fetching the project code…` and completes.
- **Expected:** step order exactly `[1/7] Checking Python` → `[2/7] Checking Git` → `[3/7] Checking Node.js (20+)` → `[4/7] Checking Docker Desktop` → restart notice → `[5/7] Fetching the project code...` (clones `https://github.com/andrei649/jarvis-hub.git` into `.\jarvis-hub`) → `[6/7] JARVIS: Python environment + dependencies...` → `[7/7] WorldView: configuration + Node dependencies...` → `pytest -q` → `[DONE] Full install succeeded!` and the four closing hints (`START.bat`, `set JARVIS_WORLDVIEW=0`, `npm run db:seed`, `UPDATE.bat`).
- **Also acceptable (honest degradation):** Docker failing with `[WARNING] Docker install failed…(WorldView needs Docker; JARVIS runs without it.)` — Docker is explicitly a soft requirement (`INSTALL.bat:67-94`). `[SKIP] The worldview folder is missing in this checkout.`
- **FAIL if:** it exits at a `goto :end` without saying why; it clones but never installs deps; it claims success while `.venv\Scripts\python.exe` does not exist → **BLOCKER**. Any prompt the owner cannot answer from the printed text → **MAJOR**.
- **Evidence:** full console transcript per run, number of re-runs needed, wall-clock total.

#### ENV-002 — the 10-minute quickstart target  🖥⏱
- **Surface:** `README.md` → Quickstart · `MANUAL_TESTING.md` §A · **Auto:** ❌
- **Why it matters:** §A states the target explicitly: *a running server in under 10 minutes*.
- **Steps:** 1) On the clean box, from download to `http://127.0.0.1:8080/` rendering the cockpit, time it. 2) Record the single longest step.
- **Expected:** ≤10 min excluding OS-level downloads (Python/Node/Docker via winget) — record those separately since they dominate.
- **FAIL if:** >10 min with all prerequisites already present → **MAJOR** (record the stall, not just the total).
- **Evidence:** timestamps per numbered step.

#### ENV-003 — `INSTALL.bat` runs the FULL suite before you can start  🖥
- **Surface:** `INSTALL.bat:172-178` (`"!VPY!" -m pytest -q`) · **Auto:** ❌
- **Why it matters:** the installer's last act is an unconditional full-suite run. On a laptop that is many minutes of apparent hang with no progress indicator; a first-time owner may kill it.
- **Expected:** the banner `Verifying with the JARVIS tests (optional)...` appears **before** the run, and the outcome is reported as `[DONE] Full install succeeded!` (rc 0) or `[DONE] Installed (some tests failed - you can still try it).`
- **FAIL if:** a failing suite blocks reaching `START.bat` → **MAJOR**. If the run emits no output for >90 s with no "this takes a while" hint → **MINOR** (usability finding; note it, it is the same trap `install.sh` avoids by defaulting to the fast smoke).
- **Evidence:** elapsed time of the pytest phase; the exact closing banner.

#### ENV-004 — `install.ps1` (PowerShell path) equals `INSTALL.bat`  🖥
- **Surface:** `install.ps1` · **Auto:** ❌
- **Steps:** 1) On a second clean profile: `powershell -ExecutionPolicy Bypass -File install.ps1`. 2) Compare its 5 numbered steps against `INSTALL.bat`'s outcome.
- **Expected:** `[1/5] Python <ver>` → `[2/5] Creating .venv and installing JARVIS dependencies...` → `[3/5] WorldView setup (optional)...` → … → same end state (`.venv` + deps). `[FAIL] dependency install failed` and exit 1 on a pip failure (`install.ps1:37`).
- **FAIL if:** it does not create `.venv` or silently continues after a pip failure → **MAJOR**.

#### ENV-005 — `START.bat` boot + auto-open  🖥👁
- **Surface:** `START.bat` · **Auto:** ❌
- **Steps:** 1) Double-click `START.bat`. 2) Watch the banner. 3) Wait for the browser.
- **Expected:** if `.venv\Scripts\python.exe` exists it is used silently; otherwise `[INFO] No .venv found - using the global Python.` + `Recommended: run UPDATE.bat first.` (`START.bat:30-37`). Then the four address lines — `HUD: http://127.0.0.1:8080/ (V2 cockpit; legacy HUD at /v1)`, `Admin: http://127.0.0.1:8080/admin`, `Signal Layer: http://127.0.0.1:8787/healthz (if started)` — the note `(Keep this window open. Close it to stop the server.)`, and a PowerShell poller that opens the default browser at `/` on the first HTTP 200. `JARVIS_HUD` defaults to `v2`.
- **Also acceptable:** no browser opens if the default browser is unset — the console URL is still correct.
- **FAIL if:** WorldView or the Signal Layer start **without** `JARVIS_WORLDVIEW=1` / `JARVIS_SIGNAL_LAYER=1` → **MAJOR** (both are documented opt-in, `START.bat:39-47`).
- **Evidence:** screenshot of the console + the first HUD paint.

| ID | Check | Do | Expect | Fail | Auto |
|----|-------|----|--------|------|------|
| ENV-006 | `START.bat` with WorldView opted in 🖥 | `set JARVIS_WORLDVIEW=1` then `START.bat` | Three extra windows (`WorldView API`, `WorldView Frontend`, `WorldView Demo Feed`) + `docker compose up -d` in `worldview\`; poller opens `http://localhost:3000` | MAJOR | ❌ |
| ENV-007 | WorldView opt-in with Docker stopped 🖥 | Stop Docker Desktop, repeat ENV-006 | `[SKIP] docker compose failed (is Docker Desktop running?) - skipping WorldView.` and **Nerva still starts on :8080** | MAJOR | ❌ |
| ENV-008 | WorldView opt-in with no `node_modules` 🖥 | `rmdir /s worldview\node_modules`, repeat ENV-006 | `[SKIP] worldview\node_modules is missing. Run this once first: cd worldview && npm install` | MINOR | ❌ |
| ENV-009 | Signal Layer opt-in 🖥 | `set JARVIS_SIGNAL_LAYER=1` then `START.bat`; then `curl http://127.0.0.1:8787/healthz` | `[INFO] Mode: replay  Port: 8787`, separate window, healthz answers | MINOR | ⚠️ CI lane `signal-layer` runs `npm test` in `services/signal-layer` (`.github/workflows/ci.yml`) |
| ENV-010 | Signal Layer with Node absent 🖥 | Rename node.exe out of PATH, repeat | `[SKIP] Node not found (Node 20+ required) - skipping Signal Layer.`; hub still boots | MINOR | ❌ |
| ENV-011 | Legacy HUD switch 🖥 | `set JARVIS_HUD=v1` then `START.bat`, open `/` | `/` serves the legacy static HUD (`agents/web/templates/index.html`); `/v2` still serves the React cockpit (`agents/web.py:736-753`) | MINOR | ❌ |
| ENV-012 | `/v2` alias and SPA deep link | Open `/v2/` then `/v2/anything` | Both return the same v2 shell (SPA client routing); assets come from the `/v2/assets` mount | MINOR | ❌ |
| ENV-013 | Windows service install 🖥 | `deploy/windows/install-service.ps1` per `deploy/README.md` | Service registers (NSSM) and `/healthz` answers after a reboot | MAJOR | ⚠️`tests/test_compatibility.py::test_windows_service_script_present` (presence only) |
| ENV-014 | `smoke.ps1` 🖥 | `powershell -File smoke.ps1` | Runs `pytest tests/ -q --no-header`, then boots `uvicorn agents.web:app` on :8080, asserts `/` returns 200, prints `ALL CHECKS PASSED` and exits 0 | MAJOR | ❌ |

---

## 01.2 Clean-machine install — Linux / macOS

| ID | Check | Do | Expect | Fail | Auto |
|----|-------|----|--------|------|------|
| ENV-015 | `install.sh` default path | `./install.sh` in a fresh clone | `[1/5] Python 3.x` → `[2/5] Creating .venv and installing JARVIS dependencies…` → `[3/5] WorldView setup (opt-in via JARVIS_WORLDVIEW=1)…` → `[SKIP] WorldView not requested…` → `[4/5] Running the install smoke (fast; full suite: ./install.sh --dev)…` → `[5/5] Done. (tests ok: 1)` + the four closing address lines | BLOCKER | ❌ |
| ENV-016 | `install.sh` fast smoke really runs | Watch step 4 | It calls `python scripts/install_smoke.py --json` and prints a JSON object with `ok`, `ready_status`, `agents`, `channels`, `model`, `reply`, `elapsed_seconds` | MAJOR | ✅`tests/test_o26_p2_install_smoke.py` |
| ENV-017 | Install smoke content is honest | Read the JSON | `model` is `install-smoke-fake-model` and `reply` is `Install smoke reply: Nerva is alive.` — i.e. it is visibly a **fake** backend, never presented as your real model (`scripts/install_smoke.py:25-27`) | MAJOR (if it claims a real model) | ✅`tests/test_o26_p2_install_smoke.py` |
| ENV-018 | `install.sh --dev` | `./install.sh --dev` | Step 4 becomes `Running the FULL offline test suite (--dev)…` and runs `python -m pytest -q`; on failure `[WARN] some tests failed — you can still try: ./start.sh` and the install still completes | MAJOR | ⚠️`tests/test_o26_p2_install_smoke.py::test_cli_dev_runs_full_suite_after_fast_smoke` (the script's `--dev`, not `install.sh`) |
| ENV-019 | WorldView opt-in on Linux | `JARVIS_WORLDVIEW=1 ./install.sh` | Node-major check; `[WARN] Node vX is < 20 …` when old; scaffolds `worldview/.env`, `worldview/backend-api/.env`, `worldview/frontend/.env.local` **without overwriting** existing ones; `npm install` in `worldview/` | MINOR | ❌ |
| ENV-020 | `install.sh` never overwrites your filled `.env` | Put a sentinel in `worldview/.env`, re-run with `JARVIS_WORLDVIEW=1` | Sentinel survives (`[ -f … ] \|\| cp`) | MAJOR | ❌ |
| ENV-021 | `start.sh` default | `./start.sh` | `Starting Jarvis Hub at http://127.0.0.1:8080/  (HUD=v2; Ctrl-C to stop)`; activates `.venv` if present, else `[INFO] no .venv found — run ./install.sh first. Using system python.` | MAJOR | ❌ |
| ENV-022 | `serve.py` direct | `python serve.py` | Prints `Nerva starting at http://127.0.0.1:8080` and `Features: multi-agent cabinet, skills system, memory store, cost analytics, CI/CD`, then uvicorn's own startup lines | MAJOR | ⚠️`tests/test_h2311_operability.py::test_server_config_*` |
| ENV-023 | Raw uvicorn entry enforces the same guards | `python -m uvicorn agents.web:app --port 8080` | Boots; the app lifespan calls `enforce_boot_posture()` so the bind/hardened guards apply on this path too (`agents/web.py:275-276`, `agents/core/boot_guards.py:69`) | MAJOR | ✅`tests/test_o26_f6_boot_guards.py::test_web_lifespan_calls_the_guards` |
| ENV-024 | systemd unit | Install `deploy/systemd/jarvis-hub.service` + `jarvis-hub.env`, `systemctl start`, then `systemctl stop` | Starts; `/healthz` 200; `stop` drains in-flight requests within `JARVIS_SHUTDOWN_TIMEOUT` (default 10 s) instead of hanging | MAJOR | ⚠️`tests/test_compatibility.py::test_systemd_unit_present_and_wired` (presence/wiring only) |

---

## 01.3 Container install & the optional service stack

#### ENV-025 — `docker-compose up` brings up the full stack  🔑
- **Surface:** `docker-compose.yml` · **Auto:** ❌
- **Why it matters:** §A promises "all containers healthy" and it is the cheapest way to make §H (Qdrant/Neo4j) and the Oracle agent (n8n) testable — run 1 skipped both because the services were down.
- **Prereq:** a `.env` file **must exist** in the repo root — the `jarvis` service declares `env_file: - .env` and compose fails hard without it.
- **Steps:** 1) `cp .env.example .env` (leave keys blank). 2) `docker compose up -d`. 3) `docker compose ps`. 4) `curl -s localhost:8080/api/status`. 5) `curl -s localhost:6333/readyz` (Qdrant), open `http://localhost:7474` (Neo4j), `http://localhost:5678` (n8n).
- **Expected:** four services `jarvis`, `qdrant`, `neo4j`, `n8n` running; `GET /api/status` → `{"version":"0.11.0","agents":17,"status":"ok"}`; ports 8080/6333/7474+7687/5678 published.
- **FAIL if:** the compose file's inline Dockerfile fails to build, or `jarvis` restarts in a loop → **MAJOR**.
- **Evidence:** `docker compose ps`, the `/api/status` body, `docker compose logs jarvis --tail=50`.

| ID | Check | Do | Expect | Fail | Auto |
|----|-------|----|--------|------|------|
| ENV-026 | Compose binds `0.0.0.0` — the bind guard must be satisfied | Inspect the container CMD then `docker compose logs jarvis \| head -30` | The CMD is `uvicorn … --host 0.0.0.0` passed as a **raw CLI flag**, so `JARVIS_HOST` is unset inside the container and `assert_safe_bind` sees loopback and does not fire. This is the documented residual in `agents/core/boot_guards.py:12-15` — confirm the log carries **no** `[SECURITY] binding to non-loopback host` line and treat the container as network-exposed | MAJOR (if you can reach admin routes from another LAN host with no token — see §01.Y) | ✅`tests/test_o26_f6_boot_guards.py` (guard logic), ❌ (compose posture) |
| ENV-027 | Compose with tokens set | Put `JARVIS_ADMIN_TOKEN`/`JARVIS_USER_TOKEN` in `.env`, recreate | The tokens reach the process as real env vars (compose `env_file`, not dotenv) so admin/user guards activate — contrast with ENV-039 | MAJOR | ✅`tests/test_user_guard_hf1.py`, `tests/test_admin_guard_hf7.py` |
| ENV-028 | Neo4j runs with `NEO4J_AUTH: none` | `docker compose config \| grep -A2 NEO4J_AUTH` | It is genuinely unauthenticated — acceptable only on a loopback-only host. Record it as a posture note, not a pass/fail | MINOR (document) | ❌ |
| ENV-029 | Stack teardown keeps data | `docker compose down` then `up -d` | Named volumes `qdrant_data`, `neo4j_data`, `n8n_data` persist; hub data does **not** (no volume for it) — confirm and note | MAJOR (if the doc claims hub data persists) | ❌ |
| ENV-030 | `docker-compose.worldview.yml` | `docker compose -f docker-compose.worldview.yml up -d` | Only `jarvis-signal-layer` starts on :8787 in `replay` mode; the `worldmonitor` service is commented out by design | MINOR | ⚠️ signal-layer CI lane |
| ENV-031 | Packaged executable build 🖥 | `pip install pyinstaller` then `python scripts/build_exe.py` | Builds `dist/nerva/` (onedir) and runs its own boot smoke: launches the binary with an isolated temp `JARVIS_USER_HOME`, polls `/readyz`, verifies the first-run scaffold (`docs/PACKAGING.md:37-45`) | MAJOR | ⚠️`tests/test_release_build.py`, `tests/test_user_home_packaging.py` |

---

## 01.4 The environment matrix

Every row below was grepped from the source; the "read at" column is where the value is consumed.
**Read this first:** `.env` is loaded **late** — inside `PluginManager.build()` during `load_agents()`
(`agents/core/plugin_manager.py:71-80`), *after* `agents/web.py` has already evaluated its
module-level env reads. So the rows marked **(import-time)** are ignored when set only in `.env`.

| Var | Read at | Effect | Default | If unset |
|---|---|---|---|---|
| `JARVIS_HOST` | `serve.py:66`, `boot_guards.py:75` | uvicorn bind host + the bind guard's input | `127.0.0.1` | loopback-only (safe) |
| `JARVIS_PORT` | `serve.py:67` (`env_int`) | bind port | `8080` | 8080 |
| `JARVIS_LOG_LEVEL` | `serve.py:68` | uvicorn log level | `info` | info |
| `JARVIS_SHUTDOWN_TIMEOUT` | `serve.py:69` | graceful-drain seconds on SIGTERM | `10` | 10 |
| `JARVIS_ALLOW_INSECURE_BIND` | `boot_guards.py:39` | acknowledge an unauthenticated non-loopback bind | off | external bind refuses to start |
| `JARVIS_HARDENED` | `security/hardened.py:32` | forces REDACT guardrails, strict egress, no mutating MCP, requires audit key | off | normal posture |
| `JARVIS_AUDIT_KEY` | `security/hardened.py` (`missing_audit_key`) | HMAC key for the audit chain | unset | **hardened boot refuses to start** |
| `JARVIS_HOME` | `paths.py:140` | relocates the whole runtime-data root | `<repo>/memory_logs` | state lives in the checkout (startup WARNING) |
| `JARVIS_MEMORY_DIR` | `paths.py:140` | legacy alias for the above | unset | — |
| `JARVIS_USER_HOME` | `paths.py:97` | the owner "Documents" data folder (scaffolded) | frozen → `~/Documents/Nerva`; dev → `None` | inert in a dev checkout |
| `JARVIS_APP_ROOT` | `paths.py:82` | overrides the read-only app tree | repo root / `sys._MEIPASS` | — |
| `JARVIS_ADMIN_TOKEN` **(import-time)** | `agents/web.py:62` | bootstrap admin credential | unset | admin routes: localhost trusted, network 403 |
| `JARVIS_USER_TOKEN` **(import-time)** | `agents/web.py:147` | user-tier credential | unset | user routes: localhost only, network 403 |
| `JARVIS_TRUSTED_PROXY` | `agents/web.py:85` | trust `X-Forwarded-For` for the localhost gate + rate-limit key | off | fails closed behind a proxy |
| `JARVIS_RATE_LIMIT` | `agents/web.py:218` (`env_int`) | unauth per-IP requests / 60 s; `0` disables | `120` | 120 |
| `JARVIS_CORS_ORIGINS` | `agents/web.py:416` (`env_list`) | CORS allowlist; middleware only added when non-empty | unset | same-origin only |
| `JARVIS_CSP` | `agents/web.py:518` | overrides the CSP header | the `_DEFAULT_CSP` string | default CSP |
| `JARVIS_DISABLE_CSP` | `agents/web.py:519` | drop the CSP header | off | CSP sent |
| `DEV_MODE` **(import-time)** | `agents/web.py:48` | enables `/sandbox/execute`, skill import, unconfirmed memory clear | off | those return 403/400 |
| `JARVIS_HUD` | `agents/web.py:739` | `v1` serves the legacy HUD at `/` | v2 | v2 cockpit |
| `JARVIS_A2A_ENABLED` | `agents/core/a2a.py:88` | exposes `/.well-known/agent-card` + `POST /api/a2a/task` | off | those 404 |
| `JARVIS_A2A_KEY` | `a2a.py` | peer signing secret | unset | signed tasks 401 |
| `JARVIS_MCP_ROUTE_TOOLS` | `agents/web.py:1311` | binds read-only routes as MCP tools | off | only `ask_<agent>` tools |
| `JARVIS_MCP_MUTATING_TOOLS` | `agents/web.py:1339` | + write routes (double-gated, blocked under hardening) | off | no write tools |
| `JARVIS_LM_STUDIO_URL` | `llm/hybrid_router.py:300` | overrides the LM Studio base URL (wins over the admin setting) | `http://localhost:1234` | auto-detect on :1234 |
| `JARVIS_OLLAMA_URL` | `llm/hybrid_router.py:303` | overrides the Ollama base URL | `http://localhost:11434` | auto-detect on :11434 |
| `JARVIS_STRICT_MODELS` | `llm/hybrid_router.py:388` | block routing to a model off an agent's allowlist | **on** | strict (fail-closed) |
| `JARVIS_AUTO_DEEP` / `JARVIS_DEEP_MODEL` | `llm/hybrid_router.py` | heavy prompts escalate to the deep local slot | `1` / `deepseek-r1-distill-qwen-32b` | deep slot used when available |
| `JARVIS_LLM_WARMUP` | orchestrator | pre-warm the local model at boot | **on** | warms up |
| `JARVIS_SYSTEM_PROFILE` | `system_profiles.py` | `balanced`\|`gaming`\|`ai`\|`multimedia`\|`admin`\|`headless` posture preset | `balanced` | historical behaviour |
| `JARVIS_LOG_FILE` / `JARVIS_LOG_MAX_MB` / `JARVIS_LOG_BACKUPS` | `core/log.py:46,59,60` | rotating file log (opt-in; env wins over `system.log_to_file`) | off / 10 MB / 5 | stderr only |
| `JARVIS_BACKUP_KEY` / `JARVIS_KEY_DIR` | `core/backup.py:63,77,84` | encrypt archives at rest → `.tar.gz.enc` | unset | plaintext `.tar.gz` |
| `JARVIS_TESTING` | orchestrator/stores | test posture | off | — |
| `ANTHROPIC_API_KEY` | `hybrid_router.py:321-347`, `plugin_manager.py:82` | Claude tier for `vision`/`steve` | unset | logs `ANTHROPIC_API_KEY not set — Claude tiering disabled, heavy agents will fall back` |
| `GEMINI_API_KEY` | `hybrid_router.py:320-331` | Gemini Flash/Pro tier + cloud escalation for `athena` | unset | `_cloud_available` false |
| `OPENAI_API_KEY` | `plugin_manager.py:83` | reached through `CloudLLMPlugin` fallback only | unset | — |
| `OPENROUTER_API_KEY` / `OPENROUTER_BASE_URL` | `llm/providers/__init__.py:141-143` | first-class OpenAI-compatible provider profile | unset / `https://openrouter.ai/api/v1` | that profile inactive |
| `TELEGRAM_BOT_TOKEN` / `DISCORD_BOT_TOKEN` / `SLACK_BOT_TOKEN` / `SMTP_*`+`IMAP_*` | `agents/web.py:329-369` | wires each channel at boot | unset | logs `… not set — telegram channel disabled` etc. |
| `JARVIS_WORLDVIEW` / `JARVIS_SIGNAL_LAYER` / `JARVIS_WORLDVIEW_FEED` | `START.bat`, `start.sh`, `install.sh` | opt in to the companion stacks | `0` / `0` / `demo` | not started |

| ID | Check | Do | Expect | Fail | Auto |
|----|-------|----|--------|------|------|
| ENV-032 | Port override | `JARVIS_PORT=8099 python serve.py` | Banner says `http://127.0.0.1:8099`; `curl :8099/healthz` 200 | MAJOR | ✅`tests/test_h2311_operability.py::test_server_config_env_override` |
| ENV-033 | Garbage port falls back, never crashes | `JARVIS_PORT=abc python serve.py` | Boots on **8080** (`env_int` returns the default on non-numeric) | MAJOR | ✅`tests/test_h2311_operability.py::test_server_config_bad_int_falls_back` |
| ENV-034 | Boolean spelling robustness | Set `JARVIS_A2A_ENABLED=on`, then `=ON`, then `=yes`, then `=banana` | `on/ON/yes` enable; `banana` resolves to the flag's **default** (off) — `env_config.truthy` | MAJOR | ✅`tests/test_o26_p2_env_config.py` |
| ENV-035 | Strict flag can't be weakened by a typo | `JARVIS_STRICT_EGRESS=nope` | Stays strict (unknown → declared default, which is on) | BLOCKER if it relaxes | ✅`tests/test_o26_p2_env_config.py::test_strict_egress_default_on_junk_stays_on` |
| ENV-036 | External bind refuses without auth | `JARVIS_HOST=0.0.0.0 python serve.py` with no tokens | `SystemExit` printing `Refusing to bind to non-loopback host '0.0.0.0' without authentication.` + the two remedies | BLOCKER if it binds | ✅`tests/test_o26_f6_boot_guards.py::test_external_bind_without_auth_refuses_to_start` |
| ENV-037 | External bind allowed with a token | `JARVIS_HOST=0.0.0.0 JARVIS_USER_TOKEN=devuser python serve.py` | Boots and prints `[SECURITY] binding to non-loopback host '0.0.0.0' — public routes are reachable from the network (authenticated).` | MAJOR | ✅ same file |
| ENV-038 | External bind with explicit ack | `JARVIS_HOST=0.0.0.0 JARVIS_ALLOW_INSECURE_BIND=1 python serve.py` | Boots; the same line ends `(INSECURE, acknowledged).` | MAJOR | ✅ same file |
| ENV-039 | **Tokens set only in `.env` are ignored** 🔑 | Put `JARVIS_ADMIN_TOKEN=fromdotenv` in `.env` only (not exported), boot, then `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/api/admin/settings -H "X-Admin-Token: fromdotenv"` from **another LAN host** | Document the real behaviour. `ADMIN_TOKEN` is read at `agents/web.py:62` (import), before dotenv loads at `plugin_manager.py:72`, so the token does **not** activate | MAJOR — the runbook tells the owner to "pre-set the keys/tokens in `.env`" (`docs/COWORK_QA_RUNBOOK.md` §8 notes) | ❌ |
| ENV-040 | Cloud keys **do** work from `.env` 🔑 | Put `GEMINI_API_KEY` in `.env` only, boot, `curl -s :8080/status \| grep llm_backend` | `llm_backend` gains `+gemini` — provider keys are read *after* dotenv, unlike the tokens | MAJOR | ⚠️`tests/test_o26_p2_env_config.py` |
| ENV-041 | Hardened profile precondition | `JARVIS_HARDENED=1 python serve.py` with no `JARVIS_AUDIT_KEY` | `SystemExit`: `Refusing to start with JARVIS_HARDENED=1:` + the missing-audit-key bullet | BLOCKER if it starts | ✅`tests/test_o26_f6_boot_guards.py`, `tests/test_cdx12_hardened_profile.py` |
| ENV-042 | Hardened profile boots with the key | add `JARVIS_AUDIT_KEY=…`, retry; then `GET /api/security/posture` (admin) | Boots; `hardened` block reports enabled and the forced toggles | MAJOR | ✅ same |
| ENV-043 | `JARVIS_HOME` relocates state | `JARVIS_HOME=/tmp/nerva-qa python serve.py`, then `ls /tmp/nerva-qa` | `settings.db`, `security/`, `checkpoints/`, … appear there; nothing new under `memory_logs/` | MAJOR | ✅`tests/test_user_home_packaging.py::test_jarvis_home_still_wins_over_user_home` |
| ENV-044 | In-repo data root warns | Boot with `JARVIS_HOME` unset in a git checkout | Log line `Runtime state is inside the git checkout (…) — set JARVIS_HOME to store it outside the repo.` (`agents/web.py:288-290`) | MINOR | ⚠️`tests/test_user_home_packaging.py` |
| ENV-045 | `JARVIS_USER_HOME` scaffold | `JARVIS_USER_HOME=/tmp/nerva-docs python serve.py` | `serve.py` prints `Your data lives in: /tmp/nerva-docs  (config: /tmp/nerva-docs/.env)`; the folder gains `README.md`, `.env` (copied from `.env.example`), `memory/`, `skills/`, `souls/` | MAJOR | ✅`tests/test_user_home_packaging.py::test_ensure_user_home_scaffolds_once` |
| ENV-046 | Scaffold is idempotent | Edit the scaffolded `.env`, restart | Your edit survives; README not rewritten | MAJOR | ✅ same |
| ENV-047 | Admin env view masks secrets | `curl -s :8080/api/admin/env -H "X-Admin-Token: $T" \| grep -i key` | Every var whose name contains `key/token/secret/password/passwd/pass/client_id` is masked (`agents/core/routers/admin.py:63,175-178`); non-secret vars are plaintext | BLOCKER if a real key value is returned | ⚠️`tests/test_admin_settings_mutations.py` |
| ENV-048 | System profile posture | `JARVIS_SYSTEM_PROFILE=gaming python serve.py`, then `GET /api/system/profiles` (user tier) | `gaming` active; `background_autonomy:false`, `model_tier:"local-light"`; and per `orchestrator.load_runtime_settings` a constrained tier forces cloud fallback to `never` | MAJOR | ⚠️`tests/test_o26_p2_env_config.py` + profile tests |

---

## 01.5 Model backends & the hybrid router

#### ENV-049 — LM Studio auto-detect with nothing configured  🤖🖥
- **Surface:** `GET /status` (open) · `GET /api/models/local` (admin) · **Auto:** ✅`tests/test_local_model_status.py`, `tests/test_llm_status_api.py`
- **Why it matters:** the product's headline is "load a model, no config needed".
- **Prereq:** LM Studio running on :1234 with exactly one chat model loaded. Ollama **not** running.
- **Steps:** 1) `curl -s :8080/status | python -m json.tool`. 2) Compare with LM Studio's own "loaded models" list. 3) `curl -s :8080/api/models/local -H "X-Admin-Token: $T"`.
- **Expected:** `lm_online: true`; `llm_backend: "lm-studio"`; `model_state: "ready"`; `model_loaded: true`; `loaded_model` = the exact model id LM Studio shows; `resident_models` = `[{"provider":"lm-studio","id":"<that id>"}]`; `residency_state: "known"`; `configured_model` = the `/admin` default (may differ from `loaded_model` — that is by design).
- **FAIL if:** `loaded_model` names a model LM Studio does not have resident → **BLOCKER** (this is R4's failure mode, one layer down). If `model_loaded: true` with nothing loaded → **BLOCKER**.
- **Evidence:** side-by-side screenshot of LM Studio + the `/status` JSON.

#### ENV-050 — the `llm_backend` composition string is literal, not decorative  🤖🖥
- **Surface:** `GET /status` → `llm_backend` · **Auto:** ⚠️`tests/test_local_model_status.py`
- **Why it matters:** `HybridRouter.name` (`agents/core/llm/hybrid_router.py:578-589`) joins exactly the tiers that answered a probe. Run 1 saw `lm-studio+ollama-howard`; that string is the fastest honest read of which backends exist.
- **Steps:** For each combination, restart the hub and read `llm_backend`:
  1) LM Studio only → `lm-studio`
  2) LM Studio + Ollama → `lm-studio+ollama-howard`
  3) LM Studio + Ollama + `ANTHROPIC_API_KEY` → `lm-studio+ollama-howard+claude`
  4) all of the above + `GEMINI_API_KEY` → `lm-studio+ollama-howard+claude+gemini`
  5) nothing at all → `none`
- **Expected:** exactly those strings, in that order (local, ollama-howard, claude, gemini).
- **FAIL if:** a tier appears in the string while its service/key is absent → **BLOCKER** (a fabricated capability claim). If a tier is missing while present → **MAJOR**.
- **Evidence:** the five strings + the server log lines `LLM backend online: lm-studio (…)`, `Ollama available for Howard (…)` / `Ollama not available — Howard will fall back to default backend`, `Claude API available (…)` / `ANTHROPIC_API_KEY not set — …`.

#### ENV-143 — "What model are you running?" names the RESIDENT model (regression R4)  🤖🖥
- **Surface:** `POST /chat` (**user**) vs the HUD model badge vs `GET /status` → `loaded_model` · **Auto:** ✅`tests/test_llm_control_status_model.py`
- **Why it matters:** run 1's headline honesty failure below the three fabrication blockers — the spoken
  answer named the *configured default* while the badge correctly named the resident model. In a product
  whose pitch is truthful self-reporting, the chat surface lying about its own model is disqualifying.
  This is a **three-source cross-validation**, which is the only kind of check that catches this class.
- **Prereq:** LM Studio running. Load a model that is **not** the `/admin` `llm.default_model` (leave
  `configured_model` pointing at the old one — do **not** switch it through Nerva, load it directly in
  LM Studio, which is exactly how the bug reproduced).
- **Steps:**
  1) In LM Studio confirm the newly loaded model id and that the old one is unloaded.
  2) `curl -s :8080/status | python -c "import json,sys;d=json.load(sys.stdin);print(d['loaded_model'], d['configured_model'], d['resident_models'])"`
  3) Read the HUD top-bar **LLM** badge tooltip (`model loaded: <id>`).
  4) Ask in **EN**: `What model are you running?` — then in **RO**: `Ce model rulezi acum?`
  5) Ask the status-phrased variants too: EN `Which LLM is loaded right now?` / RO `Ce model e încărcat în acest moment?`
- **Expected:** all four sources agree on the **resident** id. `/status` shows
  `loaded_model == <new id>` while `configured_model` may still be the old one (that divergence is by
  design). The chat reply is of the form `I am running <resident id> on <llm_backend>, sir.` —
  `run_llm_control` calls `router.refresh_active_model()` first and only falls back to the cached
  `active_model` if that refresh is unavailable (`agents/core/llm_control.py:138-149`).
- **Also acceptable (honest degradation):** `The language backend is offline, sir. Say 'start LM Studio'
  and I will bring it up.` when the controller reports offline; `LM Studio control is not available, sir.`
  when no controller is wired. Either is a PASS — they claim nothing false.
- **FAIL if:** the reply names the **configured** model while the badge and `/status` name the resident
  one → **BLOCKER** (R4 REGRESSED). If the reply names a model that is resident in neither provider →
  **BLOCKER**. If EN and RO disagree with each other → **MAJOR** (record both verbatim).
- **Evidence:** LM Studio screenshot, the `/status` triple, the badge tooltip screenshot, and all four
  replies **verbatim** (RO with diacritics intact).

| ID | Check | Do | Expect | Fail | Auto |
|----|-------|----|--------|------|------|
| ENV-051 | Non-default URL honored 🤖 | Move LM Studio to :1235, `JARVIS_LM_STUDIO_URL=http://localhost:1235 python serve.py` | Detects; `llm_backend: "lm-studio"`. The env override wins over the persisted admin setting (`hybrid_router.py:300`) | MAJOR | ⚠️`tests/test_local_model_status.py` |
| ENV-052 | Ollama-only boot 🤖 | Stop LM Studio, run Ollama with one model | `llm_backend: "ollama+ollama-howard"` — base detect falls through to Ollama and names it `ollama` (`llm/router.py:59-66`) while `_ollama_available` also holds; `model_state: "ready"`; chat answers | MAJOR | ⚠️ |
| ENV-053 | Backend pin 🤖 | `/admin` → `llm.backend_type = ollama` with both running | Only Ollama is used for `local` routing (`llm/router.py:42-56`) | MAJOR | ⚠️ |
| ENV-054 | Catalog-vs-residency split 🤖👁 | LM Studio running with models available but **none loaded** | `lm_online: true`, `model_state: "no_model"`, `model_loaded: false`, `loaded_model: null`, `residency_state: "known"` — an honest "backend up, no model" | BLOCKER if it says `ready` | ✅`tests/test_local_model_status.py` |
| ENV-055 | Residency unknown 🤖 | A provider that answers `/v1/models` but not `/api/v0/models` | `model_state: "unknown"`, `residency_state: "unknown"` — never `ready` | BLOCKER if it says `ready` | ✅ same |
| ENV-056 | Non-conversational models excluded 🤖 | Load an embedding model only in LM Studio | It must NOT count as a resident chat model (`_CONVERSATIONAL_LM_STUDIO_TYPES = {"llm","vlm"}`, `local_model_inventory.py:24,84-91`) → `model_state: "no_model"` | MAJOR | ✅`tests/test_local_model_status.py` |
| ENV-057 | Strict-local floor is code-enforced 🤖 | With **no** local backend and only `GEMINI_API_KEY`/`ANTHROPIC_API_KEY` set, ask `frigga`, `ultron`, `howard` something | They fail closed with a local-unavailable error, never a cloud answer. `LOCAL_ONLY_AGENTS = {"frigga","ultron","howard"}` (`hybrid_router.py:89`) and no env var can weaken it | **BLOCKER** if any of the three answers via cloud | ⚠️ hybrid-router tests; see the security section for the egress proof |
| ENV-058 | Howard falls back within local 🤖 | Ollama down, LM Studio up, ask Howard | Log `Ollama unavailable for Howard, falling back to LM Studio`; answer served locally. With **both** down: `LocalBackendUnavailableError` — "start Ollama or LM Studio; cloud fallback is forbidden" | MAJOR | ⚠️ |
| ENV-059 | Cloud escalation knob | `PUT /api/admin/settings/llm {"values":{"cloud_fallback":"never"}}`, wait ≤30 s, send an oversized prompt | Stays local (`local-fallback` route), log `Cloud fallback mode → never`; with `always` an auto-policy agent goes `cloud-flash` | MAJOR | ⚠️ |
| ENV-060 | Model-pin violation blocks 🤖 | Point an agent with an `approved_models` allowlist at an unlisted model | `ModelNotApprovedError`, log `model pin violation (blocked)`. With `JARVIS_STRICT_MODELS=0` it warns and allows instead | MAJOR | ⚠️`hybrid_router.py:390-401` |
| ENV-144 | `/api/models/local` control flags are honest 🤖 | `curl -s :8080/api/models/local -H "X-Admin-Token: $T"` with LM Studio up and one model loaded | Each row carries `available`, `resident`, `configured`, `active` and a `controls` object. `can_load` is true **only** for `provider=="lm-studio"` AND the LM Studio controller enabled AND `available is True` AND `resident is False`; `can_unload` only when `resident is True` (`local_model_inventory.py:311-327`). An Ollama row must never offer `can_load`/`can_unload` | MAJOR (a button that cannot work is a false capability claim) | ✅`tests/test_local_model_status.py`, `frontend/src/test/local-models.test.tsx` |
| ENV-145 | `available`/`resident` are tri-state, not boolean 🤖 | Same call with LM Studio answering `/v1/models` but not `/api/v0/models` | `available: true`, `resident: **null**` — "unknown" is a distinct third value from "no" (`local_model_inventory.py:385-386`); the HUD renders it amber, never as "not loaded" | MAJOR | ✅`tests/test_local_model_status.py` |

---

## 01.6 Boot & readiness truth

#### ENV-061 — `/readyz` is 503 while starting and 200 once loaded
- **Surface:** `GET /readyz` · **Tier:** open · **Auto:** ✅`tests/test_h2311_operability.py::test_readyz_*`
- **Why it matters:** a supervisor must be able to hold traffic back; a "ready" lie sends a load balancer real users mid-boot.
- **Steps:** 1) Start the server and immediately poll in a tight loop: `while :; do curl -s -o /dev/null -w "%{http_code} " localhost:8080/readyz; sleep 0.3; done`. 2) Once it flips, `curl -s localhost:8080/readyz | python -m json.tool`.
- **Expected:** one or more `503` then `200`. The 503 body is `{"ready": false, "checks": {...}, "reason": "starting"}` (no orchestrator) or `"agents-not-loaded"`. The 200 body is `{"ready": true, "checks": {"orchestrator": true, "agents_loaded": 17, "channels": N, "llm_backend": "<string>"}}`. `Cache-Control: no-store` on both.
- **Also acceptable:** `agents_loaded` other than 17 **only if** `agents/_system/agents.yaml` says so — cross-check with `GET /api/status` `agents`.
- **FAIL if:** `ready: true` with `agents_loaded: 0` → **BLOCKER**. If a readiness verdict is cacheable → **MAJOR**.
- **Evidence:** the poll transcript, both bodies, response headers.

#### ENV-062 — `/readyz` does NOT lie about the model, and does not gate on it  🤖
- **Surface:** `GET /readyz` vs `GET /status` · **Auto:** ✅`tests/test_h2311_operability.py::test_readyz_ready_even_with_llm_offline`
- **Steps:** 1) Quit LM Studio and Ollama entirely. 2) `curl -s :8080/readyz`. 3) `curl -s :8080/status | python -m json.tool`.
- **Expected:** `/readyz` still **200** with `ready: true` (deliberate — the hub degrades gracefully), and `checks.llm_backend` reads `"none"`. `/status` shows `lm_online: false`, `model_state: "offline"`, `model_loaded: false`, `loaded_model: null`, `llm_backend: "none"`, `residency_state: "offline"`.
- **FAIL if:** `/readyz` reports a backend name while none is reachable → **BLOCKER**. If `/status` shows a `loaded_model` with both servers off → **BLOCKER**.
- **Evidence:** both bodies with LM Studio provably closed (screenshot).

#### ENV-063 — `/status` `sys` telemetry is probed, never fabricated  🖥👁
- **Surface:** `GET /status` → `sys` (`agents/web.py:563` `_sys_info`) · **Auto:** ❌ (probe path needs real hardware)
- **Why it matters:** this is the correctly-grounded surface run 1 used to convict Steve of fabricating a health report. If **this** is wrong, the anti-fabrication cross-check itself is broken.
- **Steps:** 1) `curl -s :8080/status | python -c "import json,sys;print(json.load(sys.stdin)['sys'])"`. 2) Compare `host` with `hostname`. 3) Compare `cpu` with Task Manager / `wmic cpu get name`. 4) Compare `ram_used`/`ram_total` (GB, 1 decimal) with Task Manager. 5) Compare `gpu`, `vram_used`, `vram_total` (GiB, integer) and `gpu_load` with `nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv`.
- **Expected:** `host` = this machine's real hostname (e.g. `DESKTOP-8AV7E7F`), never a doc's reference rig; `cpu` = the real model string plus `· N thr`; `gpu` = the real card name; VRAM within rounding of `nvidia-smi`.
- **Also acceptable (honest degradation):** `gpu: "none"` on a box with no `nvidia-smi`; `gpu: "unknown"` when `nvidia-smi` exists but the probe errors; `cpu: "unknown"` / `"N threads"` when the brand string is unavailable; zeros for `ram_*`/`vram_*` when `psutil` is missing.
- **FAIL if:** any value is a plausible-but-wrong host/CPU/GPU → **BLOCKER**.
- **Evidence:** the `sys` object next to `nvidia-smi` output and `hostname`.

| ID | Check | Do | Expect | Fail | Auto |
|----|-------|----|--------|------|------|
| ENV-064 | Version single source of truth | `curl -s :8080/api/status`; `grep __version__ agents/__init__.py`; `curl -s :8080/openapi.json \| python -c "import json,sys;print(json.load(sys.stdin)['info']['version'])"` | All three read `0.11.0`; `/status` `version` agrees | MAJOR | ✅`tests/test_compatibility.py::test_app_reports_the_single_sourced_version` |
| ENV-065 | Agent count is computed, not hardcoded | `curl -s :8080/api/status` vs `python -c "import yaml;d=yaml.safe_load(open('agents/_system/agents.yaml'));print(sum(1 for c in d['agents'].values() if (c or {}).get('status','active')=='active'))"` | Both 17 (`agents/__init__.py:9-30`) | MAJOR | ⚠️ |
| ENV-066 | `/healthz` answers before the orchestrator exists | Kill the server, restart, hit `/healthz` in the first 200 ms | `200 {"status":"ok","uptime_seconds":<small float>}`; never touches the orchestrator (`routers/ops.py:38-49`) | MAJOR | ✅`tests/test_h2311_operability.py::test_healthz_ok_without_orchestrator` |
| ENV-067 | `/healthz` uptime is monotonic | Note it, change the system clock backwards by 1 h, re-read | Uptime keeps increasing (`time.monotonic`) | MINOR | ⚠️ |
| ENV-068 | `/status` pre-orchestrator | Hit `/status` in the first instants of boot | `{"status":"starting"}` only — no fabricated `sys`/model block (`routers/status.py:65-66`) | MAJOR | ⚠️ |
| ENV-069 | Probes bypass the rate limit | From another LAN host with no token, hammer `/healthz` 300× in a minute | No `429`; `/healthz`, `/readyz`, `/metrics` are exempt (`agents/web.py:483,489`) | MAJOR | ✅`tests/test_h2311_operability.py::test_probes_exempt_from_rate_limit`, `tests/test_rate_limit_hf2.py` |
| ENV-070 | Polling reads are `no-store` | `curl -sD- -o /dev/null :8080/status` and `/dashboard`, `/tasks`, `/ticker`, `/api/cognition`, `/api/swarm/summary`, `/api/presence/owner` | `Cache-Control: no-store` on each (`agents/web.py:460-473`) | MINOR | ⚠️ |
| ENV-071 | Security headers present on boot surfaces | `curl -sD- -o /dev/null :8080/` | `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `Referrer-Policy: no-referrer`, and a `Content-Security-Policy` whose `object-src 'none'` and `frame-ancestors 'self'` are present | MAJOR | ✅`tests/test_hud_security_headers.py` |
| ENV-072 | CSP override / disable | `JARVIS_CSP="default-src 'self'" python serve.py`; then `JARVIS_DISABLE_CSP=1` | Header follows the env; with disable=1 no CSP header at all, other three still sent | MINOR | ✅ same |
| ENV-073 | `/metrics` scrape | `curl -s :8080/metrics \| head` | Prometheus text (`text/plain` per `PROM_CONTENT_TYPE`) with HTTP request/duration/in-flight series; unauthenticated by design | MINOR | ⚠️ |
| ENV-074 | Component health is honest | `curl -s :8080/api/health/components \| python -m json.tool` | `{components, failed, summary}`; the `failed` list actually names components that failed to initialize, not `[]` by default. With the registry unavailable: `{"components":{},"summary":"registry unavailable"}` | MAJOR | ⚠️ |
| ENV-075 | Boot log names the real backend | `docker compose logs jarvis` / the console | One line `Jarvis Beta ready — <llm_backend>, 17 agents, [channels], [skills]` whose backend string matches `/status` `llm_backend` exactly | MAJOR | ⚠️ |
| ENV-076 | Boot sanity gate composite | `/readyz`, `/status`, `/mission-control` (200), `POST /chat {"message":"say hello in one word"}` | All four succeed; this is `COWORK_QA_RUNBOOK` §3(a)–(c) — if any fails, **stop testing and report the boot** | BLOCKER | ⚠️ |

---

## 01.7 Posture & the settings watcher

#### ENV-077 — `product.posture` → `companion_wave1` takes effect with no restart, in ≤30 s
- **Surface:** `PUT /api/admin/settings/product` (admin) → `GET /api/security/posture` (admin) + `GET /api/cognition/status` (user) · **Auto:** ✅`tests/test_o26_p2_product_posture.py`
- **Why it matters:** the cognition/memory stack is default-**OFF**; `OWNER_TEST_DRIVE` Session 0 says most "Jarvis feels dumb" impressions come from testing with it off. Every 🤖 case in later sections depends on this being on and *provably* on.
- **Steps:** 1) `curl -s :8080/api/security/posture -H "X-Admin-Token: $T" | python -m json.tool` — record `product_posture.name`. 2) `curl -s -X PUT :8080/api/admin/settings/product -H "X-Admin-Token: $T" -H 'Content-Type: application/json' -d '{"values":{"posture":"companion_wave1"}}'`. 3) Re-read the posture immediately, then again after 35 s. 4) `curl -s :8080/api/cognition/status` (user tier) — **note:** `OWNER_TEST_DRIVE.md` Session 0 says "`GET /api/cognition` shows enabled", but that route returns the last routing/cognition *context* (`routers/ops.py:113-139`); the flag lives on `/api/cognition/status` (`agents/core/cognition/api.py:28-34`). Use the latter.
- **Expected:** step 2 → `200 {"updated": 1, "category": "product"}`. The posture snapshot then reports `name: "companion_wave1"`, `raw_name: "companion_wave1"`, `valid: true`, `label: "Companion Wave 1"`, `wave: 1`, and the `flags` map showing all eight wave-1 keys — `memory.recall_enabled`, `memory.embed_turns`, `cognition.enabled`, `cognition.honesty_enabled`, `cognition.affect_enabled`, `cognition.memory_enabled`, `cognition.learning_enabled`, `cognition.personality_enabled` — each with `value: true` and **`source: "product.posture:companion_wave1"`** (`agents/core/product_posture.py:18-27,89`). No server restart.
- **Also acceptable:** the *effective* runtime flip (what the orchestrator uses) lands on the next watcher tick, i.e. within 30 s (`agents/core/orchestrator.py:803-806`) — the snapshot may lead it.
- **FAIL if:** the flags still read `source: "default"` after 35 s, or a restart is required → **MAJOR**. If `valid` is `true` for an unknown posture name → **MAJOR**.
- **Evidence:** both posture bodies with timestamps.

| ID | Check | Do | Expect | Fail | Auto |
|----|-------|----|--------|------|------|
| ENV-078 | Only three postures exist | `curl -s :8080/api/admin/settings/product -H "X-Admin-Token: $T"` | `posture` is a `select` with opts `["off","companion_wave1","design_partner"]` (`agents/core/settings_db.py:118`) | MINOR | ✅`tests/test_o26_f2_settings_seed.py` |
| ENV-079 | Invalid posture is rejected, not stored | `PUT …/product -d '{"values":{"posture":"turbo"}}'` | `422 {"error":"invalid settings","details":[…]}`; a re-read still shows the previous value | MAJOR | ✅`tests/test_admin_settings_mutations.py` |
| ENV-080 | Unknown category | `PUT /api/admin/settings/nonsense -d '{"values":{"a":1}}'` and `GET /api/admin/settings/nonsense` | `404 {"error":"unknown category: nonsense"}` — reflected through `safe_reflect`, no stack trace | MAJOR | ✅ same |
| ENV-081 | Malformed body | `PUT …/product -d '{}'` then `-d 'not json'` | `422` from the `AdminPutBody` model; never a 500 | MAJOR | ⚠️ |
| ENV-082 | Settings writes are audited by KEY NAME only | Set a posture, then `GET /api/admin/audit -H "X-Admin-Token: $T"` | A `settings_change` row whose `summary` is `settings.product updated: ['posture']` — the **name**, never the value (`routers/admin.py:90-107`) | BLOCKER if a secret value appears | ⚠️`tests/test_admin_audit_route.py` |
| ENV-083 | `design_partner` composes with hardening | Set `posture=design_partner` with `JARVIS_HARDENED=1` + `JARVIS_AUDIT_KEY` | Same eight wave-1 flags, plus the `hardened` block reporting forced REDACT guardrails / strict egress / mutating-MCP blocked | MAJOR | ✅`tests/test_cdx12_hardened_profile.py` |
| ENV-084 | `/api/cognition` standby state is labelled | On a freshly booted server, before any chat: `GET /api/cognition` | `decision.source == "standby"`, `agents_selected: ["jarvis"]`, `timing` all zeros, `trace: []` — a labelled placeholder, **not** a fake routing decision (`routers/ops.py:117-138`) | MAJOR if it looks like a real decision | ⚠️ |
| ENV-085 | Reseed to defaults | `POST /api/admin/settings/reseed -H "X-Admin-Token: $T"` on a scratch `JARVIS_HOME` | `{"ok":true,"message":"Settings reseeded from defaults"}`; posture returns to `off` | MAJOR | ✅`tests/test_o26_f2_settings_seed.py` |
| ENV-146 | Cognition master flag follows the posture | `GET /api/cognition/status` (user) before and after ENV-077 | Before: `{"enabled": false, …}` (or `{"enabled":false,"available":false}` when no facade is wired — an honest "not available", not a silent true). After the flip: `enabled: true`. This is the *runtime* proof; the posture snapshot is the *declared* one — **both** must agree | **BLOCKER** if the snapshot says the flags are on while `/api/cognition/status` still reports `enabled:false` (a green posture screen over a dead brain) | ⚠️`tests/test_o26_p2_product_posture.py` |
| ENV-147 | Sub-capability endpoints degrade honestly | With posture `off`: `GET /api/cognition/honesty`, `/personality`, `/memory`, `/learning`, `/ensemble` (all **user**) | Each returns `{"available": false}` when its module is absent (`agents/core/cognition/api.py:37-90`) — never a zeroed-out metric block that reads like a real measurement | MAJOR | ⚠️ |
| ENV-148 | Out-of-spec settings keys are skipped, not injected | `PUT /api/admin/settings/product -H "X-Admin-Token: $T" -d '{"values":{"posture":"off","evil_key":1}}'` then `GET /api/admin/settings/product` | Response is `{"updated":1,"category":"product","skipped":["evil_key"]}`; the re-read shows **no** `evil_key` row. Only keys present in the shipped `DEFAULTS` spec are upserted (`settings_db.py:487-497`) | **BLOCKER** if an arbitrary row is created (the rest of the system reads settings back and trusts them) | ✅`tests/test_settings_integrity.py` |
| ENV-149 | Whole-tree settings read is masked | `GET /api/admin/settings -H "X-Admin-Token: $T"` | Every category returned; credential-bearing values are envelope-encrypted at rest and never returned as plaintext (`settings_db.py` secret-field encryption, AUD-1/F2) | **BLOCKER** if a stored secret comes back in clear | ✅`tests/test_settings_secret_encryption.py` |

---

## 01.8 The build's own integrity

#### ENV-086 — the full offline suite, locally green, at the pinned count  ⏱
- **Surface:** `python -m pytest -q` · **Auto:** n/a (this *is* the automated suite)
- **Why it matters:** run 1 could not run it (Python 3.10 shell + a 45 s per-command cap) and had to quote CI. §J makes a locally-green suite at the pinned count part of sign-off.
- **Prereq:** a **persistent** Python 3.12 shell with no per-command timeout; `pip install -r requirements-beta.txt` done.
- **Steps:** 1) `python --version` → must be ≥3.12. 2) `python -m pytest -q 2>&1 | tail -30`. 3) Compare the collected count with `project-status.json` → `tests.backend`.
- **Expected:** the collected count **equals `project-status.json` → `tests.backend` on the revision under test** — which `scripts/status_sync.py` generates from `pytest --collect-only`; note that `MANUAL_TESTING.md`'s preamble still says 5,406 while its own §J says 5,411, so trust the JSON. All passing; every declared skip explained in the output. `pytest.ini` already applies `-q --timeout=30 --timeout-method=thread --allow-hosts=127.0.0.1,::1,localhost`, so a stray real outbound call fails fast with `SocketConnectBlockedError` rather than hanging.
- **Also acceptable:** a small count drift — but per `COWORK_QA_RUNBOOK` §3, *a count differing from `project-status.json` is itself a finding.*
- **FAIL if:** any test fails → **BLOCKER** for the release gate. If the suite cannot run on the tester's Python → record as an **environment limitation**, not a pass.
- **Evidence:** the tail of the run including the summary line, and `python --version`.

| ID | Check | Do | Expect | Fail | Auto |
|----|-------|----|--------|------|------|
| ENV-087 | Suite does not pollute the live data root ⏱ | Note `GET /tasks?view=pending` count, run the full suite, re-read | The count does **not** grow — this is run 1's R5 (test fixtures leaking into the live Decision Inbox) | BLOCKER if it grows | ✅`tests/test_autonomy_queue_isolation.py` |
| ENV-088 | Frontend gates | `cd frontend && npm ci && npm run typecheck && npm test` | `tsc --noEmit` clean; vitest **373** passing (`project-status.json` → `tests.frontend`) | MAJOR | n/a |
| ENV-089 | Legacy-HUD tests | From the repo root: `npm ci && npm test` | The root package runs `vitest run tests/frontend` against the shipped static HUD artifacts | MINOR | n/a |
| ENV-090 | Mobile tests | `cd mobile && npm ci && npm test` | jest **96** passing | MINOR | n/a |
| ENV-091 | hud-v2 bundle freshness gate | `cd frontend && npm run build`, then `git status --porcelain agents/web/v2` | **Empty** output. Any diff means the committed bundle at `agents/web/v2/assets/` is stale — CI fails with `agents/web/v2 is stale — run 'cd frontend && npm run build' and commit.` (`.github/workflows/ci.yml:124-149`) | MAJOR | ✅ CI lane `hud-v2-build` |
| ENV-092 | Stale-bundle consequence 👁 | If ENV-091 produced a diff, diff the old/new `index-*.js` for the panels you are about to test | A stale bundle is the documented cause of run 1's false kill-switch "ENGAGED" (v2 bundle copy vs `agents/web/static/tools.js`) — record it before grading any HUD case | MAJOR | ❌ |
| ENV-093 | Generated status artifacts in sync | `python scripts/status_sync.py --check --reuse-js-counts` | Exit 0. On drift it prints `Generated project status out of sync: <files>` + `Fix with: python scripts/status_sync.py`. It deliberately ignores `latest_ci_commit` | MAJOR | ✅`tests/test_status_sync.py` |
| ENV-094 | Route/agent/gate counters are real | `python -c "import json;print(len(json.load(open('tests/_snapshots/route_surface.json'))))"` vs `project-status.json` → `routes` | Both **404** | MAJOR | ✅`tests/test_route_parity_guard.py`, `tests/test_status_sync.py` |
| ENV-095 | Machine-side release gate | `python scripts/release_gate.py` (or `--skip-tests` for the snapshot-guard subset) | Prints `code-complete` / `machine-verified` / `owner-verified` / `market-verified` tiers and a verdict `READY (machine-side) — 0 FAIL, N WARN` or `NOT READY`. `A1` (this manual's run) and `A8` are expected FAIL until the owner records them | MAJOR | ✅`tests/test_release_gate.py` |
| ENV-096 | Version-tag coherence | `python scripts/release_gate.py --json \| grep -A2 version-tag` | `WARN` with `__version__=0.11.0; no git tag` or `latest tag vX != __version__` — a WARN is expected pre-1.0, a FAIL means `agents.__version__` is unreadable | MINOR | ✅ same |
| ENV-097 | Doc links resolve | Same JSON → `doc-links` | `PASS`; a FAIL names the broken `file → target` pairs across README/MOONSHOT/NERVA_VISION/BACKLOG/GO_LIVE_PLAN/STATUS | MINOR | ✅ same |

---

## 01.9 Data lifecycle

#### ENV-098 — backup → verify (the restore drill) through the HUD and the API
- **Surface:** `GET/POST /api/admin/backup`, `POST /api/admin/backup/verify` (all **admin**) · Console → **Admin** → `BACKUP · EXPORT · FORGET` card · **Auto:** ✅`tests/test_backup.py`
- **Why it matters:** `UPGRADE.md` names the backup as the *only* rollback path, because migrations are forward-only.
- **Prereq:** admin token (or localhost, where the admin guard trusts a direct-localhost origin when no admin credential is configured — `agents/web.py:121-131`). Do this on a scratch `JARVIS_HOME` first, then once for real.
- **Steps:** 1) `curl -s -X POST :8080/api/admin/backup -H "X-Admin-Token: $T" -H 'Content-Type: application/json' -d '{"label":"pre-qa run"}'`. 2) `curl -s :8080/api/admin/backup -H "X-Admin-Token: $T"`. 3) `curl -s -X POST :8080/api/admin/backup/verify -H "X-Admin-Token: $T" -d '{}'`. 4) Repeat 1–3 from the HUD card's **back up now** and **verify** buttons.
- **Expected:** step 1 → `{"ok":true,"archive":"…/backups/…tar.gz","bytes":N,"created_at":…,"version":…,"label":"pre-qa run","encrypted":false,"dbs":[…],"file_count":N}`. Step 2 → newest-first rows `{name, bytes, encrypted, modified_at}`. Step 3 → `{"archive":…,"ok":true,"encrypted":false,"dbs":{"settings.db":"ok",…},"file_count":N,"manifest":{…}}` — the drill really extracts and runs `PRAGMA integrity_check` on every `.db`. HUD messages: `backup created · <size>` and `restore-drill OK · <n> files`.
- **Also acceptable:** `404 {"error":"no backups to verify"}` when the list is empty.
- **FAIL if:** `ok: true` with an empty `dbs` map on a populated data root, or `verify` returning `ok` for a truncated archive (see ENV-135) → **BLOCKER**.
- **Evidence:** all three bodies + the HUD card screenshot.

#### ENV-099 — restore is CLI-only, and refuses a non-empty target
- **Surface:** `python -m agents.core.backup restore <name> <target> [--force]` · **Auto:** ✅`tests/test_backup.py`
- **Why it matters:** hot in-place restore is deliberately **not** an HTTP route (`agents/core/routers/backup.py:1-11`) — an operator action with the server stopped.
- **Steps:** 1) `python -m agents.core.backup list`. 2) `python -m agents.core.backup restore <name> /tmp/restore-empty` (empty dir). 3) Repeat into the same, now non-empty, dir without `--force`. 4) Retry with `--force`. 5) Confirm there is **no** HTTP restore route: `python -c "import json;print([r for r in json.load(open('tests/_snapshots/route_surface.json')) if 'restore' in r])"`.
- **Expected:** step 2 → `{"restored_to":…,"file_count":N,"dbs":{…:"ok"},"ok":true}` (it re-integrity-checks the *restored* files). Step 3 → `FileExistsError … pass force=True to overwrite`. Step 5 → `[]`.
- **FAIL if:** it overwrites a non-empty target without `--force` → **BLOCKER**. If any HTTP route performs a restore → **MAJOR** (contradicts the documented design).
- **Evidence:** the four command outputs.

| ID | Check | Do | Expect | Fail | Auto |
|----|-------|----|--------|------|------|
| ENV-100 | Encrypted backups | `JARVIS_BACKUP_KEY=qa-key` then create + verify | Archive name ends `.tar.gz.enc`, listing shows `encrypted: true` (HUD renders an `enc` tag); verify decrypts and still reports `ok` | MAJOR | ✅`tests/test_backup.py` |
| ENV-101 | Wrong key can't read an encrypted archive | Create with key A, verify with `JARVIS_BACKUP_KEY=B` | `500 {"error":"verify failed"}` — a static message, no key material, no stack trace | MAJOR | ⚠️ |
| ENV-102 | Backups exclude themselves | Create three in a row, inspect the third's `file_count`/members | The `backups/` dir is never inside an archive; `.db-wal`/`.db-shm`/journal sidecars excluded (folded into the DB snapshot) | MAJOR | ✅ same |
| ENV-103 | The label never reaches a path | Create with `{"label":"../../etc/pwn"}` | Filename is `jarvis-backup-<UTC ts>_<hex>.tar.gz` only; the sanitized label appears in the manifest as data (`agents/core/backup.py:161-168`) | BLOCKER if the label lands in the path | ✅ same |
| ENV-104 | Portable export | `POST /api/admin/export -H "X-Admin-Token: $T"`; HUD **export my data** | `{"ok":true,…,"bytes":N}`, HUD `export written · <size>`; the dump covers user-content DBs only — never `settings.db`/secrets (`data_export.EXPORT_DBS`) | MAJOR | ✅`tests/test_data_export.py`, `tests/test_export_route_h23_9.py` |
| ENV-105 | Forget requires the literal confirmation | `POST /api/admin/forget -d '{}'`, then `-d '{"confirm":"forget"}'` | Both `400 {"error":"forget requires confirmation — send {\"confirm\": \"FORGET\"}"}` — case-sensitive | MAJOR | ✅`tests/test_data_purge.py` |
| ENV-106 | Forget is backup-first and recoverable ⚠️destructive | On a **scratch** `JARVIS_HOME` with seeded content: `POST /api/admin/forget -d '{"confirm":"FORGET"}'` | A snapshot is created **and verified** before deletion; content DBs (`missions.db`, `autonomy.db`, `analytics.db`), `notes.json`/`canvas.json` reset, and the memory-at-rest files (`bitemporal_kg.json`, `entities.json`, `decay.json`, `cognition/*`, `house/private_graph.enc`, `embedding_cache/`) are gone. HUD: `forgotten · backup-first purge complete`. `settings.db` and secrets survive | BLOCKER if it deletes without a verified backup | ✅`tests/test_data_purge.py`, `tests/test_data_purge_memory.py` |
| ENV-107 | Forget UI can't be fat-fingered 👁 | Console → Admin → `forget me…`, type `forget`, then `FORGET` | The `confirm erase` button stays disabled until the input is exactly `FORGET`; `cancel` clears the armed state | MAJOR | ⚠️`frontend/src/test/backup-panel.test.tsx` |
| ENV-108 | Forget contract gate | Trigger forget where the purge contract denies it | `403 {"error":"contract denied: <reason>"}` — never a partial delete | BLOCKER | ✅`tests/test_data_purge.py` |
| ENV-109 | Cold start on an empty data root ⏱ | `JARVIS_HOME=/tmp/nerva-cold python serve.py` on a never-used dir | Boots; `settings.db` is created and seeded with defaults; `/readyz` 200 with 17 agents; the HUD shows the **FIRST RUN** Command Center (install `✓ ready · v0.11.0`, an honest model label, `NEEDS SETUP` outcome tags) and **no seeded/demo content presented as real** | BLOCKER if any panel renders sample data as live | ✅`tests/test_o26_f2_settings_seed.py`, `tests/test_db_migrations.py` |
| ENV-110 | Delete-and-reboot cold start ⏱ | Stop the server, `rm -rf /tmp/nerva-cold`, restart | Identical to ENV-109: clean first-run state, empty inbox, empty audit, `GET /api/admin/audit` → `{"page":1,"limit":50,"total":0,"rows":[]}` | BLOCKER | ⚠️ |
| ENV-111 | Upgrade-in-place preserves data ⏱🖥 | On the real box: back up (ENV-098), note the pending-decision count + a memory fact + the posture, run `UPDATE.bat`, restart, re-check | `UPDATE.bat` runs `git pull --rebase origin main` → `.venv` → `pip install -r requirements-beta.txt` → `npm install` in `worldview/` (or `[SKIP] npm not found`) → `pytest -q` → `[OK] Everything passed. Start the app with START.bat`. After restart: count, fact, and posture all unchanged; schema migrations applied silently (forward-only, `PRAGMA user_version`) | BLOCKER if data is lost | ✅`tests/test_db_migrations.py` (migrations only) — ❌ for `UPDATE.bat` itself |
| ENV-112 | `UPDATE.bat` with local changes 🖥 | Dirty the tree, run `UPDATE.bat` | `[WARNING] git pull failed. You may have unsaved local changes.` + `Run in a terminal: git status`, then stops — it does **not** clobber your work | MAJOR | ❌ |

---

## 01.10 Degraded boots & the first-run surface

| ID | Check | Do | Expect | Fail | Auto |
|----|-------|----|--------|------|------|
| ENV-113 | No model at all 🤖 | Quit LM Studio + Ollama, no cloud keys, boot, then send a chat turn from the HUD | Server boots, `/readyz` 200. The chat pane shows the honest line `⚠ No reply — the model backend is unreachable or no model is loaded. Load a model in LM Studio, or enable ◐ DEMO to preview the interface.` (`frontend/src/app.tsx:294`) and the LLM badge reads `○ OFFLINE` with tooltip `no local LLM backend reachable` (`frontend/src/shell.tsx:39`) | BLOCKER if any answer is produced or a model is named | ⚠️ |
| ENV-114 | First-run gate appears and doesn't lie 👁 | Clean `localStorage` (incognito), open `/` with no model | The FIRST RUN modal shows `install ✓ ready · v0.11.0`, `model` in amber reading `no runnable model` (or `<id> · configured, not loaded`), and the hint `No conversational model is loaded — load one in LM Studio or Ollama, or add a cloud API key in Admin → settings.` The "Say hello" action is **not** offered a `run` button; its `reason` reads `model not loaded` | BLOCKER if `run` is offered with no model | ⚠️`frontend/src/test/command-center-panel.test.tsx`, `first-run-gate.test.tsx` |
| ENV-115 | "Say hello" does not tick on a degraded reply 👁🤖 | With a model that 400s, click **run** on Say hello | The reply is shown but the onboarding dial does **not** advance — a `⚠`-prefixed reply is treated as a failed step (`frontend/src/gap.tsx:2721-2729`) | MAJOR | ⚠️`frontend/src/test/command-center-panel.test.tsx` |
| ENV-116 | First-run dismiss persists 👁 | Click `continue to cockpit →`, reload | Gate does not reappear (`hud.firstrun.dismissed` in `localStorage`) | MAJOR | ⚠️`frontend/src/test/first-run-gate.test.tsx` |
| ENV-117 | Cold-navigation OFFLINE flash 👁 | Fresh tab straight to `/` right after `/status` and `/readyz` returned healthy | **Known cosmetic, expected to reproduce:** a brief `roster offline — server unreachable` + `○ OFFLINE` + 0 agents before the first poll (`frontend/src/shell.tsx:42,204`). Confirm it self-corrects within ~15 s | COSMETIC (do not re-file; confirm and reference) | ❌ |
| ENV-118 | Missing hard dependency | In a venv, `pip uninstall -y fastapi` then `python serve.py` | `Missing dependencies: fastapi` + `Run: pip install -r requirements-beta.txt`, exit 1. Repeat for `pyyaml`, `httpx`, `uvicorn`, `cryptography` — each named, friendly, exit 1 (`serve.py:16-27`) | MAJOR if it crashes with a traceback instead | ⚠️ |
| ENV-119 | Missing optional dependency | `pip uninstall -y numpy` then boot | Warning `numpy not installed — vector store will be slower`; server still starts | MINOR | ⚠️ |
| ENV-120 | PyYAML conflict | On a box with a system PyYAML, `pip install -r requirements-beta.txt`; if it errors, retry with `--ignore-installed PyYAML` | The documented workaround (`COWORK_QA_RUNBOOK` §2) works. Note whether the plain command fails at all on this box | MAJOR | ❌ |
| ENV-121 | Python 3.10/3.11 | On a 3.10 or 3.11 interpreter: `./install.sh`, then `python -m pytest -q` | Document precisely what happens. `COMPATIBILITY.md` declares a **hard floor of 3.12**, yet no installer enforces it (see Open gaps) — expect either a numpy resolution to `>=2.0,<2.5` and a partially working install, or import errors | MAJOR (the installer should refuse) | ❌ |
| ENV-122 | Port already in use | Start a second instance on 8080 | uvicorn fails with an address-in-use error and exits; the **first** instance keeps serving. `START.bat`'s browser poller must not open a tab that shows the wrong instance | MAJOR | ❌ |
| ENV-123 | Services down, honestly reported | Stop Qdrant/Neo4j/n8n, boot, read the Console heartbeat log + `GET /api/health/components` | Real "not responding on 127.0.0.1:6333 / :7474 / :5678" lines with real timestamps; the components view lists them as failed. **This is the grounded surface R2 grades Steve against** — capture it before asking Steve anything | BLOCKER if services are reported Online while down | ⚠️ |
| ENV-124 | No tokens at all | Boot with `JARVIS_ADMIN_TOKEN`/`JARVIS_USER_TOKEN` unset; hit `/api/admin/settings` from **localhost**, then from another LAN host | Localhost: 200 (dev posture, so a fresh box can mint its first token). LAN: `403 {"detail":"admin disabled from network — set JARVIS_ADMIN_TOKEN to enable remote access"}` | BLOCKER if the LAN request succeeds | ✅`tests/test_admin_guard_hf7.py`, `tests/test_user_guard_hf1.py` |
| ENV-150 | The three starter outcomes never overclaim 👁 | On a box with no Google connector and no configured docs folder: `GET /api/onboarding/command-center` and the HUD's `WHAT NERVA CAN DO FOR YOU` block | All three rows (`plan_my_day`, `private_documents`, `research_web`) read `status:"needs_setup"` → amber **`NEEDS SETUP`** tag, each with a concrete `setup` string. `live` requires the **capability registry's runtime honesty verdict** (`honesty.status == "live"` and `degraded == false`), so a merely-registered plugin manifest can never light this up (`routers/onboarding.py:279-290`). The privacy tag must match the route actually used: `stays local` only for `local`/`local-deep`/`local-fallback`, else `stored locally · cloud model may receive context` | **BLOCKER** if any row shows `READY NOW` without its connector, or claims `stays local` while routed to cloud | ⚠️`frontend/src/test/command-center-panel.test.tsx` |
| ENV-151 | Wizard completion is derived, not asserted 👁 | `GET /api/onboarding/wizard` (user) on a fresh install; then click **run** on Say hello with a working model; re-read | Five steps in order `intro`, `model`, `test_chat`, `autonomy`, `product_posture`. `completed` is derived from recorded funnel events (`funnel.<step>.complete` in the analytics store, `routers/onboarding.py:260-266`) — so it survives a reload without a wizard-specific store. After a successful hello, `completed` contains `test_chat` and `complete:false` (2 of 5 outstanding) | MAJOR | ✅`tests/test_onboarding_wizard.py` |
| ENV-152 | First-run gate is keyboard-reachable ♿👁 | With the FIRST RUN modal open, use **Tab/Enter only** to reach and activate `run` on Say hello, then `continue to cockpit →` | Both reachable with a visible focus indicator; `Escape` behaviour is defined (the sibling `ConsoleOverlay` binds Escape explicitly — record whether `FirstRunGate` does too, and whether focus is trapped inside the modal) | MINOR | ❌ |

---

## 01.X Degraded & honest-state matrix

What every boot surface in this section MUST show per condition. A cell that shows anything more
optimistic than stated is a finding.

| Surface | No model backend | Model server up, none loaded | Qdrant/Neo4j/n8n down | No tokens configured | Empty / deleted data root | Mid-boot (first ~2 s) | Hardened w/o audit key |
|---|---|---|---|---|---|---|---|
| `GET /healthz` | 200 `{status:ok,uptime_seconds}` | 200 | 200 | 200 | 200 | **200** (never touches orch) | process refuses to start |
| `GET /readyz` | 200 `ready:true`, `checks.llm_backend:"none"` | 200 `ready:true` | 200 | 200 | 200 once agents load | **503** `reason:"starting"` / `"agents-not-loaded"` | — |
| `GET /status` | `lm_online:false`, `model_state:"offline"`, `loaded_model:null`, `llm_backend:"none"` | `model_state:"no_model"`, `model_loaded:false`, `loaded_model:null` | unchanged (model fields independent) | unchanged (open route) | `agents_total:17`, `sessions:0` | `{"status":"starting"}` **only** | — |
| `GET /status` → `sys` | real host/CPU/RAM; `gpu:"none"` w/o nvidia-smi | same | same | same | same | absent (see above) | — |
| `GET /api/status` | `{version,agents:17,status:"ok"}` | same | same | same | same | same | — |
| `GET /api/health/components` | components listed, failures in `failed[]` | same | Qdrant/Neo4j/n8n in `failed[]` | same | same | `{"components":{},"summary":"registry unavailable"}` | — |
| `GET /api/cognition` | standby placeholder, `decision.source:"standby"` | same | same | 403 from LAN, 200 from localhost | standby | standby | — |
| `GET /api/cognition/status` | `enabled:false` (posture off) or the facade's real flags | same | same | 403 from LAN | `{"enabled":false,"available":false}` — an honest "no facade", not a zeroed metric block | same | — |
| Starter outcomes (`command-center`) | all three `needs_setup` + amber `NEEDS SETUP` + a concrete `setup` string | same | `research_web` needs_setup if websearch is degraded | — | all three `needs_setup` | — | — |
| `GET /api/security/posture` | 200 with real flags | 200 | `sandbox.backend:"unavailable"` when Docker absent | 403 from LAN | posture `off` unless set | `503 {"error":"not initialized"}` | — |
| `GET /api/admin/backup` | 200 `{"backups":[]}` | 200 | 200 | 403 from LAN / 200 localhost | `{"backups":[]}` (dir absent → empty, not error) | 200/503 | — |
| HUD LLM badge (`shell.tsx:39-42`) | `○ OFFLINE` · "no local LLM backend reachable" | amber "configured, not loaded" | unchanged | — | — | brief false `○ OFFLINE` (ENV-117, cosmetic) | — |
| FIRST RUN Command Center | `no runnable model` + the LM-Studio hint; Say hello has no `run` | `<id> · configured, not loaded` | unchanged | — | appears (wizard incomplete) | — | — |
| HUD roster (`shell.tsx:204`) | populated | populated | populated | — | populated | `roster offline — server unreachable` (cosmetic) | — |
| Chat pane | `⚠ No reply — the model backend is unreachable or no model is loaded…` | same | same | 401/403 per tier | honest empty pane | — | — |
| `serve.py` console | boots, no model claim | boots | boots | boots | prints data-root line if user home active | — | `SystemExit: Refusing to start with JARVIS_HARDENED=1:` |

---

## 01.Y Negative, adversarial & abuse cases

| ID | Check | Do | Expect | Fail | Auto |
|----|-------|----|--------|------|------|
| ENV-125 | Admin route without a token, LAN 🌐 | From a phone/second host: `curl -si http://<box>:8080/api/admin/settings` | `403` with the static detail (no token configured) or `401 {"detail":"admin token required"}` when one is | BLOCKER if 200 | ✅`tests/test_admin_guard_hf7.py` |
| ENV-126 | Wrong admin token | `-H "X-Admin-Token: wrong"` | `401`; constant-time comparison (`secrets.compare_digest`) — no timing oracle, no hint about length | MAJOR | ✅ same |
| ENV-127 | Forged proxy header 🌐 | From the LAN: `-H "X-Forwarded-For: 127.0.0.1"` on `/api/admin/settings` | Still `403` — untrusted forwarding headers make `_real_client_host` return `""`, failing closed (`agents/web.py:96-104`). Only `JARVIS_TRUSTED_PROXY=1` changes this | **BLOCKER** if it grants localhost trust | ✅ same |
| ENV-128 | Rate-limit spoofing 🌐 | From the LAN, hammer with a rotating `X-Forwarded-For` and no `JARVIS_TRUSTED_PROXY` | `429 + Retry-After: 60` still arrives after `JARVIS_RATE_LIMIT` hits — the socket peer is used, not the header (`agents/web.py:224-240`) | MAJOR | ✅`tests/test_rate_limit_hf2.py` |
| ENV-129 | Token brute-force is throttled 🌐 | From the LAN, send 200 wrong-token admin requests in a minute | Throttled: an *invalid* credential is not exempt from the limiter (`agents/web.py:243-248`) | MAJOR | ✅ same |
| ENV-130 | Rotation kills the env token | `POST /api/admin/rotate-tokens -d '{"scope":"admin","ttl_days":1}'`, then retry the old `JARVIS_ADMIN_TOKEN` | New token returned **once** with `note: "store this token now — it is shown only once"`; the static env token is now revoked and returns 401 even though still exported (`agents/web.py:70-73`) | MAJOR | ✅`tests/test_token_lifecycle.py` |
| ENV-131 | Offline recovery from total token loss | Lose every token, then `python -m agents.core.security.token_store rotate admin` on the box | Mints a fresh admin token with no HTTP involved — no lockout | MAJOR | ✅ same |
| ENV-132 | Oversized settings payload | `PUT /api/admin/settings/product` with a 10 MB `values` object | Rejected (422/413) without a 500 or an OOM; server stays up | MAJOR | ⚠️ |
| ENV-133 | Unicode + RO diacritics in a settings write | `PUT …/general -d '{"values":{"wake_words":["Jarvis","Nervă","șțăîâ","🜂"]}}'` then read back | Round-trips byte-exact (UTF-8, no mojibake); an invalid type is 422. Cross-check the value in the HUD Settings panel | MAJOR | ⚠️ |
| ENV-134 | Path traversal via a backup name | `POST /api/admin/backup/verify -d '{"name":"../../../etc/passwd"}'`; then `{"name":"jarvis-backup-x.tar.gz%00"}` | `404 {"error":"backup not found"}` — the name is matched against the trusted listing, never joined into a path (`agents/core/backup.py:239-251`) | BLOCKER if anything outside `backups/` is read | ✅`tests/test_backup.py` |
| ENV-135 | Corrupt archive is caught | Truncate a `.tar.gz` in `backups/` by 50 %, then verify it | `500 {"error":"verify failed"}` or a report with `ok:false` — **never** `ok:true` | BLOCKER | ✅ same |
| ENV-136 | Zip-Slip / symlink archive | Craft an archive containing `../evil` and a symlink member, then restore it into a temp dir | Escaping members raise; symlinks and special files are skipped and never written (`_safe_extract`, `agents/core/backup.py:255+`) | BLOCKER | ✅ same |
| ENV-137 | Double-submit / race on backup | Fire 5 concurrent `POST /api/admin/backup` | 5 distinct archives (microsecond timestamp + `secrets.token_hex(3)`); no partial/zero-byte file; the listing shows all 5 | MAJOR | ⚠️ |
| ENV-138 | Rapid-clicking the HUD backup buttons 👁 | Click **back up now** 6× fast, then **verify** 3× | No duplicate-key errors, no stuck spinner; the card's snapshot count and the `msg` line settle to a correct final state | MINOR | ❌ |
| ENV-139 | Refresh mid-backup 👁 | Start a backup of a large data root, hard-refresh the HUD immediately | On reload the archive either exists complete or not at all; nothing renders a half-written snapshot as valid | MAJOR | ❌ |
| ENV-140 | Restart mid-write ⏱ | Kill `-9` the server while a settings write / chat turn is in flight, restart | Boots; `settings.db` opens cleanly (`PRAGMA integrity_check` via a backup+verify); migrations do not re-run destructively; no orphan `.db-wal` breaks startup | BLOCKER if the DB is unopenable | ⚠️`tests/test_db_migrations.py` |
| ENV-141 | Graceful vs abrupt shutdown | `JARVIS_SHUTDOWN_TIMEOUT=2 python serve.py`, start a slow request, `SIGTERM` | Exits within ~2 s, draining what it can; channels stopped and pooled clients closed via the lifespan teardown (`agents/web.py:390-406`) — no hang, no zombie | MAJOR | ⚠️`tests/test_lifespan_smoke.py` |
| ENV-142 | Clock skew across a restart ⏱ | Note `/healthz` uptime and the newest `/api/admin/audit` timestamp, set the system clock back 2 h, restart, re-read | Uptime restarts from ~0 and is monotonic; audit rows keep their original timestamps and the chain still verifies — `GET /api/security/audit/verify` (open tier) → `{"valid":true,"first_invalid_id":null,"entries":N}` with `N` ≥ the pre-restart count | MAJOR | ⚠️ |
| ENV-153 | Local-docs key is a key, never a path | `POST /api/local-docs/index -H "X-User-Token: $U" -d '{"key":"/etc"}'`, then `-d '{"key":"../../.."}'`, then a 200-char key | Every one → `404 {"error":"unknown folder key '<echo>'","available":[…]}`. The folder path comes from the owner-configured `local_docs.folders` map, so **no request value reaches a filesystem path expression** (`routers/onboarding.py:21-26,49-55`); a >128-char key is a 422 from the field's `max_length` | **BLOCKER** if any host path is indexed | ⚠️ |
| ENV-154 | Funnel namespace stays bounded | `POST /api/onboarding/funnel -d '{"step":"pwn","event":"complete"}'` (user), then a 10 k-char `step` | `400 {"error":"unknown step 'pwn'","steps":["autonomy","intro","model","product_posture","test_chat"]}`; the oversized step is 422 (`max_length=64`). An unbounded funnel namespace would let a caller pollute the analytics store the wizard derives its state from | MAJOR | ✅`tests/test_onboarding_wizard.py` |
| ENV-155 | Disk full during a backup | Fill the volume holding the data root, then `POST /api/admin/backup` (admin) | `500 {"error":"backup failed"}` (the `OSError`/`ValueError` handler, `routers/backup.py:50-52`) and **no** truncated archive in `GET /api/admin/backup` — the tar is staged in a temp dir and only moved into `backups/` on success (`core/backup.py:176-202`) | MAJOR (BLOCKER if a truncated archive is listed as a snapshot) | ⚠️`tests/test_backup.py` |
| ENV-156 | Read-only data root | `chmod -w` the resolved `data_root()`, restart | A readable error naming the path — never a boot that appears healthy while persisting nothing, and never a silent fallback into the repo checkout. Record the exact message | MAJOR | ❌ |
| ENV-157 | Two servers, one data root ⏱ | `JARVIS_HOME=/tmp/shared JARVIS_PORT=8080 python serve.py` and `…PORT=8081 python serve.py` together; approve a task on one, read the inbox on the other | Either a clean SQLite lock error, or genuinely shared state. **Silently diverging** `autonomy.db` views (each process holding its own truth) → **MAJOR**: an owner running `START.bat` twice would then approve into a queue nobody reads | MAJOR | ❌ |
| ENV-158 | `JARVIS_RATE_LIMIT=0` really disables 🌐 | `JARVIS_RATE_LIMIT=0 python serve.py`, then 500 unauthenticated requests/min from the LAN | No 429 at all (`agents/web.py:218` + the limiter's zero check) — it must not quietly fall back to 120 | MINOR | ✅`tests/test_rate_limit_hf2.py` |

Also worth deliberately breaking, no separate ID needed: boot with `JARVIS_HOME` set to a path
containing spaces, RO diacritics and a trailing dot (`/tmp/nervă test./`) — expect it to work or to
fail with a readable message, never to half-create stores; point `JARVIS_HOME` at a network/removable
volume and yank it mid-write; boot with the system locale set to `ro_RO.UTF-8` and confirm no
date/decimal parsing changes any reported number; and start `START.bat` twice in a row (the browser
poller of the second instance must not open a tab pointed at the first).

---

## 01.Z Coverage ledger

| Group | Cases | Needs | Auto-covered | Notes |
|---|---|---|---|---|
| 01.1 Windows install | 14 (ENV-001..014) | 🖥 clean Win 11 VM, winget, ⏱ | 1 partial (`test_compatibility.py` presence checks) | No test executes any installer script — the whole group is real-world only |
| 01.2 Linux/macOS install | 10 (ENV-015..024) | shell, Node 22 for WorldView | 3 (`test_o26_p2_install_smoke.py`, `test_o26_f6_boot_guards.py`, `test_compatibility.py`) | `install.sh --dev` path untested offline |
| 01.3 Container & service | 7 (ENV-025..031) | 🔑 Docker, 🖥 for the exe build | 2 partial (`test_release_build.py`, `test_user_home_packaging.py`) | Compose posture (0.0.0.0 bind) is a documented residual |
| 01.4 Environment matrix | 17 (ENV-032..048) + a 40-row table | 🌐 for ENV-039 | 8 (`test_o26_p2_env_config.py`, `test_o26_f6_boot_guards.py`, `test_user_home_packaging.py`, `test_cdx12_hardened_profile.py`) | ENV-039 (`.env` vs import-time tokens) has no coverage |
| 01.5 Model backends | 15 (ENV-049..060, ENV-143..145) | 🤖🖥 LM Studio + Ollama + cloud keys | 7 (`test_local_model_status.py`, `test_llm_status_api.py`, `test_llm_control_status_model.py`, `frontend .../local-models.test.tsx`) | Residency-vs-catalog logic is well covered offline; the real probes are not. **ENV-143 is regression R4** and the only RO+EN chat case in this section |
| 01.6 Boot & readiness | 16 (ENV-061..076) | 🖥 for GPU telemetry, 🌐 for ENV-069 | 9 (`test_h2311_operability.py` heavily, `test_hud_security_headers.py`, `test_rate_limit_hf2.py`) | ENV-063 (`_sys_info` on real hardware) has **no** offline equivalent and is the anti-fabrication anchor |
| 01.7 Posture & watcher | 15 (ENV-077..085, ENV-146..149) | admin token, ⏱ 35 s | 9 (`test_o26_p2_product_posture.py`, `test_admin_settings_mutations.py`, `test_o26_f2_settings_seed.py`, `test_cdx12_hardened_profile.py`, `test_settings_integrity.py`, `test_settings_secret_encryption.py`) | The 30 s watcher tick itself is timing-dependent, manual only. ENV-146 is the declared-vs-runtime cross-check |
| 01.8 Build integrity | 12 (ENV-086..097) | Node 22, ⏱ long suite, persistent 3.12 shell | 5 + 2 CI lanes (`test_status_sync.py`, `test_release_gate.py`, `test_route_parity_guard.py`; CI `hud-v2-build`, `frontend`) | The counts themselves are the test |
| 01.9 Data lifecycle | 15 (ENV-098..112) | admin token, scratch `JARVIS_HOME`, ⏱ for upgrade | 9 (`test_backup.py`, `test_data_export.py`, `test_data_purge*.py`, `test_db_migrations.py`, `test_export_route_h23_9.py`) | `UPDATE.bat` itself: ❌ |
| 01.10 Degraded boots & first run | 16 (ENV-113..124, ENV-150..152) | 🤖 (absence of), 👁, 🌐, ♿ | 6 partial | ENV-120/121/122 (PyYAML, Python 3.10, port in use) and ENV-152 (♿) all ❌ |
| 01.Y Adversarial | 24 (ENV-125..142, ENV-153..158) | 🌐 second LAN device, ⏱ | 13 (`test_admin_guard_hf7.py`, `test_user_guard_hf1.py`, `test_rate_limit_hf2.py`, `test_token_lifecycle.py`, `test_backup.py`, `test_db_migrations.py`, `test_onboarding_wizard.py`) | HUD race/refresh (ENV-138/139), read-only root (ENV-156) and split-brain (ENV-157) ❌ |
| **Total** | **158 cases** | 🖥 34 · 🤖 21 · 👁 18 · 🌐 8 · 🔑 5 · ⏱ 12 · ♿ 1 | ~72 with some offline coverage · ~86 real-world only | Broader accessibility coverage belongs to the HUD sections; only the first-run gate is graded here |

---

## Open gaps found while writing

1. **`.env` cannot supply `JARVIS_ADMIN_TOKEN` / `JARVIS_USER_TOKEN` / `DEV_MODE`.** `ADMIN_TOKEN`
   (`agents/web.py:62`), `USER_TOKEN` (`agents/web.py:147`), `RATE_LIMIT_PER_MIN`
   (`agents/web.py:218`) and `DEV_MODE` (`agents/web.py:48`) are evaluated at **module import**, while
   `load_dotenv` runs much later inside `PluginManager.build()`
   (`agents/core/plugin_manager.py:71-80`, called from `load_agents()` in the app lifespan). A token
   written only into `.env` therefore never activates — the hub silently stays in the localhost-only
   dev posture. `docs/COWORK_QA_RUNBOOK.md` §8 explicitly advises "pre-set the keys/tokens in `.env`".
   Observation only; ENV-039 measures it.
2. **`settings_db.DB_PATH` is bound at import** (`agents/core/settings_db.py:30` —
   `DB_PATH = data_path("settings.db")`). Combined with (1), a `JARVIS_HOME` set only in `.env` cannot
   relocate `settings.db`, so state can split across two roots. Worth an explicit test on the owner's
   box before trusting any `.env`-driven relocation.
3. **No installer enforces the declared Python 3.12 floor.** `docs/COMPATIBILITY.md` calls 3.12 a
   *hard* floor, but `install.sh:13-17` only checks that `python3` exists and then prints the version;
   `install.ps1:22-28` does the same; `INSTALL.bat:28-48` installs Python 3.12 via winget **only when
   no python is on PATH at all** — an existing 3.10/3.11 is used as-is. `requirements-beta.txt` even
   carries a `python_version < "3.12"` numpy marker, so a 3.11 install partially succeeds. Run 1 hit
   exactly this (its shell had 3.10 and could not run the suite).
4. **Three different backend test counts are in circulation.** `install.sh:53-54` says "The full
   ~3,800-test offline suite runs with `--dev`"; `docs/MANUAL_TESTING.md`'s preamble says **5,406**
   while its own §J and `project-status.json` → `tests.backend` (the generated,
   `status_sync.py`-owned figure) both moved on. Cosmetic doc drift, but it is exactly the kind of
   number a tester compares against and then files as a finding. ENV-086 pins the JSON as authority.
5. **`docker-compose.yml` requires a `.env` file to exist** (`env_file: - .env`) yet nothing in the
   repo ships one and `MANUAL_TESTING.md` §A does not mention copying `.env.example` first —
   `docker compose up` on a fresh clone fails before any container starts.
6. **The compose container binds `0.0.0.0` through a raw uvicorn CLI flag**, which is precisely the
   residual `agents/core/boot_guards.py:12-15` documents as invisible to the guard. The container is
   therefore network-exposed with no bind-guard warning, and (per gap 1) tokens supplied only via
   `.env` inside the image would not activate — though compose's `env_file` does inject them as real
   env vars, so ENV-027 should pass while ENV-039 fails.
7. **`INSTALL.bat` clones from a hardcoded repo URL** (`INSTALL.bat:21`,
   `https://github.com/andrei649/jarvis-hub.git`). If the repo is renamed as part of the Nerva rename
   (CLAUDE.md notes the rename is an owner task), the one-click Windows installer breaks silently.
8. **`update.json` in the repo root is not an updater manifest.** It is leftover output from
   `scripts/update_thirdparty.py` (see `.github/workflows/thirdparty-autoupdate.yml:83`) and names
   `codebase-memory-mcp`. A tester could easily mistake it for Nerva's own update descriptor; no test
   asserts it is not one.
9. **`/api/cognition` synthesizes a placeholder from `INTENT_RULES` when nothing has been routed yet**
   (`agents/core/routers/ops.py:117-138`). It is labelled `source: "standby"` with `confidence: 1.0`,
   which is *almost* honest — but a confidence of 1.0 on a decision that never happened is exactly the
   shape of value a HUD panel might render as a real signal. ENV-084 checks the label; a reviewer
   should decide whether `confidence: 1.0` on standby is acceptable.
10. **The rotating file log is outside the retention sweep.** `agents/core/log.py:36-45` notes that
    root-logger records can include request-derived content (e.g. a voice-transcript preview) and that
    this file is **not** covered by the H23.10 retention sweep, bounded only by
    `max_bytes × backups`. With an in-repo data root (the default) the log lands inside the git
    checkout. Worth an owner decision, not a test. **Decided 2026-09-01 (owner):** accept the bound
    (opt-in/default-off, bounded only by `max_bytes × backups`; any box that turns it on sets
    `JARVIS_HOME` off the checkout and uses `WARNING` level); no sweep coverage or path change.
11. **`docs/GPU_RUNBOOK.md` tells the owner to set two env vars that are never read.** Its H12.14 step 3
    says: "replace the Howard tier: set `HOWARD_OLLAMA_MODEL` to your model (served at
    `HOWARD_OLLAMA_URL`, default `http://localhost:11434`)". Both are plain module constants
    (`agents/core/llm/model_config.py:19-20`) with **no** `os.environ` / `env_str` read anywhere in the
    tree (grep-confirmed across `agents/`, `scripts/`, `serve.py`). Following the runbook silently does
    nothing; the `default_model` admin setting named in the same paragraph does work. Doc bug only.
12. **README and `install.ps1` still describe the companion stacks as opt-OUT.** `README.md` §Run calls
    WorldView "auto-started by START.bat/start.sh" and says the Signal Layer is opted out with
    `JARVIS_SIGNAL_LAYER=0`; `install.ps1:84` prints `JARVIS only: set JARVIS_WORLDVIEW=0 then
    START.bat`. Both launchers are opt-**in** (`START.bat:40,45` and `start.sh:10,28` test for `=1`).
    A tester following the README will hunt for a stack that was never going to start. Cosmetic, but it
    cost time to establish which was true.
13. **`GET /api/status` reports a registry count computed at import; `/readyz` reports the live roster.**
    `agents/core/routers/status.py:97-98` returns `AGENT_COUNT`, which
    `agents/__init__.py:9-30` computes from `agents/_system/agents.yaml` **at import time** with a
    hardcoded fallback of 17 on any exception. `routers/ops.py:61-62` counts `orch.agents`. If an agent
    fails to load — or if the YAML is unreadable and the fallback fires — `/api/status` still answers
    `agents: 17` while the live roster is smaller. Not fabrication in the SOUL sense, but it is a
    surface that can read healthier than reality, and `MANUAL_TESTING.md` §A uses `/status` version +
    agents as its boot proof. ENV-025/ENV-065 cross-check them for exactly this reason.
14. **`OWNER_TEST_DRIVE.md` Session 0 names the wrong cognition route.** It says "`GET /api/cognition`
    shows enabled". That route returns the last routing/cognition *context* and has no `enabled` field
    (`agents/core/routers/ops.py:113-139`); the flag lives on `GET /api/cognition/status`
    (`agents/core/cognition/api.py:28-34`). `COWORK_QA_RUNBOOK.md` §2 repeats the same `curl`. Anyone
    verifying the posture flip by that route gets a routing blob and no answer. ENV-077/ENV-146 use the
    correct one.
15. **Could not verify — `/api/health/components` output shape with services down.** The route exists
    (`routers/status.py:51-59`, tier **open**) with a `registry unavailable` fallback, but no dedicated
    test file was found and the component keys/values could not be enumerated from source alone.
    ENV-074/ENV-123 are written to **record** the output rather than assert an exact shape.
16. **Could not verify — request-body size limits.** ENV-132 has no concrete expected value: no
    body-size cap was found on the admin-settings path in `agents/web.py` (the chat path is bounded by
    `ChatRequest.message` `max_length=4096` plus a non-blank validator). A tester must measure and report
    whether 10 MB is rejected, buffered, or fatal.
17. **Could not verify — "port already in use" ergonomics.** `serve.py` has friendly handling for missing
    dependencies (16-27) and for bind posture (`boot_guards`), but nothing for `EADDRINUSE`; the owner
    gets a raw uvicorn traceback. ENV-122 records it as a message-quality finding rather than asserting
    an expected string.
18. **Could not verify on this machine (all deferred to the owner's box):** anything requiring
    Windows (`INSTALL.bat`, `START.bat`, `UPDATE.bat`, `install.ps1`, `smoke.ps1`,
    `deploy/windows/install-service.ps1`), an NVIDIA GPU (`_sys_info`'s `nvidia-smi` branch), real LM
    Studio/Ollama probes, `docker compose` behaviour, the PyInstaller build in `packaging/nerva.spec`
    + `scripts/build_exe.py`, and the actual test counts (the counts were read from
    `project-status.json`, not re-collected here — the authoring environment is below the project's own
    Python floor, which is itself why ENV-086 insists on a persistent 3.12 shell).
19. **Line numbers move.** Every `file:line` pointer in this section was read at the working-tree
    revision it was written against. Re-grep the quoted symbol, JSON key or label text before relying
    on a number — the identifiers and literal strings are the stable part, the line numbers are not.
