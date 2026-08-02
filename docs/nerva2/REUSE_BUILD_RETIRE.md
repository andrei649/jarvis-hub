# Nerva 2.0 — Reuse, integrate, build, refactor, retire

Parent: #758 · Program: #757

This register prevents Nerva 2.0 from rebuilding mature infrastructure under new names. Every architectural proposal must map to one of these decisions and cite a migration path.

## Decision vocabulary

- **REUSE** — keep the current subsystem and extend through its public contract.
- **INTEGRATE** — adopt a maintained external system through a bounded adapter.
- **BUILD** — create Nerva-specific intellectual property that is not adequately supplied elsewhere.
- **REFACTOR** — preserve behavior/data while changing structure or contract.
- **RETIRE** — remove only after callers, data and rollback requirements are proven absent or migrated.

## Decision register

| Capability | Decision | Existing/external substrate | Nerva-specific work |
|---|---|---|---|
| LLM inference | REUSE + INTEGRATE | existing providers, local runtimes and fallback routing | Cortex policy and measured selection |
| Speech-to-text | INTEGRATE | Whisper/Parakeet-class engines through adapters | privacy/routing/room context, not ASR research |
| Text-to-speech | INTEGRATE | local/cloud TTS providers | presence-aware delivery and voice identity policy |
| Embeddings | INTEGRATE | maintained embedding models | benchmark selection and migration, not training |
| Vector storage | REUSE | current memory/vector substrate | lifecycle, provenance and deletion correctness |
| Knowledge graph storage | REUSE + REFACTOR | current bi-temporal KG | Atlas ontology, identity and query contracts |
| Workflow scheduling | REUSE | existing scheduler; evaluate Temporal/Prefect only for demonstrated gaps | Night Shift semantics and governance |
| Messaging/event transport | REUSE initially | current in-process/event mechanisms | introduce NATS/Redis Streams only if measured reliability requires it |
| Authentication/identity | REUSE initially / INTEGRATE if needed | current auth posture; mature IdP options | household roles and local ownership policy |
| Observability | INTEGRATE | OpenTelemetry/Prometheus/Grafana/Loki where operationally justified | Nerva decision/action/evidence semantics |
| Home automation | INTEGRATE | Home Assistant, MQTT, Matter, ESPHome, Homebridge | Atlas house model, policy, memory and reasoning |
| Cameras | INTEGRATE | Frigate/ONVIF/RTSP and maintained vision models | event correlation, privacy, Atlas links and governance |
| Media control | INTEGRATE | platform/device APIs | unified `present()` policy, privacy and session etiquette |
| Browser/desktop automation | INTEGRATE + REFACTOR | Playwright/accessibility/VM drivers | capability hierarchy, kernel mediation and verification |
| Action Kernel / Ultron | REUSE | current kernel, contracts, approvals, budgets, audit | broaden adoption; do not replace |
| Verification Fabric | REUSE + REFACTOR | reality harness and capability-state model | common evidence contract across all Nerva work |
| Specialist agents | REUSE selectively + REFACTOR | 17 current agents | agents become candidates/roles behind Cortex; no agent sprawl |
| Current router | REFACTOR | model/agent fallback and runtime | Cortex typed decisions, scoring and replay |
| Cortex | BUILD | partial routing/budget/eval substrates | meta-decision engine and explicit trade-off accounting |
| Atlas | BUILD on REUSE | KG, WorldView, Signal Layer, topology | canonical personal reality model |
| Episodes | BUILD on REUSE | turns, memories, events, reflection | first-class experience lifecycle |
| Howard / Digital Twin | BUILD | persona, preferences, feedback | calibrated prediction with explanations and correction |
| Night Shift | BUILD on REUSE | scheduler, budgets, ToolRPC, approvals, verification | approved-goal work discovery and morning evidence brief |
| Reflection engine | REFACTOR + BUILD | DailyReflector, background review, consolidation | one governed outcome-learning contract |
| World Model | BUILD | Atlas snapshots and domain calculators | isolated scenarios, uncertainty and sensitivity analysis |
| Skills SDK | REFACTOR + BUILD | registry, loader, marketplace, signing, quarantine | versioned manifests, conformance and acquisition loop |
| Research Lab | BUILD on REUSE | eval store, CI, model telemetry | continuous real-task benchmark and migration recommendations |
| HUD/mobile | REUSE + REFACTOR | current experience surfaces | shared executive evidence model; no rewrite |
| Duplicate plugin abstractions | RETIRE after migration | identified during call-site audit | one Skills SDK contract |
| Prompt-only long-term state | RETIRE as authority | ad hoc summaries/prompts | Atlas/Episodes/Howard become typed sources |
| Unbounded agent-to-agent chatter | RETIRE | any workflows lacking measurable purpose | bounded Cortex plans and explicit candidates |
| Demo data presented without state label | RETIRE | seed/demo surfaces | mandatory live/seed/demo provenance |

## External integration policy

An external dependency is preferred when it is actively maintained, has a stable API, can run within Nerva's privacy posture, and does not weaken Ultron governance. Integration must be replaceable through an adapter and must expose health, version and failure state.

External projects never own:

- owner identity and consent;
- Atlas's canonical personal model;
- Episodes and derived personal experience;
- Howard's preference hypotheses;
- Nerva authority, approvals or audit;
- the final decision about what capability may act.

## Retirement gate

Nothing is retired until:

1. all callers and stored data are enumerated;
2. migration and rollback are tested;
3. behavior parity or an intentional breaking decision is documented;
4. telemetry shows the old path is unused;
5. the relevant epic and #757 are updated.
