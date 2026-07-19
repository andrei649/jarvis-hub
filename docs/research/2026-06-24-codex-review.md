# Codex fresh-eyes advice for Jarvis Hub

Date: 2026-06-24

Scope note: I reviewed the public repo shape and source through the GitHub
connector because the local command runner in this Codex desktop session was
blocked by a Windows runner permission error (`CreateProcessAsUserW failed: 5`).
That means I could not run `git fetch`, `git rebase`, tests, or local grep from
this session. Treat this as a careful code-and-doc review, not a verified build
report.

## Executive read

Jarvis Hub is much more mature than the average personal-agent repo. The core
ideas are coherent, the local-first posture is real in code, and there is serious
work in places many projects skip: plugin egress controls, audit logs, route
parity guards, HUD parity ledgers, token storage, autonomy risk gating, and
local-only agent enforcement.

The biggest opportunity is no longer "add more features." The next jump is to
turn an impressive owner-operated system into a trustworthy, understandable,
recoverable product. In plain terms: pick one proactive loop, prove it for a
real user, make onboarding boringly smooth, make safety posture visible, and
keep docs/version state from drifting.

My friendly diagnosis:

- Strength: the architecture has a real spine: orchestrator, routers, agents,
  memory, plugin governance, autonomy, and HUD all have recognizable contracts.
- Strength: security is not bolted on at the very end. Several safeguards are
  already in the hot path.
- Risk: the repo has outgrown human short-term memory. Docs, version counters,
  tests counts, route counts, and feature status now drift in multiple places.
- Risk: the operator has a lot of power but not enough "one screen of truth"
  about what is live, mocked, local, cloud, configured, broken, or safe.
- Risk: the system may be optimized for the builder, while the next milestone
  needs proof from someone who is not the builder.

## What is already strong

1. Local-only enforcement is real

`agents/core/llm/hybrid_router.py` has explicit local-only floors for `frigga`,
`ultron`, and `howard`. The router fails closed for those agents instead of
silently falling back to cloud. This is one of the most important trust
properties in the project.

2. Plugin egress is unusually thoughtful

`agents/core/plugin_gate.py`, `agents/core/http_client.py`, and
`agents/core/security/ssrf.py` form a decent policy stack: manifest-level
permissions, strict default egress, local/LAN handling, dynamic-domain controls,
and SSRF validation for fetch flows. Many personal assistant projects never get
this far.

3. Refactoring discipline is visible

`agents/web.py` has been reduced from a route god-object into domain routers,
with route parity and OpenAPI parity tests guarding behavior. The tests in
`tests/test_route_parity_guard.py` and `tests/test_openapi_parity_guard.py` are
exactly the kind of safety net that makes large refactors survivable.

4. The HUD parity idea is excellent

`tests/test_hud_v2_parity.py`, `docs/design/HUD_V2_REMAINING.md`, and
`mobile/PARITY.md` create a habit: backend capabilities should not silently
escape the UI. That is a very healthy pattern for this repo.

5. The autonomy model has a sane center of gravity

`agents/core/autonomy/policy.py` uses reversibility, blast radius, signal
quality, money caps, and approval outcomes. That is a good conceptual model:
read-only and reversible work can move, irreversible work should ask.

6. Runtime data relocation exists

`agents/core/paths.py` centralizes runtime state under `JARVIS_HOME` /
`JARVIS_MEMORY_DIR`, with a repo-local fallback. That is a good foundation for
making distribution safer.

7. Security scanning has depth

`agents/core/security/scanner.py` handles secrets, PII, entropy, Romanian CNP,
and IBAN-like checks. `agents/core/security/audit.py` has chained audit records
and optional HMAC. These are strong product ingredients.

## Strategic advice

### 1. Make "trusted personal AI OS" smaller before making it bigger

The repo has a moonshot-quality vision, but the next proof point should be
narrow:

- One proactive loop.
- One user who is not the builder.
- One week of successful operation.
- One visible value metric.

Example loops:

- Morning brief that turns mail/calendar/news into 3 useful actions.
- Family-safe local memory and reminders through Frigga.
- Finance/health/check-in observer that only notifies when thresholds matter.
- Meeting-prep loop that reads calendar context and drafts exact prep.

The point is not to reduce the ambition. It is to force the ambition through a
small enough doorway that it becomes undeniable.

### 2. Prioritize the first 10 minutes

The project has many advanced systems, but a new user needs a guided path:

- Is my local model reachable?
- Which agents are local-only?
- Are tokens configured?
- Is runtime data outside the repo?
- Is audit HMAC enabled?
- Is egress strict?
- Which integrations are live vs unavailable?
- Is the HUD showing live data or seed/mock data?

An onboarding wizard would probably create more product value than another
backend surface right now. This is already tracked in the backlog as H23.20, and
I would treat it as central, not decorative.

### 3. Make safety visible, not just implemented

The code has meaningful safety controls, but the user needs to see the current
state:

- Guardrails mode: WARN / REDACT / BLOCK.
- Strict egress: on/off.
- Audit HMAC: enabled/missing.
- Runtime data root: inside repo/outside repo.
- Cloud fallback: never/on-demand/always.
- Local-only proof for Frigga/Ultron/Howard.
- MCP mutating tools: disabled/enabled.
- Token posture: static env tokens vs token store.
- Trusted proxy mode: disabled/enabled.

This should be a single readiness/trust board in the HUD, not a set of scattered
docs and environment variables.

### 4. Finish partials before greenfield

`BACKLOG.md` already says this, and I strongly agree. The best next work is not
new domains; it is closing the gaps in H23 and the HUD/mobile parity tails.

The highest-leverage partials I saw:

- Health/readiness endpoint and HUD board.
- Release engineering and service templates.
- User docs and trust/security docs.
- Model pinning/reproducibility.
- Loop/budget detection.
- HUD live/seed visibility.
- OpenAPI types for the frontend.
- Mobile parity task assignment for unscheduled rows.

### 5. Move from "capabilities" to "action governance"

There are multiple governance layers now:

- Plugin manifest permissions.
- Plugin HTTP egress.
- Autonomy risk policy.
- MCP route tools.
- Payments approval.
- Signal governance.
- Sandbox execution.
- Tool RPC.
- Writebacks.

These should eventually read as one "Action Kernel": one place where actions
are classified, previewed, approved, executed, audited, retried, and revoked.
That may already be part of the moonshot roadmap, but the code is ready for the
concept to become explicit.

## Code-level findings and advice

### A. Documentation and status drift is now a real product risk

Several important files disagree:

- `README.md` still advertises v0.10.0 and about 2,400 tests.
- `STATUS.md` says v0.11.0, 2,609 passed / 2 skipped, 304 routes.
- `BACKLOG.md` mentions about 2,768 passed / 6 skipped.
- `NERVA.md` still references v0.10.0 and about 299 routes.
- `agents/web.py` declares FastAPI app version `0.5.0-beta`.
- Some docs still mention older agent counts or older workspace paths.

Advice: create one generated status block, or one tiny script that updates
version, route count, agent count, and test count in the visible docs. Do not
make humans hand-sync this forever. This drift is not embarrassing; it is a sign
the project is alive. But now it needs a single source of truth that actually
feeds the public docs.

### B. `agents/web.py` still has hidden product semantics

The route split is a big improvement, but `agents/web.py` still holds security
posture, lifespan startup, MCP wiring, runtime state warnings, CSP, token
fallbacks, rate limiting, status helpers, and many singleton-ish objects.

Advice:

- Keep shrinking it by extracting security/auth posture into a small module with
  tests.
- Extract system readiness/status probes away from the route file.
- Keep route additions out of `web.py`, as the repo already requires.

Specific note: `_sys_info()` appears to return confident defaults such as a host
and GPU if probes fail. For a trust/readiness screen, "unknown" is safer than a
confident fallback that may be wrong.

### C. App version in code is stale

`agents/web.py` uses:

`FastAPI(title="Jarvis", version="0.5.0-beta", ...)`

That conflicts with docs around v0.11.0. If anything consumes OpenAPI metadata,
this will leak stale product identity.

Advice: source this from one version module or release metadata file.

### D. Context window setting is seeded but not consistently used

`agents/core/settings_db.py` seeds `memory.context_window = 6`.

In `agents/core/orchestrator.py`, `_call_agents_parallel` appears to fetch
history with a hard-coded `last_n=6`.

Advice: use the runtime setting consistently. This is a small fix with a nice
benefit: HUD settings become real, not decorative.

### E. Per-agent timeout is hard-coded

`agents/core/orchestrator.py` uses a blanket per-agent timeout around 120s in
parallel calls.

Advice: fold this into the H23 budget work. Different routes and agents deserve
different ceilings: quick chat, deep research, local-only private agents,
background autonomy, and eval runs should not all share one invisible value.

### F. Interaction metadata may mislabel channels

`agents/core/orchestrator.py` records interaction metadata with a hard-coded
`"channel": "web"` in at least one path.

Advice: pass the real origin through from web, Telegram, Discord, CLI, or
autonomy. This matters for analytics, local/cloud ratios, trust reporting, and
future product metrics.

### G. `Agent.synthesize()` may ignore the routed model

In `agents/core/agent.py`, `process()` appears to use the routed model from
`select_backend()`. In `synthesize()`, the route call returns backend and route
name, but the generated call appears to keep using the original configured model
instead of the routed model.

Advice: check this path with a focused test. If synthesis ignores routing, some
summary/fusion responses may use the wrong local/cloud model or policy.

### H. Public code still contains personal routing triggers

`agents/core/router.py` contains direct personal-name routing terms for family
or private contexts.

Advice: if this repo is public, move personal trigger terms to a local/private
overlay, similar to `SOUL.local.md` and `HEARTBEAT.local.md`. The router can keep
generic family/private semantics while personal names live outside public source.

### I. Howard memory prompt deserves stronger provenance boundaries

`agents/core/agent.py` injects Howard RAG shots into prompts from memory text.
That is powerful, but memories are also untrusted input.

Advice:

- Delimit memory snippets clearly as retrieved context, not instructions.
- Include source, age, and confidence where available.
- Keep a small cap on snippets and length.
- Consider scanning retrieved snippets with the same injection scanner used for
  other inputs.

### J. Memory recall is strong but needs user-facing provenance

`agents/core/memory/manager.py` supports fused vector and graph recall with
fallback behavior. The architecture is good.

Advice: in the HUD and agent responses, make recall explain itself:

- What memory source was used?
- How old was it?
- Was it vector, graph, keyword, or fused?
- Can the user forget or correct it?

This matters especially for personal AI. Trust is often built by showing why
the system remembered something, not just by remembering it.

### K. Auto-generated skills should be treated as code creation

`agents/core/settings_db.py` defaults `skills.auto_generate` to true, and
`agents/core/agent.py` nudges agents to emit `[learn: ...]`.

Advice: make sure skill generation has human review, sandboxing, audit, and
clear provenance before it becomes available to future runs. It is a great
feature, but it is also a path where model text can become durable behavior.

### L. Guardrails default WARN is friendly but weak for design partners

`agents/core/security/guardrails.py` can WARN, REDACT, or BLOCK. The default in
settings is WARN.

Advice: keep WARN for local development if you like, but provide a "Design
Partner / Hardened" profile that switches sensitive routes toward REDACT or
BLOCK, requires audit HMAC, keeps strict egress on, and disables risky mutating
surfaces by default.

### M. Audit HMAC should become a readiness item

`agents/core/security/audit.py` supports optional HMAC through
`JARVIS_AUDIT_KEY`. That is good.

Advice:

- Show "audit HMAC missing" as a trust/readiness warning outside pure localhost
  development.
- Document that retention pruning re-anchors the chain, so old tamper evidence
  before the cutoff is intentionally no longer verifiable unless exported.
- Surface `/api/security/audit/verify` as a Trust chip, as already suggested in
  `docs/design/HUD_V2_REMAINING.md`.

### N. MCP mutating tools need a very loud switch

`agents/core/mcp/route_tools.py` has a cautious mutating allowlist and keeps it
off by default. Good.

Advice: keep this posture. If mutating MCP tools are enabled, the HUD should
show it like a breaker switch, with recent calls and token identity visible.
The code comments already note that in-process MCP calls do not pass through the
full HTTP context/rate-limit/proxy-origin path.

### O. Plugin permission split could confuse future maintainers

`agents/core/plugin_gate.py` has an eligibility-style check, while
`agents/core/http_client.py` performs stricter runtime egress enforcement.
This is workable, but the naming can mislead readers into thinking `check_call`
fully validates egress.

Advice:

- Rename or document `check_call` as an eligibility check unless a target domain
  is supplied.
- Add a static test that plugin code uses `PluginHTTPClient` instead of raw
  `httpx` / `requests`, except for explicit allowlisted files.

### P. Many plugins are served to `all`

`agents/core/plugin_gate.py` lists several plugins with broad
`agents_served=["all"]`, including sensitive or external-write surfaces.

Advice: for the design-partner/hardened profile, move toward least privilege per
agent. The system already has agent identity; use it as a policy boundary.

### Q. Plugin manager has hard-coded LAN defaults

`agents/core/plugin_manager.py` includes defaults like
`http://192.168.1.100:...` for some bridge-style plugins.

Advice: public/default config should prefer blank/not-configured over a
specific LAN assumption. A readiness screen can then say "WhatsApp bridge not
configured" instead of trying a stale address.

### R. Frontend live data still tolerates shape drift

`frontend/src/api/live.ts` uses `// @ts-nocheck`, broad `any`, independent
fetches, and seed fallbacks. This was sensible during a port, but it can hide
backend/frontend shape mismatches.

Advice:

- Keep the no-break behavior for users.
- Add visible LIVE/SEED indicators everywhere a panel can fall back.
- Generate OpenAPI types and slowly remove `@ts-nocheck` from live wiring.
- Add a "failed live fetches" debug drawer so seed data does not look like truth.

### S. HUD V2 depth is good, but the tail still matters

`docs/design/HUD_V2_REMAINING.md` says the big control gap closed, but the tail
still includes plugin-gated modes, live/seed chips, OpenAPI types, self-hosted
fonts, locality surfaces, and audit verify surfacing.

Advice: finish that tail before adding more HUD modes. A complete cockpit beats
a wider cockpit with hidden mock zones.

### T. Mobile parity is visible but unscheduled in places

`mobile/PARITY.md` is a good ledger. Several rows are tracked as not started
with no task assigned.

Advice: decide which mobile gaps matter for the next user proof. Do not fill all
mobile gaps by default, but give task IDs to the few that support the chosen
proactive loop.

### U. Admin stats may not match current Agent attributes

In `agents/core/routers/admin.py`, `admin_agents_stats` appears to read fields
such as `agent.status`, `agent.model`, and `agent.tier`. In the inspected
`agents/core/agent.py`, the agent object seems centered on `config`, `name`,
`role`, and backend behavior rather than those direct attributes.

Advice: add a focused test for the admin stats endpoint and make the output
explicitly derive from `agent.config` or a stable DTO.

### V. Mixed import namespaces are a long-term trap

Some router/admin code comments mention importing via `core.*` because of
singleton split issues with `agents.core.*`.

Advice: after the current refactor wave settles, make namespace consistency a
dedicated cleanup. Duplicate module identity can create spooky state bugs:
settings, registries, plugin managers, and audit singletons are especially
vulnerable.

### W. Autonomy risk classification is good but should be previewable

`agents/core/autonomy/policy.py` is understandable and testable. The user-facing
missing piece is a preview:

- Why is this action tier 2?
- Which word or field triggered the tier?
- What would make it safer?
- What budget remains today?
- Was this auto-approved by policy, or manually approved?

Advice: add a policy explanation endpoint or panel. This makes autonomy feel
less magical and easier to trust.

### X. Interrupt budget is fixed in code

`agents/core/autonomy/worker.py` has `INTERRUPT_BUDGET_PER_DAY = 4`, while
settings also contain `autonomy.interrupt_budget`.

Advice: verify the setting is actually wired where the worker is constructed.
If it is not, wire it. If it is, add a small comment or test so future readers
do not think the constant is the real source of truth.

### Y. Data root inside repo is allowed for compatibility, but scary for users

`agents/core/paths.py` intentionally defaults to `memory_logs` inside the repo.
That preserves behavior, but personal runtime data inside a source checkout is
easy to zip, commit, or sync by mistake.

Advice: keep the fallback, but make onboarding strongly recommend `JARVIS_HOME`
outside the repo and show a persistent warning until it is moved.

## Suggested near-term sequence

### 1. One-day cleanup PR

- Fix public doc/version/test-count drift.
- Update FastAPI app version metadata.
- Make README point to `STATUS.md` for volatile counts.
- Add a small "status sync" script if possible.

### 2. Small correctness PR

- Use `memory.context_window` instead of hard-coded history size.
- Check and fix `Agent.synthesize()` routed-model behavior.
- Pass real channel metadata into interaction records.
- Verify autonomy interrupt budget uses settings.

### 3. Trust/readiness PR

- Add a readiness endpoint that reports model reachability, data root posture,
  audit HMAC, strict egress, guardrails mode, local-only proof, token posture,
  cloud fallback, and live/seed state.
- Surface it in HUD Trust/Admin as a compact board.

### 4. Product proof PR

- Pick one proactive loop.
- Add a demo data mode.
- Add a runbook for that loop.
- Add one metric: "accepted useful actions per week" or similar.

### 5. Frontend hardening PR

- Add visible LIVE/SEED chips per panel.
- Start OpenAPI type generation.
- Remove `@ts-nocheck` from one live-data module at a time.

## Backlog prioritization advice

If I were steering the next sprint, I would not start another big capability.
I would choose:

1. H23.11 health/readiness/signal handling/log rotation.
2. H23.18 user docs and H23.19 trust/security docs.
3. H23.20 first-run onboarding wizard.
4. H23.1 loop/budget detection.
5. H23.2 model pinning/reproducibility.
6. HUD live/seed and audit verify surfacing from the V2 remaining tail.
7. One design-partner proof loop.

This is the path from "impressive machine" to "someone else can rely on this."

## Things I would not worry about first

- I would not chase perfect architecture before user proof.
- I would not try to close every mobile parity row immediately.
- I would not add more agent personalities until the current ones have visible
  reliability and role boundaries.
- I would not broaden cloud integrations until the local-only/trust board is
  obvious and boring.
- I would not treat marketing pages as the main gap; a demo loop is stronger
  than a landing page right now.

## Final friendly note

The repo has a real heartbeat. The rough edges are mostly the rough edges of a
large system that started as a personal command center and is now trying to
become a product. That is a good problem.

My strongest advice: make the next milestone about trust and proof, not breadth.
Let Jarvis do one narrow thing so well, so transparently, and so safely that a
non-builder can feel the value without needing to understand the architecture.
