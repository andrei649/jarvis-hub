# Competitor Research — Jarvis Hub vs. 8 Competitori
> Data: 2026-06-02 · Metodă: deep research multi-sursă (web search + fetch + verificare adversarială)
> Decizie anterioară: NU adoptăm tool extern — îmbunătățim Jarvis cu idei selectate.
> Output: ORIZONT 10 — Jarvis Competitive Edge (30 items noi în BACKLOG.md)

---

## Context

Jarvis Hub este un sistem de orchestrare multi-agent local-first (15 agenți, LM Studio/Ollama, FastAPI,
RTX 5090). Competitorii evaluați: Flowise, Langflow, CrewAI, AutoGen/AG2, SuperAGI, OpenWebUI,
LangSmith, Dust.tt.

Scopul acestui document: ce fac ei mai bine sau au unic, și cum putem îmbunătăți Jarvis cu acele idei,
fără a înlocui arhitectura Python-first, local-first.

---

## 1. FLOWISE (visual LLM builder, Node.js)

**Stare 2026:** v3.1.0 (mar 2026) — AgentFlow SDK, LangChain v1, HTTP security checks.

### Funcționalități unice:
- **3 moduri de builder**: Assistant (no-code), Chatflow (single-agent), AgentFlow V2 (multi-agent,
  handoffs, conditional routing, execuție paralelă)
- **Embedded chat widget** — snippet JS autogenerat, customizabil, drop-in pe orice website
- **Step-by-step trace vizual** — debugging pe canvas per execuție; noduri colorate verde/roșu
- **Input moderation + Output post-processing** ca noduri native
- **Prometheus/OpenTelemetry** pentru monitoring extern
- **REST API autogenerat** din orice flow
- **100+ noduri** (vector DBs, LLMs, tools, integrations)

### Gap-uri Jarvis vs. Flowise:
| Item | S | P | Valoare |
|------|---|---|---------|
| H10.1 — Embeddable Chat Widget | 3 | P2 | High |
| H10.2 — Visual Workflow Trace Overlay | 5 | P2 | High |
| H10.3 — Workflow Transform Nodes | 5 | P3 | Medium |
| H10.4 — Guardrails Node în Visual Builder | 2 | P3 | Medium |

---

## 2. LANGFLOW (Python-native visual builder)

**Stare 2026:** v1.9 (2026) — AI-assisted component generation, V2 Workflow API, MCP server+client.

### Funcționalități unice:
- **Componentele vizuale = cod Python real** (editabile, nu doar configurabile)
- **MCP server ȘI client** — expune flow-uri ca tool-uri MCP; consumă orice MCP server ca tool
- **Cicluri în workflow** (nu doar DAG) — loop-back edges, state management între iterații
- **AI-assisted component generation** (natural language → Python node)
- **V2 Workflow API** — trigger programatic de la sisteme externe, injectare pași la runtime
- **Agent ca tool** — un agent poate folosi alt agent ca tool

### Gap-uri Jarvis vs. Langflow:
| Item | S | P | Valoare |
|------|---|---|---------|
| H10.5 — MCP Server Mode | 8 | P1 | High |
| H10.6 — Cyclic Workflow Support | 8 | P3 | Medium |
| H10.7 — AI-Assisted Workflow Builder | 5 | P3 | Medium |
| H10.8 — Inbound Webhook Triggers | 3 | P2 | High |

---

## 3. CREWAI (Python multi-agent framework)

**Stare 2026:** v0.28 (dec 2025) + memory unification API 2026. Cel mai activ framework Python.

### Funcționalități unice:
- **4 tipuri de memorie**: Short-term (ChromaDB, per-session), Long-term (SQLite, cross-session),
  **Entity memory** (extrage entități: persoane, locuri, concepte), Contextual (auto-asamblare)
- **Hierarchical process** — manager agent auto-creat pentru coordonare, validare, redistribuire
- **Flows cu decoratori**: `@start`, `@listen(step)`, `@router` — event-driven, state persistat
- **Task callbacks** — funcție apelată la completare/eșec per task
- **Typed Pydantic outputs** — output structurat, validat tipizat (nu string brut)
- **Async kickoff** + token tracking per task

### Gap-uri Jarvis vs. CrewAI:
| Item | S | P | Valoare |
|------|---|---|---------|
| H8.1b — Entity Memory Store (ext. H8.1) | 5 | P1 | High |
| H10.9 — Python Flow Decorator API | 5 | P3 | Medium |
| H10.10 — Structured Agent Outputs (Pydantic) | 5 | P2 | High |
| H10.11 — Hierarchical Workflow Manager | 8 | P3 | Medium |

---

## 4. AUTOGEN / AG2 (Microsoft multi-agent, rebranded)

**Stare 2026:** AG2 v0.9 (apr 2025) — Group Chat + Swarm unificate. Microsoft → maintenance mode;
comunitate a forkat și continuă AG2 cu arhitectură event-driven async.

### Funcționalități unice:
- **Dynamic speaker selection**: AutoPattern (LLM decide cine vorbește), RoundRobin, Random, Manual
- **Termination conditions** — stop la keyword/LLM-judge/count
- **Human Proxy agent** — om în loop cu stall-handling și approval requests
- **Nested chats** — group chat care conține alt group chat (recursiv)
- **Conversational protocol** — tot e un mesaj tipizat (sursă/destinatar/conținut)
- **Code executor** integrat prin extensions API

### Gap-uri Jarvis vs. AutoGen:
| Item | S | P | Valoare |
|------|---|---|---------|
| H10.12 — Workflow Termination Conditions | 3 | P2 | High |
| H10.13 — Dynamic Agent Router | 8 | P2 | High |
| H10.14 — Nested Workflow Steps | 8 | P3 | Medium |
| H10.15 — Critic Agent Pattern | 5 | P2 | High |

---

## 5. SUPERAGI (autonomous agent framework — STALLED)

**Stare 2026:** Ultimul release: v0.0.14 (ian 2024). Ultimul commit: security patch ian 2025.
Proiect stagnant — NU de adoptat ca dependință. Pattern-urile de UI rămân valoroase.

### Funcționalități unice (UX patterns):
- **Action Console** — aprobare/respingere/feedback per acțiune individuală (granularitate maximă)
- **Run History cu activity feed** — timeline detaliată per agent per rulare
- **APM Dashboard** — metrici org: tokens totali, runs, cost; breakdown per model și per agent
- **Model/Tool/Knowledge Console** — analytics per layer cu token consumption
- **Toolkit Marketplace** — repository centralizat cu install, review, rating

### Gap-uri Jarvis vs. SuperAGI:
| Item | S | P | Valoare |
|------|---|---|---------|
| H10.16 — APM Dashboard | 5 | P1 | High |
| H10.17 — Per-Agent Run History | 8 | P2 | High |
| H10.18 — Action-Level Approval UI | 5 | P3 | Medium |

---

## 6. OPENWEBUI (local LLM frontend)

**Stare 2026:** Proiect activ, 50k+ stars GitHub. Features enterprise-grade pentru local LLM.

### Funcționalități unice:
- **Arena mode** — 2 modele random, side-by-side blind, vot, leaderboard agregat quality rankings
- **Functions/Pipes system** — plugin-uri Python care interceptează mesaje sau creează "modele" custom
- **Channels** — camere Discord-like cu @mention agenți, pipeline complet (tools, RAG, filters)
- **Workspace Notes** — rich editor atașat la conversații, AI rewrite in-place
- **Agentic RAG** — modelul decide autonomous când/cum să caute; retry cu query diferit
- **Chatterbox TTS** — voice cloning integrat
- **RBAC 3-level** cu groups pentru multi-user
- **Filesystem tool** pentru knowledge base (ls, cat, grep, find)

### Gap-uri Jarvis vs. OpenWebUI:
| Item | S | P | Valoare |
|------|---|---|---------|
| H10.19 — Model Arena / Blind Comparison | 8 | P1 | High |
| H8.3b — Agentic RAG Tool (ext. H8.3) | 8 | P2 | High |
| H10.20 — Chat Channels / Rooms | 8 | P3 | Medium |
| H10.21 — Conversation Notes | 3 | P3 | Medium |

---

## 7. LANGSMITH (observability & eval platform)

**Stare 2026:** Disponibil în AWS Marketplace. Pairwise annotation queues (feb 2026). Expanding
pentru autonomous agent monitoring.

### Funcționalități unice:
- **Trace hierarchy completă** — run → chain → LLM call → tool call, cu timing, tokens, cost per span
- **Prompt Hub** — versionare prompturi cu commit history, deploy, rollback, colaborare
- **Annotation queues** — route trace-uri la revieweri umani cu rubric; cozi pairwise (A vs B)
- **Online evaluation** — evaluatori pe traffic live în real-time, detectează drift imediat
- **Dataset versioning** — seturi de test versionate, eval history per dataset version
- **LLM-as-judge** — criterii configurabile pentru scoring automat
- **CI/CD integration** — eval gate în deploy pipeline
- **Proactive alerts** — alertă când metrici degradează

### Gap-uri Jarvis vs. LangSmith:
| Item | S | P | Valoare |
|------|---|---|---------|
| H10.22 — Agent Prompt Version Control | 13 | P1 | High |
| H9.3b — Dataset Regression Tracking (ext. H9.3) | 5 | P1 | High |
| H10.23 — Live Quality Monitor | 13 | P2 | High |
| H10.24 — Cost Tracking per Agent | 5 | P1 | High |
| H10.25 — Human Review Queue | 5 | P3 | Medium |

---

## 8. DUST.TT (enterprise agent builder)

**Stare 2026:** $40M raised. 2025 product update: triggers, Spaces, MCP integrations, write-back.

### Funcționalități unice:
- **Spaces** — containere date cu permisiuni (Open/Restricted), asignate per team/agent
- **Natural language scheduling** — "run every Monday morning" → cron automat
- **Webhook triggers** — agenți activați din sisteme externe
- **Write-back integrations** — agenții scriu înapoi în Notion, Jira, GitHub, Google Drive
- **Behavior preview** — testezi configurația agentului înainte de deploy live
- **Agent templates** — configurații pre-built pentru use case-uri comune, clonabile
- **Dual-layer permissions** — date accesabile vs. cine folosește agentul (separat)
- **Fleet management** — sute de agenți cu governance centralizată

### Gap-uri Jarvis vs. Dust.tt:
| Item | S | P | Valoare |
|------|---|---|---------|
| H10.26 — Data Spaces / Agent Data Scope | 13 | P3 | Medium |
| H10.27 — NL Scheduling | 3 | P2 | Medium |
| H10.28 — Agent Config Preview | 5 | P2 | High |
| H10.29 — Agent Templates Library | 3 | P3 | Medium |
| H10.30 — (merge cu H10.8) Inbound Webhook Triggers | — | — | — |

---

## Teme Cross-Cutting (≥4 competitori din 8)

| Temă | Competitori | Gap Jarvis | Prioritate |
|------|-------------|------------|------------|
| **Prompt/config versioning** | Flowise, LangSmith, Dust, CrewAI | SOUL.md = fișier Git, fără A/B sau rollback prin UI | P1 |
| **Cost tracking per request** | LangSmith, SuperAGI, Flowise, Dust | Tokens tracked, $ cost nu există | P1 |
| **MCP Server mode** | Langflow, Dust, OpenWebUI | Jarvis e doar client MCP | P1 |
| **Model quality comparison** | OpenWebUI, LangSmith, Flowise | Bench = latency; 0 quality scores | P1 |
| **Agentic RAG** | OpenWebUI, Langflow, CrewAI | Recall injectat fix, modelul nu decide | P2 |
| **Embeddable interface** | Flowise, Dust, OpenWebUI | Fără embed extern | P2 |
| **Human-in-loop la action level** | SuperAGI, AutoGen, Dust | Task-level gating; nu action-level | P2 |
| **Termination conditions în workflows** | AutoGen, CrewAI, Langflow | WorkflowEngine fără condiție de stop | P2 |

---

## Surse

- [Flowise Documentation](https://docs.flowiseai.com/)
- [Flowise vs Langflow — SFAI Labs](https://sfailabs.com/guides/flowise-vs-langflow)
- [Dify vs Flowise vs Langflow 2026 — ToolHalla](https://toolhalla.ai/blog/dify-vs-flowise-vs-langflow-2026)
- [CrewAI Memory — Official Docs](https://docs.crewai.com/en/concepts/memory)
- [CrewAI Flows — Official Docs](https://docs.crewai.com/en/concepts/flows)
- [AG2 v0.9 Release](https://docs.ag2.ai/latest/docs/blog/2025/04/28/0.9-Release-Announcement/)
- [AG2 GroupChat](https://docs.ag2.ai/latest/docs/user-guide/advanced-concepts/groupchat/groupchat/)
- [SuperAGI Action Console](https://superagi.com/docs/Core%20Components/Agents/action_console/)
- [SuperAGI APM](https://web.superagi.com/docs/)
- [OpenWebUI Features](https://docs.openwebui.com/features/)
- [OpenWebUI RAG](https://docs.openwebui.com/features/chat-conversations/rag/)
- [OpenWebUI RBAC](https://docs.openwebui.com/features/authentication-access/rbac/)
- [LangSmith Observability](https://docs.langchain.com/langsmith/observability)
- [LangSmith Annotation Queues](https://docs.smith.langchain.com/evaluation/how_to_guides/human_feedback/annotation_queues)
- [Dust.tt 2025 Product Update](https://dust.tt/blog/2025-dust-product-update-recap)
- [Langflow MCP Integration](https://www.langflow.org/blog/introducing-mcp-integration-in-langflow)
- [CrewAI vs AutoGen 2026 — Kanerika](https://kanerika.com/blogs/crewai-vs-autogen/)
- [Multi-Agent Frameworks 2026 — GuruSup](https://gurusup.com/blog/best-multi-agent-frameworks-2026)
