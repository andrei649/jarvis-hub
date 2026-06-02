# Plan Dispatch v1.0 — H10 + H11 + H12

> Generat: 2026-06-02 · Read-only până la aprobare · Status: **DRAFT**
> Înlocuiește `plan-h10-h11-dispatch.md` (acela acoperea doar H10+H11; sărea peste H12, inclusiv P0).
> Acoperă cele trei orizonturi rămase spre v1.0: **H10 (188 SP) + H11 (55 SP) + H12 (89 SP) = ~332 SP**.

---

## Schimbarea de scope față de planul vechi

Planul anterior (`plan-h10-h11-dispatch.md`) presupunea că v1.0 = H10 + H11. Analiza backlog-ului a
arătat că **ORIZONT 12** există și conține **singurul item P0 din tot backlog-ul**:

- **H12.1 — Securitate ca feature de prim rang (P0)** — e simultan hardening real ȘI wedge-ul de
  marketing (alternativa guvernată la OpenClaw, care a eșuat pe exact aceste puncte). Backlog-ul îl
  marchează drept *acțiune imediată recomandată*.

**Decizie de secvențiere:** H12.1 se mută înaintea tuturor wave-urilor H10/H11 (Wave 0).

### De ce H12 e aproape complet deblocat

Aproape toate dependențele H12 sunt pe orizonturi **deja terminate**:

| Item H12 | Dep | Stare dep |
|----------|-----|-----------|
| H12.1 | H6.2, Sec | ✅ done |
| H12.2 | H8.3 | ✅ done |
| H12.3 | H8.2 | ✅ done |
| H12.4 | — | liber |
| H12.5 | H6.2 | ✅ done |
| H12.6 | H5.15, H8.1 | ✅ done |
| H12.7 | H8.1 | ✅ done |
| H12.8 | H12.4 | intern |
| H12.9, H12.10, H12.13 | — | liber |
| H12.11 | H1.3 | ✅ done |
| H12.12 | Skills | ✅ done |
| H12.14 | H11.3 | intern (H11) |

Concluzie: H12 e **masiv paralelizabil** — singura dependență internă reală e H12.8→H12.4 și H12.14→H11.3.

---

## Stare de bază confirmată (neschimbată)

- `agents/web.py` — ~98 rute, hotspot principal (atins de 20+ iteme)
- `workflows/engine.py` + `pipeline.py` — motor DAG, atins de 7+ iteme H10.D
- `observability/tracer.py` — baza pentru cost/quality tracking
- MCP există doar ca **client** (`mcp/client.py`) — serverul lipsește
- Nu există încă: `arena`, `nl_schedule`, `entity.py`, `webhooks`, widget, chat rooms, data spaces,
  cripto secrete at-rest, skill signing, Wyoming, KG editor UX, local-docs onboarding

---

## A. Hotspot-uri (zonele de conflict)

| Fișier | Iteme care îl ating | Risc |
|--------|---------------------|------|
| `agents/web.py` | 25+ iteme (endpoint-uri noi) | 🔴 MAXIM |
| `workflows/engine.py` | H10.3,4,6,7,11,12,13,14,15 | 🔴 ÎNALT |
| `workflows/pipeline.py` | H10.3,6,10,11,12,13,14,15 | 🔴 ÎNALT |
| `agents/core/orchestrator.py` | H10.10,23,27, H8.3b | 🟠 MEDIU |
| `agents/web/static/admin.js` | H10.8,16,22,28,29, H12.3,9 | 🟠 MEDIU |
| `agents/core/sandbox.py` | H12.1, H11.4 | 🟠 MEDIU |
| `agents/core/observability/tracer.py` | H10.17,23,24, H12.5 | 🟠 MEDIU |
| Fișiere **NOI** (zero conflict) | majoritatea H12, H10.A/B/C noi, H11.x | 🟢 ZERO |

**Regula de aur (din AGENTS.md):** un PR draft = read-only pentru ceilalți agenți; fiecare wave
rebase-uiește pe `origin/main` la start; un singur lead/conductor per sesiune.

---

## B. Wave Dispatch Plan

### Wave 0 — Securitate & Încredere (P0 — NOU, primul) 🔴 PRIORITAR
**3 agenți | ~15 SP | Risc: 🟠 MEDIUM (atinge sandbox + storage secrete)**
*Prereq: main la zi. Acesta e wedge-ul; merge înaintea oricărui H10.*

| Agent | Item | SP | P | Fișiere atinse |
|-------|------|----|----|----------------|
| 1 | H12.1 Securitate prim-rang | 8 | **P0** | `core/secrets.py` NOU (cripto at-rest), `core/skills/loader.py` (signing), `sandbox.py`, `web.py` +2 (approval queue reversibil) |
| 2 | H12.10 Indicator mute / strict-local | 2 | P2 | `web.py` +1, `admin.js`, voce — zero conflict cu agent 1 |
| 3 | H12.9 UX management modele locale | 5 | P2 | `web.py` +2, `admin.js` (tab nou) — zero conflict Python cu agent 1 |

⚠️ Agent 1 deține `sandbox.py` și introduce cripto secrete — review uman atent. Agenții 2+3 sunt UI/zero-conflict.

### Wave 1 — Observabilitate + Onboarding (fundație) 🟢 LOW
**6 agenți | ~27 SP**
*Prereq: Wave 0 merged (sau în paralel — fără overlap de fișiere)*

| Agent | Item | SP | P | Fișiere |
|-------|------|----|----|--------|
| 1 | H10.24 Cost per Trace | 5 | P1 | `tracer.py`, `cost_tracker.py`, `web.py` +1 |
| 2 | H9.3b Dataset Regression | 5 | P1 | `datasets.py` NOU, `eval.py`, `web.py` +2 |
| 3 | H10.5 MCP Server Mode | 8 | P1 | `mcp/server.py` NOU COMPLET, `web.py` +1 |
| 4 | H10.8 Inbound Webhooks | 3 | P2 | `webhooks.py` NOU, `web.py` +3, `admin.js` |
| 5 | H12.2 Onboarding drop-folder | 3 | **P1** | `core/local_docs.py` NOU, `web.py` +2 (dep H8.3 ✅) |
| 6 | H12.4 Suport protocol Wyoming | 5 | **P1** | `core/voice/wyoming.py` NOU — zero conflict |

### Wave 2 — Observabilitate Avansată + Memory/KG 🟠 MEDIUM
**6 agenți | ~39 SP**
*Prereq: Wave 1 merged*

| Agent | Item | SP | P | Fișiere |
|-------|------|----|----|--------|
| 1 | H10.16 APM Dashboard | 5 | P1 | `bench.py`, `web.py` +2, `admin.js` |
| 2 | H10.17 Per-Agent Run History | 8 | P2 | `run_history.py` NOU, `web.py` +1 |
| 3 | H8.1b Entity Memory Store | 5 | P1 | `memory/entity.py` NOU, `web.py` +2 |
| 4 | H10.22 Prompt Version Control | 13 | P1 | `soul_versioning.py` NOU, `web.py` +4, `admin.js` |
| 5 | H10.29 Agent Templates | 3 | P3 | `agent_templates.py` NOU, `web.py` +2, `admin.js` |
| 6 | H12.3 KG interogabil & editabil (UX) | 8 | **P1** | `web.py` +3 (CRUD entități), `admin.js` (KG editor) — dep H8.2 ✅ |

⚠️ `admin.js` atins de agenții 1,4,5,6 — fiecare adaugă secțiuni noi, nu modifică existente. Merge secvențial pe admin.js.
⚠️ H8.1b (entity store) trebuie merged înainte de H8.3b (Wave 4) și ajută H12.6 (Wave 3).

### Wave 3 — Workflow Engine + Proactivitate 🟠 MEDIUM
**7 agenți | ~37 SP**
*Prereq: Wave 1 merged; merge intern secvențial pe engine.py*

| Agent | Item | SP | P | Note |
|-------|------|----|----|------|
| 1 | H10.12 Termination Conditions | 3 | P2 | merge PRIMUL — deblocant H10.15/H10.6 |
| 2 | H10.10 Structured Outputs | 5 | P2 | `agent.py`, `orchestrator.py`, `pipeline.py` |
| 3 | H10.13 Dynamic Router | 8 | P2 | `engine.py`, `pipeline.py` |
| 4 | H10.3 Transform Nodes | 5 | P3 | `engine.py`, `pipeline.py`, `workflows.js` |
| 5 | H10.9 Python Flow Decorator | 5 | P3 | `decorator.py` NOU — zero conflict |
| 6 | H10.2 Visual Trace Overlay | 5 | P2 | doar `workflows.js` + `observability.js` — zero conflict Python |
| 7 | H12.5 Preview / dry-run autonomie | 5 | **P2** | `inbox.py`, `tracer.py`, `web.py` +1 (dep H6.2 ✅) |

Merge intern engine.py: H10.12 → H10.10 → H10.13 → H10.3 (H10.9, H10.2, H12.5 = zero conflict).

### Wave 4 — Quality, Arena, RAG + Captură 🟠 MEDIUM-HIGH
**6 agenți | ~47 SP**
*Prereq: Wave 1+2 merged (H10.24, H8.1b, H9.3b)*

| Agent | Item | SP | P | Risc |
|-------|------|----|----|------|
| 1 | H10.19 Model Arena | 8 | P1 | `arena.py` NOU, `web.py` +2 |
| 2 | H10.23 Live Quality Monitor | 13 | P2 | ⚠️ LLM-judge per trace — async-gate obligatoriu |
| 3 | H10.25 Human Review Queue | 5 | P3 | `review_queue.py` NOU, `web.py` +2 |
| 4 | H8.3b Agentic RAG Tool | 8 | P2 | `memory/manager.py`, `orchestrator.py`, `agent.py` |
| 5 | H12.6 Update-uri KG incrementale | 5 | **P2** | `memory/entity.py` ext, `orchestrator.py` (dep H8.1b din Wave 2) |
| 6 | H12.7 Captură pasivă multi-suprafață | 8 | **P2** | `core/capture/` NOU — ⚠️ STRICT opt-in + inspectabil, nimic nu pleacă local |

### Wave 5 — Workflow Advanced + Canale 🟠 MEDIUM
**6 agenți | ~37 SP**
*Prereq: Wave 3 merged*

| Agent | Item | SP | P | Note |
|-------|------|----|----|------|
| 1 | H10.15 Critic Agent | 5 | P2 | merge PRIMUL (deblocant H10.11) |
| 2 | H10.6 Cyclic Workflow | 8 | P3 | ⚠️ invalidează validator DAG — loop detection necesar |
| 3 | H10.14 Nested Workflows | 8 | P3 | |
| 4 | H10.7 AI-Assisted Builder | 5 | P3 | `web.py` +1, `workflows.js` |
| 5 | H10.28 Agent Config Preview | 5 | P2 | `web.py` +1, `admin.js` |
| 6 | H12.11 Canale escaladare extinse | 3 | **P2** | adaptoare canal există deja, `web.py` +1 (dep H1.3 ✅) |
| 7 | H12.8 Split sateliți → server GPU | 8 | P2 | dep H12.4 (Wave 1) — `core/voice/` ext |

### Wave 6 — UX Complex + H11 Platform 🔴 HIGH
**10 agenți | ~78 SP**
*Prereq: Wave 4+5 merged; H10.20 și H10.26 review separat*

| Agent | Item | SP | P | Note |
|-------|------|----|----|------|
| 1 | H10.4 Guardrails Node | 2 | P3 | merge PRIMUL |
| 2 | H10.18 Action-Level Approval | 5 | P3 | `inbox.py`, `app.js` |
| 3 | H10.30 Write-Back Integrations | 8 | P3 | pluginuri NOI: Notion, GitHub |
| 4 | H10.11 Hierarchical Workflow | 8 | P3 | `engine.py`, `pipeline.py` |
| 5 | H10.20 Chat Channels/Rooms | 8 | P3 | ⚠️ SSE nou, concurență — risc HIGH |
| 6 | H10.26 Data Spaces | 13 | P3 | ⚠️ schimbă modelul de permisiuni memorie — risc HIGH |
| 7 | H11.4 WASM Sandbox | 8 | P3 | `sandbox.py` extins (coord. cu H12.1 din Wave 0) |
| 8 | H11.1 Desktop Tauri | 13 | P3 | `tauri/` NOU — necesită Rust toolchain |
| 9 | H11.2 Rust Extensions | 21 | P3 | `rust_ext/` NOU — necesită GPU + PyO3 |
| 10 | H11.3 SFT/GRPO Pipeline | 13 | P3 | `training/sft.py` NOU — necesită GPU |

> H11.1/H11.2/H11.3 + H12.13 sunt proiecte independente — pot fi dispatch-ate oricând există infra (GPU/Rust).

### Wave 7 — Polish + Platformă & BUG-2 🟢 LOW
**5 agenți | ~34 SP**

| Agent | Item | SP | P |
|-------|------|----|----|
| 1 | H10.21 Conversation Notes | 3 | P3 |
| 2 | H10.1 Embeddable Widget | 3 | P2 |
| 3 | H12.12 Marketplace skills semnat | 8 | P3 (dep H12.1 signing din Wave 0) |
| 4 | H12.13 Sync E2E opt-in | 13 | P3 ⚠️ E2E obligatoriu |
| 5 | BUG-2 Jest setup + componente | ≥2 | (vezi `plan-bug2-frontend-tests.md`) |

> H12.14 (model agentic fine-tuned) e overlap cu H11.3 — se livrează împreună cu H11.3 (Wave 6) sau post-1.0.

---

## C. Estimare Totală

| Categorie | Iteme | SP |
|-----------|-------|----|
| H10 Competitive Edge | 30 | 188 |
| H11 Platform Parity | 4 | 55 |
| H12 Asistent Privat & Proactiv | 14 | 89 |
| BUG-2 Frontend tests | — | 59–75 (continuu) |
| **Total v1.0** | **48 iteme** | **~332 + BUG-2** |

**Timeline (paralel maxim, ~5-6 agenți/wave):** ~22–28 zile calendar.

---

## D. Ordine de Merge

```
Wave 0 (SECURITATE P0) ─┐
                        ├→ Wave 1 → Wave 2 ─┐
                        │         ↘ Wave 3   ├→ Wave 4 ─┐
                        │                    │           ├→ Wave 6 → Wave 7
                        │         Wave 3 → Wave 5 ───────┘
H11.x + H12.13 → oricând independent (necesită GPU/Rust pt. H11.2/3)
```

### Dependențe stricte per PR:

| PR (Item) | Trebuie merged înainte de |
|-----------|--------------------------|
| **H12.1** | **toate** (P0 — wedge de securitate, fundație) |
| H10.24 | H10.16, H10.23 |
| H9.3b | H10.22, H10.25 |
| H10.12 | H10.15, H10.6 |
| H10.15 | H10.11 |
| H8.1b | H8.3b, H12.6 |
| H12.4 | H12.8 |
| H12.1 (signing) | H12.12 (marketplace semnat) |

---

## E. Recomandare de start

1. **Wave 0 imediat** — H12.1 (P0) e simultan hardening și diferențiator de piață. Nu aștepta.
2. Wave 1 poate porni în paralel cu Wave 0 (zero overlap de fișiere).
3. Restul respectă lanțul din secțiunea D.

> **Status:** DRAFT — niciun cod scris. Dispatch începe la aprobarea planului.
