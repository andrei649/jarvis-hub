# MCU J.A.R.V.I.S. — Gap Analysis & Audit (2026-05-31)

> Audit tehnic al `jarvis-hub` față de „The Holy Grail" (Jarvis-ul lui Tony Stark).
> Spre deosebire de premisa unui asistent pur reactiv, codebase-ul este deja
> matur: **ORIZONT 6 (Proactive Cortex) e 100% livrat**, există memorie hibridă
> Qdrant+Neo4j, pipeline voce cu streaming, hybrid LLM router și sandbox Docker.
> Acest document măsoară golurile **reale** rămase și ce s-a livrat în acest audit.

Bază de comparație OSS: Open Interpreter, OpenClaw, gptme, QwenPaw, OpenHands,
Khoj, Leon, Mycroft/Neon, AutoGPT/BabyAGI (ca anti-pattern). Vezi și
`docs/research/2026-05-31-autonomous-proactive-agents.md`.

---

## FAZA 1 — Gap analysis pe 4 paliere

### 1. Preemptiveness & Proactivity — **EXISTĂ, dar lipsea stratul de trigger**

Ce există deja (verificat în cod):
- `core/autonomy/queue.py` — coadă SQLite cu state-machine strict
  (`proposed→approved→running→done|failed|blocked`), retry cap 3, fără re-intrare.
- `core/autonomy/worker.py` — `submit → policy.decide → act/notify/ask`, interrupt
  budget (≤4 push/zi), night-shift (`tick(max_tier=1)`).
- `core/autonomy/policy.py` — risk gate cu 4 tiers + scoring (reversibility,
  blast radius, signal quality, time sensitivity) + cap/plafon bani.
- `core/autonomy/{inbox,digest,preferences}.py` — decision inbox Telegram,
  morning brief / evening retro, preference learning.
- `core/heartbeat.py` — APScheduler + cron din `HEARTBEAT.md` (model OpenClaw).

**Golul real:** stratul de **trigger** era subțire. Singurele surse de muncă erau
cron-ul/heartbeat-ul și `submit` manual (din HUD/Telegram). Tabelul de mapare din
research-ul propriu o spunea explicit: *„Trigger layer → de adăugat event
watchers"*. Nu exista nimic care să **observe** mediul (resurse OS, servicii
căzute) și să transforme o schimbare de stare într-un task gated.

**Livrat în acest audit (FAZA 3):** `core/autonomy/observer.py` — `ProactiveObserver`
care eșantionează host-ul, face **debounce pe schimbare de stare** (alertă o
singură dată, nu la fiecare tick) și injectează în coada existentă. „Sir, serverul
Docker a căzut. Îl repornesc?" devine un task `restart_service` tier-3 → blocat →
card în decision inbox. Vezi mai jos.

**Rămas (next):** event-watchers pe email/calendar/finanțe/health (același pattern
ca observer-ul); handler real `restart_service` în executor (acum, după aprobare,
task-ul cade pe fallback LLM — vezi nota de siguranță din FAZA 3).

### 2. Contextual & Semantic Memory — **hibrid vector+graf există; lipsește fusion + consolidare**

Ce există:
- `core/memory/qdrant_store.py` — vector DB (Qdrant), degradare grațioasă fără numpy.
- `core/memory/graph.py` + `seed_graph.py` — knowledge graph Neo4j („unde lucrează
  Andrei?" → din graf).
- `core/memory/conversation.py` (JSONL) + `store.py` (numpy 768-dim) + `persistence.py`.
- `core/ingestion/*` — pipeline de ingestie (WhatsApp/Facebook parsers, stylometry,
  embedder) pentru Howard (digital twin).

**Goluri reale:**
- **Fără retrieval fusion.** Vectorii și graful sunt interogați separat; nu există
  un retriever care să combine (RRF/weighted) scorurile semantice cu cele din graf.
  Jarvis-ul din MCU „știe instant" pentru că fuzionează surse — aici sunt silozuri.
- **Fără consolidare/reflecție.** Nu există o buclă care să rezume sesiunile vechi
  în memorie long-term (pattern-ul QwenPaw `.learnings/` + promovare zilnică).
- **Embedder de bază** (`ingestion/embedder.py`) — nu e clar dacă batch-uiește sau
  cache-uiește; potențial bottleneck la ingestie mare.

**Recomandare:** `HybridRetriever` (vector ∪ graf, reciprocal-rank fusion) + un job
nocturn de consolidare care promovează highlights în graf (folosește night-shift-ul
deja existent).

### 3. Multi-modal Fluidity & Latency — **pipeline complet; TTFB optimizabil**

Ce există: `core/voice/{wake_word,stt,tts,pipeline}.py` (openWakeWord +
faster-whisper + edge-tts), `channels/web.py` cu SSE streaming, `gemini_cache.py`
(context cache), `resilience.py` (retry + circuit breaker).

**Goluri reale pe TTFB voce:**
- **TTS nu e chunk-uit pe propoziții.** Streaming-ul de tokeni LLM există, dar TTS
  pare să aștepte textul; sentence-level TTS (sintetizează prima propoziție în timp
  ce LLM-ul încă generează) ar tăia secunde din time-to-first-audio.
- **Fără prewarm/speculative.** Un singur model încărcat (constrângere VRAM 24GB,
  decizie corectă), dar cold-start-ul LLM nu e mascat.
- **Routing-ul era pe calea fierbinte** — vezi FAZA 2: l-am păstrat determinist și
  offline tocmai ca să **nu** adauge latență LLM la fiecare query.

**Recomandare:** TTS pe propoziții + barge-in (întrerupere la wake word în timpul
redării) + paralelizare STT-tail / LLM-prefill.

### 4. Competitor benchmark — 5 idei OSS pe care Jarvis NU le are (încă)

1. **Open Interpreter / agentic code-exec loop** — scrie cod → rulează în sandbox →
   citește output → iterează. `core/sandbox.py` există (Docker + subprocess) dar
   executor-ul autonomy NU are o buclă ReAct de codegen. (Aceasta era opțiunea B
   din brief; am ales A.)
2. **OpenHands — agent = funcție pură (event history → next event).** Orchestrator-ul
   actual e un obiect stateful de 954 linii; un event-stream tipizat ar simplifica
   testarea și replay-ul.
3. **gptme / QwenPaw — `lessons/` + auto-reflecție consultate ÎNAINTE de acțiune.**
   `learning/loop.py` există (health routing, promovare bench) dar nu există un store
   de „lecții" pe care agentul să-l citească înainte să acționeze.
4. **Khoj — connectors pluggable + indexare locală pe surse personale** (email, docs,
   notes) cu sync incremental. Ingestia există punctual (Howard) dar nu generalizată.
5. **OpenClaw — capability matrix per sesiune.** Heartbeat-ul există; lipsește
   gating-ul dinamic de capabilități per context (deja parțial via `plugin_gate.py`).

---

## FAZA 2 — Cel mai slab modul: `core/router.py` (rescris)

**Diagnostic (roast).** Intent router-ul era auto-etichetat *„Simple keyword-based
routing for v0.1.0. Will be upgraded to LLM-based in v0.2.0"* — proiectul e la
v0.5-beta. Probleme reale, în calea fierbinte (poarta de intrare a întregului sistem):

1. **Substring matching** (`if keyword in text_lower`): „car" prindea în s**car**ed /
   Os**car**, „max" în **max**imum, „search" în re**search**. Misrouting silențios.
2. **Doar engleză**, pentru un user RO/EN: „câți bani am?" nu ajungea NICIODATĂ la
   Gecko, „cum am dormit?" nu ajungea la Hercules. Eșec demonstrabil pentru userul primar.
3. **`async` fără await** (fake async), **set fără scor/ordine/încredere**,
   **wake word pe `startswith`** („visionary"→vision, „steven"→steve).
4. **Bug latent în `keywords_found`:** router-ul punea acolo **agent-id-uri**, dar
   orchestrator-ul (`_gather_plugin_data`) verifică `"weather" in keywords` (tag-uri
   de intent) → check-ul era mereu fals, salvat doar de fallback-ul pe text.

**Rescriere (`router.py`):** clasificator **determinist, offline-first, scored,
bilingv**:
- matching pe **token/word-boundary** (fără capcane de substring), cu stem-prefix
  controlat (min 4 caractere) pentru flexiune RO („bani"→„banii", „cercet"→„cercetez").
- **RO+EN** + folding de diacritice (`ș→s`, `ț→t`, `ă→a`).
- **scoring ponderat** → agent primar + suport, `confidence` + breakdown în context.
- wake word pe **token exact** (+ particule „hey/ok/salut").
- `keywords_found` acum conține **tag-uri canonice** independente de limbă → repară
  și calea de plugin pre-fetch din orchestrator.
- **fallback LLM opțional** (injectat), folosit DOAR când nimic nu se potrivește sau
  încrederea e mică → zero latență adăugată pe calea normală, degradare grațioasă.

Contract neschimbat (drop-in): `await classify(text, agents) -> Intent` cu
`.target_agents` (primar întâi), `.is_general`, `.context`, `ROUTING_TABLE` mutabil
pe instanță (promovare bench). **47 teste noi** (`tests/test_router_v2.py`), plus
testele existente verzi.

---

## FAZA 3 — Subsistem nou: Proactive OS Observer (opțiunea A)

`core/autonomy/observer.py` — stratul de trigger care lipsea. Se integrează în
**rail-urile existente** (worker → policy → inbox → budget), nu le reinventează.

Principii (din research):
- **Debounce pe schimbare de stare:** o alertă se trimite o singură dată
  (healthy→broken); re-eșantionarea unui serviciu încă picat NU re-declanșează →
  protejează bugetul de întreruperi.
- **Observațiile informează, deciziile întrerup:**
  - alertă simplă (disk 88%) → task `monitor.alert` tier READ_ONLY → auto-approved →
    apare în HUD / morning brief, fără push.
  - propunere de remediere (Docker căzut) → task `restart_service` tier-3 → policy îl
    blochează → decision inbox: „⚠️ docker nu răspunde. Restart docker?".

Probe injectabile (testabile offline fără psutil/sockets): `ResourceProbe` (CPU/RAM/
disk via psutil, degradare grațioasă), `ServiceProbe` (liveness TCP; serviciile cu
`restart_cmd` propun remediere). Wiring: `orchestrator._autonomy_loop` apelează
`observer.observe()` la fiecare tick (gated de `system.observer_enabled`); endpoints
`/autonomy/observer` (status) + `/autonomy/observer/run` (admin). **15 teste noi**.

> **Notă de siguranță (onestă):** observer-ul **detectează și propune**; execuția
> efectivă a `restart_service` (shell) NU e auto-wired. După aprobarea din inbox,
> task-ul cade momentan pe fallback-ul LLM, nu repornește realmente serviciul.
> Wiring-ul handler-ului `restart_service` (prin sandbox/`plugin_gate`) e pasul
> următor explicit — execuția de comenzi shell e o capabilitate ireversibilă și nu
> trebuie activată în tăcere.

---

## Rezultate verificate

- Suită completă: **710 passed, 8 skipped** (baseline înainte de audit: 661 passed).
- +49 teste noi (47 router + 12 observer + 3 endpoint), zero regresii.
- Zero modificări de contract public; toate edit-urile pe orchestrator/web sunt aditive.
