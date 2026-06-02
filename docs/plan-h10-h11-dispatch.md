# Plan Dispatch H10 + H11 — Drum spre v1.0.0

> ⚠️ **SUPERSEDED (2026-06-02)** — acest plan acoperea doar H10+H11 și **sărea peste ORIZONT 12**,
> inclusiv **H12.1 (singurul P0 din backlog)**. Planul autoritar pentru v1.0 este acum
> **[`plan-v1-dispatch.md`](plan-v1-dispatch.md)** (H10 + H11 + H12). Păstrat ca referință istorică.

> Generat: 2026-06-02 · Read-only până la aprobare · Status: **DRAFT (superseded)**
> Analiză completă a swim lanes, dependențe și wave dispatch multi-agent.

---

## Stare de bază confirmată

- `agents/web.py` — 98 rute, 2135 linii (hotspot principal)
- `workflows/engine.py` + `pipeline.py` — motor DAG, atins de 7+ iteme H10
- `observability/tracer.py` — baza pentru cost/quality tracking
- MCP există doar ca **client** (`mcp/client.py`) — serverul lipsește complet
- Nu există: `arena`, `nl_schedule`, `entity.py`, `webhooks`, widget, chat rooms, data spaces

---

## A. Swim Lane Analysis

### A1. Fișiere critice (hotspot-uri)

| Fișier | Iteme care îl ating | Risc |
|--------|---------------------|------|
| `agents/web.py` | 20+ iteme (endpoint-uri noi) | 🔴 MAXIM |
| `workflows/engine.py` | H10.3, 4, 6, 7, 11, 12, 13, 14, 15 | 🔴 ÎNALT |
| `workflows/pipeline.py` | H10.3, 6, 10, 11, 12, 13, 14, 15 | 🔴 ÎNALT |
| `agents/core/orchestrator.py` | H10.10, 23, 27, H8.3b | 🟠 MEDIU |
| `agents/web/static/admin.js` | H10.8, 16, 22, 28, 29 | 🟠 MEDIU |
| `agents/core/observability/tracer.py` | H10.17, 23, 24 | 🟠 MEDIU |
| Fișiere **NOI** (zero conflict) | H10.1, 5, 8, 9, 21, 22, 27, 29, H11.x | 🟢 ZERO |

### A2. Iteme cu fișiere NOI (zero conflict, paralelizabile oricând)

| Item | Fișiere noi |
|------|------------|
| H10.5 MCP Server Mode | `agents/core/mcp/server.py` |
| H10.27 NL Scheduling | `agents/core/autonomy/nl_schedule.py` |
| H10.1 Embeddable Widget | `agents/core/widget.py` |
| H8.1b Entity Memory Store | `agents/core/memory/entity.py` |
| H10.22 Prompt Version Control | `agents/core/soul_versioning.py` |
| H10.23 Live Quality Monitor | `agents/core/quality_monitor.py` |
| H10.9 Python Flow Decorator | `agents/core/workflows/decorator.py` |
| H10.29 Agent Templates | `agents/core/agent_templates.py` |
| H10.21 Conversation Notes | `agents/core/notes.py` |
| H10.8 Inbound Webhooks | `agents/core/webhooks.py` |
| H10.30 Write-Back Integrations | `agents/core/plugins/notion_writeback.py`, `github_issues.py` |
| H11.1 Desktop Tauri | `tauri/` (director nou) |
| H11.2 Rust Extensions | `rust_ext/` (director nou) |
| H11.3 SFT/GRPO Pipeline | `agents/core/training/sft.py` |

### A3. Dependențe obligatorii (lanț de blocare)

```
H10.24 (Cost per Trace)       → H10.16 (APM Dashboard), H10.23 (Quality Monitor)
H9.3b  (Dataset Regression)   → H10.22 (Prompt VC), H10.25 (Human Review)
H10.12 (Termination Conds)    → H10.15 (Critic Agent), H10.6 (Cyclic)
H10.15 (Critic Agent)         → H10.11 (Hierarchical)
H8.1b  (Entity Memory Store)  → H8.3b (Agentic RAG)
H11.x                         → independent oricând (proiecte separate)
```

---

## B. Wave Dispatch Plan

### Wave 1 — Observabilitate + Quick Wins
**5 agenți | ~24 SP | Risc: 🟢 LOW**
*Prereq: main la zi*

| Agent | Item | SP | Fișiere atinse |
|-------|------|----|--------------------|
| 1 | H10.24 Cost per Trace | 5 | `tracer.py`, `cost_tracker.py`, `web.py` +1 |
| 2 | H9.3b Dataset Regression | 5 | `datasets.py` NOU, `eval.py`, `web.py` +2 |
| 3 | H10.5 MCP Server Mode | 8 | `mcp/server.py` NOU COMPLET, `web.py` +1 |
| 4 | H10.8 Inbound Webhooks | 3 | `webhooks.py` NOU, `web.py` +3, `admin.js` |
| 5 | H10.27 NL Scheduling | 3 | `autonomy/nl_schedule.py` NOU, `orchestrator.py` minimal |

### Wave 2 — Observabilitate Avansată + Memory
**5 agenți | ~34 SP | Risc: 🟠 MEDIUM**
*Prereq: Wave 1 merged*

| Agent | Item | SP | Fișiere atinse |
|-------|------|----|----------------|
| 1 | H10.16 APM Dashboard | 5 | `bench.py`, `web.py` +2, `admin.js` |
| 2 | H10.17 Per-Agent Run History | 8 | `run_history.py` NOU, `web.py` +1 |
| 3 | H8.1b Entity Memory Store | 5 | `memory/entity.py` NOU, `web.py` +2 |
| 4 | H10.22 Prompt Version Control | 13 | `soul_versioning.py` NOU, `web.py` +4, `admin.js` |
| 5 | H10.29 Agent Templates | 3 | `agent_templates.py` NOU, `web.py` +2, `admin.js` |

⚠️ `admin.js` atins de agenții 1, 4, 5 simultan — fiecare adaugă secțiuni noi, nu modifică existente.

### Wave 3 — Workflow Engine Extensions
**6 agenți | ~29 SP | Risc: 🟠 MEDIUM**
*Prereq: Wave 1 merged; merge intern secvențial pe engine.py*

| Agent | Item | SP | Note |
|-------|------|----|------|
| 1 | H10.12 Termination Conditions | 3 | merge PRIMUL — deblocant |
| 2 | H10.10 Structured Outputs | 5 | `agent.py`, `orchestrator.py`, `pipeline.py` |
| 3 | H10.13 Dynamic Router | 8 | `engine.py`, `pipeline.py` |
| 4 | H10.3 Transform Nodes | 5 | `engine.py`, `pipeline.py`, `workflows.js` |
| 5 | H10.9 Python Flow Decorator | 5 | `decorator.py` NOU — zero conflict |
| 6 | H10.2 Visual Trace Overlay | 5 | doar `workflows.js` + `observability.js` — zero conflict Python |

Merge order intern: H10.9 și H10.2 → H10.12 → H10.10 → H10.13 → H10.3

### Wave 4 — Quality, Arena, RAG
**4 agenți | ~34 SP | Risc: 🟠 MEDIUM-HIGH**
*Prereq: Wave 1+2 merged*

| Agent | Item | SP | Risc special |
|-------|------|----|--------------|
| 1 | H10.19 Model Arena | 8 | `arena.py` NOU, `web.py` +2 |
| 2 | H10.23 Live Quality Monitor | 13 | ⚠️ LLM-as-judge per trace — risc latență, async-gate obligatoriu |
| 3 | H10.25 Human Review Queue | 5 | `review_queue.py` NOU, `web.py` +2 |
| 4 | H8.3b Agentic RAG Tool | 8 | `memory/manager.py`, `orchestrator.py`, `agent.py` |

### Wave 5 — Workflow Advanced
**5 agenți | ~31 SP | Risc: 🟠 MEDIUM**
*Prereq: Wave 3 merged*

| Agent | Item | SP | Note |
|-------|------|----|------|
| 1 | H10.15 Critic Agent | 5 | merge PRIMUL |
| 2 | H10.6 Cyclic Workflow | 8 | ⚠️ invalidează validatorul DAG — loop detection necesar |
| 3 | H10.14 Nested Workflows | 8 | |
| 4 | H10.7 AI-Assisted Builder | 5 | `web.py` +1, `workflows.js` |
| 5 | H10.28 Agent Config Preview | 5 | `web.py` +1, `admin.js` |

### Wave 6 — UX Complex + H11
**10 agenți | ~78 SP | Risc: 🔴 HIGH**
*Prereq: Wave 4+5 merged; H10.20 și H10.26 se review-uiesc separat*

| Agent | Item | SP | Note |
|-------|------|----|------|
| 1 | H10.4 Guardrails Node | 2 | merge PRIMUL |
| 2 | H10.18 Action-Level Approval | 5 | `inbox.py`, `app.js` |
| 3 | H10.30 Write-Back Integrations | 8 | pluginuri NOI: Notion, GitHub |
| 4 | H10.11 Hierarchical Workflow | 8 | `engine.py`, `pipeline.py` |
| 5 | H10.20 Chat Channels/Rooms | 8 | ⚠️ SSE nou, concurență — risc HIGH |
| 6 | H10.26 Data Spaces | 13 | ⚠️ schimbă modelul de permisiuni memorie — risc HIGH |
| 7 | H11.4 WASM Sandbox | 8 | `sandbox.py` extins |
| 8 | H11.1 Desktop Tauri | 13 | `tauri/` NOU — necesită Rust toolchain |
| 9 | H11.2 Rust Extensions | 21 | `rust_ext/` NOU — necesită GPU + PyO3 |
| 10 | H11.3 SFT/GRPO Pipeline | 13 | `training/sft.py` NOU — necesită GPU |

> H11.1/H11.2/H11.3 sunt proiecte complet independente — pot fi dispatch-ate oricând.
> H11.2 (Rust) și H11.3 (SFT) necesită infrastructură specială (GPU, Rust toolchain).

### Wave 7 — Polish + BUG-2
**4 agenți | ~16 SP | Risc: 🟢 LOW**

| Agent | Item | SP |
|-------|------|----|
| 1 | H10.21 Conversation Notes | 3 |
| 2 | H10.1 Embeddable Widget | 3 |
| 3 | H10.30 restante | 8 |
| 4 | BUG-2 Jest setup + componente simple | ≥2 |

---

## C. Estimare Totală

| Categorie | SP | Zile calendar (paralel maxim) |
|-----------|----|-------------------------------|
| H10 Competitive Edge (30 iteme) | 188 | ~18–22 |
| H11 Platform Parity (4 iteme) | 55 | paralel cu H10 |
| BUG-2 Frontend tests | 59–75 | continuu pe toate wave-urile |
| **Total** | **~300** | **~20–25 zile** |

---

## D. Ordine de Merge (rezumat)

```
Wave 1 → Wave 2 → Wave 3 (paralel cu Wave 2 după H10.12)
       ↘ Wave 4 (după Wave 2)
Wave 3 → Wave 5
Wave 4+5 → Wave 6 → Wave 7
H11.x → oricând independent
```

### Dependențe stricte per PR:

| PR (Item) | Trebuie merged înainte de |
|-----------|--------------------------|
| H10.24 | H10.16, H10.23 |
| H9.3b | H10.22, H10.25 |
| H10.12 | H10.15, H10.6 |
| H10.15 | H10.11 |
| H8.1b | H8.3b |

---

> **Status:** DRAFT — niciun cod scris. Dispatch începe la aprobarea planului.
