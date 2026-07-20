# Owner Portfolio Control Center — Gap Audit and Bounded Design

**Date:** 2026-07-20

**Status:** Proposed after repository audit; design only, no runtime changes

**Product:** Jarvis Hub / Nerva

**Decision:** The Owner Portfolio Control Center is a Jarvis capability and HUD surface. It is not a separate application.

## 1. Goal

Give the owner one governed view of all configured personal and business projects while reusing Jarvis' existing execution, autonomy, memory, and approval primitives.

The control center must answer five questions without inventing data:

1. What outcomes are active across the portfolio?
2. What changed since the last review?
3. Which agents and missions are working on each outcome?
4. Which decisions require the owner's attention now?
5. Which source document is authoritative for each status claim?

All configured projects may continue to make automated progress. Human attention remains a separate, explicitly bounded resource.

### 1.1 Product fit

This capability is on-mission rather than adjacent scope. `NERVA_VISION.md` explicitly places projects inside the persistent intelligence layer spanning the owner's digital and physical world, while `MOONSHOT.md` defines Jarvis/Nerva as the governed interface to that world. The missing piece is a structured, inspectable project/outcome projection over primitives that already exist.

## 2. Non-goals

- Build a second dashboard, project-management product, or agent runtime.
- Replace `BACKLOG.md`; it remains the product-development priority source for Jarvis itself.
- Replace Mission Workspaces or the autonomy queue.
- Overload the existing Finance/market meaning of "portfolio"; financial holdings remain a separate domain that may link to Owner Portfolio projects later.
- Treat semantic memory chunks as structured project state.
- Copy private source documents into the public repository.
- Hard-code an owner's projects, income target, employer, family, paths, or priorities.
- Send messages, publish, spend money, or modify external systems without the existing approval and Action Kernel path.
- Write back into owner source documents in the first delivery slice.

## 3. Audit evidence — what already exists

| Need | Existing primitive | Evidence | Reuse decision |
|---|---|---|---|
| Long-running execution | Mission Workspaces | `agents/core/autonomy/missions.py`, `agents/core/routers/missions.py` | Reuse; link projects to missions instead of creating a second executor. |
| Governed actions and human decisions | Autonomy `TaskQueue`, Decision Inbox, Action Kernel | `agents/core/autonomy/queue.py`, `agents/core/routers/autonomy.py`, `frontend/src/gap.tsx` | Reuse; portfolio decisions may point to autonomy tasks. |
| Multi-agent execution | Workflow DAG/runtime | `agents/core/workflows/pipeline.py`, `agents/core/workflows/engine.py` | Reuse workflow runs and lineage; do not create a portfolio executor. |
| Basic project tasks | Hephaestus PM skill | `skills/pm/main.py` | Treat as a legacy/narrow adapter; do not make it the portfolio source of truth. |
| Daily activity story | Today in Jarvis | `agents/core/memory/timeline.py`, `GET /api/dashboard/today`, `TodayPanel` | Extend by projection later; do not fork another activity feed. |
| System north star | Accepted autonomous actions and counter-metrics | `agents/core/observability/north_star.py` | Keep unchanged; portfolio outcome metrics are a separate layer. |
| Private document ingestion | Local Docs configured-folder indexer | `agents/core/local_docs.py`, `agents/core/routers/onboarding.py` | Reuse extraction/config patterns, not its unstructured memory representation. |
| Per-agent knowledge scopes | Data Spaces | `agents/core/data_spaces.py` | Reuse where possible, but portfolio reads must fail closed because Data Spaces currently defaults open when unassigned. |
| Weekly priorities | Pepper's declared role | `agents/pepper/SOUL.md` | Pepper owns review cadence and attention-budget presentation, not strategic scoring. |
| Strategic scenarios | Athena's declared role | `agents/athena/SOUL.md` | Athena produces evidence-backed option scoring; Jarvis remains orchestrator. |
| Career-asset review | Athena's quarterly portfolio-review mandate | `agents/athena/SOUL.md` | Extend the owner model; do not create a separate career-portfolio silo. |
| Financial holdings | Market snapshot and Finance mode | `agents/core/market/analyze.py`, `agents/core/routers/market.py`, `frontend/src/modes4.tsx` | Keep domain-specific. Owner Portfolio may consume a bounded financial projection, never duplicate holdings logic. |
| User-facing workspaces | Missions and Today panels | `frontend/src/gap.tsx` | Promote one first-class Portfolio mode inside Jarvis; do not introduce another frontend app. |
| Browser/mobile contract | Shared API plus parity ledger | `mobile/PARITY.md` | Ship browser read surface and record an explicit mobile decision in the same implementation PR. |

The local server at `127.0.0.1:8080` was not running during the audit, so this document makes no claim about current owner runtime data, configured folders, or live Mission contents. The gap conclusion is based on repository models, routes, and HUD wiring.

A static inventory of backend route decorators found no route whose path expresses `project`, `portfolio`, `priority`, or `objective`. The tracked project status reports 398 total routes; the exact total varies with mounted/generated surfaces, but the absence of an Owner Portfolio route is consistent across both audits.

### 3.1 Current Mission limitation

A `Mission` has `title`, `goal`, `status`, `plan`, step/time budgets, timestamps, artifacts, and events. It does not have project ownership, portfolio priority, KPI definitions, source provenance, review cadence, a human-attention marker, or links to other missions/tasks.

A Mission represents a bounded execution effort. A Portfolio Project represents a durable owner outcome. They must remain different concepts.

The step budget is enforced, but the time budget is currently observed as `over_time` rather than automatically terminating the Mission. Portfolio health must not present the time limit as a hard execution stop until that runtime behavior exists.

### 3.2 Current autonomy-task limitation

A `Task` has an agent, action kind, title, payload, risk tier, execution state, attention mode, origin, decision metadata, and result. It does not have a first-class project link. The `/tasks` dashboard currently synthesizes `project` from `kind`, which is display compatibility rather than a durable project relationship.

### 3.3 Current PM-skill limitation

`skills/pm/main.py` stores only `project`, `title`, and `status`. It is useful for narrow physical-project task lists but has no objective, KPI, provenance, governance, budget, agent ownership, decision model, or HUD/API surface.

### 3.4 Current document-ingestion limitation

Local Docs recursively extracts supported files and stores chunks in memory with `source`, relative file, and chunk number. That enables recall but cannot answer structured portfolio questions safely. It has no incremental project projection, source-revision conflict signal, or authoritative-field semantics.

### 3.5 Current HUD limitation

Jarvis exposes Missions, Today, tasks, decisions, and system north-star metrics separately. No surface groups them by durable owner outcome, reports portfolio staleness/conflicts, or identifies the next human decision per project.

Those owner-relevant surfaces are mostly buried in Console → **Autonomy & Agents**. The main rail and `modeComponent()` have no Portfolio destination, and Cockpit's visible decision column is not hydrated from the real approval queue. The Morning Brief frontend/backend contract is also misaligned, so seed/demo priorities must never be presented as live owner priorities.

The current mobile parity ledger lists the Tasks board but has no explicit Missions or Today row. The portfolio implementation must add its own honest parity row and must not assume those adjacent browser surfaces already exist on mobile.

## 4. Bounded domain model

### 4.1 `PortfolioProject`

```text
PortfolioProject
  id: integer
  slug: string, unique
  title: string
  domain: string
  status: proposed | active | waiting | blocked | completed | archived
  human_attention: none | review | decision | meeting
  source_key: configured-folder key
  source_ref: relative logical reference, never an absolute path
  source_hash: content/revision hash | null
  source_state: current | stale | conflict | unavailable
  last_synced_at: timestamp | null
  last_reviewed_at: timestamp | null
  review_due_at: timestamp | null
  created_at: timestamp
  updated_at: timestamp
```

Unknown values stay `null`; the system must not infer a KPI, priority, confidence, or deadline merely to fill the HUD.

### 4.2 `PortfolioObjective`

```text
PortfolioObjective
  id
  project_id | null              # null = owner/portfolio-level outcome
  parent_objective_id | null
  title
  metric_key | null
  baseline_value | null
  current_value | null
  target_value | null
  unit | null
  deadline | null
  confidence: low | medium | high | null
  source_ref | null
```

The existing Jarvis product north star remains unchanged. Owner objectives and outcomes are a separate, explicitly sourced layer; neither is used as a silent substitute for the other.

### 4.3 `PortfolioMetric`

```text
PortfolioMetric
  id
  objective_id
  value
  observed_at | null
  source_ref | null
  confidence: low | medium | high | null
```

The first slice stores only explicit source values. Derived values must carry a derivation label and input provenance.

### 4.4 `PortfolioLink`

Use a join table instead of changing Mission or Task schemas in the first slice:

```text
PortfolioLink
  project_id
  objective_id | null
  resource_type: mission | workflow_run | autonomy_task | pm_task | artifact
  resource_id: string
  created_at
```

This keeps existing runtimes byte-identical while enabling portfolio projections.

### 4.5 `PortfolioDecision`

```text
PortfolioDecision
  id
  project_id
  title
  state: open | deferred | resolved | cancelled
  due_at | null
  autonomy_task_id | null
  source_ref | null
  created_at
  resolved_at | null
```

If a decision results in an action, execution still passes through the autonomy queue, policy, contracts, Action Kernel, approval path, and audit log.

### 4.6 `PriorityCommitment` and `AgentAssignment`

```text
PriorityCommitment
  id
  target_type: project | objective | mission | autonomy_task
  target_id
  rank
  horizon: today | week | quarter
  rationale | null
  review_at | null
  source_ref | null

AgentAssignment
  project_id | null
  objective_id | null
  mission_id | null
  agent_id
  role: accountable | responsible | consulted | informed
  capacity_note | null
```

These records type the accountability that currently exists only in agent prompts. They do not grant tool or data access; execution authority still comes from the existing policy, capability, contract, and Data Space layers.

### 4.7 `TodayProjection` (read model, not another store)

```text
TodayProjection
  generated_at
  selected_commitments[]
  calendar_constraints[]
  active_missions[]
  running_tasks[]
  approvals_and_blockers[]
  rationale[]
```

This projection explains what should receive attention today and why. It reuses existing rows and APIs; it does not replace the retrospective `Today in Jarvis` timeline or create another task queue.

## 5. Source-of-truth contract

### 5.1 Configuration

The owner configures source roots by key in local settings, following the existing Local Docs pattern:

```json
{
  "portfolio.sources": {
    "owner-projects": "<private local path>"
  }
}
```

HTTP requests select a configured key. They never supply a raw filesystem path. Absolute paths never appear in API responses or public logs.

### 5.2 Structured source adapter

Add a read-only adapter protocol:

```text
PortfolioSourceAdapter.discover(source_key) -> project descriptors
PortfolioSourceAdapter.read(project_ref) -> normalized snapshot + provenance
PortfolioSourceAdapter.diff(previous, current) -> explicit changes/conflicts
```

The initial filesystem adapter recognizes an owner-configured project-control convention. The adapter must:

- read only supported control documents;
- preserve relative source references and hashes;
- make repeated syncs idempotent;
- report missing/malformed fields rather than inventing them;
- leave source files untouched;
- treat the configured source as authoritative when it conflicts with cached portfolio projections;
- keep full document text in the owner source and optional memory index, not duplicate it in `portfolio.db`.

Semantic Local Docs ingestion may run alongside structured sync. It is not the structured-state source.

### 5.3 Writeback

Writeback is explicitly deferred. A later slice may propose a source-document patch only when all of the following exist:

1. backup/archive-before-write;
2. exact diff preview;
3. source-revision conflict check;
4. explicit owner approval;
5. Action Kernel and audit record;
6. rollback artifact.

## 6. Privacy and domain separation

Portfolio state is personal by default and opt-in.

- `portfolio.enabled` defaults to `false`.
- A source has an explicit agent allowlist; missing scope fails closed to the prime orchestrator/owner surface rather than inheriting Data Spaces' default-open behavior.
- Employer-confidential, business, family, and general-personal domains remain separately scoped.
- Cross-domain synthesis receives only explicit, bounded projections; it never grants one domain agent raw access to another domain's documents.
- Strict-local agents retain their no-cloud guarantee.
- API and HUD projections omit absolute paths, raw source text, private recipients, credentials, and hidden source metadata.
- Public Souls and repository docs contain no owner-specific project details. Personal mappings live in local configuration or gitignored local overlays.

## 7. Responsibility model

| Role | Responsibility |
|---|---|
| Jarvis | Prime orchestration, portfolio aggregation, routing, final owner brief. |
| Pepper | Weekly review cadence, attention-budget/WIP presentation, meeting and decision surfacing. |
| Athena | Evidence-backed strategic comparison and transparent confidence scoring. |
| Domain agent | Executes or proposes work within the project's explicit data scope. |
| Mission Workspace | Runs a step-budgeted, time-observed multi-step effort linked to one project. |
| Autonomy task | Executes or requests approval for one governed action. |
| Owner | Sets objectives, resolves strategic conflicts, approves consequential actions, and changes priority policy. |

No agent may silently rewrite priority, objective, or source truth.

## 8. Priority and human-attention policy

Visibility, automated execution, and human WIP are separate dimensions:

- every configured project may remain visible;
- any number may have low-risk automated work in progress, subject to existing budgets;
- only a configurable number may consume owner attention during a review period;
- the HUD shows the configured limit and refuses to present a hidden/default number as an owner decision.

Suggested local setting:

```text
portfolio.human_wip_limit
```

Strategic ranking is transparent. A future scorer may accept explicit inputs such as expected impact, time to first signal, confidence, owner hours, urgency, and strategic value. Missing inputs remain missing. The scorer exposes inputs and formula; the model does not emit an unexplained rank.

The selected rank/horizon/rationale is stored as a `PriorityCommitment`, not folded into an execution task. This allows every project to remain visible while only a bounded set consumes owner attention.

## 9. Read-only API slice

Proposed API, all owner/user guarded:

```text
GET  /api/portfolio
GET  /api/portfolio/{project_id}
GET  /api/portfolio/governance
GET  /api/portfolio/today
POST /api/portfolio/sync                 # explicit configured source key
POST /api/portfolio/{project_id}/review  # records review metadata only
```

Mutation routes that create Missions, change priority, or resolve decisions are separate later slices and remain governed. The initial list/detail payload includes:

- project state and source freshness;
- explicit metrics;
- linked mission/task counts and statuses;
- next open human decision;
- review-due signal;
- no raw source text or absolute path.

## 10. HUD slice

Add one first-class **Portfolio** mode to Jarvis' existing rail and `modeComponent()` switch. This is a Jarvis surface, not another application. It should reuse the existing component/data-loading patterns and may expose a compact link or summary in Console → **Autonomy & Agents**, but the primary control center must not remain hidden in the Console overlay.

Before the structured backend lands, an honest proof view may fan in existing Today, north-star, Missions, running tasks, approvals, interrupt-budget, and autonomy-policy APIs. It must label that interim section **Needs attention**, not **Top priorities**, because the current models do not carry strategic priority or outcome semantics.

Minimum presentation:

- project title, domain, status, priority, and source freshness;
- current explicit KPI values, with unknown shown honestly;
- active/blocked Mission and autonomy-task counts;
- next human decision or meeting;
- owner-attention tag;
- stale/conflict/unavailable source warnings;
- configured human-WIP usage.

The mode is read-first. Actions link to existing Missions and Decision Inbox controls. New execution buttons are not added in the first slice.

The implementation PR must update:

- HUD route coverage/parity tests;
- `mobile/PARITY.md` with an explicit read-only/desktop-only/mobile-follow-up decision;
- generated OpenAPI types and committed HUD bundle when applicable.

## 11. Delivery slices

Each implementation slice is one bounded branch/PR and starts from current `origin/main`.

1. **OPC-0 — audit/design:** this document only; no runtime change.
2. **OPC-1 — store + source adapter:** default-off Project/Objective/Priority/Assignment schema, idempotent read-only sync, provenance and conflict tests.
3. **OPC-2 — read API:** list/detail/governance/Today projections, auth/parity snapshots, no raw-path leaks.
4. **OPC-3 — first-class HUD mode:** read-only Portfolio rail destination, honest empty/disabled/stale states, real approvals/decisions, and mobile-parity decision.
5. **OPC-4 — execution lineage:** link existing Missions, workflow runs, autonomy tasks, and PM tasks without changing their execution semantics.
6. **OPC-5 — governance cadence:** Pepper weekly review projection and Athena strategy input; transparent owner-attention limit, assignments, and decision brief.
7. **OPC-6 — governed writeback, optional:** separate design and owner approval; backup, diff, conflict check, Action Kernel, audit, rollback.

The official backlog identifier and roadmap placement remain TBD until active draft PRs that lock `BACKLOG.md` are merged or closed.

## 12. Acceptance criteria

### Functional

- A configured source can be synced repeatedly without duplicate projects or metrics.
- Every displayed status and metric has an explicit source or is visibly derived.
- Jarvis' product north star and the owner's outcome metrics remain distinct and correctly labelled.
- Portfolio list/detail links existing Missions and tasks without duplicating their runtimes.
- The governance response identifies open owner decisions and attention demand.
- Disabled/unconfigured sources return honest empty/disabled states.

### Safety and privacy

- Default behavior is byte-identical while `portfolio.enabled=false`.
- No endpoint accepts a raw source path.
- No API/HUD payload exposes an absolute path or raw private document text.
- Missing per-source agent scope fails closed.
- No source document is modified in OPC-1 through OPC-5.
- Any consequential action still passes existing governance and audit boundaries.

### Verification

- Store migration, idempotence, source-hash, conflict, malformed-source, and corrupt-DB tests.
- Route-auth, route-surface, OpenAPI, and HUD parity tests.
- Data-scope tests proving cross-domain raw access is denied.
- Mission/task linking tests proving existing state machines remain unchanged.
- Frontend tests for disabled, empty, live, stale, conflict, unknown-KPI, and attention-limit states.

## 13. Collision snapshot and safe recording path

At the initial audit snapshot, no repository branch, open issue, or open PR was named for an Owner Portfolio capability. Four draft PRs (`#692`–`#695`) touched shared planning/status files, including `BACKLOG.md`; `#692` merged while this design was being prepared, leaving `#693`–`#695` open and draft. Under the repository's draft-PR lock rule, shared files touched by those drafts remain read-only to this work.

Runtime collision risk is also domain-specific: `#695` touches Finance balance/live-data seams, while `#693` touches WorldView, OpenAPI snapshots, and mobile parity. Owner Portfolio must not modify those seams until the drafts merge, close, or explicitly release the files.

Therefore OPC-0 records the audited design in this unique spec file only. It does not edit `BACKLOG.md`, `STATUS.md`, frontend files, runtime files, or any active agent worktree. Roadmap recording must happen after the shared-file locks clear, in the first implementation PR or an explicitly coordinated planning commit.

## 14. Rollback

OPC-0 is a documentation-only branch. Runtime slices must remain removable by:

- disabling `portfolio.enabled`;
- unregistering the portfolio router/mode;
- leaving Mission, autonomy, memory, PM, and source documents untouched;
- preserving `portfolio.db` for export or deleting it only through an explicit owner data action.
