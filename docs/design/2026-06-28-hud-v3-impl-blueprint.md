# HUD v3 → `frontend/src` — Implementation Blueprint

> **Status:** planning artifact for the hud-v3 port (PR 1 of the series).
> **Source of truth:** the vendored prototype `docs/design/hud-v3/` (an executable design spec —
> open `index.html` in any browser). **The one rule:** the prototype *is* the design contract; match
> it, don't reinterpret it (`docs/design/hud-v3/HANDOVER_CLAUDE_CODE.md` §3).
> **Stable target brief:** `docs/design/SINGLE_PAGE_HUD_BRIEF.md` (2026-06-27).
> **Completion gate:** `tests/test_hud_v2_parity.py` — every human-facing route resolves to a real
> `frontend/src` surface or an explicit `NOT_IN_HUD`.

This blueprint is the bridge from the prototype to the production HUD (`frontend/src`, served prebuilt
at `/v2`). The production HUD **already exists** and is substantially wired (it is "hud-v2"); v3 is the
next design iteration. So most rows below are an **evolve-in-place** of an existing component, not a
from-scratch port. Each row ships as **its own PR**, green on `tsc --noEmit` + vitest + the
`hud-v2-build` stale-bundle guard.

---

## 0 · The three anchors (unchanged from the handover)

1. **Design source of truth** — `docs/design/hud-v3/` (vendored prototype). Every surface is
   demonstrated; `docs/design/hud-v3/v3-api.jsx` maps each surface to its real route.
2. **The contract** — `frontend/src/api/{client,actions,live,loaders,types}.ts` (same-origin fetch;
   the three auth tiers open / user-guard / admin-guard; the honest LIVE / SEED / OFFLINE rule).
3. **The completion gate** — `tests/test_hud_v2_parity.py`.

---

## 1 · Path-rename ledger (prototype → real backend)

The prototype's `v3-api.jsx` binds a few routes under shorthand names. Reconciled against the
authoritative route surface (`tests/_snapshots/route_surface.json`), **4 need a rename**; everything
else is already exact. Encode these renames in `frontend/src/api/actions.ts` / `live.ts` — never carry
the prototype's shorthand into production.

| Prototype path (`v3-api.jsx`) | Real backend route | Parity surface |
|---|---|---|
| `GET /autonomy/missions` | **`GET /api/missions`** | autonomy |
| `POST /autonomy/missions/{id}/{action}` | **`POST /api/missions/{id}/{start\|pause\|resume\|complete\|cancel}`** | autonomy |
| `GET /governance` | **`GET /api/security/governance`** | trust |
| `GET /posture` | **`GET /api/security/posture`** | trust |
| `GET /loop-breaker` | **`GET /api/security/loop-breaker`** (+ `POST …/reset`) | trust |

**Already exact (no rename):** `/status`, `/tasks`, `POST /autonomy/tasks/{id}/decision`,
`/autonomy/observer`, `/api/a2a/peers`, `/api/security/audit/{intent,verify}`, `/api/agents`,
`GET·POST /autonomy/policy` *(shipped PR #418)*, `/api/memory/search`, `/chat` (+`/chat/stream`),
`/api/analytics/locality`, `GET /autonomy/interrupts` *(shipped PR #418)*, `/api/security/kill-switch`,
`/api/metrics/{kernel,capabilities}`.

> **Backend gap closed.** The only two genuinely-missing endpoints from the v3 compatibility review —
> `POST /autonomy/policy` (per-agent AUTO/ASK/OFF) and `GET /autonomy/interrupts` (interrupt budget) —
> shipped in **PR 0 (#418)**. The remaining v3 work is the frontend itself.

---

## 2 · Surface → component → endpoint → acceptance → parity map

Sequenced by ORIZONT-24 phase. **"Target"** names the existing `frontend/src` file to evolve (or
`NEW` when the surface has no home yet). **"Parity row"** is the surface every listed route already
maps to in `tests/test_hud_v2_parity.py` (so no new parity entries are needed — the gate stays green by
construction).

### Phase B — substrate (P0, do first)

| # | Surface (prototype) | Target (`frontend/src`) | Endpoint(s) — real | Acceptance | Parity row |
|---|---|---|---|---|---|
| B1 ✅ | Decision Inbox (`v3-decisions.jsx`) | `gap.tsx` `DecisionInboxPanel` (Autonomy cluster, first) | `GET /autonomy/tasks?status=blocked` · `POST /autonomy/tasks/{id}/decision` `{action}` | **The resolve action was genuinely missing** — the queue was *read* (network fan) but never resolvable. Now accept/reject/defer on the blocked queue; empty = honest "all clear". **Shipped PR 12.** | `cockpit` / `autonomy` |
| B2 | Action Kernel syscall table (`v3-modes2.jsx` AI-OS) | `gap.tsx` Kernel tile (exists) → Observe | `GET /api/metrics/kernel` | grant/deny/queue counts per kind from real meter; 0-state shows "no decisions yet", not fabricated rows | `observe` |
| B3 ✅ | Verification Fabric readiness (`v3-modes2.jsx` AI-OS) | `gap.tsx` `ReadinessPanel` (Trust cluster) | `GET /api/metrics/capabilities` | SEAM→WIRED→VERIFIED→GA ladder from registry; **never fake VERIFIED** (honesty contract #4) — `harness_pending` renders "wired, not yet proven". **Shipped PR 2.** | `observe` |
| B4 | Kill-switch (live + halts) | `gap.tsx` / `modes.tsx` Trust STOP (exists) | `GET·POST /api/security/kill-switch` (POST admin) | Engage is admin-guarded (in-app token, not `window.prompt`); engaged ⇒ writes blocked, surface honest 423 | `trust` |
| B5 | Audit chain + verify chip | `gap.tsx` / `modes.tsx` Trust audit (exists) | `GET /api/security/audit/intent` · `…/verify` | Chain grows on each resolve; verdict chip reflects real `/verify` result | `trust` |
| B6 | %-local locality | `modes.tsx` Trust ring + badge (exists) | `GET /api/analytics/locality` | Ring shows real split; **never fabricate** — absent data = "—", not a number | `observe` |

### Phase C — the ~37 deep write-controls (P1)

| # | Surface | Target | Endpoint(s) — real | Notes |
|---|---|---|---|---|
| C1 ✅ | Missions board/drawer (pause/resume/accept) | `gap.tsx` `MissionsPanel` (Autonomy cluster) | `GET /api/missions` · `POST /api/missions/{id}/{start\|pause\|resume\|complete\|cancel}` | **renamed** (see §1) — applied. Contextual governed-action controls per status. **Shipped PR 3.** |
| C2 ✅ | Autonomy AUTO/ASK/OFF + per-agent policies | global: `modes2.tsx` `AutonomyMode` (exists); **per-agent: `gap.tsx` `AgentAutonomyPanel`** | `GET·POST /autonomy/mode` · `GET·POST /autonomy/policy` | per-agent policy shipped PR #418; **the per-agent control surface shipped PR 5** (set/clear AUTO·ASK·OFF per agent; `default` clears) |
| C3 ◑ | Memory: recall search · remember · forget · KG edit/delete · ingest · local-docs | search/remember/docs: `modes.tsx` + `LocalDocsPanel`/`DataSpacesPanel` (exist); **KG list/delete + forget: `gap.tsx` `KgPanel`** | `/api/memory/search` · `/remember` · `POST /api/memory/decay/forget` · `GET·DELETE /api/kg/entities` · `/api/local-docs/index` | **KG entity list/delete + memory-forget-by-id shipped PR 11**; search/remember/local-docs already had surfaces |
| C4 | Cockpit streaming + feedback + voice + VLM | `cockpit.tsx` (exists) | `POST /chat/stream` · `/api/feedback` · `/api/voice/capabilities` · `/tts`(`/stream`) · `/api/vlm/describe` | streaming already partly wired |
| C5 | A2A approval inbox · Rooms | `modes3.tsx` Interop (exists) | `/api/a2a/inbox*` · `/api/rooms` | |
| C6 ✅ | Governance / posture / loop-breaker | `gap.tsx` `GovernancePanel` + `PosturePanel` (Trust); loop-breaker `LoopBreakerPanel` (exists) | `/api/security/governance` · `/api/security/posture` · `/api/security/loop-breaker`(`/reset`) | **renamed** (see §1) — applied. Scorecard (suite scores + gate) + packaged posture. **Shipped PR 6.** |
| C7 ◑ | Build: workflows · skills · sandbox · templates | **workflows: `gap.tsx` `WorkflowsPanel`**; skills/sandbox/templates: `MarketplacePanel`/`SandboxPanel`/`TemplatesPanel` (exist) | `GET /api/workflows` · `POST /api/workflows/run` · `DELETE /api/workflows/{id}` · `/api/skills/marketplace*` · `/sandbox/execute` | **workflow-runtime mgmt (list·run·delete) shipped PR 10**; skills/sandbox/templates already had panels |
| C8 ✅ | Observe: quality-threshold · arena · evals · review | `gap.tsx` `ArenaPanel` + `QualityPanel`; evals/review `EvalPanel`/`ReviewPanel` (exist) | `GET /api/arena/leaderboard` · `GET /api/quality` · `POST /api/quality/threshold` · eval/review routes | arena leaderboard + answer-quality gate (read + admin set-threshold) **shipped PR 9**; evals/review already had panels |
| C9 ✅ | Backup / export / forget-me · onboarding | **backup+export+forget: `gap.tsx` `BackupPanel`** (Admin); onboarding: `OnboardingPanel` (exists) | `GET·POST /api/admin/backup` · `POST /api/admin/backup/verify` · `POST /api/admin/export` · `POST /api/admin/forget` · onboarding route | **backup + restore-drill + export shipped PR 7; forget-me (confirm-gated) shipped PR 8** — the data-sovereignty triad is whole. (onboarding already has a panel) |
| C10 ✅ | Mesh devices / sync | `gap.tsx` `MeshPeersPanel` (Interop cluster) | `GET·POST·DELETE /api/a2a/peers` (admin) | Allowlist + one-time shared secret; list/add/remove. **Shipped PR 4.** |

### Phase D — tail (P2)

Native canvas **Neural Mesh** (`v3-mesh.jsx`) ported as a `<canvas>` component sharing the data layer
(drop the `/brain?embed=1` iframe — handover §3.5); WorldView / Argus (`v3-worldview.jsx` →
`modes_world.tsx` / `world_app.tsx`, exists); Life packs as plugins land.

---

## 3 · Translation rules (binding — from handover §3)

1. **The prototype is the contract** — pixel/IA fidelity to `docs/design/hud-v3/`, not a reinterpretation.
2. **Mock → real** — `v3-mock.jsx` exists only to demo; every "live" surface in `frontend/src` gets a
   **runtime check against the real backend** (year-one learning #3: mocks hide bugs).
3. **Hooks map 1:1** — `useResource` / `useMutation` / `useStream` → the existing loaders/SWR pattern
   in `api/loaders.ts`; keep the loading → data → stale → honest-error lifecycle and the telemetry bus
   (p50/p95 is a real guardrail).
4. **Honesty contract** — LIVE shows real data, DEMO is watermarked, OFFLINE shows nothing stale.
   **Never fabricate a %-local split or a VERIFIED state.**
5. **Neural Mesh is native** — `v3-mesh.jsx` is a `<canvas>` brain (no iframe); port as a component,
   drop `/brain?embed=1`.
6. **Auth tiers** — handle 401/403 with in-app token entry (not `window.prompt`); admin / payments /
   kill-switch-engage are admin-guarded.

---

## 4 · Per-PR definition of done

Every surface PR (B1…, C1…, D…) must:

- [ ] Match the prototype surface (IA + controls + states) — the prototype is the contract.
- [ ] Bind the **real** route(s) from the table, applying the §1 renames; no prototype shorthand leaks in.
- [ ] Implement the honest LIVE / DEMO / OFFLINE lifecycle (no seed passed off as live; no fabricated
      %-local or VERIFIED).
- [ ] Green on `tsc --noEmit`, vitest (add/extend a `frontend/src/test/*.test.tsx`), and the
      `hud-v2-build` stale-bundle guard (rebuild the served bundle).
- [ ] `tests/test_hud_v2_parity.py` stays green (all routes already map to a surface — no new
      `NOT_IN_HUD` needed).
- [ ] `docs/REVIEW_QUEUE.md` updated with what to manually test (visual/runtime can't be verified
      hermetically in CI — this is the manual-review net).

> **Known limitation (flagged).** The frontend port cannot be hermetically **runtime/visually** verified
> in this environment (no browser/screenshot). The safety net is `tsc --noEmit` + vitest + the
> stale-bundle guard + the `REVIEW_QUEUE` manual checklist. Each PR states this explicitly.

---

## 5 · Competition-inspired backlog (port targets, from handover §4)

1. **Frictionless onboarding** (already a real 4-step wizard in the prototype) → wire model-pull to
   `/api/models/local`, capabilities to kernel issuance.
2. **Local-model management** (Admin → Local Models: load/unload/set-default + pull-a-model) →
   `/api/models/local` + LM Studio.
3. **Multi-surface ambient capture** ✅ **shipped PR 13** — `CapturePanel` (Memory): opt-in stream with each item's redacted preview shown + individually deletable (`DELETE /api/capture/{id}`) + clear-all.
4. **Satellite-mic / Wyoming** (Mesh → Devices "pair a phone as a mic satellite" — make pairing real).
5. **The "felt-value" loop** — one undeniable proactive loop (morning brief + one reversible
   remediation) end-to-end; cinema mode is the shareable artifact.

---

*Generated as PR 1 of the hud-v3 port. Execute §2 one PR per surface: Phase B substrate → ~37
write-controls → P2 tail.*
