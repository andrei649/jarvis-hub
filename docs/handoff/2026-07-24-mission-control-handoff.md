# Handoff — Mission Control / Projects HUD (2026-07-24)

> **Scop:** o sesiune nouă pornește cu **zero context** din conversația care a produs asta
> (containerul e efemer, doar fișierele commit-uite persistă). Acest dosar îți dă starea completă,
> pointerii pe cod, convențiile obligatorii și un prompt gata de lipit — ca să nu redescoperi nimic.
>
> Documentul-frate durabil e **`BACKLOG.md` → `## 🛰️ ORIZONT 34`** (linia ~1011): acolo trăiește
> roadmap-ul cu status. Aici e *cum ajungi la el* + ce s-a livrat concret pe 2026-07-24.

---

## 0. TL;DR — unde suntem

Andrei vrea un **„Mission Control" stil Tony Stark**: pagini interactive prin care își vede și
ghidează roiul de AI-uri (flota internă Nerva + agenții de dev Codex/Claude/opencode/Antigravity),
cu feed live, intervenție umană (approve/steer), proactivitate (WhatsApp când e plecat de la biroul
de acasă) și, în timp, generare de venit — **totul local-first, guvernat și onest**.

**Explorarea a arătat că Nerva avea deja ~80% din fundație.** Pe 2026-07-24 s-au livrat piesele
lipsă din stratul de suprafață + fix-uri de onestitate. Ce a mai rămas e în §4 (roadmap) — nimic
din ce urmează nu necesită reconstruit backend-ul; e cablare HUD + slice-uri de proactivitate.

**Postura non-negociabilă (din `AGENTS.md`/`CLAUDE.md`):** local-first, guvernat, **onest** — „un
'nu pot / n-am date' onest e PASS; date fabricate arătate ca reale sunt BLOCKER". Asta a fost
firul roșu al întregii sesiuni (vezi PR #721).

---

## 1. Ce s-a livrat azi (PR-uri mergeuite + cel deschis)

| PR | Titlu | Ce a adus | Stare |
|----|-------|-----------|-------|
| **#720** | H34.1 Mission Control | Pagină standalone `/mission-control` (self-contained, polling 2s) + router **read-only** `GET /api/swarm/summary` care agregă roster + tracer + autonomy + missions + workflows + sub-agents + A2A + kill-switch + **dev-swarm locks** (reader pure-read cross-OS, NU importă `lock.py`). HITL prin endpoint-urile guvernate EXISTENTE (zero rute mutante noi). | ✅ merged |
| **#721** | Grounding onestitate | `Orchestrator._data_grounding_block` — fix-ul cauzei-rădăcină a 3 blockere de fabricație (Pepper inventa agendă, Steve raporta hardware „Online" deși picat, Gecko inventa solduri). Injectat la fiecare turn la ambele build-site-uri (stream + `_call_agents_parallel`). | ✅ merged |
| **#723** | QA follow-ups | (a) `fix(honesty)`: status LLM raportează modelul **live rezident**, nu default-ul configurat (`llm_control.py`, `refresh_active_model`); (b) `fix(autonomy)`: `TaskQueue` rezolvă DB-ul **lazy la init** ca fixture-urile de test să nu ajungă în Decision Inbox-ul live; (c) `feat(hud)`: rehidratare transcript la refresh (`app.tsx`, mount `useEffect` → `GET /memory`); (d) kill-switch fix (`halted` e MAP nu bool); (e) spec Cowork. | ✅ merged |
| **#724** | **Projects + timeline** | **DESCHIS (draft).** Vezi §2. | 🔄 CI ruleză |

---

## 2. PR #724 — „Projects" + timeline vizual (DESCHIS, branch `claude/ai-swarm-orchestrator-jkzwak`)

Răspunde celor două întrebări ale owner-ului: *„cum administrez proiecte pe subiecte diferite
fără istoric?"* + *„cum îmi arată vizual ce a făcut?"*.

- **Mod nou „Projects"** (nav rail + palette): unifică într-o singură suprafață —
  - **Rooms** = fire pe subiect cu istoric persistent + roster `@mention` (`RoomsPanel`, `/api/rooms`),
  - **Missions** = workspace-uri guvernate cu buget + state machine (`MissionsPanel`, `/api/missions/*`),
  - **Sessions** = reia o sesiune de chat veche (`SessionsPanel` existent, `/sessions` + `/sessions/resume`).
- **Activity timeline** (`ActivityTimelinePanel`): stream cronologic „ce a făcut", fuzionează
  audit-ul hash-înlănțuit (`/api/admin/audit`, admin) + coada autonomy (`/tasks?view=history`, user),
  cu **filtru all/audit/tasks**. Afișează doar titlu/decizie/status — **niciodată payload/result**
  (rămân admin-tier; vezi TASK-5) → zero tier leak. Stare goală onestă.
- **Pur frontend, zero rute backend noi** → fără reseed de snapshot-uri (route/openapi/auth).
- Verificat în sandbox: `tsc --noEmit` curat · `vitest` 373/373 · `vite build` OK · bundle v2 reconstruit.

**Rămâne (owner, în browser):** confirmare vizuală — creezi 2 camere pe subiecte diferite,
conversezi, refresh (istoric persistă + comutabil), `@mention` rutează corect, misiune cu buget
pauzează/reia, `resume` la o sesiune veche; apoi un task guvernat (aprobi/respingi) apare în timeline.

**Fișiere atinse în #724:** `frontend/src/gap.tsx` (`ProjectsMode`, `ActivityTimelinePanel`;
reutilizează `RoomsPanel`/`MissionsPanel`/`SessionsPanel`), `app.tsx` (import + render înainte de
live-gate), `shell.tsx` (nav + palette), `primitives.tsx` (icon `projects`), `data.ts` (i18n EN/RO),
`agents/web/v2/**` (bundle rebuilt).

---

## 3. Pointeri pe cod (unde trăiește fiecare lucru)

### Suprafețe deja construite
- **Mission Control:** `agents/core/routers/swarm.py` (`read_dev_locks`, `build_swarm_summary`,
  `GET /mission-control`, `GET /api/swarm/summary`) + pagina `agents/web/mission_control.html`.
- **Grounding onestitate:** `agents/core/orchestrator.py` → `_runtime_state_block()` (identitate model)
  + `_data_grounding_block(plugin_data)` (date). Apendate la `runtime_block` la **ambele** build-site-uri
  (path stream ~L1183 + `_call_agents_parallel` ~L1933). Gather-ul: `plugin_gatherer.gather_plugin_data`.
- **Rooms/Missions/Sessions:** `agents/core/routers/{rooms,missions,sessions}.py`.
- **Autonomy queue:** `agents/core/autonomy/queue.py` (`TaskQueue`, DB rezolvat lazy la init).
- **HUD v2 (React):** `frontend/src/` → `shell.tsx` (MODES + nav), `app.tsx` (`modeComponent` render
  switch + `MODE_LIVE_KEYS` honest-gate), `gap.tsx` (panouri Console + helperi `useApi/apiGet/apiPost/
  Card/Row/Tag/State/arr/mono/asLive`), `api/live.ts` (`useLiveModes` — marchează ce e LIVE vs SEED),
  `api/actions.ts` (write-side bindings), `data.ts` (`V2` + `I18N`), `primitives.tsx` (`ICONS`).

### Pentru munca rămasă (roadmap §4)
- **H34.2 proactivitate (away → WhatsApp):** `agents/core/autonomy/escalation.py:96` (`class
  EscalationRouter`), `:115` (`async def escalate(message, channels)`); plugin WhatsApp:
  `agents/core/plugins/whatsapp_bridge.py`, înregistrat în `agents/core/plugin_manager.py:94`.
  Semnalul de prezență (owner.away) = **owner-side** (daemon Windows idle/lock sau overlay Tauri) →
  `docs/OWNER_TASKS.md`. Buget de întrerupere ≤4/zi deja existent.
- **H34.3 feed PR/CI dev-swarm:** plugin `oracle_bridge` + `GITHUB_TOKEN`; se afișează lângă
  panoul de locks din Mission Control.
- **H34.4 `SwarmPanel` React:** port al paginii standalone în `frontend/src` (secțiunea Observe).
- **H34.5 venit guvernat:** `agents/core/routers/payments.py` (lifecycle approve/reject/settle,
  admin); rămâne draft-first + approval-gated (MOONSHOT §5 — zero cheltuială autonomă).
- **North-star metrics:** `agents/core/observability/north_star.py` (`GET /api/metrics/north-star`).
- **TASK-5 (tier leak pre-existent):** `agents/core/routers/dashboard.py:136` — `GET /tasks` user-tier
  servește `payload`/`result` complete. Fix propus: proiectează-le afară din `format_task` sau admin-gate.

---

## 4. Ce urmează (din `BACKLOG.md` → ORIZONT 34, linia ~1011)

| # | Item | SP | Prio |
|---|------|----|----|
| H34.2 | Desk presence + away notify (prezență owner → `EscalationRouter` → WhatsApp/Telegram, sub bugetul ≤4/zi) | 5 | P2 |
| H34.3 | Dev-swarm PR/CI feed (oracle_bridge) lângă panoul de locks | 3 | P2 |
| H34.4 | `SwarmPanel` React în Console V2 (portul paginii standalone) | 3 | P3 |
| H34.5 | Pointer program venit — rămâne guvernat, draft-first | — | — |

Owner-tasks (hardware/instalări) → `docs/OWNER_TASKS.md`.

---

## 5. Convenții OBLIGATORII (ca să nu pici gate-urile)

1. **Rute noi** → în router per-domeniu (`agents/core/routers/*.py`), **niciodată** `@app.*` inline.
   Guards din `routers/_deps.py`; `nocache_json` din `web_helpers`; orch via `app_state.get_orch()`.
2. **La rute noi** → re-seed snapshot-uri: `python tests/test_route_parity_guard.py --update` +
   `python tests/test_openapi_parity_guard.py --update`; adaugă manual în `tests/_snapshots/route_auth.json`
   (sortat); RULES în `tests/test_hud_v2_parity.py`; path-uri no-store în `_NO_STORE_PATHS` (`web.py`).
   **PR #724 n-a atins backend → n-a avut nevoie de niciun reseed.**
3. **Frontend build (3 job-uri CI separate):**
   - `hud-v2-build` = `npm ci` + `npm run build` (Vite → `agents/web/v2/`), apoi `git diff --exit-code
     agents/web/v2` → **trebuie să commit-uiești bundle-ul reconstruit**.
   - `frontend` = `tsc --noEmit` (prinde erori de tip pe care esbuild/vite le ratează — rulează-l MEREU).
   - `vitest` = `npm test`.
   - Node **22** (ca în CI). Din `frontend/`: `npm run typecheck && npm run build && npm test`.
4. **Commit author:** `Claude <noreply@anthropic.com>`. Footer commit:
   `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` + `Claude-Session: <url>`.
5. **PR footer:** `🤖 Generated with [Claude Code](https://claude.com/claude-code)` + linia de sesiune.
   Template PR: `.github/pull_request_template.md` (`## Changes` + `## Test plan` cu 3 checkbox-uri).
6. **BACKLOG sync — în ACELAȘI commit cu merge-ul:** când mergi/s-a mergeuit un PR, bifează itemii
   livrați în `BACKLOG.md` + actualizează contorul de teste (`python scripts/status_sync.py` apoi `--check`).
7. **Branch:** `claude/ai-swarm-orchestrator-jkzwak`. Dacă PR-ul e deja mergeuit → **restart din main**
   proaspăt (`git fetch origin main && git checkout -B <branch> origin/main`), nu stivui pe istoric mergeuit.
8. **`conftest.py`** izolează `JARVIS_HOME` în tempdir — nu presupune date reale în teste.

---

## 6. Prompt gata de lipit pentru sesiunea următoare

> Continuă Mission Control / Nerva (vezi `docs/handoff/2026-07-24-mission-control-handoff.md` +
> `BACKLOG.md` → ORIZONT 34). PR #724 (Projects + timeline) e deschis — verifică întâi statusul lui
> (CI verde? review comments?) și du-l la merge. Apoi ia **H34.2** (proactivitate: când owner.away,
> rutează cardurile de work-terminat/approval prin `EscalationRouter` — `agents/core/autonomy/
> escalation.py:115` — spre WhatsApp/Telegram, sub bugetul ≤4/zi). Semnalul de prezență e owner-side
> (`docs/OWNER_TASKS.md`) — deci livrează partea de backend/rutare testabilă + un stub de semnal.
> Respectă convențiile din §5 al handoff-ului (per-domain routers, reseed snapshots la rute noi,
> rebuild bundle v2, tsc+vitest, commit author + footer, BACKLOG sync la merge). Local-first, guvernat,
> onest: fără date fabricate, stări goale oneste, fără cheltuială autonomă (MOONSHOT §5). Puține PR-uri.

---

## 7. Verificare rapidă de sănătate (prima comandă în sesiunea nouă)

```bash
cd /home/user/jarvis-hub
git log --oneline -6                      # ce s-a mergeuit
git branch --show-current                 # claude/ai-swarm-orchestrator-jkzwak
cd frontend && npm ci && npm run typecheck && npm test   # frontend verde?
cd .. && python -m pytest tests/ -q       # backend verde (offline)?
```

*Onestitate: acest handoff e scris din contextul sesiunii 2026-07-24; pointerii `file:line` erau
corecți la commit, dar re-grep-uiește înainte să te bazezi pe un număr de linie (codul se mișcă).*
