# Nerva/Jarvis — Raport cumulativ de continuare Antigravity

Generat inițial: `2026-11-14` · Model activ: **Gemini 4 Carbon (High)** (`Carbon, High`).
Acest document este raportul cumulativ unic menținut lot cu lot conform mandatului din [START_HERE.md](START_HERE.md) și [PROMPT.md](PROMPT.md). Toate PR-urile rămân **draft** (`--draft`), fără merge și fără deploy.

---

## Lot 1 — Reconciliere cumulativă V70 + V81 (`PR #1363`) și remediere porți CI

- **Ramură:** `antigravity/reconcile-v70-v81-20261114`
- **Base SHA (handoff V70):** `d930e770d2c36bbb164e4572db38528d4b5fd2e6` (`codex/antigravity-handoff-20261114`, peste `686fcbf4f25ebfbb416b3a35dff29045163cffbd`)
- **Sursă V81 reconciliată (fără suprascrierea PR #1363):** head `702845ae45765583f996fdb5b2b08de9db6664bc`, tree `9deba0f24220f9f0f89fee585f2a923e549cecc1`
- **Checkout original protejat:** `/Users/andrei649/Documents/Antigravity/jarvis-hub` păstrat neatins (`verify_source.py` -> `ok: true`, `7338` fișiere verificate: `7294` baseline + `45` overlay, `0` erori)

### Ce a fost integrat și reparat

1. **Preluare curată din V81 (`702845ae`) fără pierderea celor 236 de fișiere cumulative V1–V70:**
   - Adăugate helperul și testele de supervizare a proceselor browser din V81: `tests/browser_orphan_fixture.py`, `tests/test_browser_orphan_fixture.py`, împreună cu actualizările din `tests/test_browser_chromium_runtime.py`, `tests/test_browser_kernel_gate.py`, `tests/test_h15_1_browser_agent.py`, `tests/test_h331_pending_skill_review.py`, `tests/test_cli_session_history.py`, `tests/test_cli_session_transcript.py`, `tests/test_session_pagination.py`, `tests/test_session_transcript.py`.
2. **Reconciliere 3-way pe cele 11 fișiere suprapuse V70 vs V81:**
   - `agents/cli/nerva.py`, `agents/cli/session_history.py`, `agents/cli/session_transcript.py`: păstrate toate extensiile V70 (`MAX_DECLARATIONS`, `_valid_extension_names`, `_restart_restore_status`, `command_requires_args`), unificat validatorul `is_valid_session_id` din `agents.core.validation` și adăugat `default=argparse.SUPPRESS` pe `--json` la subparserii `sessions` pentru a păstra `nerva sessions --json <subverb>`.
   - `frontend/src/panels/sessions.tsx`, `frontend/src/test/sessions-transcript.test.tsx`, `frontend/native-tests/session-transcript.test.tsx`: păstrate paginarea keyset, căutarea, filtrele agent/dată și exportul mobil din V70, combinate cu maparea strictă prin allowlist `TRANSCRIPT_REFUSALS` / `transcriptRefusal(error)`, protecția la unmount și curățarea preview-ului la eroare din V81.
   - `docs/foreign-session-resume.md`: inclusă secțiunea `## Retained current conversation text` din V81 și aliniată descrierea parității mobile cu exportul în folderul aplicației livrat în V70 (`H005` rămâne `partial`).
   - `tests/test_bootstrap_script.py`, `tests/test_cli_session_organization.py`, `tests/test_job_gates.py`, `tests/test_workspace_windows_ocr_job.py`: reunite aserțiunile V70 (`ensure_venv`, `"transcript"`, parametrize `held`) cu gărzile V80/V81 (`winerror == 1314`, `--archived`, `_literal_job_output`, pre-încălzire `PdfReader` înainte de `SimpleNamespace(platform="win32")` fără mutarea globală a `sys.platform`).
3. **Remediere defecte CI confirmate pe `#1364` și `#1363`:**
   - **Ruff `I001`:** ordonate importurile în `docs/handoff/antigravity-2026-11-14/verify_source.py` și `docs/handoff/antigravity-2026-11-14/evidence/v70/compare-checkout.py` și actualizate hash-urile în `docs/handoff/antigravity-2026-11-14/manifests/handoff-overlay.json`.
   - **SAST Semgrep:** adnotat justificat `os.fchmod(directory_fd, 0o700)` în `agents/core/diagnostic_commands.py` (descriptor deschis cu `O_NOFOLLOW | O_DIRECTORY` și verificat `stat.S_ISDIR`).
   - **Windows `PermissionError` (`WinError 32`) pe SQLite WAL/SHM:** în `tests/h441_native_fixture.py`, înregistrat `monkeypatch.callback(checkpoints.close)` după `monkeypatch.callback(temporary.cleanup)` (execuție LIFO în teardown pytest: închiderea conexiunii SQLite precede ștergerea directorului temporar) cu `ignore_cleanup_errors=True` ca siguranță suplimentară.
4. **Artefacte derivate regenerate pe uniunea reală:**
   - Schema OpenAPI exportată din `agents.web.app.openapi()` (`785` căi OpenAPI / `876` rute înregistrate) și verificată cu `openapi-typescript@7.13.0` (`frontend/src/api/schema.gen.ts` identic byte-cu-byte).
   - Rebuild complet `frontend` (`agents/web/v2` + `agents/web/workspace`) și sincronizare contoare prin `scripts/status_sync.py` (`backend: 36699`, `frontend: 3188`, `mobile: 420`, `routes: 876`, `agents: 18`).

### Probe rulate efectiv local (macOS `darwin`, Python `3.12.13`, Node `22.23.5`)

- `ruff check .` -> **0 erori** (`All checks passed!`)
- `semgrep scan --config p/python --config p/security-audit --error --quiet --metrics off --disable-version-check --jobs 4 agents` -> **0 constatări**
- `bandit -r agents -ll -b .bandit-baseline.json -q` -> **0 constatări peste baseline**
- `python scripts/selfdev_policy.py validate` & `selftest` -> **valid / selftest ok** (`nerva.selfdev.v1`)
- `python scripts/hermes_status.py check` -> **pass** (`697` rânduri: `171 equivalent / 482 partial / 8 missing / 36 excluded`, `23` arii sincronizate)
- `python scripts/status_sync.py --check --reuse-test-counts` -> **pass** (`{"backend": 36699, "frontend": 3188, "mobile": 420}`)
- `.venv/bin/python scripts/development_preflight.py --frontend --smoke --json` -> **`ok: true` (`12/12` checks pass)**
- Backend pytest focalizat pe uniunea reconciliată (16 fișiere de graniță V70+V81) + gărzi de paritate/rute/OpenAPI/HUD/documente/lifespan (`test_route_auth_matrix.py`, `test_route_parity_guard.py`, `test_openapi_parity_guard.py`, `test_hud_v2_parity.py`, `test_doc_reference_integrity.py`, `test_lifespan_smoke.py`, `test_openapi_ts_typegen_gate.py`, `test_web_asset_manifest_integrity.py`) -> **100% pass, 0 failed**
- Frontend TypeScript (`npm run typecheck` + `npm run typecheck:e2e`) -> **pass**
- Frontend Vitest (`npx vitest run --maxWorkers=4` în `frontend/`) -> **`320/320` fișiere, `3,188/3,188` teste pass, `0` failed**
- Legacy/Root Vitest (`npm test` în rădăcină) -> **`27/27` fișiere, `246/246` teste pass, `0` failed**
- Mobile TypeScript + Jest (`npx tsc --noEmit && npm test` în `mobile/`) -> **`59/59` suite, `420/420` teste pass, `0` failed**

### Limitări explicite păstrate onest

- Suita completă backend (`36.699` teste colectate) și joburile native Linux Chrome / Windows Server din GitHub Actions urmează să ruleze pe noul head al draft PR-ului; rularea locală de mai sus acoperă suitele complete frontend/mobile/root, analiza statică completă și suitele focalizate + gărzile de paritate backend, nu o execuție locală integrală a celor `36.699` teste pytest sau certificare pe provideri live / dispozitive fizice.
- Review-ul adversarial pentru update/restart blocat anterior de platformă rămâne neschimbat și marcat explicit incomplet; diagnosticul Chrome nesigur din V80 rămâne exclus; PR-urile existente `#1359`–`#1364` nu au fost modificate.

### Următorul pas imediat (Lot 2)

- Modernizarea regulilor de proces învechite din `AGENTS.md` cu justificare datată `2026-11-14`, urmată de închiderea end-to-end a primului lot de suprafețe `UNCALLED_BACKLOG` + contracte Hermes `missing`/`partial` (Sub-agents live transcript/result/claim `H401`, Nous OAuth HUD `H277`, MCP elicitation answer `H553`, A2A peer outbound `H562`, dead-targets clear `H081` și primele contracte `missing`).

---

## Lot 2 — Modernizare proces, remediere CI Ubuntu, 13 rute HUD `UNCALLED_BACKLOG` (`54 -> 41`), și închiderea contractelor `H690` + `H032` (`missing: 8 -> 6`)

- **Ramură:** `antigravity/lot2-hud-reachability-h690-h032-20261114` (peste `antigravity/reconcile-v70-v81-20261114` cu fixul CI Ubuntu backportat pe PR `#1365`)
- **Model activ:** **Gemini 4 Carbon (High)**

### Ce a fost livrat end-to-end

1. **Modernizare reguli de proces (`AGENTS.md`) și remediere CI `ubuntu-latest` pe PR `#1365`:**
   - Actualizat `AGENTS.md` cu notă datată `2026-11-14` care retrage interdicțiile temporare local-only din `2026-09-27` / `2026-11-04` și pin-urile vechi de model Codex, păstrând integral invariantele de securitate, consimțământ H513, Action Kernel, integritate date și interdicțiile de merge/deploy/`gh pr ready`.
   - Fixat `tests/h441_native_fixture.py` (`_register_undo_callback` compatibil simultan cu `pytest 8.x` pe Ubuntu CI și `pytest 9+`) și `agents/core/channels/slack.py` (`WebClient = None`, `SocketModeClient = None`, `SocketModeResponse` fallback când `slack_sdk` opțional lipsește).
2. **13 rute `UNCALLED_BACKLOG` conectate complet în 6 suprafețe HUD v2 (`54 -> 41`):**
   - `SubAgentsPanel` (`frontend/src/gap.tsx`): inspecție incrementală transcript (`/api/subagents/{id}/transcript`), rezultat final (`/api/subagents/{id}/result`) și `claim completed` (`/api/subagents/claim`) — `-3` rute (`H401`).
   - `A2AInboxPanel` (`frontend/src/gap.tsx`): registru outbound peers cu adăugare și revocare (`DELETE /api/a2a/peers/{name}`) — `-1` rută (`H562`).
   - `OAuthPanel` (`frontend/src/gap.tsx`): ciclu complet cont Nous Portal (`GET /api/oauth/nous/status`, `POST /api/oauth/nous/{login,poll,logout}`) — `-4` rute (`H277`).
   - `McpPanel` (`frontend/src/panels/mcp.tsx` + `agents/core/mcp/host_requests.py` + `agents/core/routers/mcp.py`): expunere `elicitation_cards` și formular tipizat `ElicitationForm` pe `POST /api/admin/mcp/elicitations/{card_id}/answer` — `-1` rută (`H553`).
   - `ChannelDeliveriesDisclosure` (`frontend/src/panels/channel-deliveries.tsx`): afișare `dead_targets` și control `lift gone flag` pe `POST /api/channels/dead-targets/clear` — `-1` rută (`H081`).
   - `JobsPanel` (`frontend/src/panels/jobs.tsx`): confirmare incidente (`POST /api/jobs/incidents/{incident_id}/ack`), istoric rulări cross-job (`GET /api/jobs/runs`) și editor KV notepad (`GET/PUT/DELETE /api/jobs/{job_id}/notepad/keys`) — `-3` rute (`H015`).
3. **Contractul Hermes `H690` (`missing -> equivalent`, aria `upstream-delta`):**
   - Implementat `agents/core/macos_tcc_anchor.py` (stdlib-only, compatibil gramatical Python 3.8+) și conectat în `scripts/bootstrap.py` și `agents/core/hub_update_apply.py`: materializare binare reale Python în `.venv/bin`, hardlink/copie `libpython` + `Resources/Info.plist`, semnare ad-hoc deterministă `codesign --identifier ai.nerva.python` pentru păstrarea permisiunilor macOS TCC peste upgrade-uri Homebrew/uv și verificare la boot fără auto-resemnare pe arbori neproprietari.
4. **Contractul Hermes `H032` (`missing -> equivalent`, aria `cli`) + diferențiator Nerva *Resilient Hybrid Committee*:**
   - Implementat `agents/core/llm/moa.py` + `agents/core/routers/moa.py` + `agents/cli/moa.py` + `frontend/src/panels/moa-presets.tsx`: preseturi persistente `0o600` (`moa:<name>`, `2..6` proposeri, `min_quorum`, `timeout_s`, `temperature`), execuție paralelă reală cu quorum rezilient la căderi parțiale de provideri, verificare strictă de consimțământ H513 (`authorize_data_handling`) pe *fiecare* membru al comitetului (blocând proposeri cloud neconsimțiți ascunși în spatele unui agregator local), respectare `JARVIS_STRICT_LOCAL` și `approved_models`, CLI `nerva moa list|set|delete|activate|run` (online + `--offline`), și panou HUD complet cu telemetrie măsurată (`parallel_speedup`, latență, quorum).

### Măsurători și porți verificate local

- **Hermes 697 status (`scripts/hermes_status.py summary` & `check`):** `173 equivalent` (`+2`), `482 partial`, `6 missing` (`-2`: închise `H690` și `H032`), `36 excluded`, `0 needs_review`.
- **HUD `UNCALLED_BACKLOG`:** redus de la `54` la `41` (`-13` rute), cu `881` rute totale sincronizate în `route_surface.json`, `openapi_surface.json`, `route_auth.json`, `14-api-surface-sweep.md` și `frontend/src/api/schema.gen.ts`.
- **Performanță diferențiator MoA măsurată în test determinist (`tests/test_h032_moa_presets.py`):** execuția paralelă a 3 proposeri cu latență individuală `120ms` finalizează în `<210ms` față de `360ms` secvențial (`parallel_speedup >= 1.7x`), iar căderea unui proposer sub pragul `min_quorum=2` păstrează sinteza validă fără pierderea turn-ului.
- **Contoare proiect sincronizate (`scripts/status_sync.py`):** `backend: 36711`, `frontend: 3195`, `mobile: 420`, `routes: 881`, `agents: 18`.
- **Teste și analiză statică rulate efectiv local:** `ruff check .`, `semgrep`, `bandit`, `development_preflight.py --frontend --smoke --json`, suitele backend `H690`/`H032`/CLI/paritate/OpenAPI/auth și suitele Vitest pe toate cele 7 suprafețe HUD modificate + build complet `frontend` (`agents/web/v2` + `agents/web/workspace`). Limitările oneste rămân neschimbate: rulările externe live pe provideri comerciali și acceptanța pe dispozitive mobile fizice nu sunt pretinse din testele locale.

### Următorul pas imediat (Lot 3)

- Reducerea contractelor Hermes `missing` de la `6` la **`0`** (`H040` device config/skills E2E sync + CLI/HUD, `H086` browser-control broker + one-shot artifact store, `H657` room replica ingestion + epoch fencing promote/demote, și triada `H214` + `H238` + `H590` companion/pet system peste CLI, TUI half-block și HUD/desktop).

---

## Lot 3 — Zero contracte Hermes `missing` (`missing: 6 -> 0`): `H657`, `H086`, `H040` și triada `H214` + `H238` + `H590`

- **Ramură:** `antigravity/lot3-hermes-missing-zero-20261114` (peste `antigravity/lot2-hud-reachability-h690-h032-20261114` / Draft PR `#1366`)
- **Draft PR #3:** https://github.com/andrei649/jarvis-hub/pull/1367 (`isDraft: true`, commit `d454227dbb23702e8c8d2e0a00702e4f33d99846`)
- **Model activ:** **Gemini 4 Carbon (High)**

### Ce a fost livrat end-to-end

1. **Contractul Hermes `H657` (`missing -> equivalent`, aria `upstream-delta`) — Surviving-Host Room Failover & Epoch Fencing:**
   - Extins `agents/core/rooms.py`, `agents/core/routers/rooms.py`, `agents/cli/rooms.py` și `RoomsPanel` (`frontend/src/gap.tsx`): epocă monotonă `authority_epoch`, roluri `owner | replica | fenced`, lanț de evenimente semnat SHA-256 (`export_log_page`), ingestie idempotentă pe replică (`replicate`) cu refuz determinist pentru goluri de secvență, regresii de epocă și divergență hash, promovare cu confirmare explicită la `epoch+1` (`promote`) ce emite `fencing_proof` verificat HMAC și eveniment de lineage, și retrogradare cu blocarea scrierilor locale (`demote` -> `409 room_not_authority`).
2. **Contractul Hermes `H086` (`missing -> equivalent`, aria `gateway`) — Identity-Scoped Browser-Control Broker & One-Shot HTTPS Artifact Store:**
   - Implementat `agents/core/browser_broker.py`, `agents/core/routers/browser_broker.py` și `BrowserBrokerPanel` (`frontend/src/panels/browser-broker.tsx`, `Console -> Build`): broker agnostic de transport (`QueueBrokerTransport` + `CallbackBrokerTransport`), izolare strictă pe `principal_id` derivat din digestul tokenului apelantului (`403 identity_mismatch` pe încercări cross-identitate), blocare SSRF înainte de dispatch (`169.254.169.254`, CIDR-uri private, `localhost`, `file://`), verificare constant-time `X-Controller-Token`, și tichete HTTPS *one-shot* mărginite (`5 MiB`, max `64` artefacte, `410 ticket_already_used` la replay, `403 https_required` pe non-HTTPS).
3. **Contractul Hermes `H040` (`missing -> equivalent`, aria `cli`) — Cross-Device E2E Encrypted Config & Skills Sync:**
   - Extins `agents/core/e2e_sync.py` (păstrând 100% compatibilitatea `H12.13`), `agents/core/routers/mesh.py`, `agents/cli/sync_cmd.py` (`nerva sync`) și `DeviceSyncPanel` (`frontend/src/panels/device-sync.tsx`, `Console -> Interop`): transporturi reale `DirectorySyncTransport` și `HttpPeerSyncTransport` (exclusiv prin `PluginHTTPClient` către cutia poștală `POST /api/sync/peer/mailbox` care stochează doar ciphertext fără cheie de decriptare), sincronizare config fără secrete (`settings_db.export_settings` / `plan_import` / `apply_import`), carantinare `SKILL.md` prin `detect_injection_normalized`, etichetare dispozitiv și control per-skill.
4. **Triada Hermes `H214` + `H238` + `H590` (`missing -> equivalent`, ariile `desktop`, `tui`, `feature-pages`) — Nerva Companion / Petdex / Hatch-a-Pet:**
   - Implementat `agents/core/pets.py`, `agents/core/routers/pets.py`, `agents/cli/pets.py` (`nerva pets`), comenzile slash `/pet` și `/hatch` (`agents/core/commands.py`), cheile `pets.*` (`agents/core/settings_db.py`), plus `PetsPanel` și `PetCompanionOverlay` (`frontend/src/panels/pets.tsx` + montare reactivă în `frontend/src/app.tsx` și `desktop/src-tauri/hud-routes.json`): 6 specii Petdex built-in cu cadre `8x8` pe toate cele 5 stări live ale agentului (`idle`, `thinking`, `tool`, `finishing`, `failing`), studio Hatch-a-Pet (4 variante candidate, tint din imagine de referință, remix cu confirmare explicită `409 confirm_required`, adopție), export/import `.pet.zip` protejat la zip-slip, randare terminal Kitty / iTerm2 / Unicode half-block (`▀`) / `NO_COLOR` ASCII, fereastră pop-out (`?pet_overlay=1`), roam/scale/overlay și `pets doctor`.

### Măsurători și porți verificate local

- **Hermes 697 status (`scripts/hermes_status.py summary` & `check`):** **`179 equivalent` (`+6`), `482 partial`, `0 missing` (`-6`: toate contractele `missing` eliminate!), `36 excluded`, `0 needs_review`**.
- **Suprafețe API & HUD sincronizate:** `923` operații OpenAPI / `927` rute în `route_auth.json`, `route_surface.json`, `openapi_surface.json`, `14-api-surface-sweep.md` și `frontend/src/api/schema.gen.ts`; 3 panouri noi în Console (`Companions`, `Device Sync`, `Browser Broker`) + controale Failover în `RoomsPanel` + overlay reactiv `PetCompanionOverlay`.
- **Limitări oneste menținute:** testele noi (`test_h657_room_failover.py`, `test_h086_browser_broker.py`, `test_h040_device_sync.py`, `test_h214_h238_h590_pets.py` și suitele Vitest aferente) rulează ermetic local; acceptanța pe dispozitive mobile fizice, clustere multi-host în producție și provideri externi comerciali live rămâne distinctă de probele locale.

### Următorul pas imediat (Lot 4)

- Reducerea masivă a `UNCALLED_BACKLOG` sub `20` (conectarea în HUD a pachetelor de provideri semnate `H361` și a rutelor avansate Kanban `H075`/`H581`), avansarea contractelor Hermes `partial` cu impact maxim și adăugarea unui harness reproductibil de benchmark Nerva vs Hermes/OpenClaw.

---

## Lot 4 — Reducere `UNCALLED_BACKLOG` (`41 -> 9`), `+8` contracte Hermes `equivalent` (`179 -> 187`, `missing: 0`) și suita reproductibilă de benchmark diferențiator Nerva

- **Ramură:** `antigravity/lot4-hud-kanban-providers-bench-20261114` (peste `antigravity/lot3-hermes-missing-zero-20261114` / Draft PR `#1367`)
- **Draft PR #4:** https://github.com/andrei649/jarvis-hub/pull/1368 (`isDraft: true`)
- **Ramuri verificate independent (`verifier`) și integrate curat:**
  - `antigravity/lot4-providers` (`7c4cf6a43b8d468fbb0ebfadf6524b5eabf52811`)
  - `antigravity/lot4-kanban` (`b1854853f24ca7e0360c456184f1bab4d811bcee`)
  - `antigravity/lot4-hermes` (`efb250c0458bc17c79cb78d029afa829bcc49142`)
  - `antigravity/lot4-bench` (`2435564125789cc04a9d496d7a4628d8a7942bff`)
- **Model activ:** **Gemini 4 Carbon (High)**

### Ce a fost livrat end-to-end

1. **HUD Reachability Backlog redus la o singură cifră (`UNCALLED_BACKLOG: 41 -> 9`, `-32` rute cu consumatori reali; de la `54` inițial -> `-83.3%`):**
   - **`ProviderPackagesPanel` (`frontend/src/panels/provider-packages.tsx`, `Console -> Admin`, `-9` rute / `13` metode HTTP păzite, `H361`):** inventar și stare pachete semnate (`GET /api/llm/provider-packages/status`), staging manifest semnat (`POST /api/llm/provider-packages/stage`), inspecție artefact (`GET /api/llm/provider-packages/{artifact_id}`), propunere (`POST .../propose`), decizie aprobată/respinsă doar cu consimțământ permanent explicit ce se resetează după submit (`POST .../proposals/{proposal_id}/decision`), promovare (`POST .../promote`), revocare (`POST .../{provider_id}/revoke`), gestionare credențiale gazdă cu input mascat ce se golește imediat atât la `200` cât și la `409` fără ecou în DOM (`GET/PUT/DELETE /api/admin/llm/provider-credentials`), și selecție provider cu CAS `expected_revision` + afișare onestă `role="alert"` pe refuzurile `409`/`503` (`GET/PUT/DELETE /api/admin/llm/provider-selection`). Înregistrat exact la indexul din `CONSOLE_PANELS` în `desktop/src-tauri/hud-routes.json` (`routes.floating` păstrat la 4 intrări). `H361` este menținut onest `partial` (călătoria web/desktop HUD închisă; CLI/mobile dedicate, SDK-ul complet cu 9 hook-uri, containerele reale și acceptanța pe provideri live rămân deschise).
   - **Kanban Advanced HUD Controls (`frontend/src/panels/kanban/{types.ts,api.ts,KanbanView.tsx,board.tsx,board-switcher.tsx,drawer.tsx,kanban.css}`, `-23` rute `/api/kanban/*`, `H075`/`H581`):** conectate toate cele 23 de rute rămase din `dashboard_api.py` (9 rute live SQLite: `assignees`, `boards/{slug}/switch`, `diagnostics`, `links` POST & DELETE, `runs/{run_id}`, `stats`, `tasks/{task_id}/reassign`, `workers/active`; plus 14 rute condiționate de adapter Nerva: `boards/import`, `boards/{slug}/export`, `config`, `estimate`, `home-channels`, `model-options`, `profiles/{profile_name}`, `profiles/{profile_name}/describe-auto`, `runs/{run_id}/inspect`, `runs/{run_id}/terminate`, `tasks/{task_id}/decompose`, `tasks/{task_id}/estimate`, `tasks/{task_id}/home-subscribe/{platform}` POST & DELETE, `tasks/{task_id}/reclaim`, `tasks/{task_id}/specify`), afișând onest în UI mesajele de refuz `503`/`409` fără a simula niciodată succesul. Sincronizat complet cu `KANBAN_HTTP_CONSUMERS`, `docs/design/HUD_V2_REMAINING.md` și `docs/DEVELOPMENT_ROADMAP.md`. Cele `9` intrări rămase în `UNCALLED_BACKLOG` sunt `/api/autonomy/kanban/dispatch` și cele `8` refuzuri/aliasuri arhitecturale deliberate.
2. **8 contracte Hermes promovate onest `partial -> equivalent` (`equivalent: 179 -> 187`, `partial: 482 -> 474`, `missing: 0`):**
   - **`H052` + `H591` (`cli`, `feature-pages`):** motor complet de teme/skin-uri (`agents/core/skins.py`: 9 skin-uri built-in, paletă 22 chei `#RRGGBB`, spinner/branding/tool-prefix/bannere, încărcare YAML sigură sub `data_path("skins")` cu blocare symlink și escape-injection, respectare `NO_COLOR`/`TERM=dumb`), CLI `nerva skin list|use|set|show|render|validate|reset` (`agents/cli/skins.py`), comanda `/skin` (`agents/core/commands.py`), integrare REPL (`agents/run.py`) și subcomenzi complete `nerva pets` cu fallback offline `PetStore`.
   - **`H295` (`tools`):** `check_fns` per-tool în `agents/core/tool_profiles.py` cu `CheckFnCache` (`30.0s` TTL + `60.0s` fereastră de grație last-known-good), `no_cache_check_fn` și sondă `sandbox.is_isolated()` pe `execute_code` astfel încât unealta dispare din oferta turn-ului când nu există un backend izolat Docker/WASM disponibil.
   - **`H320` + `H650` (`tools`, `user-journeys`):** `delegate_task` (`agents/core/delegate_tool.py`) extins cu `action: spawn|collect|list|steer|stop` pe ToolRPC (mediat de Action Kernel, izolat la `(parent == agent, parent_session == current_session())`, `origin="agent"` pe `steer`) + `schema_overrides()` dinamice cu sloturile de concurență libere/active, `SubagentLifecycleAPI` (`agents/core/subagent_lifecycle_api.py`) și ghidul `docs/DELEGATION_PATTERNS.md`.
   - **`H429` (`memory`):** `StreamingContextScrubber` (`agents/core/security/rag_guard.py`) pe ieșirea stream/non-stream și la ingestie, plus redactare `SecretScanner().redact` și trunchiere head/tail la granița de compresie (`agents/core/context_compressor.py`).
   - **`H508` (`security`):** scanner in-process pre-comandă (`agents/core/security/command_content_scanner.py` + `terminal_consent_categories.py` + `smart_approvals.py`) pentru URL-uri/hosturi homograph/IDN/punycode/TR39 și escape/bidi injection în terminal (`permanent=False` consimțământ exclusiv pe sesiune, blochează auto-aprobarea `SmartPolicy`), fail-open implicit configurabil prin `security.command_scanner_fail_open` cu circuit breaker (`3` eșecuri / `300s` + marker `24h`) și finding `HIGH` sintetizat în mod fail-closed.
   - **`H012` (`cli`):** sursă `'codex'` în `MIGRATION_SOURCES` (`agents/core/skills/importer.py`, `scripts/nerva_import.py`, `agents/cli/import_cmd.py`) cu `CODEX_MIGRATION_MAPPING` (tokeni `config.toml` -> `SecretStore`, preview `AGENTS.md`, fapte `memory.md` marcate tainted, `skills/` carantinate), `cleanup_source` dry-run-first (`--confirm` obligatoriu, arhivă backup `0o600`, păstrare fișiere neafiliate) și CLI `nerva import sources|plan|apply|cleanup`.
3. **Suită reproductibilă de benchmark diferențiator Nerva vs Hermes/OpenClaw (`scripts/bench_nerva_differentiators.py` + `docs/benchmarks/nerva-vs-hermes-openclaw-2026-11-14.{json,md}` + `tests/test_bench_nerva_differentiators.py`):**
   - **B1 — Resilient Hybrid Committee (`H032`, `moa.py`):** `100%` (`3/3`) completare quorum cu 1 proposer în avarie față de `0%` (`0/3`) pe baseline-ul secvențial fail-stop; `3.98x` speedup paralel steady-state (`2.14x` wall); plafon timeout `2.0s` (`2011 ms` vs `3500 ms` proposer blocat) și fail-closed verificat sub quorum (`2/4 < 3`).
   - **B2 — Controllable Cloud Privacy (`H513`, `moa.py` + `data_handling.py`):** `0` apeluri / `0` tokeni scurși către un membru cloud neconsimțit pe 4 prompturi sensibile (`100%` acuratețe blocare politică + verificare strict-local `ultron`), livrând simultan `100%` sinteză locală pe `local-moa` (față de `4` apeluri / `78` tokeni scurși pe baseline neprotejat).
   - **B3 — Surviving-Host Room Failover & Fencing (`H657`, `rooms.py`):** `100%` (`8/8`) respingere scrieri stale-epoch (`409 room_fenced`), `0/12` intrări replicate pierdute + `3` intrări post-failover comise, latență promovare `0.735 ms`, plus respingere goluri de secvență, alterare hash-chain și dovezi HMAC falsificate (`403`).
   - **B4 — Identity-Scoped Browser Broker (`H086`, `browser_broker.py`):** `100%` (`8/8`) blocare SSRF (CIDR-uri private, loopback, IMDS, `file://`), `100%` (`6/6`) izolare cross-principal (`owner-alice` vs `peer-bob`), impunere `403 https_required` și `100%` (`6/6`) respingere replay tichete one-shot (`410 ticket_already_used`).
   - **B5 — Secret-Stripped E2E Cross-Device Sync (`H040`, `e2e_sync.py` + `settings_db.py`):** `0/4` chei/valori secrete scurse în export și în manifestul de transport, skill ostil cu prompt-injection carantinat la pull, `100%` (`8/8`) respingere bit-flip pe ciphertext autentificat (documentat onest ca Fernet `AES-128-CBC + HMAC-SHA256` cu PBKDF2 390k iterații), și convergență deterministă `100%` (`6/6` permutări) prin sortare canonică `(max_ts, device_id)` peste metadatele `(ts, device)` din plicurile `E2ESync` (cu atribuire explicită între helperul `_lww_order_manifests` din harness și ordinea lexicală/de sosire din `DirectorySyncTransport` / `pull_state`).

### Măsurători și porți verificate local

- **Hermes 697 status (`scripts/hermes_status.py summary` & `check`):** **`187 equivalent` (`26.8%`, `+8` în Lot 4, `+16` cumulat față de începutul sesiunii), `474 partial`, `0 missing` (eliminat integral în Lot 3), `36 excluded`, `0 needs_review`**.
- **HUD `UNCALLED_BACKLOG`:** redus la **`9`** rute (`54 -> 41 -> 9`, `-45` rute conectate end-to-end în Lot 2 + Lot 4).
- **Contoare proiect sincronizate (`scripts/status_sync.py --check --reuse-test-counts`):** `backend: 36743`, `frontend: 3207`, `mobile: 420`, `routes: 923`, `agents: 18`.
- **Analiză statică, securitate și suite rulate efectiv secvențial:** `ruff check .` (`0` erori), `bandit -r agents -ll -b .bandit-baseline.json -q` (`0` constatări peste baseline), `semgrep scan --config p/python --config p/security-audit` (`0` constatări), `npm run typecheck && npm run build`, Vitest (`10/10` fișiere, `60/60` teste), `bench_nerva_differentiators.py --check` (`5/5 passed`), `pytest` pe 23 suite de integrare/paritate/securitate (`579 passed, 1 skipped, 0 failed`), și `development_preflight.py --frontend --smoke --json` (`ok: true`, `12/12` checks pass).
- **Igienă depozite & siguranță PR:** toate worktree-urile temporare `jarvis-wt-*.nosync` au fost eliminate curat; `/Users/andrei649/Documents/Antigravity/jarvis-hub` este 100% neatins (`git status --short` gol); toate PR-urile deschise (`#1365`, `#1366`, `#1367`, `#1368`) sunt verificate `isDraft: true`, fără merge și fără deploy.
- **Limitări oneste menținute:** toate benchmark-urile și testele rulate local sunt deterministe și ermetice (`live_network_llm_calls = 0`); rularea completă a celor `36.743` teste backend pe matricea CI Ubuntu/Windows și acceptanța pe provideri comerciali live, clustere multi-host reale sau dispozitive mobile fizice rămân distincte.

---

## Lot 5 — PAUZĂ (2026-11-14, în lucru — backup salvat pe ramuri, fără Draft PR #5)

- **Ramură țintă Lot 5:** `antigravity/lot5-backlog-hermes-autonomy-20261114` (peste `antigravity/lot4-hud-kanban-providers-bench-20261114` / Draft PR `#1368`, base SHA `ffbfce81a2733f4b10dc2e60463b2931a51cdadf`)
- **Motiv pauză:** oprire solicitată de proprietar după atingerea limitei de cotă pe workerii swarm; tot progresul a fost salvat curat în commit-uri și împins ca ramuri de backup pe `origin` (fără PR pentru Lot 5, fără merge, fără deploy).

### Starea exactă a celor 4 ramuri Lot 5 (păstrate și ca worktree-uri locale în `jarvis-wt-lot5-*.nosync`)

1. **`antigravity/lot5-kanban`** (`37a3a5615b220e8bacc1fcee16580b746b19205a`, `/Users/andrei649/Documents/Antigravity/jarvis-wt-lot5-kanban.nosync`) — **VERIFICAT GREEN (`1/4` în `#24`)**:
   - Conectat `POST /api/autonomy/kanban/dispatch` în `AutonomyControlPanel` (`frontend/src/panels/autonomy-legacy.tsx`) cu validare strictă `KanbanDispatchBody`, afișare onestă `503`/`409`/`422`, teste Vitest (`4` noi, `54/54` / `58/58` pass), `npm run typecheck`, `ruff` și `pytest tests/test_hud_v2_parity.py tests/test_doc_reference_integrity.py` (`26 passed`).
   - `UNCALLED_BACKLOG` redus `9 -> 8` (rămân exclusiv cele 8 refuzuri/aliasuri arhitecturale deliberate). `H18.34` rămâne deschis pentru paritatea nativă mobilă.
   - *Notă la integrare:* necesită `python scripts/status_sync.py` pentru a actualiza contorul frontend (`+4` teste Vitest).

2. **`antigravity/lot5-bench`** (`bd93bff5caf993bd150828a87d3cd1b4bfd88fa5`, `/Users/andrei649/Documents/Antigravity/jarvis-wt-lot5-bench.nosync`) — **REVIZUIT & TESTAT DE AUTOR (`#27`), RE-VERIFICARE `verifier` ÎN AȘTEPTARE**:
   - LWW canonic în `agents/core/e2e_sync.py` mutat pe timestamp-ul autentificat Fernet (`encrypt_at_time` / `extract_timestamp`) + `device_id` din înregistrarea decriptată și recalculare `digest` peste `ct`; adăugat `agents/core/llm/cost_cascade.py` (cu `physical_request_scope` H513 per cerere fizică) + Benchmark `B6` (`84.8%` reducere estimată de cost, `0` depășiri de plafon în rularea ermetică; bibliotecă neconectată încă în `HybridRouter`).
   - Autorul a raportat `ruff`, `bandit`, `semgrep`, `bench_nerva_differentiators.py --check` (`6/6`) și `pytest` (`41 passed`) verzi pe `bd93bff5`.
   - *Două eșecuri pre-existente confirmate la baza `ffbfce81` (nemodificate de Lot 5):* `test_o26_p2_env_config::test_raw_env_reads_do_not_grow` (`115 > 110` citiri brute `os.environ`) și `3` eșecuri de identitate callback în `test_agent_runtime_v2.py`.

3. **`antigravity/lot5-hermes-core`** (`cc7aba9a8301251884b1770425313b0a9cd21e2f`, `/Users/andrei649/Documents/Antigravity/jarvis-wt-lot5-hermes-core.nosync`) — **WIP NEVERIFICAT (salvat înainte de pauză)**:
   - Commit `WIP(lot5, UNVERIFIED)` cu 16 fișiere (`+3109/-48`): `agents/cli/{nerva.py,approvals_policy.py,env_cmd.py,profiles.py}`, `agents/core/{code_env.py,orchestrator.py,paths.py,profiles.py,settings_db.py,turn_compaction.py,turn_notices.py}`, `agents/core/autonomy/{command_allowlist.py,smart_approvals.py}`, `agents/core/memory/context_engine.py`, `agents/core/security/env_write_guard.py`, `docs/ENV_WRITE_GUARD.md`.
   - **NU** s-au rulat teste, `ruff`/`bandit`/`semgrep` și **NU** s-au actualizat `docs/hermes/{assessment.json,areas.json}` sau testele dedicate.

4. **`antigravity/lot5-hermes-gw`** (`207eda49bc5d39cada27b58f1f58e9eba9cef017`, `/Users/andrei649/Documents/Antigravity/jarvis-wt-lot5-hermes-gw.nosync`) — **WIP NEVERIFICAT (salvat înainte de pauză)**:
   - Commit `WIP(lot5, UNVERIFIED)` cu 6 fișiere (`+2244/-336`): `agents/core/channels/{gateway.py,group_policy.py,slack.py,slack_ai_surfaces.py,webhook_channels.py}`, `agents/core/mcp/oauth_client.py`.
   - **NU** s-au rulat teste, `ruff`/`bandit`/`semgrep` și **NU** s-au actualizat `docs/hermes/{assessment.json,areas.json}` sau testele dedicate.

### Pași exacți la reluare

1. Audit & finalizare pe cele 4 ramuri din `jarvis-wt-lot5-*.nosync`:
   - Re-verificare formală pe `antigravity/lot5-bench` (`bd93bff5`) față de observațiile `#26`.
   - Finalizare + teste hermetice dedicate + `ruff`/`bandit`/`semgrep` + actualizare cinstită `docs/hermes/{assessment.json,areas.json}` pe `antigravity/lot5-hermes-core` și `antigravity/lot5-hermes-gw` (fără a supra-declara echivalențe).
2. Integrare pe `antigravity/lot5-backlog-hermes-autonomy-20261114` în `jarvis-work.nosync`: merge cele 4 ramuri verificate, reconciliere `docs/hermes/`, apoi secvențial: `python scripts/hermes_status.py write && check`, `(cd frontend && npm run typecheck && npm run build)`, `python scripts/status_sync.py && --check --reuse-test-counts`, `ruff check .`, `bandit -r agents -ll -b .bandit-baseline.json -q`, `semgrep scan`, `pytest` pe suitele relevante + paritate/auth/OpenAPI/doc-integrity, și `python scripts/development_preflight.py --frontend --smoke --json`.
3. Curățare worktree-uri `jarvis-wt-lot5-*.nosync`, actualizare `CONTINUATION_LEDGER.md`, push + deschidere **Draft PR #5** (`--draft --base antigravity/lot4-hud-kanban-providers-bench-20261114`, verificat `isDraft: true`).

### Ce rămâne deschis per ansamblu în proiect

- **Contracte Hermes:** `474` rămase `partial` (din `697` total; `187 equivalent`, `0 missing`, `36 excluded`).
- **HUD `UNCALLED_BACKLOG`:** `8` rute rămase după integrarea Lot 5 (`antigravity/lot5-kanban`), toate fiind refuzuri/aliasuri arhitecturale deliberate (`STAYS UNWIRED ON PURPOSE` / `RESTORED`).
- **Porți de release & backlog:** porțile deschise din `project-status.json` (`A1`, `A3`, `A4`, `A6`), rularea integrală CI pe Ubuntu/Windows pentru Draft PR-urile `#1365`–`#1368`, cele 2 regresii pre-existente la baza `ffbfce81`, conectarea în producție a `AdaptiveCostCascade` (dacă se dorește în Lot 6), plus acceptanța pe provideri live și dispozitive fizice/mobile.


## 2026-11-17 — #1370 post-merge standalone privacy and settings repair

Goal: fix confirmed standalone cloud-consent, settings-key and hardlink-config
findings, and record genuine HUD/mobile gaps. Base
`3a482575ec9d3f59d6baa47d70cf4455d5f84572`; isolated branch
`fix/jarvis-os-cloud-consent`, lease none. Scope: `apps/jarvis-os/`, focused
regressions, parity ledgers/H18.38, generated status and repair evidence.

Local-first default and strict saved/request cloud consent now fence every
fallback, late metadata/auth probes and remote/custom endpoints. Local Ollama
uses refreshed model provenance and a fully tagged `:local` selector; older
servers fail offline. OpenRouter masks and unrelated secret saves are preserved;
failed consent saves remain visibly failed. `allowHardLinks` loads/saves its JSON
boolean with default false. Provenance-based vault containment remains intact.
No real accounts, notes, live vault configuration or service activation used.

Builder: Codex (host-selected model/effort); separate read-only reviewer used the
host-selected model/effort without override. Reviewer found and rechecked concrete
revocation/model-locality/save gaps; all were repaired. Final focused integration
300 pass, shipped settings4 pass, Ruff/policy/Hermes/status checks and synthetic
install preflight pass. Root HUD250 passes. Initial full backend:36557 passed,
163 skipped,208 failed,141 errors. Base rerun reproduced348/349 failures/errors;
private workspace temp root resolves provider-store ancestry failures (347/349
pass), leaving two baseline-reproduced G17 process-group assertions. Full backend
is not declared green; see detailed evidence for names and snapshot limits.
See [repair evidence](../../reviews/2026-11-17-jarvis-os-consent.md) for exact scope,
commands/outcomes and unexecuted acceptance. Next: commit/push and open **draft only**. No ready, merge, deploy or workflow changes.


## 2026-11-17 — PR #1372 JUnit-compatible count correction

Base/head investigated: `3f47f602ffb21bf00e062d3e2599642a4792b02d`. Hosted
Linux attempt 2 passed backend Test and Hermes23/23, failing only count37071 vs
tracked37070. No hosted XML artifact was uploaded. Local collection evidence
shows37070 items plus one JUnit collection-skip report for the missing Discord
module. The previous generator omitted that report.

The generator now predicts the exact-JUnit outcome total from one collect-only
invocation and its private validated collection XML; runtime skips are not doubled,
collection/report failures refuse to update, and the nested-project guard stays.
CI parser/comparison/verification functions remain unchanged. XML support is lazy
so bare-Python backlog/help still works; eight regressions cover the behavior.
Actual regeneration yields37079 reported outcomes, not a hand-set count.

Final focused integration70 passed; repository Ruff, targeted Bandit, live count
and generated-status checks pass. Read-only review found the eager import issue,
which received a red/green compatibility regression and fix. New-head hosted CI
remains pending after the follow-up push. No workflow/security settings, merge,
ready promotion, deploy, credentials or real-data activation changed. See
[exact count evidence](../../reviews/2026-11-17-jarvis-os-count.md). Rollback is a
revert of this count follow-up commit.
