# ORIZONT 6 — Jarvis Autonom (Proactive Cortex) — Design

> Bază de cercetare: `docs/research/2026-05-31-autonomous-proactive-agents.md`
> Principiu director: **ambient agent**, nu auto-prompt loop. Trigger → coadă → execuție gated → decision inbox.
> Politica de autonomie implicită: **ECHILIBRATĂ** — act autonom pe acțiuni reversibile/sigure (research, drafturi, organizare); cere aprobare pe ireversibil sau bani.

## Obiectiv
Jarvis își găsește singur de lucru, lucrează continuu, îți scrie pe telefon (Telegram) doar când are nevoie de o decizie, și susține un ritual de review de 10–30 min/zi (morning brief + evening retro). Autonomia crește în timp pe măsură ce învață ce aprobi.

## Sub-proiecte (epice)

### H6.1 — Autonomy Loop & Self-Tasking Queue (inima)
- Modul: `agents/core/autonomy/queue.py` — `TaskQueue` peste SQLite (`memory_logs/autonomy.db`).
- Schema `tasks`: `id, agent, kind, title, payload(json), risk_tier, status, autonomy_level, created_at, updated_at, attempts, result(json), decided_by, decision`.
- State-machine strict: `proposed → approved → running → done | failed | blocked`. Fără re-intrare după `done/failed`.
- Worker pe heartbeat (`AutonomyWorker.tick()`): ia `approved`/auto-aprobate → rulează; pune restul în `proposed`/`blocked`.
- Plafoane dure (anti-AutoGPT): `MAX_ATTEMPTS=3`, `TASK_TIMEOUT_S`, **PID lock** (`autonomy.lock`), fereastră de timp pentru night-shift, log append-only.
- Două cozi (gptme): `kind=manual` (cerut de user) vs `kind=generated` (auto-propus).
- Endpoint: `GET /autonomy/tasks`, `POST /autonomy/tasks/{id}/decision` (`_admin_guard`).

### H6.2 — Decision Inbox pe Telegram (human-in-the-loop)
- Extinde `core/channels/telegram.py`: trimite un card pentru task-uri `blocked`/`risk_tier≥external` cu butoane inline **Aprob / Editez / Resping / Amân** (mapate pe accept/edit/respond/ignore).
- Callback handler → scrie decizia în `TaskQueue` → deblochează worker-ul.
- **Buget de întreruperi**: max `INTERRUPT_BUDGET_PER_DAY=4` push-uri urgente; restul se acumulează pentru review-ul zilnic (batch).
- Card conține: acțiune propusă, rationale, sursă/evidență, rezultat așteptat, risk tier.
- Fallback: dacă Telegram nu e configurat → totul așteaptă în HUD review view.

### H6.3 — Risk Gate & Autonomy Dial
- Modul: `agents/core/autonomy/policy.py` — `classify_action(action) -> RiskTier` și `decide(task) -> {act | ask | notify}`.
- 4 risk tiers: `read_only`, `reversible`, `external` (atinge terți), `irreversible_or_money`.
- Politica echilibrată implicită: `read_only/reversible → act+log`; `external → notify`; `irreversible_or_money → ask`.
- Scoring pe 4 factori (reversibility, blast_radius, signal_quality, time_sensitivity) → poate ridica un tier.
- Plafoane bani: `cap_per_action`, `daily_ceiling` în settings DB (`autonomy.*`).
- Reuse: se înfige în `guardrails.py` + `plugin_gate.py` (nu reimplementa permisiuni).

### H6.4 — Daily Review Ritual
- Heartbeat dimineața (`07:00`): `morning_brief` — ce a făcut peste noapte, ce propune azi, decizii în așteptare. Text + opțional audio (TTS H1.1) via Telegram.
- Heartbeat seara (`20:00`): `evening_retro` — livrate/blocate + **batch approve** pentru mâine (un mesaj cu lista, un tap per item sau "aprobă tot sigur").
- HUD view `/autonomy` (React) — listă task-uri + acțiuni de review.

### H6.5 — Preference Learning & Decision Journal
- Extinde `core/learning/loop.py`: fiecare approve/reject → `PreferenceRecord` (acțiune, context, decizie, risk_tier).
- Scor de preferință per (agent, kind, risk_tier); când scorul de aprobare e constant ridicat pe o clasă reversibilă → propune ridicarea `autonomy_level` (sugestie, nu automat; gated pe `autonomy.auto_raise`).
- Decision journal în Neo4j (H3.2): decizie + raționament + predicție + confidence; review periodic pentru calibrare.
- Semnale implicite: corecții, override, amânări → intră în scor.

### H6.6 — Night Shift (opțional, după H6.1–H6.3)
- Fereastră configurabilă (`autonomy.night_window`, ex. 23:00–06:00) în care worker-ul rulează batch doar pe task-uri `reversible`/`read_only` (research, drafturi, organizare) în sandbox (H4.8).
- Rezultatele apar în morning brief.

## Arhitectură (mapare pe existent)
| Strat | Cărămidă existentă | Modul nou |
|---|---|---|
| Trigger | APScheduler / HEARTBEAT.md (H3.5) | `autonomy/triggers.py` (event watchers) |
| Queue | SQLite | `autonomy/queue.py` |
| Risk gate | guardrails.py + plugin_gate.py (H4.9) | `autonomy/policy.py` |
| Inbox | telegram.py (H1.2) | extindere + callback handler |
| Ritual | gateway + TTS (H1.1) | heartbeat morning/evening |
| Learning | learning/loop.py (H3.4) + Neo4j (H3.2) | `PreferenceRecord` + journal |
| Night shift | sandbox (H4.8) | fereastră + batch |

## Decizii de design
1. **Coadă proprie, nu LangGraph.** Stack-ul e pur Python/FastAPI; o coadă SQLite cu state-machine e mai simplă și evită dependența + caveatul de re-execuție a nodului la resume. (Cel mai simplu lucru care merge — Anthropic.)
2. **Risk tier ca sursă de adevăr pentru gating**, nu confidence-ul modelului. Reversibilitatea decide întâi.
3. **Buget de întreruperi ca lege**, nu sugestie — protejează atenția userului.
4. **Autonomia se ridică empiric**, niciodată din start; default conservator per clasă nouă de acțiune.
5. **Append-only audit** pentru toate deciziile autonome (reuse `security/audit.py` cu Merkle chain).

## Plan de implementare (MVP întâi)
1. **MVP "Continuous Jarvis"** = H6.1 + H6.3 + H6.2 minimal → bucla completă: propune → gating → întreabă pe Telegram → execută. Teste: state-machine, risk classification, decision flow (TestClient + Telegram mock).
2. H6.4 (ritual) — heartbeat-uri + brief.
3. H6.5 (preference learning) — peste learning loop.
4. H6.6 (night shift) — ultimul, după ce gating-ul e dovedit.

## Acceptance criteria
- AC H6.1: un task propus trece prin `proposed→approved→running→done`; un task care eșuează de 3x → `failed`, nu reintră.
- AC H6.2: task `irreversible_or_money` → push pe Telegram cu 4 butoane; "Aprob" → `running`.
- AC H6.3: acțiune `reversible` → executată autonom fără întrebare; `money` peste cap → cere aprobare.
- AC H6.4: la 07:00 sosește morning brief fără trigger manual; seara batch-approve.
- AC H6.5: după N aprobări pe o clasă reversibilă → sugerează ridicarea autonomiei.
- AC buget: max 4 push-uri urgente/zi; restul în review.
