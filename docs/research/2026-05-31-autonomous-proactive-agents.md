# Research: Jarvis Autonom & Proactiv — arhitectură cu surse

> Data: 2026-05-31 · Bază pentru ORIZONT 6 (vezi `BACKLOG.md` + `docs/superpowers/specs/2026-05-31-horizon6-autonomous-jarvis-design.md`)
> Metodă: deep-research (5 unghiuri, fan-out web search + fetch + verificare). Multe pagini-editor au dat 403 la fetch → cifrele exacte sunt direcțional solide, magnitudine aproximativă; mecanismele structurale sunt confirmate de surse primare (GitHub).

## TL;DR

Nu construi o buclă "auto-prompt" stil AutoGPT (intră în cicluri, arde bani). Construiește un **ambient agent**: declanșat de **trigger-e** (cron + evenimente) → pune muncă într-o **coadă cu state-machine** → execută autonom acțiunile **reversibile/sigure** → ridică în **decision inbox-ul de pe Telegram** doar acțiunile ireversibile/costisitoare, cu **buget de întreruperi**. Modelul OpenClaw (heartbeat ~30 min citește `HEARTBEAT.md` → act/notify) = exact ce Jarvis are deja.

## 1. Ambient agent + agent inbox
- Ambient agents ascultă un flux de evenimente, lucrează concurent, ies la suprafață doar când contează. [LangChain](https://blog.langchain.com/introducing-ambient-agents/)
- Trei patternuri HITL: **Notify** / **Question** / **Review**. [LangChain](https://blog.langchain.com/introducing-ambient-agents/)
- Agent Inbox = UI tip email care centralizează acțiunile în așteptare de la mai mulți agenți. [agent-inbox](https://github.com/langchain-ai/agent-inbox)
- 4 răspunsuri: `accept` / `edit` / `response` / `ignore`; `interrupt()` + `Command(resume=)` peste un checkpointer care persistă starea. [agent-inbox](https://github.com/langchain-ai/agent-inbox), [agents-from-scratch](https://github.com/langchain-ai/agents-from-scratch)
- ⚠️ La resume nodul se poate re-executa de la început → efectele secundare DUPĂ `interrupt()`.

## 2. Politica echilibrată: când întrerupe vs. acționează
- Buget realist: **~3–5 notificări nesolicitate/zi**; peste → cade retenția. [tianpan](https://tianpan.co/blog/2026-05-13-background-agents-notification-budget-attention-economy) O întrerupere = ~23 min recuperare. [CMU HCII](https://hcii.cmu.edu/news/event/paying-attention-interruption-human-centered-approach-intelligent-interruption)
- Scară de autonomie **per acțiune**: L0 Observe → L1 Inform → L2 Recommend → L3 Act-cu-aprobare → L4 Act-cu-veto → L5 Autonom. Stai pe L1–L3. [devops.com](https://devops.com/when-should-a-devops-agent-act-without-human-approval/), [Sheridan-Verplank](https://petrowiki.org/Levels_of_automation)
- Scoring pe 4 factori: **reversibilitate · blast radius · signal quality · time sensitivity**. [devops.com](https://devops.com/when-should-a-devops-agent-act-without-human-approval/)
- Two-way door (reversibil) → decide repede; one-way door (ireversibil) → aprobare. [Amazon framing](https://blog.kindel.com/2019/06/27/one-way-and-two-way-doors/)
- Anthropic: ~0.8% acțiuni ireversibile, ~73% cu om în buclă; încrederea urcă 20%→40% cu experiența → autonomia se ridică treptat. [measuring-agent-autonomy](https://www.anthropic.com/news/measuring-agent-autonomy), [building effective agents](https://www.anthropic.com/research/building-effective-agents)
- Bani: cap per-acțiune + plafon zilnic. [autonomy budget](https://medium.com/@bhagyarana80/the-autonomy-budget-a-safe-way-to-ship-agents-8a695038c784)
- Heuristică: anulabil de om în <5 min = low-risk; restore DB / rollback = Tier 3+. [mindstudio](https://www.mindstudio.ai/blog/classify-ai-agent-actions-by-risk)

## 3. Self-tasking (fără să o ia razna)
- Muncă proactivă din **trigger-e externe** (cron + event), nu auto-prompting. [event-driven](https://atlan.com/know/event-driven-architecture-for-ai-agents/), [ProactiveBench](https://arxiv.org/abs/2410.12361)
- Coadă cu state-machine strict: `todo → running → done|failed`, fără re-intrare. [nightshift](https://github.com/johndaskovsky/nightshift)
- Plafoane dure: retry ~3, timeout/task, PID lock, ferestre de timp, log append-only. [ai-night-shift](https://github.com/JudyaiLab/ai-night-shift)
- Lecția AutoGPT/BabyAGI: bucle nelimitate = cicluri + cost runaway; ambele au abandonat framing-ul. [toms hardware](https://www.tomshardware.com/news/autonomous-agents-new-big-thing), [vibeagentmaking](https://vibeagentmaking.com/blog/autogpt-got-100k-stars-and-then-what/)
- gptme: două cozi — **manual** + **generated**. [gptme template](https://github.com/gptme/gptme-agent-template)

## 4. Ritual zilnic + batch approval + preference learning
- Morning brief proactiv care **pre-generează muncă peste noapte**. [OpenClaw morning brief](https://github.com/hesamsheikh/awesome-openclaw-usecases/blob/main/usecases/custom-morning-brief.md) Khoj: automations cron în fusul orar local, livrate ca newsletter. [khoj](https://docs.khoj.dev/features/automations/)
- Batch approval: 10–50 acțiuni cu rationale, aprobate într-o ședință (10–30 h/lună economisite). [getclaw](https://getclaw.sh/blog/human-in-the-loop-ai-agents-approvals-2026)
- Preference learning: reject = semnal; semnale implicite (corecții, override, abandon) → întreabă tot mai rar. [feedback loop](https://medium.com/@yadav.navya1601/creating-a-feedback-loop-integrating-user-insights-into-ai-agent-development-301232d9e6db), [arXiv](https://arxiv.org/abs/2602.16173)
- Decision journal: loghează decizie + raționament + predicție + confidence înainte de rezultat. [fs.blog](https://fs.blog/decision-journal/)
- Proactivitate utilă doar dacă e ne-intruzivă și negociabilă. [ACM](https://dl.acm.org/doi/10.1145/3706598.3713357), [arXiv](https://arxiv.org/abs/2509.24073)

## 5. Lecții OSS
- **OpenClaw**: heartbeat citește `HEARTBEAT.md` → act/notify; memorie+skills ca Markdown; capability matrix per sesiune. [github](https://github.com/openclaw/openclaw), [akamai](https://www.akamai.com/blog/security/clawdbot-openclaw-practical-lessons-building-secure-agents)
- **gptme**: workspace pe git; două cozi; `lessons/` consultat înainte de acțiune. [template](https://github.com/gptme/gptme-agent-template)
- **QwenPaw**: `.learnings/` cu auto-reflecție; memorie zilnică promovată în long-term; memorie per user. [issue 578](https://github.com/agentscope-ai/QwenPaw/issues/578)
- **OpenHands**: agent = funcție pură event-history → next-event; event stream tipizat; runtime sandboxed. [arXiv](https://arxiv.org/abs/2407.16741), [docs](https://docs.openhands.dev/openhands/usage/architecture/runtime)
- **Khoj**: pipeline modular, connectors pluggable, indexare locală. [github](https://github.com/khoj-ai/khoj)
- **Leon**: căi de execuție multiple (skill determinist vs. agent-mode). [docs](https://docs.getleon.ai/architecture)
- **Anthropic**: cel mai simplu lucru care merge; puține tool-uri workflow-shaped, namespaced, token-efficient. [building agents](https://www.anthropic.com/research/building-effective-agents), [writing tools](https://www.anthropic.com/engineering/writing-tools-for-agents)

## 6. Mapare pe building-block-urile Jarvis
| Strat nou | Cărămidă existentă | De adăugat |
|---|---|---|
| Trigger layer | APScheduler / HEARTBEAT.md (H3.5) | event watchers (email/calendar/finanțe/health) |
| Task queue | SQLite (checkpoint.py, settings_db) | tabel `tasks` + worker + retry cap + PID lock |
| Risk gate | guardrails.py + plugin_gate.py (H4.9) | risk tag per acțiune + politica reversibil→act / money→ask |
| Decision Inbox | Telegram channel (H1.2) | butoane inline + buget 3–5/zi |
| Daily ritual | gateway + TTS (H1.1) | morning brief + evening retro + batch-approve view |
| Preference learning + journal | Learning Loop (H3.4) + Neo4j (H3.2) | scor preferințe din approve/reject |
| Night shift | sandbox Docker (H4.8) | fereastră de timp + batch pe task-uri reversibile |

## 7. Încredere & limite
- **Înaltă** (surse primare fetchuite): mecanica agent-inbox, state-machine night-shift, model OpenClaw heartbeat, gptme/QwenPaw learning stores, OpenHands event-sourcing.
- **Direcțional solidă** (snippet-uri, pagini 403): buget 3–5/zi, ~0.8% ireversibile + ratchet încredere Anthropic, 23 min recuperare.
- **De verificat la build:** re-execuția nodului la `resume` în LangGraph (dacă folosim acel mecanism vs. coada proprie).
