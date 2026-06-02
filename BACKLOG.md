# Jarvis Hub — Backlog Multi-Agent

> Owner: Andrei · Planificat: 2026-05-30 · Echipă: agenți Claude + opencode
> HUD: http://127.0.0.1:8080/ · Admin: /admin

**S = story points (1 = ~jumătate de zi) · P = prioritate (P0–P3)**

## Run

```bash
pip install -r requirements-beta.txt
python -m uvicorn agents.web:app --host 127.0.0.1 --port 8080
python -m pytest tests/ -v          # 784 passed, 9 skipped
```

> Cele 8 skipped sunt din `tests/test_spotify.py` (pattern HTTP-router, opencode) care
> așteaptă `agents/core/skills/spotify.py` — neimplementat. Spotify (H2.5) **funcționează**
> via `skills/spotify/main.py` (pattern loader, acoperit de `tests/test_spotify_skill.py`).

**După modificări JS/CSS:** Ctrl+F5 în browser (cache bust).
**După modificări Python:** repornire server (Ctrl+C, re-execută comanda uvicorn).
**Server curent** (dacă e pornit): PID vezi `netstat -ano | findstr ":8080 "`.
**Stack:** Python 3.12 + FastAPI + vanilla React (createElement, no JSX).

---

## Version Roadmap

| Version | Target | Milestone | Items |
|---------|--------|-----------|-------|
| **0.5-beta** | 🟢 Live | Foundation complete. All H1–H4, cross-cutting, security, bugs done. | H1–H4, Sprint 0, Cross-cutting, Sec, Bugs |
| **0.6-beta** | Next | Howard fine-tuning + voice clone + continuous ingestion | H5.1 |
| **0.7-beta** | Next | Mobile PWA + i18n + UI Overhaul | H5.2, H5.3, H5.4 |
| **0.8-beta** | Next | Performance & robustness + multi-agent workflows | H5.5, H5.6 |
| **0.9-beta** | Next | New integrations + agent marketplace | H5.7, H5.8 |
| **0.9.1-beta** | 🟢 Live | Recall cu embeddings reale + perf cale fierbinte | H7.1–H7.5 |
| **1.0.0** | 🎯 Stable | All H5/H7 done, documented, CI/CD, onboarding docs | All above + ARCHITECTURE.md |
| **1.1.0** | Next | Memorie personală — „Jarvis te cunoaște" | ORIZONT 8 (H8.x) |

---

## Status General

| Horizon | Total | ✅ Done | S total | S done | % |
|---------|-------|---------|---------|--------|---|
| **H1–H4 + Sprint 0 + Cross-cutting + Sec + Bugs** | 67 | **67** | 248 | **248** | **100%** |
| **H5 Next Wave** (P2–P3) | 17 | **17** | 128 | **128** | **100%** |
| **H6 Jarvis Autonom** (P1) | 7 | **7** | 60 | **60** | **100%** |
| **H7 Perf Cale Fierbinte** (P1–P2) | 5 | **5** | 16 | **16** | **100%** |
| **H8 Memorie Personală** (P1–P3) | 7 | **0** | 43 | **0** | **0%** |
| **H9 Agent Ops: Workflows & Observability** (P2) | 3 | **3** | 29 | **29** | **100%** |
| **H10 Competitive Edge** (P1–P3) | 30 | **0** | 188 | **0** | **0%** |
| **Total general** | **136** | **99** | **712** | **481** | **68%** |

**Test count:** 909 passed, 9 skipped (2026-06-02: +ORIZONT 7 — perf_hotpath 9, recall_cache 6, model_tiering 19; + recall cu embeddings reale & RAG injection)

---

## ✅ ORIZONT 6 — Jarvis Autonom / Proactive Cortex (P1) — 7/7 COMPLET

> Viziune: Jarvis își găsește singur de lucru, lucrează continuu, îmi scrie pe telefon (Telegram)
> doar când are nevoie de o decizie, și susține un review zilnic de 10–30 min (morning brief + evening retro).
> Autonomia crește în timp pe măsură ce învață ce aprob.
>
> **Design:** `docs/superpowers/specs/2026-05-31-horizon6-autonomous-jarvis-design.md`
> **Research (cu surse):** `docs/research/2026-05-31-autonomous-proactive-agents.md`
> **Politică implicită:** ECHILIBRAT — act autonom pe reversibil/sigur (research, drafturi, organizare);
> aprobare pe ireversibil sau bani. **Buget întreruperi: ≤4 push-uri urgente/zi**, restul în review.
> **Principiu:** ambient agent (trigger → coadă → gating → inbox), NU auto-prompt loop (anti-AutoGPT).

| # | Item | S | Dep | AC |
|---|------|---|-----|----|
| H6.1 ✅ | **Autonomy Loop & Self-Tasking Queue** — coadă SQLite cu state-machine (`proposed→approved→running→done\|failed\|blocked`), worker pe loop, retry cap 3, 2 cozi manual/generated. `core/autonomy/queue.py` + `worker.py`, endpoints `/autonomy/*` | 13 | H3.5 | ✅ task trece prin tot ciclul; eșec ×3 → `failed`, nu reintră |
| H6.2 ✅ | **Decision Inbox pe Telegram** — card cu butoane inline Aprob/Editez/Resping/Amân pe task-uri blocate; buget ≤4 push/zi; rest în batch. `core/autonomy/inbox.py` + callback în `channels/telegram.py` | 8 | H6.1, H1.2 | ✅ task money/ireversibil → push cu 4 butoane → „Aprob" → running |
| H6.3 ✅ | **Risk Gate & Autonomy Dial** — `policy.py`: 4 tiers (read_only/reversible/external/irreversible_or_money) + scoring (reversibility, blast_radius, signal_quality, time_sensitivity); cap/ceiling bani | 8 | H6.1, H4.9 | ✅ reversibil → act fără întrebare; money peste cap → ask |
| H6.4 ✅ | **Daily Review Ritual** — morning brief 07:00 + evening retro 20:00 (cron), batch list; endpoint `/autonomy/brief`. `core/autonomy/digest.py` | 8 | H6.1, H3.5 | ✅ digest construit din coadă, trimis pe Telegram, expus în HUD |
| H6.5 ✅ | **Preference Learning & Decision Journal** — scor approve/reject per (agent,kind,tier), `suggest_autonomy_raise` (doar tier 1–2), jurnal JSONL append-only. `core/autonomy/preferences.py` + endpoint `/autonomy/preferences/suggestions` | 13 | H6.1, H3.4 | ✅ după N aprobări reversibile → sugerează ridicarea autonomiei |
| H6.6 ✅ | **Night Shift** — fereastră wrap-midnight; `tick(max_tier=1)` rulează batch doar reversibil/read-only. `worker.is_night_window` + filtru `queue.runnable(max_tier)` | 5 | H6.1, H6.3 | ✅ noaptea rulează doar muncă reversibilă; extern/ireversibil așteaptă |
| H6.7 ✅ | **Proactive OS Observer** (trigger layer) — `core/autonomy/observer.py`: eșantionează resurse (CPU/RAM/disk via psutil) + liveness servicii (TCP), **debounce pe schimbare de stare**, injectează în coada existentă (alertă→READ_ONLY auto-act, vizibilă în HUD/brief; remediere→tier-3 ASK→decision inbox). Probe injectabile (offline-testable). Endpoints `/autonomy/observer[/run]`. | 5 | H6.1, H6.3 | ✅ serviciu căzut → card „restart?" în inbox **o singură dată**; resursă în prag → alertă în brief |

> **ORIZONT 6 COMPLET ✅** — bucla autonomă end-to-end + executor real per task-kind (research→websearch, restul→LLM pipeline), ritual zilnic, preference learning, night shift, **+ Proactive OS Observer (H6.7)**. Suită 715 passed.
> **Audit MCU (2026-05-31):** intent router rescris (determinist, scored, **bilingv RO/EN**, fără substring-bug, fallback LLM opțional) — vezi `docs/gap-analysis-mcu-jarvis.md`. **Rămas ✅ (livrat 2026-06-01):** handler real `restart_service` (H5.12 — `RemediationRunner`, allowlist + no-shell + audit) și event-watchers email/calendar/finanțe/health (H5.13 — `EventWatcher`, același pattern ca observer-ul) sunt acum implementate, wired și testate.
> **Setări noi** (categoria `autonomy` în admin): owner_chat_id, cap_per_action, daily_ceiling, interrupt_budget, night_shift/start/end + `system.autonomy_tick`.
>
> **UPDATE CHAT ANTIGRAVITY (2026-06-01) ✅**: Core TTS & Hands-Free Live Voice Interaction implementat complet + unit teste adăugate și 100% verzi.
> **Bug-uri rezolvate:** 
> 1. Eroare runtime stale pycache (`SecurityEventType.LLM_CALL` missing) rezolvată prin curățare pycache + repornire.
> 2. `t_s0 is not defined` în `handle_input_stream` rezolvată prin inițializare explicită de cronometru.
> 3. Scurgeri de thinking/reasoning blocks streamuite (rezolvat cu `ThinkingStreamFilter` + `strip_thinking()`).
> 4. Crash de tip `TypeError` în event handlerul `submit` al UI-ului atunci când se dădea click pe Transmit (rezolvat prin securizarea `textOverride` tip string).
>
> **QA PASS CLAUDE (2026-06-01) ✅**: Suită rulată end-to-end → **740 passed, 9 skipped** (după fix); **749** cu H5.14.
> - **Verificat:** TTS/voice Antigravity (PR #11) — `/tts` endpoint, `ThinkingStreamFilter`, fallback `reasoning_content` în `generate_stream`; cod solid, teste verzi.
> - **Descoperit & sincronizat:** **H5.12 + H5.13** erau deja implementate, wired și testate (commit `6cafc9d`) dar nemarcate în backlog → marcate ✅ acum.
> - **Bug reparat (CI roșu → verde):** 2 eșecuri ordine-dependente din scurgerea globalei `web.orch` între fișiere de test. Cauză: `lifespan` nu reseta `orch`/`gateway` la shutdown (4 fișiere cu `with TestClient(web.app)` scurgeau un orchestrator real) + `_admin_response` din `test_resilience_integration.py` nu restaura globala (MagicMock). Fix: lifecycle simetric (guarded) în `web.py` + save/restore în helperul de resilience. Suita e acum deterministă.
> - **Următoarea dezvoltare livrată:** **H5.14 Retrieval Fusion Engine** (RRF vector⊕graph) — engine + wiring + 9 teste offline.

---

## 🔴 Auto-Generated Diagnostic Tasks

> [!NOTE]
> These tasks are auto-generated from active runtime failures in `problems.jsonl`.
> Sync runs automatically during the autonomy observer check.

✓ No active runtime failures detected in the last 48 hours.
## ORIZONT 5 — Next Wave (P2–P3) — 12/17

> Fiecare item are spec + plan propriu în `docs/superpowers/`. Timeline: 0.6 → 0.9 → 1.0.
>
> **Livrat sesiunea Claude 2026-06-01:** H5.15 ✅ Daily Reflection + H5.6 ✅ Multi-Agent Workflows + H5.14 Task4 ✅ `/api/memory/search` + HUD Fused Recall. Merged în `main` (PR #13, commit `6eaac77`).
>
> **Livrat Antigravity 2026-06-01:** H5.1 ✅ Howard Stark Digital Twin + H5.2 ✅ Mobile HUD / PWA + H5.3 ✅ i18n RO/EN + H5.4 ✅ Premium UI Overhaul + H5.7 ✅ New Plugins + H5.8 ✅ Agent Marketplace.
>
> **Livrat sesiunea Claude 2026-06-01 (LM Studio recall):** brațul vectorial al fused recall era mort — `/api/memory/search` trimitea `embedding=None` și nimic nu popula `MemoryManager.vectors`. Acum embeddings reale end-to-end: `Embedder` capătă backend **LM Studio** (`/v1/embeddings`, default) lângă Ollama, cu fallback hash determinist (recall nu pică niciodată). `MemoryManager.embed/remember/recall`, query embedat în `/api/memory/search`, endpoint nou `POST /api/memory/remember`, opțiune `MEMORY_EMBED_TURNS`. Config în `.env.example` (`EMBED_BACKEND/MODEL/BASE_URL`). +9 teste offline (809 passed, 9 skipped).

| # | Item | S | Dep | Target version |
|---|------|---|-----|---------------|
| H5.1 | Howard: fine-tuning + voice clone + continuous ingestion (arhivă personală: Facebook + WhatsApp → LLM antrenat pe conversațiile lui Andrei) | 13 | — | 0.6 |
| H5.2 ✅ | **Mobile HUD / PWA** (responsive, offline, push) | 8 | — | 0.7 ✅ |
| H5.3 ✅ | **Multi-Language / i18n (RO/EN switch)** | 5 | — | 0.7 ✅ |
| H5.4 ✅ | **UI Overhaul (teme, layout, accesibilitate)** | 8 | H5.2 | 0.7 ✅ |
| H5.5 ✅ | **Performance & Robustness** (retry, circuit breaker, rate limit, caching, resilience metrics) | 8 | — | 0.8 ✅ |
| H5.6 ✅ | **Multi-Agent Workflows** (handoff, paralel, pipeline) — `WorkflowEngine` + `Pipeline`/`WorkflowStep` (DAG, topological sort, parallel batches) + `WorkflowRegistry` (3 built-in: finance_report, research_and_brief, security_digest) + endpoints `/api/workflows` + `/api/workflows/run`. 16 teste offline. | 13 | H5.5 | 0.8 ✅ |
| H5.7 ✅ | **New Integrations / Plugins (SMS, CRM, IoT, social)** | 8 | — | 0.9 ✅ |
| H5.8 ✅ | **Agent Marketplace / Skill Sharing** (registry, publish) | 13 | H5.6 | 0.9 ✅ |
| H5.9 ✅ | **Resilience Tab in Main HUD** — tab live în SystemsPanel cu retry metrics + circuit breaker states, endpoint public `/api/resilience` | 3 | H5.5 | 0.8 ✅ |
| H5.10 ✅ | **Live Data Wiring** — Memory, Plugins, Learning, Security tabs trec de la mock static la endpoint-uri live (`/memory/stats`, `/api/plugins`, `/learning/stats`, `/security/status`, `/bench/stats`) | 5 | H5.9 | 0.8 ✅ |
| H5.11 ✅ | **Missing Widgets** — Ticker feed live, OAuth status tab, Oracle tab, Tasks widget; CognitionPanel live | 5 | H5.10 | 0.8 ✅ |
| H5.12 ✅ | **Secured Shell Task Executor** — `RemediationRunner` (allowlist, permission gate, no-shell `exec`, audited) wired ca handler `restart_service` în executor. `core/autonomy/remediation.py` | 5 | H6.7 | 0.8 ✅ |
| H5.13 ✅ | **Proactive Event Watchers** — `EventWatcher` + Email/Calendar/Finance/Health probes, eșantionate în bucla de autonomie (gated `system.watchers_enabled`). `core/autonomy/watchers.py` | 8 | H6.7 | 0.8 ✅ |
| H5.14 ✅ | **Retrieval Fusion Engine** — `reciprocal_rank_fusion()` + `HybridRetriever` (vector⊕graph RRF, weight-tunable, injectabil) + `MemoryManager.hybrid_search()`. `core/memory/fusion.py`, 9 teste offline. **Task4 ✅:** `GET /api/memory/search` + `FusedRecallBox` în MemoryTab. | 5 | H3.1, H3.2 | 0.8 ✅ |
| H5.15 ✅ | **Daily Reflection & Graph Consolidation** — `DailyReflector` (`core/autonomy/reflection.py`): gather context → LLM reflection → JSON entities/relations/lessons → promote to Neo4j graph; idempotent per zi; hookuit în `_autonomy_loop` (fereastră 22:00–07:00, gated `system.reflection_enabled`). Endpoint `/api/reflection/status` + `/api/reflection/run`. 10 teste offline. | 8 | H6.6, H3.2 | 0.8 ✅ |
| H5.16 ✅ | **Sentence-level TTS & Audio Barge-in** — integration edge-tts, play/stop barge-in sync, auto-speak, unit tested | 8 | H1.1, H5.5 | 0.8 ✅ |
| H5.17 ✅ | **Batch & Cache Embeddings Pipeline** — `EmbeddingCache` (content-addressed, sharded, crash-safe) + `Embedder.embed_batch` (dedup + paralel) + retry/backoff (degradare la hash) + cache stats în pipeline. `core/ingestion/embedder.py` | 5 | H5.5 | 0.8 ✅ |

---

## ORIZONT 7 — Performanță Cale Fierbinte (P1–P2)

> Sursă: profiling 2026-06-02 al căii per-turn (NU generarea LLM). Bottleneck
> non-LLM = scrieri sincrone SQLite pe event-loop-ul async (checkpoint + audit +
> worker autonomie). Detalii + măsurători: `docs/research/2026-06-02-perf-hotpath.md`.
> **Câștig măsurat:** commit SQLite `3317 µs → 92 µs` (~36×) cu WAL+`synchronous=NORMAL`.

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| H7.1 ✅ | **SQLite WAL + `synchronous=NORMAL`** pe DB-urile scrise per-turn — `checkpoint.py`, `security/audit.py`, `autonomy/queue.py`. Durabil (WAL crash-safe; NORMAL sigur sub WAL). | 1 | P1 | — | ✅ commit-uri ~36× mai ieftine; suite persistență/autonomy/securitate verzi |
| H7.2 ✅ | **Offload scrieri blocante de pe event-loop** — `checkpoints.save` / `audit.log` / `_record_interactions` / `_log_session` prin `asyncio.to_thread` în toate cele 3 call-site-uri per-turn; `checkpoint.py` cu `check_same_thread=False` + `threading.Lock`. | 3 | P1 | H7.1 | ✅ handlerele per-turn nu mai fac I/O sqlite/fișier sincron pe loop; thread-safe sub `to_thread` |
| H7.3 ✅ | **Debounce / frecvență checkpoint** — `_maybe_checkpoint()` salvează doar la `memory.checkpoint_every` (default 5) turns; `_flush_checkpoint()` forțat pe `new_session()` + `aclose()` (shutdown). Reduce I/O și CPU (`json.dumps` al state-ului). | 2 | P2 | H7.2 | ✅ checkpoint scris ≤1×/N turns; restart curat nu pierde sesiunea activă |
| H7.4 ✅ | **Query-embedding cache + fast-fail (recall)** — `Embedder.from_env(cache_dir=…)` default `memory_logs/embedding_cache/recall` + LRU in-process (`_PROC_CACHE`, 256) cheie `(backend,model,text)`; `max_retries=1` fast-fail. | 2 | P2 | — (recall) | ✅ query repetat = cache hit (fără network/disk); embeddings down → recall degradează instant |
| H7.5 ✅ | **Strategie fast/heavy model** — `is_heavy_request()` (token threshold 2000 + keywords RO/EN) escaladează în `hybrid_router.select_backend()` POLICY_AUTO de la slotul rapid (VRAM) la slotul deep (DDR5); flag `JARVIS_AUTO_DEEP`. | 8 | P2 | — | ✅ task ușor → model rapid `local`; task greu → `local-deep`/DEFAULT_DEEP_MODEL; nu afectează cloud/claude/local-only |

> **ORIZONT 7 COMPLET ✅** (2026-06-02) — livrat în paralel (3 streams Claude Code în worktree izolat: A=H7.2+H7.3, B=H7.4, C=H7.5), integrat secvențial cu rezolvare de conflicte. **+49 teste offline noi** (test_perf_hotpath 9, test_recall_cache 6, test_model_tiering 19, + extinderi). Setări noi: `memory.checkpoint_every` (runtime), env `EMBED_CACHE_DIR`, `JARVIS_AUTO_DEEP`.
>
> **Caveat-uri:** checkpoint poate întârzia ≤N turns (flush pe boundary sesiune); `get_model(agent_id)` NU escaladează (nu are prompt) — escaladarea trăiește în `select_backend()`, calea fierbinte. H7.5 validabil complet doar live pe System76 cu cele 2 sloturi LM Studio încărcate.

---

## Active: ORIZONT 8 — Memorie Personală & Personalizare („Jarvis te cunoaște") (P1) — 0/7

> **Viziune:** Jarvis își construiește în timp o **memorie despre Andrei** — fapte, preferințe,
> decizii, oameni, proiecte — extrasă din conversații, consolidată periodic (ca reflection-ul H5.15),
> versionată și injectată în context la fiecare agent, ca răspunsurile să fie personalizate fără
> să repet de fiecare dată cine sunt și ce vreau. Construit pe infrastructura livrată: fused recall
> (H5.14), embeddings reale + cache (H7.4), daily reflection (H5.15).
>
> **Principii:** local-first (ethos Frigga — datele personale rămân pe LAN), **inspectabil & editabil**
> (pot vedea/șterge orice fapt), opt-in pentru orice plecare spre cloud. Personalizarea crește în timp,
> dar controlul rămâne la mine.

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| H8.1 | **Memorie despre Andrei (User Profile Memory)** — store structurat persistent (facts / preferences / decisions / people / projects) construit din conversații (extragere LLM + consolidare idempotentă, pattern H5.15), versionat, injectat în prompt la toți agenții. `core/memory/profile.py` + `/api/profile`. | 13 | P1 | H5.14, H5.15, H7.4 | după câteva conversații, Jarvis cunoaște preferințe/fapte despre Andrei și le folosește; profilul e inspectabil în HUD |
| H8.2 | **Privacy & Forget Controls** — pentru memoria personală: export JSON, forget/redact selectiv per fapt, retention policy, scope strict-local. | 5 | P1 | H8.1 | pot șterge un fapt anume; export complet; nimic personal nu pleacă în cloud fără opt-in explicit |
| H8.3 | **Recall ON by default + Memory HUD** — activează `memory.recall_enabled` cu cache-ul H7.4; tab HUD cu faptele memorate (search/edit/delete), surse și scoruri (extinde Fused Recall). | 8 | P2 | H7.4, H8.1 | recall activ în chat din oficiu; HUD afișează și editează memoria personală |
| H8.4 | **Embeddings de calitate (model dedicat)** — `mxbai-embed-large` sau container TEI; benchmark calitate retrieval vs hash/nomic; degradare grațioasă păstrată. | 5 | P2 | H7.4 | retrieval măsurabil mai bun pe un set de probe; fallback intact |
| H8.5 | **Validare live fast/heavy (H7.5) + Model Tier HUD** — confirmă pe System76 cu 2 sloturi LM Studio încărcate; expune deciziile de tiering (fast↔deep) în `/bench` + HUD. | 5 | P2 | H7.5 | comutare fast↔deep vizibilă; latențe per tier măsurate |
| H8.6 | **Proactive Personal Briefs** — morning/evening brief (H6.4) personalizate din profil + recall: ce contează pentru Andrei azi (proiecte, oameni, deadline-uri). | 5 | P3 | H8.1, H6.4 | briefurile referă proiectele/oamenii din profilul personal |
| H8.7 | **AI-Navigable Docs upkeep** — `docs/ARCHITECTURE.md` ca sursă unică de navigare pentru asistenți AI; checklist „docs la zi" în template-ul de PR. | 2 | P3 | — | doc-ul reflectă codul curent; PR-urile mari ating și ARCHITECTURE.md |

> **Tech-debt notat (2026-06-02):** `README.md` rămăsese în urmă (test count 181/39, v0.2.1, linia Memory fără embeddings/graph) — actualizat în această sesiune. De ținut sincron pe viitor.
>
> **Inconsistențe găsite la scrierea `docs/ARCHITECTURE.md` — REZOLVATE (2026-06-02):**
> 1. ✅ **Model real, nu hardcodat:** `LLMRouter.detect()` auto-detectează modelul încărcat în LM Studio/Ollama (`/v1/models`, `/api/tags`) și îl folosește; fallback la `/admin → llm.default_model`. Doc-urile aliniate.
> 2. ✅ **`agents.yaml`:** eliminat duplicatul `howard` din `bench:` (rămâne doar în `agents:`, activ).
> 3. ✅ **Claude model din `/admin`:** nou setting `llm.claude_model` (settings_db) citit de `hybrid_router` în loc de constanta hardcodată.
> 4. ✅ **`handle_input_stream`:** `agent_id` și `t_s0` pre-inițializate înainte de buclă — fără `UnboundLocalError` când `target` e gol.
>
> **Vizinea Howard (context utilizator):** Howard = digital twin care „știe ce știe Claude despre Andrei" — alimentat de memoria personală (H8.1) + arhiva ingerată (H5.1). **Rămas în mâna lui Andrei:** antrenarea unui LLM pe toate conversațiile din Facebook/WhatsApp (date pe care le furnizează el); pipeline-ul de ingestie + fine-tuning e H5.1.

---

## Active: ORIZONT 9 — Agent Ops: Visual Workflows & Observability (P2)

> **Context (research utilizator, 2026-06-02):** evaluare a tool-urilor externe de management
> echipe AI (Flowise, Langflow, CrewAI, Autogen, SuperAGI, OpenWebUI, LangSmith, Dust.tt).
> **Decizie de arhitectură:** NU adoptăm un tool extern — Jarvis Hub acoperă deja orchestrarea,
> routing-ul hibrid local↔cloud, rolurile/tier-urile de agenți, autonomia, securitatea și memoria,
> lucruri pe care acele tool-uri nu le au la un loc (și sunt Node/TS, contra „pure Python"). Împrumutăm
> doar **2 idei** unde avem gap real: builder vizual de workflow-uri (Flowise/Langflow) și
> observability/eval (LangSmith), construite nativ peste ce avem.

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| H9.1 ✅ | **Visual Workflow Builder** — tab HUD (canvas SVG, vanilla React) PESTE `WorkflowEngine` (H5.6): noduri = pași/agenți, muchii = `depends_on`; creează/editează/salvează workflow-uri user-defined + rulare. Backend: `Pipeline.from_dict`, persistență (CRUD) + endpoints `/api/workflows` POST/PUT/DELETE, register în registry. | 13 | P2 | H5.6 | pot compune vizual un workflow, îl salvez, îl rulez din HUD; DAG invalid → eroare clară |
| H9.2 ✅ | **Observability — Trace Explorer** — store de trace-uri per-request (classify→route→model→tokens→latență→cost), nu doar `last_cognition`; endpoint `/api/traces[/{id}]` + tab HUD de inspecție. Extinde `bench.py` + CognitionPanel. | 8 | P2 | — | fiecare request lasă un trace inspectabil; pot vedea unde se duce timpul/tokenii pe pași |
| H9.3 ✅ | **Offline Eval Harness** — rulează seturi de prompturi prin orchestrator (LLM injectabil), scor pass/criterii, tracking de regresie; `core/observability/eval.py` + CLI/endpoint. | 8 | P2 | H9.2 | un set de probe produce scor reproductibil offline; regresii vizibile între rulări |

---

## ORIZONT 10 — Jarvis Competitive Edge (P1–P3) — 0/30

> **Research complet (2026-06-02):** deep research pe 8 competitori (Flowise, Langflow, CrewAI,
> AutoGen/AG2, SuperAGI, OpenWebUI, LangSmith, Dust.tt) — surse verificate adversarial.
> Doc complet: `docs/research/2026-06-02-competitor-research-h10.md`
>
> **Principiu:** nu adoptăm tool extern (decizie H9 menținută). Împrumutăm **idei concrete** unde
> avem gap real față de industrie. Toate construite peste ce avem (Python-first, local-first).
>
> **Teme cross-cutting (≥4 competitori):** prompt versioning · cost tracking · MCP server mode ·
> model quality comparison · agentic RAG · embeddable interface · action-level HITL · workflow termination.

### H10 — Status General

| Horizon | Total | ✅ Done | S total | S done | % |
|---------|-------|---------|---------|--------|---|
| **H10 Competitive Edge** | 30 | **0** | 188 | **0** | **0%** |

### H10.A — Observability & Eval (P1 — fundație)

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H10.16 | **APM Dashboard** — metrici org în Admin HUD: tokens totali consumați (cu cost $ estimat), runs totale, breakdown per agent și per model. Extinde `/admin` + `bench.py`. | 5 | P1 | H9.2 | SuperAGI |
| H10.24 | **Cost Tracking per Agent** — calcul $ per request (tokens × preț per provider/model), stocat în trace, vizibil per agent/zi în HUD. `PRICE_TABLE` configurabil în `agents.yaml`. | 5 | P1 | H9.2 | LangSmith |
| H10.19 | **Model Arena / Blind Comparison** — tab HUD: același query trimis la 2 modele, răspunsuri side-by-side anonimizate, buton vot, leaderboard quality score agregat. `/api/arena/run` + `/api/arena/vote`. | 8 | P1 | H7.5 | OpenWebUI |
| H9.3b | **Dataset Regression Tracking** (ext. H9.3) — datasets de eval persistente cu versiuni (JSONL), track scor per dataset-version, comparare rulări în HUD; integrabil în CI. | 5 | P1 | H9.3 | LangSmith |
| H10.22 | **Agent Prompt Version Control** — SOUL.md versionat cu history (git-tags sau DB), UI de comparare 2 versiuni, A/B eval pe un dataset, rollback. | 13 | P1 | H9.3b | LangSmith |
| H10.23 | **Live Quality Monitor** — evaluatori (LLM-as-judge + heuristic) care rulează pe trace-urile live după fiecare request; scor per request în trace; alertă când avg_score scade sub threshold. | 13 | P2 | H9.2, H10.24 | LangSmith |
| H10.17 | **Per-Agent Run History** — în HUD per agent: timeline run-uri, acțiuni din fiecare run, durată, tokens, status (success/fail/partial). `/api/agents/{id}/runs`. | 8 | P2 | H9.2 | SuperAGI |
| H10.25 | **Human Review Queue** — UI sistematic: trace-urile flagate (scor mic sau manual) apar într-o coadă de review cu rubric, vot thumbs up/down, adăugare la dataset eval. | 5 | P3 | H9.3b | LangSmith |

### H10.B — MCP & Integrare (P1–P2)

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H10.5 | **MCP Server Mode** — Jarvis expune agenți + workflow-uri ca tool-uri MCP (stdio/SSE); orice client MCP (Claude Desktop, Cursor, alt Jarvis) poate apela agenți Jarvis ca tool-uri. `core/mcp/server.py`. | 8 | P1 | H4.7 | Langflow |
| H10.8 | **Inbound Webhook Triggers** — endpoint `/api/webhooks/{id}` (POST) activează un agent sau workflow pre-configurat cu payload-ul ca input; autentificat cu token. Interfacă în Admin pentru creare/gestionare webhook-uri. | 3 | P2 | H5.6 | Langflow + Dust |
| H10.27 | **NL Scheduling** — în locul cron manual în APScheduler, câmp de text "every weekday at 7am" / "în fiecare luni la 9" → parse → cron expression. `core/autonomy/nl_schedule.py`. | 3 | P2 | H3.5 | Dust |
| H10.1 | **Embeddable Chat Widget** — endpoint `/api/widget/{token}` returnează snippet JS + CSS care embed-uiește chat-ul Jarvis pe orice website; theming configurabil din Admin. | 3 | P2 | H1.3 | Flowise |
| H10.30_writebacks | **Write-Back Integrations** — agenții pot scrie înapoi în sisteme externe (Notion, GitHub Issues, Google Calendar) ca tool-uri native; Pepper/Hephaestus primii candidați. | 8 | P3 | H2.1, H2.7 | Dust |

### H10.C — Memory & RAG (P1–P2)

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H8.1b | **Entity Memory Store** (ext. H8.1) — extragere LLM automată de entități (persoane, proiecte, locuri, concepte) din conversații într-un store structurat separat, searchable, afișat în HUD Memory tab. `core/memory/entity.py`. | 5 | P1 | H8.1, H5.14 | CrewAI |
| H8.3b | **Agentic RAG Tool** (ext. H8.3) — recall nu mai e injectat fix (top_k); devine tool call LLM-callable (`search_memory(query)`); modelul decide când/cum să caute și poate retry cu query diferit. | 8 | P2 | H8.3, H7.4 | OpenWebUI |
| H10.21 | **Conversation Notes** — rich text editor (textarea + markdown preview) în HUD atașat la sesiunea curentă; conținut injectat ca context persistent la orice agent; acțiune „Rescrie cu AI" inline. | 3 | P3 | H1.3 | OpenWebUI |

### H10.D — Workflow Engine (P2–P3)

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H10.12 | **Workflow Termination Conditions** — WorkflowStep poate defini o condiție de stop (LLM judge: "task rezolvat?", keyword match, max-iterations), nu doar completare normală. `WorkflowStep.stop_condition`. | 3 | P2 | H5.6 | AutoGen |
| H10.10 | **Structured Agent Outputs (Pydantic)** — SOUL.md sau config poate specifica un JSON schema; orchestratorul validează output-ul agentului și returnează eroare structurată la caller dacă nu e conform. | 5 | P2 | H5.6 | CrewAI |
| H10.15 | **Critic Agent Pattern** — built-in workflow node tip `critic`: primește output-ul pasului anterior, îl evaluează pe criterii configurabile, decide `accept`/`retry`(max N)/`escalate`. | 5 | P2 | H5.6, H10.12 | AutoGen |
| H10.13 | **Dynamic Agent Router** — WorkflowStep de tip `router_llm`: un agent coordinator decide la runtime care agent urmează, pe baza output-ului precedent (nu DAG fix). | 8 | P2 | H5.6 | AutoGen |
| H10.2 | **Visual Workflow Trace Overlay** — la fiecare rulare de workflow în HUD, nodurile pe canvas se colorează (verde=success, roșu=error, galben=running) și afișează output-ul per pas inline. | 5 | P2 | H9.1, H9.2 | Flowise |
| H10.28 | **Agent Config Preview** — în HUD Admin, înainte de save la SOUL.md sau config agent, un modal interactiv permite testarea comportamentului cu un query sandbox (fără a afecta producția). | 5 | P2 | H1.5 | Dust |
| H10.4 | **Guardrails Node în Visual Builder** — GuardrailsEngine expus ca nod plug-in în WorkflowBuilder; configurabil per workflow, nu doar global. | 2 | P3 | H4.9, H9.1 | Flowise |
| H10.6 | **Cyclic Workflow Support** — loop-back edges în WorkflowEngine cu contor de iterații și condiție de exit; util pentru retry loops și iterative refinement. | 8 | P3 | H5.6, H10.12 | Langflow |
| H10.7 | **AI-Assisted Workflow Builder** — în Visual Builder, câmp "Descrie ce vrei să facă acest pas" → LLM generează WorkflowStep config (agent, tool, prompt template). | 5 | P3 | H9.1 | Langflow |
| H10.9 | **Python Flow Decorator API** — `@jarvis_flow`, `@listen(step_id)`, `@router` pentru definire workflow-uri în cod Python (nu doar YAML/JSON); complement al Visual Builder. | 5 | P3 | H5.6 | CrewAI |
| H10.11 | **Hierarchical Workflow Manager** — workflow de tip `hierarchical`: auto-creează un manager agent care coordonează crew-ul, validează rezultate și redistribuie dacă un pas eșuează. | 8 | P3 | H5.6, H10.15 | CrewAI |
| H10.14 | **Nested Workflow Steps** — un WorkflowStep poate conține el însuși un sub-workflow; util pentru task decomposition recursivă. | 8 | P3 | H5.6 | AutoGen |
| H10.3 | **Workflow Transform Nodes** — noduri native în Visual Builder: Formatter, Validator, JSONExtractor, Summarizer — transformă output-ul unui pas înainte de a-l transmite mai departe. | 5 | P3 | H9.1 | Flowise |

### H10.E — UX & Multi-user (P2–P3)

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H10.29 | **Agent Templates Library** — librărie de configurații pre-built pentru agenți comuni (research assistant, email triage, code reviewer, daily brief); importabile și clonabile din Admin. | 3 | P3 | — | Dust |
| H10.18 | **Action-Level Approval UI** — în HUD, tab live cu tool call-urile pending approval (granularitate sub-task); buton Aprob/Resping per acțiune individuală. Extinde H6.2. | 5 | P3 | H6.2 | SuperAGI |
| H10.20 | **Chat Channels / Rooms** — canale de chat tematice în HUD (per proiect/context); în fiecare canal poți @mention agenți specifici; pipeline complet (tools, RAG, filters). | 8 | P3 | H1.3 | OpenWebUI |
| H10.26 | **Data Spaces / Agent Data Scope** — organizează sursele de date (memory segments, plugin outputs, knowledge) în "spații" cu permisiuni per agent; complement la `LOCAL_ONLY_AGENTS`. | 13 | P3 | H8.1, H4.7 | Dust |

---

## ✅ Arhivă — Tot ce e livrat în 0.5-beta

> Toate itemurile de mai jos sunt complet implementate, testate și funcționale.

### Foundation (H1) + Sprint 0

| Item | S | AC |
|------|---|----|
| **H1.1** Voice Channel (STT → orchestrator → TTS) | 8 | Pipeline complet funcțional |
| **H1.2** Telegram Channel (webhook + polling) | 5 | Bot răspunde direct, session per chat_id |
| **H1.3** Web Channel robust (SSE streaming) | 3 | Text → LLM → tokens streamuite în HUD |
| **H1.4** OAuth wiring (Google Calendar, Gmail, Spotify) | 5 | Token refresh + OAuth lifecycle complet |
| **H1.5** Admin DB → Runtime (settings watcher 30s) | 5 | Schimb temp din admin → efect imediat |
| **S0.1** Model Tiering (Claude API pentru grei, local pt ușori) | 3 | Vision/Steve → Claude; rest → local; Frigga → strict local |
| **S0.2** Heartbeat Sanity (intervale ≥60 min) | 2 | Steve la 2h, Ultron de 2x/zi, rest OK |
| **S0.3** Smoke Test + CI pe push | 2 | GitHub Actions pytest + server smoke |

### Core Agent Capabilities (H2) — 12 items

| Item | S | AC |
|------|---|----|
| **H2.1** Pepper Calendar | 5 | „adaugă meeting" → eveniment creat |
| **H2.2** Pepper Gmail Triage | 5 | „ce e nou în inbox?" → listă priorizată |
| **H2.3** Friday Brief Pipeline | 8 | Briefing complet structurat la cerere |
| **H2.4** Hercules Health Data | 5 | „cum am dormit?" → durată, calitate, trend |
| **H2.5** Jerome Spotify | 3 | „pune ceva focus" → track din library |
| **H2.6** Gecko Balance Reader | 8 | „câți bani am?" → sumă + mock când neconfigurat |
| **H2.7** Hephaestus PM | 8 | „status Cosmina?" → fază, milestone, blockeri |
| **H2.8** Frigga Local Store | 8 | „cât a dormit Max?" → ore, calitate. Zero network |
| **H2.9** Vision Web Research | 5 | „cercetează piața X" → raport cu surse |
| **H2.10** Veronica Drafting | 3 | „scrie post LinkedIn" → draft complet |
| **H2.11** Stark GA4 Analytics | 5 | KPI summary + mock când neconfigurat |
| **H2.12** Hybrid LLM Router (local ↔ Gemini) | 13 | Rutează per request după token count + agent policy |

### Intelligence & Memory (H3) — 6 items

| Item | S | AC |
|------|---|----|
| **H3.1** Qdrant Vector DB | 5 | Căutare similaritate pe conversații |
| **H3.2** Neo4j Knowledge Graph | 8 | „unde lucrează Andrei?" → răspunde din graph |
| **H3.3** Session Persistence cross-channel | 5 | Mesaj web → întrerup → Telegram → același context |
| **H3.4** Learning Loop live | 8 | După 100 interacțiuni → sugerează promovare bench |
| **H3.5** Heartbeat System (APScheduler) | 5 | 07:00 Jarvis face morning brief fără trigger |
| **H3.6** Bench Agent Activation | 8 | 20 query-uri Vision → Bruce devine activ |

### Platform & Security (H4) — 11 items

| Item | S | AC |
|------|---|----|
| **H4.1** Discord Channel | 5 | Agent trimite mesaj pe Discord |
| **H4.2** Email Channel (SMTP/IMAP) | 3 | „trimite raport pe email" → trimis |
| **H4.3** Slack Channel | 3 | Stark vede mențiuni Slack |
| **H4.4** Ultron Security Monitoring | 8 | „status securitate?" → devices, ports, threats |
| **H4.5** Steve System Monitor | 8 | „cum e sistemul?" → metrics + alerts |
| **H4.6** Oracle n8n Workflow Designer | 5 | „creează workflow vreme" → creat |
| **H4.7** MCP Client real (stdio/SSE) + admin-wiring | 8 | Server adăugat din admin → disponibil ca plugin (endpoints testate `tests/test_mcp_admin.py`) |
| **H4.8** Sandbox Docker | 5 | „rulează Python" → container, output |
| **H4.9** Guardrails (REDACT/BLOCK) | 5 | Prompt injection → blocat; PII → redactat |
| **H4.10** Admin Charts & Audit | 8 | Admin arată ultimele 100 interacțiuni, latență |
| **H4.11** Context Cache + Metrics | 5 | 50 mesaje → 80% cache hit |

### Cross-cutting (6) / Securitate (5) / Bugfixes (17)

**Cross-cutting:** Session Manager thread-safe, Error taxonomy, CHANGELOG.md, Integration tests per agent (15), Plans per agent, Load test 15 agenți <30s.

**Securitate:** Admin env masked, Admin guard (token/localhost), SSRF protection, Gemini stream raise_for_status, OAuth PKCE+state+Fernet.

**Bugfixes:** 17 bugs fixed (admin.js, app.js, web.py, orchestrator.py, css) — vezi detalii în archive commit `4e3bae5`.

---

## Testing Guide

> Cum testezi fiecare feature. Pentru comenzi rapide, vezi `docs/features/`.

```
Feature               Test command                          Ce verifici
─────────────────────────────────────────────────────────────────────────
All tests             python -m pytest tests/ -q            Toate feature-urile
Voice                 python tests/test_voice.py -v         STT → TTS pipeline
Telegram              python tests/test_telegram.py -v      Webhook + polling
OAuth                 python tests/test_oauth.py -v         Token refresh + PKCE
Calendar (Pepper)     python tests/test_calendar.py -v      CRUD evenimente
Gmail (Pepper)        python tests/test_gmail.py -v         Etichete, triage
Spotify (Jerome)      python tests/test_spotify_skill.py -v Play/pause/queue
Health (Hercules)     python tests/test_apple_health.py -v  Sleep/HRV/steps
Gecko (balance)       python tests/test_balance.py -v       ING/Libra/CSV/mock
Stark (analytics)     python tests/test_analytics.py -v     GA4 KPIs + mock
Security (Ultron)     python tests/test_security.py -v      Porturi, threats
System (Steve)        python tests/test_system.py -v        CPU/GPU/RAM/temp
n8n (Oracle)          python tests/test_n8n.py -v           CRUD workflow-uri
Sandbox               python tests/test_sandbox_gating.py -v Docker exec
Guardrails            python tests/test_guardrails.py -v    PII redact, injection block
Charts (admin)        python tests/test_admin_stats.py -v   Endpoint metrics
Learning              python tests/test_learning_live.py -v Health routing + promovare
Session               python tests/test_session*.py -v      Persistență + cross-channel
Bench                 python tests/test_bench_activation.py Bench promovare
Integration           python tests/test_agents_integration.py -v Toți agenții (SOUL+router+process)
Load                  python tests/test_load.py -v          15 paralel <30s
Smoke                 powershell smoke.ps1                  Server start + pytest
```

---

## Dependencies

| Resursă | Pentru | Cost |
|---------|--------|------|
| Google Cloud OAuth 2.0 | Pepper Gmail | Gratuit |
| Spotify Developer App | Jerome Spotify | Gratuit |
| Tavily API | Vision Research | Gratuit (1000/lună) |
| Discord Bot Token | Discord channel | Gratuit |
| Slack App Token | Slack channel | Gratuit |
| Docker (Qdrant, Neo4j, n8n) | H3.1, H3.2, H4.6 | Gratuit |
| n8n API Key | Oracle | Gratuit |
## 🔴 Auto-Generated Diagnostic Tasks

> [!NOTE]
> These tasks are auto-generated from active runtime failures in `problems.jsonl`.
> Sync runs automatically during the autonomy observer check.

✓ No active runtime failures detected in the last 48 hours.
## ORIZONT 5: Next Wave (P2–P3) — specs detaliate

> Scop: extindere capabilități după foundation stabil. Status: **12/17 done**.
> Specs complete pentru itemii rămași (H5.1, H5.2, H5.3, H5.4, H5.7, H5.8) mai jos.

### H5.1 — Howard: Fine-Tuning + Voice Clone + Continuous Ingestion (S:13, Dep: —)
Ollama backend (`ollama_howard.py`), embedder RAG, voice cloning XTTS, watch `data/` for new exports.
**AC:** Howard răspunde în vocea lui Andrei, cu RAG din arhivă, via Ollama.

### H5.2 — Mobile HUD / PWA (S:8, Dep: —)
Dashboard responsive, mobile-first, offline support (Service Worker), push notifications.
**AC:** HUD-ul funcționează pe telefon fără pierderi de funcționalitate.

### H5.3 — Multi-Language / i18n (S:5, Dep: —)
Extrage stringuri RO hardcodate în fișiere de traducere, suport EN/RO, detectare automată limbă.
**AC:** UI-ul comută între RO și EN după preferință.

### H5.4 — UI Overhaul (S:8, Dep: H5.2)
Teme, layout îmbunătățit, componente reutilizabile, animații, accesibilitate.
**AC:** HUD-ul arată modern și e utilizabil și pe ecrane mici.

### H5.5 ✅ — Performance & Robustness (S:8, Dep: —)
Resilience patterns: `@resilient_call` decorator with retry + exponential backoff, CircuitBreaker with tri-state (closed/open/half-open), ResilienceMetrics per agent+backend. Integrated into CloudLLMPlugin (Anthropic, Gemini, OpenAI) and HTTP plugins (weather, gmail, calendar, spotify). Exposed in `/api/admin/stats` endpoint + admin UI charts. Load test verifies 50 parallel calls with 10% failure rate.
**AC:** Sistemul nu crapă la overload și se recuperează automat.

### H5.6 ✅ — Multi-Agent Workflows (S:13, Dep: H5.5) — LIVRAT 2026-06-01
`core/workflows/`: `WorkflowEngine` (DAG topological sort, parallel batches via asyncio.gather, template substitution `{step_id}`), `Pipeline`/`WorkflowStep`, `WorkflowRegistry` (3 built-ins: finance_report, research_and_brief, security_digest). Endpoints `GET /api/workflows` + `POST /api/workflows/run`. 16 teste offline (`tests/test_workflows.py`).
**AC ✅:** Un query complex se execută în <15s; pașii paraleli rulează concurent.

### H5.7 — New Integrations / Plugins (S:8, Dep: —)
More plugins: notificări SMS, CRM sync, social media posting, IoT control.
**AC:** 3+ pluginuri noi funcționale, testate, cu admin configurator.

### H5.8 ✅ — Agent Marketplace / Skill Sharing (S:13, Dep: H5.6)
Catalog de skills partajabile, import dintr-un registry, versionare skills, publish workflow.
**AC:** Un skill scris de altcineva se instalează cu o comandă.

### H5.9 ✅ — Resilience Tab in Main HUD (S:3, Dep: H5.5)
Adăugare tab în SystemsPanel din HUD cu starea circuit breakerelor și retry metrics (endpoint `/api/resilience`).
**AC:** Interfața arată live degradarea grațioasă a conexiunilor.

### H5.10 ✅ — Live Data Wiring (S:5, Dep: H5.9)
Conectare taburi Memory, Plugins, Learning, Security la endpoint-uri reale din backend în loc de mock.
**AC:** Toate graficele și listele de securitate din HUD prezintă datele reale din DB/Logs.

### H5.11 ✅ — Missing Widgets (S:5, Dep: H5.10)
Ticker feed în HUD, status OAuth integrat, widget de task-uri curente și CognitionPanel funcțional.
**AC:** Toate widgeturile din interfață sunt active și interactive.

### H5.12 ✅ — Secured Shell Task Executor (S:5, Dep: H6.7)
`RemediationRunner` (`core/autonomy/remediation.py`) execută `restart_service` aprobat prin patru straturi independente: **allowlist** (rulează doar argv-ul allowlistat, ignoră `cmd` din payload), **permission gate** (`system-control` → steve/ultron/jarvis), **no-shell** (`create_subprocess_exec(*argv)`), **bounded + audited** (timeout + recovery probe + audit). Wired ca handler `restart_service` în executor (`orchestrator.py`). I/O injectabil → testat offline (`tests/test_autonomy_remediation.py`).
**AC ✅:** Aprobarea unui restart din Telegram execută comanda shell reală în siguranță, în loc de fallback LLM.

### H5.13 ✅ — Proactive Event Watchers (S:8, Dep: H6.7)
`EventWatcher` + `EmailProbe`/`CalendarProbe`/`FinanceProbe`/`HealthProbe` (`core/autonomy/watchers.py`), construite din pluginurile active și eșantionate în `_autonomy_loop` (gated `system.watchers_enabled`). Același pattern debounce ca OS Observer-ul; probe injectabile, testate offline (`tests/test_event_watchers.py`).
**AC ✅:** Evenimentele externe sunt observate, injectând alerte/taskuri automate în coada de autonomie.

### H5.14 ✅ — Retrieval Fusion Engine (S:5, Dep: H3.1, H3.2)
`core/memory/fusion.py`: `reciprocal_rank_fusion(ranked_lists, k=60, weights, top_k)` — RRF pur, rank-based (fără normalizare între scale diferite), cu provenance (`sources`) și payload merge; `HybridRetriever(vector_store, graph)` adaptează formele reale (`{id,score,metadata}` vector / `{name,type,properties}` graph), injectabil → testat offline cu `InMemoryVectorStore`+`InMemoryGraph`; `MemoryManager.hybrid_search(embedding, keyword, top_k)`. Plan: `docs/superpowers/plans/2026-06-01-h5.14-retrieval-fusion.md`. 9 teste (`tests/test_retrieval_fusion.py`).
**Task 4 livrat ✅:** endpoint public `/api/memory/search` + box „Fused recall" în HUD (MemoryTab → FusedRecallBox cu input + RRF results).
**AC ✅:** un singur query întoarce o listă rankată care împletește similaritatea conversațională (vector) cu hit-urile factuale din graf; fuziune deterministă, weight-tunable, rulează offline.

### H5.15 ✅ — Daily Reflection & Graph Consolidation (S:8, Dep: H6.6, H3.2) — LIVRAT 2026-06-01
`core/autonomy/reflection.py`: `DailyReflector` — gather context (last 60 turns) → LLM prompt → JSON `{entities, relations, lessons}` → `add_fact()` în Neo4j. Idempotent per zi. Hookuit în `_autonomy_loop` (fereastră 22:00–07:00, gated `system.reflection_enabled`). Endpoints `/api/reflection/status` + `/api/reflection/run`. 10 teste offline (`tests/test_daily_reflection.py`).
**AC ✅:** Knowledge Graph-ul se extinde organic după fiecare noapte prin auto-reflecție.

### H5.16 ✅ — Sentence-level TTS & Audio Barge-in (S:8, Dep: H1.1, H5.5)
Pipeline de voce optimizat: streaming audio fragmentat la nivel de propoziție și barge-in instant la wake word în timpul redării.
**AC:** Latența de prim sunet scade sub 1.5s, iar redarea se oprește la detectarea vocii utilizatorului. S-a implementat edge-tts backend, dynamic speech button (🔊), global audio window manager și hands-free live voice interaction (auto-transmitere și auto-speak).

### H5.17 ✅ — Batch & Cache Embeddings Pipeline (S:5, Dep: H5.5)
`core/ingestion/embedder.py`: `EmbeddingCache` (cheie `sha256(namespace\x00text)`, sharding pe 2 hex, scriere atomică temp→rename, stats hit/miss); `Embedder.embed_batch(texts, batch_size)` rezolvă hit-urile întâi, deduplică misses și le calculează (opțional pe `ThreadPoolExecutor`); fiecare apel de backend e reîncercat cu backoff exponențial și degradează la hash-embedding la epuizare (un apel flaky nu mai oprește ingestul). `embed_many` folosește batch-ul; pipeline-ul logează `cache_stats` în Phase 6. Namespace pe `backend:model` → nu amestecă ollama cu hash. 9 teste offline (`tests/test_embedding_pipeline.py`).
**AC ✅:** Ingestia masivă pentru digital twin-ul Howard decurge fluid și stabil — re-rulările servesc din cache, rate-limit-urile sunt absorbite de retry, iar eșecurile izolate degradează grațios.

---

**Total cost lunar:** $0 (toate serviciile au tier gratis sufficient pentru uz personal)
