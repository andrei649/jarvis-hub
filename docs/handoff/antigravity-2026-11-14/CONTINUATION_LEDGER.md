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
