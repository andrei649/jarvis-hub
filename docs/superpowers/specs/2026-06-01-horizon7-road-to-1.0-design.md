# Orizont 7 — Drumul spre 1.0.0: Hardening, Release Readiness & Observability

> **Owner:** Andrei · **Planificat:** 2026-06-01 · **Status:** PROPUS (planning)
> **Predecesor:** H1–H6 + H5 Next Wave = 100% (436/436 SP) · **Țintă versiune:** 1.0.0 stable
> **Surse:** audit multi-agent 2026-06-01 (docs/release, CI/hermeticitate, calitate cod, scoping features)
> + `docs/gap-analysis-1.0.md` (checklist produs/promovare existent).

## 1. De ce această fază (și nu mai multe features)

Backlog-ul de features e la **100%** (H1–H6). Roadmap-ul din `BACKLOG.md` definește explicit
1.0.0 ca *„All H5 done, documented, CI/CD, onboarding docs + polishing"*. După un sprint
orizontal lung, faza disciplinată nu adaugă scope — face produsul **de încredere, testabil,
documentat și măsurabil**. Auditul de mai jos arată că sub features-urile complete există
datorie reală care blochează un 1.0 serios:

- **Suita de teste nu e hermetică.** `python -m pytest tests/` **atârnă >18 min offline**:
  `TestClient(app)` pornește lifespan-ul → Oracle GitHub watcher (`oracle_bridge.start_watcher()`,
  `orchestrator.py:467`) intră într-un loop de polling de 30s către `api.github.com`. Nu există
  `pytest-timeout`, nici gate de test, nici blocare de rețea în `conftest.py`.
- **CI e schelet.** `.github/workflows/smoke.yml` rulează **doar pe push în master/main**
  (nu pe PR-uri — de aceea PR #15 nu are CI), **doar pe Windows**, fără lint/type-check/coverage.
- **Robustețe.** ~44 `except Exception: pass`/`return None` înghit erori în security/autonomy/log;
  14+ pluginuri reinventează `httpx.AsyncClient` cu timeouts incoerente; SQLite fără
  `check_same_thread=False`/lock în 3 din 4 store-uri; endpoint-uri fără validare de input.
- **Documentația se contrazice.** `README.md` zice simultan „181 passed" (l.73) și „39 tests" (l.83);
  versiune „v0.2.1" vs roadmap „0.5-beta"; port `8000` (README/JARVIS) vs `8080` (AGENTS/BACKLOG);
  model `gemma-4-26b` (JARVIS) vs `gemma-4-31b` (README); „15 agents" în docs vs **16** la runtime;
  fără `LICENSE`, fără `CONTRIBUTING.md`.

## 2. Principii

- **Verde devreme & hermetic.** Suita rulează offline, determinist, <90s. Rețeaua reală în
  teste = eșec imediat, nu hang.
- **Fără scope orizontal nou** în Track A–C. Track D = doar câștiguri rapide care folosesc
  infrastructura existentă (H5.5 metrics, H3.4 learning).
- **Reversibil & gated** pentru orice automatizare nouă (learning-loop trece prin decision inbox).
- **Single source of truth** pentru versiune și pentru fapte (docs ↔ cod ↔ CI).

## 3. Tracks & Stories

**S = story points (1 ≈ ½ zi) · P = prioritate.** Total ≈ **51 SP**.

### Track A — Test Hermeticity & CI/CD (P0, blochează restul)

#### H7.1 — Suită de teste hermetică (S:5, P0)
Cauza-rădăcină a hang-ului: watcher-ele/canalele pornesc apeluri externe la lifespan.
- Gate `oracle_bridge.start_watcher()` (și orice watcher cu I/O extern) pe `JARVIS_TESTING`
  (`orchestrator.py:467`).
- `tests/conftest.py`: fixture **autouse** care setează `JARVIS_TESTING=1` + **socket guard**
  (blochează conexiuni non-loopback → orice apel de rețea real eșuează instant).
- `pytest.ini`: `addopts = -q --timeout=15 --timeout-method=thread` (+ `pytest-timeout` în deps).
- Convertește `TestClient(web.app)` din **module-level** în fixtures **function-scoped** cu
  context manager în `test_cognition_api.py`, `test_tts.py`, `test_systems_api.py`,
  `test_resilience_integration.py` (teardown simetric de lifespan între teste).
- **AC:** `python -m pytest tests/` rulează **offline, verde, <90s**, fără niciun hang; un test
  care atinge rețeaua reală eșuează imediat.

#### H7.2 — CI/CD pentru 1.0 (S:5, P0, Dep: H7.1)
- `smoke.yml`: adaugă trigger `pull_request: [master, main]`.
- Matrix `os: [ubuntu-latest, windows-latest]` (Linux e mediul real de rulare — Bonobo/Pop!_OS).
- Pași noi: `ruff check`, `mypy agents/ --ignore-missing-imports` (non-blocking inițial),
  `pytest --cov=agents --cov-report=term-missing`.
- Healthcheck robust la pornirea serverului (poll pe `/`, nu `sleep 5`).
- **AC:** fiecare PR rulează CI pe Linux+Windows cu lint + teste + coverage; smoke verde.

### Track B — Code Hardening (P1)

#### H7.3 — Client HTTP centralizat + retry/circuit-breaker (S:8, P1)
`PluginHTTPClient` factory (timeouts coerente, `@resilient_call`/CircuitBreaker din H5.5, pooling);
migrează cele 14+ pluginuri (`weather, news, balance, analytics, crm_sync, sms_alerts, iot_control,
apple_health, spotify, homebridge, telegram_bot, …`).
- **AC:** un singur client + policy partajat; pluginurile îl folosesc; metrici de reziliență per plugin.

#### H7.4 — SQLite thread-safety & igienă conexiuni (S:5, P1)
`check_same_thread=False` + serializare scrieri (lock) pe `checkpoint.py`, `settings_db.py`,
`autonomy/queue.py`, `autonomy/preferences.py` (audit.py e referința corectă); WAL consistent.
- **AC:** acces concurent sigur; `test_load.py` (50 paralel) fără „SQLite objects created in a thread"
  și fără corupere.

#### H7.5 — Validare input pe endpoint-uri (S:3, P1)
Limite Pydantic/Query: `ChatRequest.message` max len, `limit` bounds, `task_id` numeric,
`/sandbox/execute` code size cap.
- **AC:** input invalid/oversize → `422`, fără OOM/DoS.

#### H7.6 — Curățare excepții înghițite silențios (S:5, P1)
Înlocuiește `except Exception: pass`/`return None` „oarbe" din `log.py:62`, `channels/telegram.py:80/89`,
`autonomy/watchers.py`, `autonomy/remediation.py:137/154`, `web.py:249/263` cu logging structurat +
fallback explicit (păstrând degradarea grațioasă **intenționată** din pluginuri).
- **AC:** nicio cădere silențioasă în căi de security/autonomy; fiecare eroare e logată cu context.

#### H7.7 — Elimină date mock/dummy înșelătoare (S:2, P1)
`/tasks` returnează `dummy-task-1/2/3` când nu sunt taskuri (`web.py:562–605`); `iot_control` mock
fără flag transparent.
- **AC:** UI nu mai primește date false ne-marcate; stare „no tasks" reală.

### Track C — Docs & Release Hygiene (P1)

#### H7.8 — Adevăr în documentație (S:3, P1)
Single source of truth pentru versiune (`agents/__init__.py: __version__`, expus în `/status`).
Reparat: test counts (README 181≠39≠BACKLOG 789), versiune (v0.2.1→actual), port (8000↔8080),
model (26b↔31b), agent count (15↔16), endpoint count (JARVIS „17").
- **AC:** zero contradicții cross-doc; un check CI verifică versiunea unică.

#### H7.9 — Onboarding & release (S:5, P1)
`LICENSE`, `CONTRIBUTING.md`, quickstart **Linux/Mac** (nu doar `.bat`), `docker-compose.yml`
(server + Qdrant + Neo4j + n8n) aliniat la `.env.example`, README cu badges + screenshot;
release workflow (tag → GitHub Release). Referință: `docs/gap-analysis-1.0.md`.
- **AC:** dev nou clonează și rulează în **<10 min pe Linux/Mac**; `git tag` → GitHub Release.

### Track D — Observability & Product Polish (P2, câștiguri rapide high-ROI)

#### H7.10 — Cost & Usage Analytics (S:5, P2, Dep: H5.5)
Tabele de preț per model + agregare tokens/cost per agent (local vs cloud) + burn lunar proiectat;
`GET /api/analytics/cost` + tab HUD. (Folosește metricile deja colectate în H5.5.)
- **AC:** dashboard arată cost per agent + proiecție lunară din date reale.

#### H7.11 — Activare Learning-Loop (auto promote/demote) (S:5, P2, Dep: H3.4, H6.5)
Job săptămânal care **propune** promovări/retrogradări de agenți pe baza scorurilor, trecut prin
**decision inbox** (reversibil, aprobat de om).
- **AC:** după N interacțiuni, sistemul propune în inbox promovarea unui bench agent; aprobarea îl activează.

## 4. Secvențiere

1. **H7.1** (deblochează CI fiabil + tot restul) → **H7.2**.
2. Track B (H7.3–H7.7) și Track C (H7.8–H7.9) în paralel.
3. Track D (H7.10–H7.11) la final.

## 5. Definition of Done pentru 1.0.0

- `pytest tests/` verde, hermetic, <90s, pe Linux+Windows în CI, pe fiecare PR.
- `ruff` curat; `mypy` fără erori noi pe căile critice.
- Zero contradicții în docs; versiune unică expusă în `/status`.
- `LICENSE` + `CONTRIBUTING.md` + quickstart Linux/Mac + docker-compose funcțional.
- Niciun `except: pass` orb în security/autonomy; endpoint-uri cu validare de input.
- Dashboard de cost live; learning-loop propune evoluția agenților prin inbox.

## 6. Stretch → Orizont 8 (post-1.0, din scoping-ul de features)

Voice clone (XTTS), Howard fine-tuning end-to-end, multi-user/family accounts, mobile offline voice,
n8n NLU→workflow, desktop Tauri, advanced guardrails DSL (ACL per agent), eval/regression harness.
